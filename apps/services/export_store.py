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

`meta.json` là nguồn chuẩn để khôi phục state: nó ghi UUID của cặp, tên file
pdf/csv, form đã nhập, các vùng tô đen, file gốc, cờ đã-gửi từng file (phục vụ
retry không gửi trùng) và nhật ký upload (`attempts`, `last_error`,
`last_attempt_at`, `uploaded_at`) để hiển thị "cặp nào chưa lên và vì sao" sau
khi mở lại app.
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

# Cột nối CSV với PDF của cùng một cặp. ``export_id`` là UUID bền vững của cặp
# và là nonce chống trùng hash giữa cả những workspace/máy khác nhau.
CSV_FILE_COLUMN = "file_name"
CSV_EXPORT_ID_COLUMN = "export_id"


class CsvMigrationError(RuntimeError):
    """CSV cũ không thể được chuẩn hoá an toàn trước khi upload."""


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

        export_id = meta.get("id") or ""
        if not export_id:
            # Meta rất cũ có thể chưa mang id. Nếu lần migration trước đã ghi
            # CSV rồi nhưng app tắt trước lúc ghi meta, nhận lại chính UUID đó
            # để retry không tạo một hash mới ở mỗi lần khởi động.
            try:
                export_id = _peek_csv_export_id(csv_path)
            except (OSError, csv.Error, UnicodeError, CsvMigrationError) as e:
                log.warning("Chưa đọc được export_id từ CSV %s: %s", csv_path, e)
        export_id = export_id or uuid.uuid4().hex

        exports.append(
            {
                "id": export_id,
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


def _read_csv_rows(path: str) -> tuple[list[str], list[dict]]:
    """Đọc nguyên CSV để migration không làm mất cột/dòng ngoài ``form_data``."""

    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        raise CsvMigrationError("CSV không có header")
    if not rows:
        raise CsvMigrationError("CSV không có dòng dữ liệu")
    if any(None in row for row in rows):
        raise CsvMigrationError("CSV có ô thừa so với header")
    return fieldnames, rows


def _csv_export_id_from_rows(rows: list[dict]) -> str:
    """Lấy UUID đã có trong các dòng; báo lỗi nếu chúng tự mâu thuẫn."""

    ids = {
        str(row.get(CSV_EXPORT_ID_COLUMN) or "").strip()
        for row in rows
        if str(row.get(CSV_EXPORT_ID_COLUMN) or "").strip()
    }
    if len(ids) > 1:
        raise CsvMigrationError("CSV chứa nhiều export_id khác nhau")
    return next(iter(ids), "")


def _peek_csv_export_id(path: str) -> str:
    """Lấy UUID đã có trong CSV mà không thay đổi file."""

    _fieldnames, rows = _read_csv_rows(path)
    return _csv_export_id_from_rows(rows)


def _write_csv_rows(output_path: str, fieldnames: list[str], rows: list[dict]) -> None:
    """Ghi atomic các dòng CSV, đồng thời áp dụng chống formula injection."""

    tmp = f"{output_path}.__tmp__"
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                safe_row = {
                    key: _csv_safe("" if value is None else str(value))
                    for key, value in row.items()
                }
                writer.writerow(safe_row)
        os.replace(tmp, output_path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_csv(output_path: str, form: dict, pdf_name: str, export_id: str) -> None:
    """Ghi atomic CSV metadata kèm tên PDF và UUID bền vững của cặp.

    Backend loại file trùng theo **hash nội dung** (không nhìn tên file) và
    không sửa được. Không có các trường identity này, hai cặp cùng bệnh nhân +
    cùng type + cùng các mốc ngày cho ra CSV giống hệt nhau từng byte → server
    nuốt mất CSV thứ hai: PDF lên được, metadata bị SÓT mà không ai báo lỗi.
    ``file_name`` nối metadata với đúng PDF; ``export_id`` là UUID lưu cả trong
    meta nên bảo đảm nội dung khác nhau ngay cả khi hai workspace/máy tạo cùng
    tên file.
    """

    if not export_id:
        raise ValueError("export_id không được để trống")
    row = dict(
        form,
        **{
            CSV_FILE_COLUMN: pdf_name,
            CSV_EXPORT_ID_COLUMN: export_id,
        },
    )
    _write_csv_rows(output_path, list(row.keys()), [row])


def ensure_csv_identity(export: dict) -> bool:
    """Vá CSV cũ thiếu ``file_name``/``export_id``. True = đã ghi lại.

    False nghĩa là CSV đã đủ hai cột. Nếu không thể đọc/ghi hoặc meta thiếu dữ
    liệu để vá, hàm ném :class:`CsvMigrationError`; caller phải dừng upload cặp
    đó, không được âm thầm gửi CSV cũ có nguy cơ bị backend bỏ qua.

    Đánh đổi đã cân nhắc: nếu một CSV cũ THỰC RA đã tới server mà app không kịp
    ghi nhận (``ReadTimeout``), lần gửi lại sau khi vá sẽ mang nội dung mới nên
    server không nhận ra trùng → sinh bản ghi lặp, thay vì bị nuốt im lặng như
    trước. Chấp nhận được vì endpoint vốn không có idempotency key: chính sách
    retry (xem ``upload_api``) đã đặt quyền quyết định gửi lại vào tay người
    dùng đúng cho những trường hợp này, và mất metadata thì tệ hơn ghi lặp.
    """

    path = export.get("csv_path") or ""
    pdf_name = os.path.basename(export.get("pdf_path") or "")
    missing_meta = [
        name
        for name, value in (
            ("csv_path", path),
            ("pdf_path", pdf_name),
        )
        if not value
    ]
    if missing_meta:
        raise CsvMigrationError(
            "thiếu dữ liệu meta: " + ", ".join(missing_meta)
        )
    try:
        fieldnames, rows = _read_csv_rows(path)
        csv_export_id = _csv_export_id_from_rows(rows)
        export_id = export.get("id") or csv_export_id or uuid.uuid4().hex
        export["id"] = export_id

        required = (CSV_FILE_COLUMN, CSV_EXPORT_ID_COLUMN)
        missing_columns = [name for name in required if name not in fieldnames]
        expected_pdf_name = _csv_safe(pdf_name)
        expected_export_id = _csv_safe(export_id)
        identity_matches = all(
            row.get(CSV_FILE_COLUMN) == expected_pdf_name
            and row.get(CSV_EXPORT_ID_COLUMN) == expected_export_id
            for row in rows
        )
        if not missing_columns and identity_matches:
            return False
        fieldnames.extend(missing_columns)
        for row in rows:
            row[CSV_FILE_COLUMN] = pdf_name
            row[CSV_EXPORT_ID_COLUMN] = export_id
        _write_csv_rows(path, fieldnames, rows)
    except CsvMigrationError:
        raise
    except (OSError, csv.Error, UnicodeError, ValueError) as e:
        log.warning("Không chuẩn hoá được CSV %s: %s", path, e)
        raise CsvMigrationError(f"không đọc/ghi được {path}: {e}") from e
    log.info("Đã chuẩn hoá identity CSV (thiếu=%s): %s", missing_columns, path)
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
    "CSV_EXPORT_ID_COLUMN",
    "CsvMigrationError",
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
    "ensure_csv_identity",
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

        # Hai workspace/máy có thể tạo cùng form VÀ cùng tên PDF. UUID của cặp
        # vẫn phải làm nội dung khác nhau để backend không nuốt mất bản thứ hai.
        _a = os.path.join(_pending, "a.csv")
        _b = os.path.join(_pending, "b.csv")
        _pdf_name = "HematologyImage_P001_18.08.2026.12.00.00_.pdf"
        _id_a = "a" * 32
        _id_b = "b" * 32
        write_csv(_a, _FORM, _pdf_name, _id_a)
        write_csv(_b, _FORM, _pdf_name, _id_b)
        _first = open(_a, "rb").read()
        assert _first != open(_b, "rb").read(), "CSV trùng nội dung"
        assert b"13NV" in _first, "thiếu cột SID"
        assert _pdf_name.encode() in _first, "thiếu cột file_name"
        assert _id_a.encode() in _first, "thiếu cột export_id"

        # UUID đi đủ vòng meta -> restart -> move, không sinh lại giữa retry.
        _pair_pdf = os.path.join(_pending, "pair.pdf")
        with open(_pair_pdf, "wb") as _fh:
            _fh.write(b"pdf")
        _pair = {
            "id": _id_a,
            "display_name": "pair",
            "pdf_path": _pair_pdf,
            "csv_path": _a,
            "form_data": _FORM,
        }
        write_meta(_pending, _pair)
        _pending_rows, _uploaded_rows = read_all(_base)
        assert _pending_rows[0]["id"] == _id_a, "restart làm đổi export_id"
        move_pair(_pending_rows[0], uploaded_dir(_base))
        _pending_rows, _uploaded_rows = read_all(_base)
        assert not _pending_rows and _uploaded_rows[0]["id"] == _id_a

        # Chống CSV formula injection khi mở bằng Excel/Sheets.
        _c = os.path.join(_pending, "c.csv")
        write_csv(
            _c,
            dict(_FORM, patient_code="=cmd|'/c calc'!A1"),
            "x.pdf",
            "c" * 32,
        )
        assert b",'=cmd" in open(_c, "rb").read(), "thiếu prefix chống công thức"

        # CSV bản cũ phải được vá đủ identity, và chỉ vá một lần.
        _old = os.path.join(_pending, "old.csv")
        with open(_old, "w", newline="", encoding="utf-8-sig") as _fh:
            _fh.write(
                "date,patient_code" + chr(10)
                + "18-08-2026,P001" + chr(10)
                + "19-08-2026,P002" + chr(10)
            )
        _exp = {
            "id": "d" * 32,
            "csv_path": _old,
            "pdf_path": os.path.join(_pending, "old.pdf"),
            "form_data": _FORM,
        }
        assert ensure_csv_identity(_exp) is True, "không vá CSV cũ"
        _migrated = open(_old, "rb").read()
        assert b"old.pdf" in _migrated, "vá xong vẫn thiếu file_name"
        assert b"d" * 32 in _migrated, "vá xong vẫn thiếu export_id"
        with open(_old, encoding="utf-8-sig", newline="") as _fh:
            assert len(list(csv.DictReader(_fh))) == 2, "migration làm mất dòng"
        assert ensure_csv_identity(_exp) is False, "vá lặp lần hai"

        # Crash sau khi ghi CSV nhưng trước meta: lần sau phải nhận lại UUID CSV.
        _partial = dict(_exp, id="")
        assert ensure_csv_identity(_partial) is False
        assert _partial["id"] == "d" * 32, "không nhận lại id từ CSV"

        # CSV rỗng/hỏng phải báo lỗi rõ, không được giả vờ là đã sẵn sàng.
        _empty = os.path.join(_pending, "empty.csv")
        with open(_empty, "w", newline="", encoding="utf-8-sig") as _fh:
            _fh.write("date,patient_code" + chr(10))
        try:
            ensure_csv_identity(dict(_exp, csv_path=_empty))
        except CsvMigrationError:
            pass
        else:
            raise AssertionError("CSV rỗng không báo lỗi migration")

    print("export_store OK")
