"""Trang Upload PDF Xét Nghiệm.

Chia trách nhiệm:
- `UploadPDFPage` (file này) - UI + state; lưu/upload chạy nền (thread) để
  không đơ giao diện.
- `apps.services.pdf_redact` - render + ghi PDF đã tô đen.
- `apps.services.upload_api` - POST HTTP lên backend (idempotent: bỏ qua file
  đã gửi khi retry).
- `apps.services.export_store` - lưu trữ bền vững cặp PDF+CSV qua thư mục
  pending/uploaded + meta.json, giúp biết cặp nào chưa upload sau khi mở lại app.
- `apps.widgets.date_picker.DatePicker` - popup lịch.

Người dùng tick ☑ chọn từng cặp muốn upload; upload xong cặp nào thì file cặp
đó được chuyển từ thư mục pending sang uploaded.
"""

from __future__ import annotations

import copy
import csv
import logging
import os
import queue
import threading
import tkinter as tk
import uuid
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from apps.config import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PURPLE,
    ACCENT_RED,
    API_BEARER_TOKEN,
    API_UPLOAD_OWNER,
    API_UPLOAD_URL,
    APP_DIR,
    BG_CARD,
    BG_INPUT,
    BG_MAIN,
    BORDER_COLOR,
    BTN_HOVER_BLUE,
    BTN_HOVER_ORANGE,
    BTN_HOVER_PURPLE,
    FG_DIM,
    FG_TEXT,
    FG_TITLE,
)
from apps.services import export_store
from apps.services.pdf_redact import save_redacted_pdf, temp_output_path
from apps.services.upload_api import upload_pair
from apps.widgets import (
    DatePicker,
    ScrollableFrame,
    StatusBar,
    StyledButton,
    make_header,
    show_error,
    show_info,
    show_warning,
)

log = logging.getLogger(__name__)

SAVE_RENDER_SCALE = 3.0
TYPE_OPTIONS = ("Hematology", "Biochemistry", "Microbiology", "Other")

# Naming rule: [DropdownType][Image/Metadata]_[PatientCode]_[dd.MM.yyyy.HH.mm.ss].<ext>

# Ký tự đầu ô mà Excel/Sheets hiểu là công thức → phải "thoát" khi ghi CSV.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Chống CSV formula injection: prefix ' cho ô bắt đầu bằng ký tự công thức."""

    if value and value[0] in _CSV_FORMULA_PREFIXES:
        return "'" + value
    return value


def _norm_path(path: str) -> str:
    """Chuẩn hoá path để so sánh trùng (Windows: bỏ phân biệt hoa/thường)."""

    return os.path.normcase(os.path.abspath(path))


def _sanitize_filename_token(s: str) -> str:
    """Loại ký tự không hợp lệ cho filename Windows."""

    cleaned = (
        s.replace("/", "-")
        .replace("\\", "-")
        .replace(":", "-")
        .replace("*", "")
        .replace("?", "")
        .replace('"', "")
        .replace("<", "")
        .replace(">", "")
        .replace("|", "")
        .strip()
    )
    return cleaned or "_"


