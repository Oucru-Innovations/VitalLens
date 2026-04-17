"""Header và section card dùng chung cho các trang con."""

from __future__ import annotations

import tkinter as tk

from apps.config import (
    ACCENT_BLUE,
    BG_CARD,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    FG_DIM,
    FG_TITLE,
)


def make_header(parent: tk.Widget, controller, title_text: str) -> tk.Frame:
    """Header chung có nút "Quay lại" về HomePage."""

    # Import trễ để tránh circular import (home -> widgets -> home).
    from apps.pages.home import HomePage

    header = tk.Frame(parent, bg=BG_CARD, height=56)
    header.pack(fill="x")
    header.pack_propagate(False)

    back_btn = tk.Label(
        header,
        text="  ←  Quay lại  ",
        font=("Helvetica", 12),
        bg=BG_CARD,
        fg=ACCENT_BLUE,
        cursor="hand2",
    )
    back_btn.pack(side="left", padx=15, pady=10)
    back_btn.bind("<Button-1>", lambda e: controller.show_frame(HomePage))
    back_btn.bind(
        "<Enter>",
        lambda e: back_btn.config(
            fg=BTN_HOVER_BLUE, font=("Helvetica", 12, "underline")
        ),
    )
    back_btn.bind(
        "<Leave>",
        lambda e: back_btn.config(fg=ACCENT_BLUE, font=("Helvetica", 12)),
    )

    tk.Label(
        header,
        text=title_text,
        font=("Helvetica", 17, "bold"),
        bg=BG_CARD,
        fg=FG_TITLE,
    ).pack(side="left", padx=5)

    tk.Frame(parent, bg=BORDER_COLOR, height=1).pack(fill="x")
    return header


def make_section(parent: tk.Widget, title: str) -> tk.Frame:
    """Tạo section card có viền mỏng và title trên cùng."""

    section = tk.Frame(
        parent,
        bg=BG_CARD,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
    )
    section.pack(fill="x", padx=25, pady=(12, 0))

    tk.Label(
        section,
        text=title,
        font=("Helvetica", 12, "bold"),
        bg=BG_CARD,
        fg=FG_DIM,
    ).pack(anchor="w", padx=15, pady=(12, 5))
    return section


__all__ = ["make_header", "make_section"]
