import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

from database.db import (
    get_scheduler_settings,
    get_video_by_key,
    insert_video,
    insert_report,
    insert_scheduler_log,
)
from core.transcribe import scan_folder, process_audio_file, calc_md5
from core.ai_process import run_full_pipeline

# ===== 1. 排程器單例 =====
# APScheduler 用全域變數管理，避免 Streamlit rerun 重複建立
_scheduler: BackgroundScheduler = None

# ===== 2. 取得或建立排程器 =====
def get_scheduler() -> BackgroundScheduler:
    """取得全域排程器（若不存在則建立）"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Taipei")
        _scheduler.start()
    return _scheduler

# ===== 3. 核心掃描任務（排程執行）=====
def _scan_job():
    """
    排程觸發的掃描任務
    1. 從 DB 讀取設定
    2. 掃描資料夾
    3. 比對 MD5，過濾已處理的檔案
    4. 新檔案 → 轉錄 → AI 雙工序 → 存檔
    5. 寫入排程記錄
    """
    settings    = get_scheduler_settings()
    folder_path = settings.get("folder_path", "")
    auto_p_name = settings.get("auto_p_name", "務實課長-俞威名")

    # ----- 3.1 取得人格 Prompt -----
    # 避免循環 import，直接查 DB
    import sqlite3
    from database.db import DB_PATH, get_conn
    conn      = get_conn()
    p_row     = conn.execute(
        "SELECT prompt FROM personalities WHERE name = ?", (auto_p_name,)
    ).fetchone()
    conn.close()
    p_prompt  = p_row["prompt"] if p_row else "你是一位務實的 IT 課長。"

    # ----- 3.2 掃描資料夾 -----
    files      = scan_folder(folder_path)
    found      = len(files)
    new_count  = 0
    skip_count = 0

    if found == 0:
        insert_scheduler_log(folder_path, 0, 0, 0, "success", "資料夾無新檔案")
        return

    for filepath in files:
        try:
            # ----- 3.3 計算 MD5 比對是否已處理 -----
            md5 = calc_md5(filepath)
            existing = get_video_by_key(md5)

            if existing:
                skip_count += 1
                continue

            # ----- 3.4 新檔案：轉錄 -----
            result = process_audio_file(filepath)
            if not result["success"]:
                insert_scheduler_log(
                    folder_path, found, new_count, skip_count,
                    "error", f"{filepath}：{result['error']}"
                )
                continue

            # ----- 3.5 AI 雙工序 -----
            ai_result = run_full_pipeline(
                result["raw_text"], auto_p_name, p_prompt
            )

            # ----- 3.6 存入資料庫 -----
            video_id = insert_video(
                source_key   = md5,
                source_type  = "folder",
                title        = result["title"],
                raw_text     = result["raw_text"],
                refined_text = ai_result["refined_text"],
            )
            insert_report(
                video_id = video_id,
                p_name   = auto_p_name,
                report   = ai_result["report"],
            )
            new_count += 1

        except Exception as e:
            insert_scheduler_log(
                folder_path, found, new_count, skip_count,
                "error", f"{filepath} 例外：{str(e)}"
            )

    # ----- 3.7 寫入本次掃描記錄 -----
    insert_scheduler_log(
        folder_path, found, new_count, skip_count,
        "success",
        f"完成：新增 {new_count} 筆，跳過 {skip_count} 筆"
    )

# ===== 4. 啟動排程 =====
def start_scheduler(interval_min: int):
    """
    啟動（或重設）資料夾掃描排程
    每次呼叫前會先移除舊的 job，確保間隔設定即時生效
    """
    scheduler = get_scheduler()

    # 移除舊的掃描 job（如果存在）
    if scheduler.get_job("folder_scan"):
        scheduler.remove_job("folder_scan")

    scheduler.add_job(
        func     = _scan_job,
        trigger  = IntervalTrigger(minutes=interval_min),
        id       = "folder_scan",
        name     = "資料夾掃描",
        replace_existing = True,
        max_instances    = 1,       # 避免上一次還沒跑完就重複觸發
    )

# ===== 5. 停止排程 =====
def stop_scheduler():
    """移除掃描 job（排程器本身繼續運行，只是沒有任務）"""
    scheduler = get_scheduler()
    if scheduler.get_job("folder_scan"):
        scheduler.remove_job("folder_scan")

# ===== 6. 查詢排程狀態 =====
def get_scheduler_status() -> dict:
    """
    回傳目前排程器狀態
    {
        "running":       True/False,
        "job_exists":    True/False,
        "next_run":      "2026-04-19 10:30:00" 或 None
    }
    """
    scheduler = get_scheduler()
    job       = scheduler.get_job("folder_scan")

    return {
        "running":    scheduler.running,
        "job_exists": job is not None,
        "next_run":   (
            job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            if job and job.next_run_time else None
        ),
    }

# ===== 7. Streamlit 啟動時初始化排程 =====
def init_scheduler_from_db():
    """
    app.py 啟動時呼叫
    讀取 DB 設定，若 enabled=1 則自動啟動排程
    確保重啟 Streamlit 後排程自動恢復
    """
    settings     = get_scheduler_settings()
    enabled      = settings.get("enabled", "0") == "1"
    interval_min = int(settings.get("interval_min", "10"))

    if enabled:
        start_scheduler(interval_min)
