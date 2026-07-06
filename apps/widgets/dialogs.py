"""Hộp thoại thông báo có thể bôi đen / copy nội dung.

``tkinter.messagebox`` không cho phép copy text trên một số máy Windows,
gây khó khăn khi cần gửi lại thông báo lỗi. Các hàm ở đây dựng hộp thoại
tuỳ chỉnh với nút "Copy" và nội dung có thể chọn bằng chuột.
"""

from __future__ import annotations

import tkinter as tk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    BG_MAIN,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    FG_TEXT,
    FG_TITLE,
)

_ICONS = {
    "info": ("i", ACCENT_BLUE),
    "warning": ("!", ACCENT_ORANGE),
    "error": ("✕", ACCENT_RED),
}


def show_message(parent: tk.Widget, title: str, message: str, kind: str = "info") -> None:
    """Hiện hộp thoại thông báo với nội dung có thể bôi đen/copy được."""

    icon, color = _ICONS.get(kind, _ICONS["info"])
    root = parent.winfo_toplevel()

    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=BG_MAIN)
    win.transient(root)

    header = tk.Frame(win, bg=BG_MAIN)
    header.pack(fill="x", padx=20, pady=(20, 10))
    tk.Label(header, text=icon, font=("Helvetica", 16, "bold"),
              bg=BG_MAIN, fg=color, width=2).pack(side="left", padx=(0, 8))
    tk.Label(header, text=title, font=("Helvetica", 13, "bold"),
              bg=BG_MAIN, fg=FG_TITLE).pack(side="left")

    line_count = message.count("\n") + 1
    text = tk.Text(win, wrap="word", font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
                    borderwidth=0, highlightthickness=1, highlightbackground=BORDER_COLOR,
                    height=min(14, max(3, line_count + 1)), padx=10, pady=10)
    text.insert("1.0", message)
    text.configure(state="disabled")
    text.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    btn_row = tk.Frame(win, bg=BG_MAIN)
    btn_row.pack(fill="x", padx=20, pady=(0, 20))

    def copy_all():
        win.clipboard_clear()
        win.clipboard_append(message)

    copy_btn = tk.Label(btn_row, text="  Copy  ", font=("Helvetica", 11), bg=BG_CARD, fg=FG_TEXT,
                        cursor="hand2", padx=8, pady=4,
                        highlightbackground=BORDER_COLOR, highlightthickness=1)
    copy_btn.pack(side="left")
    copy_btn.bind("<Button-1>", lambda e: copy_all())

    ok_btn = tk.Label(btn_row, text="  OK  ", font=("Helvetica", 11, "bold"),
                      bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=12, pady=4)
    ok_btn.pack(side="right")
    ok_btn.bind("<Button-1>", lambda e: win.destroy())
    ok_btn.bind("<Enter>", lambda e: ok_btn.config(bg=BTN_HOVER_BLUE))
    ok_btn.bind("<Leave>", lambda e: ok_btn.config(bg=ACCENT_BLUE))

    win.bind("<Return>", lambda e: win.destroy())
    win.bind("<Escape>", lambda e: win.destroy())

    win.update_idletasks()
    width = max(380, min(640, win.winfo_reqwidth()))
    height = win.winfo_reqheight()
    x = root.winfo_x() + (root.winfo_width() - width) // 2
    y = root.winfo_y() + (root.winfo_height() - height) // 2
    win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    win.grab_set()
    ok_btn.focus_set()
    win.wait_window()


def show_info(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="info")


def show_warning(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="warning")


def show_error(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="error")


__all__ = ["show_message", "show_info", "show_warning", "show_error"]
