"""Cấu hình chung cho VitalLens.

Mọi hằng số / setting runtime sống trong `Settings`. Các tên viết hoa
ở cuối file được re-export để giữ tương thích với code hiện tại
(`from apps.config import BG_MAIN, SFTP_PATH, ...`).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _resolve_app_dir() -> Path:
    """Thư mục gốc của ứng dụng, chịu được cả khi chạy bằng PyInstaller .exe."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # config.py nằm tại apps/config.py -> parent.parent là repo root.
    return Path(__file__).resolve().parent.parent


APP_DIR: Path = _resolve_app_dir()


# =====================================================================
# Theme (màu sắc) - giữ flat constants để Tkinter widgets đọc nhanh.
# =====================================================================

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


# =====================================================================
# Runtime settings
# =====================================================================


def _load_dotenv_if_present(app_dir: Path) -> None:
    """Load file cấu hình nếu có + thư viện dotenv. Silent nếu thiếu.

    Ưu tiên đọc `.env` (chuẩn dotenv). Nếu không có, fallback sang file tên
    `env` (không dấu chấm) để tránh trục trặc trên Windows - nơi Explorer
    khó tạo file bắt đầu bằng dấu chấm.

    Giá trị đã tồn tại trong ``os.environ`` KHÔNG bị đè (``override=False``)
    nên biến môi trường của hệ điều hành vẫn thắng file `.env`.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for filename in (".env", "env"):
        env_path = app_dir / filename
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)
            return


_load_dotenv_if_present(APP_DIR)


@dataclass(frozen=True)
class Settings:
    """Tất cả setting runtime (SFTP, API) gom vào một chỗ cho dễ test."""

    # SFTP
    sftp_host: str = "datastore.oucru.org"
    sftp_port: int = 22
    sftp_demo_mode: bool = False
    # OCR validate accepts a root like /EI_SHARE/.received,
    # /EI_SHARE/.received/<studyID>, or
    # /EI_SHARE/.received/<studyID>/PROCESSING.
    sftp_path: str = "/EI_SHARE/.received/13NV/PROCESSING"

    # API upload
    api_upload_url: str = ""
    api_bearer_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """Tạo instance từ biến môi trường (kèm hardcoded default)."""

        def _env_str(name: str, default: str) -> str:
            return os.environ.get(name, default)

        def _env_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def _env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        return cls(
            sftp_host=_env_str("SFTP_HOST", "datastore.oucru.org"),
            sftp_port=_env_int("SFTP_PORT", 22),
            sftp_demo_mode=_env_bool("SFTP_DEMO_MODE", False),
            sftp_path=_env_str(
                "SFTP_PATH", "/EI_SHARE/.received/13NV/PROCESSING"
            ),
            api_upload_url=_env_str("API_UPLOAD_URL", ""),
            api_bearer_token=_env_str("API_BEARER_TOKEN", ""),
        )


SETTINGS: Settings = Settings.from_env()

# =====================================================================
# Legacy flat constants (back-compat) - các module khác đang import tên này.
# =====================================================================

SFTP_HOST: str = SETTINGS.sftp_host
SFTP_PORT: int = SETTINGS.sftp_port
SFTP_DEMO_MODE: bool = SETTINGS.sftp_demo_mode
SFTP_PATH: str = SETTINGS.sftp_path
API_UPLOAD_URL: str = SETTINGS.api_upload_url
API_BEARER_TOKEN: str = SETTINGS.api_bearer_token


__all__ = [
    # Theme
    "BG_MAIN",
    "BG_CARD",
    "BG_INPUT",
    "FG_TEXT",
    "FG_DIM",
    "FG_TITLE",
    "ACCENT_BLUE",
    "ACCENT_GREEN",
    "ACCENT_ORANGE",
    "ACCENT_RED",
    "ACCENT_PURPLE",
    "BTN_HOVER_BLUE",
    "BTN_HOVER_GREEN",
    "BTN_HOVER_ORANGE",
    "BTN_HOVER_PURPLE",
    "BORDER_COLOR",
    # Paths
    "APP_DIR",
    # Settings
    "Settings",
    "SETTINGS",
    "SFTP_HOST",
    "SFTP_PORT",
    "SFTP_DEMO_MODE",
    "SFTP_PATH",
    "API_UPLOAD_URL",
    "API_BEARER_TOKEN",
]
