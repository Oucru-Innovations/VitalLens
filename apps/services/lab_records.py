"""Quét thư mục PROCESSING trên backend bất kỳ và dựng danh sách hồ sơ OCR.

Thuần Python, không dùng tkinter → dễ test.

Cấu trúc thư mục mong đợi:

    <root>/
      <studyID>/                 ví dụ: 13NV
        PROCESSING/
          <patient_id>/          folder đặt tên theo patient_id
            <ddmmyyyy>/          folder đặt tên theo ngày (8 chữ số)
              Image/
                *.pdf  *.json  *.csv

Hoặc `root` đã trỏ thẳng tới thư mục PROCESSING của một study cụ thể
(ví dụ `/EI_SHARE/.received/13NV/PROCESSING`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .storage import (
    StorageBackend,
    resolve_existing_data_dir,
    resolve_named_child_dir,
    safe_is_dir,
)

log = logging.getLogger(__name__)

DATE_TOKEN_PATTERN = re.compile(r"^\d{8}$")

# Quy u\u01b0\u1edbc t\u00ean file xu\u1ea5t t\u1eeb OCR pipeline (VitalEI):
#
#   <Type><SubType>_<patient_id>_<dd.mm.yyyy.hh.mm.ss><tail>.<ext>
#
# - Type     : `Biochemistry`, `Hematology`, `Ventilator`, `Monitor`, ...
# - SubType  : `Image` (d\u00f9ng cho PDF + JSON raw) ho\u1eb7c `Metadata` (d\u00f9ng cho CSV raw);
#              c\u00f3 th\u1ec3 kh\u00f4ng c\u00f3 \u0111\u1ed1i v\u1edbi m\u1ed9t s\u1ed1 file c\u0169.
# - tail     : `_`, `__extracted`, `_validated`, `_done`, `__extracted_validated`, ...
LAB_FILENAME_PATTERN = re.compile(
    r"^"
    r"(?P<type>[A-Za-z]+?)"
    r"(?P<subtype>Image|Metadata)?"
    r"_(?P<pid>.+?)"
    r"_(?P<ts>\d{2}\.\d{2}\.\d{4}\.\d{2}\.\d{2}\.\d{2})"
    r"(?P<tail>.*)"
    r"$"
)


@dataclass(frozen=True)
class LabFilenameParts:
    """Kết quả parse tên file theo ``LAB_FILENAME_PATTERN``."""

    type_: str
    subtype: str
    patient_id: str
    timestamp: str
    tail: str
    raw_stem: str


def parse_lab_filename(stem: str) -> Optional[LabFilenameParts]:
    """Parse stem → ``LabFilenameParts`` hoặc ``None`` nếu không khớp."""

    m = LAB_FILENAME_PATTERN.match(stem or "")
    if not m:
        return None
    return LabFilenameParts(
        type_=m.group("type"),
        subtype=m.group("subtype") or "",
        patient_id=m.group("pid"),
        timestamp=m.group("ts"),
        tail=m.group("tail") or "",
        raw_stem=stem,
    )


def _status_from_tail(tail: str) -> str:
    """Suy luận status từ phần ``tail`` sau timestamp."""

    t = tail or ""
    if t.endswith("_done"):
        return "done"
    if t.endswith("_validated"):
        return "validated"
    return "raw"

LAB_VALIDATE_TYPES = (
    "Tất cả",
    "Ventilator",
    "Monitor",
    "Hematology",
    "Biochemistry",
    "Microbiology",
    "Other",
)

LAB_TYPE_ALIASES = {
    "ventilator": "Ventilator",
    "vent": "Ventilator",
    "monitor": "Monitor",
    "hematology": "Hematology",
    "haematology": "Hematology",
    "biochemistry": "Biochemistry",
    "chemistry": "Biochemistry",
    "microbiology": "Microbiology",
    "micro": "Microbiology",
    "other": "Other",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LabRecord:
    record_key: str
    study_id: str
    base_stem: str
    record_type: str
    patient_id: str
    date_token: str
    image_path: str
    pdf_file: str
    json_raw: Optional[str] = None
    json_validated: Optional[str] = None
    json_done: Optional[str] = None
    csv_raw: Optional[str] = None
    csv_validated: Optional[str] = None
    csv_done: Optional[str] = None
    active_json_file: Optional[str] = None
    active_csv_file: Optional[str] = None
    status: str = "pending"
    display_name: str = ""

    def as_dict(self) -> dict:
        return {
            "record_key": self.record_key,
            "study_id": self.study_id,
            "base_stem": self.base_stem,
            "record_type": self.record_type,
            "patient_id": self.patient_id,
            "date_token": self.date_token,
            "image_path": self.image_path,
            "pdf_file": self.pdf_file,
            "json_raw": self.json_raw,
            "json_validated": self.json_validated,
            "json_done": self.json_done,
            "csv_raw": self.csv_raw,
            "csv_validated": self.csv_validated,
            "csv_done": self.csv_done,
            "active_json_file": self.active_json_file,
            "active_csv_file": self.active_csv_file,
            "status": self.status,
            "display_name": self.display_name,
        }


@dataclass
class LabScanResult:
    records: List[dict] = field(default_factory=list)
    processing_roots: List[str] = field(default_factory=list)
    root_dir_error: Optional[str] = None
    # So h\u1ed3 s\u01a1 \u0111\u00e3 hi\u1ec3n th\u1ecb l\u00e0 DONE (c\u1ea3 `_done.json` + `_done.csv`) v\u00e0 b\u1ecb
    # \u1ea9n kh\u1ecfi list v\u00ec ca \u0111\u00e3 ho\u00e0n t\u1ea5t - ch\u1ec9 d\u00f9ng \u0111\u1ec3 th\u00f4ng b\u00e1o tr\u00ean status bar.
    done_count: int = 0
    # Di\u1ec5n bi\u1ebfn qu\u00e1 tr\u00ecnh scan \u0111\u1ec3 UI hi\u1ec3n th\u1ecb th\u00f4ng b\u00e1o r\u00f5 r\u00e0ng khi kh\u00f4ng c\u00f3 record.
    patient_dirs: int = 0
    valid_date_dirs: int = 0
    invalid_date_dirs: int = 0
    image_dirs_missing: int = 0
    # M\u1ed7i item: ``{"path": <image_path>, "files": [..], "missing": "json|csv|json+csv"}``.
    incomplete_groups: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_record_status_suffix(stem: str) -> tuple[str, str]:
    for suffix in ("_validated", "_done"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)], suffix[1:]
    return stem, "raw"


def normalize_lab_record_type(record_type: str) -> str:
    """Map chuỗi lab-type bất kỳ sang 1 trong các giá trị ``LAB_VALIDATE_TYPES``.

    - Bỏ mọi ký tự không phải alphanumeric rồi lower-case.
    - Ưu tiên exact match trong ``LAB_TYPE_ALIASES``.
    - Fallback substring match: nếu 1 alias nằm trong chuỗi đã normalize
      (vd. ``biochemistryimage`` chứa ``biochemistry``) thì lấy alias dài
      nhất để tránh nhầm ``chemistry`` với ``biochemistry``.
    """

    raw = (record_type or "").strip()
    if not raw:
        return "Other"
    normalized = re.sub(r"[^a-z0-9]+", "", raw.lower())
    if not normalized:
        return "Other"

    exact = LAB_TYPE_ALIASES.get(normalized)
    if exact:
        return exact

    best_key = ""
    best_value = "Other"
    for alias_key, alias_val in LAB_TYPE_ALIASES.items():
        if alias_key in normalized and len(alias_key) > len(best_key):
            best_key = alias_key
            best_value = alias_val
    return best_value


def is_valid_date_token(name: str) -> bool:
    """Folder date hợp lệ theo quy ước <ddmmyyyy>.

    Chấp nhận đúng 8 chữ số + tách được thành ngày/tháng/năm thật
    (vd. `15042026`). Trả False cho các folder khác (`backup`, `.tmp`, v.v.)
    để `scan_lab_records` bỏ qua gọn gàng.
    """

    if not DATE_TOKEN_PATTERN.fullmatch(name or ""):
        return False
    try:
        datetime.strptime(name, "%d%m%Y")
    except ValueError:
        return False
    return True


def format_date_token(name: str) -> str:
    """Hiển thị `ddmmyyyy` dạng `dd/mm/yyyy` cho UI; giữ nguyên nếu không đúng format."""

    if is_valid_date_token(name):
        return f"{name[0:2]}/{name[2:4]}/{name[4:8]}"
    return name


def parse_lab_record_type(base_stem: str, patient_id: str) -> str:
    marker = f"_{patient_id}_"
    if marker in base_stem:
        record_type = base_stem.split(marker, 1)[0].strip("_ ")
        if record_type:
            return normalize_lab_record_type(record_type)
    fallback = base_stem.split("_", 1)[0].strip("_ ")
    return normalize_lab_record_type(fallback)


def get_study_id_from_processing_root(
    backend: StorageBackend, processing_root: str
) -> str:
    clean = str(processing_root).rstrip("/\\")
    if backend.is_remote:
        parts = tuple(p for p in clean.split("/") if p)
    else:
        parts = Path(clean).parts

    if len(parts) >= 2 and parts[-1].upper() == "PROCESSING":
        return parts[-2]
    if parts:
        return parts[-1]
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def discover_processing_roots(
    backend: StorageBackend, root_dir: str
) -> List[str]:
    """Trả về danh sách thư mục PROCESSING nằm dưới `root_dir`.

    Chấp nhận các dạng: `.received`, `.received/<studyID>`, hoặc
    `.received/<studyID>/PROCESSING`.
    """

    if not root_dir:
        return []

    roots: List[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        key = str(path).rstrip("/\\")
        if not key or key in seen or not safe_is_dir(backend, path):
            return
        seen.add(key)
        roots.append(path)

    if backend.basename(root_dir).upper() == "PROCESSING":
        _add(root_dir)
        return roots

    _add(backend.join(root_dir, "PROCESSING"))

    try:
        child_names = sorted(backend.listdir(root_dir))
    except Exception:
        return roots

    for child_name in child_names:
        child_path = backend.join(root_dir, child_name)
        if not safe_is_dir(backend, child_path):
            continue
        if child_name.upper() == "PROCESSING":
            _add(child_path)
            continue
        _add(backend.join(child_path, "PROCESSING"))

    return roots


def _collect_file_groups(files: List[str]) -> Dict[tuple, dict]:
    """Nhóm danh sách file trong một ``Image/`` thành các group hồ sơ.

    - File khớp ``LAB_FILENAME_PATTERN`` (pipeline OCR hiện hành với
      subtype ``Image`` / ``Metadata`` + timestamp ``dd.mm.yyyy.hh.mm.ss``)
      được nhóm theo ``(type, patient_id, timestamp)``. Điều này cho phép
      gộp ``BiochemistryImage_...`` (PDF + JSON) với ``BiochemistryMetadata_...``
      (CSV) vào cùng 1 record dù stem khác nhau.
    - File không khớp rơi về nhánh legacy: nhóm theo ``base_stem`` sau khi
      strip ``_validated`` / ``_done`` (giữ tương thích với file cũ không
      có format ``<Type><SubType>_...``).
    """

    groups: Dict[tuple, dict] = {}
    for name in files:
        suffix = Path(name).suffix.lower()
        if suffix not in {".pdf", ".csv", ".json"}:
            continue
        stem = Path(name).stem
        parsed = parse_lab_filename(stem)
        if parsed:
            group_key = (
                "PARSED",
                parsed.type_,
                parsed.patient_id,
                parsed.timestamp,
            )
            status = _status_from_tail(parsed.tail)
        else:
            base_stem, status = strip_record_status_suffix(stem)
            group_key = ("LEGACY", base_stem, "", "")

        group = groups.setdefault(
            group_key,
            {"parsed": parsed, "pdf_stem": None, "files": {}},
        )
        slot = f"{suffix[1:]}_{status}"
        # Giữ file đầu tiên cho mỗi slot. Hiếm khi trùng slot (vd. 2 file
        # `_validated.json` cùng group), nhưng nếu xảy ra thì log cảnh báo.
        if slot in group["files"]:
            log.warning(
                "duplicate slot %s in group %s: already %s, also %s",
                slot,
                group_key,
                group["files"][slot],
                name,
            )
            continue
        group["files"][slot] = name
        if suffix == ".pdf" and status == "raw" and group["pdf_stem"] is None:
            group["pdf_stem"] = stem
    return groups


def build_lab_record_groups(
    study_id: str,
    patient_id: str,
    date_token: str,
    image_path: str,
    files: List[str],
) -> tuple[List[LabRecord], int, List[dict]]:
    """Dựng record từ danh sách file.

    Trả về ``(records, skipped_done, incomplete_groups)``:
    - ``records``: hồ sơ sẽ hiển thị (status ``pending`` hoặc ``validated``).
    - ``skipped_done``: số hồ sơ bị ẩn do có ĐỒNG THỜI ``_done.json`` và
      ``_done.csv`` - những ca đã hoàn tất.
    - ``incomplete_groups``: các group PDF có sẵn nhưng thiếu JSON/CSV để
      giúp UI giải thích cho user tại sao PDF không xuất hiện.
    """

    groups = _collect_file_groups(files)

    records: List[LabRecord] = []
    skipped_done = 0
    incomplete: List[dict] = []
    for group_key in sorted(groups.keys()):
        group = groups[group_key]
        files_dict: Dict[str, str] = group["files"]
        parsed: Optional[LabFilenameParts] = group["parsed"]

        pdf_file = files_dict.get("pdf_raw")
        if not pdf_file:
            # Không có PDF thì không review được - skip im lặng (có thể chỉ
            # là file rác JSON/CSV còn sót).
            continue

        # base_stem dùng cho việc đặt tên `_validated.json` / `_done.json`
        # khi user submit. Với file theo LAB_FILENAME_PATTERN, strip trailing
        # underscore của PDF stem để sinh form chuẩn, vd.
        # `BiochemistryImage_<pid>_14.04.2026.11.52.18` -> thêm `_validated.json`.
        pdf_stem = group["pdf_stem"] or Path(pdf_file).stem
        if parsed:
            base_stem = pdf_stem.rstrip("_")
            record_type = normalize_lab_record_type(parsed.type_)
        else:
            base_stem = group_key[1]
            record_type = parse_lab_record_type(base_stem, patient_id)

        raw_json = files_dict.get("json_raw")
        validated_json = files_dict.get("json_validated")
        done_json = files_dict.get("json_done")
        raw_csv = files_dict.get("csv_raw")
        validated_csv = files_dict.get("csv_validated")
        done_csv = files_dict.get("csv_done")

        has_json = bool(raw_json or validated_json or done_json)
        has_csv = bool(raw_csv or validated_csv or done_csv)
        if not has_json or not has_csv:
            missing = []
            if not has_json:
                missing.append("json")
            if not has_csv:
                missing.append("csv")
            incomplete.append(
                {
                    "path": image_path,
                    "base_stem": base_stem,
                    "pdf": pdf_file,
                    "files": sorted(files),
                    "missing": "+".join(missing),
                }
            )
            log.warning(
                "incomplete record %s (missing %s). Files in %s: %s",
                base_stem,
                "+".join(missing),
                image_path,
                sorted(files),
            )
            continue

        if done_json and done_csv:
            skipped_done += 1
            log.info(
                "skip DONE record: %s/%s/%s/%s",
                study_id,
                patient_id,
                date_token,
                base_stem,
            )
            continue

        status = "validated" if (validated_json and validated_csv) else "pending"

        record_key = f"{study_id}|{patient_id}|{date_token}|{base_stem}"
        records.append(
            LabRecord(
                record_key=record_key,
                study_id=study_id,
                base_stem=base_stem,
                record_type=record_type,
                patient_id=patient_id,
                date_token=date_token,
                image_path=image_path,
                pdf_file=pdf_file,
                json_raw=raw_json,
                json_validated=validated_json,
                json_done=done_json,
                csv_raw=raw_csv,
                csv_validated=validated_csv,
                csv_done=done_csv,
                active_json_file=validated_json or raw_json,
                active_csv_file=validated_csv or raw_csv,
                status=status,
                display_name=(
                    f"[{record_type}] {study_id}/{patient_id}/"
                    f"{format_date_token(date_token)} - {pdf_file}"
                ),
            )
        )
    return records, skipped_done, incomplete


def scan_lab_records(
    backend: StorageBackend, root_dir: Optional[str]
) -> LabScanResult:
    result = LabScanResult()

    if not root_dir:
        result.root_dir_error = "Chưa cấu hình thư mục gốc cho OCR validate."
        return result

    resolved = resolve_existing_data_dir(backend, root_dir)
    if not resolved:
        result.root_dir_error = (
            f"Không truy cập được thư mục gốc: {root_dir}. "
            "Kiểm tra lại SFTP_PATH hoặc study ID trong apps/config.py."
        )
        return result

    result.processing_roots = discover_processing_roots(backend, resolved)
    records: List[dict] = []

    for processing_root in result.processing_roots:
        study_id = get_study_id_from_processing_root(backend, processing_root)

        try:
            patient_dirs = sorted(backend.listdir(processing_root))
        except Exception:
            continue

        for patient_id in patient_dirs:
            patient_path = backend.join(processing_root, patient_id)
            if not safe_is_dir(backend, patient_path):
                continue
            # Folder ẩn / tạm của hệ thống không phải patient_id.
            if patient_id.startswith(".") or patient_id.startswith("_"):
                log.debug("skip non-patient folder: %s", patient_path)
                continue
            result.patient_dirs += 1

            try:
                date_dirs = sorted(backend.listdir(patient_path))
            except Exception:
                continue

            for date_token in date_dirs:
                date_path = backend.join(patient_path, date_token)
                if not safe_is_dir(backend, date_path):
                    continue
                if not is_valid_date_token(date_token):
                    # Chỉ nhận folder đúng format ddmmyyyy. Folder khác
                    # (backup, .tmp, draft...) bị bỏ qua + ghi log để debug.
                    log.debug(
                        "skip folder with invalid date token: %s", date_path
                    )
                    result.invalid_date_dirs += 1
                    continue
                result.valid_date_dirs += 1

                image_path = resolve_named_child_dir(backend, date_path, "Image")
                if not safe_is_dir(backend, image_path):
                    log.warning(
                        "patient %s / date %s: missing Image/ folder at %s",
                        patient_id,
                        date_token,
                        date_path,
                    )
                    result.image_dirs_missing += 1
                    continue

                try:
                    files = backend.listdir(image_path)
                except Exception:
                    continue

                recs, done_count, incomplete = build_lab_record_groups(
                    study_id, patient_id, date_token, image_path, files
                )
                for rec in recs:
                    records.append(rec.as_dict())
                result.done_count += done_count
                result.incomplete_groups.extend(incomplete)

    records.sort(
        key=lambda record: (
            record["study_id"],
            record["patient_id"],
            record["date_token"],
            record["pdf_file"],
        )
    )
    result.records = records
    return result


def build_lab_rows(record: dict, data: dict) -> List[dict]:
    base_row = {
        "record_type": record["record_type"],
        "study_id": record["study_id"],
        "patient_id": record["patient_id"],
        "record_date": record["date_token"],
        "source_pdf": record["pdf_file"],
    }
    for key, value in data.items():
        if key in {"results", "raw_text", "notification", "error"}:
            continue
        base_row[key] = value

    rows: List[dict] = []
    results = data.get("results") or []
    if not results:
        rows.append(dict(base_row))
        return rows
    for result in results:
        row = dict(base_row)
        row.update(result)
        rows.append(row)
    return rows


def confirmed_to_rows(
    folder_name: str, data: dict, ocr_type: str
) -> List[dict]:
    """Chuyển payload JSON confirmed thành rows phẳng để export Excel."""

    if ocr_type == "OCR BEDSIDE MONITOR":
        row = {"folder": folder_name}
        for key, val_obj in data.items():
            if isinstance(val_obj, dict):
                row[key] = val_obj.get("value", "")
            elif isinstance(val_obj, list) and val_obj:
                row[key] = val_obj[0].get("value", "")
            else:
                row[key] = val_obj
        return [row]

    base_info = {
        key: value
        for key, value in data.items()
        if key not in {"results", "raw_text"}
    }
    rows: List[dict] = []
    for result in data.get("results", []):
        if not any(value for value in result.values()):
            continue
        rows.append({"folder": folder_name, **base_info, **result})
    return rows


def normalize_json_stem(json_filename: str) -> str:
    stem = Path(json_filename).stem
    for suffix in ("_confirmed", "_final"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


__all__ = [
    "LAB_VALIDATE_TYPES",
    "DATE_TOKEN_PATTERN",
    "LAB_FILENAME_PATTERN",
    "LabFilenameParts",
    "LabRecord",
    "LabScanResult",
    "scan_lab_records",
    "discover_processing_roots",
    "build_lab_record_groups",
    "build_lab_rows",
    "confirmed_to_rows",
    "parse_lab_filename",
    "parse_lab_record_type",
    "normalize_lab_record_type",
    "normalize_json_stem",
    "strip_record_status_suffix",
    "get_study_id_from_processing_root",
    "is_valid_date_token",
    "format_date_token",
]
