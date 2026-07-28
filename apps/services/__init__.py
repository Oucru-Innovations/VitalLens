"""Service layer - thuần Python, không phụ thuộc tkinter.

Được chia thành các module nhỏ tập trung vào một mối bận tâm:
- storage        : abstraction đọc/ghi file cho local + SFTP.
- payload_io     : đọc/ghi JSON & CSV qua storage.
- excel_export   : xuất list[dict] sang file .xlsx.
- lab_records    : scan thư mục PROCESSING và nhóm hồ sơ OCR.
- mapping_excel  : file Excel mapping tuỳ chọn của người dùng (gắn thêm cột).
- medical_catalog: danh mục dịch vụ y tế (tra Name_Method + nhóm Include/Exclude).
- pdf_redact     : render PDF và xuất bản PDF đã tô đen.
- upload_api     : gửi cặp PDF + CSV qua HTTP tới backend.
"""
