"""Hộp thoại thông báo có thể bôi đen / copy nội dung.

``tkinter.messagebox`` không cho phép copy text trên một số máy Windows,
gây khó khăn khi cần gửi lại thông báo lỗi. Các hàm ở đây dựng hộp thoại
tuỳ chỉnh với nút "Copy" và nội dung có thể chọn bằng chuột.

`show_message` (một khối text) và `show_report` (nhiều nhóm có màu) dùng chung
khung dialog ở `_dialog_shell` + `_finish_dialog`, nên sửa canh giữa/phím tắt/
kích thước một lần là cả hai cùng nhận.
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

# Chặn trên/dưới cho bề rộng và chiều cao dialog (px).
_MIN_WIDTH = 380
_MAX_WIDTH = 760
_MAX_HEIGHT_RATIO = 0.85  # so với chiều cao màn hình


def _dialog_shell(
    parent: tk.Widget, title: str, kind: str, summary: str = ""
) -> tuple[tk.Toplevel, tk.Frame]:
    """Dựng khung dialog (header + vùng nội dung rỗng). Trả (win, content)."""

    icon, color = _ICONS.get(kind, _ICONS["info"])
    root = parent.winfo_toplevel()

    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=BG_MAIN)
    win.transient(root)

    header = tk.Frame(win, bg=BG_MAIN)
    header.pack(fill="x", padx=20, pady=(20, 8))
    tk.Label(header, text=icon, font=("Helvetica", 16, "bold"),
             bg=BG_MAIN, fg=color, width=2).pack(side="left", padx=(0, 8))
    tk.Label(header, text=title, font=("Helvetica", 13, "bold"),
             bg=BG_MAIN, fg=FG_TITLE).pack(side="left")
    if summary:
        tk.Label(header, text=summary, font=("Helvetica", 11),
                 bg=BG_MAIN, fg=FG_TEXT).pack(side="left", padx=(12, 0))

    content = tk.Frame(win, bg=BG_MAIN)
    content.pack(fill="both", expand=True, padx=20, pady=(0, 10))
    return win, content


def _finish_dialog(
    win: tk.Toplevel, copy_text: str, min_width: int = _MIN_WIDTH
) -> None:
    """Thêm hàng nút Copy/OK, canh giữa, rồi chạy modal cho tới khi đóng."""

    btn_row = tk.Frame(win, bg=BG_MAIN)
    btn_row.pack(fill="x", padx=20, pady=(0, 20))

    def copy_all():
        win.clipboard_clear()
        win.clipboard_append(copy_text)

    copy_btn = tk.Label(btn_row, text="  Copy  ", font=("Helvetica", 11), bg=BG_CARD,
                        fg=FG_TEXT, cursor="hand2", padx=8, pady=4,
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

    root = win.master
    win.update_idletasks()
    width = max(min_width, min(_MAX_WIDTH, win.winfo_reqwidth()))
    # Chặn chiều cao theo màn hình: nội dung dài không được tràn khỏi desktop.
    max_h = int(win.winfo_screenheight() * _MAX_HEIGHT_RATIO)
    height = min(win.winfo_reqheight(), max_h)
    x = root.winfo_x() + (root.winfo_width() - width) // 2
    y = root.winfo_y() + (root.winfo_height() - height) // 2
    win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    win.grab_set()
    ok_btn.focus_set()
    win.wait_window()


def show_message(parent: tk.Widget, title: str, message: str, kind: str = "info") -> None:
    """Hiện hộp thoại thông báo với nội dung có thể bôi đen/copy được."""

    win, content = _dialog_shell(parent, title, kind)

    line_count = message.count("\n") + 1
    text = tk.Text(content, wrap="word", font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
                   borderwidth=0, highlightthickness=1, highlightbackground=BORDER_COLOR,
                   height=min(14, max(3, line_count + 1)), padx=10, pady=10)
    text.insert("1.0", message)
    text.configure(state="disabled")
    text.pack(fill="both", expand=True)

    _finish_dialog(win, message)


def show_report(
    parent: tk.Widget,
    title: str,
    summary: str,
    groups: list[tuple[str, str, list[str]]],
    kind: str = "info",
) -> None:
    """Hộp thoại báo cáo nhiều nhóm, cuộn được và copy được.

    `groups` là danh sách ``(tiêu đề nhóm, màu chữ, các dòng)`` — ví dụ nhóm
    "đã upload" màu xanh và nhóm "chưa upload" màu đỏ. Nhóm rỗng bị bỏ qua.
    """

    win, content = _dialog_shell(parent, title, kind, summary)

    scroll = tk.Scrollbar(content)
    scroll.pack(side="right", fill="y")

    text = tk.Text(content, wrap="word", font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
                   borderwidth=0, highlightthickness=1, highlightbackground=BORDER_COLOR,
                   height=16, padx=10, pady=10, yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.config(command=text.yview)

    plain: list[str] = []
    for i, (heading, group_color, lines) in enumerate(groups):
        if not lines:
            continue
        tag = f"head{i}"
        text.tag_configure(tag, foreground=group_color,
                           font=("Helvetica", 11, "bold"), spacing1=8 if plain else 0)
        text.insert("end", f"{heading}\n", tag)
        plain.append(heading)
        for line in lines:
            text.insert("end", f"    {line}\n")
            plain.append(f"    {line}")

    text.configure(state="disabled")

    copy_text = "\n".join(([summary] if summary else []) + plain)
    _finish_dialog(win, copy_text, min_width=520)


def show_info(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="info")


def show_warning(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="warning")


def show_error(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="error")


__all__ = ["show_message", "show_report", "show_info", "show_warning", "show_error"]
