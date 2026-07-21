"""Gửi cặp (PDF + CSV) đã chuẩn bị lên backend qua HTTP multipart.

Server dùng ``upload.single("file")`` nên PDF và CSV được gửi bằng **hai
request riêng**. Để retry không gửi trùng, hàm nhận cờ ``send_pdf`` /
``send_csv`` (bỏ qua file đã gửi thành công trước đó) và trả về kết quả
chi tiết từng file qua ``pdf_ok`` / ``csv_ok``.

Retry **có điều kiện**: endpoint này không nhận idempotency key, nên gửi lại một
request đã tới được server sẽ tạo bản ghi TRÙNG. Vì vậy chỉ thử lại khi chắc
chắn server chưa xử lý request:

- Lỗi ở pha kết nối (``ConnectionError`` / ``ConnectTimeout``) — chưa gửi được byte nào.
- 408 / 425 / 429 / 502 / 503 / 504 — throttle hoặc gateway chặn trước khi tới app.

KHÔNG thử lại ``ReadTimeout`` (đã gửi xong, đang chờ phản hồi → server có thể đã
ghi bản ghi rồi) và KHÔNG thử lại 500 (app đã chạy và có thể đã ghi dở). Những
trường hợp đó trả ``retryable=True`` để người dùng tự quyết định bấm Upload lại.

Gửi cả lô: tạo một ``Session`` bằng `make_session()` rồi truyền vào từng lời
gọi để tái dùng kết nối TCP/TLS thay vì bắt tay lại cho mỗi file. Truyền
``cancel_event`` để dừng lô giữa chừng khi người dùng bấm Hủy hoặc đóng app.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

# Status cho biết request bị chặn TRƯỚC khi app xử lý → gửi lại không tạo trùng.
RETRYABLE_STATUS = frozenset({408, 425, 429, 502, 503, 504})

# 500 = app đã chạy và lỗi; có thể đã ghi dở bản ghi. Đáng thử lại nhưng phải do
# người dùng chủ động, không tự động.
USER_RETRYABLE_STATUS = frozenset({500})

DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF = 1.5
# Chặn trên cho Retry-After để server lỗi cấu hình không treo app hàng giờ.
MAX_RETRY_AFTER = 30.0


class UploadCancelled(Exception):
    """Người dùng hủy lô upload giữa chừng."""


@dataclass
class UploadResult:
    ok: bool
    status_code: Optional[int]
    message: str
    pdf_ok: bool = False
    csv_ok: bool = False
    # True = lỗi tạm thời (mạng/server bận) → để ở Pending và thử lại sau.
    retryable: bool = False
    cancelled: bool = False


def make_session() -> Any:
    """Tạo `requests.Session` để tái dùng kết nối cho cả lô upload.

    Trả None nếu chưa cài `requests` — khi đó `upload_pair` tự báo lỗi.
    """

    try:
        import requests
    except ImportError:
        return None
    return requests.Session()


def _is_safe_to_retry(exc: BaseException) -> bool:
    """True chỉ khi request chắc chắn CHƯA tới được server.

    Phân loại theo tên lớp trong MRO để không phải import `requests` ở module
    level (bản đóng gói có thể thiếu thư viện này).
    """

    names = {cls.__name__ for cls in type(exc).__mro__}
    # Đã gửi xong và đang chờ phản hồi → server có thể đã ghi bản ghi.
    if "ReadTimeout" in names or "ChunkedEncodingError" in names:
        return False
    return bool(
        names & {"ConnectTimeout", "ConnectionError", "ProxyError", "SSLError"}
    )


def _sleep_cancellable(delay: float, cancel: Optional[threading.Event]) -> None:
    """Ngủ `delay` giây nhưng tỉnh ngay khi bị hủy. Raise UploadCancelled."""

    if cancel is None:
        time.sleep(delay)
        return
    if cancel.wait(delay):
        raise UploadCancelled()


def _check_cancelled(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise UploadCancelled()


def _retry_after_seconds(resp: Any, fallback: float) -> float:
    """Đọc header Retry-After (giây). Về `fallback` nếu thiếu/không hợp lệ."""

    raw = ""
    try:
        raw = (resp.headers.get("Retry-After") or "").strip()
    except Exception:  # noqa: BLE001 - fake response trong test có thể thiếu headers
        return fallback
    if not raw:
        return fallback
    try:
        # Dạng HTTP-date cũng hợp lệ theo RFC nhưng hiếm; chỉ xử lý dạng giây.
        return max(0.0, min(float(raw), MAX_RETRY_AFTER))
    except ValueError:
        return fallback


def _open_file(label: str, fpath: str, mime: str, owner: str):
    """Mở file để gửi. Lỗi I/O ở đây KHÔNG phải lỗi mạng nên không được retry."""

    f = open(fpath, "rb")
    files = [("file", (os.path.basename(fpath), f, mime))]
    data = {"owner": owner} if owner else {}
    return f, files, data


def _send_one(
    session: Any,
    url: str,
    headers: dict,
    label: str,
    fpath: str,
    mime: str,
    owner: str,
    timeout: float,
    max_retries: int,
    backoff: float,
    cancel: Optional[threading.Event] = None,
) -> tuple[bool, Optional[int], str, bool]:
    """Gửi một file (có retry an toàn). Trả (ok, status_code, message, retryable)."""

    attempt = 0
    while True:
        attempt += 1
        _check_cancelled(cancel)

        # Mở file NGOÀI khối bắt lỗi mạng: FileNotFoundError/PermissionError là
        # lỗi cục bộ, retry vô ích và không được báo nhầm thành "lỗi mạng".
        try:
            fh, files, data = _open_file(label, fpath, mime, owner)
        except OSError as e:
            log.error("  [%s] Không mở được file: %s", label, e)
            return False, None, f"Không đọc được file {label}: {e}", False

        try:
            resp = session.post(
                url, headers=headers, files=files, data=data, timeout=timeout
            )
        except Exception as e:  # noqa: BLE001 - requests ném nhiều loại lỗi mạng
            safe = _is_safe_to_retry(e)
            if safe and attempt <= max_retries:
                delay = backoff * attempt
                log.warning(
                    "  [%s] Lỗi kết nối (lần %d/%d): %s — thử lại sau %.1fs",
                    label, attempt, max_retries + 1, e, delay,
                )
                _sleep_cancellable(delay, cancel)
                continue
            if not safe:
                # Request có thể đã tới server → tự gửi lại sẽ tạo bản ghi trùng.
                log.warning(
                    "  [%s] Lỗi sau khi đã gửi (%s) — KHÔNG tự thử lại để "
                    "tránh tạo bản ghi trùng.", label, type(e).__name__,
                )
                return (
                    False, None,
                    f"Mất phản hồi khi gửi {label} ({e}). Server có thể đã nhận "
                    f"— kiểm tra trước khi gửi lại.",
                    True,
                )
            log.warning("  [%s] Lỗi kết nối, đã hết lượt thử: %s", label, e)
            return False, None, f"Lỗi mạng khi gửi {label}: {e}", True
        finally:
            fh.close()

        log.info("  [%s] HTTP status: %d (lần %d)", label, resp.status_code, attempt)
        log.debug("  [%s] Body: %s", label, resp.text[:300] if resp.text else "(trống)")

        if resp.status_code in (200, 201):
            return True, resp.status_code, "OK", False

        if resp.status_code in RETRYABLE_STATUS and attempt <= max_retries:
            delay = _retry_after_seconds(resp, backoff * attempt)
            log.warning(
                "  [%s] Server bận (%d), thử lại sau %.1fs",
                label, resp.status_code, delay,
            )
            _sleep_cancellable(delay, cancel)
            continue

        body = resp.text[:200] if resp.text else "(trống)"
        log.error(
            "  [FAIL] Server trả lỗi %d khi gửi %s — body: %s",
            resp.status_code, label, resp.text[:500] if resp.text else "(trống)",
        )
        return (
            False,
            resp.status_code,
            f"Server báo lỗi {resp.status_code} khi gửi {label}: {body}",
            resp.status_code in RETRYABLE_STATUS
            or resp.status_code in USER_RETRYABLE_STATUS,
        )


def upload_pair(
    url: str,
    bearer_token: Optional[str],
    pdf_path: str,
    csv_path: str,
    owner: str = "",
    timeout: float = 60.0,
    send_pdf: bool = True,
    send_csv: bool = True,
    session: Any = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_BACKOFF,
    cancel_event: Optional[threading.Event] = None,
) -> UploadResult:
    """Gửi POST multipart tới `url`. Không raise, luôn trả UploadResult.

    ``send_pdf`` / ``send_csv`` = False nghĩa là file đó đã gửi thành công ở
    lần trước → bỏ qua (kết quả coi như OK sẵn) để tránh upload trùng.
    ``session`` = Session dùng chung cho cả lô (None thì tự tạo tạm).
    ``cancel_event`` = set() để dừng giữa chừng; kết quả có ``cancelled=True``.
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

    own_session = session is None
    if own_session:
        session = make_session()
    if session is None:
        log.error("  [FAIL] Thiếu thư viện 'requests'.")
        return UploadResult(
            False, None, "Thiếu thư viện requests. Chạy: pip install requests",
            pdf_ok, csv_ok,
        )

    try:
        # --- Auth header ---
        headers = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
            log.debug(
                "  Auth      : Bearer token đã được đính kèm (len=%d)",
                len(bearer_token),
            )
        else:
            log.debug("  Auth      : Không có bearer token")

        # --- Kiểm tra file tồn tại + kích thước ---
        for label, fpath, _ in jobs:
            if os.path.exists(fpath):
                size_kb = os.path.getsize(fpath) / 1024
                log.info(
                    "  %s size   : %.1f KB  (%s)",
                    label, size_kb, os.path.basename(fpath),
                )
            else:
                log.error("  [FAIL] File không tồn tại: %s", fpath)
                # File mất khỏi ổ đĩa → retry cũng vô ích.
                return UploadResult(
                    False, None, f"File không tìm thấy: {fpath}", pdf_ok, csv_ok
                )

        last_status: Optional[int] = None
        for label, fpath, mime in jobs:
            log.info("  [%s] Đang gửi %s...", label, os.path.basename(fpath))
            try:
                ok, status, message, retryable = _send_one(
                    session, url, headers, label, fpath, mime, owner,
                    timeout, max_retries, retry_backoff, cancel_event,
                )
            except UploadCancelled:
                log.info("  [%s] Đã hủy theo yêu cầu người dùng.", label)
                return UploadResult(
                    False, None, "Đã hủy", pdf_ok, csv_ok,
                    retryable=True, cancelled=True,
                )
            if not ok:
                return UploadResult(False, status, message, pdf_ok, csv_ok, retryable)

            last_status = status
            if label == "PDF":
                pdf_ok = True
            else:
                csv_ok = True
    finally:
        if own_session:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    log.info("  [OK] Upload thành công (pdf_ok=%s, csv_ok=%s)", pdf_ok, csv_ok)
    log.info("=== upload_pair KẾT THÚC: OK ===")
    return UploadResult(True, last_status, "OK", pdf_ok, csv_ok)


__all__ = [
    "UploadResult",
    "UploadCancelled",
    "upload_pair",
    "make_session",
    "RETRYABLE_STATUS",
    "USER_RETRYABLE_STATUS",
]
