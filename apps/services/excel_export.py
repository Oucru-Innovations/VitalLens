"""Xuất list[dict] thành file .xlsx với sheet tuỳ chỉnh."""

from __future__ import annotations

import re
from typing import Iterable, List


def _sanitize_sheet_name(name: str, default: str = "Sheet1") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "_", name).strip() or default
    return cleaned[:31]


def collect_columns(rows: Iterable[dict]) -> List[str]:
    columns: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


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
    ws.title = _sanitize_sheet_name(sheet_name)

    cols = columns or collect_columns(rows)
    ws.append(cols)
    for row in rows:
        ws.append([row.get(column, "") for column in cols])

    wb.save(path)
    return len(rows)


__all__ = ["write_rows_to_xlsx", "collect_columns"]
