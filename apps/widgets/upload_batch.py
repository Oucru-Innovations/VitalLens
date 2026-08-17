"""Lựa chọn phương thức upload (SFTP hoặc HTTP) cho nút upload (X-Quang, XML, Upload Nhiều File, ...).

Dùng một `Uploader` (Strategy, xem `apps.services.upload_api`)  để xử lý queue các file cần upload. 
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from apps.services.upload_api import UploadJob, Uploader

log = logging.getLogger(__name__)


def run_upload_batch(
    parent: tk.Widget,
    upload_btn,
    status,
    get_uploader: Callable[[Callable[[Uploader], None], Callable[[str], None]], None],
    jobs: list[UploadJob],
    on_job_done: Optional[Callable[[UploadJob], None]] = None,
    on_job_failed: Optional[Callable[[UploadJob, str], None]] = None,
    on_batch_done: Optional[Callable[[bool], None]] = None,
) -> None:
    """Chuẩn bị Uploader cho từng file. Luôn chạy hết mọi job kể cả khi có job
    bị lỗi (không dừng ở lỗi đầu tiên) - lỗi được gom lại và báo cáo chung
    khi xong, để một job lỗi không chặn các job còn lại trong lô.
    Tự bật/tắt `upload_btn`, cập nhật `status`, và hiện một thanh tiến trình
    tạm thời ngay phía trên `status`.

    `get_uploader(on_ready, on_error)`: factory bất đồng bộ trả Uploader qua
    `on_ready` (vd: SFTP cần đăng nhập trước; HTTP gọi `on_ready` ngay).

    `on_job_done(job)` / `on_job_failed(job, message)` được gọi trên main thread
    cho từng job, để trang gọi có thể liệt kê file thành công / thất bại.
    """

    if not jobs:
        return

    total = sum(len(job.files) for job in jobs)
    upload_btn.set_state("disabled")
    status.set("Đang chuẩn bị upload...", "working")

    progress_bar = ttk.Progressbar(
        status.master, mode="determinate", maximum=max(total, 1)
    )
    progress_bar.pack(fill="x", padx=15, pady=(0, 4), before=status)

    def tick(_file_path: str) -> None:
        # Chạy trên background thread (xem do_run) - chỉ được đụng vào
        # widget Tk qua parent.after, không gọi trực tiếp.
        parent.after(0, progress_bar.step, 1)

    def finish(done_count: int, errors: list[tuple[UploadJob, str]]) -> None:
        progress_bar.destroy()
        upload_btn.set_state("normal")
        if errors:
            log.error(
                "Lô upload kết thúc: %d file OK, %d/%d job lỗi.",
                done_count, len(errors), len(jobs),
            )
            status.set(
                f"Upload: {done_count} file OK, {len(errors)} job lỗi.", "error"
            )
            detail = "\n".join(f"{job.label}: {msg}" for job, msg in errors)
            messagebox.showerror("Lỗi upload", detail)
        else:
            status.set(
                f"Upload thành công! {done_count} file ({len(jobs)} mục).",
                "success",
            )
        if on_batch_done is not None:
            on_batch_done(not errors)

    def do_run(uploader: Uploader) -> None:
        """Chạy trên background thread để không đứng UI khi upload nhiều file."""

        done_count = 0
        errors: list[tuple[UploadJob, str]] = []

        for job in jobs:
            parent.after(
                0, status.set,
                f"Đang upload '{job.label}' ({len(job.files)} file)...", "working",
            )
            result = uploader.upload(job, on_file_done=tick)
            if result.ok:
                done_count += len(job.files)
                if on_job_done is not None:
                    parent.after(0, on_job_done, job)
            else:
                errors.append((job, result.message))
                # Log ngay tại chỗ (thread nền) kèm danh sách file của job, để
                # file log giữ đủ vết ngay cả khi người dùng tắt hộp thoại lỗi.
                log.error(
                    "Job '%s' upload THẤT BẠI (status=%s, retryable=%s): %s | file: %s",
                    job.label, result.status_code, result.retryable, result.message,
                    ", ".join(job.files),
                )
                if on_job_failed is not None:
                    parent.after(0, on_job_failed, job, result.message)

        parent.after(0, finish, done_count, errors)

    def on_ready(uploader: Uploader) -> None:
        threading.Thread(target=do_run, args=(uploader,), daemon=True).start()

    def on_error(err_msg: str) -> None:
        log.error("Không tạo được uploader, hủy lô %d job: %s", len(jobs), err_msg)
        progress_bar.destroy()
        upload_btn.set_state("normal")
        status.set(f"Lỗi: {err_msg}", "error")
        messagebox.showerror("Lỗi", err_msg)
        if on_batch_done is not None:
            on_batch_done(False)

    get_uploader(on_ready, on_error)


__all__ = ["run_upload_batch"]
