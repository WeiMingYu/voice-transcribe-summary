# 語音轉錄與摘要系統 開發記錄

**日期：** 2026-04-19
**開發者：** 俞威名（WeiMing）
**專案路徑：** `<專案目錄>/`
**啟動指令：** `python -m streamlit run app.py`

---

## 一、專案目的

將 v4 單檔小程式升級為模組化專案，解決以下痛點：

| v4 問題 | v5 解法 |
|--------|--------|
| 同一影片換人格就重新轉錄 | 一對多資料庫設計，refined_text 快取 |
| 所有邏輯塞在單一檔案 | 模組化分層架構 |
| 長文超過 context 直接截斷 | Chunking 分段 + 摘要合併 |
| 只支援 YouTube URL | 新增手動上傳、資料夾排程監控 |
| 排程設定寫死 | 設定存 DB，介面可調，重啟自動恢復 |

---

## 二、專案結構

```
v5/
├── app.py                  # 主程式入口，側欄人格管理
├── requirements.txt        # 套件清單
├── reports.db              # SQLite 資料庫（自動建立）
├── database/
│   ├── __init__.py
│   └── db.py               # 所有 DB 操作集中管理
├── core/
│   ├── __init__.py
│   ├── transcribe.py       # Whisper 轉錄、yt-dlp 字幕、MD5
│   ├── ai_process.py       # Refine + Chunking + Feedback
│   └── scheduler.py        # APScheduler 排程管理
└── pages/
    ├── __init__.py
    ├── tab_youtube.py      # YouTube URL Tab
    ├── tab_upload.py       # 手動上傳音訊 Tab
    └── tab_folder.py       # 資料夾監控設定 Tab
```

---

## 三、資料庫設計（reports.db）

### 一對多架構

```
video_library（一）→ ai_reports（多）
同一來源只轉錄一次，可多人格生成心得
```

### 資料表清單

| 資料表 | 用途 |
|--------|------|
| `video_library` | 媒體主表，source_key 為唯一鍵（URL 或 MD5） |
| `ai_reports` | 心得表，FK 參考 video_library |
| `personalities` | 人格設定，name 為 PK |
| `scheduler_log` | 排程掃描記錄，除錯用 |
| `scheduler_settings` | 排程設定，key-value 結構 |

### 關鍵欄位設計

```sql
-- video_library
source_key  TEXT UNIQUE  -- YouTube URL 或檔案 MD5
source_type TEXT         -- youtube_subtitle / youtube_whisper / upload / folder
refined_text TEXT        -- 快取用，換人格不重新轉錄

-- scheduler_settings（key-value）
enabled      -- 0 或 1
folder_path  -- 監控資料夾絕對路徑
interval_min -- 掃描間隔（分鐘）
auto_p_name  -- 自動套用人格名稱
```

---

## 四、AI 處理流程

### 雙工序設計

```
原始逐字稿（raw_text）
    ↓
[工序 1] Refine（校對）
    Temperature: 0.2（保守）
    修正語音辨識錯字，不改原意
    ↓
[工序 2] Feedback（心得）
    Temperature: 0.8（創意）
    根據人格 Prompt 生成群組心得
```

### Chunking 分段策略（7B 模型專用）

```
CHUNK_SIZE    = 1500 字  # 每段上限
CHUNK_OVERLAP = 100 字   # 段落重疊，避免語意斷裂

短文（< 1500字）→ 直接處理
長文（≥ 1500字）→ 分段 Refine → 分段摘要 → 合併總摘要 → Feedback
```

### 快取命中邏輯

```
輸入 URL 或檔案
    ↓
查 video_library WHERE source_key = ?
    ├── 有 refined_text → 直接跳 Feedback（節省幾分鐘）
    └── 無紀錄 → 完整流程：轉錄 → Refine → Feedback → 存 DB
```

---

## 五、技術堆疊

| 類別 | 技術 | 說明 |
|------|------|------|
| 前端 | Streamlit | 三 Tab 介面 |
| 資料庫 | SQLite | reports.db，conn.row_factory = sqlite3.Row |
| 語音轉文字 | openai-whisper small | GPU 優先，CPU 備援 |
| 字幕下載 | yt-dlp | 先抓繁體，再試簡體，失敗才啟動 Whisper |
| AI 推論 | LM Studio + Qwen2.5-7B | Port 1234，OpenAI 相容 API |
| 排程 | APScheduler BackgroundScheduler | 單例模式，重啟自動恢復 |

