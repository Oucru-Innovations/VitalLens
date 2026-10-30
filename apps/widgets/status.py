"""Thanh trạng thái cho các trang."""

from __future__ import annotations

import logging
import sys
import tkinter as tk

from apps.config import ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED, BG_CARD, FG_DIM

# Mọi trang báo kết quả cho người dùng qua đây, nên đây cũng là chỗ ghi log
# cho từng chức năng. "working"/"info" là tiến độ, chỉ hiện khi
# VITALLENS_LOG_LEVEL=DEBUG.
_LOG_LEVELS = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "success": logging.INFO,
    "info": logging.DEBUG,
    "working": logging.DEBUG,
}


def _page_name(widget: tk.Misc | None) -> str:
    """Tên lớp trang chứa widget (OCRPage, UploadPDFPage...) để làm tag log."""

    while widget is not None:
        if type(widget).__module__.startswith("apps.pages"):
            return type(widget).__name__
        widget = widget.master
    return "ui"


class StatusBar(tk.Frame):
    """Thanh trạng thái với icon và màu theo mức độ."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(parent, bg=BG_CARD, **kwargs)
        self._log = logging.getLogger(f"apps.ui.{_page_name(parent)}")
        self._label = tk.Label(
            self,
            text="",
            bg=BG_CARD,
            fg=FG_DIM,
            font=("Helvetica", 11),
            anchor="w",
            wraplength=600,
        )
        self._label.pack(fill="x", padx=15, pady=8)

    def set(self, text: str, level: str = "info") -> None:
        # Gọi từ trong khối except thì kèm traceback: dòng trên giao diện chỉ có
        # str(e), log phải có đủ để biết hỏng ở dòng nào.
        in_except = level == "error" and sys.exc_info()[0] is not None
        self._log.log(_LOG_LEVELS.get(level, logging.INFO), "%s", text, exc_info=in_except)
        colors = {
            "info": FG_DIM,
            "success": ACCENT_GREEN,
            "warning": ACCENT_ORANGE,
            "error": ACCENT_RED,
            "working": ACCENT_ORANGE,
        }
        icons = {
            "info": "",
            "success": "✓  ",
            "warning": "⚠  ",
            "error": "✗  ",
            "working": "⟳  ",
        }
        self._label.config(
            text=icons.get(level, "") + text,
            fg=colors.get(level, FG_DIM),
        )


__all__ = ["StatusBar"]
