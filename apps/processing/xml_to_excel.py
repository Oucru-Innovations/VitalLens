"""Xử lý XML → Excel: giải mã Base64 các FILEHOSO loại XML4, xuất Excel.

Chỉ XML4 được xử lý; các loại hồ sơ khác (XML1/2/3/…) bị bỏ qua hoàn toàn.

Mỗi bản ghi được đối chiếu với danh mục dịch vụ (``database_medical.csv``)
qua ``MA_DICH_VU`` = ``ID_SERVICE`` để lấy tên phương pháp (``Name_Method``)
và nhóm lọc:

    Include                   -> sheet chính
    Exclude                   -> loại khỏi kết quả
    (không có trong danh mục)  -> sheet riêng để rà soát thủ công

Bản ghi thiếu ``MA_DICH_VU`` cũng vào sheet "chưa phân loại" — không có mã thì
không thể khẳng định là Exclude, nên không được lặng lẽ vứt đi.
"""

import os
import logging
import base64
import gzip
import zlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from apps.services import medical_catalog
from apps.services.excel_export import (
    append_row_as_text,
    collect_columns,
    sanitize_sheet_name,
)

log = logging.getLogger(__name__)

# Loại hồ sơ duy nhất được xuất ra Excel.
TARGET_LOAIHOSO = "XML4"

# XML4: lấy hết các cột, trừ những cột này.
XML4_EXCLUDED_COLUMNS = {"MA_BS_DOC_KQ"}

# Cột mã dịch vụ trong XML4 và cột tên tra được từ danh mục.
SERVICE_CODE_COLUMN = "MA_DICH_VU"
NAME_METHOD_COLUMN = medical_catalog.COL_NAME

# Tên sheet (ASCII: sanitize_sheet_name thay dấu tiếng Việt bằng "_").
SHEET_INCLUDE = "XML4_Include"
SHEET_UNCLASSIFIED = "XML4_ChuaPhanLoai"


def decode_base64_content(b64_string):
    try:
        decoded_bytes = base64.b64decode(b64_string)
    except Exception as e:
        log.warning("Giải mã Base64 thất bại: %s", e)
        return None

    try:
        decoded_bytes = gzip.decompress(decoded_bytes)
    except (OSError, EOFError, zlib.error):
        # Không nén GZIP (BadGzipFile là OSError) → dùng nguyên bytes đã giải
        # Base64. EOFError/zlib.error = stream GZIP cụt hoặc hỏng: vẫn nuốt ở
        # đây để chỉ mất đúng payload này, thay vì ném lên và làm hỏng toàn bộ
        # file XML đang xử lý.
        pass

    try:
        return decoded_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return decoded_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            log.warning("Giải mã văn bản thất bại sau Base64/GZIP: %s", e)
            return None


def parse_inner_xml(xml_string):
    records = []
    try:
        xml_string = xml_string.strip()
        root = ET.fromstring(xml_string)
        records = _extract_all_records(root)
    except ET.ParseError:
        records.append({"RAW_CONTENT": xml_string[:32000]})
    return records


def _extract_all_records(root):
    records = []
    list_parents = []
    for child in root:
        grandchildren = list(child)
        if grandchildren:
            if any(list(gc) for gc in grandchildren):
                list_parents.append(child)

    for list_parent in list_parents:
        for item in list_parent:
            sub_children = list(item)
            if sub_children:
                record = {}
                for field in sub_children:
                    field_children = list(field)
                    if not field_children:
                        text = (field.text or "").strip()
                        record[field.tag] = text
                    else:
                        texts = [s.text.strip() for s in field.iter()
                                 if s.text and s.text.strip()]
                        record[field.tag] = "; ".join(texts)
                if record:
                    records.append(record)

    if not records:
        record = {}
        for child in root:
            sub_children = list(child)
            if not sub_children:
                record[child.tag] = (child.text or "").strip()
            else:
                for gc in sub_children:
                    if not list(gc):
                        record[f"{child.tag}_{gc.tag}"] = (gc.text or "").strip()
        if record:
            records.append(record)
    return records


def process_xml_file(xml_filepath):
    """Giải mã mọi FILEHOSO loại XML4 trong 1 file, trả về list bản ghi."""

    filename = os.path.basename(xml_filepath)
    records_out = []

    try:
        tree = ET.parse(xml_filepath)
        root = tree.getroot()
    except ET.ParseError:
        with open(xml_filepath, "r", encoding="utf-8-sig") as f:
            content = f.read()
        root = ET.fromstring(content)

    file_hoso_list = root.findall(".//FILEHOSO")
    for fh in file_hoso_list:
        loai_node = fh.find("LOAIHOSO")
        content_node = fh.find("NOIDUNGFILE")
        if loai_node is None or content_node is None:
            continue
        loai_hoso = (loai_node.text or "").strip()
        if loai_hoso != TARGET_LOAIHOSO:
            continue
        b64_content = content_node.text.strip() if content_node.text else ""
        if not b64_content:
            continue
        decoded_xml = decode_base64_content(b64_content)
        if decoded_xml is None:
            continue
        records = parse_inner_xml(decoded_xml)
        file_id = os.path.splitext(filename)[0]
        for rec in records:
            if "ID" in rec:
                rec["ID_GOC"] = rec["ID"]
            rec["ID"] = file_id
        records_out.extend(records)

    return records_out


