"""Khung modal dùng chung + các hộp thoại thông báo/xác nhận copy được.

``tkinter.messagebox`` không cho copy text trên một số máy Windows và không
cuộn được: thông báo liệt kê vài chục file sẽ cao hơn màn hình, đẩy nút
Yes/No ra ngoài desktop. Mọi popup của app đi qua `Modal` để cùng một luật:

- Hàng nút (``footer``) được pack TRƯỚC nội dung, bám đáy cửa sổ → khi cửa sổ
  bị kẹp chiều cao, phần bị co là nội dung chứ không bao giờ là nút.
- Kích thước tính theo nội dung thật (không đặt cứng ``380x170`` — vỡ ngay khi
  Windows để scale 125–150%), kẹp theo màn hình, canh giữa cửa sổ cha.
- Nội dung form (``scroll=True``) nằm trong `ScrollableFrame`: màn hình thấp
  thì cuộn được, vừa màn hình thì ẩn thanh cuộn.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from apps.config import (
    ACCENT_BLUE,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    FG_TEXT,
    FG_TITLE,
)

from .scrollable import ScrollableFrame

_ICONS = {
    "info": ("i", ACCENT_BLUE),
    "warning": ("!", ACCENT_ORANGE),
    "error": ("✕", ACCENT_RED),
}

# Chặn trên/dưới cho kích thước dialog.
_MIN_WIDTH = 380
_MAX_WIDTH = 760
_MAX_SCREEN_RATIO = 0.85   # so với kích thước màn hình
_TASKBAR_MARGIN = 48       # px chừa cho taskbar Windows khi kẹp vị trí

_SECONDARY_BG = "#6b7280"
_SECONDARY_HOVER = "#4b5563"


class Modal(tk.Toplevel):
    """Popup modal: header / ``body`` / ``footer`` (hàng nút).

    Dựng nội dung vào ``self.body``, thêm nút bằng `add_button`, rồi gọi
    `run` — hàm này canh cỡ, grab và chặn cho tới khi popup đóng.
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        kind: str | None = None,
        summary: str = "",
        scroll: bool = False,
    ) -> None:
        root = parent.winfo_toplevel()
        super().__init__(root)
        self.withdraw()  # dựng xong mới hiện, khỏi nhấp nháy ở góc màn hình
        self.title(title)
        self.configure(bg=BG_CARD)
        self.transient(root)

        self.footer = tk.Frame(self, bg=BG_CARD)
        self.footer.pack(side="bottom", fill="x", padx=20, pady=(10, 16))

        header = tk.Frame(self, bg=BG_CARD)
        header.pack(side="top", fill="x", padx=20, pady=(16, 8))
        if kind:
            icon, color = _ICONS.get(kind, _ICONS["info"])
            tk.Label(header, text=icon, font=("Helvetica", 16, "bold"),
                     bg=BG_CARD, fg=color, width=2).pack(side="left", padx=(0, 8))
        tk.Label(header, text=title, font=("Helvetica", 13, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(side="left")
        if summary:
            tk.Label(header, text=summary, font=("Helvetica", 11),
                     bg=BG_CARD, fg=FG_TEXT).pack(side="left", padx=(12, 0))

        self._min_width = _MIN_WIDTH
        self._scroll: ScrollableFrame | None = None
        if scroll:
            self._scroll = ScrollableFrame(self, bg=BG_CARD)
            self._scroll.pack(fill="both", expand=True, padx=20)
            self.body = self._scroll.interior
        else:
            self.body = tk.Frame(self, bg=BG_CARD)
            self.body.pack(fill="both", expand=True, padx=20)

        self.bind("<Escape>", lambda e: self.destroy())

    def add_button(
        self, text: str, command: Callable[[], None], primary: bool = False,
        side: str = "right",
    ) -> tk.Label:
        """Nút phẳng ở footer. Nút ``side="right"`` xếp từ phải sang theo thứ tự
        gọi — thêm nút Hủy trước để nó nằm ngoài cùng như chuẩn Windows."""

        bg, hover = (ACCENT_BLUE, BTN_HOVER_BLUE) if primary else (
            _SECONDARY_BG, _SECONDARY_HOVER)
        btn = tk.Label(
            self.footer, text=f"  {text}  ",
            font=("Helvetica", 11, "bold" if primary else "normal"),
            bg=bg, fg="#ffffff", cursor="hand2", padx=12, pady=5,
        )
        btn.pack(side=side, padx=(8, 0) if side == "right" else (0, 8))
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def fit(self, recenter: bool = False) -> None:
        """Canh cỡ theo nội dung. Gọi lại khi nội dung đổi sau lúc hiện (vd dòng
        báo lỗi dài ra); ``recenter=False`` giữ nguyên vị trí cửa sổ."""

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        max_w = min(_MAX_WIDTH, int(sw * _MAX_SCREEN_RATIO))
        max_h = int(sh * _MAX_SCREEN_RATIO)

        self.update_idletasks()
        if self._scroll is not None:
            # Canvas không tự lấy cỡ theo nội dung — đặt bằng cỡ frame bên trong.
            inner, sf = self._scroll.interior, self._scroll
            sf.canvas.configure(width=inner.winfo_reqwidth(),
                                height=inner.winfo_reqheight())
            sf.vscroll.pack(side="right", fill="y", before=sf.canvas)
            self.update_idletasks()
            if self.winfo_reqheight() <= max_h:
                sf.vscroll.pack_forget()  # vừa màn hình: khỏi hiện thanh cuộn
                self.update_idletasks()

        width = max(min(self._min_width, max_w), min(max_w, self.winfo_reqwidth()))
        height = min(self.winfo_reqheight(), max_h)

        if recenter:
            root = self.master
            x = root.winfo_rootx() + (root.winfo_width() - width) // 2
            y = root.winfo_rooty() + (root.winfo_height() - height) // 2
        else:
            x, y = self.winfo_x(), self.winfo_y()
        x = max(0, min(x, sw - width))
        y = max(0, min(y, sh - height - _TASKBAR_MARGIN))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(width, _MIN_WIDTH), min(height, 160))

    def run(self, focus: tk.Widget | None = None, min_width: int = _MIN_WIDTH) -> None:
        """Canh cỡ theo nội dung (kẹp theo màn hình), grab, chờ tới khi đóng."""

        self._min_width = min_width
        root = self.master
        if root.state() == "iconic":
            # Popup transient không hiện khi cửa sổ cha đang thu nhỏ, và
            # wait_visibility bên dưới sẽ chờ mãi (vd báo lỗi cuối lô upload).
            root.deiconify()
        self.fit(recenter=True)
        self.deiconify()
        try:
            self.wait_visibility()  # grab trên cửa sổ chưa hiện → TclError
            self.grab_set()
        except tk.TclError:
            pass
        (focus or self).focus_set()
        self.wait_window()


def _text_body(win: Modal, message: str) -> tk.Text:
    """Ô text cuộn được; gọi ``configure(state="disabled")`` sau khi chèn xong
    — disabled vẫn bôi đen/copy được."""

    height = min(14, max(3, message.count("\n") + 2))
    scroll = tk.Scrollbar(win.body)
    scroll.pack(side="right", fill="y")
    text = tk.Text(win.body, wrap="word", font=("Helvetica", 11), bg=BG_INPUT,
                   fg=FG_TEXT, borderwidth=0, highlightthickness=1,
                   highlightbackground=BORDER_COLOR, height=height, padx=10,
                   pady=10, yscrollcommand=scroll.set)
    text.insert("1.0", message)
    text.pack(side="left", fill="both", expand=True)
    scroll.config(command=text.yview)
    return text


def show_message(parent: tk.Widget, title: str, message: str, kind: str = "info") -> None:
    """Hiện hộp thoại thông báo với nội dung có thể bôi đen/copy được."""

    win = Modal(parent, title, kind)
    _text_body(win, message).configure(state="disabled")
    win.add_button("Copy", lambda: win.copy_to_clipboard(message), side="left")
    ok = win.add_button("OK", win.destroy, primary=True)
    win.bind("<Return>", lambda e: win.destroy())
    win.run(focus=ok)


def ask_yes_no(
    parent: tk.Widget, title: str, message: str, kind: str = "warning",
    yes_text: str = "Đồng ý", no_text: str = "Hủy",
) -> bool:
    """Thay ``messagebox.askyesno``: cuộn được nên danh sách dài không đẩy
    nút ra khỏi màn hình. Enter = đồng ý, Esc/đóng cửa sổ = hủy."""

    result = [False]
    win = Modal(parent, title, kind)
    _text_body(win, message).configure(state="disabled")

    def yes() -> None:
        result[0] = True
        win.destroy()

    win.add_button("Copy", lambda: win.copy_to_clipboard(message), side="left")
    win.add_button(no_text, win.destroy)
    ok = win.add_button(yes_text, yes, primary=True)
    win.bind("<Return>", lambda e: yes())
    win.run(focus=ok)
    return result[0]


def ask_owner(parent: tk.Widget, initial: str = "") -> str | None:
    """Hỏi tên người tải dữ liệu (owner) trước khi upload API — tự do, chỉ cần
    không rỗng (server không ràng buộc định dạng). Trả None nếu người dùng hủy."""

    result: list[str | None] = [None]
    win = Modal(parent, "Người dùng", scroll=True)
    tk.Label(win.body, text="Tên người dùng đang tải dữ liệu (owner):",
             font=("Helvetica", 11), bg=BG_CARD, fg=FG_TEXT).pack(anchor="w")
    owner_var = tk.StringVar(value=initial)
    entry = tk.Entry(win.body, textvariable=owner_var, font=("Helvetica", 12),
                     bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                     borderwidth=1, highlightthickness=1, highlightcolor=ACCENT_BLUE)
    entry.pack(fill="x", pady=(4, 2), ipady=6)
    entry.select_range(0, "end")
    error = tk.Label(win.body, text="", font=("Helvetica", 9), bg=BG_CARD,
                     fg=ACCENT_RED)
    error.pack(anchor="w")

    def on_ok() -> None:
        val = owner_var.get().strip()
        if not val:
            entry.config(highlightcolor=ACCENT_RED, highlightbackground=ACCENT_RED)
            error.config(text="Chưa nhập tên người dùng.")
            entry.focus_set()
            return
        result[0] = val
        win.destroy()

    win.add_button("Hủy", win.destroy)
    win.add_button("✓  OK", on_ok, primary=True)
    entry.bind("<Return>", lambda e: on_ok())
    win.run(focus=entry)
    return result[0]


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

    win = Modal(parent, title, kind, summary)
    text = _text_body(win, "")
    text.configure(height=16)

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
    win.add_button("Copy", lambda: win.copy_to_clipboard(copy_text), side="left")
    ok = win.add_button("OK", win.destroy, primary=True)
    win.bind("<Return>", lambda e: win.destroy())
    win.run(focus=ok, min_width=520)


def show_info(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="info")


def show_warning(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="warning")


def show_error(parent: tk.Widget, title: str, message: str) -> None:
    show_message(parent, title, message, kind="error")


__all__ = [
    "Modal",
    "ask_owner",
    "ask_yes_no",
    "show_message",
    "show_report",
    "show_info",
    "show_warning",
    "show_error",
]
