import streamlit as st
from database.db import (
    get_all_videos,
    delete_video,
    get_conn,
    insert_report,
    get_all_personalities,
)
from core.ai_process import generate_feedback

# ===== 1. 來源類型顯示對照 =====
SOURCE_LABEL = {
    "youtube_subtitle": "🎬 YT字幕",
    "youtube_whisper":  "🎬 YT語音",
    "upload":           "📂 上傳",
    "folder":           "📁 資料夾",
}

# ===== 2. 取得媒體庫（含心得數量）=====
def get_video_library_with_count():
    """
    取得所有媒體紀錄，並附帶每筆已生成的心得數量
    回傳 list of dict
    """
    conn = get_conn()
    rows = conn.execute('''
        SELECT
            v.id,
            v.source_key,
            v.source_type,
            v.title,
            v.created_at,
            COUNT(r.id) AS report_count
        FROM video_library v
        LEFT JOIN ai_reports r ON r.video_id = v.id
        GROUP BY v.id
        ORDER BY v.id DESC
    ''').fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ===== 3. 頁面主函式 =====
def show(selected_p: str, p_dict: dict):
    """
    媒體庫頁面：顯示所有已轉錄的影片/音訊，可點選生成心得
    參數：
        selected_p : 目前選擇的人格名稱
        p_dict     : {name: prompt} 人格字典
    """

    # ===== 3.1 頁面說明 =====
    st.subheader("📚 媒體庫")
    st.caption("所有已轉錄的影片與音訊，點選後可直接生成心得，不需重新轉錄。")

    # ===== 3.2 初始化 session_state =====
    for k, v in {
        "lib_selected_id":   None,   # 目前選取的 video_id
        "lib_selected_key":  "",     # 顯示用（source_key 前段）
        "lib_report_result": "",     # 生成的心得
        "lib_refined_text":  "",     # 對應的文字稿
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ===== 3.3 功能列 =====
    col_refresh, col_del, _ = st.columns([1, 1, 5])
    with col_refresh:
        if st.button("🔄 重新整理", use_container_width=True):
            st.rerun()
    with col_del:
        btn_del = st.button(
            "🗑️ 刪除選取",
            use_container_width=True,
            disabled=st.session_state["lib_selected_id"] is None
        )

    st.divider()

    # ===== 3.4 載入媒體庫 =====
    videos = get_video_library_with_count()

    if not videos:
        st.info("目前沒有任何已轉錄的媒體，請先到 YouTube 或上傳 Tab 新增。")
        return

    # ===== 3.5 資料列表 =====
    st.markdown(f"**共 {len(videos)} 筆紀錄**")

    # 表頭
    col_w = [0.8, 1.2, 4.5, 2.0, 1.0]
    hcols = st.columns(col_w)
    for col, label in zip(hcols, ["選取", "來源", "標題 / URL", "建立時間", "心得數"]):
        col.markdown(f"**{label}**")
    st.divider()

    # 資料列
    for v in videos:
        cols = st.columns(col_w)

        # ----- 選取按鈕 -----
        is_selected = st.session_state["lib_selected_id"] == v["id"]
        btn_label   = "✅" if is_selected else "⬜"
        if cols[0].button(btn_label, key=f"sel_{v['id']}"):
            if is_selected:
                # 再點一次取消選取
                st.session_state["lib_selected_id"]   = None
                st.session_state["lib_selected_key"]  = ""
                st.session_state["lib_report_result"] = ""
                st.session_state["lib_refined_text"]  = ""
            else:
                st.session_state["lib_selected_id"]   = v["id"]
                st.session_state["lib_selected_key"]  = v["source_key"]
                st.session_state["lib_report_result"] = ""
                st.session_state["lib_refined_text"]  = ""
            st.rerun()

        # ----- 來源類型 -----
        cols[1].markdown(SOURCE_LABEL.get(v["source_type"], v["source_type"]))

        # ----- 標題/URL（截短顯示）-----
        display_key = v["title"] or v["source_key"] or ""
        if len(display_key) > 60:
            display_key = display_key[:60] + "..."
        cols[2].markdown(f"`{display_key}`")

        # ----- 建立時間 -----
        cols[3].markdown(v["created_at"][:16] if v["created_at"] else "")

        # ----- 心得數 -----
        cols[4].markdown(f"📝 {v['report_count']}")

    st.divider()

    # ===== 3.6 已選取提示 =====
    selected_id = st.session_state["lib_selected_id"]

    if selected_id is None:
        st.info("⬆️ 請點選上方任一筆資料")
        return

    # 取得選取的詳細資料
    selected_video = next((v for v in videos if v["id"] == selected_id), None)
    if not selected_video:
        st.warning("找不到選取的資料，請重新整理")
        return

    display_title = selected_video["title"] or selected_video["source_key"] or f"ID:{selected_id}"
    st.success(f"已選取：{display_title[:80]}")

    # ===== 3.7 刪除處理 =====
    if btn_del:
        delete_video(selected_id)
        st.session_state["lib_selected_id"]   = None
        st.session_state["lib_report_result"] = ""
        st.session_state["lib_refined_text"]  = ""
        st.success("已刪除")
        st.rerun()

    # ===== 3.8 生成心得區 =====
    st.markdown("---")
    st.markdown("**🤖 生成心得**")

    col_p, col_btn = st.columns([3, 1])
    with col_p:
        # 人格選擇（獨立於側欄，這裡可以臨時換）
        p_options  = list(p_dict.keys())
        p_index    = p_options.index(selected_p) if selected_p in p_options else 0
        chosen_p   = st.selectbox(
            "選擇人格",
            p_options,
            index   = p_index,
            key     = f"lib_p_{selected_id}",
            label_visibility = "collapsed"
        )
    with col_btn:
        btn_gen = st.button("✍️ 生成心得", type="primary", use_container_width=True)

    # ===== 3.9 執行生成 =====
    if btn_gen:
        # 從 DB 取得 refined_text
        conn         = get_conn()
        video_row    = conn.execute(
            "SELECT refined_text FROM video_library WHERE id = ?", (selected_id,)
        ).fetchone()
        conn.close()

        refined_text = video_row["refined_text"] if video_row else ""

        if not refined_text:
            st.error("此筆資料沒有文字稿，無法生成心得。")
        else:
            p_prompt = p_dict.get(chosen_p, "你是一位務實的 IT 課長。")

            with st.spinner(f"使用人格「{chosen_p}」生成心得中..."):
                report = generate_feedback(
                    refined_text, chosen_p, p_prompt,
                    log_callback=None   # 媒體庫不顯示詳細進度
                )

            # 存入 DB
            insert_report(
                video_id = selected_id,
                p_name   = chosen_p,
                report   = report,
            )

            st.session_state["lib_report_result"] = report
            st.session_state["lib_refined_text"]  = refined_text
            st.rerun()

    # ===== 3.10 結果顯示 =====
    if st.session_state["lib_report_result"]:
        st.markdown("---")
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("**📝 文字稿**")
            st.text_area(
                label            = "refined",
                value            = st.session_state["lib_refined_text"],
                height           = 400,
                label_visibility = "collapsed",
                key              = f"lib_txt_{selected_id}"
            )
            st.download_button(
                label     = "⬇️ 下載文字稿",
                data      = st.session_state["lib_refined_text"],
                file_name = "transcript.txt",
                mime      = "text/plain",
                key       = f"lib_dl_txt_{selected_id}"
            )

        with col_right:
            st.markdown(f"**💡 心得**")
            st.text_area(
                label            = "report",
                value            = st.session_state["lib_report_result"],
                height           = 400,
                label_visibility = "collapsed",
                key              = f"lib_rep_{selected_id}"
            )
            st.download_button(
                label     = "⬇️ 下載心得",
                data      = st.session_state["lib_report_result"],
                file_name = "report.txt",
                mime      = "text/plain",
                key       = f"lib_dl_rep_{selected_id}"
            )

    # ===== 3.11 歷史心得記錄 =====
    st.markdown("---")
    st.markdown("**📚 此媒體的歷史心得**")

    conn     = get_conn()
    reports  = conn.execute('''
        SELECT id, p_name, report, created_at
        FROM ai_reports
        WHERE video_id = ?
        ORDER BY id DESC
    ''', (selected_id,)).fetchall()
    conn.close()

    if not reports:
        st.caption("尚無心得記錄")
    else:
        for r in reports:
            with st.expander(f"🕐 {r['created_at'][:16]}　｜　👤 {r['p_name']}"):
                st.markdown(r["report"])
                st.download_button(
                    label     = "⬇️ 下載",
                    data      = r["report"],
                    file_name = f"report_{r['id']}.txt",
                    mime      = "text/plain",
                    key       = f"hist_dl_{r['id']}"
                )
