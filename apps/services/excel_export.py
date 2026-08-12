"""Xuất list[dict] thành file .xlsx với sheet tuỳ chỉnh."""

from __future__ import annotations

import re
from typing import Iterable, List


def sanitize_sheet_name(name: str, default: str = "Sheet1") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "_", name).strip() or default
    return cleaned[:31]


def append_row_as_text(ws, values: Iterable) -> None:
    """Ghi 1 dòng, ép các ô bị hiểu nhầm là công thức về dạng text.

    openpyxl gán ``data_type="f"`` cho mọi chuỗi bắt đầu bằng ``=`` (và chỉ
    ``=``; ``+ - @`` đã được lưu dạng text sẵn trong .xlsx). Hệ quả: kết quả
    xét nghiệm dạng ``=<0.5`` mở ra thành ``#NAME?`` — mất dữ liệu âm thầm —
    còn chuỗi kiểu ``=cmd|'/c calc'!A1`` trở thành lệnh DDE.

    Đặt ``data_type="s"`` giữ nguyên **đúng văn bản gốc**. Không dùng cách
    prefix dấu ``'`` như bên CSV: ở .xlsx nó sẽ làm hỏng các giá trị âm hợp lệ
    (``-5.2``) vốn không hề bị coi là công thức.

    Ô được dựng sẵn TRƯỚC khi append, không sửa lại sau. Cách cũ (``ws.append``
    rồi duyệt ``ws[ws.max_row]``) là O(n²): cả ``max_row`` lẫn ``ws[<int>]``
    đều quét toàn bộ ``ws._cells`` mỗi lần gọi, nên chi phí tăng theo bình
    phương số dòng — đo được 0,37s cho 500 dòng nhưng 21s cho 4.000 dòng, tức
    hàng chục phút với một lô XML4 thật. Cách này O(số cột) mỗi dòng và chạy
    được cả ở chế độ ``write_only`` (nơi không thể truy cập lại ô đã ghi).
    """

    from openpyxl.cell import Cell

    row = []
    for value in values:
        if isinstance(value, str) and value.startswith("="):
            cell = Cell(worksheet=ws, column=1, row=1, value=value)
            cell.data_type = "s"  # toạ độ thật do ws.append gán lại
            row.append(cell)
        else:
            row.append(value)
    ws.append(row)


def collect_columns(rows: Iterable[dict]) -> List[str]:
    return list(dict.fromkeys(key for row in rows for key in row))


def write_rows_to_xlsx(
    path: str,
    rows: List[dict],
    sheet_name: str = "Sheet1",
    columns: List[str] | None = None,
) -> int:
    """Ghi rows ra file Excel. Trả về số dòng dữ liệu ghi được."""

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sanitize_sheet_name(sheet_name)

    cols = columns or collect_columns(rows)
    append_row_as_text(ws, cols)
    for row in rows:
        append_row_as_text(ws, [row.get(column, "") for column in cols])

    wb.save(path)
    return len(rows)


__all__ = [
    "append_row_as_text",
    "collect_columns",
    "sanitize_sheet_name",
    "write_rows_to_xlsx",
]
