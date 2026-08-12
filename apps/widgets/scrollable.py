"""Frame cuộn dọc dùng chung cho các trang có nội dung có thể dài hơn màn hình."""

from __future__ import annotations

import tkinter as tk


def make_scrollable_listbox(
    parent: tk.Widget, frame_bg=None, **listbox_kwargs
) -> tuple[tk.Frame, tk.Listbox]:
    """Listbox + Scrollbar dọc đã nối dây sẵn, đặt trong 1 Frame.

    Trả ``(frame, listbox)`` — gọi ``frame.pack(...)`` theo ý muốn ở nơi gọi;
    hàm này không tự pack frame (mỗi nơi gọi cần fill/padx/pady khác nhau).
    """

    frame = tk.Frame(parent, bg=frame_bg)
    sb = tk.Scrollbar(frame)
    sb.pack(side="right", fill="y")
    listbox = tk.Listbox(frame, yscrollcommand=sb.set, **listbox_kwargs)
    listbox.pack(side="left", fill="both", expand=True)
    sb.config(command=listbox.yview)
    return frame, listbox


class ScrollableFrame(tk.Frame):
    """Frame có thanh cuộn dọc. Nội dung thực tế đặt vào ``self.interior``."""

    def __init__(self, parent, bg=None, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.vscroll = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.interior = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")

        self.interior.bind("<Configure>", self._on_interior_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_interior_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._window, width=event.width)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


__all__ = ["ScrollableFrame", "make_scrollable_listbox"]
