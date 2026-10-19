"""Popup nhập cấu hình kết nối (URL + token) — thay cho việc sửa `.env` tay.

Bước hỏng nhiều nhất trong hướng dẫn cài đặt là "đổi tên `.env.example` thành
`.env` rồi mở bằng Notepad": Windows Explorer không cho đặt tên bắt đầu bằng
dấu chấm, và người dùng hay sửa nhầm định dạng. Dialog này ghi thẳng vào `.env`
CẠNH EXE (xem `apps/services/user_config.py`; lui về `%APPDATA%\\VitalLens\\.env`
khi thư mục đó chỉ-đọc) nên bản phát hành không cần kèm file config nào.
"""

from __future__ import annotations

import os
import tkinter as tk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    FG_DIM,
    FG_TEXT,
    is_secure_endpoint,
)
from apps.services.user_config import USER_ENV_PATH, save_user_env

from .dialogs import Modal

__all__ = ["show_settings_dialog"]

_FIELDS = [
    ("API_UPLOAD_URL", "Địa chỉ server (API_UPLOAD_URL)", False),
    ("API_BEARER_TOKEN", "Token được cấp riêng (API_BEARER_TOKEN)", True),
    ("API_UPLOAD_OWNER", "Email mặc định (API_UPLOAD_OWNER)", False),
]
_WIDTH = 520
_WRAP = _WIDTH - 60


def show_settings_dialog(parent: tk.Widget) -> bool:
    """Hiện popup cấu hình. Trả True nếu người dùng đã lưu."""

    dialog = Modal(parent, "Cấu hình kết nối", scroll=True)
    body = dialog.body

    tk.Label(
        body, text=f"Lưu tại {USER_ENV_PATH}", font=("Helvetica", 9),
        bg=BG_CARD, fg=FG_DIM, wraplength=_WRAP, justify="left",
    ).pack(pady=(0, 10), anchor="w")

    entries: dict[str, tk.Entry] = {}
    for key, label, secret in _FIELDS:
        tk.Label(
            body, text=label, font=("Helvetica", 10), bg=BG_CARD, fg=FG_TEXT
        ).pack(anchor="w")
        entry = tk.Entry(
            body, font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
            insertbackground=FG_TEXT, borderwidth=1, highlightthickness=1,
            highlightcolor=ACCENT_BLUE, show="●" if secret else "",
        )
        entry.insert(0, os.environ.get(key, ""))
        entry.pack(fill="x", pady=(2, 8), ipady=5)
        entries[key] = entry

    hint = tk.Label(
        body, text="", font=("Helvetica", 9), bg=BG_CARD, fg=ACCENT_RED,
        wraplength=_WRAP, justify="left",
    )
    hint.pack(anchor="w")

    saved = [False]
    warned = [False]

    def on_save():
        values = {k: e.get().strip() for k, e in entries.items()}
        url_entry = entries["API_UPLOAD_URL"]
        # Cảnh báo chứ KHÔNG chặn: `config._warn_insecure_endpoint` đã chọn
        # cách đó, và chặn ở đây thì dialog vô dụng với người đang phải dùng
        # endpoint http:// — họ quay lại sửa .env bằng Notepad, mất luôn cả
        # cảnh báo. Hiện đúng lúc người dùng gõ vào thì có ích hơn một dòng log.
        if not is_secure_endpoint(values["API_UPLOAD_URL"]) and not warned[0]:
            warned[0] = True
            url_entry.config(highlightcolor=ACCENT_RED)
            url_entry.focus_set()
            hint.config(
                text="⚠ http:// gửi token và dữ liệu bệnh nhân qua mạng KHÔNG "
                     "mã hoá — ai trên cùng đường truyền cũng đọc được. Hãy đổi "
                     "sang https://. Bấm Lưu lần nữa nếu vẫn muốn dùng http://."
            )
            dialog.fit()
            return
        try:
            save_user_env(values)
        except OSError as exc:
            hint.config(text=f"Không ghi được file cấu hình: {exc}")
            dialog.fit()
            return
        saved[0] = True
        dialog.destroy()

    dialog.bind("<Return>", lambda e: on_save())
    dialog.add_button("Hủy", dialog.destroy)
    dialog.add_button("✓  Lưu", on_save, primary=True)
    dialog.run(focus=entries["API_UPLOAD_URL"], min_width=_WIDTH)
    return saved[0]
