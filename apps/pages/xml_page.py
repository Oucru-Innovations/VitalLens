"""Trang xử lý XML → Excel."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from apps.config import (
    APP_DIR, BG_MAIN, BG_CARD, BG_INPUT, FG_TEXT, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN,
)
from apps.widgets import StyledButton, StatusBar, make_header, make_section
from apps.processing.xml_to_excel import run_xml_to_excel


class XMLToExcelPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller
        self.xml_files = []

        make_header(self, controller, "Xử lý XML → Excel")

        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True)

        # === Section 1: Chọn file ===
        s1 = make_section(body, "BƯỚC 1 — Chọn file XML đầu vào")

        btn_row = tk.Frame(s1, bg=BG_CARD)
        btn_row.pack(fill="x", padx=15, pady=(0, 5))

        pick_btn = tk.Label(btn_row, text="  Chọn file XML...  ", font=("Helvetica", 12, "bold"),
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
        s2 = make_section(body, "BƯỚC 2 — Chọn nơi lưu file Excel")

        out_row = tk.Frame(s2, bg=BG_CARD)
        out_row.pack(fill="x", padx=15, pady=(0, 12))

        self.output_var = tk.StringVar(value=str(APP_DIR / "KetQua_GiaiMa_XML.xlsx"))
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
            messagebox.showwarning("Thiếu dữ liệu", "Vui lòng chọn ít nhất 1 file XML.")
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showwarning("Thiếu đường dẫn", "Vui lòng chọn nơi lưu file Excel.")
            return

        self.run_btn.set_state("disabled")
        self.status.set("Đang xử lý...", "working")

        def on_done(success, msg):
            self.controller.after(0, lambda: self._finish(success, msg))

        threading.Thread(target=run_xml_to_excel, args=(self.xml_files, output, on_done), daemon=True).start()

    def _finish(self, success, msg):
        self.run_btn.set_state("normal")
        if success:
            self.status.set(msg, "success")
            messagebox.showinfo("Thành công", msg)
        else:
            self.status.set(msg, "error")
            messagebox.showerror("Lỗi", msg)
