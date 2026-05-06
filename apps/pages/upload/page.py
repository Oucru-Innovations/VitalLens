"""Trang Upload PDF Xét Nghiệm.

Chia trách nhiệm:
- `UploadPDFPage` (file này) - chỉ chứa UI và state.
- `apps.services.pdf_redact` - render + ghi PDF đã tô đen.
- `apps.services.upload_api` - POST HTTP lên backend.
- `apps.widgets.date_picker.DatePicker` - popup lịch.
"""

from __future__ import annotations

import copy
import csv
import logging
import os
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
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
from apps.services.pdf_redact import save_redacted_pdf, temp_output_path
from apps.services.upload_api import upload_pair
from apps.widgets import DatePicker, StatusBar, StyledButton, make_header

log = logging.getLogger(__name__)

SAVE_RENDER_SCALE = 3.0
TYPE_OPTIONS = ("Hematology", "Biochemistry", "Microbiology", "Other")

# Naming rule: [DropdownType][Image/Metadata]_[PatientCode]_[dd.MM.yyyy.HH.mm.ss].<ext>


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

        self.pending_count_lbl = tk.Label(
            bottom, text="0 file", font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM
        )
        self.pending_count_lbl.pack(padx=10, anchor="w")

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
        self.pending_listbox.bind("<<ListboxSelect>>", self._on_pending_selected)
        self.pending_listbox.bind("<Delete>", self._on_delete_key)
        self.pending_listbox.bind("<BackSpace>", self._on_delete_key)

        self.upload_btn = StyledButton(
            bottom,
            text="▲  Upload",
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

        form = tk.Frame(right, bg=BG_CARD)
        form.pack(fill="x", padx=10)

        self.form_vars: dict[str, tk.StringVar] = {}
        self.input_widgets: list = []

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

            def open_picker():
                if self.view_mode == "uploaded":
                    return
                picker = DatePicker(self, var.get(), lambda d: var.set(d))
                picker.transient(self.winfo_toplevel())
                picker.grab_set()

            date_btn = tk.Label(
                row,
                text=" 📅 ",
                font=("Helvetica", 11),
                bg=ACCENT_BLUE,
                fg="#ffffff",
                cursor="hand2",
                padx=4,
                pady=3,
            )
            date_btn.pack(side="right", padx=(4, 0))
            date_btn.bind("<Button-1>", lambda e: open_picker())
            date_btn.bind("<Enter>", lambda e: date_btn.config(bg=BTN_HOVER_BLUE))
            date_btn.bind("<Leave>", lambda e: date_btn.config(bg=ACCENT_BLUE))

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
        files = filedialog.askopenfilenames(
            title="Chọn file PDF xét nghiệm",
            filetypes=[("PDF files", "*.pdf"), ("Tất cả", "*.*")],
        )
        if not files:
            return
        existing = set(self.pdf_files)
        for f in files:
            if f not in existing:
                self.pdf_files.append(f)
        self._refresh_file_list()

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
        self.view_mode = mode
        if mode == "pending":
            self.lbl_tab_pending.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_uploaded.config(fg=FG_DIM, cursor="hand2")
            self.upload_btn.pack(padx=10, pady=10, fill="x")
        else:
            self.lbl_tab_uploaded.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_pending.config(fg=FG_DIM, cursor="hand2")
            self.upload_btn.pack_forget()

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

        if is_readonly:
            if self.save_btn.winfo_ismapped():
                self.save_btn.pack_forget()
        else:
            if not self.save_btn.winfo_ismapped():
                self.save_btn.pack(padx=10, pady=(0, 10), fill="x")

    def _on_delete_key(self, event) -> None:
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
            self._delete_files(exp.get("pdf_path"), exp.get("csv_path"))
        except OSError as e:
            self.status.set(f"Không thể xóa file export: {e}", "error")
            return

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
            original_file = exp.get("original_file")

            if original_file and original_file != self.current_file:
                self._load_pdf(original_file)
            elif original_file:
                self._apply_state()
                self._restore_form_data(original_file)
                self._render_current_page()

        self.file_listbox.selection_clear(0, "end")

    def _refresh_pending_list(self) -> None:
        self.pending_listbox.delete(0, "end")
        data_list = (
            self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        )
        suffix = "[Chờ Upload]" if self.view_mode == "pending" else "[Đã Upload]"
        for exp in data_list:
            self.pending_listbox.insert("end", f"  🏷 {exp['display_name']} {suffix}")
        count = len(data_list)
        self.pending_count_lbl.config(
            text=f"{count} file (cặp)", fg=ACCENT_GREEN if count else FG_DIM
        )

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

        if self.current_pdf and self.current_file != filepath:
            try:
                self.current_pdf.close()
            except Exception:
                pass
            self.current_pdf = None

        if not self.current_pdf:
            self.current_file = filepath
            self.current_pdf = pdfium.PdfDocument(filepath)
            self.page_count = len(self.current_pdf)
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
        if not self.current_pdf:
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
        if self._is_uploaded_view() or not self.current_pdf:
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
        path = filedialog.askdirectory(title="Chọn thư mục lưu")
        if path:
            self.output_var.set(path)

    def _delete_files(self, *paths: str | None) -> None:
        for path in paths:
            if not path:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                continue

    def _save(self) -> None:
        if not self.current_file:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn file PDF trước.")
            return

        patient_code = self.form_vars["patient_code"].get().strip()
        if not patient_code:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập Patient Code.")
            return

        type_val = self.form_vars["type"].get().strip()
        if type_val == "Other":
            type_val = self.form_vars["other_type"].get().strip()
        if not type_val:
            messagebox.showwarning(
                "Thiếu thông tin", "Vui lòng chọn hoặc nhập Type."
            )
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            messagebox.showwarning(
                "Thiếu đường dẫn", "Vui lòng chọn thư mục lưu."
            )
            return

        os.makedirs(output_dir, exist_ok=True)

        form = {k: v.get().strip() for k, v in self.form_vars.items()}

        current_time = datetime.now().strftime("%d.%m.%Y.%H.%M.%S")
        safe_type = _sanitize_filename_token(type_val)
        safe_patient = _sanitize_filename_token(patient_code)

        pdf_name = f"{safe_type}Image_{safe_patient}_{current_time}_.pdf"
        csv_name = f"{safe_type}Metadata_{safe_patient}_{current_time}_.csv"
        pdf_path = os.path.join(output_dir, pdf_name)
        csv_path = os.path.join(output_dir, csv_name)
        display_name = f"{safe_type}Image_{safe_patient}_{current_time}_"

        old_pdf = None
        old_csv = None
        if self.current_export_idx is not None:
            data_list = (
                self.saved_exports
                if self.view_mode == "pending"
                else self.uploaded_exports
            )
            if self.current_export_idx < len(data_list):
                old_pdf = data_list[self.current_export_idx].get("pdf_path")
                old_csv = data_list[self.current_export_idx].get("csv_path")

        pdf_tmp = temp_output_path(pdf_path)
        csv_tmp = temp_output_path(csv_path)

        try:
            self._delete_files(pdf_tmp, csv_tmp)
            save_redacted_pdf(
                self.current_file,
                self.redactions.get(self.current_file, {}),
                pdf_tmp,
                scale=SAVE_RENDER_SCALE,
            )
            self._save_csv(csv_tmp, form)
            os.replace(pdf_tmp, pdf_path)
            os.replace(csv_tmp, csv_path)

            snapshot_form = copy.deepcopy(form)
            snapshot_redacts = copy.deepcopy(
                self.redactions.get(self.current_file, {})
            )

            if self.current_export_idx is not None:
                data_list = (
                    self.saved_exports
                    if self.view_mode == "pending"
                    else self.uploaded_exports
                )
                if self.current_export_idx < len(data_list):
                    data_list[self.current_export_idx].update(
                        {
                            "pdf_path": pdf_path,
                            "csv_path": csv_path,
                            "display_name": display_name,
                            "form_data": snapshot_form,
                            "redactions": snapshot_redacts,
                        }
                    )
            else:
                self.saved_exports.append(
                    {
                        "original_file": self.current_file,
                        "pdf_path": pdf_path,
                        "csv_path": csv_path,
                        "display_name": display_name,
                        "form_data": snapshot_form,
                        "redactions": snapshot_redacts,
                    }
                )
                saved_idx = len(self.saved_exports) - 1

                self.draft_form_data[self.current_file] = {}
                self.draft_redactions[self.current_file] = {}
                self.redactions[self.current_file] = {}

                self.current_export_idx = None
                self.set_view_mode("pending", preserve_idx=False)

                current_date = self.form_vars["date"].get()
                for key, var in self.form_vars.items():
                    if key != "date":
                        var.set("")
                self.form_vars["date"].set(current_date)

                self._render_current_page()
                self.pending_listbox.after(
                    50,
                    lambda idx=saved_idx: (
                        self.pending_listbox.selection_clear(0, "end"),
                        self.pending_listbox.selection_set(idx),
                    ),
                )

            self.saved_files.add(self.current_file)
            self._save_current_form_data()
            self._refresh_file_list()
            self._refresh_pending_list()

            if self.current_export_idx is not None:
                self.pending_listbox.selection_clear(0, "end")
                self.pending_listbox.selection_set(self.current_export_idx)

            stale_paths: list[str] = []
            if old_pdf and os.path.normcase(
                os.path.abspath(old_pdf)
            ) != os.path.normcase(os.path.abspath(pdf_path)):
                stale_paths.append(old_pdf)
            if old_csv and os.path.normcase(
                os.path.abspath(old_csv)
            ) != os.path.normcase(os.path.abspath(csv_path)):
                stale_paths.append(old_csv)
            try:
                self._delete_files(*stale_paths)
            except OSError:
                pass

            self.status.set(f"Đã lưu: {pdf_name} và {csv_name}", "success")
        except Exception as e:  # noqa: BLE001
            try:
                self._delete_files(pdf_tmp, csv_tmp)
            except OSError:
                pass
            log.exception("Save failed")
            self.status.set(f"Lỗi lưu: {e}", "error")

    def _save_csv(self, output_path: str, form: dict) -> None:
        fieldnames = list(form.keys())
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(form)

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
        if self.view_mode != "pending":
            return

        if not self.saved_exports:
            messagebox.showinfo(
                "Không có file",
                "Chưa có cặp PDF + CSV nào trong Pending để upload.",
            )
            return

        total = len(self.saved_exports)

        if not API_UPLOAD_URL:
            msg = (
                "CHƯA CÓ BACKEND ENDPOINT!\n\n"
                "Bạn chưa cấu hình API_UPLOAD_URL trong file .env,\n"
                f"Tuy nhiên để demo thì: Sẽ giả lập upload thành công\n"
                f"{total} cặp file và chuyển sang mục Uploaded nhé?"
            )
            if not messagebox.askyesno("Upload Demo", msg):
                return

            # Demo mode: chuyển tất cả sang uploaded
            while self.saved_exports:
                exp = self.saved_exports.pop(0)
                self.uploaded_exports.append(exp)
                original_file = exp.get("original_file")
                if original_file:
                    self.draft_form_data.pop(original_file, None)
                    self.draft_redactions.pop(original_file, None)
                    if not any(
                        e.get("original_file") == original_file
                        for e in self.saved_exports
                    ):
                        self.saved_files.discard(original_file)

            self.current_export_idx = None
            self._refresh_pending_list()
            self._refresh_file_list()
            self.status.set(f"Demo: {total} cặp file đã chuyển sang Uploaded", "success")
            return

        # --- Real upload ---
        file_list = "\n".join(
            f"  {i+1}. {exp['display_name']}"
            for i, exp in enumerate(self.saved_exports)
        )

        # Hỏi email owner qua dialog nhỏ
        owner_email = self._ask_owner_email()
        if owner_email is None:
            return  # User hủy

        msg = (
            f"Sẽ upload {total} cặp file (PDF + CSV) lên server:\n\n"
            f"{file_list}\n\n"
            f"Owner: {owner_email}\n\n"
            "Xác nhận gửi tất cả?"
        )
        if not messagebox.askyesno("Upload API", msg):
            return

        success_count = 0
        fail_count = 0
        first_error = ""

        # Upload từng cặp, luôn lấy phần tử đầu tiên vì list bị pop
        while self.saved_exports:
            exp = self.saved_exports[0]
            pdf_to_upload = exp["pdf_path"]
            csv_to_upload = exp["csv_path"]

            self.status.set(
                f"Đang upload [{success_count + fail_count + 1}/{total}]: "
                f"{exp['display_name']}...",
                "working",
            )
            self.update()

            result = upload_pair(
                API_UPLOAD_URL,
                API_BEARER_TOKEN,
                pdf_to_upload,
                csv_to_upload,
                owner=owner_email,
            )

            if result.ok:
                success_count += 1
                exp = self.saved_exports.pop(0)
                self.uploaded_exports.append(exp)

                original_file = exp.get("original_file")
                if original_file:
                    self.draft_form_data.pop(original_file, None)
                    self.draft_redactions.pop(original_file, None)
                    if not any(
                        e.get("original_file") == original_file
                        for e in self.saved_exports
                    ):
                        self.saved_files.discard(original_file)
            else:
                fail_count += 1
                if not first_error:
                    first_error = result.message
                # Dừng khi gặp lỗi
                break

        self.current_export_idx = None
        self._refresh_pending_list()
        self._refresh_file_list()

        if fail_count:
            self.status.set(
                f"Upload: {success_count} OK, {fail_count} lỗi. "
                f"Còn {len(self.saved_exports)} file pending.",
                "error",
            )
            messagebox.showerror(
                "Upload có lỗi",
                f"Đã upload {success_count}/{total} cặp file.\n\n"
                f"Lỗi: {first_error}\n\n"
                f"Các file còn lại vẫn nằm trong Pending.",
            )
        else:
            self.status.set(
                f"Upload thành công! {success_count}/{total} cặp file.", "success"
            )


__all__ = ["UploadPDFPage"]
