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

    log.info("=== upload_pair BẮT ĐẦU ===")
    log.info("  URL       : %s", url)
    log.info("  PDF file  : %s", pdf_path)
    log.info("  CSV file  : %s", csv_path)
    log.info("  Timeout   : %.1fs", timeout)

    if not url:
        log.error("  [FAIL] API_UPLOAD_URL chưa được cấu hình.")
        return UploadResult(False, None, "Chưa cấu hình API_UPLOAD_URL")

    try:
        import requests
    except ImportError:
        log.error("  [FAIL] Thiếu thư viện 'requests'.")
        return UploadResult(
            False, None, "Thiếu thư viện requests. Chạy: pip install requests"
        )

    # --- Auth header ---
    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
        log.debug("  Auth      : Bearer token đã được đính kèm (len=%d)", len(bearer_token))
    else:
        log.debug("  Auth      : Không có bearer token")

    # --- Kiểm tra file tồn tại + kích thước ---
    for label, fpath in (("PDF", pdf_path), ("CSV", csv_path)):
        if os.path.exists(fpath):
            size_kb = os.path.getsize(fpath) / 1024
            log.info("  %s size   : %.1f KB  (%s)", label, size_kb, os.path.basename(fpath))
        else:
            log.error("  [FAIL] File không tồn tại: %s", fpath)
            return UploadResult(False, None, f"File không tìm thấy: {fpath}")

    # --- Gửi request ---
    log.info("  Đang gửi HTTP POST multipart...")
    try:
        with open(pdf_path, "rb") as fpdf, open(csv_path, "rb") as fcsv:
            files = {
                "pdf_file": (os.path.basename(pdf_path), fpdf, "application/pdf"),
                "csv_file": (os.path.basename(csv_path), fcsv, "text/csv"),
            }
            log.debug("  Fields    : %s", list(files.keys()))
            resp = requests.post(url, headers=headers, files=files, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        log.warning("  [FAIL] Lỗi mạng khi gửi request: %s", e)
        return UploadResult(False, None, f"Lỗi mạng: {e}")

    # --- Phân tích response ---
    log.info("  HTTP status   : %d", resp.status_code)
    log.debug("  Response headers: %s", dict(resp.headers))
    log.debug(
        "  Response body (%d bytes): %s",
        len(resp.content),
        resp.text[:500] if resp.text else "(trống)",
    )

    if resp.status_code in (200, 201):
        log.info("  [OK] Upload thành công (status %d)", resp.status_code)
        log.info("=== upload_pair KẾT THÚC: OK ===")
        return UploadResult(True, resp.status_code, "OK")

    log.error(
        "  [FAIL] Server trả lỗi %d — body: %s",
        resp.status_code,
        resp.text[:500] if resp.text else "(trống)",
    )
    log.info("=== upload_pair KẾT THÚC: THẤT BẠI ===")
    return UploadResult(
        False,
        resp.status_code,
        f"Server báo lỗi {resp.status_code}: {resp.text[:200]}",
    )


__all__ = ["UploadResult", "upload_pair"]
