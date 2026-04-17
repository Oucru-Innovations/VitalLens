"""Popup chọn ngày đơn giản dạng lịch tháng."""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import datetime
from typing import Callable, Optional

from apps.config import ACCENT_BLUE, BG_CARD, BG_INPUT, FG_DIM


class DatePicker(tk.Toplevel):
    """Hộp thoại chọn ngày.

    Args:
        parent: widget cha.
        initial_date: chuỗi ``"dd-mm-yyyy"`` để khởi tạo vị trí.
        on_select: callback nhận chuỗi ngày được chọn.
    """

    def __init__(
        self,
        parent: tk.Widget,
        initial_date: Optional[str] = None,
        on_select: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.title("Chọn Ngày")
        self.geometry("280x250")
        self.resizable(False, False)

        self.on_select = on_select
        if initial_date:
            try:
                self.current_date = datetime.strptime(initial_date, "%d-%m-%Y")
            except ValueError:
                self.current_date = datetime.now()
        else:
            self.current_date = datetime.now()

        self.year = self.current_date.year
        self.month = self.current_date.month

        self._build_ui()
        self._update_calendar()

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_CARD)
        header.pack(fill="x", pady=5)

        tk.Button(header, text="<", command=self._prev_month, width=3).pack(
            side="left", padx=5
        )

        self.lbl_month_year = tk.Label(
            header, font=("Helvetica", 11, "bold"), bg=BG_CARD
        )
        self.lbl_month_year.pack(side="left", expand=True)

        tk.Button(header, text=">", command=self._next_month, width=3).pack(
            side="right", padx=5
        )

        self.cal_frame = tk.Frame(self, bg=BG_CARD)
        self.cal_frame.pack(fill="both", expand=True, padx=5, pady=5)

        for i, d in enumerate(["T2", "T3", "T4", "T5", "T6", "T7", "CN"]):
            tk.Label(
                self.cal_frame,
                text=d,
                fg=FG_DIM,
                font=("Helvetica", 9, "bold"),
                bg=BG_CARD,
            ).grid(row=0, column=i, sticky="nsew")
        for i in range(7):
            self.cal_frame.columnconfigure(i, weight=1)

    def _update_calendar(self) -> None:
        self.lbl_month_year.config(text=f"{self.month:02d}/{self.year}")
        for widget in self.cal_frame.grid_slaves():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()

        cal = calendar.monthcalendar(self.year, self.month)
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                btn = tk.Button(
                    self.cal_frame,
                    text=str(day),
                    relief="flat",
                    bg=BG_INPUT,
                    command=lambda d=day: self._select(d),
                )
                if (
                    self.year == self.current_date.year
                    and self.month == self.current_date.month
                    and day == self.current_date.day
                ):
                    btn.config(bg=ACCENT_BLUE, fg="white")
                btn.grid(row=r + 1, column=c, sticky="nsew", padx=1, pady=1)

    def _prev_month(self) -> None:
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self._update_calendar()

    def _next_month(self) -> None:
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self._update_calendar()

    def _select(self, day: int) -> None:
        if self.on_select:
            selected = f"{day:02d}-{self.month:02d}-{self.year}"
            self.on_select(selected)
        self.destroy()


__all__ = ["DatePicker"]
