"""Lưu trữ bền vững cho các cặp (PDF + CSV) đã xuất.

Mục tiêu: sau khi tắt/mở lại app vẫn biết cặp nào CHỜ upload và cặp nào ĐÃ
upload. Trạng thái được lưu bằng **thư mục vật lý** dưới `base_dir` (thư mục
người dùng chọn ở ô "Thư mục lưu"):

    base_dir/
        pending/     - cặp đã lưu, CHỜ upload
        uploaded/    - cặp đã upload thành công

Mỗi cặp gồm 3 file:
    <pdf_name>.pdf          - PDF đã tô đen
    <csv_name>.csv          - metadata form
    <display_name>.meta.json - "sổ cái" của cặp (nguồn dữ liệu chuẩn)

`meta.json` là nguồn chuẩn để khôi phục state: nó ghi tên file pdf/csv, form
đã nhập, các vùng tô đen, file gốc, cờ đã-gửi từng file (phục vụ retry không
gửi trùng) và nhật ký upload (`attempts`, `last_error`, `last_attempt_at`,
`uploaded_at`) để hiển thị "cặp nào chưa lên và vì sao" sau khi mở lại app.
Quét thư mục = tìm mọi `*.meta.json` rồi dựng lại danh sách.

Module này cũng ghi luôn file CSV metadata (`write_csv`): backend loại file
trùng theo **hash nội dung**, nên định dạng CSV là một phần của "cặp trên đĩa"
chứ không phải chuyện của UI - xem docstring `write_csv`.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

PENDING = "pending"
UPLOADED = "uploaded"
_WORKSPACE_FILE = ".vitallens_workspace.json"
_META_SUFFIX = ".meta.json"

# Cột nối CSV với PDF của cùng một cặp; cũng là thứ giữ cho nội dung CSV không
# bao giờ trùng nhau (xem `write_csv`).
CSV_FILE_COLUMN = "file_name"

# Ký tự đầu ô mà Excel/Sheets hiểu là công thức → phải "thoát" khi ghi CSV.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# =====================================================================
# Đường dẫn thư mục
# =====================================================================


def pending_dir(base_dir: str) -> str:
    return os.path.join(base_dir, PENDING)


def uploaded_dir(base_dir: str) -> str:
    return os.path.join(base_dir, UPLOADED)


def ensure_dirs(base_dir: str) -> None:
    os.makedirs(pending_dir(base_dir), exist_ok=True)
    os.makedirs(uploaded_dir(base_dir), exist_ok=True)


def _meta_name(display_name: str) -> str:
    return f"{display_name}{_META_SUFFIX}"


# =====================================================================
# (De)serialize redactions ({page:int -> [rect]} <-> JSON keys là str)
# =====================================================================


def _redactions_to_json(redactions: Dict[int, List]) -> Dict[str, List]:
    return {str(page): [list(rect) for rect in rects]
            for page, rects in (redactions or {}).items()}


def _redactions_from_json(data: Any) -> Dict[int, List]:
    out: Dict[int, List] = {}
    for key, rects in (data or {}).items():
        try:
            page = int(key)
        except (TypeError, ValueError):
            continue
        out[page] = [tuple(r) for r in rects]
    return out


# =====================================================================
# Ghi / đọc meta
# =====================================================================


def write_meta(folder: str, export: dict) -> str:
    """Ghi (atomic) meta.json cho `export` vào `folder`. Trả path meta."""

    meta = {
        "id": export["id"],
        "display_name": export["display_name"],
        "pdf_name": os.path.basename(export["pdf_path"]),
        "csv_name": os.path.basename(export["csv_path"]),
        "original_file": export.get("original_file", ""),
        "form_data": export.get("form_data", {}),
        "redactions": _redactions_to_json(export.get("redactions", {})),
        "pdf_sent": bool(export.get("pdf_sent", False)),
        "csv_sent": bool(export.get("csv_sent", False)),
        # Nhật ký upload: giúp sau khi mở lại app vẫn biết cặp nào từng lỗi,
        # lỗi gì và đã thử bao nhiêu lần.
        "attempts": int(export.get("attempts", 0) or 0),
        "last_error": export.get("last_error", "") or "",
        "last_attempt_at": export.get("last_attempt_at", "") or "",
        "uploaded_at": export.get("uploaded_at", "") or "",
    }
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, _meta_name(export["display_name"]))
    tmp = f"{path}.__tmp__"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    export["meta_path"] = path
    return path


def _load_folder(folder: str) -> List[dict]:
    exports: List[dict] = []
    if not os.path.isdir(folder):
        return exports
    for name in sorted(os.listdir(folder)):
        if not name.endswith(_META_SUFFIX):
            continue
        meta_path = os.path.join(folder, name)
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Bỏ qua meta hỏng %s: %s", meta_path, e)
            continue

        pdf_path = os.path.join(folder, meta.get("pdf_name", ""))
        csv_path = os.path.join(folder, meta.get("csv_name", ""))
        if not (os.path.exists(pdf_path) and os.path.exists(csv_path)):
            log.warning("Bỏ qua meta thiếu file cặp: %s", meta_path)
            continue

        exports.append(
            {
                "id": meta.get("id") or uuid.uuid4().hex,
                "original_file": meta.get("original_file", ""),
                "pdf_path": pdf_path,
                "csv_path": csv_path,
                "meta_path": meta_path,
                "display_name": meta.get("display_name")
                or name[: -len(_META_SUFFIX)],
                "form_data": meta.get("form_data", {}),
                "redactions": _redactions_from_json(meta.get("redactions", {})),
                "pdf_sent": bool(meta.get("pdf_sent", False)),
                "csv_sent": bool(meta.get("csv_sent", False)),
                "attempts": int(meta.get("attempts", 0) or 0),
                "last_error": meta.get("last_error", "") or "",
                "last_attempt_at": meta.get("last_attempt_at", "") or "",
                "uploaded_at": meta.get("uploaded_at", "") or "",
            }
        )
    return exports


def read_all(base_dir: str) -> Tuple[List[dict], List[dict]]:
    """Quét cả hai thư mục, trả về (pending_exports, uploaded_exports)."""

    return _load_folder(pending_dir(base_dir)), _load_folder(uploaded_dir(base_dir))


# =====================================================================
# Di chuyển / xoá cặp file
# =====================================================================


def move_pair(export: dict, dest_folder: str) -> dict:
    """Di chuyển pdf/csv/meta của `export` sang `dest_folder` (cập nhật path)."""

    os.makedirs(dest_folder, exist_ok=True)
    for key in ("pdf_path", "csv_path", "meta_path"):
        src = export.get(key)
        if not src or not os.path.exists(src):
            continue
        dst = os.path.join(dest_folder, os.path.basename(src))
        os.replace(src, dst)
        export[key] = dst
    # Ghi lại meta ở vị trí mới để đồng bộ cờ đã-gửi + tên file.
    write_meta(dest_folder, export)
    return export


def delete_pair(export: dict) -> None:
    """Xoá pdf/csv/meta của `export` khỏi ổ cứng (bỏ qua nếu đã mất)."""

    for key in ("pdf_path", "csv_path", "meta_path"):
        path = export.get(key)
        if not path:
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            continue


# =====================================================================
# CSV metadata
# =====================================================================


def _csv_safe(value: str) -> str:
    """Chống CSV formula injection: prefix ' cho ô bắt đầu bằng ký tự công thức."""

    if value and value[0] in _CSV_FORMULA_PREFIXES:
        return "'" + value
    return value


