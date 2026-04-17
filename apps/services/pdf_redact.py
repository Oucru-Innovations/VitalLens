"""Render PDF và lưu bản PDF đã tô đen vùng nhạy cảm.

Dùng pypdfium2 để rasterize từng trang rồi ghi lại thành PDF mới. Nhờ vậy
không cần thư viện edit PDF phức tạp; đổi lại file output lớn hơn một chút.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# (x1, y1, x2, y2) theo toạ độ point của PDF.
Rect = Tuple[float, float, float, float]
PageRedactions = Dict[int, List[Rect]]


def temp_output_path(output_path: str) -> str:
    """Đường dẫn tạm cho save atomic (ghi xong rồi rename)."""

    path = Path(output_path)
    return str(path.with_name(f"{path.stem}.__tmp__{path.suffix}"))


def _draw_redactions(img, rects: Iterable[Rect], scale: float):
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    for (px1, py1, px2, py2) in rects:
        draw.rectangle(
            [
                int(px1 * scale),
                int(py1 * scale),
                int(px2 * scale),
                int(py2 * scale),
            ],
            fill="black",
        )


def save_redacted_pdf(
    src_pdf_path: str,
    redactions: PageRedactions,
    output_path: str,
    scale: float = 3.0,
) -> None:
    """Rasterize `src_pdf_path`, vẽ các hình chữ nhật tô đen, rồi lưu ra PDF mới."""

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(src_pdf_path)
    images = []
    try:
        for page_num in range(len(pdf)):
            page = pdf[page_num]
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil().convert("RGB")

            rects = redactions.get(page_num, [])
            if rects:
                _draw_redactions(img, rects, scale)
            images.append(img)
    finally:
        pdf.close()

    if not images:
        return

    images[0].save(
        output_path,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=scale * 72,
    )


__all__ = ["save_redacted_pdf", "temp_output_path", "Rect", "PageRedactions"]
