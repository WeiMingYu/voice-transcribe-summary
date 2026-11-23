from openai import OpenAI

# ===== 1. LM Studio 連線設定 =====
LMS_BASE_URL = "http://localhost:1234/v1"
LMS_API_KEY  = "lm-studio"
LMS_MODEL    = "local-model"

# Refine 工序：保守，不改原意
REFINE_TEMPERATURE   = 0.2
# Feedback 工序：創意，風格化
FEEDBACK_TEMPERATURE = 0.8

# ===== 2. Chunking 設定 =====
# 7B 模型 context 約 8192 token，中文約 1 字 = 1.5 token
# 安全起見每段控制在 1500 字，保留空間給 prompt
CHUNK_SIZE    = 1500   # 每段字數
CHUNK_OVERLAP = 100    # 段落重疊字數（避免語意斷裂）

# ===== 3. 取得 LM Studio Client =====
def get_client() -> OpenAI:
    """回傳 LM Studio OpenAI 相容 Client"""
    return OpenAI(base_url=LMS_BASE_URL, api_key=LMS_API_KEY)

# ===== 4. 文字分段（Chunking）=====
def split_chunks(text: str, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list:
    """
    將長文字切成多段，段落間有重疊避免語意斷裂
    回傳 list of str
    """
    chunks = []
    start  = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        # 下一段從（end - overlap）開始，製造重疊
        start = end - overlap if end < length else length

    return chunks

# ===== 5. 第一道工序：Refine（校對單段）=====
def refine_chunk(client: OpenAI, chunk: str) -> str:
    """
    對單一段落進行語音辨識校對
    修正錯字、理順邏輯，不改原意
    """
    prompt = (
        "你是專業的 AI 技術速記校對員。\n"
        "請修正以下逐字稿中的語音辨識錯誤（例如：同音異字、技術術語辨識錯誤），"
        "並理順語句邏輯。\n"
        "規則：\n"
        "1. 只輸出修正後的純文本，不加任何說明。\n"
        "2. 不得增加或刪減原文的核心意思。\n"
        "3. 使用繁體中文。\n\n"
        f"原文：\n{chunk}"
    )
    try:
        response = client.chat.completions.create(
            model=LMS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=REFINE_TEMPERATURE,
            max_tokens=2000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # 失敗則回傳原段，不中斷整體流程
        return chunk

# ===== 6. 第一道工序：Refine（完整流程，含 Chunking）=====
def refine_transcript(raw_text: str, log_callback=None) -> str:
    """
    完整 Refine 流程：
    - 短文（< CHUNK_SIZE）：直接校對
    - 長文（>= CHUNK_SIZE）：分段校對後合併
    回傳校對後的完整文字
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    client = get_client()

    # ----- 6.1 短文直接處理 -----
    if len(raw_text) < CHUNK_SIZE:
        log("📝 文字較短，直接校對...")
        return refine_chunk(client, raw_text)

    # ----- 6.2 長文分段處理 -----
    chunks = split_chunks(raw_text)
    total  = len(chunks)
    log(f"📄 文字較長，分 {total} 段校對...")

    refined_chunks = []
    for i, chunk in enumerate(chunks, 1):
        log(f"   校對第 {i}/{total} 段...")
        refined_chunks.append(refine_chunk(client, chunk))

    return "\n".join(refined_chunks)

# ===== 7. 第二道工序：摘要合併（長文專用）=====
def summarize_chunks(client: OpenAI, refined_text: str, log_callback=None) -> str:
    """
    針對超長的校對文字，先分段摘要再合併成一份總摘要
    避免 7B 模型在生成心得時遺失長文細節
    僅在 refined_text > CHUNK_SIZE 時才觸發
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    # 短文不需要摘要
    if len(refined_text) < CHUNK_SIZE:
        return refined_text

    chunks = split_chunks(refined_text)
    total  = len(chunks)
    log(f"🗂️ 長文摘要：分 {total} 段提取重點...")

    summaries = []
    for i, chunk in enumerate(chunks, 1):
        log(f"   摘要第 {i}/{total} 段...")
        prompt = (
            "請用繁體中文，條列出以下段落的 3～5 個核心重點。\n"
            "只輸出重點清單，不加說明。\n\n"
            f"段落內容：\n{chunk}"
        )
        try:
            response = client.chat.completions.create(
                model=LMS_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800
            )
            summaries.append(response.choices[0].message.content.strip())
        except Exception:
            summaries.append(chunk[:300])  # 失敗則取前 300 字

    # 合併所有段落摘要
    combined = "\n\n".join(summaries)
    log("🔗 合併所有段落摘要...")

    # 最後再做一次總摘要
    final_prompt = (
        "以下是一部影片各段落的重點摘要，請整合成一份完整的影片重點總結。\n"
        "使用繁體中文，條列格式，約 300～500 字。\n\n"
        f"{combined}"
    )
    try:
        response = client.chat.completions.create(
            model=LMS_MODEL,
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.3,
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return combined

# ===== 8. 第二道工序：Feedback（生成心得）=====
def generate_feedback(refined_text: str, p_name: str, p_prompt: str,
                       log_callback=None) -> str:
    """
    根據人格 Prompt 生成心得回覆
    長文會先做摘要再生成，確保 7B 模型抓到完整內容
    回傳生成的心得字串
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    client = get_client()

    # ----- 8.1 長文先摘要 -----
    if len(refined_text) >= CHUNK_SIZE:
        log("📋 長文偵測，先進行分段摘要...")
        context_text = summarize_chunks(client, refined_text, log_callback)
    else:
        context_text = refined_text

    # ----- 8.2 生成心得 -----
    log(f"✍️ 使用人格「{p_name}」生成心得...")

    system_prompt = p_prompt
    user_prompt   = (
        f"請閱讀以下影片重點，以你的身份撰寫一份心得回覆，準備發送到 130 人的工作群組。\n\n"
        f"撰寫規則：\n"
        f"1. 開場自然、口語但禮貌。\n"
        f"2. 連結「物料管理、工作效率、生產管理 或 倉庫行政」的實務應用。\n"
        f"3. 長度約 400～600 字，不要使用摘要格式。\n"
        f"4. 全程使用繁體中文，嚴禁出現簡體字。\n"
        f"   常見錯誤對照：动→動、传→傳、这→這、来→來、时→時、说→說、问→問、为→為。\n"
        f"5. 結尾要有一個具體的問題讓同事可以回應。\n\n"
        f"影片重點：\n{context_text}"
    )

    try:
        response = client.chat.completions.create(
            model=LMS_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            temperature=FEEDBACK_TEMPERATURE,
            max_tokens=2000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 產出失敗：{e}"

# ===== 9. 主入口：完整雙工序處理 =====
def run_full_pipeline(raw_text: str, p_name: str, p_prompt: str,
                      log_callback=None) -> dict:
    """
    完整雙工序流程：
        raw_text → Refine → Summarize（長文）→ Feedback
    回傳 dict：
        {
            "refined_text": "...",
            "report": "...",
            "success": True/False,
            "error": ""
        }
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    result = {
        "refined_text": "",
        "report":       "",
        "success":      False,
        "error":        ""
    }

    try:
        # ----- 工序 1：Refine -----
        log("🧠 [工序 1/2] 文字校對中...")
        refined = refine_transcript(raw_text, log_callback)
        result["refined_text"] = refined

        # ----- 工序 2：Feedback -----
        log("✍️ [工序 2/2] 生成心得中...")
        report = generate_feedback(refined, p_name, p_prompt, log_callback)
        result["report"]  = report
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)

    return result
