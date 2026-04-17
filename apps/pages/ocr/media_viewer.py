"""Media viewer cho trang OCR - hiển thị PDF / ảnh / DICOM.

Nhận StorageBackend để fetch file về temp khi ở chế độ SFTP.
"""

from __future__ import annotations

import os
import platform
import tkinter as tk
from pathlib import Path
from typing import List, Tuple

from apps.config import BG_CARD, FG_DIM, ACCENT_BLUE, ACCENT_RED
from apps.processing.xray import load_image
from apps.services.storage import StorageBackend

IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".dcm"}


class MediaViewer:
    """Quản lý khung xem trước (Canvas + Frame) cho OCR review."""

    def __init__(
        self,
        viewer_frame: tk.Frame,
        viewer_canvas: tk.Canvas,
        backend: StorageBackend,
        ocr_type_getter,
    ):
        self.viewer_frame = viewer_frame
        self.viewer_canvas = viewer_canvas
        self.backend = backend
        self._get_ocr_type = ocr_type_getter
        self._photo_ref = None
        self._photo_refs: List = []
        self._pdf_photo_refs: List = []

    def _clear(self) -> None:
        for w in self.viewer_frame.winfo_children():
            w.destroy()
        self._photo_ref = None
        self._photo_refs = []
        self._pdf_photo_refs = []

    def display_media(self, folder_path: str, media_files: List[str]) -> None:
        self._clear()
        if not media_files:
            tk.Label(
                self.viewer_frame,
                text="Không tìm thấy file hiển thị",
                font=("Helvetica", 12),
                bg=BG_CARD,
                fg=FG_DIM,
            ).pack(expand=True)
            return

        local_paths: List[Tuple[str, str]] = []
        for mf in media_files:
            remote_path = self.backend.join(folder_path, mf)
            local_path = self.backend.fetch_to_temp(
                remote_path, suffix=Path(mf).suffix
            )
            local_paths.append((local_path, mf))

        self.viewer_frame.after_idle(lambda: self._render(local_paths))

    def _render(self, local_paths: List[Tuple[str, str]]) -> None:
        try:
            from PIL import Image, ImageTk

            self.viewer_frame.update_idletasks()
            max_w = max(self.viewer_canvas.winfo_width() - 30, 300)

            if self._get_ocr_type() == "OCR BEDSIDE MONITOR":
                local_path, media_file = local_paths[0]
                ext = Path(media_file).suffix.lower()
                img = load_image(local_path) if ext == ".dcm" else Image.open(local_path)
                max_h = max(self.viewer_canvas.winfo_height() - 30, 300)
                img.thumbnail((max_w, max_h), Image.LANCZOS)
                self._photo_ref = ImageTk.PhotoImage(img)
                tk.Label(
                    self.viewer_frame, image=self._photo_ref, bg=BG_CARD
                ).pack(expand=True)
                return

            for local_path, media_file in local_paths:
                ext = Path(media_file).suffix.lower()
                if ext == ".pdf":
                    self._display_pdf(local_path, media_file)
                elif ext in IMG_EXTS:
                    self._display_image(local_path, media_file, max_w)
        except Exception as e:  # noqa: BLE001 - UI fallback
            tk.Label(
                self.viewer_frame,
                text=f"Lỗi hiển thị: {e}",
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=ACCENT_RED,
            ).pack(expand=True)

    def _display_image(self, local_path: str, media_file: str, max_w: int) -> None:
        try:
            from PIL import Image, ImageTk

            ext = Path(media_file).suffix.lower()
            img = load_image(local_path) if ext == ".dcm" else Image.open(local_path)
            img.thumbnail((max_w, 2000), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_refs.append(photo)
            tk.Label(
                self.viewer_frame,
                text=Path(media_file).name,
                font=("Helvetica", 10),
                bg=BG_CARD,
                fg=FG_DIM,
            ).pack(pady=(8, 2))
            tk.Label(self.viewer_frame, image=photo, bg=BG_CARD).pack(pady=(0, 4))
        except Exception as e:  # noqa: BLE001
            tk.Label(
                self.viewer_frame,
                text=f"Lỗi ảnh {media_file}: {e}",
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=ACCENT_RED,
            ).pack(pady=4)

    def _display_pdf(self, local_path: str, media_file: str) -> None:
        try:
            import pypdfium2 as pdfium
            from PIL import ImageTk

            pdf = pdfium.PdfDocument(local_path)
            self.viewer_frame.update_idletasks()
            max_w = max(self.viewer_canvas.winfo_width() - 30, 400)
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                pw, _ph = page.get_size()
                scale = max(max_w / pw, 1.0)
                scale = min(scale, 3.0)
                bitmap = page.render(scale=scale)
                img = bitmap.to_pil()
                photo = ImageTk.PhotoImage(img)
                self._pdf_photo_refs.append(photo)
                tk.Label(self.viewer_frame, image=photo, bg=BG_CARD).pack(
                    pady=(0, 4)
                )
            pdf.close()
        except ImportError:
            tk.Label(
                self.viewer_frame,
                text=f"File: {media_file}\n\nCần cài pypdfium2:\npip install pypdfium2",
                font=("Helvetica", 11),
                bg=BG_CARD,
                fg=FG_DIM,
                justify="center",
            ).pack(expand=True)

            open_btn = tk.Label(
                self.viewer_frame,
                text="  Mở file PDF  ",
                font=("Helvetica", 11, "bold"),
                bg=ACCENT_BLUE,
                fg="#ffffff",
                cursor="hand2",
                padx=10,
                pady=6,
            )
            open_btn.pack(pady=10)
            open_btn.bind("<Button-1>", lambda e: _open_external(local_path))


def _open_external(local_path: str) -> None:
    import subprocess

    if platform.system() == "Windows":
        os.startfile(local_path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", local_path])
    else:
        subprocess.Popen(["xdg-open", local_path])


__all__ = ["MediaViewer", "IMG_EXTS"]
