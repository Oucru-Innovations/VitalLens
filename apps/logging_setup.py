"""Centralized logging configuration for the entire app.

Called once from `main.py` before any Paddle module is imported.
Consolidates logic that was previously scattered across files.
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

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)


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


__all__ = ["setup_logging", "patch_paddlex_when_frozen"]
