"""Trang chủ."""

import threading
import tkinter as tk
import webbrowser

from apps import __version__
from apps.config import (
    BG_MAIN, BG_CARD, FG_TITLE, FG_DIM,
    ACCENT_BLUE, ACCENT_ORANGE, ACCENT_GREEN, ACCENT_PURPLE,
    BTN_HOVER_BLUE, BTN_HOVER_ORANGE, BTN_HOVER_GREEN, BTN_HOVER_PURPLE,
    BORDER_COLOR, UPDATE_MANIFEST_URL,
)
from apps.services.update_check import check_for_update
from apps.widgets import show_info, show_settings_dialog


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
        from apps.pages.multi_upload_page import MultiUploadPage

        btn_data = [
            ("Xử lý XML → Excel", "Giải mã XML4, đối chiếu danh mục dịch vụ → Excel",
             ACCENT_BLUE, BTN_HOVER_BLUE, XMLToExcelPage),
            ("Xử lý ảnh X-Quang", "Xóa text burned-in + anonymize metadata DICOM",
             ACCENT_ORANGE, BTN_HOVER_ORANGE, XRayPage),
            ("Đánh giá kết quả OCR", "So sánh kết quả OCR với dữ liệu gốc",
             ACCENT_GREEN, BTN_HOVER_GREEN, OCRPage),
            ("Upload PDF Xét nghiệm", "Tô đen, nhập thông tin & lưu PDF + CSV",
             ACCENT_PURPLE, BTN_HOVER_PURPLE, UploadPDFPage),
            ("Upload File đã xử lý", "Gửi file đã xử lý lên VITAL-LOG",
             ACCENT_BLUE, BTN_HOVER_BLUE, MultiUploadPage),
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

        footer = tk.Frame(center, bg=BG_MAIN)
        footer.pack(pady=(28, 0))

        # Số version luôn hiện — hỗ trợ chỉ cần nhìn màn hình là biết bản nào.
        self._version_label = tk.Label(
            footer, text=f"v{__version__}", font=("Helvetica", 10),
            bg=BG_MAIN, fg=FG_DIM,
        )
        self._version_label.pack(side="left")

        tk.Label(footer, text="  ·  ", font=("Helvetica", 10),
                 bg=BG_MAIN, fg=FG_DIM).pack(side="left")

        settings = tk.Label(
            footer, text="⚙ Cấu hình kết nối", font=("Helvetica", 10),
            bg=BG_MAIN, fg=ACCENT_BLUE, cursor="hand2",
        )
        settings.pack(side="left")
        settings.bind("<Button-1>", lambda e: self._open_settings())

        threading.Thread(target=self._check_update, daemon=True).start()

    def _open_settings(self):
        if not show_settings_dialog(self):
            return
        # apps.config chụp giá trị một lần lúc import và các trang đã
        # `from apps.config import API_UPLOAD_URL`, nên giá trị mới chỉ có hiệu
        # lực ở lần chạy sau.
        #
        # ponytail: bắt khởi động lại thay vì làm config nạp nóng. Muốn bỏ bước
        # này thì các trang upload phải đọc `Settings.from_env()` lúc gọi thay
        # vì hằng số phẳng — sửa đúng vào đường upload, phần rủi ro nhất.
        show_info(
            self,
            "Đã lưu cấu hình",
            "Khởi động lại VitalLens để áp dụng cấu hình mới.",
        )

    def _check_update(self):
        """Chạy nền: mạng chậm không được giữ cửa sổ chính."""
        update = check_for_update(__version__, UPDATE_MANIFEST_URL)
        if not update:
            return
        try:
            self.after(0, self._show_update, update)
        except tk.TclError:
            pass  # App đã đóng trước khi request xong.

    def _show_update(self, update):
        text = f"v{__version__} — đã có bản {update.version}"
        if update.url:
            self._version_label.config(cursor="hand2")
            self._version_label.bind(
                "<Button-1>", lambda e: webbrowser.open(update.url)
            )
            text += ", bấm để tải"
        self._version_label.config(text=text, fg=ACCENT_BLUE)
