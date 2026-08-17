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

from apps.runtime_paths import bundle_dir, exe_dir

log = logging.getLogger(__name__)


def _resolve_app_dir() -> Path:
    """Return the application root directory.

    Works correctly during development, inside a PyInstaller EXE, and inside
    a Nuitka binary (kể cả onefile — xem ``apps/runtime_paths.py``).
    """

    # config.py lives at apps/config.py → parent.parent is the repo root.
    return exe_dir() or Path(__file__).resolve().parent.parent


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
    """Load dotenv config files if any exist.

    Đọc theo thứ tự ưu tiên, **nạp hết** chứ không dừng ở file đầu tiên
    (``override=False`` nên file nào đặt khoá trước thì file đó thắng):

    1. ``%APPDATA%\\VitalLens\\.env`` — config riêng của người dùng, nằm
       NGOÀI thư mục app nên không mất khi giải nén đè bản mới và không đi
       theo khi ai đó copy thư mục app cho đồng nghiệp. Xem
       ``apps/services/user_config.py``.
    2. ``<app_dir>/.env`` rồi ``<app_dir>/env`` — cách cũ, giữ để bản cài sẵn
       của người dùng hiện tại không hỏng. Tên không dấu chấm là vì Windows
       Explorer từ chối tạo file bắt đầu bằng dấu chấm.
    3. ``<bundle_dir>/.env`` — bản `.env` được NHÚNG vào binary lúc build
       (``build_nuitka.bat``). Đứng CUỐI vì nó chỉ là giá trị mặc định xuất
       xưởng: mọi file của người dùng ở trên, và biến môi trường OS, đều đè
       lên được mà không phải build lại app.

    Existing ``os.environ`` values are NOT overridden (``override=False``),
    so OS-level environment variables always win over every file.

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

    from apps.services.user_config import USER_ENV_PATH

    candidates = [USER_ENV_PATH, app_dir / ".env", app_dir / "env"]
    bundled = bundle_dir()
    if bundled is not None:
        # dict.fromkeys: bản Nuitka standalone (không onefile) có
        # bundle_dir() == app_dir → tránh nạp và log cùng một file hai lần.
        candidates = list(dict.fromkeys(candidates + [bundled / ".env"]))

    loaded_any = False
    for candidate in candidates:
        exists = candidate.is_file()
        _dbg(f"Check    : {candidate} -> {'FOUND' if exists else 'not found'}")
        if not exists:
            continue

        loaded_any = True
        _dbg(f"Loading  : {candidate} ({candidate.stat().st_size} bytes)")
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=candidate, override=False)
            _dbg("Parser   : python-dotenv")
        except ImportError:
            # python-dotenv not bundled → use built-in parser
            _parse_env_file_manually(candidate)
            _dbg("Parser   : built-in (dotenv not available)")

    if not loaded_any:
        _dbg("RESULT   : No .env file found!")
        _flush()
        return

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

    # SFTP buffer dir (destination for a separate inference util to pick up)
    sftp_buffer_path: str = ""
    sftp_upload_default_user: str = "user@oucru.org"

    # API upload
    api_upload_url: str = ""
    api_bearer_token: str = ""
    api_upload_owner: str = ""

    # URL của manifest cập nhật (JSON công khai, không chứa token).
    # Rỗng = tắt hẳn việc kiểm tra. Xem apps/services/update_check.py.
    update_manifest_url: str = ""

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
            sftp_buffer_path=_env_str("SFTP_BUFFER_PATH", ""),
            sftp_upload_default_user=_env_str(
                "SFTP_UPLOAD_DEFAULT_USER", "user@oucru.org"
            ),
            api_upload_url=_env_str("API_UPLOAD_URL", ""),
            api_bearer_token=_env_str("API_BEARER_TOKEN", ""),
            api_upload_owner=_env_str("API_UPLOAD_OWNER", ""),
            update_manifest_url=_env_str("UPDATE_MANIFEST_URL", ""),
        )


SETTINGS: Settings = Settings.from_env()


def is_secure_endpoint(url: str) -> bool:
    """True khi gửi bearer token tới ``url`` là an toàn.

    ``http://`` gửi header ``Authorization`` dạng cleartext — bất kỳ ai trên
    cùng đường truyền đều đọc được token lẫn dữ liệu bệnh nhân. Localhost thì
    bỏ qua vì không ra khỏi máy. Rỗng = chưa cấu hình, không có gì để lộ.

    Một nơi duy nhất định nghĩa luật này: cảnh báo lúc khởi động và dialog
    nhập cấu hình đều gọi hàm này. Hai bản logic bảo mật sẽ lệch nhau.
    """

    url = (url or "").strip().lower()
    if not url or url.startswith("https://"):
        return True
    if not url.startswith("http://"):
        return False
    host = url[len("http://"):].split("/", 1)[0].split(":", 1)[0]
    return host in {"localhost", "127.0.0.1", "::1"}


def _warn_insecure_endpoint(settings: Settings) -> None:
    """Ghi log cảnh báo khi endpoint upload không đủ an toàn."""

    url = (settings.api_upload_url or "").strip().lower()
    if not url.startswith("http://") or is_secure_endpoint(url):
        return
    host = url[len("http://"):].split("/", 1)[0].split(":", 1)[0]
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
SFTP_BUFFER_PATH: str = SETTINGS.sftp_buffer_path
SFTP_UPLOAD_DEFAULT_USER: str = SETTINGS.sftp_upload_default_user
API_UPLOAD_URL: str = SETTINGS.api_upload_url
API_BEARER_TOKEN: str = SETTINGS.api_bearer_token
API_UPLOAD_OWNER: str = SETTINGS.api_upload_owner
UPDATE_MANIFEST_URL: str = SETTINGS.update_manifest_url


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
    "SFTP_BUFFER_PATH",
    "SFTP_UPLOAD_DEFAULT_USER",
    "API_UPLOAD_URL",
    "API_BEARER_TOKEN",
    "API_UPLOAD_OWNER",
    "UPDATE_MANIFEST_URL",
    "is_secure_endpoint",
]


if __name__ == "__main__":
    assert is_secure_endpoint("https://a.example.org/upload")
    assert is_secure_endpoint("")
    assert is_secure_endpoint("http://localhost:8000/upload")
    assert is_secure_endpoint("http://127.0.0.1/upload")
    assert not is_secure_endpoint("http://a.example.org/upload")
    assert not is_secure_endpoint("http://a.example.org:8080/upload")
    assert not is_secure_endpoint("ftp://a.example.org")
    print("config OK")
