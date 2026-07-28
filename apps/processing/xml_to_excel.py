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

Ngoài danh mục cố định đó, người dùng có thể chọn thêm 1 file Excel mapping
(``services/mapping_excel.py``) để gắn thêm cột vào bản ghi. File này là tuỳ
chọn, do người dùng kiểm soát, và chỉ THÊM cột — không tham gia lọc.

Payload giải mã/parse không được thì bị BỎ, không xuất nội dung thô ra Excel:
bộ lọc PII ở đây chạy trên tên cột (``XML4_EXCLUDED_COLUMNS`` trong
``_sheet_columns``) nên nó không lọc nổi một ô chứa nguyên văn hồ sơ. Số hồ sơ
và số file bị bỏ được đếm và báo lên UI.
"""

import os
import logging
import base64
import zlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from apps.services import mapping_excel, medical_catalog
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

# Hai byte đầu của một stream GZIP.
GZIP_MAGIC = b"\x1f\x8b"

# Trần dung lượng sau khi giải nén 1 payload. Một hồ sơ XML4 thật chỉ vài trăm
# KB; vượt xa mức này thì là file hỏng hoặc "gzip bomb" (vài KB base64 nở ra
# hàng GB). Không chặn thì 8 luồng chạy song song đủ làm app hết RAM.
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024

# Số tên file tối đa liệt kê trong cảnh báo (tránh hộp thoại dài vô tận).
MAX_LISTED_FAILED_FILES = 5


def _gunzip_bounded(data):
    """Giải nén GZIP có trần dung lượng. Trả ``None`` nếu hỏng hoặc quá lớn."""

    dobj = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)  # 16 = đọc header GZIP
    try:
        out = dobj.decompress(data, MAX_DECOMPRESSED_BYTES)
    except zlib.error as e:
        log.warning("Stream GZIP hỏng, bỏ qua payload: %s", e)
        return None

    if dobj.unconsumed_tail or not dobj.eof:
        log.warning(
            "Payload GZIP vượt trần %d byte hoặc bị cắt cụt — bỏ qua.",
            MAX_DECOMPRESSED_BYTES,
        )
        return None
    return out


def decode_base64_content(b64_string):
    try:
        decoded_bytes = base64.b64decode(b64_string)
    except Exception as e:
        log.warning("Giải mã Base64 thất bại: %s", e)
        return None

    # Không có magic GZIP → nội dung để trần, dùng nguyên bytes đã giải Base64.
    if decoded_bytes.startswith(GZIP_MAGIC):
        decoded_bytes = _gunzip_bounded(decoded_bytes)
        if decoded_bytes is None:
            return None

    try:
        return decoded_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        log.warning("Giải mã văn bản thất bại sau Base64/GZIP: %s", e)
        return None


def parse_inner_xml(xml_string):
    """Parse XML con đã giải mã. Trả ``None`` nếu không parse được.

    KHÔNG bao giờ trả nội dung thô ra ngoài. Bản cũ nhét cả payload vào một ô
    ``RAW_CONTENT`` khi parse lỗi; bản ghi đó không có ``MA_DICH_VU`` nên rơi
    vào sheet "chưa phân loại" và mang theo NGUYÊN VĂN hồ sơ — gồm cả các
    trường trong ``XML4_EXCLUDED_COLUMNS``. Bộ lọc cột chỉ chạy ở
    ``_sheet_columns()``, tức là chạy trên TÊN cột, nên nó không thể lọc được
    thứ đã bị gộp vào trong một ô. Payload hỏng nay chỉ được đếm và báo lên UI.
    """

    try:
        return _extract_all_records(ET.fromstring(xml_string.strip()))
    except ET.ParseError as e:
        log.warning("Payload XML4 không parse được, bỏ qua: %s", e)
        return None


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
    """Giải mã mọi FILEHOSO loại XML4 trong 1 file.

    Trả ``(records, n_payload_loi)`` — ``n_payload_loi`` là số payload XML4
    giải mã/parse không được. Phải trả về để ``_collect_and_save`` còn báo cho
    người dùng biết có bao nhiêu hồ sơ đã bị bỏ, thay vì chỉ ghi vào log.
    """

    filename = os.path.basename(xml_filepath)
    records_out = []
    n_bad = 0

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
            n_bad += 1
            continue
        records = parse_inner_xml(decoded_xml)
        if records is None:
            n_bad += 1
            continue
        file_id = os.path.splitext(filename)[0]
        for rec in records:
            if "ID" in rec:
                rec["ID_GOC"] = rec["ID"]
            rec["ID"] = file_id
        records_out.extend(records)

    return records_out, n_bad


def _sheet_columns(records, extra_columns=()):
    """Cột của 1 sheet: ID đứng đầu, Name_Method nằm ngay sau MA_DICH_VU.

    ``extra_columns`` (các cột từ file mapping) luôn được đưa vào cuối, kể cả
    khi không bản ghi nào khớp — người dùng đã chọn file mapping thì phải thấy
    cột của nó, dù rỗng, mới biết là không khớp được gì.
    """

    columns = ["ID"] + [
        k for k in collect_columns(records)
        if k not in ("ID", NAME_METHOD_COLUMN) and k not in XML4_EXCLUDED_COLUMNS
        and k not in extra_columns
    ]
    if SERVICE_CODE_COLUMN in columns:
        columns.insert(columns.index(SERVICE_CODE_COLUMN) + 1, NAME_METHOD_COLUMN)
    else:
        columns.append(NAME_METHOD_COLUMN)
    return columns + list(extra_columns)


def _split_by_catalog(records, catalog):
    """Chia bản ghi theo nhóm trong danh mục.

    Trả ``(included, unclassified, n_excluded)``. Group lạ (không phải
    Include/Exclude) được xếp vào nhóm chưa phân loại thay vì bị loại — sai
    chính tả trong danh mục không được âm thầm làm mất dữ liệu. Việc cảnh báo
    Group lạ do ``medical_catalog`` lo một lần lúc nạp file, không lặp lại ở đây.

    Lưu ý: hàm SỬA TRỰC TIẾP các dict trong ``records`` (gắn thêm cột
    ``Name_Method``) thay vì copy — bản ghi có thể tới hàng trăm nghìn dòng,
    nhân đôi lên chỉ để giữ tính "thuần" là không đáng. Bản ghi thuộc nhóm
    Exclude không được gắn gì vì đằng nào cũng bị bỏ.
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


