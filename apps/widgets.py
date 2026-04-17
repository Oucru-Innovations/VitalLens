"""Custom widgets dùng chung cho các trang."""

import tkinter as tk
from apps.config import (
    BG_MAIN, BG_CARD, FG_DIM, FG_TITLE,
    ACCENT_BLUE, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED,
    BTN_HOVER_BLUE, BORDER_COLOR,
)


class StyledButton(tk.Button):
    """Nút tùy chỉnh với hiệu ứng hover."""

    def __init__(self, parent, text="", command=None,
                 bg_color=ACCENT_BLUE, hover_color=BTN_HOVER_BLUE,
                 fg_color="#000000", font_size=14, **kwargs):
        self._bg = bg_color
        self._hover = hover_color
        super().__init__(
            parent, text=text, command=command,
            bg=bg_color, fg=fg_color, activebackground=hover_color,
            activeforeground=fg_color, font=("Helvetica", font_size, "bold"),
            relief="flat", borderwidth=0, cursor="hand2",
            padx=30, pady=12, **kwargs,
        )
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))

    def set_state(self, state):
        if state == "disabled":
            self.config(state="disabled", bg="#b0b0b0")
        else:
            self.config(state="normal", bg=self._bg)


class StatusBar(tk.Frame):
    """Thanh trạng thái với icon và màu sắc."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG_CARD, **kwargs)
        self._label = tk.Label(self, text="", bg=BG_CARD, fg=FG_DIM,
                               font=("Helvetica", 11), anchor="w", wraplength=600)
        self._label.pack(fill="x", padx=15, pady=8)

    def set(self, text, level="info"):
        colors = {"info": FG_DIM, "success": ACCENT_GREEN, "error": ACCENT_RED, "working": ACCENT_ORANGE}
        icons = {"info": "", "success": "✓  ", "error": "✗  ", "working": "⟳  "}
        self._label.config(text=icons.get(level, "") + text, fg=colors.get(level, FG_DIM))


def make_header(parent, controller, title_text):
    """Header chung cho các trang con, có nút quay lại HomePage."""
    from apps.pages.home import HomePage

    header = tk.Frame(parent, bg=BG_CARD, height=56)
    header.pack(fill="x")
    header.pack_propagate(False)

    back_btn = tk.Label(header, text="  ←  Quay lại  ", font=("Helvetica", 12),
                        bg=BG_CARD, fg=ACCENT_BLUE, cursor="hand2")
    back_btn.pack(side="left", padx=15, pady=10)
    back_btn.bind("<Button-1>", lambda e: controller.show_frame(HomePage))
    back_btn.bind("<Enter>", lambda e: back_btn.config(fg=BTN_HOVER_BLUE, font=("Helvetica", 12, "underline")))
    back_btn.bind("<Leave>", lambda e: back_btn.config(fg=ACCENT_BLUE, font=("Helvetica", 12)))

    tk.Label(header, text=title_text, font=("Helvetica", 17, "bold"),
             bg=BG_CARD, fg=FG_TITLE).pack(side="left", padx=5)

    tk.Frame(parent, bg=BORDER_COLOR, height=1).pack(fill="x")
    return header


def make_section(parent, title):
    """Tạo section card với title."""
    section = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER_COLOR, highlightthickness=1)
    section.pack(fill="x", padx=25, pady=(12, 0))

    tk.Label(section, text=title, font=("Helvetica", 12, "bold"),
             bg=BG_CARD, fg=FG_DIM).pack(anchor="w", padx=15, pady=(12, 5))
    return section
