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

Vì ``ReadTimeout`` rơi vào nhóm phải hỏi người dùng, timeout chờ phản hồi để
rộng (``DEFAULT_READ_TIMEOUT``) còn timeout kết nối để chặt
(``DEFAULT_CONNECT_TIMEOUT``) — xem chú thích tại chỗ khai báo.

Gửi cả lô: tạo một ``Session`` bằng `make_session()` rồi truyền vào từng lời
gọi để tái dùng kết nối TCP/TLS thay vì bắt tay lại cho mỗi file. Truyền
``cancel_event`` để dừng lô giữa chừng khi người dùng bấm Hủy hoặc đóng app.

Ngoài các hàm HTTP (`upload_pair`, `upload_files_http`) và primitive SFTP
(`upload_files_sftp`), file này còn định nghĩa tầng Strategy dùng chung cho
UI: `UploadJob`, `Uploader` (Protocol), `HttpUploader`, `SftpUploader` - xem
`apps.widgets.upload_batch.run_upload_batch`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable

from apps.services.storage import LocalBackend, StorageBackend, ensure_remote_dir

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
HTTP_POST_DELAY = 0.5

# Timeout tách làm HAI pha (requests nhận tuple ``(connect, read)``):
#
# - connect: chỉ là bắt tay TCP/TLS, vài giây là đủ. Để số lớn ở đây rất hại —
#   lỗi pha kết nối được TỰ ĐỘNG thử lại (xem `_is_safe_to_retry`), nên server
#   không truy cập được sẽ treo ``connect × (1 + max_retries)`` trước khi người
#   dùng thấy báo lỗi.
# - read: thời gian chờ GIỮA hai lần nhận byte sau khi đã gửi xong, KHÔNG phải
#   tổng thời gian request. File lớn upload chậm nhưng đều đặn sẽ không bị cắt;
#   con số này chỉ cần đủ cho lúc backend im lặng vì đang xử lý file.
#
# Read để rộng tay vì ``ReadTimeout`` KHÔNG được tự thử lại (endpoint không có
# idempotency key) — mỗi lần chạm timeout là một lần người dùng phải tự kiểm tra
# xem server đã nhận hay chưa.
DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_READ_TIMEOUT = 300.0
DEFAULT_TIMEOUT = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)


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


@dataclass
class UploadJob:
    """Một lượt upload: nhãn hiển thị + danh sách file cục bộ.

    HTTP: mỗi job gồm 1 file (label = tên file). SFTP: mỗi job là một nhóm
    (label = thư mục nhận, files = các file trong nhóm đó).
    """

    label: str
    files: list[str]


@runtime_checkable
class Uploader(Protocol):
    """Strategy chung cho việc upload một `UploadJob` (HTTP hoặc SFTP)."""

    def upload(
        self, job: UploadJob, on_file_done: Optional[Callable[[str], None]] = None
    ) -> UploadResult: ...


def make_session() -> Any:
    """Tạo `requests.Session` để tái dùng kết nối cho cả lô upload.

    Trả None nếu chưa cài `requests` — khi đó `upload_pair` tự báo lỗi.
    """

    try:
        import requests
    except ImportError:
        return None
    return requests.Session()


def _format_timeout(timeout: float | tuple[float, float]) -> str:
    """Mô tả timeout cho log (chấp nhận cả dạng số lẫn tuple connect/read)."""

    if isinstance(timeout, tuple):
        return f"connect={timeout[0]:.1f}s, read={timeout[1]:.1f}s"
    return f"{timeout:.1f}s"


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
    timeout: float | tuple[float, float],
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
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
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
    log.info("  Timeout   : %s", _format_timeout(timeout))

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


def upload_files_http(
    url: str,
    bearer_token: Optional[str],
    file_path: str,
    owner: str = "",
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_BACKOFF,
) -> UploadResult:
    """POST một file bất kỳ tới `url` (dùng cho MultiUpload - chỉ áp dụng
    cho file loại Pdf, backend hiện chỉ nhận cho PDF).

    Dùng chung `_send_one` với `upload_pair`, cùng chính sách retry (mặc định
    `DEFAULT_MAX_RETRIES`/`DEFAULT_BACKOFF`, có thể override). Không raise,
    luôn trả UploadResult.
    """

    log.info("=== upload_files_http BẮT ĐẦU ===")
    log.info("  URL   : %s", url)
    log.info("  File  : %s", file_path)
    log.info("  Owner : %s", owner or "(không có)")

    if not url:
        log.error("  [FAIL] API_UPLOAD_URL chưa được cấu hình.")
        return UploadResult(False, None, "Chưa cấu hình API_UPLOAD_URL")

    session = make_session()
    if session is None:
        log.error("  [FAIL] Thiếu thư viện 'requests'.")
        return UploadResult(
            False, None, "Thiếu thư viện requests. Chạy: pip install requests"
        )

    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    label = os.path.basename(file_path)
    try:
        ok, status, message, retryable = _send_one(
            session, url, headers, label, file_path, "application/pdf", owner,
            timeout, max_retries=max_retries, backoff=retry_backoff,
        )
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass

    log.info("=== upload_files_http KẾT THÚC: %s ===", "OK" if ok else "FAIL")
    return UploadResult(ok, status, message, retryable=retryable)