def write_csv(output_path: str, form: dict, pdf_name: str) -> None:
    """Ghi (atomic) CSV metadata, kèm cột `file_name` = tên PDF của cặp.

    Backend loại file trùng theo **hash nội dung** (không nhìn tên file) và
    không sửa được. Không có cột này, hai cặp cùng bệnh nhân + cùng type + cùng
    các mốc ngày cho ra CSV giống hệt nhau từng byte → server nuốt mất CSV thứ
    hai: PDF lên được, metadata bị SÓT mà không ai báo lỗi. `pdf_name` là duy
    nhất trong kho (xem `UploadPDFPage._unique_export_names`) nên mỗi CSV có
    một nội dung riêng, đồng thời cho backend biết dòng này thuộc PDF nào.
    """

    row = dict(form, **{CSV_FILE_COLUMN: pdf_name})
    safe_row = {k: _csv_safe(str(v)) for k, v in row.items()}
    tmp = f"{output_path}.__tmp__"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(safe_row)
    os.replace(tmp, output_path)


def ensure_csv_file_name(export: dict) -> bool:
    """Vá CSV lưu bằng bản cũ (chưa có cột `file_name`). True = đã ghi lại.

    Những cặp còn nằm sẵn trong `pending/` từ trước khi có cột này vẫn dính lỗi
    trùng hash, nên vá ngay trước lúc gửi thay vì bắt người dùng lưu lại tay.
    """

    path = export.get("csv_path") or ""
    form = export.get("form_data") or {}
    pdf_name = os.path.basename(export.get("pdf_path") or "")
    if not path or not form or not pdf_name:
        return False
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh), [])
        if CSV_FILE_COLUMN in header:
            return False
        write_csv(path, form, pdf_name)
    except OSError as e:
        log.warning("Không vá được cột %s cho %s: %s", CSV_FILE_COLUMN, path, e)
        return False
    log.info("Đã vá cột %s cho CSV cũ: %s", CSV_FILE_COLUMN, path)
    return True

