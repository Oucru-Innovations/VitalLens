"""Gửi cặp (PDF + CSV) đã chuẩn bị lên backend qua HTTP multipart.

Server dùng ``upload.single("file")`` nên PDF và CSV được gửi bằng **hai
request riêng**. Để retry không gửi trùng, hàm nhận cờ ``send_pdf`` /
``send_csv`` (bỏ qua file đã gửi thành công trước đó) và trả về kết quả
chi tiết từng file qua ``pdf_ok`` / ``csv_ok``.
"""

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
    pdf_ok: bool = False
    csv_ok: bool = False


def upload_pair(
    url: str,
    bearer_token: Optional[str],
    pdf_path: str,
    csv_path: str,
    owner: str = "",
    timeout: float = 60.0,
    send_pdf: bool = True,
    send_csv: bool = True,
) -> UploadResult:
    """Gửi POST multipart tới `url`. Không raise, luôn trả UploadResult.

    ``send_pdf`` / ``send_csv`` = False nghĩa là file đó đã gửi thành công ở
    lần trước → bỏ qua (kết quả coi như OK sẵn) để tránh upload trùng.
    """

    log.info("=== upload_pair BẮT ĐẦU ===")
    log.info("  URL       : %s", url)
    log.info("  PDF file  : %s (gửi=%s)", pdf_path, send_pdf)
    log.info("  CSV file  : %s (gửi=%s)", csv_path, send_csv)
    log.info("  Owner     : %s", owner or "(không có)")
    log.info("  Timeout   : %.1fs", timeout)

    # File nào không cần gửi thì coi như đã OK từ trước.
    pdf_ok = not send_pdf
    csv_ok = not send_csv

    # --- Danh sách file cần gửi (bỏ qua file đã gửi trước đó) ---
    jobs = []
    if send_pdf:
        jobs.append(("PDF", pdf_path, "application/pdf"))
    if send_csv:
        jobs.append(("CSV", csv_path, "text/csv"))

    # Không còn gì để gửi (retry sau khi cả hai đã thành công) → OK ngay, khỏi
    # cần URL hay thư viện requests.
    if not jobs:
        log.info("  [OK] Không có gì để gửi (cả hai file đã gửi trước đó).")
        return UploadResult(True, None, "OK (đã gửi trước đó)", pdf_ok, csv_ok)

    if not url:
        log.error("  [FAIL] API_UPLOAD_URL chưa được cấu hình.")
        return UploadResult(False, None, "Chưa cấu hình API_UPLOAD_URL", pdf_ok, csv_ok)

    try:
        import requests
    except ImportError:
        log.error("  [FAIL] Thiếu thư viện 'requests'.")
        return UploadResult(
            False, None, "Thiếu thư viện requests. Chạy: pip install requests",
            pdf_ok, csv_ok,
        )

    # --- Auth header ---
    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
        log.debug("  Auth      : Bearer token đã được đính kèm (len=%d)", len(bearer_token))
    else:
        log.debug("  Auth      : Không có bearer token")

    # --- Kiểm tra file tồn tại + kích thước ---
    for label, fpath, _ in jobs:
        if os.path.exists(fpath):
            size_kb = os.path.getsize(fpath) / 1024
            log.info("  %s size   : %.1f KB  (%s)", label, size_kb, os.path.basename(fpath))
        else:
            log.error("  [FAIL] File không tồn tại: %s", fpath)
            return UploadResult(False, None, f"File không tìm thấy: {fpath}", pdf_ok, csv_ok)

    last_status: Optional[int] = None
    for label, fpath, mime in jobs:
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
            return UploadResult(
                False, None, f"Lỗi mạng khi gửi {label}: {e}", pdf_ok, csv_ok
            )

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
                pdf_ok, csv_ok,
            )

        last_status = resp.status_code
        if label == "PDF":
            pdf_ok = True
        else:
            csv_ok = True

    log.info("  [OK] Upload thành công (pdf_ok=%s, csv_ok=%s)", pdf_ok, csv_ok)
    log.info("=== upload_pair KẾT THÚC: OK ===")
    return UploadResult(True, last_status, "OK", pdf_ok, csv_ok)


__all__ = ["UploadResult", "upload_pair"]
