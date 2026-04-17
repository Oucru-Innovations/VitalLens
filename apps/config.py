"""Cấu hình chung cho VitalLens."""

import os
import sys
from pathlib import Path

# Thư mục gốc của ứng dụng (hỗ trợ cả khi chạy bằng PyInstaller .exe)
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

# ========================== THEME / COLORS ==========================

BG_MAIN = "#f5f5f5"
BG_CARD = "#ffffff"
BG_INPUT = "#f0f0f0"
FG_TEXT = "#333333"
FG_DIM = "#888888"
FG_TITLE = "#1a1a1a"
ACCENT_BLUE = "#2563eb"
ACCENT_GREEN = "#16a34a"
ACCENT_ORANGE = "#ea580c"
ACCENT_RED = "#dc2626"
ACCENT_PURPLE = "#7c3aed"
BTN_HOVER_BLUE = "#1d4ed8"
BTN_HOVER_GREEN = "#15803d"
BTN_HOVER_ORANGE = "#c2410c"
BTN_HOVER_PURPLE = "#6d28d9"
BORDER_COLOR = "#d4d4d4"

# ========================== CẤU HÌNH SFTP ==========================

SFTP_HOST = "datastore.oucru.org"
SFTP_PORT = 22
SFTP_DEMO_MODE = False
# OCR validate accepts a root like /EI_SHARE/.received, /EI_SHARE/.received/<studyID>,
# or /EI_SHARE/.received/<studyID>/PROCESSING.
# If the app reports missing PROCESSING, double-check SFTP_PATH and the study ID.
SFTP_PATH = "/EI_SHARE/.received/13NV/PROCESSING"

# ========================== API UPLOAD ==========================
# Cố gắng load từ biến môi trường (qua file .env nếu có)
try:
    from dotenv import load_dotenv
    # Tìm file .env trong thư mục gốc
    env_path = APP_DIR / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

API_UPLOAD_URL = os.environ.get("API_UPLOAD_URL", "")
API_BEARER_TOKEN = os.environ.get("API_BEARER_TOKEN", "")
