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
    owner: str = "",
    timeout: float = 60.0,
) -> UploadResult:
    """Gửi POST multipart tới `url`. Không raise, luôn trả UploadResult."""

    log.info("=== upload_pair BẮT ĐẦU ===")
    log.info("  URL       : %s", url)
    log.info("  PDF file  : %s", pdf_path)
    log.info("  CSV file  : %s", csv_path)
    log.info("  Owner     : %s", owner or "(không có)")
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

    # --- Gửi từng file riêng (server dùng upload.single("file")) ---
    results = []
    for label, fpath, mime in (
        ("PDF", pdf_path, "application/pdf"),
        ("CSV", csv_path, "text/csv"),
    ):
        log.info("  [%s] Đang gửi %s...", label, os.path.basename(fpath))
        try:
            with open(fpath, "rb") as f:
                files = [("file", (os.path.basename(fpath), f, mime))]
                data = {"owner": owner} if owner else {}
                resp = requests.post(
                    url, headers=headers, files=files, data=data,
                    timeout=timeout,
                )
        except Exception as e:  # noqa: BLE001
            log.warning("  [%s] Lỗi mạng: %s", label, e)
            return UploadResult(False, None, f"Lỗi mạng khi gửi {label}: {e}")

        log.info("  [%s] HTTP status: %d", label, resp.status_code)
        log.debug("  [%s] Body: %s", label, resp.text[:300] if resp.text else "(trống)")

        if resp.status_code not in (200, 201):
            log.error(
                "  [FAIL] Server trả lỗi %d khi gửi %s — body: %s",
                resp.status_code, label,
                resp.text[:500] if resp.text else "(trống)",
            )
            return UploadResult(
                False,
                resp.status_code,
                f"Server báo lỗi {resp.status_code} khi gửi {label}: {resp.text[:200]}",
            )
        results.append(resp.status_code)

    log.info("  [OK] Upload cả 2 file thành công: %s", results)
    log.info("=== upload_pair KẾT THÚC: OK ===")
    return UploadResult(True, results[0], "OK")


__all__ = ["UploadResult", "upload_pair"]
