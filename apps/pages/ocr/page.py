"""OCR review page - UI shell.

Chỉ chịu trách nhiệm dựng layout, bắt sự kiện và điều phối giữa:
- StorageBackend (local hoặc SFTP) cho mọi I/O
- lab_records service để scan/build hồ sơ
- payload_io / excel_export để đọc ghi dữ liệu
- media_viewer + form_builder để dựng UI chi tiết
"""

from __future__ import annotations

import logging
import os
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    BG_CARD,
    BG_INPUT,
    BG_MAIN,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    BTN_HOVER_GREEN,
    FG_DIM,
    FG_TEXT,
    FG_TITLE,
    SFTP_DEMO_MODE,
    SFTP_HOST,
    SFTP_PATH,
    SFTP_PORT,
)
from apps.services import lab_records
from apps.services.excel_export import write_rows_to_xlsx
from apps.services.lab_records import LAB_VALIDATE_TYPES, format_date_token
from apps.services.payload_io import read_csv, read_json, write_csv, write_json
from apps.services.storage import (
    LocalBackend,
    SftpBackend,
    StorageBackend,
    safe_is_dir,
)
from apps.widgets import (
    StatusBar,
    StyledButton,
    make_header,
    make_section,
    ScrollableFrame,
    show_info,
    show_warning,
)

from .form_builder import (
    LabFormState,
    add_result_row,
    build_lab_form,
    build_monitor_form,
    remove_result_row,
)
from .media_viewer import IMG_EXTS, MediaViewer

log = logging.getLogger(__name__)

OCR_VALIDATE_TYPE = "OCR VILIDATE"


