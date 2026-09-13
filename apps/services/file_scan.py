"""Quét toàn bộ file bên trong một thư mục cục bộ.

Dùng cho các trang cho phép chọn cả thư mục thay vì chọn từng file - ví dụ
BƯỚC 1 của MultiUploadPage. Thư mục do người dùng chọn qua
`filedialog.askdirectory` luôn nằm trên đĩa cục bộ (Tkinter không hỗ trợ
duyệt SFTP), nên hàm này dùng thẳng `os.walk` thay vì `StorageBackend`.
"""

from __future__ import annotations

import os

__all__ = ["list_files_recursive"]


def list_files_recursive(root: str) -> list[str]:
    """Trả về đường dẫn đầy đủ của mọi file nằm trong `root`, gồm cả thư mục con."""
    results: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            results.append(os.path.join(dirpath, name))
    return sorted(results)
