"""Popup đăng nhập SFTP dùng chung cho các trang cần upload lên SFTP.

Lần đầu một trang gọi `ensure_sftp_backend()` trong session, popup sẽ hỏi
username/password rồi kết nối trong background thread. Các lần gọi sau
tái sử dụng kết nối đã lưu ở `SftpSessionManager` (apps.services.sftp_session)
- singleton dùng chung cho cả app, tự đóng khi app thoát.

"""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional

from apps.config import (
    ACCENT_BLUE,
    ACCENT_RED,
    BG_CARD,
    BG_INPUT,
    FG_TEXT,
    SFTP_DEMO_MODE,
    SFTP_HOST,
    SFTP_PORT,
    SFTP_UPLOAD_DEFAULT_USER,
)
from apps.services.sftp_session import SftpSessionManager
from apps.services.storage import LocalBackend, StorageBackend
from apps.services.upload_api import SftpUploader, Uploader

from .dialogs import Modal

_lock = threading.Lock()
_connecting = False
_pending: list[tuple[Callable[[StorageBackend], None], Callable[[str], None]]] = []


def _prompt_login(parent: tk.Widget) -> Optional[tuple[str, str]]:
    """Hiện popup hỏi username/password SFTP. Trả None nếu user hủy."""

    dialog = Modal(parent, "Đăng nhập SFTP để upload", scroll=True)
    body = dialog.body

    tk.Label(
        body, text="Username:", font=("Helvetica", 10), bg=BG_CARD, fg=FG_TEXT
    ).pack(anchor="w")
    user_var = tk.StringVar(value=SFTP_UPLOAD_DEFAULT_USER)
    user_entry = tk.Entry(
        body,
        textvariable=user_var,
        font=("Helvetica", 11),
        bg=BG_INPUT,
        fg=FG_TEXT,
        insertbackground=FG_TEXT,
        borderwidth=1,
        highlightthickness=1,
        highlightcolor=ACCENT_BLUE,
    )
    user_entry.pack(fill="x", pady=(2, 8), ipady=5)

    tk.Label(
        body, text="Password:", font=("Helvetica", 10), bg=BG_CARD, fg=FG_TEXT
    ).pack(anchor="w")
    pass_var = tk.StringVar(value="")
    pass_entry = tk.Entry(
        body,
        textvariable=pass_var,
        font=("Helvetica", 11),
        show="●",
        bg=BG_INPUT,
        fg=FG_TEXT,
        insertbackground=FG_TEXT,
        borderwidth=1,
        highlightthickness=1,
        highlightcolor=ACCENT_BLUE,
    )
    pass_entry.pack(fill="x", pady=(2, 8), ipady=5)

    result: list[Optional[tuple[str, str]]] = [None]

    def on_ok(event=None):
        username = user_var.get().strip()
        password = pass_var.get()
        if not username or not password:
            user_entry.config(highlightcolor=ACCENT_RED)
            pass_entry.config(highlightcolor=ACCENT_RED)
            return
        result[0] = (username, password)
        dialog.destroy()

    pass_entry.bind("<Return>", on_ok)
    dialog.add_button("Hủy", dialog.destroy)
    dialog.add_button("✓  Kết nối", on_ok, primary=True)
    dialog.run(focus=pass_entry)
    return result[0]


def _finish(ok: bool, payload) -> None:
    """Giải quyết tất cả các lệnh gọi đang xếp hàng chờ kết nối này."""

    global _connecting
    with _lock:
        callbacks, _pending[:] = list(_pending), []
        _connecting = False
    for on_ready, on_error in callbacks:
        (on_ready if ok else on_error)(payload)


def ensure_sftp_backend(
    parent: tk.Widget,
    on_ready: Callable[[StorageBackend], None],
    on_error: Callable[[str], None],
) -> None:
    """Đảm bảo có một backend SFTP dùng được rồi gọi `on_ready(backend)`.

    Chỉ lệnh gọi đầu tiên trong session (hoặc đầu tiên trong lúc chưa ai
    kết nối) hỏi username/password và mở kết nối; các lệnh gọi khác đến
    trong lúc đang kết nối chỉ xếp hàng chờ, không hỏi lại mật khẩu và
    không mở kết nối thứ hai.
    """

    global _connecting

    existing = SftpSessionManager.instance().get()
    if existing is not None:
        on_ready(existing)
        return

    with _lock:
        _pending.append((on_ready, on_error))
        if _connecting:
            return  # đã có lệnh gọi khác đang lo việc đăng nhập/kết nối
        _connecting = True

    if SFTP_DEMO_MODE:
        _finish(True, LocalBackend())
        return

    creds = _prompt_login(parent)
    if creds is None:
        _finish(False, "Đã hủy đăng nhập")
        return
    username, password = creds

    def do_connect() -> None:
        try:
            backend = SftpSessionManager.instance().connect(
                SFTP_HOST.strip(), SFTP_PORT, username, password
            )
            parent.after(0, lambda: _finish(True, backend))
        except ImportError:
            parent.after(
                0,
                lambda: _finish(
                    False, "Thiếu thư viện paramiko. Chạy: pip install paramiko"
                ),
            )
        except Exception as e:  # noqa: BLE001 - network layer
            # Truyền giá trị ngay: `e` bị xoá khi ra khỏi khối except, lambda
            # chạy sau sẽ NameError → kết nối hỏng không bao giờ được báo và
            # `_connecting` kẹt True, mọi lần upload SFTP sau đó treo.
            parent.after(0, _finish, False, str(e))

    threading.Thread(target=do_connect, daemon=True).start()


def get_sftp_uploader(
    parent: tk.Widget, remote_base: str
) -> Callable[[Callable[[Uploader], None], Callable[[str], None]], None]:
    """Factory `get_uploader` (xem `apps.widgets.upload_batch.run_upload_batch`)
    cho upload SFTP: đăng nhập qua popup dùng chung (tái sử dụng phiên nếu đã
    có) rồi bọc backend thành `SftpUploader`.
    """

    def get_uploader(
        on_ready: Callable[[Uploader], None], on_error: Callable[[str], None]
    ) -> None:
        def _on_backend(backend: StorageBackend) -> None:
            on_ready(SftpUploader(backend, remote_base))

        ensure_sftp_backend(parent, _on_backend, on_error)

    return get_uploader


__all__ = ["ensure_sftp_backend", "get_sftp_uploader"]
