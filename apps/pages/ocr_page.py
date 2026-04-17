"""Trang Ä‘Ã¡nh giÃ¡ káº¿t quáº£ OCR."""

import os
import io
import csv
import json
import re
import platform
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from apps.config import (
    BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM, FG_TITLE,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_RED,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN,
    BORDER_COLOR,
    SFTP_HOST, SFTP_PORT, SFTP_DEMO_MODE, SFTP_PATH,
)
from apps.widgets import StyledButton, StatusBar, make_header, make_section
from apps.processing.xray import load_image

OCR_VALIDATE_TYPE = "OCR VILIDATE"

LAB_VALIDATE_TYPES = (
    "Táº¥t cáº£",
    "Ventilator",
    "Monitor",
    "Hematology",
    "Biochemistry",
    "Microbiology",
    "Other",
)


class OCRPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller
        self.sftp_connected = False
        self.ocr_type = None
        self.root_dir = None
        self.all_confirmed = []
        self.confirmed_files = []
        self._photo_ref = None
        self.current_folder_name = None
        self.current_folder_path = None
        self.current_json_file = None
        self.current_json_data = None
        self.current_csv_file = None
        self.current_csv_rows = []
        self.current_csv_fieldnames = []
        self.form_vars = {}
        self.result_vars = []
        self.folders = []
        self.lab_records = []
        self.lab_processing_roots = []
        self.lab_root_dir_error = None
        self.filtered_lab_records = []
        self.current_lab_record = None
        self.lab_type_var = tk.StringVar(value=LAB_VALIDATE_TYPES[0])

        make_header(self, controller, "ÄÃ¡nh giÃ¡ káº¿t quáº£ OCR")

        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True)
        self.body = body

        # === Section: SFTP Login ===
        s1 = make_section(body, "ÄÄ‚NG NHáº¬P SFTP")

        row_user = tk.Frame(s1, bg=BG_CARD)
        row_user.pack(fill="x", padx=15, pady=4)
        tk.Label(row_user, text="Username:", font=("Helvetica", 12), bg=BG_CARD, fg=FG_TEXT,
                 width=10, anchor="e").pack(side="left")
        self.user_var = tk.StringVar(value="")
        tk.Entry(row_user, textvariable=self.user_var, font=("Helvetica", 12),
                 bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                 borderwidth=0, highlightthickness=1, highlightcolor=ACCENT_BLUE
                 ).pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))

        row_pass = tk.Frame(s1, bg=BG_CARD)
        row_pass.pack(fill="x", padx=15, pady=(4, 12))
        tk.Label(row_pass, text="Password:", font=("Helvetica", 12), bg=BG_CARD, fg=FG_TEXT,
                 width=10, anchor="e").pack(side="left")
        self.pass_var = tk.StringVar(value="")
        tk.Entry(row_pass, textvariable=self.pass_var, font=("Helvetica", 12), show="â—",
                 bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                 borderwidth=0, highlightthickness=1, highlightcolor=ACCENT_BLUE
                 ).pack(side="left", fill="x", expand=True, ipady=5, padx=(8, 0))

        btn_frame = tk.Frame(s1, bg=BG_CARD)
        btn_frame.pack(pady=(0, 15))
        self.connect_btn = StyledButton(btn_frame, text="Káº¿t ná»‘i SFTP", command=self._connect_sftp,
                                        bg_color=ACCENT_BLUE, hover_color=BTN_HOVER_BLUE, font_size=13)
        self.connect_btn.pack()

        self.status = StatusBar(body)
        self.status.pack(fill="x", padx=25, pady=(12, 0))

        self.content_frame = tk.Frame(body, bg=BG_MAIN)
        self.content_frame.pack(fill="both", expand=True, padx=25, pady=10)
        tk.Label(self.content_frame, text="Vui lÃ²ng Ä‘Äƒng nháº­p SFTP Ä‘á»ƒ tiáº¿p tá»¥c",
                 font=("Helvetica", 13), bg=BG_MAIN, fg=FG_DIM).pack(expand=True)

        self.review_frame = tk.Frame(self, bg=BG_MAIN)

    # ===================== SFTP =====================

    def _connect_sftp(self):
        if SFTP_DEMO_MODE:
            self.connect_btn.set_state("disabled")
            self.status.set("Äang káº¿t ná»‘i (DEMO)...", "working")
            self.after(500, lambda: self._on_connected(None, None))
            return

        host = SFTP_HOST.strip()
        port = SFTP_PORT
        username = self.user_var.get().strip()
        password = self.pass_var.get()

        if not host:
            messagebox.showwarning("Thiáº¿u thÃ´ng tin", "ChÆ°a cáº¥u hÃ¬nh host SFTP trong code.")
            return
        if not username:
            messagebox.showwarning("Thiáº¿u thÃ´ng tin", "Vui lÃ²ng nháº­p username.")
            return
        if not password:
            messagebox.showwarning("Thiáº¿u thÃ´ng tin", "Vui lÃ²ng nháº­p password.")
            return
        self.connect_btn.set_state("disabled")
        self.status.set("Äang káº¿t ná»‘i...", "working")

        def do_connect():
            try:
                import paramiko
                transport = paramiko.Transport((host, port))
                transport.connect(username=username, password=password)
                sftp = paramiko.SFTPClient.from_transport(transport)
                self.controller.after(0, lambda: self._on_connected(sftp, transport))
            except ImportError:
                self.controller.after(0, lambda: self._on_connect_fail(
                    "Thiáº¿u thÆ° viá»‡n paramiko. Cháº¡y: pip install paramiko"))
            except Exception as e:
                self.controller.after(0, lambda: self._on_connect_fail(str(e)))

        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connected(self, sftp, transport):
        self.sftp = sftp
        self.transport = transport
        self.sftp_connected = True
        self.connect_btn.set_state("normal")
        self.status.set(f"ÄÃ£ káº¿t ná»‘i thÃ nh cÃ´ng tá»›i {SFTP_HOST or 'DEMO'}", "success")

        for w in self.content_frame.winfo_children():
            w.destroy()

        tk.Label(self.content_frame, text="Chá»n loáº¡i Ä‘Ã¡nh giÃ¡ OCR",
                 font=("Helvetica", 15, "bold"), bg=BG_MAIN, fg=FG_TITLE).pack(pady=(20, 15))

        cards = tk.Frame(self.content_frame, bg=BG_MAIN)
        cards.pack()

        btn_data = [
            (OCR_VALIDATE_TYPE, "ÄÃ¡nh giÃ¡ káº¿t quáº£ OCR phiáº¿u xÃ©t nghiá»‡m", ACCENT_BLUE, BTN_HOVER_BLUE),
        ]

        for title, desc, color, hover in btn_data:
            card = tk.Frame(cards, bg=BG_CARD, highlightbackground=BORDER_COLOR,
                            highlightthickness=1, cursor="hand2")
            card.pack(pady=6, ipadx=20, ipady=10, fill="x")

            inner = tk.Frame(card, bg=BG_CARD)
            inner.pack(fill="x", padx=20, pady=8)

            left = tk.Frame(inner, bg=BG_CARD)
            left.pack(side="left", fill="both", expand=True)

            tk.Label(left, text=title, font=("Helvetica", 15, "bold"), bg=BG_CARD, fg=FG_TITLE).pack(anchor="w")
            tk.Label(left, text=desc, font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM,
                     justify="left").pack(anchor="w", pady=(2, 0))

            arrow = tk.Label(inner, text=">", font=("Helvetica", 16, "bold"), bg=BG_CARD, fg=color)
            arrow.pack(side="right", padx=(10, 0))

            for widget in [card, inner, left, arrow] + left.winfo_children():
                widget.bind("<Button-1>", lambda e, t=title: self._on_ocr_type_selected(t))
                widget.bind("<Enter>", lambda e, c=card, clr=hover: c.config(highlightbackground=clr, highlightthickness=2))
                widget.bind("<Leave>", lambda e, c=card: c.config(highlightbackground=BORDER_COLOR, highlightthickness=1))

    def _on_connect_fail(self, error_msg):
        self.connect_btn.set_state("normal")
        self.status.set(f"Káº¿t ná»‘i tháº¥t báº¡i: {error_msg}", "error")

    # ===================== OCR TYPE SELECTION =====================

    def _on_ocr_type_selected(self, ocr_type):
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
                    title=f"Chá»n thÆ° má»¥c gá»‘c cho {ocr_type} (DEMO)")
                if not root_dir:
                    return
                self.root_dir = root_dir
        else:
            self.root_dir = SFTP_PATH
            if not self.root_dir:
                messagebox.showwarning("Thiáº¿u cáº¥u hÃ¬nh", f"ChÆ°a cáº¥u hÃ¬nh Ä‘Æ°á»ng dáº«n SFTP cho {ocr_type}.")
                return
        self._show_review_ui()

    def _is_validate_mode(self):
        return self.ocr_type == OCR_VALIDATE_TYPE

    # ===================== REVIEW UI =====================

    def _show_review_ui(self):
        self.body.pack_forget()
        for w in self.review_frame.winfo_children():
            w.destroy()
        self.review_frame.pack(fill="both", expand=True)

        # Sub-header
        sub_hdr = tk.Frame(self.review_frame, bg=BG_CARD, height=44)
        sub_hdr.pack(fill="x")
        sub_hdr.pack_propagate(False)

        back_lbl = tk.Label(sub_hdr, text="  â† Quay láº¡i  ", font=("Helvetica", 11),
                            bg=BG_CARD, fg=ACCENT_BLUE, cursor="hand2")
        back_lbl.pack(side="left", padx=10)
        back_lbl.bind("<Button-1>", lambda e: self._back_to_type_selection())
        back_lbl.bind("<Enter>", lambda e: back_lbl.config(fg=BTN_HOVER_BLUE, font=("Helvetica", 11, "underline")))
        back_lbl.bind("<Leave>", lambda e: back_lbl.config(fg=ACCENT_BLUE, font=("Helvetica", 11)))

        tk.Label(sub_hdr, text=self.ocr_type, font=("Helvetica", 14, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(side="left", padx=5)

        tk.Frame(self.review_frame, bg=BORDER_COLOR, height=1).pack(fill="x")

        # Main PanedWindow layout
        pw = tk.PanedWindow(self.review_frame, orient="horizontal", bg=BORDER_COLOR,
                            sashwidth=4, sashrelief="flat")
        pw.pack(fill="both", expand=True, pady=2)

        # === Left: folder / record list ===
        left = tk.Frame(pw, bg=BG_CARD)

        list_title = "Danh sÃ¡ch há»“ sÆ¡" if self._is_validate_mode() else "Danh sÃ¡ch folder"
        self.folder_list_title = tk.Label(left, text=list_title, font=("Helvetica", 11, "bold"),
                                          bg=BG_CARD, fg=FG_TITLE)
        self.folder_list_title.pack(padx=10, pady=(10, 5), anchor="w")

        if self._is_validate_mode():
            filter_row = tk.Frame(left, bg=BG_CARD)
            filter_row.pack(fill="x", padx=10, pady=(0, 8))

            tk.Label(filter_row, text="Loáº¡i:", font=("Helvetica", 10, "bold"),
                     bg=BG_CARD, fg=FG_DIM).pack(side="left")

            self.lab_type_box = ttk.Combobox(
                filter_row,
                textvariable=self.lab_type_var,
                state="readonly",
                values=("Táº¥t cáº£",),
                font=("Helvetica", 10),
            )
            self.lab_type_box.configure(values=LAB_VALIDATE_TYPES)
            self.lab_type_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
            self.lab_type_box.bind("<<ComboboxSelected>>", self._on_lab_type_changed)

        list_frame = tk.Frame(left, bg=BG_CARD)
        list_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        sb = tk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.folder_listbox = tk.Listbox(
            list_frame, font=("Helvetica", 11), bg=BG_INPUT, fg=FG_TEXT,
            selectbackground=ACCENT_BLUE, selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0, yscrollcommand=sb.set)
        self.folder_listbox.pack(fill="both", expand=True)
        sb.config(command=self.folder_listbox.yview)
        self.folder_listbox.bind("<<ListboxSelect>>", self._on_folder_selected)

        export_text = "Export theo loáº¡i" if self._is_validate_mode() else "Export Excel"
        self.export_btn = StyledButton(left, text=export_text, command=self._export_excel,
                                       bg_color=ACCENT_GREEN, hover_color=BTN_HOVER_GREEN,
                                       font_size=11)
        self.export_btn.pack(padx=10, pady=10, fill="x")

        pw.add(left, minsize=180, width=220)

        # === Center: viewer ===
        center = tk.Frame(pw, bg=BG_CARD)

        tk.Label(center, text="Xem trÆ°á»›c", font=("Helvetica", 11, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(padx=10, pady=(10, 5), anchor="w")

        viewer_container = tk.Frame(center, bg=BG_CARD)
        viewer_container.pack(fill="both", expand=True, padx=5, pady=5)

        self.viewer_canvas = tk.Canvas(viewer_container, bg=BG_CARD, highlightthickness=0)
        viewer_sb = tk.Scrollbar(viewer_container, orient="vertical", command=self.viewer_canvas.yview)
        self.viewer_canvas.configure(yscrollcommand=viewer_sb.set)
        viewer_sb.pack(side="right", fill="y")
        self.viewer_canvas.pack(side="left", fill="both", expand=True)

        self.viewer_frame = tk.Frame(self.viewer_canvas, bg=BG_CARD)
        self._viewer_cw = self.viewer_canvas.create_window((0, 0), window=self.viewer_frame, anchor="nw")
        self.viewer_frame.bind("<Configure>",
                               lambda e: self.viewer_canvas.configure(scrollregion=self.viewer_canvas.bbox("all")))
        self.viewer_canvas.bind("<Configure>",
                                lambda e: self.viewer_canvas.itemconfig(self._viewer_cw, width=e.width))

        def _vw_mw(evt):
            self.viewer_canvas.yview_scroll(int(-1 * evt.delta), "units")
        self.viewer_canvas.bind("<Enter>", lambda e: self.viewer_canvas.bind_all("<MouseWheel>", _vw_mw))
        self.viewer_canvas.bind("<Leave>", lambda e: self.viewer_canvas.unbind_all("<MouseWheel>"))

        viewer_hint = "Chá»n há»“ sÆ¡ Ä‘á»ƒ xem" if self._is_validate_mode() else "Chá»n folder Ä‘á»ƒ xem"
        tk.Label(self.viewer_frame, text=viewer_hint,
                 font=("Helvetica", 12), bg=BG_CARD, fg=FG_DIM).pack(expand=True)

        sw = self.controller.winfo_width() or self.controller.winfo_screenwidth()
        remaining = sw - 220
        half = int(remaining * 0.5)
        pw.add(center, minsize=250, width=half)

        # === Right: form ===
        right = tk.Frame(pw, bg=BG_CARD)

        tk.Label(right, text="Chá»‰nh sá»­a dá»¯ liá»‡u", font=("Helvetica", 12, "bold"),
                 bg=BG_CARD, fg=FG_TITLE).pack(padx=10, pady=(10, 5), anchor="w")

        form_container = tk.Frame(right, bg=BG_CARD)
        form_container.pack(fill="both", expand=True, padx=5)

        self.form_canvas = tk.Canvas(form_container, bg=BG_CARD, highlightthickness=0)
        form_sb = tk.Scrollbar(form_container, orient="vertical", command=self.form_canvas.yview)
        self.form_canvas.configure(yscrollcommand=form_sb.set)
        form_sb.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)

        self.form_inner = tk.Frame(self.form_canvas, bg=BG_CARD)
        self._form_cw = self.form_canvas.create_window((0, 0), window=self.form_inner, anchor="nw")
        self.form_inner.bind("<Configure>",
                             lambda e: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>",
                              lambda e: self.form_canvas.itemconfig(self._form_cw, width=e.width))

        def _mw(evt):
            self.form_canvas.yview_scroll(int(-1 * evt.delta), "units")
        self.form_canvas.bind("<Enter>", lambda e: self.form_canvas.bind_all("<MouseWheel>", _mw))
        self.form_canvas.bind("<Leave>", lambda e: self.form_canvas.unbind_all("<MouseWheel>"))

        form_hint = "Chá»n há»“ sÆ¡ Ä‘á»ƒ xem dá»¯ liá»‡u" if self._is_validate_mode() else "Chá»n folder Ä‘á»ƒ xem dá»¯ liá»‡u"
        tk.Label(self.form_inner, text=form_hint,
                 font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM).pack(pady=20)

        self.submit_btn = StyledButton(right, text="Submit xÃ¡c nháº­n", command=self._submit,
                                       bg_color=ACCENT_BLUE, hover_color=BTN_HOVER_BLUE,
                                       font_size=12)
        self.submit_btn.pack(padx=10, pady=10, fill="x")

        self.review_frame.bind_all("<Return>", lambda e: self._submit())

        pw.add(right, minsize=250, width=half)

        self.review_status = StatusBar(self.review_frame)
        self.review_status.pack(fill="x", padx=5, pady=(0, 5))

        self._load_folders()

    def _back_to_type_selection(self):
        self.review_frame.unbind_all("<Return>")
        self.review_frame.pack_forget()
        self.body.pack(fill="both", expand=True)

    def _join_data_path(self, base_path, *parts):
        if SFTP_DEMO_MODE:
            return os.path.join(base_path, *parts)

        path = base_path.rstrip("/")
        for part in parts:
            path += "/" + str(part).strip("/")
        return path

    def _get_path_name(self, path):
        clean_path = str(path).rstrip("/\\")
        if not clean_path:
            return ""
        if SFTP_DEMO_MODE:
            return Path(clean_path).name
        return clean_path.split("/")[-1]

    def _safe_is_data_dir(self, path):
        try:
            return self._is_data_dir(path)
        except Exception:
            return False

    def _resolve_existing_data_dir(self, path):
        clean_path = str(path).rstrip("/\\")
        if not clean_path:
            return None

        if self._safe_is_data_dir(clean_path):
            return clean_path

        if SFTP_DEMO_MODE:
            return None

        is_abs = clean_path.startswith("/")
        parts = [part for part in clean_path.split("/") if part]
        if not parts:
            return "/" if self._safe_is_data_dir("/") else None

        current = "/" if is_abs else ""
        for part in parts:
            parent = current or "."
            resolved = self._resolve_named_child_dir(parent, part)
            if not self._safe_is_data_dir(resolved):
                return None
            current = resolved

        return current

    def _prepare_lab_root_dir(self):
        self.lab_root_dir_error = None
        if not self.root_dir:
            self.lab_root_dir_error = "Chua cau hinh thu muc goc cho OCR validate."
            return None

        resolved_root = self._resolve_existing_data_dir(self.root_dir)
        if resolved_root:
            self.root_dir = resolved_root
            return resolved_root

        self.lab_root_dir_error = (
            f"Khong truy cap duoc thu muc goc: {self.root_dir}. "
            "Kiem tra lai SFTP_PATH hoac study ID trong apps/config.py."
        )
        return None

    def _resolve_named_child_dir(self, parent_path, child_name):
        direct_path = self._join_data_path(parent_path, child_name)
        if self._safe_is_data_dir(direct_path):
            return direct_path

        try:
            child_names = self._list_data_dir(parent_path)
        except Exception:
            return direct_path

        target_name = child_name.lower()
        for existing_name in child_names:
            if existing_name.lower() != target_name:
                continue
            candidate_path = self._join_data_path(parent_path, existing_name)
            if self._safe_is_data_dir(candidate_path):
                return candidate_path

        return direct_path

    def _list_data_dir(self, path):
        return os.listdir(path) if SFTP_DEMO_MODE else self.sftp.listdir(path)

    def _is_data_dir(self, path):
        if SFTP_DEMO_MODE:
            return os.path.isdir(path)

        import stat as st_mod
        return st_mod.S_ISDIR(self.sftp.stat(path).st_mode)

    def _remove_data_file(self, path):
        if SFTP_DEMO_MODE:
            if os.path.exists(path):
                os.remove(path)
            return

        try:
            self.sftp.remove(path)
        except (IOError, OSError):
            return

    def _normalize_json_stem(self, json_filename):
        stem = Path(json_filename).stem
        for suffix in ("_confirmed", "_final"):
            if stem.endswith(suffix):
                return stem[:-len(suffix)]
        return stem

    def _rename_data_file(self, source_path, target_path):
        if SFTP_DEMO_MODE:
            os.replace(source_path, target_path)
            return

        try:
            self.sftp.remove(target_path)
        except (IOError, OSError):
            pass
        self.sftp.rename(source_path, target_path)

    def _strip_record_status_suffix(self, stem):
        for suffix in ("_validated", "_done"):
            if stem.endswith(suffix):
                return stem[:-len(suffix)], suffix[1:]
        return stem, "raw"

    def _discover_lab_processing_roots(self):
        if not self.root_dir:
            return []

        processing_roots = []
        seen = set()

        def add_processing_root(path):
            key = str(path).rstrip("/\\")
            if not key or key in seen or not self._safe_is_data_dir(path):
                return
            seen.add(key)
            processing_roots.append(path)

        if self._get_path_name(self.root_dir).upper() == "PROCESSING":
            add_processing_root(self.root_dir)
            return processing_roots

        add_processing_root(self._join_data_path(self.root_dir, "PROCESSING"))

        try:
            child_names = sorted(self._list_data_dir(self.root_dir))
        except Exception:
            return processing_roots

        for child_name in child_names:
            child_path = self._join_data_path(self.root_dir, child_name)
            if not self._safe_is_data_dir(child_path):
                continue

            if child_name.upper() == "PROCESSING":
                add_processing_root(child_path)
                continue

            add_processing_root(self._join_data_path(child_path, "PROCESSING"))

        return processing_roots

    def _get_study_id_from_processing_root(self, processing_root):
        clean_path = str(processing_root).rstrip("/\\")
        if SFTP_DEMO_MODE:
            parts = Path(clean_path).parts
        else:
            parts = tuple(part for part in clean_path.split("/") if part)

        if len(parts) >= 2 and parts[-1].upper() == "PROCESSING":
            return parts[-2]
        if parts:
            return parts[-1]
        return "UNKNOWN"

    def _parse_lab_record_type(self, base_stem, patient_id):
        marker = f"_{patient_id}_"
        if marker in base_stem:
            record_type = base_stem.split(marker, 1)[0].strip("_ ")
            if record_type:
                return self._normalize_lab_record_type(record_type)

        fallback = base_stem.split("_", 1)[0].strip("_ ")
        return self._normalize_lab_record_type(fallback)

    def _normalize_lab_record_type(self, record_type):
        raw = (record_type or "").strip()
        if not raw:
            return "Other"

        normalized = re.sub(r"[^a-z0-9]+", "", raw.lower())
        alias_map = {
            "ventilator": "Ventilator",
            "vent": "Ventilator",
            "monitor": "Monitor",
            "hematology": "Hematology",
            "haematology": "Hematology",
            "biochemistry": "Biochemistry",
            "chemistry": "Biochemistry",
            "microbiology": "Microbiology",
            "micro": "Microbiology",
            "other": "Other",
        }
        return alias_map.get(normalized, "Other")

    def _read_json_payload(self, folder_path, json_file):
        if SFTP_DEMO_MODE:
            with open(os.path.join(folder_path, json_file), "r", encoding="utf-8") as f:
                return json.load(f)

        remote_path = folder_path.rstrip("/") + "/" + json_file
        with self.sftp.open(remote_path, "r") as f:
            return json.loads(f.read().decode("utf-8"))

    def _read_csv_payload(self, folder_path, csv_file):
        if not csv_file:
            return [], []

        if SFTP_DEMO_MODE:
            with open(os.path.join(folder_path, csv_file), "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                return list(reader.fieldnames or []), list(reader)

        remote_path = self._join_data_path(folder_path, csv_file)
        with self.sftp.open(remote_path, "r") as f:
            raw_bytes = f.read()
        content = raw_bytes.decode("utf-8-sig")
        stream = io.StringIO(content)
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)

    def _write_json_payload(self, folder_path, json_file, data):
        content = json.dumps(data, ensure_ascii=False, indent=2)
        if SFTP_DEMO_MODE:
            with open(os.path.join(folder_path, json_file), "w", encoding="utf-8") as f:
                f.write(content)
            return

        remote_path = self._join_data_path(folder_path, json_file)
        with self.sftp.open(remote_path, "w") as f:
            f.write(content.encode("utf-8"))

    def _write_csv_payload(self, folder_path, csv_file, rows):
        fieldnames = list(dict.fromkeys(
            key
            for row in rows
            for key in row.keys()
        ))
        if not fieldnames:
            fieldnames = ["record_type", "study_id", "patient_id", "record_date", "source_pdf"]

        if SFTP_DEMO_MODE:
            with open(os.path.join(folder_path, csv_file), "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in fieldnames})
            return

        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

        remote_path = self._join_data_path(folder_path, csv_file)
        with self.sftp.open(remote_path, "w") as f:
            f.write(stream.getvalue().encode("utf-8-sig"))

    def _confirmed_to_rows(self, folder_name, data):
        if self.ocr_type == "OCR BEDSIDE MONITOR":
            row = {"folder": folder_name}
            for key, val_obj in data.items():
                if isinstance(val_obj, dict):
                    row[key] = val_obj.get("value", "")
                elif isinstance(val_obj, list) and val_obj:
                    row[key] = val_obj[0].get("value", "")
                else:
                    row[key] = val_obj
            return [row]

        base_info = {
            key: value for key, value in data.items()
            if key not in {"results", "raw_text"}
        }
        rows = []
        for result in data.get("results", []):
            if not any(value for value in result.values()):
                continue
            rows.append({"folder": folder_name, **base_info, **result})
        return rows

    def _build_lab_rows(self, record, data):
        base_row = {
            "record_type": record["record_type"],
            "study_id": record["study_id"],
            "patient_id": record["patient_id"],
            "record_date": record["date_token"],
            "source_pdf": record["pdf_file"],
        }

        for key, value in data.items():
            if key in {"results", "raw_text", "notification", "error"}:
                continue
            base_row[key] = value

        rows = []
        results = data.get("results") or []
        if not results:
            rows.append(dict(base_row))
            return rows

        for result in results:
            row = dict(base_row)
            row.update(result)
            rows.append(row)
        return rows

    def _build_lab_record_groups(self, study_id, patient_id, date_token, image_path, files):
        groups = {}
        for name in files:
            suffix = Path(name).suffix.lower()
            if suffix not in {".pdf", ".csv", ".json"}:
                continue

            base_stem, status = self._strip_record_status_suffix(Path(name).stem)
            group = groups.setdefault(base_stem, {
                "base_stem": base_stem,
                "patient_id": patient_id,
                "date_token": date_token,
                "image_path": image_path,
            })
            group[f"{suffix[1:]}_{status}"] = name

        records = []
        for base_stem in sorted(groups):
            group = groups[base_stem]
            pdf_file = group.get("pdf_raw")
            if not pdf_file:
                continue

            raw_json = group.get("json_raw")
            validated_json = group.get("json_validated")
            done_json = group.get("json_done")
            raw_csv = group.get("csv_raw")
            validated_csv = group.get("csv_validated")
            done_csv = group.get("csv_done")

            if not (raw_json or validated_json or done_json):
                continue
            if not (raw_csv or validated_csv or done_csv):
                continue

            status = "pending"
            if validated_json and validated_csv:
                status = "validated"
            if done_json and done_csv:
                status = "done"

            record_type = self._parse_lab_record_type(base_stem, patient_id)
            record_key = f"{study_id}|{patient_id}|{date_token}|{base_stem}"
            records.append({
                "record_key": record_key,
                "study_id": study_id,
                "base_stem": base_stem,
                "record_type": record_type,
                "patient_id": patient_id,
                "date_token": date_token,
                "image_path": image_path,
                "pdf_file": pdf_file,
                "json_raw": raw_json,
                "json_validated": validated_json,
                "json_done": done_json,
                "csv_raw": raw_csv,
                "csv_validated": validated_csv,
                "csv_done": done_csv,
                "active_json_file": validated_json or raw_json or done_json,
                "active_csv_file": validated_csv or raw_csv or done_csv,
                "status": status,
                "display_name": f"[{record_type}] {study_id}/{patient_id}/{date_token} - {pdf_file}",
            })

        return records

    def _scan_lab_records(self):
        records = []
        if not self._prepare_lab_root_dir():
            return records

        self.lab_processing_roots = self._discover_lab_processing_roots()
        for processing_root in self.lab_processing_roots:
            study_id = self._get_study_id_from_processing_root(processing_root)

            try:
                patient_dirs = sorted(self._list_data_dir(processing_root))
            except Exception:
                continue

            for patient_id in patient_dirs:
                patient_path = self._join_data_path(processing_root, patient_id)
                if not self._safe_is_data_dir(patient_path):
                    continue

                try:
                    date_dirs = sorted(self._list_data_dir(patient_path))
                except Exception:
                    continue

                for date_token in date_dirs:
                    date_path = self._join_data_path(patient_path, date_token)
                    if not self._safe_is_data_dir(date_path):
                        continue

                    image_path = self._resolve_named_child_dir(date_path, "Image")
                    if not self._safe_is_data_dir(image_path):
                        continue

                    try:
                        files = self._list_data_dir(image_path)
                    except Exception:
                        continue

                    records.extend(
                        self._build_lab_record_groups(study_id, patient_id, date_token, image_path, files)
                    )

        records = [record for record in records if record["status"] != "done"]
        records.sort(key=lambda record: (
            record["study_id"],
            record["patient_id"],
            record["date_token"],
            record["pdf_file"],
        ))
        return records

    def _refresh_lab_record_list(self, preserve_key=None):
        type_values = list(LAB_VALIDATE_TYPES)
        current_type = self.lab_type_var.get().strip() or LAB_VALIDATE_TYPES[0]
        if hasattr(self, "lab_type_box"):
            self.lab_type_box.configure(values=type_values)
        if current_type not in type_values:
            current_type = LAB_VALIDATE_TYPES[0]
            self.lab_type_var.set(current_type)

        if current_type == LAB_VALIDATE_TYPES[0]:
            self.filtered_lab_records = list(self.lab_records)
        else:
            self.filtered_lab_records = [
                record for record in self.lab_records
                if record["record_type"] == current_type
            ]

        self.folder_listbox.delete(0, "end")
        for idx, record in enumerate(self.filtered_lab_records):
            prefix = "  âœ“ " if record["status"] == "validated" else "  "
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

    def _load_lab_records(self, preserve_key=None):
        self.lab_records = self._scan_lab_records()
        self._refresh_lab_record_list(preserve_key=preserve_key)

        if self.lab_root_dir_error:
            self.review_status.set(self.lab_root_dir_error, "error")
            return

        validated_count = sum(1 for record in self.lab_records if record["status"] == "validated")
        processing_count = len(self.lab_processing_roots)
        if not processing_count:
            self.review_status.set(
                f"Khong tim thay thu muc PROCESSING duoi {self.root_dir}. "
                "Hay kiem tra lai SFTP_PATH hoac cau truc thu muc study.",
                "error",
            )
            return
        self.review_status.set(
            f"Tim thay {len(self.lab_records)} ho so {OCR_VALIDATE_TYPE} trong {processing_count} "
            f"thu muc PROCESSING, {validated_count} ho so da validated",
            "info",
        )

    def _on_lab_type_changed(self, event=None):
        self._refresh_lab_record_list()

    def _on_lab_record_selected(self):
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

        try:
            self.current_csv_fieldnames, self.current_csv_rows = self._read_csv_payload(
                record["image_path"], record["active_csv_file"]
            )
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c CSV: {e}", "error")
            self.current_csv_fieldnames, self.current_csv_rows = [], []
            return

        self._display_media(record["image_path"], [record["pdf_file"]])
        self._load_form_data(record["image_path"], record["active_json_file"])

        status_text = "validated" if record["status"] == "validated" else "pending"
        self.review_status.set(
            f"{record['record_type']} | {record['study_id']} | {record['patient_id']} | "
            f"{record['date_token']} | {status_text}"
            f" | PDF: {record['pdf_file']} | JSON: {record['active_json_file']} | CSV: {record['active_csv_file']}",
            "success" if record["status"] == "validated" else "info",
        )

    def _build_lab_validated_payload(self):
        confirmed = {
            key: value for key, value in self.current_json_data.items()
            if key != "results"
        }
        for key in self.form_vars:
            value = self.form_vars[key].get()
            confirmed[key] = value if value else None

        confirmed["results"] = []
        for rv in self.result_vars:
            row = {}
            has_data = False
            for key, var in rv.items():
                if key == "_frame":
                    continue
                value = var.get()
                row[key] = value if value else None
                if value:
                    has_data = True
            if has_data:
                confirmed["results"].append(row)

        return confirmed

    def _submit_lab_validation(self):
        if not self.current_lab_record or not self.current_json_data:
            self.review_status.set("Vui lÃ²ng chá»n há»“ sÆ¡ trÆ°á»›c", "error")
            return

        confirmed = self._build_lab_validated_payload()
        record = self.current_lab_record
        validated_json_name = record["base_stem"] + "_validated.json"
        validated_csv_name = record["base_stem"] + "_validated.csv"

        try:
            self._write_json_payload(record["image_path"], validated_json_name, confirmed)
            csv_rows = self._build_lab_rows(record, confirmed)
            self._write_csv_payload(record["image_path"], validated_csv_name, csv_rows)
            self.current_csv_fieldnames, self.current_csv_rows = self._read_csv_payload(
                record["image_path"], validated_csv_name
            )
        except Exception as e:
            self.review_status.set(f"Lá»—i lÆ°u validated: {e}", "error")
            return

        self.current_json_file = validated_json_name
        self.current_csv_file = validated_csv_name
        self.current_json_data = confirmed

        self.lab_type_var.set(record["record_type"])
        self._load_lab_records(preserve_key=record["record_key"])
        self.review_status.set(
            f"ÄÃ£ validated JSON + CSV cho {record['study_id']} / {record['patient_id']} / "
            f"{record['date_token']} / {record['record_type']}",
            "success",
        )

    def _export_lab_excel(self):
        selected_type = self.lab_type_var.get().strip() or LAB_VALIDATE_TYPES[0]
        if selected_type == LAB_VALIDATE_TYPES[0]:
            messagebox.showwarning("Chá»n loáº¡i", "Vui lÃ²ng chá»n 1 loáº¡i cá»¥ thá»ƒ Ä‘á»ƒ export.")
            return

        records = [
            record for record in self.lab_records
            if record["record_type"] == selected_type and record["status"] == "validated"
        ]
        if not records:
            messagebox.showwarning("KhÃ´ng cÃ³ dá»¯ liá»‡u", f"ChÆ°a cÃ³ há»“ sÆ¡ validated cho loáº¡i {selected_type}.")
            return

        safe_type = re.sub(r"[^A-Za-z0-9._-]+", "_", selected_type).strip("_") or "type"
        output_path = filedialog.asksaveasfilename(
            title="LÆ°u file Excel", defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"OCR_VILIDATE_{safe_type}.xlsx",
        )
        if not output_path:
            return

        rows = []
        rename_pairs = []
        for record in records:
            validated_csv = record.get("csv_validated")
            validated_json = record.get("json_validated")
            if not validated_csv or not validated_json:
                continue

            try:
                _, csv_rows = self._read_csv_payload(record["image_path"], validated_csv)
            except Exception as e:
                self.review_status.set(f"Lá»—i Ä‘á»c CSV validated: {e}", "error")
                return

            rows.extend(csv_rows)
            rename_pairs.append((
                self._join_data_path(record["image_path"], validated_json),
                self._join_data_path(record["image_path"], record["base_stem"] + "_done.json"),
            ))
            rename_pairs.append((
                self._join_data_path(record["image_path"], validated_csv),
                self._join_data_path(record["image_path"], record["base_stem"] + "_done.csv"),
            ))

        if not rows:
            messagebox.showwarning("KhÃ´ng cÃ³ dá»¯ liá»‡u", f"KhÃ´ng Ä‘á»c Ä‘Æ°á»£c CSV validated cho loáº¡i {selected_type}.")
            return

        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            sheet_name = re.sub(r"[^A-Za-z0-9 ]+", "_", selected_type).strip() or "OCR_LAB"
            ws.title = sheet_name[:31]
            columns = list(dict.fromkeys(key for row in rows for key in row.keys()))
            ws.append(columns)
            for row in rows:
                ws.append([row.get(column, "") for column in columns])
            wb.save(output_path)
        except Exception as e:
            self.review_status.set(f"Lá»—i xuáº¥t Excel: {e}", "error")
            return

        rename_errors = []
        for source_path, target_path in rename_pairs:
            try:
                self._rename_data_file(source_path, target_path)
            except Exception as e:
                rename_errors.append(f"{Path(source_path).name}: {e}")

        self._load_lab_records()
        if rename_errors:
            self.review_status.set(
                f"ÄÃ£ export loáº¡i {selected_type}, nhÆ°ng cÃ³ {len(rename_errors)} file khÃ´ng rename Ä‘Æ°á»£c sang done",
                "error",
            )
            return

        self.review_status.set(
            f"ÄÃ£ export {len(rows)} dÃ²ng cho loáº¡i {selected_type} vÃ  chuyá»ƒn file sang tráº¡ng thÃ¡i done",
            "success",
        )
        messagebox.showinfo("ThÃ nh cÃ´ng", f"ÄÃ£ export loáº¡i {selected_type}: {len(rows)} dÃ²ng dá»¯ liá»‡u")

    def _collect_pending_confirmed_exports(self):
        rows = []
        confirmed_files = []

        if not self.root_dir:
            return rows, confirmed_files

        if SFTP_DEMO_MODE:
            folder_names = sorted(os.listdir(self.root_dir))
            for folder_name in folder_names:
                folder_path = os.path.join(self.root_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                files = os.listdir(folder_path)
                if any(f.endswith("_final.json") for f in files):
                    continue
                confirmed_file = next((f for f in sorted(files) if f.endswith("_confirmed.json")), None)
                if not confirmed_file:
                    continue

                data = self._read_json_payload(folder_path, confirmed_file)
                rows.extend(self._confirmed_to_rows(folder_name, data))
                base_name = self._normalize_json_stem(confirmed_file)
                confirmed_path = os.path.join(folder_path, confirmed_file)
                final_path = os.path.join(folder_path, base_name + "_final.json")
                confirmed_files.append((confirmed_path, final_path))
            return rows, confirmed_files

        import stat as st_mod

        for folder_name in sorted(self.sftp.listdir(self.root_dir)):
            folder_path = self.root_dir.rstrip("/") + "/" + folder_name
            if not st_mod.S_ISDIR(self.sftp.stat(folder_path).st_mode):
                continue

            files = self.sftp.listdir(folder_path)
            if any(f.endswith("_final.json") for f in files):
                continue
            confirmed_file = next((f for f in sorted(files) if f.endswith("_confirmed.json")), None)
            if not confirmed_file:
                continue

            data = self._read_json_payload(folder_path, confirmed_file)
            rows.extend(self._confirmed_to_rows(folder_name, data))
            base_name = self._normalize_json_stem(confirmed_file)
            confirmed_path = folder_path.rstrip("/") + "/" + confirmed_file
            final_path = folder_path.rstrip("/") + "/" + base_name + "_final.json"
            confirmed_files.append((confirmed_path, final_path))

        return rows, confirmed_files

    # ===================== FOLDER LIST =====================

    def _load_folders(self):
        if self._is_validate_mode():
            self._load_lab_records()
            return

        folders = []
        try:
            if SFTP_DEMO_MODE:
                if not self.root_dir or not os.path.isdir(self.root_dir):
                    self.review_status.set("ThÆ° má»¥c khÃ´ng há»£p lá»‡", "error")
                    return
                for name in sorted(os.listdir(self.root_dir)):
                    full = os.path.join(self.root_dir, name)
                    if os.path.isdir(full):
                        has_final = any(f.endswith("_final.json") for f in os.listdir(full))
                        if not has_final:
                            folders.append(name)
            else:
                import stat as st_mod
                for name in sorted(self.sftp.listdir(self.root_dir)):
                    full = self.root_dir.rstrip("/") + "/" + name
                    try:
                        if st_mod.S_ISDIR(self.sftp.stat(full).st_mode):
                            files = self.sftp.listdir(full)
                            has_final = any(f.endswith("_final.json") for f in files)
                            if not has_final:
                                folders.append(name)
                    except Exception:
                        pass
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c thÆ° má»¥c: {e}", "error")
            return

        self.folders = folders
        try:
            self.all_confirmed, self.confirmed_files = self._collect_pending_confirmed_exports()
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c file xÃ¡c nháº­n: {e}", "error")
            return

        self.folder_listbox.delete(0, "end")
        for f in folders:
            self.folder_listbox.insert("end", "  " + f)
        pending_exports = len(self.confirmed_files)
        self.review_status.set(
            f"TÃ¬m tháº¥y {len(folders)} folder chÆ°a hoÃ n thÃ nh, {pending_exports} folder Ä‘Ã£ xÃ¡c nháº­n chá» export",
            "info",
        )

    def _on_folder_selected(self, event):
        if self._is_validate_mode():
            self._on_lab_record_selected()
            return

        sel = self.folder_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if self.folder_listbox.get(idx).startswith("  âœ“"):
            return
        folder_name = self.folders[idx]
        if SFTP_DEMO_MODE:
            folder_path = os.path.join(self.root_dir, folder_name)
        else:
            folder_path = self.root_dir.rstrip("/") + "/" + folder_name

        self.current_folder_name = folder_name
        self.current_folder_path = folder_path

        try:
            if SFTP_DEMO_MODE:
                files = os.listdir(folder_path)
            else:
                files = self.sftp.listdir(folder_path)
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c folder: {e}", "error")
            return

        json_file = None
        confirmed_json_file = None
        raw_json_file = None
        media_files = []
        is_monitor = (self.ocr_type == "OCR BEDSIDE MONITOR")
        img_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".dcm"}

        for f in files:
            suffix = Path(f).suffix.lower()
            if suffix == ".json":
                if f.endswith("_confirmed.json") and not confirmed_json_file:
                    confirmed_json_file = f
                elif not f.endswith("_final.json") and not raw_json_file:
                    raw_json_file = f
            if is_monitor:
                if not media_files and suffix in img_exts:
                    media_files.append(f)
            else:
                if suffix == ".pdf" or suffix in img_exts:
                    media_files.append(f)

        json_file = confirmed_json_file or raw_json_file
        self._display_media(folder_path, media_files)
        self._load_form_data(folder_path, json_file)
        self.review_status.set(f"Folder: {folder_name}", "info")

    # ===================== MEDIA VIEWER =====================

    def _display_media(self, folder_path, media_files):
        for w in self.viewer_frame.winfo_children():
            w.destroy()
        self._photo_ref = None
        self._photo_refs = []
        self._pdf_photo_refs = []
        if not media_files:
            tk.Label(self.viewer_frame, text="KhÃ´ng tÃ¬m tháº¥y file hiá»ƒn thá»‹",
                     font=("Helvetica", 12), bg=BG_CARD, fg=FG_DIM).pack(expand=True)
            return

        local_paths = []
        for mf in media_files:
            if SFTP_DEMO_MODE:
                local_paths.append((os.path.join(folder_path, mf), mf))
            else:
                import tempfile
                fd, lp = tempfile.mkstemp(suffix=Path(mf).suffix)
                os.close(fd)
                self.sftp.get(folder_path.rstrip("/") + "/" + mf, lp)
                local_paths.append((lp, mf))

        self.viewer_frame.after_idle(lambda: self._render_media(local_paths))

    def _render_media(self, local_paths):
        try:
            from PIL import Image, ImageTk
            self.viewer_frame.update_idletasks()
            max_w = max(self.viewer_canvas.winfo_width() - 30, 300)

            if self.ocr_type == "OCR BEDSIDE MONITOR":
                local_path, media_file = local_paths[0]
                ext = Path(media_file).suffix.lower()
                if ext == ".dcm":
                    img = load_image(local_path)
                else:
                    img = Image.open(local_path)
                max_h = max(self.viewer_canvas.winfo_height() - 30, 300)
                img.thumbnail((max_w, max_h), Image.LANCZOS)
                self._photo_ref = ImageTk.PhotoImage(img)
                tk.Label(self.viewer_frame, image=self._photo_ref, bg=BG_CARD).pack(expand=True)
            else:
                img_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".dcm"}
                for local_path, media_file in local_paths:
                    ext = Path(media_file).suffix.lower()
                    if ext == ".pdf":
                        self._display_pdf(local_path, media_file)
                    elif ext in img_exts:
                        self._display_image(local_path, media_file, max_w)
        except Exception as e:
            tk.Label(self.viewer_frame, text=f"Lá»—i hiá»ƒn thá»‹: {e}",
                     font=("Helvetica", 11), bg=BG_CARD, fg=ACCENT_RED).pack(expand=True)

    def _display_image(self, local_path, media_file, max_w):
        try:
            from PIL import Image, ImageTk
            ext = Path(media_file).suffix.lower()
            if ext == ".dcm":
                img = load_image(local_path)
            else:
                img = Image.open(local_path)
            img.thumbnail((max_w, 2000), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_refs.append(photo)
            tk.Label(self.viewer_frame, text=Path(media_file).name,
                     font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM).pack(pady=(8, 2))
            tk.Label(self.viewer_frame, image=photo, bg=BG_CARD).pack(pady=(0, 4))
        except Exception as e:
            tk.Label(self.viewer_frame, text=f"Lá»—i áº£nh {media_file}: {e}",
                     font=("Helvetica", 11), bg=BG_CARD, fg=ACCENT_RED).pack(pady=4)

    def _display_pdf(self, local_path, media_file):
        try:
            import pypdfium2 as pdfium
            from PIL import Image, ImageTk
            pdf = pdfium.PdfDocument(local_path)
            self.viewer_frame.update_idletasks()
            max_w = max(self.viewer_canvas.winfo_width() - 30, 400)
            self._pdf_photo_refs = []
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                pw, ph = page.get_size()
                scale = max(max_w / pw, 1.0)
                scale = min(scale, 3.0)
                bitmap = page.render(scale=scale)
                img = bitmap.to_pil()
                photo = ImageTk.PhotoImage(img)
                self._pdf_photo_refs.append(photo)
                tk.Label(self.viewer_frame, image=photo, bg=BG_CARD).pack(pady=(0, 4))
            pdf.close()
        except ImportError:
            tk.Label(self.viewer_frame,
                     text=f"File: {media_file}\n\nCáº§n cÃ i pypdfium2:\npip install pypdfium2",
                     font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM, justify="center").pack(expand=True)

            def _open_ext():
                import subprocess
                if platform.system() == "Windows":
                    os.startfile(local_path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", local_path])
                else:
                    subprocess.Popen(["xdg-open", local_path])

            open_btn = tk.Label(self.viewer_frame, text="  Má»Ÿ file PDF  ",
                                font=("Helvetica", 11, "bold"), bg=ACCENT_BLUE, fg="#ffffff",
                                cursor="hand2", padx=10, pady=6)
            open_btn.pack(pady=10)
            open_btn.bind("<Button-1>", lambda e: _open_ext())

    # ===================== FORM DATA =====================

    def _load_form_data(self, folder_path, json_file):
        for w in self.form_inner.winfo_children():
            w.destroy()
        self.form_vars = {}
        self.result_vars = []

        if not json_file:
            tk.Label(self.form_inner, text="KhÃ´ng tÃ¬m tháº¥y file JSON",
                     font=("Helvetica", 11), bg=BG_CARD, fg=FG_DIM).pack(pady=20)
            return

        try:
            data = self._read_json_payload(folder_path, json_file)
        except Exception as e:
            tk.Label(self.form_inner, text=f"Lá»—i Ä‘á»c JSON: {e}",
                     font=("Helvetica", 11), bg=BG_CARD, fg=ACCENT_RED).pack(pady=20)
            return

        self.current_json_file = json_file
        self.current_json_data = data

        if self.ocr_type == "OCR BEDSIDE MONITOR":
            self._build_monitor_form(data)
        else:
            self._build_lab_form(data)

    def _build_monitor_form(self, data):
        for key, val_obj in data.items():
            row = tk.Frame(self.form_inner, bg=BG_CARD)
            row.pack(fill="x", padx=8, pady=3)

            tk.Label(row, text=key.upper(), font=("Helvetica", 11, "bold"),
                     bg=BG_CARD, fg=FG_TEXT, width=12, anchor="e").pack(side="left", padx=(0, 8))

            if isinstance(val_obj, dict):
                value = str(val_obj.get("value", ""))
            elif isinstance(val_obj, list) and val_obj:
                value = str(val_obj[0].get("value", ""))
            else:
                value = str(val_obj) if val_obj else ""

            var = tk.StringVar(value=value)
            self.form_vars[key] = var
            tk.Entry(row, textvariable=var, font=("Helvetica", 12),
                     bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                     borderwidth=0, highlightthickness=1,
                     highlightcolor=ACCENT_BLUE).pack(side="left", fill="x", expand=True, ipady=4)

    def _build_lab_form(self, data):
        extraction_status = data.get("extraction_status")
        notification = data.get("notification")
        error_info = data.get("error")
        results = data.get("results", [])
        is_error = extraction_status == "failed"
        is_warning = notification is not None and not is_error
        is_blank = is_error or (not results)

        # Error / Warning banner
        if is_error and notification:
            banner = tk.Frame(self.form_inner, bg="#fef2f2")
            banner.pack(fill="x", padx=8, pady=(8, 4))
            tk.Label(banner, text="âœ—  " + notification.get("type", "error").upper().replace("_", " "),
                     font=("Helvetica", 12, "bold"), bg="#fef2f2", fg=ACCENT_RED,
                     anchor="w").pack(fill="x", padx=10, pady=(6, 0))
            tk.Label(banner, text=notification.get("message", ""),
                     font=("Helvetica", 11), bg="#fef2f2", fg="#7f1d1d",
                     anchor="w", wraplength=500, justify="left").pack(fill="x", padx=10, pady=(2, 6))
            if error_info and error_info.get("details", {}).get("recommendation"):
                tk.Label(banner, text="ðŸ’¡ " + error_info["details"]["recommendation"],
                         font=("Helvetica", 10, "italic"), bg="#fef2f2", fg="#92400e",
                         anchor="w", wraplength=500, justify="left").pack(fill="x", padx=10, pady=(0, 6))
        elif is_warning and notification:
            warn_bg = "#fffbeb" if notification.get("type") != "partial_extraction" else "#fff7ed"
            banner = tk.Frame(self.form_inner, bg=warn_bg)
            banner.pack(fill="x", padx=8, pady=(8, 4))
            tk.Label(banner, text="âš   " + notification.get("type", "warning").upper().replace("_", " "),
                     font=("Helvetica", 12, "bold"), bg=warn_bg, fg=ACCENT_ORANGE,
                     anchor="w").pack(fill="x", padx=10, pady=(6, 0))
            tk.Label(banner, text=notification.get("message", ""),
                     font=("Helvetica", 11), bg=warn_bg, fg="#78350f",
                     anchor="w", wraplength=500, justify="left").pack(fill="x", padx=10, pady=(2, 6))

        # Metadata
        provider = data.get("provider")
        model = data.get("model")
        source = data.get("source")
        if provider or model:
            meta_frame = tk.Frame(self.form_inner, bg="#f0f9ff")
            meta_frame.pack(fill="x", padx=8, pady=(4, 4))
            parts = []
            if provider:
                parts.append(provider)
            if model and model not in (provider or ""):
                parts.append(f"model: {model}")
            if source:
                parts.append(f"({source})")
            tk.Label(meta_frame, text="â„¹  " + "  |  ".join(parts),
                     font=("Helvetica", 10), bg="#f0f9ff", fg="#1e40af",
                     anchor="w").pack(fill="x", padx=10, pady=4)

        # Blank-form hint
        if is_blank:
            hint_bg = "#f0fdf4" if is_error else "#fefce8"
            hint_fg = ACCENT_GREEN if is_error else "#854d0e"
            hint = tk.Frame(self.form_inner, bg=hint_bg)
            hint.pack(fill="x", padx=8, pady=(4, 8))
            hint_text = ("Káº¿t quáº£ trÃ­ch xuáº¥t bá»‹ lá»—i / trá»‘ng. "
                         "Báº¡n cÃ³ thá»ƒ nháº­p thá»§ cÃ´ng bÃªn dÆ°á»›i.")
            tk.Label(hint, text="âœŽ  " + hint_text,
                     font=("Helvetica", 11), bg=hint_bg, fg=hint_fg,
                     anchor="w", wraplength=500, justify="left").pack(fill="x", padx=10, pady=6)

        # Patient info fields
        info_keys = ["patient_name", "patient_dob", "patient_id",
                     "collection_date", "lab_name", "report_type"]

        tk.Label(self.form_inner, text="ThÃ´ng tin bá»‡nh nhÃ¢n",
                 font=("Helvetica", 13, "bold"), bg=BG_CARD, fg=FG_TITLE
                 ).pack(anchor="w", padx=10, pady=(8, 5))

        for key in info_keys:
            row = tk.Frame(self.form_inner, bg=BG_CARD)
            row.pack(fill="x", padx=10, pady=3)
            label = key.replace("_", " ").title()
            tk.Label(row, text=label, font=("Helvetica", 12), bg=BG_CARD, fg=FG_DIM,
                     width=16, anchor="e").pack(side="left", padx=(0, 8))
            var = tk.StringVar(value=str(data.get(key) or ""))
            self.form_vars[key] = var
            tk.Entry(row, textvariable=var, font=("Helvetica", 12),
                     bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                     borderwidth=0, highlightthickness=1,
                     highlightcolor=ACCENT_BLUE).pack(side="left", fill="x", expand=True, ipady=5)

        extra_keys = [
            key for key in data.keys()
            if key not in {
                *info_keys,
                "results", "raw_text",
                "provider", "model", "source",
                "notification", "error", "extraction_status",
            }
            and not isinstance(data.get(key), (dict, list))
        ]
        if extra_keys:
            tk.Label(self.form_inner, text="ThÃ´ng tin theo loáº¡i",
                     font=("Helvetica", 13, "bold"), bg=BG_CARD, fg=FG_TITLE
                     ).pack(anchor="w", padx=10, pady=(10, 5))

            for key in extra_keys:
                row = tk.Frame(self.form_inner, bg=BG_CARD)
                row.pack(fill="x", padx=10, pady=3)
                label = key.replace("_", " ").title()
                tk.Label(row, text=label, font=("Helvetica", 12), bg=BG_CARD, fg=FG_DIM,
                         width=16, anchor="e").pack(side="left", padx=(0, 8))
                var = tk.StringVar(value=str(data.get(key) or ""))
                self.form_vars[key] = var
                tk.Entry(row, textvariable=var, font=("Helvetica", 12),
                         bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                         borderwidth=0, highlightthickness=1,
                         highlightcolor=ACCENT_BLUE).pack(side="left", fill="x", expand=True, ipady=5)

        tk.Frame(self.form_inner, bg=BORDER_COLOR, height=1).pack(fill="x", padx=10, pady=10)

        # Results section
        result_hdr = tk.Frame(self.form_inner, bg=BG_CARD)
        result_hdr.pack(fill="x", padx=10, pady=(5, 5))

        self._result_count_lbl = tk.Label(
            result_hdr, text=f"Káº¿t quáº£ ({len(results)} má»¥c)",
            font=("Helvetica", 13, "bold"), bg=BG_CARD, fg=FG_TITLE)
        self._result_count_lbl.pack(side="left")

        rm_btn = tk.Label(result_hdr, text="  âˆ’ XÃ³a dÃ²ng  ", font=("Helvetica", 10, "bold"),
                          bg=ACCENT_RED, fg="#ffffff", cursor="hand2", padx=4, pady=2)
        rm_btn.pack(side="right", padx=(4, 0))
        rm_btn.bind("<Button-1>", lambda e: self._remove_result_row())
        rm_btn.bind("<Enter>", lambda e: rm_btn.config(bg="#b91c1c"))
        rm_btn.bind("<Leave>", lambda e: rm_btn.config(bg=ACCENT_RED))

        add_btn = tk.Label(result_hdr, text="  + ThÃªm dÃ²ng  ", font=("Helvetica", 10, "bold"),
                           bg=ACCENT_GREEN, fg="#ffffff", cursor="hand2", padx=4, pady=2)
        add_btn.pack(side="right", padx=(4, 0))
        add_btn.bind("<Button-1>", lambda e: self._add_result_row())
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg="#15803d"))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=ACCENT_GREEN))

        # Table header
        hdr = tk.Frame(self.form_inner, bg=BG_CARD)
        hdr.pack(fill="x", padx=10, pady=(0, 3))
        for col_text, col_w in [("TÃªn xÃ©t nghiá»‡m", 0), ("GiÃ¡ trá»‹", 10),
                                 ("ÄÆ¡n vá»‹", 8), ("Ref", 6), ("Flag", 5)]:
            if col_w == 0:
                tk.Label(hdr, text=col_text, font=("Helvetica", 10, "bold"),
                         bg=BG_CARD, fg=FG_DIM).pack(side="left", fill="x", expand=True, anchor="w")
            else:
                tk.Label(hdr, text=col_text, font=("Helvetica", 10, "bold"),
                         bg=BG_CARD, fg=FG_DIM, width=col_w).pack(side="left", padx=2)

        self._results_container = tk.Frame(self.form_inner, bg=BG_CARD)
        self._results_container.pack(fill="x", padx=10)

        if results:
            for result in results:
                self._add_result_row(result)
        elif is_blank:
            for _ in range(3):
                self._add_result_row()

    # ===================== RESULT ROWS =====================

    def _add_result_row(self, result=None):
        i = len(self.result_vars)
        bg = BG_INPUT if i % 2 == 0 else "#e8e8e8"
        rf = tk.Frame(self._results_container, bg=bg)
        rf.pack(fill="x", pady=1)
        row_vars = {}
        row_vars["_frame"] = rf

        var_name = tk.StringVar(value=str((result or {}).get("test_name") or ""))
        row_vars["test_name"] = var_name
        tk.Entry(rf, textvariable=var_name, font=("Helvetica", 11),
                 bg=bg, fg=FG_TEXT, borderwidth=0, highlightthickness=0,
                 readonlybackground=bg).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 2))

        for col_key, col_w in [("value", 10), ("unit", 8),
                                ("reference_range", 6), ("flag", 5)]:
            var = tk.StringVar(value=str((result or {}).get(col_key) or ""))
            row_vars[col_key] = var
            tk.Entry(rf, textvariable=var, font=("Helvetica", 11), width=col_w,
                     bg="#ffffff", fg=FG_TEXT, insertbackground=FG_TEXT,
                     borderwidth=1, relief="solid",
                     highlightthickness=0).pack(side="left", ipady=4, padx=2)

        self.result_vars.append(row_vars)
        self._update_result_count()

    def _remove_result_row(self):
        if not self.result_vars:
            return
        row = self.result_vars.pop()
        frame = row.get("_frame")
        if frame:
            frame.destroy()
        self._update_result_count()

    def _update_result_count(self):
        if hasattr(self, "_result_count_lbl"):
            n = len(self.result_vars)
            self._result_count_lbl.config(text=f"Káº¿t quáº£ ({n} má»¥c)")

    # ===================== SUBMIT =====================

    def _submit(self):
        if self._is_validate_mode():
            self._submit_lab_validation()
            return

        if not self.current_json_data or not self.current_folder_path:
            self.review_status.set("Vui lÃ²ng chá»n folder trÆ°á»›c", "error")
            return

        if self.ocr_type == "OCR BEDSIDE MONITOR":
            confirmed = {}
            for key in self.current_json_data:
                orig = self.current_json_data[key]
                if key in self.form_vars:
                    raw = self.form_vars[key].get()
                    try:
                        new_val = float(raw)
                        if new_val == int(new_val):
                            new_val = int(new_val)
                    except (ValueError, OverflowError):
                        new_val = raw
                    if isinstance(orig, dict):
                        confirmed[key] = {**orig, "value": new_val}
                    elif isinstance(orig, list):
                        confirmed[key] = [{**(orig[0] if orig else {}), "value": new_val}]
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
                row = {}
                has_data = False
                for k, v in rv.items():
                    if k == "_frame":
                        continue
                    val = v.get()
                    row[k] = val if val else None
                    if val:
                        has_data = True
                if has_data:
                    confirmed["results"].append(row)
            if "raw_text" in self.current_json_data:
                confirmed["raw_text"] = self.current_json_data["raw_text"]

        base_name = self._normalize_json_stem(self.current_json_file)
        confirmed_name = base_name + "_confirmed.json"

        try:
            if SFTP_DEMO_MODE:
                out_path = os.path.join(self.current_folder_path, confirmed_name)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(confirmed, f, ensure_ascii=False, indent=2)
            else:
                out_path = self.current_folder_path.rstrip("/") + "/" + confirmed_name
                with self.sftp.open(out_path, "w") as f:
                    f.write(json.dumps(confirmed, ensure_ascii=False, indent=2).encode("utf-8"))
        except Exception as e:
            self.review_status.set(f"Lá»—i lÆ°u: {e}", "error")
            return

        final_name = base_name + "_final.json"
        if SFTP_DEMO_MODE:
            final_path = os.path.join(self.current_folder_path, final_name)
        else:
            final_path = self.current_folder_path.rstrip("/") + "/" + final_name
        self.current_json_file = confirmed_name
        self.current_json_data = confirmed
        self.confirmed_files = [item for item in self.confirmed_files if item[0] != out_path]
        self.confirmed_files.append((out_path, final_path))
        try:
            self.all_confirmed, self.confirmed_files = self._collect_pending_confirmed_exports()
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c file xÃ¡c nháº­n: {e}", "error")
            return

        # Mark current folder done & auto-advance
        cur_idx = None
        sel = self.folder_listbox.curselection()
        if sel:
            cur_idx = sel[0]
            self.folder_listbox.delete(cur_idx)
            self.folder_listbox.insert(cur_idx, "  âœ“ " + self.current_folder_name)
            self.folder_listbox.itemconfig(cur_idx, fg=ACCENT_GREEN)
        confirmed_count = sum(1 for i in range(self.folder_listbox.size())
                              if self.folder_listbox.get(i).startswith("  âœ“"))
        total = self.folder_listbox.size()
        self.review_status.set(
            f"ÄÃ£ lÆ°u: {confirmed_name}  â€”  {confirmed_count}/{total} folder hoÃ n thÃ nh", "success")

        if cur_idx is not None and cur_idx + 1 < total:
            next_idx = cur_idx + 1
            while next_idx < total and self.folder_listbox.get(next_idx).startswith("  âœ“"):
                next_idx += 1
            if next_idx < total:
                self.folder_listbox.selection_clear(0, "end")
                self.folder_listbox.selection_set(next_idx)
                self.folder_listbox.see(next_idx)
                self.folder_listbox.event_generate("<<ListboxSelect>>")

    # ===================== EXPORT EXCEL =====================

    def _export_excel(self):
        if self._is_validate_mode():
            self._export_lab_excel()
            return

        try:
            rows, confirmed_files = self._collect_pending_confirmed_exports()
        except Exception as e:
            self.review_status.set(f"Lá»—i Ä‘á»c file xÃ¡c nháº­n: {e}", "error")
            return

        if not confirmed_files:
            messagebox.showwarning("KhÃ´ng cÃ³ dá»¯ liá»‡u", "ChÆ°a cÃ³ folder nÃ o Ä‘Æ°á»£c xÃ¡c nháº­n.")
            return

        output_path = filedialog.asksaveasfilename(
            title="LÆ°u file Excel", defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"OCR_{self.ocr_type.replace(' ', '_')}.xlsx")
        if not output_path:
            return

        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            if rows:
                columns = list(dict.fromkeys(k for r in rows for k in r))
                ws.append(columns)
                for row_data in rows:
                    ws.append([row_data.get(c, "") for c in columns])
            wb.save(output_path)
            row_count = len(rows)

            for cp, fp in confirmed_files:
                try:
                    if SFTP_DEMO_MODE:
                        if os.path.exists(cp):
                            os.rename(cp, fp)
                    else:
                        self.sftp.rename(cp, fp)
                except Exception:
                    pass

            cnt = len(confirmed_files)
            self.confirmed_files.clear()
            self.all_confirmed.clear()
            self._load_folders()
            self.review_status.set(f"ÄÃ£ xuáº¥t {row_count} dÃ²ng, {cnt} folder hoÃ n thÃ nh", "success")
            messagebox.showinfo("ThÃ nh cÃ´ng", f"ÄÃ£ xuáº¥t {row_count} dÃ²ng dá»¯ liá»‡u")
        except Exception as e:
            self.review_status.set(f"Lá»—i xuáº¥t Excel: {e}", "error")