---

## 六、環境設定

### Python 版本

```bash
# 使用 Python 3.12（Whisper 相依性要求）
py -3.12 -m venv venv
venv\Scripts\activate
```

### 套件安裝

```bash
# CUDA 版 torch（必須從官方，不走清華鏡像）
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 其他套件（走清華鏡像）
pip install openai-whisper openai streamlit apscheduler -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### GPU 確認

```python
import torch
print(torch.__version__)          # 應為 2.5.1+cu121
print(torch.cuda.is_available())  # 應為 True
```

### 硬體配置

| 項目 | 規格 |
|------|------|
| GPU | RTX 3060 8GB |
| VRAM 使用狀況 | LM Studio 約佔 6.2GB，Whisper small 約需 1GB |
| 建議作法 | 跑 Whisper 前先在 LM Studio 卸載模型 |

---

## 七、LM Studio 設定

```
模型：Qwen2.5-7B-Instruct（Q4_K_M）
Port：1234
GPU Offload：35
Context Length：8192
Flash Attention：on
max_tokens：2000
```

---

## 八、踩過的坑

### 坑 1：torch CPU 版問題
- **症狀：** Whisper 顯示 `cpu`，GPU 沒用到
- **原因：** 預設 pip 裝的是 `torch+cpu` 版
- **解法：** 重裝 `--index-url https://download.pytorch.org/whl/cu121`

### 坑 2：Python 版本衝突
- **症狀：** Whisper 安裝或執行報錯
- **原因：** Python 3.14 對某些 Whisper 相依套件不相容
- **解法：** 用 `py -3.12 -m venv venv` 建立 3.12 專用環境

### 坑 3：Streamlit + APScheduler 衝突
- **症狀：** 排程在 Streamlit rerun 時重複建立
- **解法：** 排程器用全域單例（`_scheduler` 全域變數），`session_state["initialized"]` 確保只初始化一次

### 坑 4：Qwen 輸出簡體字
- **症狀：** 心得偶爾出現 `动、传、这` 等簡體字
- **解法：** Feedback prompt 加入明確的繁體規範與常見錯誤對照表

### 坑 5：長文 context 截斷
- **症狀：** 30 分鐘影片後半段內容 AI 沒看到
- **原因：** v4 直接取前 3000 字丟進去
- **解法：** v5 Chunking 分段處理，確保全文都進入 AI

---

## 九、功能完成度

| 功能 | 狀態 | 備註 |
|------|------|------|
| YouTube 字幕下載 | ✅ | 繁體→簡體備援 |
| Whisper GPU 轉錄 | ✅ | CUDA 確認 |
| Refine 校對 | ✅ | 含 Chunking |
| 長文摘要合併 | ✅ | 分段摘要→總摘要 |
| 人格心得生成 | ✅ | 繁體強制規範 |
| 快取機制 | ✅ | MD5 / URL 查重 |
| 手動上傳音訊 | ✅ | tempfile 處理 |
| 資料夾排程監控 | ✅ | APScheduler |
| 排程設定介面 | ✅ | 存 DB，重啟恢復 |
| 人格管理介面 | ✅ | 新增/編輯/刪除 |
| 歷史心得側欄 | ✅ | 最近 10 筆 |
| 掃描記錄介面 | ✅ | 最近 20 筆 |

---

## 十、待擴充（未來計畫）

| 功能 | 說明 |
|------|------|
| yt-dlp 抓影片標題 | 目前 title 欄位留空，未來補上 |
| RAG 整合 | ChromaDB 檢索產品手冊，客服語音自動對應 SOP |
| Line Notify 通知 | 排程處理完成後推播通知主管 |
| 多模態 Vision | 擷取影片截圖分析投影片內容 |
| Dual GPU 隔離 | 未來升級硬體後，LLM 與 Whisper 分卡執行 |
| 情感分數自動判定 | ai_reports.sentiment 欄位目前保留未用 |
