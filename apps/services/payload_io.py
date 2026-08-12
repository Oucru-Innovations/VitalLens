"""Đọc/ghi JSON & CSV qua một StorageBackend.

Mọi trang UI nên import từ đây thay vì `open()` trực tiếp, để vừa local vừa
SFTP đều chạy cùng code path.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable, List, Tuple

from .storage import StorageBackend


def read_json(backend: StorageBackend, folder_path: str, filename: str) -> Any:
    path = backend.join(folder_path, filename)
    raw = backend.read_bytes(path)
    return json.loads(raw.decode("utf-8-sig"))


def write_json(
    backend: StorageBackend, folder_path: str, filename: str, data: Any
) -> None:
    path = backend.join(folder_path, filename)
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    backend.write_bytes(path, content)


def read_csv(
    backend: StorageBackend, folder_path: str, filename: str
) -> Tuple[List[str], List[dict]]:
    """Trả về (fieldnames, rows). Rỗng nếu filename falsy."""

    if not filename:
        return [], []
    path = backend.join(folder_path, filename)
    raw = backend.read_bytes(path)
    content = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = list(reader.fieldnames or [])
    rows = list(reader)
    return fieldnames, rows


def write_csv(
    backend: StorageBackend,
    folder_path: str,
    filename: str,
    rows: Iterable[dict],
    fieldnames: List[str] | None = None,
) -> None:
    rows = list(rows)
    if not fieldnames:
        collected = list(dict.fromkeys(key for row in rows for key in row))
        fieldnames = collected or [
            "record_type",
            "study_id",
            "patient_id",
            "record_date",
            "source_pdf",
        ]

    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})

    path = backend.join(folder_path, filename)
    # utf-8-sig để Excel/Office hiểu BOM khi mở file CSV tiếng Việt.
    backend.write_bytes(path, stream.getvalue().encode("utf-8-sig"))


__all__ = ["read_json", "write_json", "read_csv", "write_csv"]
