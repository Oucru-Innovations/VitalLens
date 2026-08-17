"""Danh mục dịch vụ y tế (``database_medical.csv``) — tra tên và nhóm lọc.

Khoá tra cứu là cột ``ID_SERVICE``, khớp với ``MA_DICH_VU`` trong hồ sơ XML4.
Cột ``Group`` quyết định số phận của bản ghi khi xuất Excel:

    Include                    -> giữ lại, xuất ra sheet chính
    Exclude                    -> loại hẳn khỏi kết quả
    (không có trong danh mục)  -> đẩy sang sheet riêng để rà soát thủ công

Danh mục là **dữ liệu cố định của bản phát hành**, không phải file cấu hình
người dùng chỉnh được:

- Bản đóng gói (EXE): chỉ đọc từ thư mục tài nguyên bên trong gói
  (``apps.runtime_paths.bundle_dir()`` — ``_internal/`` với PyInstaller, thư
  mục bung tạm với Nuitka onefile). Bản phát hành **không** kèm bản CSV rời
  cạnh EXE nữa, nên sửa file cạnh EXE không còn tác dụng gì.
- Bản chạy từ source: đọc từ ``<APP_DIR>/database/`` (máy dev là môi trường
  tin cậy, và không có thư mục gói để đọc).

Mọi lần nạp đều đối chiếu SHA-256 với ``CATALOG_SHA256`` hardcode trong file
này. Vân tay nằm trong source nên nằm trong git: đổi danh mục bắt buộc phải
đi qua commit + review + build lại, và ``build_exe.spec`` cũng chặn ngay lúc
build nếu CSV không khớp hằng số. Sửa file trong ``_internal/`` sau khi cài
sẽ làm chức năng XML4 **dừng hẳn với thông báo lỗi**, thay vì âm thầm xuất ra
kết quả lọc theo một danh mục khác.

Giới hạn cần biết: đây là chống sửa **vô tình và tuỳ tiện**, không phải chống
kẻ tấn công có toàn quyền trên máy. Người dùng có quyền admin luôn có thể
giải nén bundle, sửa CSV rồi vá luôn hằng số trong bytecode. Muốn bảo đảm
thật sự thì danh mục (hoặc chính bước lọc) phải nằm phía server.

Kết quả đọc được cache theo (đường dẫn, mtime, size) để mở nhiều lô XML liên
tiếp không phải parse lại 9k dòng. Dict trả về là read-only
(``MappingProxyType``) — caller lỡ tay ghi vào đó sẽ làm hỏng cache dùng
chung cho cả phiên chạy.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional

from apps.config import APP_DIR
from apps.runtime_paths import bundle_dir

log = logging.getLogger(__name__)

CATALOG_DIRNAME = "database"
CATALOG_FILENAME = "database_medical.csv"

# Vân tay SHA-256 của bản danh mục được duyệt.
#
# Cập nhật danh mục = thay file CSV + thay hằng số này trong CÙNG một commit,
# rồi build lại. Không khớp thì `build_exe.spec` chặn lúc build và
# `load_catalog()` chặn lúc chạy. Lấy giá trị mới bằng:
#
#     python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('database/database_medical.csv').read_bytes()).hexdigest())"
#
# (thông báo lỗi khi lệch cũng in sẵn vân tay đọc được, copy thẳng vào đây).
CATALOG_SHA256 = "8b3b677dbcb32ec34d239fea7a0f1534b0eac89c9c476d61e244a3e12dbcab21"

# Tên cột trong file CSV.
COL_ID = "ID_SERVICE"
COL_NAME = "Name_Method"
COL_GROUP = "Group"

# Giá trị cột Group sau khi normalize về lowercase.
GROUP_INCLUDE = "include"
GROUP_EXCLUDE = "exclude"
KNOWN_GROUPS = frozenset({GROUP_INCLUDE, GROUP_EXCLUDE})

# Số mã tối đa liệt kê trong cảnh báo Group lạ (tránh log dài vô ích).
_MAX_LISTED_CODES = 10


class CatalogError(Exception):
    """Không nạp được danh mục. Message được viết cho người dùng cuối đọc."""


@dataclass(frozen=True)
class CatalogEntry:
    """Một dòng trong danh mục (chỉ giữ phần cần cho việc lọc/tra tên)."""

    name_method: str
    group: str  # đã lowercase: "include" / "exclude" / giá trị lạ khác


Catalog = Mapping[str, CatalogEntry]

# Cache 1 ô: ((path, mtime, size), danh mục đã parse) — hoặc None khi chưa nạp.
#
# Gộp khoá và giá trị vào MỘT biến để việc cập nhật là một phép gán nguyên tử.
# Tách làm hai biến thì `_cache_key, _cache_value = ...` biên dịch ra hai lệnh
# STORE_GLOBAL, và `_collect_and_save` chạy trên thread nền nên một luồng khác
# có thể đọc được khoá mới đi kèm giá trị cũ.
_cache: tuple | None = None
_cache_lock = threading.Lock()


def catalog_search_paths() -> List[Path]:
    """Vị trí file danh mục — bản đóng gói KHÔNG đọc file cạnh EXE.

    Khi chạy dạng EXE, chỉ đọc trong bundle. Đây chính là chỗ chặn
    việc người dùng thả một CSV khác cạnh ``VitalLens.exe`` để đổi kết quả lọc:
    app không nhìn tới đường dẫn đó nữa.
    """

    bundle = bundle_dir()
    if bundle is not None:
        return [bundle / CATALOG_DIRNAME / CATALOG_FILENAME]
    return [Path(APP_DIR) / CATALOG_DIRNAME / CATALOG_FILENAME]


def normalize_service_code(code) -> str:
    """Chuẩn hoá mã dịch vụ để so khớp (bỏ khoảng trắng, không phân biệt hoa/thường).

    Vài mã trong danh mục có chữ cái thường (``27.205b.0463``) nên phải fold
    hoa/thường; đã kiểm tra là việc này không gây trùng khoá.
    """

    return str(code or "").strip().upper()


def _warn_unknown_groups(path: Path, unknown: Dict[str, List[str]]) -> None:
    """Cảnh báo MỘT LẦN cho mỗi giá trị Group lạ, kèm vài mã ví dụ.

    Group sai chính tả là lỗi của file danh mục, không phải của từng bản ghi
    XML — cảnh báo ở đây (9k dòng, chi phí có chặn trên) thay vì trong vòng
    lặp phân loại (có thể hàng trăm nghìn dòng).
    """

    for group, codes in sorted(unknown.items()):
        sample = ", ".join(codes[:_MAX_LISTED_CODES])
        extra = f" (và {len(codes) - _MAX_LISTED_CODES} mã khác)" if (
            len(codes) > _MAX_LISTED_CODES
        ) else ""
        log.warning(
            "%s: Group=%r không phải %s/%s — %d mã sẽ vào nhóm chưa phân "
            "loại: %s%s",
            path, group, GROUP_INCLUDE, GROUP_EXCLUDE, len(codes), sample, extra,
        )


def _read_verified_text(path: Path) -> str:
    """Đọc file danh mục sau khi đối chiếu vân tay. Ném ``CatalogError`` nếu lệch.

    Hash TRƯỚC khi parse: file đã bị sửa thì không được phép đi tiếp, kể cả
    khi nó vẫn là CSV hợp lệ — đó mới đúng là trường hợp nguy hiểm (kết quả
    lọc sai mà không ai biết).

    Đọc file đúng MỘT lần rồi hash chính bytes đó. Hash một lần và đọc lại lần
    nữa sẽ để lọt khe TOCTOU: file bị thay giữa hai lần đọc thì cái được parse
    không phải cái đã được kiểm. Đằng nào cũng cần toàn bộ nội dung để parse,
    nên đọc một lần còn rẻ hơn.
    """

    try:
        raw = path.read_bytes()
    except OSError as e:
        raise CatalogError(f"không đọc được file ({e})") from e

    digest = hashlib.sha256(raw).hexdigest()
    if digest != CATALOG_SHA256:
        raise CatalogError(
            f"vân tay SHA-256 không khớp — file đã bị sửa hoặc hỏng.\n"
            f"      đọc được: {digest}\n"
            f"      cần có  : {CATALOG_SHA256}\n"
            f"      Cài lại bản phát hành gốc; danh mục không được sửa tại chỗ."
        )

    try:
        # utf-8-sig: file danh mục có BOM.
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        # Chỉ xảy ra khi CATALOG_SHA256 được cập nhật theo một file lưu sai
        # encoding (mở bằng Excel trên Windows tiếng Việt rồi Save mặc định →
        # cp1258/cp1252). Hash khớp nhưng nội dung vẫn không dùng được.
        raise CatalogError(
            f"không phải UTF-8 ({e.reason} tại byte {e.start}). "
            f"Mở lại file và lưu dạng 'CSV UTF-8'."
        ) from e


def _parse_catalog_file(path: Path) -> Catalog:
    """Parse 1 file danh mục. Ném ``CatalogError`` nếu file không dùng được."""

    entries: Dict[str, CatalogEntry] = {}
    unknown_groups: Dict[str, List[str]] = {}
    content = _read_verified_text(path)

    try:
        reader = csv.DictReader(io.StringIO(content))
        missing = {COL_ID, COL_NAME, COL_GROUP} - set(reader.fieldnames or [])
        if missing:
            raise CatalogError(
                f"thiếu cột bắt buộc: {', '.join(sorted(missing))}"
            )

        for row in reader:
            code = normalize_service_code(row.get(COL_ID))
            if not code:
                continue
            if code in entries:
                # Giữ dòng đầu tiên để kết quả không phụ thuộc thứ tự file.
                log.warning("Mã dịch vụ trùng trong danh mục, bỏ qua: %s", code)
                continue
            group = (row.get(COL_GROUP) or "").strip().lower()
            if group not in KNOWN_GROUPS:
                unknown_groups.setdefault(group, []).append(code)
            entries[code] = CatalogEntry(
                name_method=(row.get(COL_NAME) or "").strip(),
                group=group,
            )
    except csv.Error as e:
        raise CatalogError(f"sai định dạng CSV ({e})") from e

    if not entries:
        raise CatalogError(f"không có dòng dữ liệu nào có {COL_ID}")

    if unknown_groups:
        _warn_unknown_groups(path, unknown_groups)

    return MappingProxyType(entries)


def load_catalog(path: Optional[Path] = None) -> Catalog:
    """Nạp danh mục và trả về mapping read-only ``{mã đã chuẩn hoá: CatalogEntry}``.

    Không truyền ``path`` thì thử lần lượt các vị trí trong
    ``catalog_search_paths()``. Ném ``CatalogError`` (message tiếng Việt, đã
    liệt kê từng vị trí và lý do) nếu không nạp được ở đâu cả.
    """

    global _cache

    candidates = [Path(path)] if path is not None else catalog_search_paths()
    problems: List[str] = []

    for candidate in candidates:
        try:
            stat = candidate.stat()
        except OSError:
            problems.append(f"  • {candidate}: không tìm thấy")
            continue

        key = (str(candidate), stat.st_mtime, stat.st_size)
        with _cache_lock:
            cached = _cache
        if cached is not None and cached[0] == key:
            return cached[1]

        try:
            entries = _parse_catalog_file(candidate)
        except CatalogError as e:
            log.warning("Bỏ qua danh mục %s: %s", candidate, e)
            problems.append(f"  • {candidate}: {e}")
            continue

        # Log vân tay để đối chiếu khi cần truy vết "máy này lọc bằng danh mục nào".
        log.info(
            "Đã nạp danh mục %s: %d mã dịch vụ (sha256=%s…)",
            candidate, len(entries), CATALOG_SHA256[:12],
        )
        with _cache_lock:
            _cache = (key, entries)
        return entries

    raise CatalogError(
        f"Không nạp được danh mục dịch vụ '{CATALOG_FILENAME}'.\n"
        + "\n".join(problems)
    )


def lookup(catalog: Catalog, service_code) -> Optional[CatalogEntry]:
    """Tra một mã dịch vụ. None = không có trong danh mục (kể cả mã rỗng)."""

    code = normalize_service_code(service_code)
    if not code:
        return None
    return catalog.get(code)


__all__ = [
    "CATALOG_DIRNAME",
    "CATALOG_FILENAME",
    "CATALOG_SHA256",
    "COL_ID",
    "COL_NAME",
    "COL_GROUP",
    "GROUP_INCLUDE",
    "GROUP_EXCLUDE",
    "KNOWN_GROUPS",
    "Catalog",
    "CatalogEntry",
    "CatalogError",
    "catalog_search_paths",
    "normalize_service_code",
    "load_catalog",
    "lookup",
]