def _apply_mapping(records, mapping):
    """Gắn các cột từ file mapping vào bản ghi khớp khoá. Trả số bản ghi khớp.

    Bản ghi không khớp vẫn được điền chuỗi rỗng cho đủ cột — để trống hẳn thì
    ``rec.get(c, "")`` lúc ghi Excel cũng ra rỗng, nhưng điền sẵn giúp
    ``collect_columns`` nhìn thấy cột và giữ thứ tự ổn định.

    Sửa trực tiếp dict trong ``records``, cùng lý do với ``_split_by_catalog``.
    """

    n_matched = 0
    blank = {column: "" for column in mapping.value_columns}
    for rec in records:
        found = mapping.lookup(rec.get(mapping.key_column))
        if found is None:
            rec.update(blank)
        else:
            rec.update(found)
            n_matched += 1
    return n_matched


def _dropped_input_warning(failed_files, n_bad_payloads):
    """Câu cảnh báo về phần dữ liệu đầu vào đã bị bỏ. Rỗng nếu không mất gì.

    Với dữ liệu y tế, "đọc được bao nhiêu" quan trọng ngang "xuất ra bao
    nhiêu": người dùng phải biết ngay trên UI là có file/hồ sơ bị bỏ, chứ
    không phải đi mò trong log.
    """

    parts = []
    if failed_files:
        listed = ", ".join(failed_files[:MAX_LISTED_FAILED_FILES])
        if len(failed_files) > MAX_LISTED_FAILED_FILES:
            listed += f", …(+{len(failed_files) - MAX_LISTED_FAILED_FILES})"
        parts.append(f"{len(failed_files)} file không đọc được: {listed}")
    if n_bad_payloads:
        parts.append(f"{n_bad_payloads} hồ sơ {TARGET_LOAIHOSO} hỏng đã bị bỏ")
    if not parts:
        return ""
    return "\n⚠ " + "; ".join(parts) + ". Xem log để biết chi tiết."


