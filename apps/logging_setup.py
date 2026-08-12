"""Centralized logging configuration for the entire app.

Called once from `main.py` before any Paddle module is imported.
Consolidates logic that was previously scattered across files.
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path


_NOISY_LOGGERS = (
    "paddle",
    "paddleocr",
    "paddlex",
    "ppocr",
)

# App chạy với console=False (build_exe.spec) nên log ra stderr không ai thấy.
# File log là cách DUY NHẤT để xem lại "đã upload file nào, lúc nào, kết quả
# ra sao" sau khi sự cố — upload_api.py đã log rất chi tiết, chỉ thiếu nơi lưu.
_LOG_FILENAME = "vitallens.log"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def _resolve_log_dir() -> Path:
    """Thư mục ghi log: %LOCALAPPDATA%\\VitalLens khi đóng gói, thư mục gốc
    repo khi chạy từ source.

    KHÔNG dùng thư mục cạnh EXE (``dist\\VitalLens\\``, nơi ``apps.config``
    trỏ tới) — đó là thư mục bị zip nguyên vẹn và gửi cho end-user (xem README
    "Ship to End Users"). Log có thể mang patient_code (nhúng trong tên file
    PDF/CSV, xem `apps.pages.upload.page`) nên phải nằm ngoài mọi thứ có thể
    lọt vào bản release; `build.bat` cũng chỉ quét `.env`/`env`/
    `config_debug.log`, không quét `logs/`. %LOCALAPPDATA% là thư mục riêng
    của từng máy, không bao giờ nằm trong `dist\\`.

    Lặp lại một phần logic của ``apps.config._resolve_app_dir`` tại chỗ (thay
    vì import) để module này không phụ thuộc ``apps.config`` — thứ tự import
    ở main.py là load-bearing (patch SSL/env Paddle phải chạy trước khi import
    bất kỳ gì).
    """

    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "VitalLens" / "logs"
    return Path(__file__).resolve().parent.parent / "logs"


def setup_logging(level: int | str = logging.INFO) -> None:
    """Configure root logger and silence noisy loggers.

    Also sets environment variables to suppress useless Paddle messages.
    No-op if called more than once (guarded by an internal flag).
    """

    # Guard: only run once
    if getattr(setup_logging, "_configured", False):
        return
    setup_logging._configured = True  # type: ignore[attr-defined]

    # Environment variables for Paddle/OCR — must be set before paddle import.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("GLOG_minloglevel", "2")

    # Suppress warnings that cannot be silenced via loggers.
    warnings.filterwarnings("ignore", message="No ccache found")
    warnings.filterwarnings(
        "ignore", message=".*doesn't match a supported version"
    )

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        log_dir = _resolve_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / _LOG_FILENAME,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handlers.append(file_handler)
    except OSError:
        # Thư mục không ghi được (quyền, ổ đầy...) → vẫn chạy tiếp với stderr.
        pass

    logging.basicConfig(level=level, format=fmt, handlers=handlers)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)


def patch_windows_ssl_cert_store() -> None:
    """Bỏ qua chứng chỉ lỗi trong Windows Certificate Store.

    Một số máy Windows có chứng chỉ bị lỗi định dạng ASN.1 trong hệ thống
    (thường do phần mềm antivirus/proxy công ty cài vào). Khi đó
    ``ssl.create_default_context()`` ném ``SSLError: [ASN1: NOT_ENOUGH_DATA]``
    ngay khi nạp toàn bộ store, dù ứng dụng chưa hề gọi mạng — làm sập việc
    import ``aiohttp`` (qua ``paddleocr``) trước cả khi OCR chạy.
    Phải gọi trước khi import bất kỳ thư viện nào tạo SSL context mặc định.
    """

    if sys.platform != "win32":
        return
    try:
        import ssl

        _original = ssl.SSLContext._load_windows_store_certs

        def _safe_load_windows_store_certs(self, storename, purpose):
            try:
                _original(self, storename, purpose)
            except ssl.SSLError:
                pass

        ssl.SSLContext._load_windows_store_certs = _safe_load_windows_store_certs
    except Exception:
        pass


def patch_paddlex_when_frozen() -> None:
    """Bypass PaddleX dependency checks when running as a PyInstaller EXE.

    PaddleX performs dependency checks that fail inside a frozen bundle.
    Monkey-patch the check functions to return True/None. Only applied
    when ``sys.frozen`` is set.
    """

    if not getattr(sys, "frozen", False):
        return
    try:
        import paddlex.utils.deps as _pdx_deps

        _pdx_deps.is_dep_available = lambda *a, **kw: True
        _pdx_deps.is_extra_available = lambda *a, **kw: True
        _pdx_deps.require_deps = lambda *a, **kw: None
        _pdx_deps.require_extra = lambda *a, **kw: None
    except Exception:
        pass


__all__ = ["setup_logging", "patch_paddlex_when_frozen", "patch_windows_ssl_cert_store"]
