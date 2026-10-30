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

from apps.runtime_paths import is_frozen, writable_exe_dir


_NOISY_LOGGERS = (
    "paddle",
    "paddleocr",
    "paddlex",
    "ppocr",
)

# App chạy với console=False (build_nuitka.bat) nên log ra stderr không ai thấy.
# File log là cách DUY NHẤT để xem lại "đã upload file nào, lúc nào, kết quả
# ra sao" sau khi sự cố — upload_api.py đã log rất chi tiết, chỉ thiếu nơi lưu.
_LOG_FILENAME = "vitallens.log"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def _resolve_log_dir() -> Path:
    """``<thư mục chứa EXE>/logs``; lui về %LOCALAPPDATA% khi không ghi được.

    Mặc định cạnh EXE vì hỗ trợ từ xa luôn phải bắt đầu bằng "gửi tôi file
    log" — bảo người dùng mở đúng thư mục họ vừa bấm vào EXE thì được, bảo họ
    gõ %LOCALAPPDATA% thì không. Chạy từ source thì vẫn là thư mục gốc repo.

    Lý do cũ để tránh chỗ này đã hết hiệu lực: hồi đó bản phát hành là thư mục
    onedir bị zip nguyên vẹn gửi cho end-user, log dính patient_code (nhúng
    trong tên file PDF/CSV, xem `apps.pages.upload.page`) sẽ đi theo. Bản
    onefile bây giờ chỉ là một EXE, không có thư mục nào để zip.

    CÒN LẠI một rủi ro: EXE đặt trên ổ mạng dùng chung thì mọi người ghi vào
    cùng một file log và đọc được patient_code của nhau. Ai làm vậy nên đặt
    VITALLENS_LOG_DIR trỏ về máy mình.

    Dùng ``apps.runtime_paths`` (chỉ stdlib, không tác dụng phụ) chứ KHÔNG
    import ``apps.config`` — thứ tự import ở main.py là load-bearing (patch
    SSL/env Paddle phải chạy trước khi import bất kỳ gì nặng), và
    ``apps.config`` nạp ``.env`` ngay lúc import.
    """

    override = os.environ.get("VITALLENS_LOG_DIR", "").strip()
    if override:
        return Path(override)
    if not is_frozen():
        return Path(__file__).resolve().parent.parent / "logs"
    beside_exe = writable_exe_dir()
    if beside_exe is not None:
        return beside_exe / "logs"
    # Program Files / ổ mạng chỉ-đọc: không ghi nổi cạnh EXE thì vẫn phải có log.
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "VitalLens" / "logs"


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
    # Mặc định paddlex/__init__ gọi repo_manager.initialize() (chỉ phục vụ
    # train) và cấm gọi lần 2. Nếu lần import đầu hỏng giữa chừng, lần import
    # lại chỉ báo "PDX has already been initialized", che mất lỗi thật.
    os.environ.setdefault("PADDLE_PDX_EAGER_INIT", "False")

    # Suppress warnings that cannot be silenced via loggers.
    warnings.filterwarnings("ignore", message="No ccache found")
    warnings.filterwarnings(
        "ignore", message=".*doesn't match a supported version"
    )

    # VITALLENS_LOG_LEVEL=DEBUG ghi cả tiến độ từng bước (status "working"/"info")
    # khi cần soi một lỗi khó; mặc định INFO chỉ giữ mốc chính + lỗi.
    env_level = os.environ.get("VITALLENS_LOG_LEVEL", "").strip().upper()
    # Gõ sai (vd "VERBOSE") thì basicConfig ném ValueError → EXE chết lặng lúc mở.
    if isinstance(logging.getLevelName(env_level), int):
        level = env_level
    fmt = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    log_dir: Path | None = None
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
        log_dir = None

    logging.basicConfig(level=level, format=fmt, handlers=handlers)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)

    _install_crash_hooks(log_dir)
    _log_startup_banner(log_dir)


_crash_file = None  # giữ file mở suốt đời process cho faulthandler


def _install_crash_hooks(log_dir: Path | None) -> None:
    """Đưa mọi lỗi không ai bắt vào file log.

    EXE chạy không console: traceback in ra stderr là mất. Ba đường lọt:
    - exception ở main thread (sys.excepthook)
    - exception trong thread nền: OCR, upload, SFTP (threading.excepthook)
    - crash native (access violation trong DLL/mã biên dịch): Python không kịp
      ném exception, chỉ faulthandler ghi được stack — vào ``crash.log``.
    Exception trong callback Tkinter đi đường riêng, xem ``App.report_callback_exception``.
    """

    import faulthandler
    import threading

    log = logging.getLogger("apps.crash")

    def _excepthook(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            log.critical("Lỗi không bắt được ở main thread", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_excepthook(args):
        if args.exc_type is not SystemExit:
            log.critical(
                "Lỗi không bắt được trong thread %s",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook

    global _crash_file
    if log_dir is None:
        return
    try:
        path = log_dir / "crash.log"
        # ponytail: chỉ cắt khi >1 MB lúc khởi động, đủ vì mỗi lần chạy thêm 1 dòng.
        mode = "w" if path.exists() and path.stat().st_size > 1024 * 1024 else "a"
        _crash_file = open(path, mode, encoding="utf-8")
        from datetime import datetime

        _crash_file.write(f"=== start {datetime.now():%Y-%m-%d %H:%M:%S} pid={os.getpid()}\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        _crash_file = None


def _log_startup_banner(log_dir: Path | None) -> None:
    """Mốc đầu mỗi lần chạy: biết log thuộc bản nào, chạy ở đâu."""

    import platform

    from apps import __version__

    logging.getLogger("apps").info(
        "===== VitalLens %s khởi động | %s | python %s | %s | exe=%s | cwd=%s | log=%s",
        __version__,
        "EXE" if is_frozen() else "source",
        platform.python_version(),
        platform.platform(),
        sys.executable,
        os.getcwd(),
        log_dir,
    )


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
    """Bypass PaddleX dependency checks when running as a packaged binary.

    PaddleX performs dependency checks that fail inside a Nuitka bundle. Monkey-patch the check functions to return
    True/None. Only applied when packaged.
    """

    if not is_frozen():
        return
    try:
        import paddlex.utils.deps as _pdx_deps

        _pdx_deps.is_dep_available = lambda *a, **kw: True
        _pdx_deps.is_extra_available = lambda *a, **kw: True
        _pdx_deps.require_deps = lambda *a, **kw: None
        _pdx_deps.require_extra = lambda *a, **kw: None
    except Exception:
        # Không chặn app khởi động (trang PDF không cần OCR), nhưng phải ghi
        # lại: đây là lỗi import paddlex THẬT, X-quang sẽ gặp lại sau.
        logging.getLogger(__name__).exception("Không import được paddlex lúc khởi động")


__all__ = ["setup_logging", "patch_paddlex_when_frozen", "patch_windows_ssl_cert_store"]
