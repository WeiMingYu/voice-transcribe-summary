import streamlit as st
import os
import tempfile
from database.db import (
    get_video_by_key,
    insert_video,
    insert_report,
    get_reports_by_video,
)
from core.transcribe import process_audio_file, calc_md5, SUPPORTED_AUDIO_EXT
from core.ai_process import run_full_pipeline, generate_feedback

# ===== 1. 頁面主函式 =====
def show(selected_p: str, p_dict: dict):
    """
    手動上傳音訊檔頁面
    參數：
        selected_p : 目前選擇的人格名稱
        p_dict     : {name: prompt} 人格字典（由 app.py 側欄傳入）
    """

    st.subheader("📂 上傳音訊檔")
    st.caption(
        f"支援格式：{', '.join(SUPPORTED_AUDIO_EXT)}｜"
        "系統會計算 MD5，同一個檔案不會重複轉錄。"
    )

    # ===== 2. 檔案上傳區 =====
    uploaded_file = st.file_uploader(
        "選擇音訊檔案",
        type=["mp3", "wav", "m4a", "mp4", "aac", "flac"],
        label_visibility="collapsed"
    )

    # ===== 3. 上傳後預覽與快取檢查 =====
    if uploaded_file:

        col_info, col_btn = st.columns([4, 1])

        with col_info:
            st.markdown(f"**📄 檔案：** `{uploaded_file.name}`")
            size_mb = uploaded_file.size / 1024 / 1024
            st.markdown(f"**📦 大小：** `{size_mb:.1f} MB`")

        with col_btn:
            btn_start = st.button(
                "🚀 開始分析",
                type    = "primary",
                use_container_width = True
            )

        st.divider()

        # ===== 4. 開始分析流程 =====
        if btn_start:
            p_prompt = p_dict.get(selected_p, "你是一位務實的 IT 課長。")

            with st.status("⚙️ 自動化流程執行中...", expanded=True) as status:

                # ----- 4.1 儲存到暫存檔，計算 MD5 -----
                st.write("🔑 計算檔案 MD5...")

                # 用 tempfile 建立暫存檔，確保副檔名正確（Whisper 需要）
                suffix = os.path.splitext(uploaded_file.name)[1]
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix
                ) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    md5 = calc_md5(tmp_path)

                    # ----- 4.2 快取檢查 -----
                    existing = get_video_by_key(md5)

                    if existing and existing["refined_text"]:
                        # 有快取：直接生成心得
                        st.write("⚡ 快取命中，跳過轉錄步驟")
                        refined_text = existing["refined_text"]
                        video_id     = existing["id"]

                        st.write(f"✍️ 使用人格「{selected_p}」生成心得...")
                        report = generate_feedback(
                            refined_text, selected_p, p_prompt,
                            log_callback=st.write
                        )

                    else:
                        # 無快取：完整流程
                        # ----- 4.3 Whisper 轉錄 -----
                        result = process_audio_file(
                            tmp_path,
                            log_callback=st.write
                        )

                        if not result["success"]:
                            status.update(label="❌ 轉錄失敗", state="error")
                            st.error(f"錯誤原因：{result['error']}")
                            st.stop()

                        # ----- 4.4 AI 雙工序 -----
                        ai_result = run_full_pipeline(
                            result["raw_text"], selected_p, p_prompt,
                            log_callback=st.write
                        )

                        refined_text = ai_result["refined_text"]
                        report       = ai_result["report"]

                        # ----- 4.5 存入資料庫 -----
                        st.write("💾 儲存結果至資料庫...")
                        video_id = insert_video(
                            source_key   = md5,
                            source_type  = "upload",
                            title        = uploaded_file.name,
                            raw_text     = result["raw_text"],
                            refined_text = refined_text,
                        )
                        insert_report(
                            video_id = video_id,
                            p_name   = selected_p,
                            report   = report,
                        )

                    status.update(label="✅ 處理完成！", state="complete")

                finally:
                    # ----- 4.6 清理暫存檔（不論成功失敗都要刪）-----
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

            # ===== 5. 結果顯示 =====
            st.subheader("📊 分析結果")
            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("**📝 校對後文字稿**")
                st.text_area(
                    label            = "refined_text",
                    value            = refined_text,
                    height           = 450,
                    label_visibility = "collapsed"
                )
                st.download_button(
                    label     = "⬇️ 下載文字稿",
                    data      = refined_text,
                    file_name = f"{uploaded_file.name}_transcript.txt",
                    mime      = "text/plain"
                )

            with col_right:
                st.markdown(f"**💡 {selected_p} 的心得**")
                st.text_area(
                    label            = "report",
                    value            = report,
                    height           = 450,
                    label_visibility = "collapsed"
                )
                st.download_button(
                    label     = "⬇️ 下載心得",
                    data      = report,
                    file_name = f"{uploaded_file.name}_report.txt",
                    mime      = "text/plain"
                )

            # ===== 6. 同檔案歷史心得 =====
            st.divider()
            st.markdown("**📚 此檔案的歷史心得紀錄**")
            history = get_reports_by_video(video_id)

            if len(history) <= 1:
                st.caption("目前只有這一筆，換個人格再生成看看！")
            else:
                for row in history:
                    with st.expander(
                        f"🕐 {row['created_at']}　｜　👤 {row['p_name']}"
                    ):
                        st.markdown(row["report"])
