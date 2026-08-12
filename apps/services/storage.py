"""Storage backend: thống nhất API đọc/ghi file cho local filesystem và SFTP.

UI và các service khác chỉ nói chuyện với interface `StorageBackend`,
không được import `paramiko` hoặc `os.listdir` trực tiếp.
"""

from __future__ import annotations

import os
import stat as _stat
import tempfile
from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Interface tối thiểu để duyệt và đọc/ghi dữ liệu."""

    is_remote: bool

    def listdir(self, path: str) -> List[str]: ...
    def is_dir(self, path: str) -> bool: ...
    def exists(self, path: str) -> bool: ...
    def read_bytes(self, path: str) -> bytes: ...
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def remove(self, path: str) -> None: ...
    def rename(self, src: str, dst: str) -> None: ...
    def join(self, base: str, *parts: str) -> str: ...
    def basename(self, path: str) -> str: ...
    def fetch_to_temp(self, path: str, suffix: str = "") -> str: ...
    def mkdir(self, path: str) -> None: ...


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


class LocalBackend:
    """Backend dùng filesystem cục bộ (dùng cho chế độ DEMO hoặc chạy offline)."""

    is_remote = False

    def listdir(self, path: str) -> List[str]:
        return os.listdir(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def read_bytes(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def write_bytes(self, path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

    def remove(self, path: str) -> None:
        if os.path.exists(path):
            os.remove(path)

    def rename(self, src: str, dst: str) -> None:
        os.replace(src, dst)

    def join(self, base: str, *parts: str) -> str:
        return os.path.join(base, *parts)

    def basename(self, path: str) -> str:
        return Path(str(path).rstrip("/\\")).name

    def fetch_to_temp(self, path: str, suffix: str = "") -> str:
        # Không cần copy - trả luôn đường dẫn gốc để viewer mở trực tiếp.
        return path

    def mkdir(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# SFTP backend
# ---------------------------------------------------------------------------


class SftpBackend:
    """Backend wrap quanh paramiko.SFTPClient.

    Path convention: luôn dùng "/" (POSIX) kể cả khi chạy trên Windows.
    """

    is_remote = True

    def __init__(self, sftp, transport=None):
        self.sftp = sftp
        self.transport = transport

    def close(self) -> None:
        for obj in (self.sftp, self.transport):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass

    def listdir(self, path: str) -> List[str]:
        return self.sftp.listdir(path)

    def is_dir(self, path: str) -> bool:
        try:
            return _stat.S_ISDIR(self.sftp.stat(path).st_mode)
        except (IOError, OSError):
            return False

    def exists(self, path: str) -> bool:
        try:
            self.sftp.stat(path)
            return True
        except (IOError, OSError):
            return False

    def read_bytes(self, path: str) -> bytes:
        with self.sftp.open(path, "r") as f:
            return f.read()

    def write_bytes(self, path: str, data: bytes) -> None:
        with self.sftp.open(path, "w") as f:
            f.write(data)

    def remove(self, path: str) -> None:
        try:
            self.sftp.remove(path)
        except (IOError, OSError):
            pass

    def rename(self, src: str, dst: str) -> None:
        try:
            self.sftp.remove(dst)
        except (IOError, OSError):
            pass
        self.sftp.rename(src, dst)

    def join(self, base: str, *parts: str) -> str:
        path = str(base).rstrip("/")
        for part in parts:
            if part is None:
                continue
            path = path + "/" + str(part).strip("/")
        return path or "/"

    def basename(self, path: str) -> str:
        clean = str(path).rstrip("/")
        return clean.rsplit("/", 1)[-1] if clean else ""

    def fetch_to_temp(self, path: str, suffix: str = "") -> str:
        fd, local_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self.sftp.get(path, local_path)
        return local_path

    def mkdir(self, path: str) -> None:
        """Tạo trực tiếp thư mục con"""
        is_abs = str(path).startswith("/")
        parts = [p for p in str(path).split("/") if p]
        current = "/" if is_abs else ""
        for part in parts:
            current = self.join(current, part) if current else part
            if self.is_dir(current):
                continue
            try:
                self.sftp.mkdir(current)
            except (IOError, OSError):
                if not self.is_dir(current):
                    raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def safe_is_dir(backend: StorageBackend, path: str) -> bool:
    try:
        return backend.is_dir(path)
    except Exception:
        return False


def resolve_named_child_dir(
    backend: StorageBackend, parent_path: str, child_name: str
) -> str:
    """Tìm thư mục con khớp tên (không phân biệt hoa/thường).

    Nếu không tìm thấy, trả về đường dẫn kết hợp trực tiếp để caller có thể
    kiểm tra lại bằng `is_dir`.
    """

    direct_path = backend.join(parent_path, child_name)
    if safe_is_dir(backend, direct_path):
        return direct_path

    try:
        children = backend.listdir(parent_path)
    except Exception:
        return direct_path

    target = child_name.lower()
    for existing in children:
        if existing.lower() != target:
            continue
        candidate = backend.join(parent_path, existing)
        if safe_is_dir(backend, candidate):
            return candidate

    return direct_path


def ensure_remote_dir(backend: StorageBackend, path: str) -> None:
    """Tạo thư mục đích bằng interface của backend
    Dùng khi upload file
    """

    clean = str(path).rstrip("/\\")
    if not clean or safe_is_dir(backend, clean):
        return
    backend.mkdir(clean)


def resolve_existing_data_dir(
    backend: StorageBackend, path: str
) -> Optional[str]:
    """Đi lần theo từng thành phần path để chịu được khác biệt hoa/thường
    trên server. Trả về None nếu không tồn tại."""

    clean = str(path).rstrip("/\\")
    if not clean:
        return None

    if safe_is_dir(backend, clean):
        return clean

    if not backend.is_remote:
        # Local: không cần case-insensitive walk (Windows đã lo).
        return None

    is_abs = clean.startswith("/")
    parts = [p for p in clean.split("/") if p]
    if not parts:
        return "/" if safe_is_dir(backend, "/") else None

    current = "/" if is_abs else ""
    for part in parts:
        parent = current or "."
        resolved = resolve_named_child_dir(backend, parent, part)
        if not safe_is_dir(backend, resolved):
            return None
        current = resolved
    return current


__all__ = [
    "StorageBackend",
    "LocalBackend",
    "SftpBackend",
    "safe_is_dir",
    "resolve_named_child_dir",
    "resolve_existing_data_dir",
    "ensure_remote_dir",
]
