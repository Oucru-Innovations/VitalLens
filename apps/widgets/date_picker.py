"""Popup chọn ngày dạng lịch tháng.

Thiết kế ưu tiên ĐỘ TIN CẬY trên Windows:
- Dùng ``Toplevel`` bình thường (không ``overrideredirect``) → tránh lỗi
  ``grab failed: window not viewable`` và các trục trặc focus của cửa sổ
  không viền.
- Vị trí: luôn hiện **ngay dưới ô ngày** (tham số ``anchor``); nếu không có
  anchor thì căn giữa cửa sổ cha. Không nhảy ra góc màn hình.
- Modal (``grab_set`` sau ``wait_visibility``), đóng bằng ``Esc`` / nút ✕ cửa
  sổ. Có nút "Hôm nay" và "Xóa" cho thao tác nhanh.
"""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import datetime
from typing import Callable, Optional

from apps.config import (
    ACCENT_BLUE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    FG_DIM,
    FG_TEXT,
    FG_TITLE,
)

_WEEKDAYS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


class DatePicker(tk.Toplevel):
    """Hộp thoại chọn ngày (định dạng ``dd-mm-yyyy``).

    Args:
        parent: widget cha.
        initial_date: chuỗi ``"dd-mm-yyyy"`` để khởi tạo vị trí hiển thị.
        on_select: callback nhận chuỗi ngày được chọn (chuỗi rỗng khi "Xóa").
        anchor: widget để neo popup (thường là ô ngày). Popup hiện ngay dưới.
        allow_clear: hiện nút "Xóa" để trả về chuỗi rỗng.
    """

    def __init__(
        self,
        parent: tk.Widget,
        initial_date: Optional[str] = None,
        on_select: Optional[Callable[[str], None]] = None,
        anchor: Optional[tk.Widget] = None,
        allow_clear: bool = True,
    ) -> None:
        super().__init__(parent)
        self.on_select = on_select
        self._anchor = anchor
        self._allow_clear = allow_clear
        self._closed = False

        self.title("📅 Chọn ngày")
        self.resizable(False, False)
        self.configure(bg=BG_CARD)
        self.withdraw()  # ẩn khi đang dựng để không nhấp nháy ở góc màn hình

        if initial_date:
            try:
                self.current_date: Optional[datetime] = datetime.strptime(
                    initial_date, "%d-%m-%Y"
                )
            except ValueError:
                self.current_date = None
        else:
            self.current_date = None

        base = self.current_date or datetime.now()
        self.year = base.year
        self.month = base.month
        self._today = datetime.now().date()

        self._build_ui()
        self._update_calendar()
        self._place_near_anchor()

        # Hiện ra rồi mới grab (tránh lỗi "window not viewable").
        self.deiconify()
        self.transient(parent.winfo_toplevel())
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()

        self.bind("<Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_CARD)
        header.pack(fill="x", padx=8, pady=(8, 4))

        self._nav_btn(header, "‹", self._prev_month).pack(side="left")

        self.lbl_month_year = tk.Label(
            header, font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TITLE
        )
        self.lbl_month_year.pack(side="left", expand=True)

        self._nav_btn(header, "›", self._next_month).pack(side="right")

        self.cal_frame = tk.Frame(self, bg=BG_CARD)
        self.cal_frame.pack(fill="both", expand=True, padx=8)

        for i, d in enumerate(_WEEKDAYS):
            tk.Label(
                self.cal_frame,
                text=d,
                fg=ACCENT_RED if d == "CN" else FG_DIM,
                font=("Helvetica", 9, "bold"),
                bg=BG_CARD,
                width=4,
                pady=2,
            ).grid(row=0, column=i, sticky="nsew")
        for i in range(7):
            self.cal_frame.columnconfigure(i, weight=1)

        footer = tk.Frame(self, bg=BG_CARD)
        footer.pack(fill="x", padx=8, pady=(4, 8))
        self._text_btn(footer, "Hôm nay", ACCENT_BLUE, self._select_today).pack(
            side="left"
        )
        if self._allow_clear:
            self._text_btn(footer, "Xóa", ACCENT_RED, self._clear).pack(side="right")

    def _nav_btn(self, parent: tk.Widget, text: str, cmd) -> tk.Label:
        btn = tk.Label(
            parent,
            text=text,
            font=("Helvetica", 14, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="hand2",
            width=2,
        )
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.config(fg=BTN_HOVER_BLUE))
        btn.bind("<Leave>", lambda e: btn.config(fg=ACCENT_BLUE))
        return btn

    def _text_btn(self, parent: tk.Widget, text: str, color: str, cmd) -> tk.Label:
        btn = tk.Label(
            parent,
            text=text,
            font=("Helvetica", 10, "bold"),
            bg=BG_CARD,
            fg=color,
            cursor="hand2",
            padx=6,
            pady=2,
        )
        btn.bind("<Button-1>", lambda e: cmd())
        return btn

    def _update_calendar(self) -> None:
        self.lbl_month_year.config(text=f"Tháng {self.month:02d} / {self.year}")
        for widget in self.cal_frame.grid_slaves():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()

        cal = calendar.monthcalendar(self.year, self.month)
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                is_selected = (
                    self.current_date is not None
                    and self.year == self.current_date.year
                    and self.month == self.current_date.month
                    and day == self.current_date.day
                )
                is_today = (
                    self.year == self._today.year
                    and self.month == self._today.month
                    and day == self._today.day
                )
                cell = tk.Label(
                    self.cal_frame,
                    text=str(day),
                    font=("Helvetica", 10),
                    bg=BG_INPUT,
                    fg=FG_TEXT,
                    cursor="hand2",
                    width=4,
                    pady=4,
                )
                if is_selected:
                    cell.config(
                        bg=ACCENT_BLUE, fg="white", font=("Helvetica", 10, "bold")
                    )
                elif is_today:
                    cell.config(
                        fg=ACCENT_BLUE,
                        font=("Helvetica", 10, "bold"),
                        highlightbackground=ACCENT_BLUE,
                        highlightthickness=1,
                    )
                cell.bind("<Button-1>", lambda e, d=day: self._select(d))
                if not is_selected:
                    cell.bind("<Enter>", lambda e, w=cell: w.config(bg="#dbeafe"))
                    cell.bind("<Leave>", lambda e, w=cell: w.config(bg=BG_INPUT))
                cell.grid(row=r + 1, column=c, sticky="nsew", padx=1, pady=1)

    # ------------------------------------------------------------------
    # Vị trí
    # ------------------------------------------------------------------

    def _place_near_anchor(self) -> None:
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        anchor = self._anchor
        if anchor is not None and anchor.winfo_ismapped():
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 2
            if y + h > sh:  # tràn xuống dưới → hiện phía trên ô
                y = anchor.winfo_rooty() - h - 2
        else:
            top = self.master.winfo_toplevel()
            x = top.winfo_rootx() + (top.winfo_width() - w) // 2
            y = top.winfo_rooty() + (top.winfo_height() - h) // 2

        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Điều hướng / chọn
    # ------------------------------------------------------------------

    def _prev_month(self) -> None:
        if self.month == 1:
            self.month, self.year = 12, self.year - 1
        else:
            self.month -= 1
        self._update_calendar()

    def _next_month(self) -> None:
        if self.month == 12:
            self.month, self.year = 1, self.year + 1
        else:
            self.month += 1
        self._update_calendar()

    def _select(self, day: int) -> None:
        if self.on_select:
            self.on_select(f"{day:02d}-{self.month:02d}-{self.year}")
        self._close()

    def _select_today(self) -> None:
        if self.on_select:
            self.on_select(datetime.now().strftime("%d-%m-%Y"))
        self._close()

    def _clear(self) -> None:
        if self.on_select:
            self.on_select("")
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


__all__ = ["DatePicker"]