class UploadPDFPage(tk.Frame):
    def __init__(self, parent: tk.Widget, controller) -> None:
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller

        # File list + current PDF
        self.pdf_files: list[str] = []
        self.current_file: str | None = None
        self.current_pdf = None
        self.page_count = 0
        self.current_page = 0

        # Canvas rendering state
        self._photo = None
        self._display_scale = 1.0
        self._img_offset_x = 0
        self._img_offset_y = 0
        self._img_width = 0
        self._img_height = 0

        # Drawing state
        self._drawing = False
        self._draw_start: tuple[int, int] | None = None
        self._draw_rect_id = None

        # Per-file snapshots
        self.redactions: dict[str, dict[int, list]] = {}
        self.form_data: dict[str, dict] = {}
        self.saved_files: set[str] = set()
        self.draft_redactions: dict[str, dict[int, list]] = {}
        self.draft_form_data: dict[str, dict] = {}

        # Export state
        self.saved_exports: list[dict] = []
        self.uploaded_exports: list[dict] = []
        self.view_mode = "pending"
        self.current_export_idx: int | None = None

        # Cặp (theo id) được TICK để upload. Rỗng = chưa chọn gì.
        self.upload_checked: set[str] = set()

        # Cờ bận: chặn thao tác khi đang lưu/upload chạy nền.
        self._busy = False

        # Hàng đợi để thread nền gửi callback về main thread (Tkinter không
        # thread-safe → chỉ đụng widget ở main thread qua poller này).
        self._ui_queue: queue.Queue = queue.Queue()

        make_header(self, controller, "Upload PDF Xét Nghiệm")

        pw = tk.PanedWindow(
            self,
            orient="horizontal",
            bg=BORDER_COLOR,
            sashwidth=4,
            sashrelief="flat",
        )
        pw.pack(fill="both", expand=True, padx=2, pady=2)

        left = self._build_left_panel(pw)
        pw.add(left, minsize=180, width=220)

        center = self._build_center_panel(pw)
        sw = controller.winfo_screenwidth()
        center_w = int((sw - 220) * 0.55)
        pw.add(center, minsize=300, width=center_w)

        right = self._build_right_panel(pw)
        pw.add(right, minsize=260)

        self.status = StatusBar(self)
        self.status.pack(fill="x", padx=5, pady=(0, 5))

        # Khôi phục thư mục làm việc gần nhất + nạp lại pending/uploaded từ ổ đĩa
        # để sau khi tắt/mở lại app vẫn biết cặp nào chưa upload.
        saved_dir = export_store.load_workspace(APP_DIR)
        if saved_dir:
            self.output_var.set(saved_dir)
        self._reload_from_disk(announce=True)

        # Bơm callback từ thread nền về main thread.
        self.after(80, self._poll_ui_queue)

    # ================================================================
    # LEFT PANEL - files + pending list
    # ================================================================

    def _build_left_panel(self, parent) -> tk.Frame:
        left = tk.Frame(parent, bg=BG_CARD)

        top = tk.Frame(left, bg=BG_CARD)
        top.pack(fill="both", expand=True)

        tk.Label(
            top,
            text="Danh sách PDF gốc",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(padx=10, pady=(10, 5), anchor="w")

        pick_btn = tk.Label(
            top,
            text="  + Chọn file PDF...  ",
            font=("Helvetica", 11, "bold"),
            bg=ACCENT_ORANGE,
            fg="#ffffff",
            cursor="hand2",
            padx=8,
            pady=5,
        )
        pick_btn.pack(padx=10, pady=(0, 5), fill="x")
        pick_btn.bind("<Button-1>", lambda e: self._pick_files())
        pick_btn.bind("<Enter>", lambda e: pick_btn.config(bg=BTN_HOVER_ORANGE))
        pick_btn.bind("<Leave>", lambda e: pick_btn.config(bg=ACCENT_ORANGE))

        self.file_count_lbl = tk.Label(
            top, text="Chưa chọn file", font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM
        )
        self.file_count_lbl.pack(padx=10, anchor="w")

        list_frame1 = tk.Frame(top, bg=BG_CARD)
        list_frame1.pack(fill="both", expand=True, padx=5, pady=5)

        sb1 = tk.Scrollbar(list_frame1)
        sb1.pack(side="right", fill="y")

        self.file_listbox = tk.Listbox(
            list_frame1,
            font=("Helvetica", 10),
            bg=BG_INPUT,
            fg=FG_TEXT,
            selectbackground=ACCENT_BLUE,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=sb1.set,
        )
        self.file_listbox.pack(fill="both", expand=True)
        sb1.config(command=self.file_listbox.yview)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_selected)

        tk.Frame(left, bg=BORDER_COLOR, height=2).pack(fill="x", padx=5, pady=5)

        bottom = tk.Frame(left, bg=BG_CARD)
        bottom.pack(fill="both", expand=True)

        tab_frame = tk.Frame(bottom, bg=BG_CARD)
        tab_frame.pack(fill="x", padx=10, pady=(5, 5))

        self.lbl_tab_pending = tk.Label(
            tab_frame,
            text="Pending",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="arrow",
        )
        self.lbl_tab_pending.pack(side="left")
        self.lbl_tab_pending.bind(
            "<Button-1>", lambda e: self.set_view_mode("pending")
        )

        tk.Label(
            tab_frame, text=" | ", font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM
        ).pack(side="left")

        self.lbl_tab_uploaded = tk.Label(
            tab_frame,
            text="Uploaded",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_DIM,
            cursor="hand2",
        )
        self.lbl_tab_uploaded.pack(side="left")
        self.lbl_tab_uploaded.bind(
            "<Button-1>", lambda e: self.set_view_mode("uploaded")
        )

        # Toggle chọn/bỏ chọn tất cả (chỉ hiện ở tab Pending).
        self.lbl_select_all = tk.Label(
            tab_frame,
            text="☑ Tất cả",
            font=("Helvetica", 10, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="hand2",
        )
        self.lbl_select_all.pack(side="right")
        self.lbl_select_all.bind("<Button-1>", lambda e: self._toggle_select_all())

        count_row = tk.Frame(bottom, bg=BG_CARD)
        count_row.pack(fill="x")
        self.pending_count_lbl = tk.Label(
            count_row, text="0 file", font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM
        )
        self.pending_count_lbl.pack(side="left", padx=10, anchor="w")
        self.checked_count_lbl = tk.Label(
            count_row, text="", font=("Helvetica", 10, "bold"),
            bg=BG_CARD, fg=ACCENT_PURPLE,
        )
        self.checked_count_lbl.pack(side="right", padx=10)

        list_frame2 = tk.Frame(bottom, bg=BG_CARD)
        list_frame2.pack(fill="both", expand=True, padx=5, pady=5)

        sb2 = tk.Scrollbar(list_frame2)
        sb2.pack(side="right", fill="y")

        self.pending_listbox = tk.Listbox(
            list_frame2,
            font=("Helvetica", 10),
            bg=BG_INPUT,
            fg=FG_TEXT,
            selectbackground=ACCENT_BLUE,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=sb2.set,
        )
        self.pending_listbox.pack(fill="both", expand=True)
        sb2.config(command=self.pending_listbox.yview)
        # Bắt click trước class-binding để phân biệt: click ô ☑ = tick chọn
        # upload, click phần tên = xem/sửa cặp.
        self.pending_listbox.bind("<Button-1>", self._on_pending_click)
        self.pending_listbox.bind("<<ListboxSelect>>", self._on_pending_selected)
        self.pending_listbox.bind("<Delete>", self._on_delete_key)
        self.pending_listbox.bind("<BackSpace>", self._on_delete_key)

        # Progress bar (ẩn khi rảnh, hiện khi lưu/upload chạy nền).
        self.progress = ttk.Progressbar(bottom, mode="determinate")

        self.upload_btn = StyledButton(
            bottom,
            text="▲  Upload đã chọn",
            command=self._upload,
            bg_color=ACCENT_PURPLE,
            hover_color=BTN_HOVER_PURPLE,
            font_size=12,
        )
        self.upload_btn.pack(padx=10, pady=10, fill="x")

        return left

    # ================================================================
    # CENTER PANEL - canvas + redaction
    # ================================================================

    def _build_center_panel(self, parent) -> tk.Frame:
        center = tk.Frame(parent, bg=BG_CARD)

        nav = tk.Frame(center, bg=BG_CARD)
        nav.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(
            nav,
            text="Xem & Tô đen PDF",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(side="left")

        undo_btn = tk.Label(
            nav,
            text="  ↩ Undo  ",
            font=("Helvetica", 10, "bold"),
            bg=ACCENT_RED,
            fg="#ffffff",
            cursor="hand2",
            padx=4,
            pady=2,
        )
        undo_btn.pack(side="right", padx=2)
        undo_btn.bind("<Button-1>", lambda e: self._undo_redaction())
        undo_btn.bind("<Enter>", lambda e: undo_btn.config(bg="#b91c1c"))
        undo_btn.bind("<Leave>", lambda e: undo_btn.config(bg=ACCENT_RED))

        clear_btn = tk.Label(
            nav,
            text="  ✕ Xóa hết  ",
            font=("Helvetica", 10, "bold"),
            bg="#6b7280",
            fg="#ffffff",
            cursor="hand2",
            padx=4,
            pady=2,
        )
        clear_btn.pack(side="right", padx=2)
        clear_btn.bind("<Button-1>", lambda e: self._clear_redactions())
        clear_btn.bind("<Enter>", lambda e: clear_btn.config(bg="#4b5563"))
        clear_btn.bind("<Leave>", lambda e: clear_btn.config(bg="#6b7280"))

        next_btn = tk.Label(
            nav,
            text="  ▶  ",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="hand2",
        )
        next_btn.pack(side="right", padx=2)
        next_btn.bind("<Button-1>", lambda e: self._change_page(1))

        self.page_label = tk.Label(
            nav, text="", font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM
        )
        self.page_label.pack(side="right", padx=4)

        prev_btn = tk.Label(
            nav,
            text="  ◀  ",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            cursor="hand2",
        )
        prev_btn.pack(side="right", padx=2)
        prev_btn.bind("<Button-1>", lambda e: self._change_page(-1))

        self.canvas = tk.Canvas(
            center, bg="#e0e0e0", highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)

        self.canvas.bind("<ButtonPress-1>", self._on_draw_start)
        self.canvas.bind("<B1-Motion>", self._on_draw_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_draw_end)

        self.canvas.create_text(
            200,
            150,
            text="Chọn file PDF để xem",
            font=("Helvetica", 13),
            fill=FG_DIM,
            tags="placeholder",
        )
        return center

    # ================================================================
    # RIGHT PANEL - form
    # ================================================================

    def _build_right_panel(self, parent) -> tk.Frame:
        right = tk.Frame(parent, bg=BG_CARD)

        tk.Label(
            right,
            text="Thông tin phiếu xét nghiệm",
            font=("Helvetica", 12, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(padx=10, pady=(10, 5), anchor="w")

        out_sec = tk.Frame(right, bg=BG_CARD)
        out_sec.pack(fill="x", padx=10, pady=(0, 8))

        tk.Label(
            out_sec,
            text="Thư mục lưu:",
            font=("Helvetica", 10, "bold"),
            bg=BG_CARD,
            fg=FG_DIM,
        ).pack(anchor="w")

        out_row = tk.Frame(
            out_sec,
            bg=BORDER_COLOR,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
        )
        out_row.pack(fill="x")

        self.output_var = tk.StringVar(value=str(APP_DIR / "output_pdf"))
        tk.Entry(
            out_row,
            textvariable=self.output_var,
            font=("Helvetica", 10),
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, ipady=5, padx=(6, 0))

        browse_btn = tk.Label(
            out_row,
            text=" … ",
            font=("Helvetica", 10, "bold"),
            bg=ACCENT_BLUE,
            fg="#ffffff",
            cursor="hand2",
            padx=8,
            pady=5,
        )
        browse_btn.pack(side="left")
        browse_btn.bind("<Button-1>", lambda e: self._pick_output_dir())
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(bg=BTN_HOVER_BLUE))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(bg=ACCENT_BLUE))

        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(
            fill="x", padx=10, pady=5
        )

        form_scroll = ScrollableFrame(right, bg=BG_CARD)
        form_scroll.pack(fill="both", expand=True, padx=10)
        form = form_scroll.interior

        self.form_vars: dict[str, tk.StringVar] = {}
        self.input_widgets: list = []
        self.date_labels: dict[str, tk.Label] = {}
        self._date_refreshers: list = []

        def _input_border(parent_frame):
            return tk.Frame(
                parent_frame,
                bg=BORDER_COLOR,
                highlightbackground=BORDER_COLOR,
                highlightthickness=1,
            )

        def _entry_row(key: str, label_text: str) -> tk.Frame:
            row = tk.Frame(form, bg=BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(
                row,
                text=label_text,
                font=("Helvetica", 11, "bold"),
                bg=BG_CARD,
                fg=FG_TEXT,
                width=20,
                anchor="e",
            ).pack(side="left", padx=(0, 6))
            var = tk.StringVar(value="")
            self.form_vars[key] = var
            wrapper = _input_border(row)
            wrapper.pack(side="left", fill="x", expand=True)
            entry = tk.Entry(
                wrapper,
                textvariable=var,
                font=("Helvetica", 11),
                bg=BG_INPUT,
                fg=FG_TEXT,
                insertbackground=FG_TEXT,
                borderwidth=0,
                highlightthickness=0,
                relief="flat",
            )
            self.input_widgets.append(entry)
            entry.pack(fill="x", ipady=5, padx=4, pady=2)
            return row

        def _date_row(key: str, label_text: str, default_value: str = "") -> tk.Frame:
            row = tk.Frame(form, bg=BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(
                row,
                text=label_text,
                font=("Helvetica", 11, "bold"),
                bg=BG_CARD,
                fg=FG_TEXT,
                width=20,
                anchor="e",
            ).pack(side="left", padx=(0, 6))

            var = tk.StringVar(value=default_value)
            self.form_vars[key] = var

            wrapper = _input_border(row)
            wrapper.pack(side="left", fill="x", expand=True)

            # "Ô" read-only: KHÔNG cho gõ freetext, chỉ chọn qua lịch. Gồm nhãn
            # giá trị (hoặc placeholder) + nút xóa + icon lịch.
            field = tk.Frame(wrapper, bg=BG_INPUT)
            field.pack(fill="x")

            cal_icon = tk.Label(
                field, text="📅", font=("Helvetica", 11),
                bg=BG_INPUT, cursor="hand2", padx=6,
            )
            cal_icon.pack(side="right")

            clear_btn = tk.Label(
                field, text="✕", font=("Helvetica", 10, "bold"),
                bg=BG_INPUT, fg=FG_DIM, cursor="hand2", padx=4,
            )

            val_lbl = tk.Label(
                field, anchor="w", font=("Helvetica", 11),
                bg=BG_INPUT, fg=FG_TEXT, cursor="hand2",
            )
            val_lbl.pack(side="left", fill="x", expand=True, padx=(8, 2), pady=5)
            self.date_labels[key] = val_lbl

            def refresh(*_):
                readonly = self.view_mode == "uploaded"
                v = var.get().strip()
                cur = "arrow" if readonly else "hand2"
                val_lbl.config(cursor=cur)
                cal_icon.config(cursor=cur)
                if v:
                    val_lbl.config(text=v, fg=FG_TEXT)
                    if readonly:
                        clear_btn.pack_forget()
                    else:
                        clear_btn.pack(side="right")
                else:
                    val_lbl.config(text="— chọn ngày —", fg=FG_DIM)
                    clear_btn.pack_forget()

            var.trace_add("write", refresh)
            self._date_refreshers.append(refresh)

            def open_picker(event=None):
                if self.view_mode == "uploaded" or self._busy:
                    return
                DatePicker(self, var.get(), lambda d: var.set(d), anchor=wrapper)

            val_lbl.bind("<Button-1>", open_picker)
            cal_icon.bind("<Button-1>", open_picker)
            cal_icon.bind("<Enter>", lambda e: cal_icon.config(bg="#e5e7eb"))
            cal_icon.bind("<Leave>", lambda e: cal_icon.config(bg=BG_INPUT))
            clear_btn.bind("<Button-1>", lambda e: (var.set(""), "break")[1])
            clear_btn.bind("<Enter>", lambda e: clear_btn.config(fg=ACCENT_RED))
            clear_btn.bind("<Leave>", lambda e: clear_btn.config(fg=FG_DIM))

            refresh()
            return row

        # Date display (read-only)
        row_date = tk.Frame(form, bg=BG_CARD)
        row_date.pack(fill="x", pady=4)
        tk.Label(
            row_date,
            text="Date:",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=20,
            anchor="e",
        ).pack(side="left", padx=(0, 6))

        current_date_str = datetime.now().strftime("%d-%m-%Y")
        self.form_vars["date"] = tk.StringVar(value=current_date_str)

        date_display = tk.Frame(
            row_date,
            bg=BG_INPUT,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
        )
        date_display.pack(side="left", fill="x", expand=True)
        tk.Label(
            date_display,
            textvariable=self.form_vars["date"],
            font=("Helvetica", 11, "bold"),
            bg=BG_INPUT,
            fg=ACCENT_BLUE,
            anchor="w",
        ).pack(fill="x", padx=8, pady=5)

        _entry_row("patient_code", "Patient Code:")

        # Type
        self.row_type = tk.Frame(form, bg=BG_CARD)
        self.row_type.pack(fill="x", pady=4)
        tk.Label(
            self.row_type,
            text="Type:",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=20,
            anchor="e",
        ).pack(side="left", padx=(0, 6))
        self.form_vars["type"] = tk.StringVar(value="")

        type_wrapper = _input_border(self.row_type)
        type_wrapper.pack(side="left", fill="x", expand=True)
        type_box = ttk.Combobox(
            type_wrapper,
            textvariable=self.form_vars["type"],
            state="readonly",
            font=("Helvetica", 11),
        )
        self.input_widgets.append(type_box)
        type_box["values"] = TYPE_OPTIONS
        type_box.pack(fill="x", ipady=4, padx=2, pady=1)

        # Other Type
        self.row_other = tk.Frame(form, bg=BG_CARD)
        tk.Label(
            self.row_other,
            text="Specify Other:",
            font=("Helvetica", 11, "bold"),
            bg=BG_CARD,
            fg=FG_TEXT,
            width=20,
            anchor="e",
        ).pack(side="left", padx=(0, 6))
        self.form_vars["other_type"] = tk.StringVar(value="")
        other_wrapper = _input_border(self.row_other)
        other_wrapper.pack(side="left", fill="x", expand=True)
        other_entry = tk.Entry(
            other_wrapper,
            textvariable=self.form_vars["other_type"],
            font=("Helvetica", 11),
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        )
        self.input_widgets.append(other_entry)
        other_entry.pack(fill="x", ipady=5, padx=4, pady=2)

        def on_type_selected(event=None):
            if self.form_vars["type"].get() == "Other":
                self.row_other.pack(fill="x", pady=4, after=self.row_type)
            else:
                self.row_other.pack_forget()

        type_box.bind("<<ComboboxSelected>>", on_type_selected)
        self.update_type_visibility = on_type_selected

        _date_row("sampling_date", "Sampling Date:")
        _date_row("receipt_date", "Date of sample receipt:")
        _date_row("result_date", "Date of results:")

        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(
            fill="x", padx=10, pady=10
        )

        self.save_btn = StyledButton(
            right,
            text="💾  Lưu (PDF + CSV)",
            command=self._save,
            bg_color=ACCENT_BLUE,
            hover_color=BTN_HOVER_BLUE,
            font_size=12,
        )
        self.save_btn.pack(padx=10, pady=(0, 10), fill="x")

        return right

    # ================================================================
    # FILE MANAGEMENT
    # ================================================================

    def _pick_files(self) -> None:
        if self._busy:
            return
        files = filedialog.askopenfilenames(
            title="Chọn file PDF xét nghiệm",
            filetypes=[("PDF files", "*.pdf"), ("Tất cả", "*.*")],
        )
        if not files:
            return
        existing = {_norm_path(f) for f in self.pdf_files}
        added = 0
        for f in files:
            key = _norm_path(f)
            if key not in existing:
                existing.add(key)
                self.pdf_files.append(f)
                added += 1
        self._refresh_file_list()
        if added < len(files):
            self.status.set(
                f"Đã thêm {added} file (bỏ qua {len(files) - added} file trùng)",
                "info",
            )

    def _refresh_file_list(self) -> None:
        self.file_listbox.delete(0, "end")
        for f in self.pdf_files:
            name = os.path.basename(f)
            prefix = "  ✓  " if f in self.saved_files else "  "
            self.file_listbox.insert("end", prefix + name)
            if f in self.saved_files:
                self.file_listbox.itemconfig(
                    self.file_listbox.size() - 1, fg=ACCENT_GREEN
                )
        self.file_count_lbl.config(
            text=f"✓ {len(self.pdf_files)} file" if self.pdf_files else "Chưa chọn file",
            fg=ACCENT_GREEN if self.pdf_files else FG_DIM,
        )

    def _on_file_selected(self, event) -> None:
        if self._busy:
            return
        sel = self.file_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        filepath = self.pdf_files[idx]

        self._save_current_form_data()
        self.current_export_idx = None

        if filepath != self.current_file:
            self._load_pdf(filepath)
        else:
            self._apply_state()
            self._restore_form_data(filepath)
            self._render_current_page()
            self._update_form_state()

        self.pending_listbox.selection_clear(0, "end")

    def set_view_mode(self, mode: str, preserve_idx: bool = False) -> None:
        if self._busy:
            return
        self.view_mode = mode
        if mode == "pending":
            self.lbl_tab_pending.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_uploaded.config(fg=FG_DIM, cursor="hand2")
            self.upload_btn.pack(padx=10, pady=10, fill="x")
            self.lbl_select_all.pack(side="right")
        else:
            self.lbl_tab_uploaded.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_pending.config(fg=FG_DIM, cursor="hand2")
            self.upload_btn.pack_forget()
            self.lbl_select_all.pack_forget()

        if not preserve_idx:
            self.current_export_idx = None

        self._refresh_pending_list()
        self._update_form_state()

    def _update_form_state(self) -> None:
        is_readonly = self.view_mode == "uploaded"
        for w in self.input_widgets:
            if isinstance(w, ttk.Combobox):
                w.config(state="disabled" if is_readonly else "readonly")
            elif isinstance(w, tk.Entry):
                w.config(state="disabled" if is_readonly else "normal")

        # Cập nhật các ô ngày (ẩn nút xóa + đổi cursor theo chế độ xem).
        for refresh in self._date_refreshers:
            refresh()

        if is_readonly:
            if self.save_btn.winfo_ismapped():
                self.save_btn.pack_forget()
        else:
            if not self.save_btn.winfo_ismapped():
                self.save_btn.pack(padx=10, pady=(0, 10), fill="x")

    def _on_delete_key(self, event) -> None:
        if self._busy:
            return
        sel = self.pending_listbox.curselection()
        if not sel:
            return
        idx = sel[0]

        self.focus_set()
        mode_text = "Pending" if self.view_mode == "pending" else "Uploaded"
        if not messagebox.askyesno(
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa bản lưu này khỏi mục {mode_text}?\n"
            "(Sẽ xóa luôn file gốc được xuất ra trên ổ cứng)",
        ):
            return

        data_list = (
            self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        )
        exp = data_list[idx]
        original_file = exp.get("original_file")

        try:
            export_store.delete_pair(exp)
        except OSError as e:
            self.status.set(f"Không thể xóa file export: {e}", "error")
            return

        self.upload_checked.discard(exp.get("id"))
        data_list.pop(idx)
        if original_file and self.view_mode == "pending":
            still_has_pending = any(
                item.get("original_file") == original_file
                for item in self.saved_exports
            )
            if not still_has_pending:
                self.saved_files.discard(original_file)

        if self.current_export_idx == idx:
            self.current_export_idx = None
        elif self.current_export_idx is not None and self.current_export_idx > idx:
            self.current_export_idx -= 1

        self._refresh_file_list()
        self._refresh_pending_list()

    def _on_pending_selected(self, event) -> None:
        if self._busy:
            return
        sel = self.pending_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        data_list = (
            self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        )

        if idx < len(data_list):
            self._save_current_form_data()
            self.current_export_idx = idx

            exp = data_list[idx]
            # Sau khi mở lại app, file gốc có thể không còn → xem bản PDF đã xuất.
            view_path = self._export_view_path(exp)

            if view_path and view_path != self.current_file:
                self._load_pdf(view_path)
            elif view_path:
                self._apply_state()
                self._restore_form_data(view_path)
                self._render_current_page()

        self.file_listbox.selection_clear(0, "end")

    def _export_view_path(self, exp: dict) -> str | None:
        """File để hiển thị cho một export: ưu tiên file gốc, fallback PDF đã xuất."""

        original = exp.get("original_file")
        if original and os.path.exists(original):
            return original
        pdf_path = exp.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            return pdf_path
        return original or pdf_path

    def _refresh_pending_list(self) -> None:
        self.pending_listbox.delete(0, "end")
        data_list = (
            self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        )
        is_pending = self.view_mode == "pending"

        # Dọn các id đã tick nhưng không còn trong pending nữa.
        if is_pending:
            valid_ids = {exp["id"] for exp in self.saved_exports}
            self.upload_checked &= valid_ids

        suffix = "[Chờ Upload]" if is_pending else "[Đã Upload]"
        for exp in data_list:
            if is_pending:
                box = "☑" if exp["id"] in self.upload_checked else "☐"
                self.pending_listbox.insert(
                    "end", f" {box}  🏷 {exp['display_name']} {suffix}"
                )
            else:
                self.pending_listbox.insert(
                    "end", f"  🏷 {exp['display_name']} {suffix}"
                )

        # Giữ lại highlight cho cặp đang xem.
        if (
            self.current_export_idx is not None
            and 0 <= self.current_export_idx < len(data_list)
        ):
            self.pending_listbox.selection_clear(0, "end")
            self.pending_listbox.selection_set(self.current_export_idx)

        count = len(data_list)
        self.pending_count_lbl.config(
            text=f"{count} file (cặp)", fg=ACCENT_GREEN if count else FG_DIM
        )
        if is_pending:
            n_checked = len(self.upload_checked)
            self.checked_count_lbl.config(
                text=f"đã chọn: {n_checked}" if n_checked else ""
            )
        else:
            self.checked_count_lbl.config(text="")

    def _toggle_select_all(self) -> None:
        """Chọn tất cả nếu chưa full, ngược lại bỏ chọn hết (chỉ ở tab Pending)."""

        if self._busy or self.view_mode != "pending":
            return
        all_ids = {exp["id"] for exp in self.saved_exports}
        if self.upload_checked >= all_ids and all_ids:
            self.upload_checked.clear()
        else:
            self.upload_checked = all_ids
        self._refresh_pending_list()

    def _on_pending_click(self, event):
        """Click ô ☑ (mép trái) = tick chọn upload; click chỗ khác = xem/sửa."""

        if self._busy or self.view_mode != "pending":
            return None
        idx = self.pending_listbox.nearest(event.y)
        if idx < 0 or idx >= len(self.saved_exports):
            return None
        bbox = self.pending_listbox.bbox(idx)
        if not bbox:
            return None
        # Chỉ coi là tick khi click nằm trong vùng checkbox (~28px mép trái).
        if event.x <= 32:
            exp_id = self.saved_exports[idx]["id"]
            if exp_id in self.upload_checked:
                self.upload_checked.discard(exp_id)
            else:
                self.upload_checked.add(exp_id)
            self._refresh_pending_list()
            return "break"  # chặn class-binding đổi selection
        return None

    def _save_current_form_data(self) -> None:
        if not self.current_file:
            return
        form_copy = {k: v.get() for k, v in self.form_vars.items()}
        redacts_copy = copy.deepcopy(self.redactions.get(self.current_file, {}))

        if self.current_export_idx is not None:
            data_list = (
                self.saved_exports
                if self.view_mode == "pending"
                else self.uploaded_exports
            )
            if self.current_export_idx < len(data_list):
                data_list[self.current_export_idx]["form_data"] = form_copy
                data_list[self.current_export_idx]["redactions"] = redacts_copy
        else:
            self.draft_form_data[self.current_file] = form_copy
            self.draft_redactions[self.current_file] = redacts_copy

    def _apply_state(self) -> None:
        if self.current_export_idx is not None:
            data_list = (
                self.saved_exports
                if self.view_mode == "pending"
                else self.uploaded_exports
            )
            if self.current_export_idx < len(data_list):
                exp = data_list[self.current_export_idx]
                self.form_data[self.current_file] = copy.deepcopy(
                    exp.get("form_data", {})
                )
                self.redactions[self.current_file] = copy.deepcopy(
                    exp.get("redactions", {})
                )
        else:
            self.form_data[self.current_file] = copy.deepcopy(
                self.draft_form_data.get(self.current_file, {})
            )
            self.redactions[self.current_file] = copy.deepcopy(
                self.draft_redactions.get(self.current_file, {})
            )

    def _restore_form_data(self, filepath: str) -> None:
        data = self.form_data.get(filepath, {})
        for key, var in self.form_vars.items():
            if key == "date":
                var.set(datetime.now().strftime("%d-%m-%Y"))
            else:
                var.set(data.get(key, ""))
        if hasattr(self, "update_type_visibility"):
            self.update_type_visibility()

    # ================================================================
    # PDF LOADING & RENDERING
    # ================================================================

    def _load_pdf(self, filepath: str) -> None:
        try:
            import pypdfium2 as pdfium
        except ImportError:
            self.status.set("Cần cài pypdfium2: pip install pypdfium2", "error")
            return

        if not os.path.exists(filepath):
            self.status.set(
                f"Không tìm thấy file: {os.path.basename(filepath)}", "error"
            )
            return

        if self.current_pdf and self.current_file != filepath:
            try:
                self.current_pdf.close()
            except Exception:
                pass
            self.current_pdf = None

        if not self.current_pdf:
            try:
                doc = pdfium.PdfDocument(filepath)
                page_count = len(doc)
            except Exception as e:  # noqa: BLE001 - pypdfium2 ném lỗi chung
                log.warning("Không mở được PDF %s: %s", filepath, e)
                self.status.set(
                    f"Không mở được PDF (hỏng hoặc có mật khẩu): "
                    f"{os.path.basename(filepath)}",
                    "error",
                )
                return
            self.current_file = filepath
            self.current_pdf = doc
            self.page_count = page_count
            self.current_page = 0

        self._apply_state()
        self._restore_form_data(filepath)
        self._render_current_page()
        self.status.set(
            f"Đang xem: {os.path.basename(filepath)} ({self.page_count} trang)",
            "info",
        )

    def _render_current_page(self) -> None:
        if not self.current_pdf:
            return

        from PIL import ImageDraw, ImageTk

        self.canvas.delete("all")
        self.canvas.update_idletasks()

        page = self.current_pdf[self.current_page]
        pw_pts, ph_pts = page.get_size()

        canvas_w = max(self.canvas.winfo_width() - 20, 400)
        canvas_h = max(self.canvas.winfo_height() - 20, 400)
        self._display_scale = min(canvas_w / pw_pts, canvas_h / ph_pts)

        bitmap = page.render(scale=self._display_scale)
        img = bitmap.to_pil()

        page_rects = self.redactions.get(self.current_file, {}).get(
            self.current_page, []
        )
        if page_rects:
            draw = ImageDraw.Draw(img)
            for (px1, py1, px2, py2) in page_rects:
                draw.rectangle(
                    [
                        int(px1 * self._display_scale),
                        int(py1 * self._display_scale),
                        int(px2 * self._display_scale),
                        int(py2 * self._display_scale),
                    ],
                    fill="black",
                )

        self._photo = ImageTk.PhotoImage(img)

        cx = canvas_w // 2
        cy = canvas_h // 2
        self._img_offset_x = cx - img.width // 2
        self._img_offset_y = cy - img.height // 2
        self._img_width = img.width
        self._img_height = img.height

        self.canvas.create_image(
            self._img_offset_x,
            self._img_offset_y,
            image=self._photo,
            anchor="nw",
            tags="pdf_image",
        )
        self.page_label.config(text=f"Trang {self.current_page + 1}/{self.page_count}")

    def _change_page(self, delta: int) -> None:
        if self._busy or not self.current_pdf:
            return
        new_page = self.current_page + delta
        if 0 <= new_page < self.page_count:
            self.current_page = new_page
            self._render_current_page()

    # ================================================================
    # DRAWING (REDACTION)
    # ================================================================

    def _canvas_to_pdf_pts(self, cx: float, cy: float) -> tuple[float, float]:
        return (
            (cx - self._img_offset_x) / self._display_scale,
            (cy - self._img_offset_y) / self._display_scale,
        )

    def _is_uploaded_view(self) -> bool:
        return self.view_mode == "uploaded" and self.current_export_idx is not None

    def _on_draw_start(self, event) -> None:
        if self._busy or self._is_uploaded_view() or not self.current_pdf:
            return
        ix = event.x - self._img_offset_x
        iy = event.y - self._img_offset_y
        if not (0 <= ix <= self._img_width and 0 <= iy <= self._img_height):
            return
        self._drawing = True
        self._draw_start = (event.x, event.y)

    def _on_draw_motion(self, event) -> None:
        if not self._drawing:
            return
        if self._draw_rect_id:
            self.canvas.delete(self._draw_rect_id)
        x0, y0 = self._draw_start  # type: ignore[misc]
        self._draw_rect_id = self.canvas.create_rectangle(
            x0,
            y0,
            event.x,
            event.y,
            outline="red",
            width=2,
            dash=(4, 2),
            tags="draw_preview",
        )

    def _on_draw_end(self, event) -> None:
        if not self._drawing:
            return
        self._drawing = False
        if self._draw_rect_id:
            self.canvas.delete(self._draw_rect_id)
            self._draw_rect_id = None

        x0, y0 = self._draw_start  # type: ignore[misc]
        x1, y1 = event.x, event.y
        cx1, cy1 = min(x0, x1), min(y0, y1)
        cx2, cy2 = max(x0, x1), max(y0, y1)

        if abs(cx2 - cx1) < 5 or abs(cy2 - cy1) < 5:
            return

        px1, py1 = self._canvas_to_pdf_pts(cx1, cy1)
        px2, py2 = self._canvas_to_pdf_pts(cx2, cy2)

        page = self.current_pdf[self.current_page]
        pw_pts, ph_pts = page.get_size()
        px1 = max(0, min(px1, pw_pts))
        py1 = max(0, min(py1, ph_pts))
        px2 = max(0, min(px2, pw_pts))
        py2 = max(0, min(py2, ph_pts))

        page_rects = (
            self.redactions.setdefault(self.current_file, {}).setdefault(
                self.current_page, []
            )
        )
        page_rects.append((px1, py1, px2, py2))

        self._render_current_page()

    def _undo_redaction(self) -> None:
        if self._is_uploaded_view() or not self.current_file:
            return
        page_rects = self.redactions.get(self.current_file, {}).get(
            self.current_page, []
        )
        if page_rects:
            page_rects.pop()
            self._render_current_page()
            self.status.set("Đã undo vùng tô đen cuối cùng", "info")

    def _clear_redactions(self) -> None:
        if self._is_uploaded_view() or not self.current_file:
            return
        file_redacts = self.redactions.get(self.current_file, {})
        if self.current_page in file_redacts:
            file_redacts[self.current_page] = []
            self._render_current_page()
            self.status.set("Đã xóa hết vùng tô đen trang hiện tại", "info")

    # ================================================================
    # SAVE
    # ================================================================

    def _pick_output_dir(self) -> None:
        if self._busy:
            return
        path = filedialog.askdirectory(title="Chọn thư mục lưu")
        if not path:
            return
        if _norm_path(path) == _norm_path(self.output_var.get().strip() or "."):
            self.output_var.set(path)
            return
        if (self.saved_exports or self.uploaded_exports) and not messagebox.askyesno(
            "Đổi thư mục làm việc",
            "Đổi thư mục sẽ nạp lại danh sách Pending/Uploaded theo thư mục mới.\n"
            "Các cặp trong thư mục cũ vẫn còn trên ổ đĩa. Tiếp tục?",
        ):
            return
        self.output_var.set(path)
        export_store.save_workspace(APP_DIR, path)
        self._reload_from_disk(announce=True)

    def _delete_files(self, *paths: str | None) -> None:
        for path in paths:
            if not path:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                continue

    def _unique_export_names(
        self, folder: str, safe_type: str, safe_patient: str, current_time: str
    ) -> tuple[str, str, str]:
        """Sinh (pdf_name, csv_name, display_name) không trùng file trong `folder`."""

        n = 1
        suffix = ""
        while True:
            display_name = f"{safe_type}Image_{safe_patient}_{current_time}_{suffix}"
            pdf_name = f"{display_name}.pdf"
            csv_name = f"{safe_type}Metadata_{safe_patient}_{current_time}_{suffix}.csv"
            meta_name = f"{display_name}.meta.json"
            if not any(
                os.path.exists(os.path.join(folder, x))
                for x in (pdf_name, csv_name, meta_name)
            ):
                return pdf_name, csv_name, display_name
            suffix = str(n)
            n += 1

    def _save(self) -> None:
        if self._busy:
            return
        if not self.current_file:
            show_warning(self, "Chưa chọn file", "Vui lòng chọn file PDF trước.")
            return

        patient_code = self.form_vars["patient_code"].get().strip()
        if not patient_code:
            show_warning(self, "Thiếu thông tin", "Vui lòng nhập Patient Code.")
            return

        type_val = self.form_vars["type"].get().strip()
        if type_val == "Other":
            type_val = self.form_vars["other_type"].get().strip()
        if not type_val:
            show_warning(
                self, "Thiếu thông tin", "Vui lòng chọn hoặc nhập Type."
            )
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            show_warning(
                self, "Thiếu đường dẫn", "Vui lòng chọn thư mục lưu."
            )
            return

        try:
            export_store.ensure_dirs(output_dir)
        except OSError as e:
            show_error(self, "Lỗi thư mục", f"Không tạo được thư mục lưu:\n{e}")
            return
        export_store.save_workspace(APP_DIR, output_dir)
        pending = export_store.pending_dir(output_dir)

        form = {k: v.get().strip() for k, v in self.form_vars.items()}
        current_time = datetime.now().strftime("%d.%m.%Y.%H.%M.%S")
        safe_type = _sanitize_filename_token(type_val)
        safe_patient = _sanitize_filename_token(patient_code)

        is_edit = self.current_export_idx is not None
        pdf_name, csv_name, display_name = self._unique_export_names(
            pending, safe_type, safe_patient, current_time
        )
        pdf_path = os.path.join(pending, pdf_name)
        csv_path = os.path.join(pending, csv_name)

        old_pdf = old_csv = old_meta = None
        export_id = uuid.uuid4().hex
        if is_edit and self.current_export_idx < len(self.saved_exports):
            exp = self.saved_exports[self.current_export_idx]
            old_pdf = exp.get("pdf_path")
            old_csv = exp.get("csv_path")
            old_meta = exp.get("meta_path")
            export_id = exp.get("id", export_id)

        snapshot_form = copy.deepcopy(form)
        snapshot_redacts = copy.deepcopy(self.redactions.get(self.current_file, {}))
        src_file = self.current_file

        pdf_tmp = temp_output_path(pdf_path)
        csv_tmp = temp_output_path(csv_path)

        def work():
            # Chạy nền: rasterize PDF là phần nặng, không được chặn UI.
            self._delete_files(pdf_tmp, csv_tmp)
            save_redacted_pdf(
                src_file, snapshot_redacts, pdf_tmp, scale=SAVE_RENDER_SCALE
            )
            self._write_csv(csv_tmp, form)
            os.replace(pdf_tmp, pdf_path)
            os.replace(csv_tmp, csv_path)
            return None

        def done(_res, err):
            if err is not None:
                try:
                    self._delete_files(pdf_tmp, csv_tmp)
                except OSError:
                    pass
                log.error("Save failed: %s", err, exc_info=err)
                self._set_busy(False)
                self.status.set(f"Lỗi lưu: {err}", "error")
                return
            self._finalize_save(
                is_edit=is_edit,
                export_id=export_id,
                src_file=src_file,
                pdf_path=pdf_path,
                csv_path=csv_path,
                pdf_name=pdf_name,
                csv_name=csv_name,
                display_name=display_name,
                snapshot_form=snapshot_form,
                snapshot_redacts=snapshot_redacts,
                pending=pending,
                old_paths=(old_pdf, old_csv, old_meta),
            )

        self._set_busy(True, f"Đang lưu {display_name}...")
        self._progress_show(indeterminate=True)
        self._run_async(work, done)

    def _finalize_save(
        self,
        *,
        is_edit: bool,
        export_id: str,
        src_file: str,
        pdf_path: str,
        csv_path: str,
        pdf_name: str,
        csv_name: str,
        display_name: str,
        snapshot_form: dict,
        snapshot_redacts: dict,
        pending: str,
        old_paths: tuple,
    ) -> None:
        """Cập nhật state + UI sau khi ghi file xong (chạy trên main thread)."""

        self._set_busy(False)  # bỏ busy trước để set_view_mode hoạt động
        old_pdf, old_csv, old_meta = old_paths

        if (
            is_edit
            and self.current_export_idx is not None
            and self.current_export_idx < len(self.saved_exports)
        ):
            exp = self.saved_exports[self.current_export_idx]
            exp.update(
                {
                    "pdf_path": pdf_path,
                    "csv_path": csv_path,
                    "display_name": display_name,
                    "form_data": snapshot_form,
                    "redactions": snapshot_redacts,
                    # Nội dung đã đổi → coi như chưa gửi, cần upload lại.
                    "pdf_sent": False,
                    "csv_sent": False,
                }
            )
            select_idx = self.current_export_idx
        else:
            exp = {
                "id": export_id,
                "original_file": src_file,
                "pdf_path": pdf_path,
                "csv_path": csv_path,
                "display_name": display_name,
                "form_data": snapshot_form,
                "redactions": snapshot_redacts,
                "pdf_sent": False,
                "csv_sent": False,
            }
            self.saved_exports.append(exp)
            self.upload_checked.add(export_id)  # cặp mới mặc định được tick
            select_idx = len(self.saved_exports) - 1

            self.draft_form_data[src_file] = {}
            self.draft_redactions[src_file] = {}
            self.redactions[src_file] = {}

            self.current_export_idx = None
            self.set_view_mode("pending", preserve_idx=False)

            current_date = self.form_vars["date"].get()
            for key, var in self.form_vars.items():
                if key != "date":
                    var.set("")
            self.form_vars["date"].set(current_date)
            self._render_current_page()

        try:
            export_store.write_meta(pending, exp)
        except OSError as e:
            log.warning("Không ghi được meta: %s", e)

        self.saved_files.add(src_file)
        self._refresh_file_list()
        self._refresh_pending_list()

        self.pending_listbox.selection_clear(0, "end")
        if 0 <= select_idx < self.pending_listbox.size():
            self.pending_listbox.selection_set(select_idx)

        # Dọn file cũ (khi sửa mà đổi tên theo timestamp mới).
        keep = {_norm_path(pdf_path), _norm_path(csv_path)}
        new_meta = exp.get("meta_path")
        if new_meta:
            keep.add(_norm_path(new_meta))
        stale = [
            p for p in (old_pdf, old_csv, old_meta)
            if p and _norm_path(p) not in keep
        ]
        try:
            self._delete_files(*stale)
        except OSError:
            pass

        self.status.set(f"Đã lưu: {pdf_name} và {csv_name}", "success")

    def _write_csv(self, output_path: str, form: dict) -> None:
        fieldnames = list(form.keys())
        # Sanitize chống CSV formula injection khi mở bằng Excel/Sheets.
        safe_row = {k: _csv_safe(str(v)) for k, v in form.items()}
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(safe_row)

    # ================================================================
    # UPLOAD
    # ================================================================

    def _ask_owner_email(self) -> str | None:
        """Hiện popup nhỏ hỏi email owner. Trả None nếu user hủy."""

        dialog = tk.Toplevel(self)
        dialog.title("Nhập Owner Email")
        dialog.resizable(False, False)
        dialog.configure(bg=BG_CARD)
        dialog.grab_set()

        # Căn giữa cửa sổ
        dialog.update_idletasks()
        w, h = 380, 170
        x = self.winfo_toplevel().winfo_x() + (self.winfo_toplevel().winfo_width() - w) // 2
        y = self.winfo_toplevel().winfo_y() + (self.winfo_toplevel().winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(
            dialog,
            text="📧  Nhập email (owner):",
            font=("Helvetica", 12, "bold"),
            bg=BG_CARD,
            fg=FG_TITLE,
        ).pack(padx=20, pady=(15, 5), anchor="w")

        email_var = tk.StringVar(value=API_UPLOAD_OWNER)
        entry = tk.Entry(
            dialog,
            textvariable=email_var,
            font=("Helvetica", 12),
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            borderwidth=1,
            highlightthickness=1,
            highlightcolor=ACCENT_BLUE,
        )
        entry.pack(fill="x", padx=20, pady=5, ipady=6)
        entry.focus_set()
        entry.select_range(0, "end")

        result: list[str | None] = [None]

        def on_ok(event=None):
            val = email_var.get().strip()
            if not val or "@" not in val:
                entry.config(highlightcolor=ACCENT_RED, highlightbackground=ACCENT_RED)
                return
            result[0] = val
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        entry.bind("<Return>", on_ok)
        dialog.bind("<Escape>", lambda e: on_cancel())

        btn_frame = tk.Frame(dialog, bg=BG_CARD)
        btn_frame.pack(pady=(10, 15))

        ok_btn = tk.Label(
            btn_frame,
            text="  ✓  OK  ",
            font=("Helvetica", 11, "bold"),
            bg=ACCENT_BLUE,
            fg="#ffffff",
            cursor="hand2",
            padx=12,
            pady=5,
        )
        ok_btn.pack(side="left", padx=8)
        ok_btn.bind("<Button-1>", on_ok)
        ok_btn.bind("<Enter>", lambda e: ok_btn.config(bg=BTN_HOVER_BLUE))
        ok_btn.bind("<Leave>", lambda e: ok_btn.config(bg=ACCENT_BLUE))

        cancel_btn = tk.Label(
            btn_frame,
            text="  Hủy  ",
            font=("Helvetica", 11),
            bg="#6b7280",
            fg="#ffffff",
            cursor="hand2",
            padx=12,
            pady=5,
        )
        cancel_btn.pack(side="left", padx=8)
        cancel_btn.bind("<Button-1>", lambda e: on_cancel())
        cancel_btn.bind("<Enter>", lambda e: cancel_btn.config(bg="#4b5563"))
        cancel_btn.bind("<Leave>", lambda e: cancel_btn.config(bg="#6b7280"))

        dialog.wait_window()
        return result[0]

    def _upload(self) -> None:
        if self._busy or self.view_mode != "pending":
            return

        if not self.saved_exports:
            show_info(
                self,
                "Không có file",
                "Chưa có cặp PDF + CSV nào trong Pending để upload.",
            )
            return

        # Chỉ upload các cặp đã được tick ☑.
        targets = [e for e in self.saved_exports if e["id"] in self.upload_checked]
        if not targets:
            show_info(
                self,
                "Chưa chọn cặp nào",
                "Hãy tick ☑ vào các cặp muốn upload (hoặc bấm 'Tất cả').",
            )
            return

        total = len(targets)
        output_dir = self.output_var.get().strip()
        uploaded_folder = export_store.uploaded_dir(output_dir)
        pending_folder = export_store.pending_dir(output_dir)

        file_list = "\n".join(f"  {i+1}. {e['display_name']}" for i, e in enumerate(targets))

        # --- Demo mode (chưa cấu hình backend) ---
        if not API_UPLOAD_URL:
            msg = (
                "CHƯA CÓ BACKEND ENDPOINT!\n\n"
                "Bạn chưa cấu hình API_UPLOAD_URL trong file .env.\n"
                f"Demo: giả lập upload thành công {total} cặp đã chọn và chuyển "
                "sang mục Uploaded (di chuyển file sang thư mục uploaded)?"
            )
            if not messagebox.askyesno("Upload Demo", msg):
                return
            moved_ids = []
            for exp in targets:
                exp["pdf_sent"] = True
                exp["csv_sent"] = True
                try:
                    export_store.move_pair(exp, uploaded_folder)
                    moved_ids.append(exp["id"])
                except OSError as e:
                    log.warning("Demo move lỗi: %s", e)
            self._finalize_upload(moved_ids, "", total)
            self.status.set(
                f"Demo: {len(moved_ids)} cặp đã chuyển sang Uploaded", "success"
            )
            return

        # --- Real upload ---
        owner_email = self._ask_owner_email()
        if owner_email is None:
            return  # user hủy

        msg = (
            f"Sẽ upload {total} cặp file (PDF + CSV) đã chọn lên server:\n\n"
            f"{file_list}\n\n"
            f"Owner: {owner_email}\n\n"
            "Xác nhận gửi?"
        )
        if not messagebox.askyesno("Upload API", msg):
            return

        def work():
            moved_ids: list[str] = []
            fail_msg = ""
            for i, exp in enumerate(targets):
                self._post(
                    lambda idx=i, name=exp["display_name"]:
                    self._upload_progress(idx, total, name)
                )
                send_pdf = not exp.get("pdf_sent")
                send_csv = not exp.get("csv_sent")
                res = upload_pair(
                    API_UPLOAD_URL,
                    API_BEARER_TOKEN,
                    exp["pdf_path"],
                    exp["csv_path"],
                    owner=owner_email,
                    send_pdf=send_pdf,
                    send_csv=send_csv,
                )
                # Ghi nhớ file nào đã gửi (để retry không gửi trùng).
                if res.pdf_ok:
                    exp["pdf_sent"] = True
                if res.csv_ok:
                    exp["csv_sent"] = True

                if res.ok:
                    try:
                        export_store.move_pair(exp, uploaded_folder)
                    except OSError as e:
                        fail_msg = f"Đã gửi nhưng không di chuyển được file: {e}"
                        break
                    moved_ids.append(exp["id"])
                else:
                    # Lưu lại cờ đã-gửi từng phần rồi dừng.
                    try:
                        export_store.write_meta(pending_folder, exp)
                    except OSError:
                        pass
                    fail_msg = res.message
                    break
            return moved_ids, fail_msg

        def done(result, err):
            if err is not None:
                log.error("Upload crashed: %s", err, exc_info=err)
                self._set_busy(False)
                self.status.set(f"Lỗi upload: {err}", "error")
                return
            moved_ids, fail_msg = result
            self._finalize_upload(moved_ids, fail_msg, total)

        self._set_busy(True, f"Đang upload {total} cặp...")
        self._progress_show(maximum=total)
        self._run_async(work, done)

    def _upload_progress(self, idx: int, total: int, name: str) -> None:
        self.status.set(f"Đang upload [{idx + 1}/{total}]: {name}...", "working")
        self._progress_set(idx)

    def _finalize_upload(self, moved_ids: list, fail_msg: str, total: int) -> None:
        """Chuyển các cặp đã upload xong từ Pending sang Uploaded (main thread)."""

        self._progress_set(total)
        moved_set = set(moved_ids)

        remaining = []
        for exp in self.saved_exports:
            if exp["id"] in moved_set:
                self.uploaded_exports.append(exp)
                self.upload_checked.discard(exp["id"])
                original_file = exp.get("original_file")
                if original_file:
                    self.draft_form_data.pop(original_file, None)
                    self.draft_redactions.pop(original_file, None)
            else:
                remaining.append(exp)
        self.saved_exports = remaining

        # saved_files = tập file gốc còn có cặp đang chờ.
        self.saved_files = {
            e["original_file"] for e in self.saved_exports if e.get("original_file")
        }

        self.current_export_idx = None
        self._set_busy(False)
        self._refresh_pending_list()
        self._refresh_file_list()

        n_ok = len(moved_set)
        if fail_msg:
            self.status.set(
                f"Upload: {n_ok} OK, đã dừng do lỗi. "
                f"Còn {len(self.saved_exports)} cặp Pending.",
                "error",
            )
            show_error(
                self,
                "Upload có lỗi",
                f"Đã upload {n_ok}/{total} cặp file.\n\n"
                f"Lỗi: {fail_msg}\n\n"
                "Các cặp còn lại vẫn nằm trong Pending (có thể bấm Upload để thử lại).",
            )
        else:
            self.status.set(
                f"Upload thành công! {n_ok}/{total} cặp file.", "success"
            )

    # ================================================================
    # BACKGROUND / BUSY HELPERS
    # ================================================================

    def _poll_ui_queue(self) -> None:
        """Chạy trên main thread: thực thi các callback do thread nền đẩy vào."""

        try:
            while True:
                cb = self._ui_queue.get_nowait()
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    log.exception("UI callback lỗi")
        except queue.Empty:
            pass
        self.after(80, self._poll_ui_queue)

    def _post(self, callback) -> None:
        """Cho thread nền đặt lịch `callback` chạy trên main thread (an toàn)."""

        self._ui_queue.put(callback)

    def _run_async(self, work, done) -> None:
        """Chạy `work()` ở thread nền, gọi `done(result, err)` trên main thread."""

        def runner():
            try:
                result, err = work(), None
            except Exception as e:  # noqa: BLE001
                result, err = None, e
            self._post(lambda: done(result, err))

        threading.Thread(target=runner, daemon=True).start()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = busy
        if busy:
            self.save_btn.set_state("disabled")
            self.upload_btn.set_state("disabled")
            try:
                self.config(cursor="watch")
            except tk.TclError:
                pass
            if message:
                self.status.set(message, "working")
        else:
            self.save_btn.set_state("normal")
            self.upload_btn.set_state("normal")
            try:
                self.config(cursor="")
            except tk.TclError:
                pass
            self._progress_hide()

    def _progress_show(self, maximum: int = 0, indeterminate: bool = False) -> None:
        if indeterminate:
            self.progress.config(mode="indeterminate")
        else:
            self.progress.config(mode="determinate", maximum=max(1, maximum), value=0)
        try:
            self.progress.pack(fill="x", padx=10, pady=(0, 4), before=self.upload_btn)
        except tk.TclError:
            self.progress.pack(fill="x", padx=10, pady=(0, 4))
        if indeterminate:
            self.progress.start(12)

    def _progress_set(self, value: int) -> None:
        try:
            self.progress.config(value=value)
        except tk.TclError:
            pass

    def _progress_hide(self) -> None:
        try:
            self.progress.stop()
            self.progress.pack_forget()
            self.progress.config(value=0)
        except tk.TclError:
            pass

    # ================================================================
    # PERSISTENCE (nạp lại từ ổ đĩa) + CLEANUP
    # ================================================================

    def _reload_from_disk(self, announce: bool = False) -> None:
        """Quét thư mục pending/uploaded, dựng lại danh sách sau khi mở app."""

        base = self.output_var.get().strip()
        if not base:
            return
        try:
            pending, uploaded = export_store.read_all(base)
        except OSError as e:
            log.warning("Không nạp được state từ %s: %s", base, e)
            return

        self.saved_exports = pending
        self.uploaded_exports = uploaded
        # Mặc định tick sẵn toàn bộ cặp đang chờ để tiện upload tất cả.
        self.upload_checked = {e["id"] for e in pending}
        self.saved_files = {
            e["original_file"] for e in pending if e.get("original_file")
        }
        self.current_export_idx = None
        self._refresh_pending_list()
        self._refresh_file_list()

        if announce and (pending or uploaded):
            self.status.set(
                f"Đã nạp {len(pending)} cặp chờ upload, "
                f"{len(uploaded)} cặp đã upload từ thư mục làm việc.",
                "info",
            )

    def on_close(self) -> None:
        """Dọn tài nguyên khi đóng app (được App gọi qua WM_DELETE_WINDOW)."""

        if self.current_pdf:
            try:
                self.current_pdf.close()
            except Exception:
                pass
            self.current_pdf = None


__all__ = ["UploadPDFPage"]
