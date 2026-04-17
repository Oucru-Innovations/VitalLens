"""Cấu hình logging tập trung cho toàn app.

Được gọi một lần từ `main.py`, trước khi bất kỳ module Paddle nào được import.
Gộp logic từng rải rác trước đây (`logging.getLogger('paddle').setLevel(...)`).
"""

from __future__ import annotations

import logging
import os
import sys
import warnings


_NOISY_LOGGERS = (
    "paddle",
    "paddleocr",
    "paddlex",
    "ppocr",
)


def setup_logging(level: int | str = logging.INFO) -> None:
    """Cấu hình root logger và làm im các logger quá ồn.

    Cũng thiết lập các biến môi trường để Paddle bớt in message vô nghĩa.
    Nếu gọi nhiều lần sẽ no-op (kiểm tra thông qua flag trên root logger).
    """

    # Guard: chỉ setup một lần
    if getattr(setup_logging, "_configured", False):
        return
    setup_logging._configured = True  # type: ignore[attr-defined]

    # Biến môi trường cho Paddle/OCR - phải đặt trước khi paddle được import.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("GLOG_minloglevel", "2")

    # Tắt 2 warning không dập được qua logger.
    warnings.filterwarnings("ignore", message="No ccache found")
    warnings.filterwarnings(
        "ignore", message=".*doesn't match a supported version"
    )

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)


def patch_paddlex_when_frozen() -> None:
    """Khi chạy dưới PyInstaller EXE, PaddleX check dependency không đúng.

    Monkey-patch các hàm check trả True/None để bỏ qua. Chỉ áp dụng
    khi `sys.frozen` bật.
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


__all__ = ["setup_logging", "patch_paddlex_when_frozen"]
