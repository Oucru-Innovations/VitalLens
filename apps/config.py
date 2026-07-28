"""Global configuration for VitalLens.

All runtime constants and settings live in the ``Settings`` dataclass.
Upper-case names at the bottom of this file are re-exported for
backward compatibility (``from apps.config import BG_MAIN, SFTP_PATH, ...``).
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def _resolve_app_dir() -> Path:
    """Return the application root directory.

    Works correctly both during development and inside a PyInstaller EXE.
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # config.py lives at apps/config.py → parent.parent is the repo root.
    return Path(__file__).resolve().parent.parent


APP_DIR: Path = _resolve_app_dir()


# =====================================================================
# Theme (colors) — flat constants so Tkinter widgets can read them fast.
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
BTN_HOVER_RED = "#b91c1c"
BTN_HOVER_PURPLE = "#6d28d9"
BORDER_COLOR = "#d4d4d4"


# =====================================================================
# Runtime settings
# =====================================================================


def _parse_env_file_manually(env_path: Path) -> None:
    """Fallback parser when ``python-dotenv`` is not importable (PyInstaller).

    Reads a ``.env`` file in ``KEY=VALUE`` format and writes values into
    ``os.environ``. Blank lines and comment lines (``#``) are skipped.
    Outer quotes (``"`` or ``'``) and surrounding whitespace are stripped
    from values.

    Only writes keys that do **not** already exist in ``os.environ``
    (same as ``load_dotenv(override=False)``).
    """

    try:
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip surrounding quotes if present
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


# Tên biến chứa bí mật — chỉ được log "đã đặt / chưa đặt", KHÔNG bao giờ log giá trị.
_SECRET_KEYS = frozenset({"API_BEARER_TOKEN", "SFTP_PASSWORD"})

# Bật ghi file chẩn đoán bằng: set VITALLENS_DEBUG_CONFIG=1
_DEBUG_CONFIG_ENV = "VITALLENS_DEBUG_CONFIG"


def _redact(key: str, value: str) -> str:
    """Giá trị an toàn để ghi log: bí mật chỉ lộ độ dài, không lộ nội dung."""

    if not value:
        return "(empty)"
    if key in _SECRET_KEYS:
        return f"(set, len={len(value)})"
    return f"'{value}'"


def _load_dotenv_if_present(app_dir: Path) -> None:
    """Load a dotenv config file if one exists.

    Looks for ``.env`` first, then falls back to ``env`` (no dot) — handy
    on Windows where Explorer refuses to create filenames starting with
    a dot.

    Existing ``os.environ`` values are NOT overridden (``override=False``),
    so OS-level environment variables always win over the file.

    When ``python-dotenv`` is not importable (common in PyInstaller
    bundles), falls back to a simple built-in parser.

    Chẩn đoán: chỉ ghi ``config_debug.log`` khi biến môi trường
    ``VITALLENS_DEBUG_CONFIG`` được bật, và **không bao giờ** ghi nội dung
    ``.env`` — chỉ tên khoá đọc được, giá trị bí mật thì redact. Trước đây hàm
    này dump nguyên văn từng dòng .env (gồm cả bearer token) ra file cạnh EXE.
    """

    # --- Debug: chỉ thu thập khi được bật tường minh ---
    debug_on = os.environ.get(_DEBUG_CONFIG_ENV, "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    _debug_lines: list[str] = []

    def _dbg(msg: str) -> None:
        if debug_on:
            _debug_lines.append(msg)

    def _flush() -> None:
        if not debug_on:
            return
        try:
            (app_dir / "config_debug.log").write_text(
                "\n".join(_debug_lines), encoding="utf-8"
            )
        except OSError:
            pass

    _dbg(f"APP_DIR  = {app_dir}")
    _dbg(f"frozen   = {getattr(sys, 'frozen', False)}")
    _dbg(f"cwd      = {Path.cwd()}")

    env_path: Path | None = None
    for filename in (".env", "env"):
        candidate = app_dir / filename
        exists = candidate.is_file()
        _dbg(f"Check    : {candidate} -> {'FOUND' if exists else 'not found'}")
        if exists:
            env_path = candidate
            break

    if env_path is None:
        _dbg("RESULT   : No .env file found!")
        _flush()
        return

    _dbg(f"Loading  : {env_path} ({env_path.stat().st_size} bytes)")

    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=False)
        _dbg("Parser   : python-dotenv")
    except ImportError:
        # python-dotenv not bundled → use built-in parser
        _parse_env_file_manually(env_path)
        _dbg("Parser   : built-in (dotenv not available)")

    for key in ("API_UPLOAD_URL", "API_BEARER_TOKEN", "API_UPLOAD_OWNER"):
        _dbg(f"RESULT   : {key} = {_redact(key, os.environ.get(key, ''))}")

    _flush()


_load_dotenv_if_present(APP_DIR)


@dataclass(frozen=True)
class Settings:
    """All runtime settings (SFTP, API) in one place for easy testing."""

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
    api_upload_owner: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        """Create an instance from environment variables (with hardcoded defaults)."""

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
            api_upload_owner=_env_str("API_UPLOAD_OWNER", ""),
        )


SETTINGS: Settings = Settings.from_env()


def _warn_insecure_endpoint(settings: Settings) -> None:
    """Cảnh báo khi bearer token sẽ đi qua kênh không mã hoá.

    ``http://`` gửi header ``Authorization`` dạng cleartext — bất kỳ ai trên
    cùng đường truyền đều đọc được token lẫn dữ liệu bệnh nhân. Localhost thì
    bỏ qua vì không ra khỏi máy.
    """

    url = (settings.api_upload_url or "").strip().lower()
    if not url or not url.startswith("http://"):
        return
    host = url[len("http://"):].split("/", 1)[0].split(":", 1)[0]
    if host in {"localhost", "127.0.0.1", "::1"}:
        return
    log.warning(
        "API_UPLOAD_URL dùng http:// (host=%s) — bearer token và dữ liệu bệnh "
        "nhân sẽ đi qua mạng KHÔNG mã hoá. Hãy chuyển sang https://.",
        host,
    )


_warn_insecure_endpoint(SETTINGS)

# =====================================================================
# Legacy flat constants (backward compatibility)
# =====================================================================

SFTP_HOST: str = SETTINGS.sftp_host
SFTP_PORT: int = SETTINGS.sftp_port
SFTP_DEMO_MODE: bool = SETTINGS.sftp_demo_mode
SFTP_PATH: str = SETTINGS.sftp_path
API_UPLOAD_URL: str = SETTINGS.api_upload_url
API_BEARER_TOKEN: str = SETTINGS.api_bearer_token
API_UPLOAD_OWNER: str = SETTINGS.api_upload_owner


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
    "BTN_HOVER_RED",
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
    "API_UPLOAD_OWNER",
]
