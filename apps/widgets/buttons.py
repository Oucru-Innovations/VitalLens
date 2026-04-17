"""Nút bấm tuỳ chỉnh với hiệu ứng hover."""

from __future__ import annotations

import tkinter as tk

from apps.config import ACCENT_BLUE, BTN_HOVER_BLUE


class StyledButton(tk.Button):
    """Nút tuỳ chỉnh với màu nền, hover và trạng thái disabled."""

    def __init__(
        self,
        parent: tk.Widget,
        text: str = "",
        command=None,
        bg_color: str = ACCENT_BLUE,
        hover_color: str = BTN_HOVER_BLUE,
        fg_color: str = "#000000",
        font_size: int = 14,
        **kwargs,
    ) -> None:
        self._bg = bg_color
        self._hover = hover_color
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg_color,
            fg=fg_color,
            activebackground=hover_color,
            activeforeground=fg_color,
            font=("Helvetica", font_size, "bold"),
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=30,
            pady=12,
            **kwargs,
        )
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))

    def set_state(self, state: str) -> None:
        if state == "disabled":
            self.config(state="disabled", bg="#b0b0b0")
        else:
            self.config(state="normal", bg=self._bg)


__all__ = ["StyledButton"]
