"""Singleton quản lý MỘT phiên kết nối SFTP dùng chung cho toàn bộ app.

Mọi trang cần SFTP đều đi qua `SftpSessionManager.instance()` để lấy backend - đăng nhập một lần, dùng lại cho cả session, tự phát hiện kết nối chết (crash/timeout) và tự đóng khi app thoát.

Tự hỏi lại thông tin đăng nhập khi kết nối hết hạn.
"""

from __future__ import annotations

import atexit
import threading
from typing import Optional

import paramiko
import socket
from apps.services.storage import SftpBackend


class SftpSessionManager:
    """Singleton SFTP connection"""

    _instance: Optional["SftpSessionManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backend: Optional[SftpBackend] = None

    @classmethod
    def instance(cls) -> "SftpSessionManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _is_alive(backend: SftpBackend) -> bool:
        """Kiểm tra kết nối còn sống bằng một round-trip nhẹ (stat thư mục hiện tại)."""
        try:
            backend.sftp.stat(".")
            return True
        except Exception:
            return False

    def get(self) -> Optional[SftpBackend]:
        """Trả trạng thái hoạt động backend; tự đóng và trả None nếu đã mất kết nối."""
        with self._lock:
            if self._backend is not None and not self._is_alive(self._backend):
                self._backend.close()
                self._backend = None
            return self._backend

    def connect(self, host: str, port: int, username: str, password: str) -> SftpBackend:
        """Kết nối lại hoặc trả về kết nối hiện tại.
        """
        with self._lock:
            if self._backend is not None:
                if self._is_alive(self._backend):
                    return self._backend
                self._backend.close()
                self._backend = None

            # TCP connection timeout 15s, kỳ vọng socket.timeout/OSError nếu host unreachable.
            sock = socket.create_connection((host, port), timeout=15.0)
            transport = paramiko.Transport(sock)
            try:
                # Banner/key-exchange timeout 15s, kỳ vọng SSHException nếu timeout.
                transport.start_client(timeout=15.0)
                transport.auth_password(username=username, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)
            except Exception:
                # Đóng transport nếu connect/auth thất bại, tránh rò rỉ socket + thread.
                transport.close()
                raise

            backend = SftpBackend(sftp, transport)
            self._backend = backend
            return backend

    def close(self) -> None:
        """Đóng kết nối hiện có (nếu có). """
        with self._lock:
            if self._backend is not None:
                self._backend.close()
                self._backend = None


atexit.register(lambda: SftpSessionManager.instance().close())


__all__ = ["SftpSessionManager"]
