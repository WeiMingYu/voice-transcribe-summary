import streamlit as st
from database.db import (
    get_scheduler_settings,
    save_scheduler_settings,
    get_all_personalities,
    get_recent_scheduler_logs,
)
from core.scheduler import (
    start_scheduler,
    stop_scheduler,
    get_scheduler_status,
)
import os

# ===== 1. 頁面主函式 =====
def show():
    """
    資料夾監控設定頁面
    排程設定存入 DB，重啟後自動恢復
    """

    st.subheader("📁 資料夾監控設定")
    st.caption("設定後系統會定期掃描指定資料夾，自動處理新的音訊檔案。")

    # ===== 2. 載入目前設定 =====
    settings     = get_scheduler_settings()
    is_enabled   = settings.get("enabled", "0") == "1"
    folder_path  = settings.get("folder_path", "")
    interval_min = int(settings.get("interval_min", "10"))
    auto_p_name  = settings.get("auto_p_name", "務實課長-俞威名")

    # ===== 3. 目前排程狀態顯示 =====
    status = get_scheduler_status()

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        if status["job_exists"]:
            st.success("🟢 排程運行中")
        else:
            st.warning("🔴 排程已停止")
    with col_s2:
        st.info(f"⏱️ 掃描間隔：{interval_min} 分鐘")
    with col_s3:
        if status["next_run"]:
            st.info(f"⏰ 下次執行：{status['next_run']}")
        else:
            st.info("⏰ 下次執行：—")

    st.divider()

    # ===== 4. 設定表單 =====
    st.markdown("**⚙️ 排程設定**")

    # ----- 4.1 資料夾路徑 -----
    new_folder = st.text_input(
        "監控資料夾路徑",
        value       = folder_path,
        placeholder = "例：C:/AI_Input/Voice_Inbox",
        help        = "請輸入完整的絕對路徑，資料夾必須存在"
    )

    # 路徑存在性即時提示
    if new_folder:
        if os.path.exists(new_folder):
            st.success(f"✅ 資料夾存在，目前有 {len(os.listdir(new_folder))} 個項目")
        else:
            st.error("❌ 資料夾不存在，請確認路徑")

    # ----- 4.2 掃描間隔 -----
    new_interval = st.slider(
        "掃描間隔（分鐘）",
        min_value = 1,
        max_value = 60,
        value     = interval_min,
        step      = 1,
        help      = "建議：客服語音用 5 分鐘，一般影片用 15～30 分鐘"
    )

    # ----- 4.3 自動使用的人格 -----
    p_dict    = get_all_personalities()
    p_options = list(p_dict.keys())
    p_index   = p_options.index(auto_p_name) if auto_p_name in p_options else 0

    new_p_name = st.selectbox(
        "自動套用人格",
        options = p_options,
        index   = p_index,
        help    = "排程自動處理時使用的人格"
    )

    # ----- 4.4 啟用開關 -----
    new_enabled = st.toggle(
        "啟用自動掃描",
        value = is_enabled,
        help  = "關閉後排程停止，設定仍會保留"
    )

    st.divider()

    # ===== 5. 儲存與套用按鈕 =====
    col_save, col_scan = st.columns(2)

    with col_save:
        if st.button("💾 儲存設定", use_container_width=True, type="primary"):

            # 路徑驗證
            if new_enabled and not os.path.exists(new_folder):
                st.error("啟用排程前請先確認資料夾路徑存在！")
                st.stop()

            # 儲存到 DB
            save_scheduler_settings(
                enabled      = new_enabled,
                folder_path  = new_folder,
                interval_min = new_interval,
                auto_p_name  = new_p_name,
            )

            # 即時套用排程
            if new_enabled:
                start_scheduler(new_interval)
                st.success(f"✅ 排程已啟動，每 {new_interval} 分鐘掃描一次")
            else:
                stop_scheduler()
                st.warning("⏹️ 排程已停止")

            st.rerun()

    with col_scan:
        # 手動立即掃描按鈕
        if st.button("🔍 立即掃描一次", use_container_width=True):
            if not new_folder or not os.path.exists(new_folder):
                st.error("請先設定有效的資料夾路徑")
            else:
                with st.spinner("掃描中..."):
                    # 直接呼叫掃描邏輯
                    from core.scheduler import _scan_job
                    _scan_job()
                st.success("掃描完成！請查看下方記錄")
                st.rerun()

    # ===== 6. 掃描記錄 =====
    st.divider()
    st.markdown("**📋 最近掃描記錄**")

    logs = get_recent_scheduler_logs(limit=20)

    if not logs:
        st.caption("尚無掃描記錄")
    else:
        for log in logs:
            # 根據狀態選擇顏色
            icon = "✅" if log["status"] == "success" else "❌"

            with st.expander(
                f"{icon} {log['created_at']}　｜　"
                f"發現 {log['file_found']} 個　新增 {log['file_new']} 個　"
                f"跳過 {log['file_skip']} 個"
            ):
                st.caption(f"📁 路徑：{log['scan_path']}")
                if log["message"]:
                    if log["status"] == "error":
                        st.error(log["message"])
                    else:
                        st.success(log["message"])
