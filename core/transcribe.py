import os
import re
import hashlib
import shutil
import subprocess
import whisper
import torch
from datetime import datetime

# ===== 1. 支援的音訊格式 =====
SUPPORTED_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".mp4", ".aac", ".flac"}

# ===== 2. 工具函式 =====

def get_executable_path(name):
    """自動尋找系統中的執行檔路徑（例如 yt-dlp）"""
    path = shutil.which(name)
    return path if path else name

def get_device():
    """自動偵測 GPU / CPU"""
    return "cuda" if torch.cuda.is_available() else "cpu"

def calc_md5(filepath: str) -> str:
    """計算檔案 MD5，用來當作資料庫的 source_key"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def clean_vtt(filepath: str) -> str:
    """解析 .vtt 字幕檔，去除時間軸與重複行，回傳純文字"""
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    clean = [
        re.sub(r"<[^>]+>", "", line).strip()
        for line in lines
        if line.strip()
        and not line.startswith("WEBVTT")
        and "-->" not in line
    ]
    # 去除連續重複行
    seen = []
    for line in clean:
        if not seen or line != seen[-1]:
            seen.append(line)
    return "\n".join(seen)

# ===== 3. Whisper 模型載入（快取，避免重複載入）=====
_whisper_model = None

def get_whisper_model(model_size="small"):
    """
    取得 Whisper 模型（單例模式）
    model_size 選項：tiny / base / small / medium
    3060 8GB 建議用 small，準確度與速度平衡最好
    """
    global _whisper_model
    if _whisper_model is None:
        device = get_device()
        _whisper_model = whisper.load_model(model_size, device=device)
    return _whisper_model

# ===== 4. YouTube 字幕下載 =====

def fetch_youtube_subtitle(url: str, tmp_prefix="tmp_yt") -> str:
    """
    嘗試用 yt-dlp 下載 YouTube 自動字幕
    成功回傳純文字，失敗回傳空字串
    """
    yt_dlp = get_executable_path("yt-dlp")
    vtt_path = f"{tmp_prefix}.zh-Hant.vtt"

    # 嘗試下載繁體中文字幕
    subprocess.run([
        yt_dlp,
        "--skip-download",
        "--write-auto-sub",
        "--sub-lang", "zh-Hant",
        "--output", tmp_prefix,
        url
    ], capture_output=True)

    if os.path.exists(vtt_path):
        text = clean_vtt(vtt_path)
        os.remove(vtt_path)
        return text

    # 嘗試簡體中文字幕（備援）
    vtt_path_hans = f"{tmp_prefix}.zh-Hans.vtt"
    subprocess.run([
        yt_dlp,
        "--skip-download",
        "--write-auto-sub",
        "--sub-lang", "zh-Hans",
        "--output", tmp_prefix,
        url
    ], capture_output=True)

    if os.path.exists(vtt_path_hans):
        text = clean_vtt(vtt_path_hans)
        os.remove(vtt_path_hans)
        return text

    return ""  # 無字幕

def fetch_youtube_audio(url: str, output_path="tmp_audio.mp3") -> str:
    """
    用 yt-dlp 下載 YouTube 音訊為 mp3
    成功回傳檔案路徑，失敗回傳空字串
    """
    yt_dlp = get_executable_path("yt-dlp")
    # 去掉副檔名讓 yt-dlp 自己加
    base = output_path.replace(".mp3", "")
    subprocess.run([
        yt_dlp,
        "--extract-audio",
        "--audio-format", "mp3",
        "--output", f"{base}.mp3",
        url
    ], capture_output=True)

    return output_path if os.path.exists(output_path) else ""

# ===== 5. Whisper 轉錄（通用）=====

def transcribe_audio(audio_path: str, model_size="small") -> str:
    """
    用 Whisper 轉錄音訊檔，回傳純文字
    支援 mp3 / wav / m4a 等格式
    """
    model = get_whisper_model(model_size)
    result = model.transcribe(audio_path, language="zh")
    return result["text"]

# ===== 6. 主入口：YouTube 完整處理流程 =====

def process_youtube(url: str, log_callback=None) -> dict:
    """
    YouTube 完整轉錄流程：
    1. 嘗試抓字幕
    2. 字幕失敗則下載音訊 + Whisper 轉錄
    回傳 dict：
        {
            "source_key": url,
            "source_type": "youtube_subtitle" 或 "youtube_whisper",
            "title": "",        # 暫留，未來可用 yt-dlp 抓標題
            "raw_text": "...",
            "success": True/False,
            "error": ""
        }
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    result = {
        "source_key": url,
        "source_type": "",
        "title": "",
        "raw_text": "",
        "success": False,
        "error": ""
    }

    try:
        # ----- 6.1 嘗試字幕 -----
        log("🔍 嘗試下載 YouTube 字幕...")
        text = fetch_youtube_subtitle(url)

        if text:
            log("✅ 字幕下載成功")
            result["source_type"] = "youtube_subtitle"
            result["raw_text"] = text
            result["success"] = True
            return result

        # ----- 6.2 字幕失敗，改用 Whisper -----
        device = get_device()
        log(f"⚠️ 無字幕，啟動 Whisper ({device}) 轉錄...")

        audio_path = fetch_youtube_audio(url)
        if not audio_path:
            result["error"] = "音訊下載失敗"
            return result

        log("🎙️ Whisper 轉錄中（請稍候）...")
        text = transcribe_audio(audio_path)
        os.remove(audio_path)  # 清理暫存

        result["source_type"] = "youtube_whisper"
        result["raw_text"] = text
        result["success"] = True
        return result

    except Exception as e:
        result["error"] = str(e)
        return result

# ===== 7. 主入口：本地音訊檔處理流程 =====

def process_audio_file(filepath: str, log_callback=None) -> dict:
    """
    本地音訊檔（上傳或資料夾掃描）完整轉錄流程
    回傳格式與 process_youtube 相同
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    result = {
        "source_key": "",
        "source_type": "",
        "title": os.path.basename(filepath),
        "raw_text": "",
        "success": False,
        "error": ""
    }

    try:
        # ----- 7.1 副檔名檢查 -----
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in SUPPORTED_AUDIO_EXT:
            result["error"] = f"不支援的格式：{ext}"
            return result

        # ----- 7.2 計算 MD5 作為 source_key -----
        log("🔑 計算檔案 MD5...")
        md5 = calc_md5(filepath)
        result["source_key"] = md5

        # ----- 7.3 Whisper 轉錄 -----
        device = get_device()
        log(f"🎙️ Whisper ({device}) 轉錄中...")
        text = transcribe_audio(filepath)

        result["source_type"] = "upload" if "upload" in filepath else "folder"
        result["raw_text"] = text
        result["success"] = True
        return result

    except Exception as e:
        result["error"] = str(e)
        return result

# ===== 8. 資料夾掃描（排程用）=====

def scan_folder(folder_path: str) -> list:
    """
    掃描資料夾內所有支援格式的音訊檔
    回傳檔案路徑清單
    """
    if not os.path.exists(folder_path):
        return []

    found = []
    for fname in os.listdir(folder_path):
        ext = os.path.splitext(fname)[1].lower()
        if ext in SUPPORTED_AUDIO_EXT:
            found.append(os.path.join(folder_path, fname))
    return found
