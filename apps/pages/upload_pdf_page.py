"""Trang Upload PDF Xét Nghiệm — xem, tô đen, nhập form, lưu PDF + CSV."""

import os
import csv
import calendar
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime

from apps.config import (
    APP_DIR, BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM, FG_TITLE,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_RED, ACCENT_PURPLE,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_PURPLE,
    BORDER_COLOR,
)
from apps.widgets import StyledButton, StatusBar, make_header

# Scale khi lưu PDF (3.0 ≈ 216 DPI). Tăng nếu cần chất lượng cao hơn.
SAVE_RENDER_SCALE = 3.0

# Naming rule: [DropdownType][Image/Metadata]_[PatientCode]_[currentDate(dd.MM.yyyy)].[HH.mm.ss]

class DatePicker(tk.Toplevel):
    def __init__(self, parent, initial_date=None, on_select=None):
        super().__init__(parent)
        self.title("Chọn Ngày")
        self.geometry("280x250")
        self.resizable(False, False)

        from apps.config import BG_CARD, BG_INPUT, FG_DIM, FG_TEXT, ACCENT_BLUE

        self.on_select = on_select
        
        if initial_date:
            try:
                self.current_date = datetime.strptime(initial_date, "%d-%m-%Y")
            except ValueError:
                self.current_date = datetime.now()
        else:
            self.current_date = datetime.now()
            
        self.year = self.current_date.year
        self.month = self.current_date.month
        self.bg_card = BG_CARD
        self.bg_input = BG_INPUT
        self.fg_dim = FG_DIM
        self.accent = ACCENT_BLUE
        
        self._build_ui()
        self._update_calendar()
        
    def _build_ui(self):
        header = tk.Frame(self, bg=self.bg_card)
        header.pack(fill="x", pady=5)
        
        btn_prev = tk.Button(header, text="<", command=self._prev_month, width=3)
        btn_prev.pack(side="left", padx=5)
        
        self.lbl_month_year = tk.Label(header, font=("Helvetica", 11, "bold"), bg=self.bg_card)
        self.lbl_month_year.pack(side="left", expand=True)
        
        btn_next = tk.Button(header, text=">", command=self._next_month, width=3)
        btn_next.pack(side="right", padx=5)
        
        self.cal_frame = tk.Frame(self, bg=self.bg_card)
        self.cal_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        for i, d in enumerate(days):
            tk.Label(self.cal_frame, text=d, fg=self.fg_dim, font=("Helvetica", 9, "bold"), bg=self.bg_card).grid(row=0, column=i, sticky="nsew")
        for i in range(7):
            self.cal_frame.columnconfigure(i, weight=1)
            
    def _update_calendar(self):
        self.lbl_month_year.config(text=f"{self.month:02d}/{self.year}")
        for widget in self.cal_frame.grid_slaves():
            if int(widget.grid_info()["row"]) > 0:
                widget.destroy()
                
        cal = calendar.monthcalendar(self.year, self.month)
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if day != 0:
                    btn = tk.Button(self.cal_frame, text=str(day), relief="flat", bg=self.bg_input, 
                                    command=lambda d=day: self._select(d))
                    if self.year == self.current_date.year and self.month == self.current_date.month and day == self.current_date.day:
                        btn.config(bg=self.accent, fg="white")
                    btn.grid(row=r+1, column=c, sticky="nsew", padx=1, pady=1)

    def _prev_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self._update_calendar()

    def _next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self._update_calendar()
        
    def _select(self, day):
        if self.on_select:
            selected = f"{day:02d}-{self.month:02d}-{self.year}"
            self.on_select(selected)
        self.destroy()


class UploadPDFPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller

        # ---- state ----
        self.pdf_files = []
        self.current_file = None
        self.current_pdf = None
        self.page_count = 0
        self.current_page = 0
        self._photo = None
        self._display_scale = 1.0
        self._img_offset_x = 0
        self._img_offset_y = 0
        self._img_width = 0
        self._img_height = 0
        self._drawing = False
        self._draw_start = None
        self._draw_rect_id = None

        # Per-file data
        self.redactions = {}
        self.form_data = {}
        self.saved_files = set()
        
        self.draft_redactions = {}    # {filepath: {page_num: [(x1,y1,x2,y2)]}}
        self.draft_form_data = {}     # {filepath: {key: value}}
        self.saved_exports = []       # list of export dicts
        self.uploaded_exports = []    # Mới thêm
        self.view_mode = "pending"
        self.current_export_idx = None

        make_header(self, controller, "Upload PDF Xét Nghiệm")

        # ---- 3-panel layout ----
        pw = tk.PanedWindow(self, orient="horizontal", bg=BORDER_COLOR,
                            sashwidth=4, sashrelief="flat")
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
    # BUILD PANELS
    # ================================================================

    def _build_left_panel(self, parent):
        left = tk.Frame(parent, bg=BG_CARD)

        # --- Vùng 1: Logic cũ (chọn file gốc) ---
        top_frame = tk.Frame(left, bg=BG_CARD)
        top_frame.pack(fill="both", expand=True, padx=0, pady=0)

        tk.Label(top_frame, text="Danh sách PDF gốc", font=("Helvetica", 11, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(padx=10, pady=(10, 5), anchor="w")

        pick_btn = tk.Label(top_frame, text="  + Chọn file PDF...  ", font=("Helvetica", 11, "bold"),
                            bg=ACCENT_ORANGE, fg="#ffffff", cursor="hand2", padx=8, pady=5)
        pick_btn.pack(padx=10, pady=(0, 5), fill="x")
        pick_btn.bind("<Button-1>", lambda e: self._pick_files())
        pick_btn.bind("<Enter>", lambda e: pick_btn.config(bg=BTN_HOVER_ORANGE))
        pick_btn.bind("<Leave>", lambda e: pick_btn.config(bg=ACCENT_ORANGE))

        self.file_count_lbl = tk.Label(top_frame, text="Chưa chọn file", font=("Helvetica", 10),
                                       bg=BG_CARD, fg=FG_DIM)
        self.file_count_lbl.pack(padx=10, anchor="w")

        list_frame1 = tk.Frame(top_frame, bg=BG_CARD)
        list_frame1.pack(fill="both", expand=True, padx=5, pady=5)

        sb1 = tk.Scrollbar(list_frame1)
        sb1.pack(side="right", fill="y")

        self.file_listbox = tk.Listbox(
            list_frame1, font=("Helvetica", 10), bg=BG_INPUT, fg=FG_TEXT,
            selectbackground=ACCENT_BLUE, selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0, yscrollcommand=sb1.set)
        self.file_listbox.pack(fill="both", expand=True)
        sb1.config(command=self.file_listbox.yview)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_selected)

        # Ngăn cách giữa 2 vùng
        tk.Frame(left, bg=BORDER_COLOR, height=2).pack(fill="x", padx=5, pady=5)

        # --- Vùng 2: Pending & Uploaded Files ---
        bottom_frame = tk.Frame(left, bg=BG_CARD)
        bottom_frame.pack(fill="both", expand=True, padx=0, pady=0)

        tab_frame = tk.Frame(bottom_frame, bg=BG_CARD)
        tab_frame.pack(fill="x", padx=10, pady=(5, 5))
        
        self.lbl_tab_pending = tk.Label(tab_frame, text="Pending", font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=ACCENT_BLUE, cursor="arrow")
        self.lbl_tab_pending.pack(side="left")
        self.lbl_tab_pending.bind("<Button-1>", lambda e: self.set_view_mode("pending"))
        
        tk.Label(tab_frame, text=" | ", font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM).pack(side="left")
        
        self.lbl_tab_uploaded = tk.Label(tab_frame, text="Uploaded", font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_DIM, cursor="hand2")
        self.lbl_tab_uploaded.pack(side="left")
        self.lbl_tab_uploaded.bind("<Button-1>", lambda e: self.set_view_mode("uploaded"))

        self.pending_count_lbl = tk.Label(bottom_frame, text="0 file", font=("Helvetica", 10),
                                          bg=BG_CARD, fg=FG_DIM)
        self.pending_count_lbl.pack(padx=10, anchor="w")

        list_frame2 = tk.Frame(bottom_frame, bg=BG_CARD)
        list_frame2.pack(fill="both", expand=True, padx=5, pady=5)

        sb2 = tk.Scrollbar(list_frame2)
        sb2.pack(side="right", fill="y")

        self.pending_listbox = tk.Listbox(
            list_frame2, font=("Helvetica", 10), bg=BG_INPUT, fg=FG_TEXT,
            selectbackground=ACCENT_BLUE, selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0, yscrollcommand=sb2.set)
        self.pending_listbox.pack(fill="both", expand=True)
        sb2.config(command=self.pending_listbox.yview)
        
        self.pending_listbox.bind("<<ListboxSelect>>", self._on_pending_selected)
        self.pending_listbox.bind("<Delete>", self._on_delete_key)
        self.pending_listbox.bind("<BackSpace>", self._on_delete_key)

        # Upload button
        self.upload_btn = StyledButton(bottom_frame, text="▲  Upload", command=self._upload,
                                       bg_color=ACCENT_PURPLE, hover_color=BTN_HOVER_PURPLE,
                                       font_size=12)
        self.upload_btn.pack(padx=10, pady=10, fill="x")

        return left

    def _build_center_panel(self, parent):
        center = tk.Frame(parent, bg=BG_CARD)

        # Nav bar
        nav = tk.Frame(center, bg=BG_CARD)
        nav.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(nav, text="Xem & Tô đen PDF", font=("Helvetica", 11, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(side="left")

        undo_btn = tk.Label(nav, text="  ↩ Undo  ", font=("Helvetica", 10, "bold"),
                            bg=ACCENT_RED, fg="#ffffff", cursor="hand2", padx=4, pady=2)
        undo_btn.pack(side="right", padx=2)
        undo_btn.bind("<Button-1>", lambda e: self._undo_redaction())
        undo_btn.bind("<Enter>", lambda e: undo_btn.config(bg="#b91c1c"))
        undo_btn.bind("<Leave>", lambda e: undo_btn.config(bg=ACCENT_RED))

        clear_btn = tk.Label(nav, text="  ✕ Xóa hết  ", font=("Helvetica", 10, "bold"),
                             bg="#6b7280", fg="#ffffff", cursor="hand2", padx=4, pady=2)
        clear_btn.pack(side="right", padx=2)
        clear_btn.bind("<Button-1>", lambda e: self._clear_redactions())
        clear_btn.bind("<Enter>", lambda e: clear_btn.config(bg="#4b5563"))
        clear_btn.bind("<Leave>", lambda e: clear_btn.config(bg="#6b7280"))

        next_btn = tk.Label(nav, text="  ▶  ", font=("Helvetica", 11, "bold"),
                            bg=BG_CARD, fg=ACCENT_BLUE, cursor="hand2")
        next_btn.pack(side="right", padx=2)
        next_btn.bind("<Button-1>", lambda e: self._change_page(1))

        self.page_label = tk.Label(nav, text="", font=("Helvetica", 10),
                                   bg=BG_CARD, fg=FG_DIM)
        self.page_label.pack(side="right", padx=4)

        prev_btn = tk.Label(nav, text="  ◀  ", font=("Helvetica", 11, "bold"),
                            bg=BG_CARD, fg=ACCENT_BLUE, cursor="hand2")
        prev_btn.pack(side="right", padx=2)
        prev_btn.bind("<Button-1>", lambda e: self._change_page(-1))

        # Canvas
        self.canvas = tk.Canvas(center, bg="#e0e0e0", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)

        self.canvas.bind("<ButtonPress-1>", self._on_draw_start)
        self.canvas.bind("<B1-Motion>", self._on_draw_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_draw_end)

        self.canvas.create_text(200, 150, text="Chọn file PDF để xem",
                                font=("Helvetica", 13), fill=FG_DIM, tags="placeholder")

        return center

    def _build_right_panel(self, parent):
        right = tk.Frame(parent, bg=BG_CARD)

        tk.Label(right, text="Thông tin phiếu xét nghiệm", font=("Helvetica", 12, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(padx=10, pady=(10, 5), anchor="w")

        # Output directory
        out_sec = tk.Frame(right, bg=BG_CARD)
        out_sec.pack(fill="x", padx=10, pady=(0, 8))

        tk.Label(out_sec, text="Thư mục lưu:", font=("Helvetica", 10, "bold"),
                 bg=BG_CARD, fg=FG_DIM).pack(anchor="w")

        out_row = tk.Frame(out_sec, bg=BORDER_COLOR, highlightbackground=BORDER_COLOR,
                           highlightthickness=1)
        out_row.pack(fill="x")

        self.output_var = tk.StringVar(value=str(APP_DIR / "output_pdf"))
        tk.Entry(out_row, textvariable=self.output_var, font=("Helvetica", 10),
                 bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                 borderwidth=0, highlightthickness=0,
                 relief="flat"
                 ).pack(side="left", fill="x", expand=True, ipady=5, padx=(6, 0))

        browse_btn = tk.Label(out_row, text=" … ", font=("Helvetica", 10, "bold"),
                              bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=8, pady=5)
        browse_btn.pack(side="left")
        browse_btn.bind("<Button-1>", lambda e: self._pick_output_dir())
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(bg=BTN_HOVER_BLUE))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(bg=ACCENT_BLUE))

        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x", padx=10, pady=5)

        # Form fields
        form = tk.Frame(right, bg=BG_CARD)
        form.pack(fill="x", padx=10)

        self.form_vars = {}
        self.input_widgets = []

        def _input_border(parent_frame):
            """Tạo wrapper frame giả border cho widget."""
            wrapper = tk.Frame(parent_frame, bg=BORDER_COLOR,
                               highlightbackground=BORDER_COLOR, highlightthickness=1)
            return wrapper

        def _make_entry(key, label_text):
            row = tk.Frame(form, bg=BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label_text, font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TEXT,
                     width=20, anchor="e").pack(side="left", padx=(0, 6))
            var = tk.StringVar(value="")
            self.form_vars[key] = var
            
            wrapper = _input_border(row)
            wrapper.pack(side="left", fill="x", expand=True)
            
            entry = tk.Entry(wrapper, textvariable=var, font=("Helvetica", 11),
                     bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                     borderwidth=0, highlightthickness=0, relief="flat")
            self.input_widgets.append(entry)
            entry.pack(fill="x", ipady=5, padx=4, pady=2)
            return row

        def _make_entry_date(key, label_text, default_value=""):
            row = tk.Frame(form, bg=BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label_text, font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TEXT,
                     width=20, anchor="e").pack(side="left", padx=(0, 6))
            
            var = tk.StringVar(value=default_value)
            self.form_vars[key] = var

            def open_picker():
                if self.view_mode == "uploaded": return
                picker = DatePicker(self, var.get(), lambda d: var.set(d))
                picker.transient(self.winfo_toplevel())
                picker.grab_set()
            
            # Date button badge
            date_btn = tk.Label(row, text=" 📅 ", font=("Helvetica", 11),
                                bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=4, pady=3)
            date_btn.pack(side="right", padx=(4, 0))
            date_btn.bind("<Button-1>", lambda e: open_picker())
            date_btn.bind("<Enter>", lambda e: date_btn.config(bg=BTN_HOVER_BLUE))
            date_btn.bind("<Leave>", lambda e: date_btn.config(bg=ACCENT_BLUE))
            
            wrapper = _input_border(row)
            wrapper.pack(side="left", fill="x", expand=True)
            
            entry = tk.Entry(wrapper, textvariable=var, font=("Helvetica", 11),
                             bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                             borderwidth=0, highlightthickness=0, relief="flat")
            self.input_widgets.append(entry)
            entry.pack(fill="x", ipady=5, padx=4, pady=2)
            
            return row

        # Date Fix (read-only display)
        row_date = tk.Frame(form, bg=BG_CARD)
        row_date.pack(fill="x", pady=4)
        tk.Label(row_date, text="Date:", font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TEXT,
                 width=20, anchor="e").pack(side="left", padx=(0, 6))
        
        current_date_str = datetime.now().strftime("%d-%m-%Y")
        self.form_vars["date"] = tk.StringVar(value=current_date_str)
        
        date_display = tk.Frame(row_date, bg=BG_INPUT, highlightbackground=BORDER_COLOR,
                                highlightthickness=1)
        date_display.pack(side="left", fill="x", expand=True)
        tk.Label(date_display, textvariable=self.form_vars["date"],
                 font=("Helvetica", 11, "bold"), bg=BG_INPUT, fg=ACCENT_BLUE,
                 anchor="w").pack(fill="x", padx=8, pady=5)

        _make_entry("patient_code", "Patient Code:")

        # Type Box
        self.row_type = tk.Frame(form, bg=BG_CARD)
        self.row_type.pack(fill="x", pady=4)
        tk.Label(self.row_type, text="Type:", font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TEXT,
                 width=20, anchor="e").pack(side="left", padx=(0, 6))
        self.form_vars["type"] = tk.StringVar(value="")
        
        type_wrapper = _input_border(self.row_type)
        type_wrapper.pack(side="left", fill="x", expand=True)
        box = ttk.Combobox(type_wrapper, textvariable=self.form_vars["type"], state="readonly", font=("Helvetica", 11))
        self.input_widgets.append(box)
        box['values'] = ("Hematology", "Biochemistry", "Microbiology", "Other")
        box.pack(fill="x", ipady=4, padx=2, pady=1)

        # Other Type Box
        self.row_other = tk.Frame(form, bg=BG_CARD)
        tk.Label(self.row_other, text="Specify Other:", font=("Helvetica", 11, "bold"), bg=BG_CARD, fg=FG_TEXT,
                 width=20, anchor="e").pack(side="left", padx=(0, 6))
        self.form_vars["other_type"] = tk.StringVar(value="")
        
        other_wrapper = _input_border(self.row_other)
        other_wrapper.pack(side="left", fill="x", expand=True)
        other_entry = tk.Entry(other_wrapper, textvariable=self.form_vars["other_type"], font=("Helvetica", 11),
                 bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                 borderwidth=0, highlightthickness=0, relief="flat")
        self.input_widgets.append(other_entry)
        other_entry.pack(fill="x", ipady=5, padx=4, pady=2)

        def on_type_selected(event=None):
            if self.form_vars["type"].get() == "Other":
                self.row_other.pack(fill="x", pady=4, after=self.row_type)
            else:
                self.row_other.pack_forget()

        box.bind("<<ComboboxSelected>>", on_type_selected)
        self.update_type_visibility = on_type_selected

        _make_entry_date("sampling_date", "Sampling Date:")
        _make_entry_date("receipt_date", "Date of sample receipt:")
        _make_entry_date("result_date", "Date of results:")

        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x", padx=10, pady=10)

        # Save button
        self.save_btn = StyledButton(right, text="💾  Lưu (PDF + CSV)", command=self._save,
                                     bg_color=ACCENT_BLUE, hover_color=BTN_HOVER_BLUE,
                                     font_size=12)
        self.save_btn.pack(padx=10, pady=(0, 10), fill="x")

        return right

    # ================================================================
    # FILE MANAGEMENT
    # ================================================================

    def _pick_files(self):
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

    def _refresh_file_list(self):
        self.file_listbox.delete(0, "end")
        for f in self.pdf_files:
            name = os.path.basename(f)
            prefix = "  ✓  " if f in self.saved_files else "  "
            self.file_listbox.insert("end", prefix + name)
            if f in self.saved_files:
                self.file_listbox.itemconfig(self.file_listbox.size() - 1, fg=ACCENT_GREEN)
        self.file_count_lbl.config(
            text=f"✓ {len(self.pdf_files)} file" if self.pdf_files else "Chưa chọn file",
            fg=ACCENT_GREEN if self.pdf_files else FG_DIM)

    def _on_file_selected(self, event):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        filepath = self.pdf_files[idx]
        
        self._save_current_form_data()
        self.current_export_idx = None # Chuyển về chế độ Draft
        
        if filepath != self.current_file:
            self._load_pdf(filepath)
        else:
            self._apply_state()
            self._restore_form_data(filepath)
            self._render_current_page()
            self._update_form_state()
            
        if hasattr(self, "pending_listbox"):
            self.pending_listbox.selection_clear(0, "end")

    def set_view_mode(self, mode, preserve_idx=False):
        self.view_mode = mode
        if mode == "pending":
            self.lbl_tab_pending.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_uploaded.config(fg=FG_DIM, cursor="hand2")
            if hasattr(self, "upload_btn"):
                self.upload_btn.pack(padx=10, pady=10, fill="x")
        else:
            self.lbl_tab_uploaded.config(fg=ACCENT_BLUE, cursor="arrow")
            self.lbl_tab_pending.config(fg=FG_DIM, cursor="hand2")
            if hasattr(self, "upload_btn"):
                self.upload_btn.pack_forget()
        
        if not preserve_idx:
            self.current_export_idx = None
            
        self._refresh_pending_list()
        self._update_form_state()

    def _update_form_state(self):

        is_readonly = (self.view_mode == "uploaded")
        
        for w in getattr(self, "input_widgets", []):
            if isinstance(w, ttk.Combobox):
                w.config(state="disabled" if is_readonly else "readonly")
            elif isinstance(w, tk.Entry):
                w.config(state="disabled" if is_readonly else "normal")
                
        if is_readonly:
            if hasattr(self, "save_btn") and self.save_btn.winfo_ismapped():
                self.save_btn.pack_forget()
        else:
            if hasattr(self, "save_btn") and not self.save_btn.winfo_ismapped():
                self.save_btn.pack(padx=10, pady=(0, 10), fill="x")

    def _on_delete_key(self, event):
        sel = self.pending_listbox.curselection()
        if not sel: return
        idx = sel[0]
        
        # prevent focus bugs
        self.focus_set()
        
        mode_text = "Pending" if self.view_mode == "pending" else "Uploaded"
        ans = messagebox.askyesno("Xác nhận xóa", f"Bạn có chắc muốn xóa bản lưu này khỏi mục {mode_text}?\n(Sẽ xóa luôn file gốc được xuất ra trên ổ cứng)")
        if not ans: return
        
        data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        exp = data_list[idx]
        original_file = exp.get("original_file")

        old_pdf, old_csv = exp.get("pdf_path"), exp.get("csv_path")
        try:
            self._delete_export_files(old_pdf, old_csv)
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

    def _on_pending_selected(self, event):
        sel = self.pending_listbox.curselection()
        if not sel: return
        idx = sel[0]
        data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        
        if idx < len(data_list):
            self._save_current_form_data()
            self.current_export_idx = idx
            
            exp = data_list[idx]
            original_file = exp.get("original_file")
            
            if original_file and (original_file != self.current_file):
                self._load_pdf(original_file)
            elif original_file:
                self._apply_state()
                self._restore_form_data(original_file)
                self._render_current_page()

        self.file_listbox.selection_clear(0, "end")

    def _refresh_pending_list(self):
        self.pending_listbox.delete(0, "end")
        data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
        suffix = "[Chờ Upload]" if self.view_mode == "pending" else "[Đã Upload]"
        
        for exp in data_list:
            name = exp["display_name"]
            self.pending_listbox.insert("end", f"  🏷 {name} {suffix}")
        
        count = len(data_list)
        self.pending_count_lbl.config(text=f"{count} file (cặp)", fg=ACCENT_GREEN if count else FG_DIM)

    def _save_current_form_data(self):
        if not self.current_file: return
        import copy
        form_copy = {k: v.get() for k, v in self.form_vars.items()}
        redacts_copy = copy.deepcopy(self.redactions.get(self.current_file, {}))
        
        if self.current_export_idx is not None:
            data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
            if self.current_export_idx < len(data_list):
                data_list[self.current_export_idx]["form_data"] = form_copy
                data_list[self.current_export_idx]["redactions"] = redacts_copy
        else:
            self.draft_form_data[self.current_file] = form_copy
            self.draft_redactions[self.current_file] = redacts_copy

    def _apply_state(self):
        import copy
        if self.current_export_idx is not None:
             data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
             if self.current_export_idx < len(data_list):
                 exp = data_list[self.current_export_idx]
                 self.form_data[self.current_file] = copy.deepcopy(exp.get("form_data", {}))
                 self.redactions[self.current_file] = copy.deepcopy(exp.get("redactions", {}))
        else:
             self.form_data[self.current_file] = copy.deepcopy(self.draft_form_data.get(self.current_file, {}))
             self.redactions[self.current_file] = copy.deepcopy(self.draft_redactions.get(self.current_file, {}))

    def _restore_form_data(self, filepath):
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

    def _load_pdf(self, filepath):
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
        self.status.set(f"Đang xem: {os.path.basename(filepath)} ({self.page_count} trang)", "info")

    def _render_current_page(self):
        if not self.current_pdf:
            return

        self.canvas.delete("all")
        self.canvas.update_idletasks()

        page = self.current_pdf[self.current_page]
        pw_pts, ph_pts = page.get_size()

        canvas_w = max(self.canvas.winfo_width() - 20, 400)
        canvas_h = max(self.canvas.winfo_height() - 20, 400)

        scale_w = canvas_w / pw_pts
        scale_h = canvas_h / ph_pts
        self._display_scale = min(scale_w, scale_h)

        bitmap = page.render(scale=self._display_scale)
        img = bitmap.to_pil()

        # Vẽ các vùng tô đen đã có
        from PIL import ImageDraw
        page_rects = self.redactions.get(self.current_file, {}).get(self.current_page, [])
        if page_rects:
            draw = ImageDraw.Draw(img)
            for (px1, py1, px2, py2) in page_rects:
                dx1 = int(px1 * self._display_scale)
                dy1 = int(py1 * self._display_scale)
                dx2 = int(px2 * self._display_scale)
                dy2 = int(py2 * self._display_scale)
                draw.rectangle([dx1, dy1, dx2, dy2], fill="black")

        from PIL import ImageTk
        self._photo = ImageTk.PhotoImage(img)

        # Đặt ảnh giữa canvas
        cx = canvas_w // 2
        cy = canvas_h // 2
        self._img_offset_x = cx - img.width // 2
        self._img_offset_y = cy - img.height // 2
        self._img_width = img.width
        self._img_height = img.height

        self.canvas.create_image(self._img_offset_x, self._img_offset_y,
                                 image=self._photo, anchor="nw", tags="pdf_image")

        self.page_label.config(text=f"Trang {self.current_page + 1}/{self.page_count}")

    def _change_page(self, delta):
        if not self.current_pdf:
            return
        new_page = self.current_page + delta
        if 0 <= new_page < self.page_count:
            self.current_page = new_page
            self._render_current_page()

    # ================================================================
    # DRAWING (REDACTION)
    # ================================================================

    def _canvas_to_pdf_pts(self, cx, cy):
        """Chuyển tọa độ canvas → PDF points."""
        ix = cx - self._img_offset_x
        iy = cy - self._img_offset_y
        return ix / self._display_scale, iy / self._display_scale

    def _on_draw_start(self, event):
        is_uploaded = (self.view_mode == "uploaded") and (self.current_export_idx is not None)
        if is_uploaded: return
        if not self.current_pdf:
            return
        ix = event.x - self._img_offset_x
        iy = event.y - self._img_offset_y
        if not (0 <= ix <= self._img_width and 0 <= iy <= self._img_height):
            return
        self._drawing = True
        self._draw_start = (event.x, event.y)

    def _on_draw_motion(self, event):
        if not self._drawing:
            return
        if self._draw_rect_id:
            self.canvas.delete(self._draw_rect_id)
        x0, y0 = self._draw_start
        self._draw_rect_id = self.canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="red", width=2, dash=(4, 2), tags="draw_preview")

    def _on_draw_end(self, event):
        if not self._drawing:
            return
        self._drawing = False
        if self._draw_rect_id:
            self.canvas.delete(self._draw_rect_id)
            self._draw_rect_id = None

        x0, y0 = self._draw_start
        x1, y1 = event.x, event.y
        cx1, cy1 = min(x0, x1), min(y0, y1)
        cx2, cy2 = max(x0, x1), max(y0, y1)

        # Bỏ qua click nhỏ (tránh tô nhầm)
        if abs(cx2 - cx1) < 5 or abs(cy2 - cy1) < 5:
            return

        px1, py1 = self._canvas_to_pdf_pts(cx1, cy1)
        px2, py2 = self._canvas_to_pdf_pts(cx2, cy2)

        # Clamp vào kích thước trang
        page = self.current_pdf[self.current_page]
        pw_pts, ph_pts = page.get_size()
        px1 = max(0, min(px1, pw_pts))
        py1 = max(0, min(py1, ph_pts))
        px2 = max(0, min(px2, pw_pts))
        py2 = max(0, min(py2, ph_pts))

        page_rects = self.redactions.setdefault(self.current_file, {}).setdefault(self.current_page, [])
        page_rects.append((px1, py1, px2, py2))

        self._render_current_page()

    def _undo_redaction(self):
        is_uploaded = (self.view_mode == "uploaded") and (self.current_export_idx is not None)
        if is_uploaded: return
        if not self.current_file:
            return
        page_rects = self.redactions.get(self.current_file, {}).get(self.current_page, [])
        if page_rects:
            page_rects.pop()
            self._render_current_page()
            self.status.set("Đã undo vùng tô đen cuối cùng", "info")

    def _clear_redactions(self):
        is_uploaded = (self.view_mode == "uploaded") and (self.current_export_idx is not None)
        if is_uploaded: return
        if not self.current_file:
            return
        file_redacts = self.redactions.get(self.current_file, {})
        if self.current_page in file_redacts:
            file_redacts[self.current_page] = []
            self._render_current_page()
            self.status.set("Đã xóa hết vùng tô đen trang hiện tại", "info")

    # ================================================================
    # SAVE
    # ================================================================

    def _pick_output_dir(self):
        path = filedialog.askdirectory(title="Chọn thư mục lưu")
        if path:
            self.output_var.set(path)

    def _delete_export_files(self, *paths):
        for path in paths:
            if not path:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                continue

    def _temp_output_path(self, output_path):
        path = Path(output_path)
        return str(path.with_name(f"{path.stem}.__tmp__{path.suffix}"))

    def _save(self):
        if not self.current_file:
            messagebox.showwarning("Chưa chọn file", "Vui lòng chọn file PDF trước.")
            return

        patient_code = self.form_vars.get("patient_code").get().strip()
        if not patient_code:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập Patient Code.")
            return

        type_val = self.form_vars.get("type").get().strip()
        if type_val == "Other":
            type_val = self.form_vars.get("other_type").get().strip()

        if not type_val:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng chọn hoặc nhập Type.")
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Thiếu đường dẫn", "Vui lòng chọn thư mục lưu.")
            return

        os.makedirs(output_dir, exist_ok=True)

        # Build form data cho file CSV
        form = {k: v.get().strip() for k, v in self.form_vars.items()}

        def _safe(s):
            return (s.replace("/", "-").replace("\\", "-")
                     .replace(":", "-").replace("*", "").replace("?", "")
                     .replace('"', "").replace("<", "").replace(">", "")
                     .replace("|", "").strip()) or "_"

        current_time = datetime.now().strftime("%d.%m.%Y.%H.%M.%S")
        safe_type = _safe(type_val)
        safe_patient = _safe(patient_code)

        pdf_name = f"{safe_type}Image_{safe_patient}_{current_time}_.pdf"
        csv_name = f"{safe_type}Metadata_{safe_patient}_{current_time}_.csv"

        pdf_path = os.path.join(output_dir, pdf_name)
        csv_path = os.path.join(output_dir, csv_name)

        display_name = f"{safe_type}Image_{safe_patient}_{current_time}_"

        old_pdf = None
        old_csv = None
        if self.current_export_idx is not None:
            data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
            if self.current_export_idx < len(data_list):
                old_exp = data_list[self.current_export_idx]
                old_pdf = old_exp.get("pdf_path")
                old_csv = old_exp.get("csv_path")

        pdf_tmp_path = self._temp_output_path(pdf_path)
        csv_tmp_path = self._temp_output_path(csv_path)

        try:
            self._delete_export_files(pdf_tmp_path, csv_tmp_path)
            self._save_redacted_pdf(pdf_tmp_path)
            self._save_csv(csv_tmp_path, form)
            os.replace(pdf_tmp_path, pdf_path)
            os.replace(csv_tmp_path, csv_path)

            import copy
            snapshot_form = copy.deepcopy(form)
            snapshot_redacts = copy.deepcopy(self.redactions.get(self.current_file, {}))

            if self.current_export_idx is not None:
                data_list = self.saved_exports if self.view_mode == "pending" else self.uploaded_exports
                if self.current_export_idx < len(data_list):
                    data_list[self.current_export_idx].update({
                        "pdf_path": pdf_path,
                        "csv_path": csv_path,
                        "display_name": display_name,
                        "form_data": snapshot_form,
                        "redactions": snapshot_redacts
                    })
            else:
                self.saved_exports.append({
                    "original_file": self.current_file,
                    "pdf_path": pdf_path,
                    "csv_path": csv_path,
                    "display_name": display_name,
                    "form_data": snapshot_form,
                    "redactions": snapshot_redacts
                })
                self.current_export_idx = len(self.saved_exports) - 1
                
                self.draft_form_data[self.current_file] = {}
                self.draft_redactions[self.current_file] = {}
                self.redactions[self.current_file] = {}
                
                saved_idx = self.current_export_idx
                self.current_export_idx = None  
                
                if hasattr(self, "lbl_tab_pending"):
                    self.set_view_mode("pending", preserve_idx=False)
                
                current_date = self.form_vars["date"].get()
                for key, var in self.form_vars.items():
                    if key != "date":
                        var.set("")
                self.form_vars["date"].set(current_date)
                
                self._render_current_page()
                
                self.pending_listbox.after(50, lambda: (
                    self.pending_listbox.selection_clear(0, "end"),
                    self.pending_listbox.selection_set(saved_idx)
                ))

            self.saved_files.add(self.current_file)
            self._save_current_form_data()

            self._refresh_file_list()
            self._refresh_pending_list()

            if self.current_export_idx is not None:
                self.pending_listbox.selection_clear(0, "end")
                self.pending_listbox.selection_set(self.current_export_idx)

            stale_paths = []
            if old_pdf and os.path.normcase(os.path.abspath(old_pdf)) != os.path.normcase(os.path.abspath(pdf_path)):
                stale_paths.append(old_pdf)
            if old_csv and os.path.normcase(os.path.abspath(old_csv)) != os.path.normcase(os.path.abspath(csv_path)):
                stale_paths.append(old_csv)
            try:
                self._delete_export_files(*stale_paths)
            except OSError:
                pass

            self.status.set(f"Đã lưu: {pdf_name} và {csv_name}", "success")
        except Exception as e:
            try:
                self._delete_export_files(pdf_tmp_path, csv_tmp_path)
            except OSError:
                pass
            self.status.set(f"Lỗi lưu: {e}", "error")

    def _save_redacted_pdf(self, output_path):
        import pypdfium2 as pdfium
        from PIL import Image, ImageDraw

        pdf = pdfium.PdfDocument(self.current_file)
        images = []
        file_redactions = self.redactions.get(self.current_file, {})

        for page_num in range(len(pdf)):
            page = pdf[page_num]
            bitmap = page.render(scale=SAVE_RENDER_SCALE)
            img = bitmap.to_pil().convert("RGB")

            page_rects = file_redactions.get(page_num, [])
            if page_rects:
                draw = ImageDraw.Draw(img)
                for (px1, py1, px2, py2) in page_rects:
                    sx1 = int(px1 * SAVE_RENDER_SCALE)
                    sy1 = int(py1 * SAVE_RENDER_SCALE)
                    sx2 = int(px2 * SAVE_RENDER_SCALE)
                    sy2 = int(py2 * SAVE_RENDER_SCALE)
                    draw.rectangle([sx1, sy1, sx2, sy2], fill="black")

            images.append(img)

        pdf.close()

        if images:
            images[0].save(output_path, "PDF", save_all=True, append_images=images[1:],
                           resolution=SAVE_RENDER_SCALE * 72)

    def _save_csv(self, output_path, form):
        fieldnames = list(form.keys())
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(form)

    # ================================================================
    # UPLOAD (placeholder)
    # ================================================================

    def _upload(self):
        if self.view_mode != "pending":
            return
            
        sel = self.pending_listbox.curselection()
        if not sel:
            messagebox.showinfo("Chưa chọn file", "Vui lòng chỉ định 1 cặp file trong vùng Pending File để upload.")
            return
        
        idx = sel[0]
        if idx < len(self.saved_exports):
            export_data = self.saved_exports[idx]
            
            pdf_to_upload = export_data["pdf_path"]
            csv_to_upload = export_data["csv_path"]
            
            from apps.config import API_UPLOAD_URL, API_BEARER_TOKEN
            if not API_UPLOAD_URL:
                msg = f"CHƯA CÓ BACKEND ENDPOINT!\n\nBạn chưa cấu hình API_UPLOAD_URL trong file .env,\nTuy nhiên để demo thì: Sẽ giả lập upload thành công file\n{os.path.basename(pdf_to_upload)}\nvà chuyển sang mục Uploaded nhé?"
                ans = messagebox.askyesno("Upload Demo", msg)
            else:
                msg = f"Sẽ đẩy 2 file lên qua API:\n\n1. {os.path.basename(pdf_to_upload)}\n2. {os.path.basename(csv_to_upload)}\n\nXác nhận gửi HTTP POST?"
                ans = messagebox.askyesno("Upload API", msg)
            
            if not ans: return

            if API_UPLOAD_URL:
                # Thực hiện HTTP request thật
                try:
                    import requests
                    headers = {}
                    if API_BEARER_TOKEN:
                        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"
                    
                    self.status.set("Đang upload...", "info")
                    self.update()
                    
                    with open(pdf_to_upload, 'rb') as fpdf, open(csv_to_upload, 'rb') as fcsv:
                        files = {
                            'pdf_file': (os.path.basename(pdf_to_upload), fpdf, 'application/pdf'),
                            'csv_file': (os.path.basename(csv_to_upload), fcsv, 'text/csv'),
                        }
                        
                        resp = requests.post(API_UPLOAD_URL, headers=headers, files=files, timeout=60)
                        
                    if resp.status_code not in (200, 201):
                        self.status.set(f"Lỗi {resp.status_code} từ Server: {resp.text[:100]}", "error")
                        messagebox.showerror("Upload thất bại", f"Server báo lỗi code {resp.status_code}:\n{resp.text}")
                        return
                except Exception as e:
                    self.status.set(f"Không thể gọi API: {str(e)}", "error")
                    messagebox.showerror("Lỗi mạng", f"Lỗi Network hoặc Exception: {str(e)}")
                    return
            
            exp = self.saved_exports.pop(idx)
            self.uploaded_exports.append(exp)
            
            original_file = exp.get("original_file")
            if original_file:
                self.draft_form_data.pop(original_file, None)
                self.draft_redactions.pop(original_file, None)
                still_has_pending = any(
                    e.get("original_file") == original_file
                    for e in self.saved_exports
                )
                if not still_has_pending:
                    self.saved_files.discard(original_file)
            
            if self.current_export_idx == idx:
                self.current_export_idx = None
            elif self.current_export_idx is not None and self.current_export_idx > idx:
                self.current_export_idx -= 1
            
            self._refresh_pending_list()
            self._refresh_file_list()
            self.status.set("Upload thành công!", "success")
