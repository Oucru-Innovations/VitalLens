"""VitalLens - Python/Tkinter desktop app for medical data processing.

Sub-packages:
- ``apps.pages``     : UI layer (tkinter Frames for each page).
- ``apps.widgets``   : Shared widgets (button, status bar, date picker…).
- ``apps.services``  : Business logic + I/O (storage, payload_io, excel_export,
                       lab_records, pdf_redact, upload_api).
- ``apps.processing``: CPU-bound processing (OCR X-Ray, XML → Excel).
"""

__version__ = "0.4.0"