def _sheet_columns(records):
    """Cột của 1 sheet: ID đứng đầu, Name_Method nằm ngay sau MA_DICH_VU."""

    columns = ["ID"] + [
        k for k in collect_columns(records)
        if k not in ("ID", NAME_METHOD_COLUMN) and k not in XML4_EXCLUDED_COLUMNS
    ]
    if SERVICE_CODE_COLUMN in columns:
        columns.insert(columns.index(SERVICE_CODE_COLUMN) + 1, NAME_METHOD_COLUMN)
    else:
        columns.append(NAME_METHOD_COLUMN)
    return columns


def _split_by_catalog(records, catalog):
    """Chia bản ghi theo nhóm trong danh mục.

    Trả ``(included, unclassified, n_excluded)``. Bản ghi giữ lại được gắn
    thêm cột ``Name_Method``. Group lạ (không phải Include/Exclude) được xếp
    vào nhóm chưa phân loại thay vì bị loại — sai chính tả trong danh mục
    không được âm thầm làm mất dữ liệu. Việc cảnh báo Group lạ do
    ``medical_catalog`` lo một lần lúc nạp file, không lặp lại ở đây.
    """

    included, unclassified, n_excluded = [], [], 0
    for rec in records:
        entry = medical_catalog.lookup(catalog, rec.get(SERVICE_CODE_COLUMN))
        if entry is None:
            rec[NAME_METHOD_COLUMN] = ""
            unclassified.append(rec)
        elif entry.group == medical_catalog.GROUP_EXCLUDE:
            n_excluded += 1
        elif entry.group == medical_catalog.GROUP_INCLUDE:
            rec[NAME_METHOD_COLUMN] = entry.name_method
            included.append(rec)
        else:
            rec[NAME_METHOD_COLUMN] = entry.name_method
            unclassified.append(rec)
    return included, unclassified, n_excluded


def _collect_and_save(xml_files, output_path):
    from openpyxl import Workbook

    if not xml_files:
        return False, "Chưa chọn file XML nào!"

    # Nạp danh mục TRƯỚC khi giải mã: thiếu nó thì không lọc được, và xuất ra
    # file chưa lọc còn nguy hiểm hơn là báo lỗi.
    try:
        catalog = medical_catalog.load_catalog()
    except medical_catalog.CatalogError as e:
        return False, str(e)

    all_records = []
    max_workers = min(8, len(xml_files), os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_file = {pool.submit(process_xml_file, xf): xf for xf in xml_files}
        for future in as_completed(future_to_file):
            xf = future_to_file[future]
            try:
                all_records.extend(future.result())
            except Exception as e:
                log.warning("Lỗi xử lý %s: %s", xf, e)

    if not all_records:
        return False, f"Không có dữ liệu {TARGET_LOAIHOSO} trong các file đã chọn!"

    included, unclassified, n_excluded = _split_by_catalog(all_records, catalog)
    if not included and not unclassified:
        return False, (
            f"Toàn bộ {n_excluded} bản ghi đều thuộc nhóm Exclude — "
            f"không còn gì để xuất."
        )

    wb = Workbook()
    wb.remove(wb.active)  # bỏ sheet mặc định
    for title, records in (
        (SHEET_INCLUDE, included),
        (SHEET_UNCLASSIFIED, unclassified),
    ):
        if not records:
            continue
        ws = wb.create_sheet(title=sanitize_sheet_name(title, default="Sheet"))
        columns = _sheet_columns(records)
        # append_row_as_text: giá trị xét nghiệm kiểu "=<0.5" phải giữ nguyên
        # văn bản, không được biến thành công thức Excel.
        append_row_as_text(ws, columns)
        for rec in records:
            append_row_as_text(ws, [rec.get(c, "") for c in columns])

    wb.save(output_path)
    return True, (
        f"Hoàn thành! {len(included)} bản ghi Include, "
        f"{len(unclassified)} chưa có trong danh mục, "
        f"{n_excluded} bị loại (Exclude)."
    )


def run_xml_to_excel(xml_files, output_path, callback):
    """Giải mã XML4 song song, đối chiếu danh mục và xuất Excel."""
    try:
        success, msg = _collect_and_save(xml_files, output_path)
    except Exception as e:
        success, msg = False, f"Lỗi: {e}"
    callback(success, msg)