def _collect_and_save(xml_files, output_path, mapping_path=None):
    from openpyxl import Workbook

    if not xml_files:
        return False, "Chưa chọn file XML nào!"

    # Nạp danh mục TRƯỚC khi giải mã: thiếu nó thì không lọc được, và xuất ra
    # file chưa lọc còn nguy hiểm hơn là báo lỗi.
    try:
        catalog = medical_catalog.load_catalog()
    except medical_catalog.CatalogError as e:
        return False, str(e)

    # Mapping cũng nạp trước khi giải mã: file mapping sai thì báo ngay, thay
    # vì bắt người dùng chờ hết mấy phút decode rồi mới đổ lỗi.
    mapping = None
    if mapping_path:
        try:
            mapping = mapping_excel.load_mapping(
                mapping_path,
                reserved_columns=(
                    {"ID", "ID_GOC", NAME_METHOD_COLUMN} | XML4_EXCLUDED_COLUMNS
                ),
            )
        except mapping_excel.MappingError as e:
            return False, f"Lỗi file mapping — {e}"

    all_records = []
    failed_files = []
    n_bad_payloads = 0
    max_workers = min(8, len(xml_files), os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_file = {pool.submit(process_xml_file, xf): xf for xf in xml_files}
        for future in as_completed(future_to_file):
            xf = future_to_file[future]
            try:
                records, n_bad = future.result()
            except Exception as e:
                # Đếm để còn báo lên UI: chỉ ghi log thì người dùng thấy
                # "Hoàn thành!" mà không biết 1/5 số file đã bị bỏ qua.
                log.warning("Lỗi xử lý %s: %s", xf, e)
                failed_files.append(os.path.basename(xf))
                continue
            all_records.extend(records)
            n_bad_payloads += n_bad

    warning = _dropped_input_warning(failed_files, n_bad_payloads)

    if not all_records:
        return False, (
            f"Không có dữ liệu {TARGET_LOAIHOSO} trong các file đã chọn!{warning}"
        )

    included, unclassified, n_excluded = _split_by_catalog(all_records, catalog)
    if not included and not unclassified:
        return False, (
            f"Toàn bộ {n_excluded} bản ghi đều thuộc nhóm Exclude — "
            f"không còn gì để xuất.{warning}"
        )

    mapping_columns = ()
    mapping_note = ""
    if mapping is not None:
        mapping_columns = mapping.value_columns
        n_matched = (
            _apply_mapping(included, mapping) + _apply_mapping(unclassified, mapping)
        )
        mapping_note = (
            f"\nMapping '{mapping.source_name}' (join theo {mapping.key_column}): "
            f"{n_matched}/{len(included) + len(unclassified)} bản ghi khớp."
        )

    # write_only: openpyxl ghi thẳng từng dòng ra file thay vì dựng toàn bộ đối
    # tượng Cell trong RAM. Một lô XML4 lớn có thể lên hàng trăm nghìn dòng.
    wb = Workbook(write_only=True)
    for title, records in (
        (SHEET_INCLUDE, included),
        (SHEET_UNCLASSIFIED, unclassified),
    ):
        if not records:
            continue
        ws = wb.create_sheet(title=sanitize_sheet_name(title, default="Sheet"))
        columns = _sheet_columns(records, mapping_columns)
        # append_row_as_text: giá trị xét nghiệm kiểu "=<0.5" phải giữ nguyên
        # văn bản, không được biến thành công thức Excel.
        append_row_as_text(ws, columns)
        for rec in records:
            append_row_as_text(ws, [rec.get(c, "") for c in columns])

    wb.save(output_path)
    return True, (
        f"Hoàn thành! {len(included)} bản ghi Include, "
        f"{len(unclassified)} chưa có trong danh mục, "
        f"{n_excluded} bị loại (Exclude).{mapping_note}{warning}"
    )


def run_xml_to_excel(xml_files, output_path, callback, mapping_path=None):
    """Giải mã XML4 song song, đối chiếu danh mục và xuất Excel.

    ``mapping_path`` là file Excel mapping tuỳ chọn của người dùng; bỏ trống
    thì luồng xử lý y như cũ.
    """
    try:
        success, msg = _collect_and_save(xml_files, output_path, mapping_path)
    except Exception as e:
        success, msg = False, f"Lỗi: {e}"
    callback(success, msg)
