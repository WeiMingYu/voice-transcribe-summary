import sqlite3
from datetime import datetime

# ===== 1. 資料庫路徑設定 =====
DB_PATH = "reports.db"

# ===== 2. 取得資料庫連線 =====
def get_conn():
    """取得 SQLite 連線，啟用外鍵約束"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # 讓查詢結果可用欄位名稱存取
    conn.execute("PRAGMA foreign_keys = ON") # 啟用 FK 約束
    return conn

# ===== 3. 初始化資料庫（建表 + 預設資料）=====
def init_db():
    """系統啟動時呼叫，建立所有資料表與預設資料"""
    conn = get_conn()
    cursor = conn.cursor()

    # ----- 3.1 媒體主表 -----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_library (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key   TEXT UNIQUE,
            source_type  TEXT,
            title        TEXT,
            raw_text     TEXT,
            refined_text TEXT,
            duration     INTEGER,
            created_at   TEXT
        )
    ''')

    # ----- 3.2 心得表 -----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_reports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id   INTEGER,
            p_name     TEXT,
            report     TEXT,
            sentiment  REAL,
            created_at TEXT,
            FOREIGN KEY (video_id) REFERENCES video_library(id)
        )
    ''')

    # ----- 3.3 人格表 -----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS personalities (
            name       TEXT PRIMARY KEY,
            prompt     TEXT,
            created_at TEXT
        )
    ''')

    # ----- 3.4 排程記錄表 -----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduler_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_path  TEXT,
            file_found INTEGER,
            file_new   INTEGER,
            file_skip  INTEGER,
            status     TEXT,
            message    TEXT,
            created_at TEXT
        )
    ''')

    # ----- 3.5 排程設定表（介面可調，重啟後保留）-----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduler_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # 預設值：關閉、路徑空白、每 10 分鐘掃描一次
    defaults = [
        ("enabled",       "0"),
        ("folder_path",   ""),
        ("interval_min",  "10"),
        ("auto_p_name",   "務實課長-俞威名"),
    ]
    for k, v in defaults:
        cursor.execute(
            "INSERT OR IGNORE INTO scheduler_settings (key, value) VALUES (?, ?)", (k, v)
        )

    # ----- 3.6 預設人格 -----
    cursor.execute('''
        INSERT OR IGNORE INTO personalities (name, prompt, created_at)
        VALUES (?, ?, ?)
    ''', (
        '務實課長-俞威名',
        '你是一位在傳統製造業深耕多年的 IT 課長，語氣穩重、體貼現場、連結物料管理與 SOP。',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()

# ===== 4. video_library 相關操作 =====

def get_video_by_key(source_key: str):
    """用 source_key 查詢媒體主表，回傳 Row 或 None"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM video_library WHERE source_key = ?", (source_key,)
    ).fetchone()
    conn.close()
    return row

def insert_video(source_key, source_type, title, raw_text, refined_text, duration=None):
    """新增一筆媒體紀錄，回傳新增的 id"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO video_library
            (source_key, source_type, title, raw_text, refined_text, duration, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        source_key, source_type, title,
        raw_text, refined_text, duration,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def get_all_videos():
    """取得所有媒體紀錄（列表頁用），只取摘要欄位不含大文本"""
    conn = get_conn()
    rows = conn.execute('''
        SELECT id, source_key, source_type, title, duration, created_at
        FROM video_library
        ORDER BY id DESC
    ''').fetchall()
    conn.close()
    return rows

def delete_video(video_id: int):
    """刪除媒體主表紀錄（CASCADE 會同步刪除 ai_reports）"""
    conn = get_conn()
    # 手動刪除子表（SQLite FK cascade 需要額外設定）
    conn.execute("DELETE FROM ai_reports WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM video_library WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()

# ===== 5. ai_reports 相關操作 =====

def insert_report(video_id, p_name, report, sentiment=None):
    """新增一筆心得紀錄，回傳新增的 id"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO ai_reports (video_id, p_name, report, sentiment, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        video_id, p_name, report, sentiment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def get_reports_by_video(video_id: int):
    """取得某媒體的所有心得（依時間倒序）"""
    conn = get_conn()
    rows = conn.execute('''
        SELECT * FROM ai_reports
        WHERE video_id = ?
        ORDER BY id DESC
    ''', (video_id,)).fetchall()
    conn.close()
    return rows

def get_recent_reports(limit=15):
    """取得最近 N 筆心得，含媒體標題（歷史側欄用）"""
    conn = get_conn()
    rows = conn.execute('''
        SELECT
            r.id,
            r.p_name,
            r.report,
            r.created_at,
            v.title,
            v.source_type,
            v.source_key
        FROM ai_reports r
        JOIN video_library v ON r.video_id = v.id
        ORDER BY r.id DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return rows

def delete_report(report_id: int):
    """刪除單筆心得"""
    conn = get_conn()
    conn.execute("DELETE FROM ai_reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()

# ===== 6. personalities 相關操作 =====

def get_all_personalities():
    """取得所有人格，回傳 {name: prompt} dict"""
    conn = get_conn()
    rows = conn.execute("SELECT name, prompt FROM personalities").fetchall()
    conn.close()
    return {row["name"]: row["prompt"] for row in rows}

def upsert_personality(name, prompt):
    """新增或更新人格設定"""
    conn = get_conn()
    conn.execute('''
        INSERT OR REPLACE INTO personalities (name, prompt, created_at)
        VALUES (?, ?, ?)
    ''', (name, prompt, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def delete_personality(name):
    """刪除人格（預設人格不可刪）"""
    if name == '務實課長-俞威名':
        return False  # 預設人格保護
    conn = get_conn()
    conn.execute("DELETE FROM personalities WHERE name = ?", (name,))
    conn.commit()
    conn.close()
    return True

# ===== 7. scheduler_log 相關操作 =====

def insert_scheduler_log(scan_path, file_found, file_new, file_skip, status, message=""):
    """寫入一筆排程掃描紀錄"""
    conn = get_conn()
    conn.execute('''
        INSERT INTO scheduler_log
            (scan_path, file_found, file_new, file_skip, status, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        scan_path, file_found, file_new, file_skip, status, message,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

def get_recent_scheduler_logs(limit=20):
    """取得最近 N 筆排程記錄"""
    conn = get_conn()
    rows = conn.execute('''
        SELECT * FROM scheduler_log
        ORDER BY id DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return rows

# ===== 8. scheduler_settings 相關操作 =====

def get_scheduler_settings() -> dict:
    """
    取得所有排程設定，回傳 dict
    {
        "enabled":      "0" 或 "1",
        "folder_path":  "C:/AI_Input/Voice_Inbox",
        "interval_min": "10",
        "auto_p_name":  "務實課長-俞威名"
    }
    """
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM scheduler_settings").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def set_scheduler_setting(key: str, value: str):
    """更新單一排程設定"""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO scheduler_settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()

def save_scheduler_settings(enabled: bool, folder_path: str,
                             interval_min: int, auto_p_name: str):
    """一次儲存所有排程設定（介面儲存按鈕用）"""
    conn = get_conn()
    settings = [
        ("enabled",      "1" if enabled else "0"),
        ("folder_path",  folder_path),
        ("interval_min", str(interval_min)),
        ("auto_p_name",  auto_p_name),
    ]
    for k, v in settings:
        conn.execute(
            "INSERT OR REPLACE INTO scheduler_settings (key, value) VALUES (?, ?)",
            (k, v)
        )
    conn.commit()
    conn.close()