# =====================================================================
# Ghi nhớ thư mục làm việc gần nhất (để restart quét đúng chỗ)
# =====================================================================


def load_workspace(app_dir: str) -> str | None:
    path = os.path.join(str(app_dir), _WORKSPACE_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        value = data.get("output_dir")
        return value or None
    except (OSError, json.JSONDecodeError):
        return None


def save_workspace(app_dir: str, output_dir: str) -> None:
    path = os.path.join(str(app_dir), _WORKSPACE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"output_dir": output_dir}, fh, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("Không ghi được workspace state: %s", e)


__all__ = [
    "PENDING",
    "UPLOADED",
    "CSV_FILE_COLUMN",
    "pending_dir",
    "uploaded_dir",
    "ensure_dirs",
    "write_meta",
    "read_all",
    "move_pair",
    "delete_pair",
    "load_workspace",
    "save_workspace",
    "write_csv",
    "ensure_csv_file_name",
]


if __name__ == "__main__":
    import tempfile

    _FORM = {
        "date": "18-08-2026",
        "sid": "13NV",
        "patient_code": "P001",
        "type": "Hematology",
        "other_type": "",
        "sampling_date": "18-08-2026",
        "receipt_date": "18-08-2026",
        "result_date": "18-08-2026",
    }
    with tempfile.TemporaryDirectory() as _base:
        ensure_dirs(_base)
        _pending = pending_dir(_base)

        # Hai cặp cùng form nhưng khác PDF → nội dung CSV PHẢI khác nhau, nếu
        # không backend (loại trùng theo hash) sẽ nuốt mất cặp thứ hai.
        _a = os.path.join(_pending, "a.csv")
        _b = os.path.join(_pending, "b.csv")
        write_csv(_a, _FORM, "HematologyImage_P001_1_.pdf")
        write_csv(_b, _FORM, "HematologyImage_P001_2_.pdf")
        _first = open(_a, "rb").read()
        assert _first != open(_b, "rb").read(), "CSV trùng nội dung"
        assert b"13NV" in _first, "thiếu cột SID"
        assert b"HematologyImage_P001_1_.pdf" in _first, "thiếu cột file_name"

        # Chống CSV formula injection khi mở bằng Excel/Sheets.
        _c = os.path.join(_pending, "c.csv")
        write_csv(_c, dict(_FORM, patient_code="=cmd|'/c calc'!A1"), "x.pdf")
        assert b",'=cmd" in open(_c, "rb").read(), "thiếu prefix chống công thức"

        # CSV bản cũ (thiếu cột file_name) phải được vá, và chỉ vá một lần.
        _old = os.path.join(_pending, "old.csv")
        with open(_old, "w", newline="", encoding="utf-8-sig") as _fh:
            _fh.write("date,patient_code" + chr(10) + "18-08-2026,P001" + chr(10))
        _exp = {
            "csv_path": _old,
            "pdf_path": os.path.join(_pending, "old.pdf"),
            "form_data": _FORM,
        }
        assert ensure_csv_file_name(_exp) is True, "không vá CSV cũ"
        assert b"old.pdf" in open(_old, "rb").read(), "vá xong vẫn thiếu file_name"
        assert ensure_csv_file_name(_exp) is False, "vá lặp lần hai"

    print("export_store OK")
