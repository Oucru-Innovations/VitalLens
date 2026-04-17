"""Gửi cặp (PDF + CSV) đã chuẩn bị lên backend qua HTTP multipart."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class UploadResult:
    ok: bool
    status_code: Optional[int]
    message: str


def upload_pair(
    url: str,
    bearer_token: Optional[str],
    pdf_path: str,
    csv_path: str,
    timeout: float = 60.0,
) -> UploadResult:
    """Gửi POST multipart tới `url`. Không raise, luôn trả UploadResult."""

    if not url:
        return UploadResult(False, None, "Chưa cấu hình API_UPLOAD_URL")

    try:
        import requests
    except ImportError:
        return UploadResult(
            False, None, "Thiếu thư viện requests. Chạy: pip install requests"
        )

    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    try:
        with open(pdf_path, "rb") as fpdf, open(csv_path, "rb") as fcsv:
            files = {
                "pdf_file": (os.path.basename(pdf_path), fpdf, "application/pdf"),
                "csv_file": (os.path.basename(csv_path), fcsv, "text/csv"),
            }
            resp = requests.post(url, headers=headers, files=files, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - chuyển mọi lỗi mạng thành result.
        log.warning("upload_pair network error: %s", e)
        return UploadResult(False, None, f"Lỗi mạng: {e}")

    if resp.status_code in (200, 201):
        return UploadResult(True, resp.status_code, "OK")
    return UploadResult(
        False,
        resp.status_code,
        f"Server báo lỗi {resp.status_code}: {resp.text[:200]}",
    )


__all__ = ["UploadResult", "upload_pair"]
