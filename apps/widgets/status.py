"""Thanh trạng thái cho các trang."""

from __future__ import annotations

import tkinter as tk

from apps.config import ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED, BG_CARD, FG_DIM


class StatusBar(tk.Frame):
    """Thanh trạng thái với icon và màu theo mức độ."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(parent, bg=BG_CARD, **kwargs)
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
        colors = {
            "info": FG_DIM,
            "success": ACCENT_GREEN,
            "error": ACCENT_RED,
            "working": ACCENT_ORANGE,
        }
        icons = {
            "info": "",
            "success": "✓  ",
            "error": "✗  ",
            "working": "⟳  ",
        }
        self._label.config(
            text=icons.get(level, "") + text,
            fg=colors.get(level, FG_DIM),
        )


__all__ = ["StatusBar"]
