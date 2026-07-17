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
đã nhập, các vùng tô đen, file gốc và cờ đã-gửi từng file (phục vụ retry
không gửi trùng). Quét thư mục = tìm mọi `*.meta.json` rồi dựng lại danh sách.
"""

from __future__ import annotations

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
    "pending_dir",
    "uploaded_dir",
    "ensure_dirs",
    "write_meta",
    "read_all",
    "move_pair",
    "delete_pair",
    "load_workspace",
    "save_workspace",
]