class OCRPage(tk.Frame):
    def __init__(self, parent: tk.Widget, controller) -> None:
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller

        # --- Storage & state ---
        self.backend: StorageBackend | None = None
        self.sftp_connected = False
        self.ocr_type: str | None = None
        self.root_dir: str | None = None

        # OCR non-validate state
        self.all_confirmed: list[dict] = []
        self.confirmed_files: list[tuple[str, str]] = []
        self.folders: list[str] = []

        # Current selection
        self.current_folder_name: str | None = None
        self.current_folder_path: str | None = None
        self.current_json_file: str | None = None
        self.current_json_data: dict | None = None
        self.current_csv_file: str | None = None
        self.current_csv_rows: list[dict] = []
        self.current_csv_fieldnames: list[str] = []

        # Lab validate state
        self.lab_records: list[dict] = []
        self.lab_processing_roots: list[str] = []
        self.lab_root_dir_error: str | None = None
        self.filtered_lab_records: list[dict] = []
        self.current_lab_record: dict | None = None
        self.lab_type_var = tk.StringVar(value=LAB_VALIDATE_TYPES[0])

        # Form state (monitor/lab)
        self._form_state: LabFormState | None = None
        self.form_vars: dict[str, tk.StringVar] = {}
        self.result_vars: list[dict[str, tk.StringVar]] = []

        # --- Build UI ---
        make_header(self, controller, "Đánh giá kết quả OCR")

        self._body_scroll = ScrollableFrame(self, bg=BG_MAIN)
        self._body_scroll.pack(fill="both", expand=True)
        self.body = self._body_scroll.interior
        self._build_login_section()

        self.review_frame = tk.Frame(self, bg=BG_MAIN)

    # =====================================================================
    # LOGIN SECTION
    # =====================================================================

    def _build_login_section(self) -> None:
        s1 = make_section(self.body, "ĐĂNG NHẬP SFTP")

        row_user = tk.Frame(s1, bg=BG_CARD)
        row_user.pack(fill="x", padx=15, pady=4)
        tk.Label(
            row_user,
            text="Username:",
            font=("Helvetica", 12),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=10,
            anchor="e",
        ).pack(side="left")
        self.user_var = tk.StringVar(value="")
        tk.Entry(
            row_user,
            textvariable=self.user_var,
            font=("Helvetica", 12),
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=0,
            highlightthickness=1,
            highlightcolor=ACCENT_BLUE,
        ).pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))

        row_pass = tk.Frame(s1, bg=BG_CARD)
        row_pass.pack(fill="x", padx=15, pady=(4, 12))
        tk.Label(
            row_pass,
            text="Password:",
            font=("Helvetica", 12),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=10,
            anchor="e",
        ).pack(side="left")
        self.pass_var = tk.StringVar(value="")
        tk.Entry(
            row_pass,
            textvariable=self.pass_var,
            font=("Helvetica", 12),
            show="●",
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=0,
            highlightthickness=1,
            highlightcolor=ACCENT_BLUE,
        ).pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))

        btn_frame = tk.Frame(s1, bg=BG_CARD)
        btn_frame.pack(pady=(0, 15))
        self.connect_btn = StyledButton(
            btn_frame,
            text="Kết nối SFTP",
            command=self._connect_sftp,
            bg_color=ACCENT_BLUE,
            hover_color=BTN_HOVER_BLUE,
            font_size=13,
        )
        self.connect_btn.pack()

        self.status = StatusBar(self.body)
        self.status.pack(fill="x", padx=25, pady=(12, 0))

        self.content_frame = tk.Frame(self.body, bg=BG_MAIN)
        self.content_frame.pack(fill="both", expand=True, padx=25, pady=10)
        tk.Label(
            self.content_frame,
            text="Vui lòng đăng nhập SFTP để tiếp tục",
            font=("Helvetica", 13),
            bg=BG_MAIN,
            fg=FG_DIM,
        ).pack(expand=True)

    # =====================================================================
    # SFTP CONNECT
    # =====================================================================

    def _connect_sftp(self) -> None:
        if SFTP_DEMO_MODE:
            self.connect_btn.set_state("disabled")
            self.status.set("Đang kết nối (DEMO)...", "working")
            self.after(500, lambda: self._on_connected(LocalBackend()))
            return

        host = SFTP_HOST.strip()
        port = SFTP_PORT
        username = self.user_var.get().strip()
        password = self.pass_var.get()

        if not host:
            show_warning(self, "Thiếu thông tin", "Chưa cấu hình host SFTP trong code.")
            return
        if not username:
            show_warning(self, "Thiếu thông tin", "Vui lòng nhập username.")
            return
        if not password:
            show_warning(self, "Thiếu thông tin", "Vui lòng nhập password.")
            return

        self.connect_btn.set_state("disabled")
        self.status.set("Đang kết nối...", "working")

        def do_connect() -> None:
            try:
                import paramiko

                transport = paramiko.Transport((host, port))
                transport.connect(username=username, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)
                backend = SftpBackend(sftp, transport)
                self.controller.after(0, lambda: self._on_connected(backend))
            except ImportError:
                self.controller.after(
                    0,
                    lambda: self._on_connect_fail(
                        "Thiếu thư viện paramiko. Chạy: pip install paramiko"
                    ),
                )
            except Exception as e:  # noqa: BLE001 - network layer
                self.controller.after(0, lambda: self._on_connect_fail(str(e)))

        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connected(self, backend: StorageBackend) -> None:
        self.backend = backend
        self.sftp_connected = True
        self.connect_btn.set_state("normal")
        self.status.set(
            f"Đã kết nối thành công tới {SFTP_HOST or 'DEMO'}", "success"
        )

        for w in self.content_frame.winfo_children():
            w.destroy()

        tk.Label(
            self.content_frame,
            text="Chọn loại đánh giá OCR",
            font=("Helvetica", 15, "bold"),
            bg=BG_MAIN,
            fg=FG_TITLE,
        ).pack(pady=(20, 15))

        cards = tk.Frame(self.content_frame, bg=BG_MAIN)
        cards.pack()

        btn_data = [
            (
                OCR_VALIDATE_TYPE,
                "Đánh giá kết quả OCR phiếu xét nghiệm",
                ACCENT_BLUE,
                BTN_HOVER_BLUE,
            ),
        ]

        for title, desc, color, hover in btn_data:
            card = tk.Frame(
                cards,
                bg=BG_CARD,
                highlightbackground=BORDER_COLOR,
                highlightthickness=1,
                cursor="hand2",
            )
            card.pack(pady=6, ipadx=20, ipady=10, fill="x")

            inner = tk.Frame(card, bg=BG_CARD)
            inner.pack(fill="x", padx=20, pady=8)

            left = tk.Frame(inner, bg=BG_CARD)
            left.pack(side="left", fill="both", expand=True)

            tk.Label(
                left,
                text=title,
                font=("Helvetica", 15, "bold"),
                bg=BG_CARD,
                fg=FG_TITLE,
            ).pack(anchor="w")
            tk.Label(
                left,
                text=desc,
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=FG_DIM,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))

            arrow = tk.Label(
                inner, text=">", font=("Helvetica", 16, "bold"), bg=BG_CARD, fg=color
            )
            arrow.pack(side="right", padx=(10, 0))

            for widget in [card, inner, left, arrow] + left.winfo_children():
                widget.bind(
                    "<Button-1>", lambda e, t=title: self._on_ocr_type_selected(t)
                )
                widget.bind(
                    "<Enter>",
                    lambda e, c=card, clr=hover: c.config(
                        highlightbackground=clr, highlightthickness=2
                    ),
                )
                widget.bind(
                    "<Leave>",
                    lambda e, c=card: c.config(
                        highlightbackground=BORDER_COLOR, highlightthickness=1
                    ),
                )

    def _on_connect_fail(self, error_msg: str) -> None:
        self.connect_btn.set_state("normal")
        self.status.set(f"Kết nối thất bại: {error_msg}", "error")

    # =====================================================================
    # OCR TYPE SELECTION
    # =====================================================================

    def _on_ocr_type_selected(self, ocr_type: str) -> None:
        if self.ocr_type != ocr_type:
            self.all_confirmed = []
            self.confirmed_files = []
            self.lab_records = []
            self.filtered_lab_records = []
            self.current_lab_record = None
        self.ocr_type = ocr_type

        if SFTP_DEMO_MODE:
            demo_path = SFTP_PATH
            if demo_path and os.path.isdir(demo_path):
                self.root_dir = demo_path
            else:
                root_dir = filedialog.askdirectory(
                    title=f"Chọn thư mục gốc cho {ocr_type} (DEMO)"
                )
                if not root_dir:
                    return
                self.root_dir = root_dir
        else:
            self.root_dir = SFTP_PATH
            if not self.root_dir:
                show_warning(
                    self,
                    "Thiếu cấu hình",
                    f"Chưa cấu hình đường dẫn SFTP cho {ocr_type}.",
                )
                return
        self._show_review_ui()

    def _is_validate_mode(self) -> bool:
        return self.ocr_type == OCR_VALIDATE_TYPE

    # =====================================================================
    # REVIEW UI
    # =====================================================================

    def _show_review_ui(self) -> None:
        self.body.pack_forget()
        for w in self.review_frame.winfo_children():
            w.destroy()
        self.review_frame.pack(fill="both", expand=True)

        # Sub-header
        sub_hdr = tk.Frame(self.review_frame, bg=BG_CARD, height=44)
        sub_hdr.pack(fill="x")
        sub_hdr.pack_propagate(False)

        back_lbl = tk.Label(
            sub_hdr,
            text="  ← Quay lại  ",
            font=("Helvetica", 11),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="hand2",
        )
        back_lbl.pack(side="left", padx=10)
        back_lbl.bind("<Button-1>", lambda e: self._back_to_type_selection())
        back_lbl.bind(
            "<Enter>",
            lambda e: back_lbl.config(
                fg=BTN_HOVER_BLUE, font=("Helvetica", 11, "underline")
            ),
        )
        back_lbl.bind(
            "<Leave>",
            lambda e: back_lbl.config(fg=ACCENT_BLUE, font=("Helvetica", 11)),
        )

        tk.Label(
            sub_hdr,
            text=self.ocr_type,
            font=("Helvetica", 14, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(side="left", padx=5)

        tk.Frame(self.review_frame, bg=BORDER_COLOR, height=1).pack(fill="x")

        pw = tk.PanedWindow(
            self.review_frame,
            orient="horizontal",
            bg=BORDER_COLOR,
            sashwidth=4,
            sashrelief="flat",
        )
        pw.pack(fill="both", expand=True, pady=2)

        left = self._build_folder_list_panel(pw)
        pw.add(left, minsize=180, width=220)

        center = self._build_viewer_panel(pw)
        sw = self.controller.winfo_width() or self.controller.winfo_screenwidth()
        half = int((sw - 220) * 0.5)
        pw.add(center, minsize=250, width=half)

        right = self._build_form_panel(pw)
        pw.add(right, minsize=250, width=half)

        self.review_frame.bind_all("<Return>", lambda e: self._submit())

        self.review_status = StatusBar(self.review_frame)
        self.review_status.pack(fill="x", padx=5, pady=(0, 5))

        self._load_folders()

    def _back_to_type_selection(self) -> None:
        self.review_frame.unbind_all("<Return>")
        self.review_frame.pack_forget()
        self.body.pack(fill="both", expand=True)

    def _build_folder_list_panel(self, parent) -> tk.Frame:
        left = tk.Frame(parent, bg=BG_CARD)

        list_title = (
            "Danh sách hồ sơ" if self._is_validate_mode() else "Danh sách folder"
        )
        self.folder_list_title = tk.Label(
            left,
            text=list_title,
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        )
        self.folder_list_title.pack(padx=10, pady=(10, 5), anchor="w")

        if self._is_validate_mode():
            filter_row = tk.Frame(left, bg=BG_CARD)
            filter_row.pack(fill="x", padx=10, pady=(0, 8))
            tk.Label(
                filter_row,
                text="Loại:",
                font=("Helvetica", 10, "bold"),
                bg=BG_CARD,
                fg=FG_DIM,
            ).pack(side="left")
            self.lab_type_box = ttk.Combobox(
                filter_row,
                textvariable=self.lab_type_var,
                state="readonly",
                values=LAB_VALIDATE_TYPES,
                font=("Helvetica", 10),
            )
            self.lab_type_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
            self.lab_type_box.bind(
                "<<ComboboxSelected>>", self._on_lab_type_changed
            )

        list_frame = tk.Frame(left, bg=BG_CARD)
        list_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        sb = tk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.folder_listbox = tk.Listbox(
            list_frame,
            font=("Helvetica", 11),
            bg=BG_INPUT,
            fg=FG_TEXT,
            selectbackground=ACCENT_BLUE,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=sb.set,
        )
        self.folder_listbox.pack(fill="both", expand=True)
        sb.config(command=self.folder_listbox.yview)
        self.folder_listbox.bind("<<ListboxSelect>>", self._on_folder_selected)

        export_text = "Export theo loại" if self._is_validate_mode() else "Export Excel"
        self.export_btn = StyledButton(
            left,
            text=export_text,
            command=self._export_excel,
            bg_color=ACCENT_GREEN,
            hover_color=BTN_HOVER_GREEN,
            font_size=11,
        )
        self.export_btn.pack(padx=10, pady=10, fill="x")

        return left

    def _build_viewer_panel(self, parent) -> tk.Frame:
        center = tk.Frame(parent, bg=BG_CARD)

        tk.Label(
            center,
            text="Xem trước",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(padx=10, pady=(10, 5), anchor="w")

        viewer_container = tk.Frame(center, bg=BG_CARD)
        viewer_container.pack(fill="both", expand=True, padx=5, pady=5)

        self.viewer_canvas = tk.Canvas(
            viewer_container, bg=BG_CARD, highlightthickness=0
        )
        viewer_sb = tk.Scrollbar(
            viewer_container, orient="vertical", command=self.viewer_canvas.yview
        )
        self.viewer_canvas.configure(yscrollcommand=viewer_sb.set)
        viewer_sb.pack(side="right", fill="y")
        self.viewer_canvas.pack(side="left", fill="both", expand=True)

        self.viewer_frame = tk.Frame(self.viewer_canvas, bg=BG_CARD)
        self._viewer_cw = self.viewer_canvas.create_window(
            (0, 0), window=self.viewer_frame, anchor="nw"
        )
        self.viewer_frame.bind(
            "<Configure>",
            lambda e: self.viewer_canvas.configure(
                scrollregion=self.viewer_canvas.bbox("all")
            ),
        )
        self.viewer_canvas.bind(
            "<Configure>",
            lambda e: self.viewer_canvas.itemconfig(self._viewer_cw, width=e.width),
        )

        def _vw_mw(evt):
            self.viewer_canvas.yview_scroll(int(-1 * evt.delta), "units")

        self.viewer_canvas.bind(
            "<Enter>", lambda e: self.viewer_canvas.bind_all("<MouseWheel>", _vw_mw)
        )
        self.viewer_canvas.bind(
            "<Leave>", lambda e: self.viewer_canvas.unbind_all("<MouseWheel>")
        )

        viewer_hint = (
            "Chọn hồ sơ để xem" if self._is_validate_mode() else "Chọn folder để xem"
        )
        tk.Label(
            self.viewer_frame,
            text=viewer_hint,
            font=("Helvetica", 12),
            bg=BG_CARD,
            fg=FG_DIM,
        ).pack(expand=True)

        self.media_viewer = MediaViewer(
            self.viewer_frame,
            self.viewer_canvas,
            self.backend,  # type: ignore[arg-type]
            lambda: self.ocr_type,
        )
        return center

    def _build_form_panel(self, parent) -> tk.Frame:
        right = tk.Frame(parent, bg=BG_CARD)

        tk.Label(
            right,
            text="Chỉnh sửa dữ liệu",
            font=("Helvetica", 12, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(padx=10, pady=(10, 5), anchor="w")

        form_container = tk.Frame(right, bg=BG_CARD)
        form_container.pack(fill="both", expand=True, padx=5)

        self.form_canvas = tk.Canvas(
            form_container, bg=BG_CARD, highlightthickness=0
        )
        form_sb = tk.Scrollbar(
            form_container, orient="vertical", command=self.form_canvas.yview
        )
        self.form_canvas.configure(yscrollcommand=form_sb.set)
        form_sb.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)

        self.form_inner = tk.Frame(self.form_canvas, bg=BG_CARD)
        self._form_cw = self.form_canvas.create_window(
            (0, 0), window=self.form_inner, anchor="nw"
        )
        self.form_inner.bind(
            "<Configure>",
            lambda e: self.form_canvas.configure(
                scrollregion=self.form_canvas.bbox("all")
            ),
        )
        self.form_canvas.bind(
            "<Configure>",
            lambda e: self.form_canvas.itemconfig(self._form_cw, width=e.width),
        )

        def _mw(evt):
            self.form_canvas.yview_scroll(int(-1 * evt.delta), "units")

        self.form_canvas.bind(
            "<Enter>", lambda e: self.form_canvas.bind_all("<MouseWheel>", _mw)
        )
        self.form_canvas.bind(
            "<Leave>", lambda e: self.form_canvas.unbind_all("<MouseWheel>")
        )

        form_hint = (
            "Chọn hồ sơ để xem dữ liệu"
            if self._is_validate_mode()
            else "Chọn folder để xem dữ liệu"
        )
        tk.Label(
            self.form_inner,
            text=form_hint,
            font=("Helvetica", 11),
            bg=BG_CARD,
            fg=FG_DIM,
        ).pack(pady=20)

        self.submit_btn = StyledButton(
            right,
            text="Submit xác nhận",
            command=self._submit,
            bg_color=ACCENT_BLUE,
            hover_color=BTN_HOVER_BLUE,
            font_size=12,
        )
        self.submit_btn.pack(padx=10, pady=10, fill="x")

        return right

    # =====================================================================
    # FOLDER LIST
    # =====================================================================

    def _load_folders(self) -> None:
        if self._is_validate_mode():
            self._load_lab_records()
            return

        if not self.backend:
            self.review_status.set("Chưa có kết nối storage.", "error")
            return

        folders: list[str] = []
        try:
            if not self.root_dir or not self.backend.is_dir(self.root_dir):
                self.review_status.set("Thư mục không hợp lệ", "error")
                return
            for name in sorted(self.backend.listdir(self.root_dir)):
                full = self.backend.join(self.root_dir, name)
                if not safe_is_dir(self.backend, full):
                    continue
                try:
                    files = self.backend.listdir(full)
                except Exception:
                    continue
                if any(f.endswith("_final.json") for f in files):
                    continue
                folders.append(name)
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc thư mục: {e}", "error")
            return

        self.folders = folders
        try:
            self.all_confirmed, self.confirmed_files = (
                self._collect_pending_confirmed_exports()
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc file xác nhận: {e}", "error")
            return

        self.folder_listbox.delete(0, "end")
        for f in folders:
            self.folder_listbox.insert("end", "  " + f)
        pending_exports = len(self.confirmed_files)
        self.review_status.set(
            f"Tìm thấy {len(folders)} folder chưa hoàn thành, "
            f"{pending_exports} folder đã xác nhận chờ export",
            "info",
        )

    def _collect_pending_confirmed_exports(
        self,
    ) -> tuple[list[dict], list[tuple[str, str]]]:
        rows: list[dict] = []
        confirmed_files: list[tuple[str, str]] = []
        if not self.backend or not self.root_dir:
            return rows, confirmed_files

        for folder_name in sorted(self.backend.listdir(self.root_dir)):
            folder_path = self.backend.join(self.root_dir, folder_name)
            if not safe_is_dir(self.backend, folder_path):
                continue
            try:
                files = self.backend.listdir(folder_path)
            except Exception:
                continue
            if any(f.endswith("_final.json") for f in files):
                continue
            confirmed_file = next(
                (f for f in sorted(files) if f.endswith("_confirmed.json")), None
            )
            if not confirmed_file:
                continue
            data = read_json(self.backend, folder_path, confirmed_file)
            rows.extend(
                lab_records.confirmed_to_rows(folder_name, data, self.ocr_type or "")
            )
            base = lab_records.normalize_json_stem(confirmed_file)
            confirmed_files.append(
                (
                    self.backend.join(folder_path, confirmed_file),
                    self.backend.join(folder_path, base + "_final.json"),
                )
            )
        return rows, confirmed_files

    # =====================================================================
    # LAB VALIDATE MODE
    # =====================================================================

    def _load_lab_records(self, preserve_key: str | None = None) -> None:
        assert self.backend is not None
        scan = lab_records.scan_lab_records(self.backend, self.root_dir)
        self.lab_records = scan.records
        self.lab_processing_roots = scan.processing_roots
        self.lab_root_dir_error = scan.root_dir_error
        self.lab_done_count = scan.done_count
        # Update root_dir if resolver fixed case
        if scan.records and not scan.root_dir_error:
            pass  # root_dir đã đúng sau khi resolver run
        self._refresh_lab_record_list(preserve_key=preserve_key)

        if self.lab_root_dir_error:
            self.review_status.set(self.lab_root_dir_error, "error")
            return

        validated_count = sum(
            1 for record in self.lab_records if record["status"] == "validated"
        )
        processing_count = len(self.lab_processing_roots)
        if not processing_count:
            self.review_status.set(
                f"Không tìm thấy thư mục PROCESSING dưới {self.root_dir}. "
                "Hãy kiểm tra lại SFTP_PATH hoặc cấu trúc thư mục study.",
                "error",
            )
            return

        # Khi list r\u1ed7ng nh\u01b0ng v\u1eabn c\u00f3 patient/date folder, gi\u1ea3i th\u00edch c\u1ee5 th\u1ec3
        # \u0111\u1ec3 user bi\u1ebft kh\u00e2u n\u00e0o b\u1ecb r\u01a1i (date sai format / thi\u1ebfu Image /
        # thi\u1ebfu JSON / thi\u1ebfu CSV) thay v\u00ec "T\u00ecm th\u1ea5y 0 h\u1ed3 s\u01a1".
        if not self.lab_records and scan.patient_dirs:
            bits: list[str] = [
                f"\u0110\u00e3 qu\u00e9t {scan.patient_dirs} patient",
                f"{scan.valid_date_dirs} folder ng\u00e0y h\u1ee3p l\u1ec7",
            ]
            if scan.invalid_date_dirs:
                bits.append(
                    f"{scan.invalid_date_dirs} folder ng\u00e0y SAI format ddmmyyyy"
                )
            if scan.image_dirs_missing:
                bits.append(
                    f"thi\u1ebfu th\u01b0 m\u1ee5c Image/ \u1edf {scan.image_dirs_missing} ng\u00e0y"
                )
            if scan.incomplete_groups:
                bits.append(
                    f"{len(scan.incomplete_groups)} PDF thi\u1ebfu JSON/CSV"
                )
                first = scan.incomplete_groups[0]
                bits.append(
                    f"VD: {first['pdf']} thi\u1ebfu {first['missing']}"
                )
            self.review_status.set(
                "Kh\u00f4ng t\u00ecm th\u1ea5y h\u1ed3 s\u01a1 review \u0111\u01b0\u1ee3c. " + ", ".join(bits)
                + ". Xem log chi ti\u1ebft (logging_setup).",
                "error",
            )
            return

        done_part = (
            f", \u0111\u00e3 \u1ea9n {scan.done_count} ca done" if scan.done_count else ""
        )
        incomplete_part = (
            f", b\u1ecf qua {len(scan.incomplete_groups)} PDF thi\u1ebfu JSON/CSV"
            if scan.incomplete_groups
            else ""
        )
        self.review_status.set(
            f"T\u00ecm th\u1ea5y {len(self.lab_records)} h\u1ed3 s\u01a1 {OCR_VALIDATE_TYPE} "
            f"trong {processing_count} th\u01b0 m\u1ee5c PROCESSING, "
            f"{validated_count} h\u1ed3 s\u01a1 \u0111\u00e3 validated"
            + done_part + incomplete_part,
            "info",
        )

    def _refresh_lab_record_list(self, preserve_key: str | None = None) -> None:
        current_type = (
            self.lab_type_var.get().strip() or LAB_VALIDATE_TYPES[0]
        )
        if current_type not in LAB_VALIDATE_TYPES:
            current_type = LAB_VALIDATE_TYPES[0]
            self.lab_type_var.set(current_type)

        if current_type == LAB_VALIDATE_TYPES[0]:
            self.filtered_lab_records = list(self.lab_records)
        else:
            self.filtered_lab_records = [
                record
                for record in self.lab_records
                if record["record_type"] == current_type
            ]

        self.folder_listbox.delete(0, "end")
        for idx, record in enumerate(self.filtered_lab_records):
            prefix = "  ✓ " if record["status"] == "validated" else "  "
            self.folder_listbox.insert("end", prefix + record["display_name"])
            if record["status"] == "validated":
                self.folder_listbox.itemconfig(idx, fg=ACCENT_GREEN)

        if preserve_key:
            for idx, record in enumerate(self.filtered_lab_records):
                if record["record_key"] == preserve_key:
                    self.folder_listbox.selection_clear(0, "end")
                    self.folder_listbox.selection_set(idx)
                    self.folder_listbox.see(idx)
                    break

    def _on_lab_type_changed(self, event=None) -> None:
        self._refresh_lab_record_list()

    def _on_lab_record_selected(self) -> None:
        sel = self.folder_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.filtered_lab_records):
            return

        record = self.filtered_lab_records[idx]
        self.current_lab_record = record
        self.current_folder_name = record["display_name"]
        self.current_folder_path = record["image_path"]
        self.current_json_file = record["active_json_file"]
        self.current_csv_file = record["active_csv_file"]

        assert self.backend is not None
        try:
            self.current_csv_fieldnames, self.current_csv_rows = read_csv(
                self.backend, record["image_path"], record["active_csv_file"]
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc CSV: {e}", "error")
            self.current_csv_fieldnames, self.current_csv_rows = [], []
            return

        self.media_viewer.display_media(record["image_path"], [record["pdf_file"]])
        self._load_form_data(record["image_path"], record["active_json_file"])

        status_text = "validated" if record["status"] == "validated" else "pending"
        self.review_status.set(
            f"{record['record_type']} | {record['study_id']} | {record['patient_id']} "
            f"| {format_date_token(record['date_token'])} | {status_text} "
            f"| PDF: {record['pdf_file']} "
            f"| JSON: {record['active_json_file']} | CSV: {record['active_csv_file']}",
            "success" if record["status"] == "validated" else "info",
        )

    def _build_lab_validated_payload(self) -> dict:
        confirmed = {
            key: value
            for key, value in (self.current_json_data or {}).items()
            if key != "results"
        }
        for key in self.form_vars:
            value = self.form_vars[key].get()
            confirmed[key] = value if value else None

        confirmed["results"] = []
        for rv in self.result_vars:
            row: dict = {}
            has_data = False
            for key, var in rv.items():
                if key == "_frame":
                    continue
                value = var.get()  # type: ignore[union-attr]
                row[key] = value if value else None
                if value:
                    has_data = True
            if has_data:
                confirmed["results"].append(row)
        return confirmed

    def _submit_lab_validation(self) -> None:
        if not self.current_lab_record or not self.current_json_data:
            self.review_status.set("Vui lòng chọn hồ sơ trước", "error")
            return

        confirmed = self._build_lab_validated_payload()
        record = self.current_lab_record
        validated_json_name = record["base_stem"] + "_validated.json"
        validated_csv_name = record["base_stem"] + "_validated.csv"

        assert self.backend is not None
        try:
            write_json(
                self.backend, record["image_path"], validated_json_name, confirmed
            )
            csv_rows = lab_records.build_lab_rows(record, confirmed)
            write_csv(
                self.backend, record["image_path"], validated_csv_name, csv_rows
            )
            self.current_csv_fieldnames, self.current_csv_rows = read_csv(
                self.backend, record["image_path"], validated_csv_name
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi lưu validated: {e}", "error")
            return

        self.current_json_file = validated_json_name
        self.current_csv_file = validated_csv_name
        self.current_json_data = confirmed

        self.lab_type_var.set(record["record_type"])
        self._load_lab_records(preserve_key=record["record_key"])
        self.review_status.set(
            f"Đã validated JSON + CSV cho {record['study_id']} / "
            f"{record['patient_id']} / {format_date_token(record['date_token'])} "
            f"/ {record['record_type']}",
            "success",
        )

    def _export_lab_excel(self) -> None:
        selected_type = self.lab_type_var.get().strip() or LAB_VALIDATE_TYPES[0]
        if selected_type == LAB_VALIDATE_TYPES[0]:
            show_warning(
                self, "Chọn loại", "Vui lòng chọn 1 loại cụ thể để export."
            )
            return

        records = [
            record
            for record in self.lab_records
            if record["record_type"] == selected_type
            and record["status"] == "validated"
        ]
        if not records:
            show_warning(
                self,
                "Không có dữ liệu",
                f"Chưa có hồ sơ validated cho loại {selected_type}.",
            )
            return

        safe_type = (
            re.sub(r"[^A-Za-z0-9._-]+", "_", selected_type).strip("_") or "type"
        )
        output_path = filedialog.asksaveasfilename(
            title="Lưu file Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"OCR_VILIDATE_{safe_type}.xlsx",
        )
        if not output_path:
            return

        assert self.backend is not None
        rows: list[dict] = []
        rename_pairs: list[tuple[str, str]] = []
        for record in records:
            validated_csv = record.get("csv_validated")
            validated_json = record.get("json_validated")
            if not validated_csv or not validated_json:
                continue
            try:
                _, csv_rows = read_csv(
                    self.backend, record["image_path"], validated_csv
                )
            except Exception as e:  # noqa: BLE001
                self.review_status.set(f"Lỗi đọc CSV validated: {e}", "error")
                return
            rows.extend(csv_rows)
            rename_pairs.append(
                (
                    self.backend.join(record["image_path"], validated_json),
                    self.backend.join(
                        record["image_path"], record["base_stem"] + "_done.json"
                    ),
                )
            )
            rename_pairs.append(
                (
                    self.backend.join(record["image_path"], validated_csv),
                    self.backend.join(
                        record["image_path"], record["base_stem"] + "_done.csv"
                    ),
                )
            )

        if not rows:
            show_warning(
                self,
                "Không có dữ liệu",
                f"Không đọc được CSV validated cho loại {selected_type}.",
            )
            return

        try:
            write_rows_to_xlsx(output_path, rows, sheet_name=selected_type)
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi xuất Excel: {e}", "error")
            return

        rename_errors: list[str] = []
        for source_path, target_path in rename_pairs:
            try:
                self.backend.rename(source_path, target_path)
            except Exception as e:  # noqa: BLE001
                rename_errors.append(f"{self.backend.basename(source_path)}: {e}")

        self._load_lab_records()
        if rename_errors:
            self.review_status.set(
                f"Đã export loại {selected_type}, nhưng có {len(rename_errors)} "
                "file không rename được sang done",
                "error",
            )
            return

        self.review_status.set(
            f"Đã export {len(rows)} dòng cho loại {selected_type} và "
            "chuyển file sang trạng thái done",
            "success",
        )
        show_info(
            self,
            "Thành công",
            f"Đã export loại {selected_type}: {len(rows)} dòng dữ liệu",
        )

    # =====================================================================
    # NON-VALIDATE MODE
    # =====================================================================

    def _on_folder_selected(self, event) -> None:
        if self._is_validate_mode():
            self._on_lab_record_selected()
            return

        sel = self.folder_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if self.folder_listbox.get(idx).startswith("  ✓"):
            return
        folder_name = self.folders[idx]
        assert self.backend is not None and self.root_dir is not None
        folder_path = self.backend.join(self.root_dir, folder_name)

        self.current_folder_name = folder_name
        self.current_folder_path = folder_path

        try:
            files = self.backend.listdir(folder_path)
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc folder: {e}", "error")
            return

        json_file = None
        confirmed_json_file = None
        raw_json_file = None
        media_files: list[str] = []
        is_monitor = self.ocr_type == "OCR BEDSIDE MONITOR"

        for f in files:
            suffix = Path(f).suffix.lower()
            if suffix == ".json":
                if f.endswith("_confirmed.json") and not confirmed_json_file:
                    confirmed_json_file = f
                elif not f.endswith("_final.json") and not raw_json_file:
                    raw_json_file = f
            if is_monitor:
                if not media_files and suffix in IMG_EXTS:
                    media_files.append(f)
            else:
                if suffix == ".pdf" or suffix in IMG_EXTS:
                    media_files.append(f)

        json_file = confirmed_json_file or raw_json_file
        self.media_viewer.display_media(folder_path, media_files)
        self._load_form_data(folder_path, json_file)
        self.review_status.set(f"Folder: {folder_name}", "info")

    # =====================================================================
    # FORM LOADING
    # =====================================================================

    def _load_form_data(self, folder_path: str, json_file: str | None) -> None:
        for w in self.form_inner.winfo_children():
            w.destroy()
        self.form_vars = {}
        self.result_vars = []
        self._form_state = None

        if not json_file:
            tk.Label(
                self.form_inner,
                text="Không tìm thấy file JSON",
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=FG_DIM,
            ).pack(pady=20)
            return

        assert self.backend is not None
        try:
            data = read_json(self.backend, folder_path, json_file)
        except Exception as e:  # noqa: BLE001
            from apps.config import ACCENT_RED as _RED

            tk.Label(
                self.form_inner,
                text=f"Lỗi đọc JSON: {e}",
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=_RED,
            ).pack(pady=20)
            return

        self.current_json_file = json_file
        self.current_json_data = data

        if self.ocr_type == "OCR BEDSIDE MONITOR":
            self.form_vars = build_monitor_form(self.form_inner, data)
        else:
            state = build_lab_form(
                self.form_inner,
                data,
                on_add_row=self._add_result_row,
                on_remove_row=self._remove_result_row,
            )
            self._form_state = state
            self.form_vars = state.form_vars
            self.result_vars = state.result_vars

            results = data.get("results", [])
            if results:
                for result in results:
                    add_result_row(state, result)
            elif (
                data.get("extraction_status") == "failed"
                or not results
            ):
                for _ in range(3):
                    add_result_row(state)
            self.result_vars = state.result_vars

    def _add_result_row(self, result: dict | None = None) -> None:
        if self._form_state is None:
            return
        add_result_row(self._form_state, result)
        self.result_vars = self._form_state.result_vars

    def _remove_result_row(self) -> None:
        if self._form_state is None:
            return
        remove_result_row(self._form_state)
        self.result_vars = self._form_state.result_vars

    # =====================================================================
    # SUBMIT / EXPORT
    # =====================================================================

    def _submit(self) -> None:
        if self._is_validate_mode():
            self._submit_lab_validation()
            return
        self._submit_non_validate()

    def _submit_non_validate(self) -> None:
        if not self.current_json_data or not self.current_folder_path:
            self.review_status.set("Vui lòng chọn folder trước", "error")
            return

        if self.ocr_type == "OCR BEDSIDE MONITOR":
            confirmed: dict = {}
            for key, orig in self.current_json_data.items():
                if key in self.form_vars:
                    raw = self.form_vars[key].get()
                    try:
                        new_val: float | int | str = float(raw)
                        if new_val == int(new_val):
                            new_val = int(new_val)
                    except (ValueError, OverflowError):
                        new_val = raw
                    if isinstance(orig, dict):
                        confirmed[key] = {**orig, "value": new_val}
                    elif isinstance(orig, list):
                        confirmed[key] = [
                            {**(orig[0] if orig else {}), "value": new_val}
                        ]
                    else:
                        confirmed[key] = new_val
                else:
                    confirmed[key] = orig
        else:
            confirmed = {}
            for key in self.form_vars:
                v = self.form_vars[key].get()
                confirmed[key] = v if v else None
            confirmed["results"] = []
            for rv in self.result_vars:
                row: dict = {}
                has_data = False
                for k, var in rv.items():
                    if k == "_frame":
                        continue
                    val = var.get()  # type: ignore[union-attr]
                    row[k] = val if val else None
                    if val:
                        has_data = True
                if has_data:
                    confirmed["results"].append(row)
            if "raw_text" in self.current_json_data:
                confirmed["raw_text"] = self.current_json_data["raw_text"]

        assert self.backend is not None and self.current_folder_path is not None
        assert self.current_json_file is not None

        base_name = lab_records.normalize_json_stem(self.current_json_file)
        confirmed_name = base_name + "_confirmed.json"
        final_name = base_name + "_final.json"

        try:
            write_json(
                self.backend, self.current_folder_path, confirmed_name, confirmed
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi lưu: {e}", "error")
            return

        out_path = self.backend.join(self.current_folder_path, confirmed_name)
        final_path = self.backend.join(self.current_folder_path, final_name)
        self.current_json_file = confirmed_name
        self.current_json_data = confirmed
        self.confirmed_files = [
            item for item in self.confirmed_files if item[0] != out_path
        ]
        self.confirmed_files.append((out_path, final_path))

        try:
            self.all_confirmed, self.confirmed_files = (
                self._collect_pending_confirmed_exports()
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc file xác nhận: {e}", "error")
            return

        cur_idx: int | None = None
        sel = self.folder_listbox.curselection()
        if sel and self.current_folder_name is not None:
            cur_idx = sel[0]
            self.folder_listbox.delete(cur_idx)
            self.folder_listbox.insert(cur_idx, "  ✓ " + self.current_folder_name)
            self.folder_listbox.itemconfig(cur_idx, fg=ACCENT_GREEN)
        confirmed_count = sum(
            1
            for i in range(self.folder_listbox.size())
            if self.folder_listbox.get(i).startswith("  ✓")
        )
        total = self.folder_listbox.size()
        self.review_status.set(
            f"Đã lưu: {confirmed_name}  —  {confirmed_count}/{total} folder hoàn thành",
            "success",
        )

        if cur_idx is not None and cur_idx + 1 < total:
            next_idx = cur_idx + 1
            while next_idx < total and self.folder_listbox.get(next_idx).startswith(
                "  ✓"
            ):
                next_idx += 1
            if next_idx < total:
                self.folder_listbox.selection_clear(0, "end")
                self.folder_listbox.selection_set(next_idx)
                self.folder_listbox.see(next_idx)
                self.folder_listbox.event_generate("<<ListboxSelect>>")

    def _export_excel(self) -> None:
        if self._is_validate_mode():
            self._export_lab_excel()
            return

        try:
            rows, confirmed_files = self._collect_pending_confirmed_exports()
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi đọc file xác nhận: {e}", "error")
            return

        if not confirmed_files:
            show_warning(
                self, "Không có dữ liệu", "Chưa có folder nào được xác nhận."
            )
            return

        output_path = filedialog.asksaveasfilename(
            title="Lưu file Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"OCR_{(self.ocr_type or '').replace(' ', '_')}.xlsx",
        )
        if not output_path:
            return

        assert self.backend is not None
        try:
            row_count = write_rows_to_xlsx(output_path, rows)
            for cp, fp in confirmed_files:
                try:
                    self.backend.rename(cp, fp)
                except Exception:
                    pass

            cnt = len(confirmed_files)
            self.confirmed_files.clear()
            self.all_confirmed.clear()
            self._load_folders()
            self.review_status.set(
                f"Đã xuất {row_count} dòng, {cnt} folder hoàn thành", "success"
            )
            show_info(
                self, "Thành công", f"Đã xuất {row_count} dòng dữ liệu"
            )
        except Exception as e:  # noqa: BLE001
            self.review_status.set(f"Lỗi xuất Excel: {e}", "error")


__all__ = ["OCRPage"]
