"""Xử lý XML → Excel: giải mã Base64, trích xuất mọi loại XML (trừ XML1), xuất Excel."""

import os
import logging
import base64
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

# Loại hồ sơ KHÔNG xuất ra Excel.
SKIP_LOAIHOSO = {"XML1"}

# Các cột thông tin cá nhân / định danh bệnh nhân -> luôn loại bỏ.
# Lưu ý: MA_LK (mã liên kết hồ sơ) là mã ẩn danh dùng để nối các bản ghi
# của cùng một lần khám giữa các loại XML nên KHÔNG nằm trong danh sách này.
PERSONAL_COLUMNS = {
    "HO_TEN", "TEN_BENH_NHAN", "DIA_CHI", "DIACHI",
    "DIEN_THOAI", "DIENTHOAI", "MA_THE", "MA_THE_BHYT",
    "SO_CCCD", "CCCD", "SO_CMND", "CMND",
    "NGAYSINH", "NGAY_SINH",
}


def decode_base64_content(b64_string):
    try:
        decoded_bytes = base64.b64decode(b64_string)
        try:
            return decoded_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return decoded_bytes.decode("utf-8")
    except Exception:
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
        loai_hoso = loai_node.text.strip() if loai_node.text else "UNKNOWN"
        if loai_hoso in SKIP_LOAIHOSO:
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
            rec["ID"] = file_id
        results[loai_hoso].extend(records)

    return results


def _sheet_columns(records):
    """Trả về danh sách cột cho 1 sheet: ID đứng đầu, bỏ cột cá nhân."""
    all_keys = list(dict.fromkeys(k for r in records for k in r))
    filtered_keys = [k for k in all_keys
                     if k not in PERSONAL_COLUMNS and k != "ID"]
    return ["ID"] + filtered_keys


def run_xml_to_excel(xml_files, output_path, callback):
    """Xử lý danh sách XML files song song và xuất Excel (mỗi loại XML 1 sheet)."""
    try:
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
            callback(False, "Không có dữ liệu XML (ngoài XML1) trong các file đã chọn!")
            return

        wb = Workbook()
        wb.remove(wb.active)  # bỏ sheet mặc định, tạo sheet theo từng loại XML
        total = 0
        for loai in sorted(all_results):
            records = all_results[loai]
            if not records:
                continue
            ws = wb.create_sheet(title=loai[:31])
            columns = _sheet_columns(records)
            ws.append(columns)
            for rec in records:
                ws.append([rec.get(c, "") for c in columns])
            total += len(records)

        if not wb.sheetnames:
            callback(False, "Không có bản ghi nào để xuất!")
            return

        wb.save(output_path)
        sheets = ", ".join(wb.sheetnames)
        callback(True, f"Hoàn thành! {total} bản ghi đã xuất ({len(wb.sheetnames)} sheet: {sheets}).")
    except Exception as e:
        callback(False, f"Lỗi: {e}")
