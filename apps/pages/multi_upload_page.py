"""Trang Upload File đã xử lý.

Cho phép chọn nhiều file bất kỳ (PDF, X-ray, ECG, Ultrasound, ...), để trích xuất Study / Patient / Data type / Date tự động hoặc nhập tay.
- `Xray` / `ECG` / `Ultrasound` / `CT` / `MRI` / `Others` (Data type) → SFTP 
- Data type `Image` hoặc `Metadata` → API HTTP 

File nào thiếu Study/Patient/Date hợp lệ sẽ không thể gửi đi.
"""

from __future__ import annotations

import logging
import os
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_PURPLE,
    API_UPLOAD_OWNER,
    API_UPLOAD_URL,
    API_BEARER_TOKEN,
    BG_CARD,
    BG_INPUT,
    BG_MAIN,
    BTN_HOVER_BLUE,
    BTN_HOVER_PURPLE,
    FG_DIM,
    FG_TEXT,
    SFTP_BUFFER_PATH,
)
from apps.services.parser.file_name import FileNameParser
from apps.services.upload_api import (
    HttpUploader,
    UploadJob,
    infer_sftp_child_path,
    sanitize_path_segment,
)
from apps.widgets import (
    StyledButton, StatusBar, make_header, make_section,
    make_scrollable_listbox, get_sftp_uploader, run_upload_batch,
)

log = logging.getLogger(__name__)

# Khớp các giá trị FileNameParser.get_datatype() trả về (đã sanitize/lower).
SFTP_TYPES = {"xray", "ecg", "ultrasound", "mri", "ctscan", "others"}
HTTP_TYPES = {"image", "metadata"}

TABLE_COLUMNS = ("file", "study", "patient", "data_type", "date", "route")
# study/route được suy luận/dùng nội bộ để định tuyến upload nhưng không cần
# hiển thị cho người dùng - xem infer_sftp_child_path/_route_for.
VISIBLE_COLUMNS = ("file", "patient", "data_type", "date")
TABLE_HEADINGS = {
    "file": "File (đường dẫn đầy đủ)",
    "study": "Study",
    "patient": "Patient",
    "data_type": "Data type",
    "date": "Date (ddmmyyyy)",
    "route": "Route",
}
EDITABLE_COLUMNS = {"patient", "data_type", "date"}

_DATE_TOKEN_PATTERN = re.compile(r"^\d{8}$")


def _date_token(date_iso: str | None) -> str:
    if not date_iso:
        return ""
    try:
        return datetime.fromisoformat(date_iso).strftime("%d%m%Y")
    except ValueError:
        return ""


class MultiUploadPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller

        self.files: list[str] = []
        # path -> {"study": str, "patient": str, "data_type": str, "date": str, "manual": set[str]}
        self.parsed: dict[str, dict] = {}
        self.uploaded_log: list[tuple[str, str, str]] = []

        make_header(self, controller, "Upload Nhiều File")

        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True)

        # === Section 1: Chọn file ===
        s1 = make_section(body, "BƯỚC 1 — Chọn file (bất kỳ loại nào)")

        btn_row = tk.Frame(s1, bg=BG_CARD)
        btn_row.pack(fill="x", padx=15, pady=(0, 5))

        pick_btn = tk.Label(
            btn_row, text="  Chọn file...  ", font=("Helvetica", 12, "bold"),
            bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=10, pady=6,
        )
        pick_btn.pack(side="left")
        pick_btn.bind("<Button-1>", lambda e: self._pick_files())
        pick_btn.bind("<Enter>", lambda e: pick_btn.config(bg=BTN_HOVER_BLUE))
        pick_btn.bind("<Leave>", lambda e: pick_btn.config(bg=ACCENT_BLUE))

        remove_btn = tk.Label(
            btn_row, text="  Xóa khỏi danh sách  ", font=("Helvetica", 11, "bold"),
            bg="#6b7280", fg="#ffffff", cursor="hand2", padx=8, pady=6,
        )
        remove_btn.pack(side="left", padx=(8, 0))
        remove_btn.bind("<Button-1>", lambda e: self._remove_selected())
        remove_btn.bind("<Enter>", lambda e: remove_btn.config(bg="#4b5563"))
        remove_btn.bind("<Leave>", lambda e: remove_btn.config(bg="#6b7280"))

        self.file_count_lbl = tk.Label(
            btn_row, text="  Chưa chọn file nào", font=("Helvetica", 11),
            bg=BG_CARD, fg=FG_DIM,
        )
        self.file_count_lbl.pack(side="left", padx=10)

        # === Section 2: Bảng metadata (parse tự động + sửa tay) ===
        s2 = make_section(
            body, "BƯỚC 2 — Kiểm tra / sửa Patient, Data type, Date (double-click ô để sửa)"
        )

        table_frame = tk.Frame(s2, bg=BG_CARD)
        table_frame.pack(fill="both", expand=True, padx=15, pady=(0, 12))

        style = ttk.Style()
        style.configure(
            "Multi.Treeview", background=BG_INPUT, fieldbackground=BG_INPUT,
            foreground=FG_TEXT, rowheight=24,
        )

        self.tree = ttk.Treeview(
            table_frame, columns=TABLE_COLUMNS, displaycolumns=VISIBLE_COLUMNS,
            show="headings", height=8, selectmode="extended", style="Multi.Treeview",
        )
        for col in TABLE_COLUMNS:
            self.tree.heading(col, text=TABLE_HEADINGS[col])
        self.tree.column("file", width=360, anchor="w")
        self.tree.column("study", width=80, anchor="w")
        self.tree.column("patient", width=110, anchor="w")
        self.tree.column("data_type", width=110, anchor="w")
        self.tree.column("date", width=140, anchor="w")
        self.tree.column("route", width=70, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_cell_double_click)
        self._edit_widget: tk.Widget | None = None

        # === Section 3: Upload ===
        s3 = make_section(body, "BƯỚC 3 — Upload")

        upload_row = tk.Frame(s3, bg=BG_CARD)
        upload_row.pack(fill="x", padx=15, pady=(0, 12))

        self.upload_btn = StyledButton(
            upload_row, text="⇪  Upload", command=self._upload_all,
            bg_color=ACCENT_PURPLE, hover_color=BTN_HOVER_PURPLE, font_size=12,
        )
        self.upload_btn.pack(side="left", fill="x", expand=True)

        # === Section 4: Đã upload ===
        s4 = make_section(body, "Đã upload hoàn thành")
        uploaded_frame, self.uploaded_listbox = make_scrollable_listbox(
            s4, frame_bg=BG_CARD, height=5, font=("Courier", 10),
            bg=BG_INPUT, fg=FG_DIM, borderwidth=0, highlightthickness=0,
        )
        uploaded_frame.pack(fill="x", padx=15, pady=(0, 12))

        # === Status ===
        self.status = StatusBar(body)
        self.status.pack(fill="x", padx=25, pady=(0, 10))

    # ================================================================
    # FILE LIST MANAGEMENT
    # ================================================================

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="Chọn file (bất kỳ loại nào)",
            filetypes=[("Tất cả", "*.*")],
        )
        if not files:
            return
        existing = set(self.files)
        for f in files:
            if f not in existing:
                self.files.append(f)
                existing.add(f)
                self.parsed[f] = self._parse_path(f)
        self._refresh_table()

    def _parse_path(self, path: str) -> dict:
        info = FileNameParser(Path(path).as_posix()).parse()
        return {
            "study": info.get("study") or "",
            "patient": info.get("patient") or "",
            "data_type": info.get("datatype") or "",
            "date": _date_token(info.get("date")),
            "manual": set(),
        }

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        paths = set(sel)
        self.files = [f for f in self.files if f not in paths]
        for p in paths:
            self.parsed.pop(p, None)
        self._refresh_table()

    def _route_for(self, path: str) -> str | None:
        info = self.parsed.get(path)
        if not info:
            return None

        # Patient, Date, Data type là bắt buộc cho MỌI route (SFTP lẫn HTTP) -
        # thiếu 1 trong 3 thì chặn upload, buộc người dùng tự nhập trong bảng.
        patient = (info.get("patient") or "").strip()
        raw_data_type = (info.get("data_type") or "").strip()
        date_token = (info.get("date") or "").strip()
        if not patient or not raw_data_type or not _DATE_TOKEN_PATTERN.match(date_token):
            return None

        data_type = sanitize_path_segment(raw_data_type).replace("-", "").lower()
        if data_type in SFTP_TYPES:
            study = (info.get("study") or "").strip()
            if not study:
                return None
            return "SFTP"
        if data_type in HTTP_TYPES:
            return "HTTP"
        return None

    def _refresh_table(self):
        self._cancel_edit()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for f in self.files:
            info = self.parsed.setdefault(f, self._parse_path(f))
            route = self._route_for(f) or "?"
            self.tree.insert(
                "", "end", iid=f,
                values=(f, info.get("study", ""), info.get("patient", ""),
                        info.get("data_type", ""), info.get("date", ""), route),
            )
        for f in selected:
            if self.tree.exists(f):
                self.tree.selection_add(f)

        count = len(self.files)
        self.file_count_lbl.config(
            text=f"  ✓ {count} file" if count else "  Chưa chọn file nào",
            fg=ACCENT_GREEN if count else FG_DIM,
        )

    def _refresh_uploaded_log(self):
        self.uploaded_listbox.delete(0, "end")
        for name, type_label, dest in self.uploaded_log:
            self.uploaded_listbox.insert("end", f"  {name}   [{type_label}] -> {dest}")

    # ================================================================
    # BẢNG - SỬA TAY (inline edit)
    # ================================================================

    def _cancel_edit(self):
        if self._edit_widget is not None:
            self._edit_widget.destroy()
            self._edit_widget = None

    def _on_cell_double_click(self, event):
        self._cancel_edit()
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        # identify_column trả chỉ số theo displaycolumns (cột đang hiển thị),
        # không phải theo TABLE_COLUMNS đầy đủ (có study/route bị ẩn).
        col_index = int(col_id.replace("#", "")) - 1
        if col_index < 0 or col_index >= len(VISIBLE_COLUMNS):
            return
        col_name = VISIBLE_COLUMNS[col_index]
        if col_name not in EDITABLE_COLUMNS:
            return

        bbox = self.tree.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        current = self.parsed.get(row_id, {}).get(col_name, "")

        entry = tk.Entry(self.tree, font=("Helvetica", 10))
        entry.insert(0, current)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        self._edit_widget = entry

        def commit(_event=None):
            new_value = entry.get().strip()
            info = self.parsed.setdefault(row_id, self._parse_path(row_id))
            info[col_name] = new_value
            info.setdefault("manual", set()).add(col_name)
            self._cancel_edit()
            self._refresh_table()

        def cancel(_event=None):
            self._cancel_edit()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    # ================================================================
    # UPLOAD - TỰ ĐỘNG PHÂN LOẠI ĐÍCH
    # ================================================================

    def _upload_all(self):
        if not self.files:
            messagebox.showinfo("Không có file", "Chưa có file nào để upload.")
            return

        unresolved = [p for p in self.files if self._route_for(p) is None]
        if unresolved:
            names = "\n".join(f"  {p}" for p in unresolved)
            messagebox.showwarning(
                "Chưa xác định được đích upload",
                "Các file sau còn thiếu Patient / Date (ddmmyyyy) / Data type, "
                "hoặc Data type chưa hợp lệ (Xray/ECG/Ultrasound/CT/MRI/Others - "
                "cần thêm Study, hoặc Image/Metadata). "
                f"Vui lòng sửa lại trong bảng trước khi upload:\n\n{names}",
            )
            return

        sftp_groups: dict[str, list[str]] = {}
        http_files: list[str] = []
        for p in self.files:
            route = self._route_for(p)
            if route == "SFTP":
                info = self.parsed[p]
                key = infer_sftp_child_path(
                    info["study"], info["patient"], info["date"], info["data_type"]
                )
                is_new_group = key not in sftp_groups
                sftp_groups.setdefault(key, []).append(p)
                if is_new_group:
                    log.info(
                        "SFTP dest: %s/%s (file: %s)",
                        SFTP_BUFFER_PATH.rstrip("/"), key, p,
                    )
            else:
                http_files.append(p)

        sftp_summary = "\n".join(f"  SFTP/{k}: {len(v)} file" for k, v in sftp_groups.items())
        http_summary = f"  API: {len(http_files)} file" if http_files else ""
        summary = "\n".join(s for s in (sftp_summary, http_summary) if s)
        if not messagebox.askyesno(
            "Upload", f"Upload {len(self.files)} file theo đích tự động:\n\n{summary}"
        ):
            return

        sftp_jobs = [UploadJob(label=key, files=paths) for key, paths in sftp_groups.items()]

        if sftp_jobs:
            if not SFTP_BUFFER_PATH:
                messagebox.showwarning(
                    "Thiếu cấu hình", "Chưa cấu hình SFTP_BUFFER_PATH trong .env."
                )
                return
            run_upload_batch(
                self, self.upload_btn, self.status,
                get_sftp_uploader(self, SFTP_BUFFER_PATH), sftp_jobs,
                on_job_done=self._on_sftp_job_uploaded,
                on_batch_done=lambda ok: self._start_http_batch(http_files),
            )
        else:
            self._start_http_batch(http_files)

    def _start_http_batch(self, http_files: list[str]) -> None:
        if not http_files:
            return

        if not API_UPLOAD_URL:
            msg = (
                "CHƯA CÓ BACKEND ENDPOINT!\n\n"
                "Bạn chưa cấu hình API_UPLOAD_URL trong file .env.\n"
                f"Giả lập upload thành công {len(http_files)} file để demo?"
            )
            if not messagebox.askyesno("Upload Demo", msg):
                return
            for path in http_files:
                self._mark_uploaded(path, "API (demo)")
            self._refresh_table()
            self._refresh_uploaded_log()
            self.status.set(f"Demo: {len(http_files)} file đã upload (API)", "success")
            return

        owner = simpledialog.askstring(
            "Người dùng", "Tên người dùng đang tải dữ liệu:", initialvalue=API_UPLOAD_OWNER, parent=self,
        )
        if owner is None:
            return
        owner = owner.strip()

        jobs = [UploadJob(label=os.path.basename(p), files=[p]) for p in http_files]
        uploader = HttpUploader(API_UPLOAD_URL, API_BEARER_TOKEN, owner=owner)

        def get_uploader(on_ready, on_error):
            on_ready(uploader)

        run_upload_batch(
            self, self.upload_btn, self.status, get_uploader, jobs,
            on_job_done=self._on_http_job_uploaded,
        )

    def _on_http_job_uploaded(self, job: UploadJob) -> None:
        for path in job.files:
            self._mark_uploaded(path, "API")
        self._refresh_table()
        self._refresh_uploaded_log()

    def _on_sftp_job_uploaded(self, job: UploadJob) -> None:
        full_path = f"{SFTP_BUFFER_PATH.rstrip('/')}/{job.label}"
        for path in job.files:
            log.info("Đã upload %s -> %s", path, full_path)
            self._mark_uploaded(path, f"SFTP/{job.label}")
        self._refresh_table()
        self._refresh_uploaded_log()

    # ================================================================
    # HELPERS
    # ================================================================

    def _mark_uploaded(self, path: str, destination: str) -> None:
        type_label = self.parsed.get(path, {}).get("data_type", "")
        self.uploaded_log.append((os.path.basename(path), type_label, destination))
        if path in self.files:
            self.files.remove(path)
        self.parsed.pop(path, None)


__all__ = ["MultiUploadPage"]
