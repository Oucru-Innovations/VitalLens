"""Popup nhập cấu hình kết nối (URL + token) — thay cho việc sửa `.env` tay.

Bước hỏng nhiều nhất trong hướng dẫn cài đặt là "đổi tên `.env.example` thành
`.env` rồi mở bằng Notepad": Windows Explorer không cho đặt tên bắt đầu bằng
dấu chấm, và người dùng hay sửa nhầm định dạng. Dialog này ghi thẳng vào
`%APPDATA%\\VitalLens\\.env` (xem `apps/services/user_config.py`) nên bản phát
hành không cần kèm file config nào.

Giữ nguyên phong cách popup đăng nhập SFTP ở `apps/widgets/sftp.py`.
"""

from __future__ import annotations

import os
import tkinter as tk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    BTN_HOVER_BLUE,
    FG_DIM,
    FG_TEXT,
    FG_TITLE,
    is_secure_endpoint,
)
from apps.services.user_config import USER_ENV_PATH, save_user_env

__all__ = ["show_settings_dialog"]

_FIELDS = [
    ("API_UPLOAD_URL", "Địa chỉ server (API_UPLOAD_URL)", False),
    ("API_BEARER_TOKEN", "Token được cấp riêng (API_BEARER_TOKEN)", True),
    ("API_UPLOAD_OWNER", "Email mặc định (API_UPLOAD_OWNER)", False),
]


def show_settings_dialog(parent: tk.Widget) -> bool:
    """Hiện popup cấu hình. Trả True nếu người dùng đã lưu."""

    dialog = tk.Toplevel(parent)
    dialog.title("Cấu hình kết nối")
    dialog.resizable(False, False)
    dialog.configure(bg=BG_CARD)
    dialog.grab_set()

    dialog.update_idletasks()
    w, h = 520, 350
    top = parent.winfo_toplevel()
    x = top.winfo_x() + (top.winfo_width() - w) // 2
    y = top.winfo_y() + (top.winfo_height() - h) // 2
    dialog.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(
        dialog, text="Cấu hình kết nối", font=("Helvetica", 12, "bold"),
        bg=BG_CARD, fg=FG_TITLE,
    ).pack(padx=20, pady=(15, 2), anchor="w")
    tk.Label(
        dialog, text=f"Lưu tại {USER_ENV_PATH}", font=("Helvetica", 9),
        bg=BG_CARD, fg=FG_DIM, wraplength=w - 40, justify="left",
    ).pack(padx=20, pady=(0, 10), anchor="w")

    entries: dict[str, tk.Entry] = {}
    for key, label, secret in _FIELDS:
        tk.Label(
            dialog, text=label, font=("Helvetica", 10), bg=BG_CARD, fg=FG_TEXT
        ).pack(padx=20, anchor="w")
        entry = tk.Entry(
            dialog, font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
            insertbackground=FG_TEXT, borderwidth=1, highlightthickness=1,
            highlightcolor=ACCENT_BLUE, show="●" if secret else "",
        )
        entry.insert(0, os.environ.get(key, ""))
        entry.pack(fill="x", padx=20, pady=(2, 8), ipady=5)
        entries[key] = entry

    hint = tk.Label(
        dialog, text="", font=("Helvetica", 9), bg=BG_CARD, fg=ACCENT_RED,
        wraplength=w - 40, justify="left",
    )
    hint.pack(padx=20, anchor="w")

    saved = [False]
    warned = [False]

    def on_save(event=None):
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
            return
        try:
            save_user_env(values)
        except OSError as exc:
            hint.config(text=f"Không ghi được file cấu hình: {exc}")
            return
        saved[0] = True
        dialog.destroy()

    dialog.bind("<Return>", on_save)
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    btn_frame = tk.Frame(dialog, bg=BG_CARD)
    btn_frame.pack(pady=(12, 15))

    ok_btn = tk.Label(
        btn_frame, text="  ✓  Lưu  ", font=("Helvetica", 11, "bold"),
        bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=12, pady=5,
    )
    ok_btn.pack(side="left", padx=8)
    ok_btn.bind("<Button-1>", on_save)
    ok_btn.bind("<Enter>", lambda e: ok_btn.config(bg=BTN_HOVER_BLUE))
    ok_btn.bind("<Leave>", lambda e: ok_btn.config(bg=ACCENT_BLUE))

    cancel_btn = tk.Label(
        btn_frame, text="  Hủy  ", font=("Helvetica", 11),
        bg="#6b7280", fg="#ffffff", cursor="hand2", padx=12, pady=5,
    )
    cancel_btn.pack(side="left", padx=8)
    cancel_btn.bind("<Button-1>", lambda e: dialog.destroy())
    cancel_btn.bind("<Enter>", lambda e: cancel_btn.config(bg="#4b5563"))
    cancel_btn.bind("<Leave>", lambda e: cancel_btn.config(bg="#6b7280"))

    dialog.wait_window()
    return saved[0]
