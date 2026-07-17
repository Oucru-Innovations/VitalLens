"""App - Cửa sổ chính với điều hướng giữa các trang."""

import platform
import tkinter as tk

from apps.config import APP_DIR, BG_MAIN
from apps.pages.home import HomePage
from apps.pages.xml_page import XMLToExcelPage
from apps.pages.xray_page import XRayPage
from apps.pages.ocr import OCRPage
from apps.pages.upload import UploadPDFPage


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VitalLens")
        self._apply_app_icon()

        if platform.system() == "Darwin":
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry(f"{sw}x{sh}+0+0")
        else:
            self.state("zoomed")
        self.minsize(900, 600)
        self.configure(bg=BG_MAIN)

        self.container = tk.Frame(self, bg=BG_MAIN)
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        for PageClass in (HomePage, XMLToExcelPage, XRayPage, OCRPage, UploadPDFPage):
            frame = PageClass(self.container, self)
            self.frames[PageClass] = frame
            frame.place(relwidth=1, relheight=1)

        self.show_frame(HomePage)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def show_frame(self, page_class):
        self.frames[page_class].tkraise()

    def _on_close(self):
        # Cho các trang cơ hội dọn tài nguyên (đóng PDF handle, ...).
        for frame in self.frames.values():
            on_close = getattr(frame, "on_close", None)
            if callable(on_close):
                try:
                    on_close()
                except Exception:
                    pass
        self.destroy()

    def _apply_app_icon(self):
        icon_path = APP_DIR / "icon.ico"
        if not icon_path.exists():
            return

        try:
            self.iconbitmap(default=str(icon_path))
        except Exception:
            return
