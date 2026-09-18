"""Kiểm tra bản cập nhật — chỉ BÁO, không tự cài.

Nguồn mặc định là GitHub Releases của chính repo (``UPDATE_DEFAULT_URL``). Repo
đã public nên API ``/releases/latest`` đọc được mà không cần token; app chỉ gửi
một GET ẩn danh, không kèm dữ liệu gì của người dùng.

Chấp nhận hai dạng JSON, tự nhận ra bằng tên khoá:

    GitHub API : {"tag_name": "v1.0.0", "html_url": "https://github.com/..."}
    Manifest   : {"version": "1.0.0",   "url": "https://..."}

Dạng manifest giữ lại cho trường hợp tự host (GitHub Pages, server API nội bộ)
— ``.github/workflows/release.yml`` vẫn sinh ``latest.json`` mỗi lần tag.

Vì sao chỉ báo mà không tự thay EXE: bản Nuitka onefile chỉ là một file nên về
kỹ thuật thay được (đổi tên file đang chạy rồi ghi đè), nhưng tự tải và tự chạy
một binary mới là thêm một đường đưa mã lạ vào máy xử lý dữ liệu bệnh nhân.
Người dùng bấm link, tải EXE từ trang Release, chép đè — đủ cho nhịp phát hành
vài lần một năm.

``UPDATE_MANIFEST_URL`` đặt rỗng trong ``.env`` = tắt hẳn, không request nào đi
ra.

So sánh version phải hiểu bản tiền phát hành: ``1.0.0-rc1`` < ``1.0.0``. Cách
tách số cũ gom mọi chữ số lại nên ``'1.0.0-rc1'`` ra ``(1, 0, 1)`` — báo NGƯỢC:
người đang chạy rc1 không bao giờ thấy bản 1.0.0 chính thức, còn người dùng bản
chính thức thì bị rủ "nâng cấp" xuống rc.

Module cố ý chỉ dùng thư viện chuẩn (``requests`` import trong hàm): CI chạy
``python -m apps.services.update_check`` trên runner trắng, không cài
requirements. Vì thế không dùng ``packaging.version`` dù nó đúng hơn.
"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

log = logging.getLogger(__name__)

__all__ = ["UPDATE_DEFAULT_URL", "Update", "check_for_update", "is_newer"]

# (connect, read) — cùng kiểu tách timeout như upload_api.
_TIMEOUT = (3, 5)

# ponytail: /releases/latest của GitHub BỎ QUA bản prerelease. Đúng với ý đồ —
# người dùng bản chính thức không bị rủ nâng lên rc. Người đang chạy rc muốn
# thấy rc kế tiếp thì trỏ UPDATE_MANIFEST_URL sang .../releases (số nhiều) và
# đọc phần tử đầu; chỉ làm khi thật sự cần.
UPDATE_DEFAULT_URL = (
    "https://api.github.com/repos/Oucru-Innovations/VitalLens/releases/latest"
)


class Update(NamedTuple):
    version: str
    url: str


# `v1.0.0`, `1.0`, `1.0.0-rc1`, `1.0.0rc1` — nhóm: số, nhãn chữ, số của nhãn.
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-_.]?([A-Za-z]+)\.?(\d*))?$")


def _key(version: str) -> tuple[int, ...] | None:
    """Khoá sắp xếp, ``None`` khi chuỗi không phải version.

    Hai phần tử cuối là hạng tiền phát hành: bản chính thức ``(1, 0)`` luôn lớn
    hơn mọi bản có hậu tố ``(0, n)`` cùng số.

    ponytail: mọi nhãn chữ (alpha/beta/rc) cùng hạng — repo chỉ phát hành `rc`.
    Cần phân biệt alpha < beta < rc thì đổi `(0, n)` thành `(rank(label), n)`.
    """

    match = _VERSION_RE.match(version.strip())
    if not match:
        return None
    nums = tuple(int(p) for p in match.group(1).split("."))
    nums += (0,) * (3 - len(nums))  # '1.0' và '1.0.0' là một
    if not match.group(2):
        return nums + (1, 0)
    return nums + (0, int(match.group(3) or 0))


def is_newer(remote: str, local: str) -> bool:
    """True khi ``remote`` mới hơn ``local``. Chuỗi rác → False (không báo bừa)."""

    remote_key, local_key = _key(remote), _key(local)
    if remote_key is None or local_key is None:
        return False
    return remote_key > local_key


def check_for_update(current_version: str, manifest_url: str) -> Update | None:
    """Đọc manifest/GitHub API, trả về ``Update`` khi có bản mới hơn.

    Nuốt mọi lỗi: mạng hỏng, JSON sai, server 500, rate limit của GitHub —
    không có cái nào đáng để làm hỏng lúc khởi động app.
    """

    if not manifest_url.strip():
        return None
    try:
        import requests

        data = requests.get(manifest_url, timeout=_TIMEOUT).json()
        # GitHub trả `tag_name`/`html_url`; manifest tự host trả `version`/`url`.
        remote = str(data.get("tag_name") or data.get("version") or "")
        if not is_newer(remote, current_version):
            return None
        url = str(data.get("html_url") or data.get("url") or "")
        return Update(remote.lstrip("vV"), url)
    except Exception as exc:  # noqa: BLE001 - xem docstring
        log.info("Không kiểm tra được bản cập nhật: %s", exc)
        return None


if __name__ == "__main__":
    assert is_newer("0.3.0", "0.2.0")
    assert is_newer("v0.2.1", "0.2.0")
    assert is_newer("1.0", "0.9.9")
    assert not is_newer("0.2.0", "0.2.0")
    assert not is_newer("0.1.0", "0.2.0")
    assert not is_newer("", "0.2.0")
    assert not is_newer("latest", "0.2.0")
    # Tiền phát hành: đây là thứ cách tách số cũ làm ngược.
    assert is_newer("1.0.0", "1.0.0-rc1"), "ban chinh thuc phai moi hon rc"
    assert not is_newer("1.0.0-rc1", "1.0.0"), "rc khong duoc coi la moi hon"
    assert is_newer("1.0.0-rc2", "1.0.0-rc1")
    assert not is_newer("1.0.0-rc1", "1.0.0-rc1")
    assert is_newer("v1.0.0", "1.0.0-rc1"), "tag GitHub co tien to v"
    assert is_newer("1.0.0rc1", "0.9.9"), "hau to khong dau gach"
    assert is_newer("1.0.1", "1.0.0-rc1")
    assert not is_newer("1.0.0-rc1", "1.0.0-rc2")
    assert _key("1.0") == _key("1.0.0"), "'1.0' va '1.0.0' phai bang nhau"
    assert _key("khong-phai-version") is None
    assert check_for_update("0.2.0", "") is None
    print("update_check OK")
