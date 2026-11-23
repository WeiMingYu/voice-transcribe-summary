import streamlit as st
from database.db import (
    init_db,
    get_all_personalities,
    upsert_personality,
    delete_personality,
    get_recent_reports,
    delete_report,
)
from core.scheduler import init_scheduler_from_db

# ===== 1. 頁面基本設定 =====
st.set_page_config(
    page_title = "語音轉錄與摘要系統",
    page_icon  = "🎙️",
    layout     = "wide",
)

# ===== 2. 系統初始化（只在第一次執行）=====
# init_db 建立所有資料表與預設資料
# init_scheduler_from_db 讀取 DB 設定，自動恢復排程
if "initialized" not in st.session_state:
    init_db()
    init_scheduler_from_db()
    st.session_state["initialized"] = True

# ===== 2-1. 隱藏 Streamlit 預設選單 =====
st.markdown('''
<style>
[data-testid="stSidebarNavItems"]      { display: none; }
[data-testid="stSidebarNavSeparator"] { display: none; }
</style>
''', unsafe_allow_html=True)    

# ===== 3. 側欄：人格管理 =====
with st.sidebar:
    st.header("👤 人格設定")

    # ----- 3.1 載入所有人格 -----
    p_dict = get_all_personalities()

    # ----- 3.2 切換人格 -----
    selected_p = st.selectbox(
        "目前使用人格",
        list(p_dict.keys()),
        key="selected_p"
    )
    current_prompt = p_dict.get(selected_p, "")

    # ----- 3.3 切換人格時重設 text_area -----
    # 偵測人格是否剛切換，若是則清掉舊的 edited_prompt，強制顯示新人格的 Prompt
    if st.session_state.get("last_selected_p") != selected_p:
        st.session_state["last_selected_p"] = selected_p
        st.session_state["edited_prompt"]   = current_prompt

    # ----- 3.4 Prompt 預覽與編輯 -----
    edited_prompt = st.text_area(
        "人格 Prompt（可直接修改）",
        value  = current_prompt,
        height = 120,
        key    = "edited_prompt"
    )

    col_save, col_del = st.columns(2)

    with col_save:
        if st.button("💾 儲存", use_container_width=True):
            upsert_personality(selected_p, edited_prompt)
            st.success("已儲存")
            st.rerun()

    with col_del:
        if st.button("🗑️ 刪除", use_container_width=True):
            ok = delete_personality(selected_p)
            if ok:
                st.success("已刪除")
                st.rerun()
            else:
                st.warning("預設人格不可刪除")

    # ----- 3.4 新增人格 -----
    st.divider()
    st.markdown("**➕ 新增人格**")
    new_name   = st.text_input("人格名稱", key="new_p_name")
    new_prompt = st.text_area("人格 Prompt", height=80, key="new_p_prompt")

    if st.button("新增", use_container_width=True):
        if new_name and new_prompt:
            upsert_personality(new_name, new_prompt)
            st.success(f"已新增：{new_name}")
            st.rerun()
        else:
            st.warning("名稱和 Prompt 都不能空白")

    # ===== 4. 側欄：歷史紀錄 =====
    st.divider()
    st.header("📚 最近心得")

    history = get_recent_reports(limit=10)

    if not history:
        st.caption("尚無紀錄")
    else:
        for row in history:
            label = f"{'🎬' if 'youtube' in (row['source_type'] or '') else '🎙️'} {row['created_at'][:10]}｜{row['p_name']}"
            with st.expander(label):
                # 標題（若有）
                if row["title"]:
                    st.caption(f"📌 {row['title']}")
                st.markdown(row["report"])
                if st.button("🗑️ 刪除", key=f"del_r_{row['id']}"):
                    delete_report(row["id"])
                    st.rerun()

# ===== 5. 主內容區：Tab 切換 =====
st.title("🎙️ 語音轉錄與摘要系統")

tab_yt, tab_upload, tab_folder, tab_library = st.tabs([
    "🎬 YouTube",
    "📂 上傳音訊",
    "📁 資料夾監控",
    "📚 媒體庫",
])

# ----- 5.1 YouTube Tab -----
with tab_yt:
    from pages.tab_youtube import show as show_youtube
    show_youtube(selected_p, p_dict)

# ----- 5.2 上傳音訊 Tab -----
with tab_upload:
    from pages.tab_upload import show as show_upload
    show_upload(selected_p, p_dict)

# ----- 5.3 資料夾監控 Tab -----
with tab_folder:
    from pages.tab_folder import show as show_folder
    show_folder()

# ----- 5.4 媒體庫 Tab -----
with tab_library:
    from pages.tab_library import show as show_library
    show_library(selected_p, p_dict)
