"""Trang xử lý XML → Excel."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from apps.config import (
    APP_DIR, BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_RED,ACCENT_PURPLE,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_RED,BTN_HOVER_PURPLE,
    SFTP_BUFFER_PATH,
)
from apps.widgets import (
    StyledButton, StatusBar, make_header, make_section,
    ScrollableFrame, make_scrollable_listbox, show_info, show_warning, show_error,
    get_sftp_uploader, run_upload_batch,
)
from apps.services.upload_api import UploadJob
from apps.processing.xml_to_excel import run_xml_to_excel
from apps.services import study_mapping


def _flat_button(parent, text, color, hover, command, font_size=11, padx=8, pady=4):
    """Nút phẳng kiểu Label + hover, dùng chung cho các nút nhỏ trên trang này."""

    btn = tk.Label(parent, text=text, font=("Helvetica", font_size, "bold"),
                   bg=color, fg="#ffffff", cursor="hand2", padx=padx, pady=pady)
    btn.bind("<Button-1>", lambda e: command())
    btn.bind("<Enter>", lambda e: btn.config(bg=hover))
    btn.bind("<Leave>", lambda e: btn.config(bg=color))
    return btn


class XMLToExcelPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller
        self.xml_files = []
        self.mapping_path = None
        self._last_output_files = []

        make_header(self, controller, "Xử lý XML → Excel")

        scroll = ScrollableFrame(self, bg=BG_MAIN)
        scroll.pack(fill="both", expand=True)
        body = scroll.interior

        # === Section 1: Chọn file ===
        s1 = make_section(body, "BƯỚC 1 — Chọn file XML đầu vào")

        btn_row = tk.Frame(s1, bg=BG_CARD)
        btn_row.pack(fill="x", padx=15, pady=(0, 5))

        _flat_button(btn_row, "  Chọn file XML...  ", ACCENT_ORANGE, BTN_HOVER_ORANGE,
                     self._pick_files, font_size=12, padx=10, pady=6).pack(side="left")

        self.file_count_lbl = tk.Label(btn_row, text="  Chưa chọn file nào", font=("Helvetica", 11),
                                       bg=BG_CARD, fg=FG_DIM)
        self.file_count_lbl.pack(side="left", padx=10)

        list_frame, self.file_listbox = make_scrollable_listbox(
            s1, frame_bg=BG_CARD, height=4, font=("Courier", 11),
            bg=BG_INPUT, fg=FG_TEXT, selectbackground=ACCENT_BLUE,
            borderwidth=0, highlightthickness=0,
        )
        list_frame.pack(fill="x", padx=15, pady=(5, 12))

        # === Section 2: File mapping (tuỳ chọn) ===
        s2 = make_section(body, "BƯỚC 2 — File Excel mapping (tuỳ chọn)")

        tk.Label(
            s2,
            text=("Dòng 1 là tiêu đề. Chế độ được chọn tự động theo tên cột:\n"
                  "• Có cột USUBJID và EMR_ID → danh sách nghiên cứu: EMR_ID được "
                  "ghép với MA_LK (toàn bộ) hoặc 10 ký tự cuối của ID,\n"
                  "   kết quả xuất ra cột MA_NTG và ẩn ID/MA_LK. Có thêm "
                  "START_DATE/END_DATE thì lọc NGAY_KQ theo khoảng đó (trọn ngày,\n"
                  "   bản ghi ngoài khoảng bị loại hẳn, không xuất ra sheet nào). "
                  "Có thêm sheet Summary tổng hợp theo MA_NTG.\n"
                  "• Không có → mapping thường: ô A1 là tên trường XML4 dùng để "
                  "ghép (ví dụ MA_DICH_VU), các cột còn lại được thêm vào.\n"
                  "• File tên dạng LabRequest_<đuôi>.xlsx sẽ tự gợi ý tên file "
                  "xuất ra là LabResult_<đuôi>.xlsx."),
            font=("Helvetica", 10), bg=BG_CARD, fg=FG_DIM, justify="left",
        ).pack(anchor="w", padx=15, pady=(0, 8))

        map_row = tk.Frame(s2, bg=BG_CARD)
        map_row.pack(fill="x", padx=15, pady=(0, 12))

        _flat_button(map_row, "  Chọn file mapping...  ", ACCENT_BLUE, BTN_HOVER_BLUE,
                     self._pick_mapping).pack(side="left")

        # Chỉ pack khi đã chọn file (xem _pick_mapping / _clear_mapping).
        self.clear_map_btn = _flat_button(
            map_row, "  Bỏ chọn  ", ACCENT_RED, BTN_HOVER_RED, self._clear_mapping)

        self.mapping_lbl = tk.Label(map_row, text="  Không dùng mapping", font=("Helvetica", 11),
                                    bg=BG_CARD, fg=FG_DIM)
        self.mapping_lbl.pack(side="left", padx=10)

        # === Section 3: Output ===
        s3 = make_section(body, "BƯỚC 3 — Chọn nơi lưu file Excel")

        out_row = tk.Frame(s3, bg=BG_CARD)
        out_row.pack(fill="x", padx=15, pady=(0, 12))

        self.output_var = tk.StringVar(value=str(APP_DIR / "KetQua_GiaiMa_XML.xlsx"))
        entry = tk.Entry(out_row, textvariable=self.output_var, font=("Helvetica", 11),
                         bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
                         borderwidth=0, highlightthickness=1, highlightcolor=ACCENT_BLUE)
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        _flat_button(out_row, "  Chọn...  ", ACCENT_BLUE, BTN_HOVER_BLUE,
                     self._pick_output).pack(side="left")

        # === Run Button ===
        run_frame = tk.Frame(body, bg=BG_MAIN)
        run_frame.pack(pady=20)
        self.run_btn = StyledButton(run_frame, text="▶   BẮT ĐẦU XỬ LÝ", command=self._run,
                                    bg_color=ACCENT_GREEN, hover_color=BTN_HOVER_GREEN, font_size=15)
        self.run_btn.pack()

        # self.upload_btn = StyledButton(run_frame, text="▲  UPLOAD", command=self._upload_sftp,
        #                                bg_color=ACCENT_PURPLE, hover_color=BTN_HOVER_PURPLE, font_size=13)
        # self.upload_btn.pack(pady=(10, 0))
        # self.upload_btn.set_state("disabled")

        # === Status ===
        self.status = StatusBar(body)
        self.status.pack(fill="x", padx=25, pady=(0, 10))

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="Chọn file XML",
            filetypes=[("XML files", "*.xml"), ("Tất cả", "*.*")],
        )
        if files:
            self.xml_files = list(files)
            self.file_listbox.delete(0, "end")
            for f in self.xml_files:
                self.file_listbox.insert("end", "  " + os.path.basename(f))
            self.file_count_lbl.config(text=f"  ✓  Đã chọn {len(self.xml_files)} file", fg=ACCENT_GREEN)

    def _pick_mapping(self):
        path = filedialog.askopenfilename(
            title="Chọn file Excel mapping",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Tất cả", "*.*")],
        )
        if path:
            self.mapping_path = path
            self.mapping_lbl.config(text=f"  ✓  {os.path.basename(path)}", fg=ACCENT_GREEN)
            self.clear_map_btn.pack(side="left", padx=(8, 0))
            self._suggest_output_name(path)

    def _suggest_output_name(self, mapping_path):
        """Đổi tên file output theo quy ước LabRequest_<đuôi> -> LabResult_<đuôi>.

        Chỉ đổi PHẦN TÊN FILE, giữ nguyên thư mục đang chọn ở BƯỚC 3 (mặc định
        hoặc do người dùng tự đặt trước đó) — không tự ý đổi luôn nơi lưu.
        Tên file mapping không theo quy ước thì giữ nguyên output hiện tại.
        """

        new_name = study_mapping.derive_output_filename(mapping_path)
        if not new_name:
            return
        current_dir = os.path.dirname(self.output_var.get().strip()) or str(APP_DIR)
        self.output_var.set(os.path.join(current_dir, new_name))

    def _clear_mapping(self):
        self.mapping_path = None
        self.mapping_lbl.config(text="  Không dùng mapping", fg=FG_DIM)
        self.clear_map_btn.pack_forget()

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Lưu file Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if path:
            self.output_var.set(path)

    def _run(self):
        if not self.xml_files:
            show_warning(self, "Thiếu dữ liệu", "Vui lòng chọn ít nhất 1 file XML.")
            return
        output = self.output_var.get().strip()
        if not output:
            show_warning(self, "Thiếu đường dẫn", "Vui lòng chọn nơi lưu file Excel.")
            return

        self.run_btn.set_state("disabled")
        # self.upload_btn.set_state("disabled")
        self.status.set("Đang xử lý...", "working")

        def on_done(success, msg):
            self.controller.after(0, lambda: self._finish(success, msg, output))

        threading.Thread(
            target=run_xml_to_excel,
            args=(self.xml_files, output, on_done, self.mapping_path),
            daemon=True,
        ).start()

    def _finish(self, success, msg, output_path):
        self.run_btn.set_state("normal")
        if success:
            self._last_output_files = [output_path]
            # self.upload_btn.set_state("normal")
            self.status.set(msg, "success")
            show_info(self, "Thành công", msg)
        else:
            self.status.set(msg, "error")
            show_error(self, "Lỗi", msg)

    def _upload_sftp(self):
        if not self._last_output_files:
            show_info(self, "Không có file", "Chưa có file Excel đã xử lý để upload.")
            return
        if not SFTP_BUFFER_PATH:
            show_warning(self, "Thiếu cấu hình", "Chưa cấu hình SFTP_BUFFER_PATH trong .env.")
            return
        if not messagebox.askyesno(
            "Upload", "Upload file Excel đã xử lý lên không gian lưu trữ?"
        ):
            return

        run_upload_batch(
            # self, self.upload_btn, self.status,
            self, None, self.status,
            get_sftp_uploader(self, SFTP_BUFFER_PATH),
            [UploadJob(label="xml", files=self._last_output_files)],
        )
