"""VitalLens - Python/Tkinter desktop app hỗ trợ xử lý dữ liệu y tế.

Các package con:
- `apps.pages`     : UI layer (tkinter Frames cho từng trang).
- `apps.widgets`   : Widgets dùng chung (button, status bar, date picker...).
- `apps.services`  : Business + I/O (storage, payload_io, excel_export,
                     lab_records, pdf_redact, upload_api).
- `apps.processing`: Pure processing (OCR X-Ray, XML → Excel, image_loader).
"""

__version__ = "0.2.0"
