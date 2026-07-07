"""Xử lý XML → Excel: giải mã Base64 các FILEHOSO loại XML3/XML4, xuất Excel.

XML3 chỉ lấy các cột trong XML3_COLUMNS; XML4 lấy hết trừ XML4_EXCLUDED_COLUMNS.
Mỗi loại hồ sơ xuất ra 1 sheet riêng.
"""

import os
import logging
import base64
import gzip
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from apps.services.excel_export import sanitize_sheet_name

log = logging.getLogger(__name__)

# Chỉ xuất các loại hồ sơ này ra Excel.
ALLOWED_LOAIHOSO = {"XML3", "XML4"}

# XML3: chỉ lấy đúng các cột này (theo thứ tự, không lấy cột nào khác).
XML3_COLUMNS = [
    "MA_LK", "STT", "MA_DICH_VU", "MA_PTTT", "MA_VAT_TU",
    "MA_NHOM", "GOI_YTYT", "TEN_VAT_TU", "TEN_DICH_VU",
]

# XML4: lấy hết các cột, trừ những cột này.
XML4_EXCLUDED_COLUMNS = {"MA_BS_DOC_KQ"}


def decode_base64_content(b64_string):
    try:
        decoded_bytes = base64.b64decode(b64_string)
    except Exception as e:
        log.warning("Giải mã Base64 thất bại: %s", e)
        return None

    try:
        decoded_bytes = gzip.decompress(decoded_bytes)
    except OSError:
        pass  # nội dung không nén GZIP, dùng nguyên bytes đã giải Base64

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
    filename = os.path.basename(xml_filepath)
    results = defaultdict(list)

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
        if loai_hoso not in ALLOWED_LOAIHOSO:
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
        results[loai_hoso].extend(records)

    return results


def _sheet_columns(records, loai=None):
    """Trả về danh sách cột cho 1 sheet: ID đứng đầu, phần còn lại tuỳ loại hồ sơ."""
    all_keys = list(dict.fromkeys(k for r in records for k in r))
    if loai == "XML3":
        return ["ID"] + [k for k in XML3_COLUMNS if k in all_keys]
    if loai == "XML4":
        return ["ID"] + [k for k in all_keys if k != "ID" and k not in XML4_EXCLUDED_COLUMNS]
    return ["ID"] + [k for k in all_keys if k != "ID"]


def _collect_and_save(xml_files, output_path):
    from openpyxl import Workbook

    all_results = defaultdict(list)
    max_workers = min(8, len(xml_files), os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_file = {pool.submit(process_xml_file, xf): xf for xf in xml_files}
        for future in as_completed(future_to_file):
            xf = future_to_file[future]
            try:
                file_results = future.result()
                for loai, records in file_results.items():
                    all_results[loai].extend(records)
            except Exception as e:
                log.warning("Lỗi xử lý %s: %s", xf, e)

    if not all_results:
        return False, "Không có dữ liệu XML trong các file đã chọn!"

    wb = Workbook()
    wb.remove(wb.active)  # bỏ sheet mặc định, tạo sheet theo từng loại XML
    total = 0
    for loai in sorted(all_results):
        records = all_results[loai]
        if not records:
            continue
        ws = wb.create_sheet(title=sanitize_sheet_name(loai, default="Sheet"))
        columns = _sheet_columns(records, loai)
        ws.append(columns)
        for rec in records:
            ws.append([rec.get(c, "") for c in columns])
        total += len(records)

    if not wb.sheetnames:
        return False, "Không có bản ghi nào để xuất!"

    wb.save(output_path)
    sheets = ", ".join(wb.sheetnames)
    return True, f"Hoàn thành! {total} bản ghi đã xuất ({len(wb.sheetnames)} sheet: {sheets})."


def run_xml_to_excel(xml_files, output_path, callback):
    """Xử lý danh sách XML files song song và xuất Excel (mỗi loại XML 1 sheet)."""
    try:
        success, msg = _collect_and_save(xml_files, output_path)
    except Exception as e:
        success, msg = False, f"Lỗi: {e}"
    callback(success, msg)
