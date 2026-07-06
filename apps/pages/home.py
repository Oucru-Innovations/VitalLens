"""Trang chủ."""

import tkinter as tk
from apps.config import (
    BG_MAIN, BG_CARD, FG_TITLE, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_PURPLE,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_PURPLE,
    BORDER_COLOR,
)


class HomePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=BG_MAIN)
        self.controller = controller

        center = tk.Frame(self, bg=BG_MAIN)
        center.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(center, text="VitalLens", font=("Helvetica", 36, "bold"),
                 bg=BG_MAIN, fg=FG_TITLE).pack(pady=(0, 4))
        tk.Label(center, text="Công cụ hỗ trợ xử lý dữ liệu y tế", font=("Helvetica", 14),
                 bg=BG_MAIN, fg=FG_DIM).pack(pady=(0, 40))

        cards = tk.Frame(center, bg=BG_MAIN)
        cards.pack()

        from apps.pages.xml_page import XMLToExcelPage
        from apps.pages.xray_page import XRayPage
        from apps.pages.ocr import OCRPage
        from apps.pages.upload import UploadPDFPage

        btn_data = [
            ("Xử lý XML → Excel", "Giải mã dữ liệu XML3, XML4 thành file Excel",
             ACCENT_BLUE, BTN_HOVER_BLUE, XMLToExcelPage),
            ("Xử lý ảnh X-Quang", "Xóa text burned-in + anonymize metadata DICOM",
             ACCENT_ORANGE, BTN_HOVER_ORANGE, XRayPage),
            ("Đánh giá kết quả OCR", "So sánh kết quả OCR với dữ liệu gốc",
             ACCENT_GREEN, BTN_HOVER_GREEN, OCRPage),
            ("Upload PDF Xét Nghiệm", "Tô đen, nhập thông tin & lưu PDF + CSV",
             ACCENT_PURPLE, BTN_HOVER_PURPLE, UploadPDFPage),
        ]

        for title, desc, color, hover, page in btn_data:
            card = tk.Frame(cards, bg=BG_CARD, highlightbackground=BORDER_COLOR,
                            highlightthickness=1, cursor="hand2")
            card.pack(pady=8, ipadx=30, ipady=14, fill="x")

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
                widget.bind("<Button-1>", lambda e, p=page: controller.show_frame(p))
                widget.bind("<Enter>", lambda e, c=card, clr=hover: c.config(highlightbackground=clr, highlightthickness=2))
                widget.bind("<Leave>", lambda e, c=card: c.config(highlightbackground=BORDER_COLOR, highlightthickness=1))
