"""Trang xử lý XML → Excel."""

import os
import threading
import tkinter as tk
from tkinter import filedialog

from apps.config import (
    APP_DIR, BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_RED,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_RED,
)
from apps.widgets import (
    StyledButton, StatusBar, make_header, make_section,
    ScrollableFrame, show_info, show_warning, show_error,
)
from apps.processing.xml_to_excel import run_xml_to_excel


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

        self.file_listbox = tk.Listbox(s1, height=4, font=("Courier", 11),
                                       bg=BG_INPUT, fg=FG_TEXT, selectbackground=ACCENT_BLUE,
                                       borderwidth=0, highlightthickness=0)
        self.file_listbox.pack(fill="x", padx=15, pady=(5, 12))

        # === Section 2: File mapping (tuỳ chọn) ===
        s2 = make_section(body, "BƯỚC 2 — File Excel mapping (tuỳ chọn)")

        tk.Label(
            s2,
            text=("Gắn thêm cột vào kết quả. Dòng 1 là tiêu đề; ô A1 phải là tên "
                  "trường trong hồ sơ XML4\ndùng để ghép (ví dụ MA_DICH_VU), các "
                  "cột còn lại sẽ được thêm vào file Excel xuất ra."),
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
        self.status.set("Đang xử lý...", "working")

        def on_done(success, msg):
            self.controller.after(0, lambda: self._finish(success, msg))

        threading.Thread(
            target=run_xml_to_excel,
            args=(self.xml_files, output, on_done, self.mapping_path),
            daemon=True,
        ).start()

    def _finish(self, success, msg):
        self.run_btn.set_state("normal")
        if success:
            self.status.set(msg, "success")
            show_info(self, "Thành công", msg)
        else:
            self.status.set(msg, "error")
            show_error(self, "Lỗi", msg)
