import streamlit as st
from database.db import (
    get_video_by_key,
    insert_video,
    insert_report,
    get_reports_by_video,
    get_all_personalities,
)
from core.transcribe import process_youtube
from core.ai_process import run_full_pipeline

# ===== 1. 頁面說明 =====
def show(selected_p: str, p_dict: dict):
    """
    YouTube URL 輸入頁面
    參數：
        selected_p : 目前選擇的人格名稱
        p_dict     : {name: prompt} 人格字典（由 app.py 側欄傳入）
    """

    st.subheader("🎬 YouTube 影片分析")
    st.caption("輸入 YouTube 網址，自動取得逐字稿並生成心得。有字幕優先使用字幕，無字幕自動啟動 Whisper 轉錄。")

    # ===== 2. 網址輸入列 =====
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        url = st.text_input(
            "YouTube 網址",
            placeholder="https://www.youtube.com/watch?v=...",
            label_visibility="collapsed"
        )
    with col_btn:
        btn_start = st.button("🚀 開始分析", type="primary", use_container_width=True)

    # ===== 3. 快取提示（已處理過的影片）=====
    if url:
        existing = get_video_by_key(url)
        if existing:
            st.info(
                f"✅ 此影片已有轉錄紀錄（{existing['created_at']}），"
                f"來源：{existing['source_type']}。將直接使用快取文字稿生成新心得。"
            )

    st.divider()

    # ===== 4. 開始分析流程 =====
    if btn_start:

        # ----- 4.1 基本驗證 -----
        if not url:
            st.warning("請先輸入 YouTube 網址！")
            st.stop()

        if not url.startswith("http"):
            st.warning("網址格式不正確，請輸入完整的 YouTube 連結。")
            st.stop()

        p_prompt = p_dict.get(selected_p, "你是一位務實的 IT 課長。")

        with st.status("⚙️ 自動化流程執行中...", expanded=True) as status:

            # ----- 4.2 檢查快取 -----
            existing = get_video_by_key(url)

            if existing and existing["refined_text"]:
                # 有快取：直接跳過轉錄
                st.write("⚡ 快取命中，跳過轉錄步驟")
                refined_text = existing["refined_text"]
                video_id     = existing["id"]
                source_type  = existing["source_type"]

                # 直接跑 Feedback（不重複 Refine）
                st.write(f"✍️ 使用人格「{selected_p}」生成心得...")
                from core.ai_process import generate_feedback
                report = generate_feedback(
                    refined_text, selected_p, p_prompt,
                    log_callback=st.write
                )
                refined_for_display = refined_text

            else:
                # 無快取：完整流程
                # ----- 4.3 取得逐字稿 -----
                transcribe_result = process_youtube(url, log_callback=st.write)

                if not transcribe_result["success"]:
                    status.update(label="❌ 轉錄失敗", state="error")
                    st.error(f"錯誤原因：{transcribe_result['error']}")
                    st.stop()

                raw_text    = transcribe_result["raw_text"]
                source_type = transcribe_result["source_type"]

                # ----- 4.4 AI 雙工序 -----
                ai_result = run_full_pipeline(
                    raw_text, selected_p, p_prompt,
                    log_callback=st.write
                )

                refined_for_display = ai_result["refined_text"]
                report              = ai_result["report"]

                # ----- 4.5 存入資料庫 -----
                st.write("💾 儲存結果至資料庫...")
                if existing:
                    # 已有主表紀錄但無 refined_text（罕見情況）
                    video_id = existing["id"]
                else:
                    video_id = insert_video(
                        source_key   = url,
                        source_type  = source_type,
                        title        = "",          # 未來可用 yt-dlp 抓標題
                        raw_text     = raw_text,
                        refined_text = ai_result["refined_text"],
                    )

                insert_report(
                    video_id = video_id,
                    p_name   = selected_p,
                    report   = report,
                )

            status.update(label="✅ 處理完成！", state="complete")

        # ===== 5. 結果顯示 =====
        st.subheader("📊 分析結果")
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("**📝 校對後文字稿**")
            st.text_area(
                label        = "refined_text",
                value        = refined_for_display,
                height       = 450,
                label_visibility = "collapsed"
            )
            # 複製按鈕
            st.download_button(
                label    = "⬇️ 下載文字稿",
                data     = refined_for_display,
                file_name= "transcript.txt",
                mime     = "text/plain"
            )

        with col_right:
            st.markdown(f"**💡 {selected_p} 的心得**")
            st.text_area(
                label    = "report",
                value    = report,
                height   = 450,
                label_visibility = "collapsed"
            )
            st.download_button(
                label    = "⬇️ 下載心得",
                data     = report,
                file_name= "report.txt",
                mime     = "text/plain"
            )

        # ===== 6. 同影片歷史心得 =====
        st.divider()
        st.markdown("**📚 此影片的歷史心得紀錄**")
        history = get_reports_by_video(video_id)

        if len(history) <= 1:
            st.caption("目前只有這一筆，換個人格再生成看看！")
        else:
            for row in history:
                with st.expander(f"🕐 {row['created_at']}　｜　👤 {row['p_name']}"):
                    st.markdown(row["report"])
