"""Trang xử lý ảnh X-Quang (Anonymize DICOM)."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from apps.config import (
    APP_DIR, BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_PURPLE,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_PURPLE,
    SFTP_BUFFER_PATH,
)
from apps.widgets import (
    StyledButton, StatusBar, make_header, make_section,
    ScrollableFrame, show_info, show_warning, show_error,
    get_sftp_uploader, run_upload_batch,
)
from apps.services.upload_api import UploadJob
from apps.processing.xray import run_xray_processing, _plan_output_paths


class XRayPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller
        self.image_files = []
        self._pending_output_files = []
        self._last_output_files = []

        make_header(self, controller, "Xử lý ảnh X-Quang (Anonymize DICOM)")

        scroll = ScrollableFrame(self, bg=BG_MAIN)
        scroll.pack(fill="both", expand=True)
        body = scroll.interior

        # === Section 1: Chọn file ===
        s1 = make_section(body, "BƯỚC 1 — Chọn file ảnh (DCM, PNG, JPG...)")

        btn_row = tk.Frame(s1, bg=BG_CARD)
        btn_row.pack(fill="x", padx=15, pady=(0, 5))

        pick_btn = tk.Label(btn_row, text="  Chọn file ảnh...  ", font=("Helvetica", 12, "bold"),
                            bg=ACCENT_ORANGE, fg="#ffffff", cursor="hand2", padx=10, pady=6)
        pick_btn.pack(side="left")
        pick_btn.bind("<Button-1>", lambda e: self._pick_files())
        pick_btn.bind("<Enter>", lambda e: pick_btn.config(bg=BTN_HOVER_ORANGE))
        pick_btn.bind("<Leave>", lambda e: pick_btn.config(bg=ACCENT_ORANGE))

        self.file_count_lbl = tk.Label(btn_row, text="  Chưa chọn file nào", font=("Helvetica", 11),
                                       bg=BG_CARD, fg=FG_DIM)
        self.file_count_lbl.pack(side="left", padx=10)

        self.file_listbox = tk.Listbox(s1, height=4, font=("Courier", 11),
                                       bg=BG_INPUT, fg=FG_TEXT, selectbackground=ACCENT_BLUE,
                                       borderwidth=0, highlightthickness=0)
        self.file_listbox.pack(fill="x", padx=15, pady=(5, 12))

        # === Section 2: Output ===
        s2 = make_section(body, "BƯỚC 2 — Chọn thư mục lưu file đầu ra (DICOM anonymized)")

        out_row = tk.Frame(s2, bg=BG_CARD)
        out_row.pack(fill="x", padx=15, pady=(0, 12))

        self.output_var = tk.StringVar(value=str(APP_DIR / "output_xray"))
        entry = tk.Entry(out_row, textvariable=self.output_var, font=("Helvetica", 11),
                         bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                         borderwidth=0, highlightthickness=1, highlightcolor=ACCENT_BLUE)
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        browse_btn = tk.Label(out_row, text="  Chọn...  ", font=("Helvetica", 11, "bold"),
                              bg=ACCENT_BLUE, fg="#ffffff", cursor="hand2", padx=8, pady=4)
        browse_btn.pack(side="left")
        browse_btn.bind("<Button-1>", lambda e: self._pick_output())
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(bg=BTN_HOVER_BLUE))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(bg=ACCENT_BLUE))

        # === Run Button ===
        run_frame = tk.Frame(body, bg=BG_MAIN)
        run_frame.pack(pady=20)
        self.run_btn = StyledButton(run_frame, text="▶   BẮT ĐẦU XỬ LÝ", command=self._run,
                                    bg_color=ACCENT_GREEN, hover_color=BTN_HOVER_GREEN, font_size=15)
        self.run_btn.pack()

        self.upload_btn = StyledButton(run_frame, text="▲  UPLOAD", command=self._upload_sftp,
                                       bg_color=ACCENT_PURPLE, hover_color=BTN_HOVER_PURPLE, font_size=13)
        self.upload_btn.pack(pady=(10, 0))
        self.upload_btn.set_state("disabled")

        # === Status ===
        self.status = StatusBar(body)
        self.status.pack(fill="x", padx=25, pady=(0, 10))

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="Chọn file ảnh X-Quang",
            filetypes=[
                ("Ảnh & DICOM", "*.dcm *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp"),
                ("Tất cả", "*.*"),
            ],
        )
        if files:
            self.image_files = list(files)
            self.file_listbox.delete(0, "end")
            for f in self.image_files:
                self.file_listbox.insert("end", "  " + os.path.basename(f))
            self.file_count_lbl.config(text=f"  ✓  Đã chọn {len(self.image_files)} file", fg=ACCENT_GREEN)

    def _pick_output(self):
        path = filedialog.askdirectory(title="Chọn thư mục lưu ảnh")
        if path:
            self.output_var.set(path)

    def _run(self):
        if not self.image_files:
            show_warning(self, "Thiếu dữ liệu", "Vui lòng chọn ít nhất 1 file ảnh.")
            return
        output_dir = self.output_var.get().strip()
        if not output_dir:
            show_warning(self, "Thiếu đường dẫn", "Vui lòng chọn thư mục lưu ảnh.")
            return

        os.makedirs(output_dir, exist_ok=True)
        _, output_paths = _plan_output_paths(self.image_files, output_dir)
        self._pending_output_files = list(output_paths.values())

        self.run_btn.set_state("disabled")
        self.upload_btn.set_state("disabled")
        self.status.set("Đang khởi tạo OCR model...", "working")

        def on_update(status_code, msg):
            if status_code == "progress":
                self.controller.after(0, lambda: self.status.set(msg, "working"))
            else:
                self.controller.after(0, lambda: self._finish(status_code, msg))

        threading.Thread(target=run_xray_processing, args=(self.image_files, output_dir, on_update), daemon=True).start()

    def _finish(self, success, msg):
        self.run_btn.set_state("normal")
        if success:
            # Chạy lỗi từng phần (một số ảnh load lỗi) vẫn callback success=True
            # với thông báo "X/Y images" - lọc lại chỉ những file thực sự được
            # ghi ra đĩa, tránh queue upload các đường dẫn chưa từng tồn tại.
            self._last_output_files = [
                p for p in self._pending_output_files if os.path.exists(p)
            ]
            self.upload_btn.set_state("normal")
            self.status.set(msg, "success")
            show_info(self, "Thành công", msg)
        else:
            self.status.set(msg, "error")
            show_error(self, "Lỗi", msg)

    def _upload_sftp(self):
        if not self._last_output_files:
            show_info(self, "Không có file", "Chưa có ảnh đã xử lý để upload.")
            return
        if not SFTP_BUFFER_PATH:
            show_warning(self, "Thiếu cấu hình", "Chưa cấu hình SFTP_BUFFER_PATH trong .env.")
            return
        if not messagebox.askyesno(
            "Upload",
            f"Upload {len(self._last_output_files)} file ảnh đã xử lý lên không gian lưu trữ?",
        ):
            return

        run_upload_batch(
            self, self.upload_btn, self.status,
            get_sftp_uploader(self, SFTP_BUFFER_PATH),
            [UploadJob(label="xray", files=self._last_output_files)],
        )