def upload_files_sftp(
    backend: StorageBackend,
    remote_base: str,
    child_path: str,
    file_paths: Iterable[str],
    on_file_done: Optional[Callable[[str], None]] = None,
) -> UploadResult:
    """Gửi các file local lên `remote_base/child_path` qua `backend` SFTP.

    Thư mục được tạo tự động nếu chưa tồn tại. 
    """

    log.info("=== upload_files_sftp BẮT ĐẦU ===")
    log.info("  Remote base : %s", remote_base)
    log.info("  Child path  : %s", child_path)

    if not remote_base:
        log.error("  [FAIL] SFTP_BUFFER_PATH chưa được cấu hình.")
        return UploadResult(False, None, "Chưa cấu hình SFTP_BUFFER_PATH")

    remote_dir = backend.join(remote_base, child_path) if child_path else remote_base

    try:
        ensure_remote_dir(backend, remote_dir)
    except Exception as e:  # noqa: BLE001
        log.exception("  [FAIL] Không thể tạo thư mục remote %s", remote_dir)
        return UploadResult(False, None, f"Không thể tạo thư mục remote: {e}")

    count = 0
    for local_path in file_paths:
        name = os.path.basename(local_path)
        remote_path = backend.join(remote_dir, name)
        log.info("  Đang gửi %s -> %s", local_path, remote_path)
        try:
            data = LocalBackend().read_bytes(local_path)
            backend.write_bytes(remote_path, data)
            count += 1
            if on_file_done is not None:
                on_file_done(local_path)
        except Exception as e:  # noqa: BLE001
            # exception() để giữ traceback: lỗi SFTP thường là I/O hoặc phiên
            # rớt, không truy được nguyên nhân nếu chỉ log câu message.
            log.exception(
                "  [FAIL] Lỗi upload %s -> %s: %s", local_path, remote_path, e
            )
            return UploadResult(False, None, f"Lỗi upload {name}: {e}")

    log.info("  [OK] Upload %d file lên %s", count, remote_dir)
    log.info("=== upload_files_sftp KẾT THÚC: OK ===")
    return UploadResult(True, None, f"Đã upload {count} file lên {remote_dir}")


def sanitize_path_segment(raw: str) -> str:
    """Chuẩn hoá text trong tên thư mục remote: chỉ giữ [A-Za-z0-9_-] (giữ nguyên
    hoa/thường), phần còn lại gộp thành '-'. Rỗng/không hợp lệ → 'misc'."""

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", (raw or "").strip()).strip("-")
    return cleaned or "misc"


def infer_sftp_child_path(study: str, patient: str, date_token: str, data_type: str) -> str:
    """Trích thư mục con SFTP: '<study>/<patient>/<date>/<data_type>'.
    """

    study = (study or "").strip()
    patient = (patient or "").strip()
    date_token = (date_token or "").strip()
    if not study or not patient or not date_token:
        raise ValueError("study, patient và date_token không được rỗng")

    segments = [
        sanitize_path_segment(study),
        sanitize_path_segment(patient),
        sanitize_path_segment(date_token),
        sanitize_path_segment(data_type),
    ]
    return "/".join(segments)


class HttpUploader:
    """Uploader HTTP -`upload_files_http`. Gửi từng file)."""

    def __init__(
        self,
        url: str,
        bearer_token: Optional[str],
        owner: str = "",
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_BACKOFF,
        post_delay: float = HTTP_POST_DELAY,
    ) -> None:
        self.url = url
        self.bearer_token = bearer_token
        self.owner = owner
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.post_delay = post_delay

    def upload(
        self, job: UploadJob, on_file_done: Optional[Callable[[str], None]] = None
    ) -> UploadResult:
        file_path = job.files[0]
        result = upload_files_http(
            self.url, self.bearer_token, file_path,
            owner=self.owner, timeout=self.timeout,
            max_retries=self.max_retries, retry_backoff=self.retry_backoff,
        )
        if result.ok:
            if on_file_done is not None:
                on_file_done(file_path)
            # Chạy trên thread nền của run_upload_batch nên sleep không đứng UI.
            if self.post_delay > 0:
                time.sleep(self.post_delay)
        return result


class SftpUploader:
    """Uploader SFTP `upload_files_sftp`. ."""

    def __init__(self, backend: StorageBackend, remote_base: str) -> None:
        self.backend = backend
        self.remote_base = remote_base

    def upload(
        self, job: UploadJob, on_file_done: Optional[Callable[[str], None]] = None
    ) -> UploadResult:
        return upload_files_sftp(
            self.backend, self.remote_base, job.label, job.files,
            on_file_done=on_file_done,
        )


__all__ = [
    "UploadResult",
    "UploadCancelled",
    "upload_pair",
    "make_session",
    "RETRYABLE_STATUS",
    "USER_RETRYABLE_STATUS",
    "HTTP_POST_DELAY",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_READ_TIMEOUT",
    "DEFAULT_TIMEOUT",
    "upload_files_http",
    "upload_files_sftp",
    "sanitize_path_segment",
    "infer_sftp_child_path",
    "UploadJob",
    "Uploader",
    "HttpUploader",
    "SftpUploader",
]
