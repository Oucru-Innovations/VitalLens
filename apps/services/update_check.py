"""Kiểm tra bản cập nhật — chỉ BÁO, không tự cài.

Vì sao chỉ báo mà không tự cập nhật: bundle onedir nặng ~700 MB và Windows khoá
chính file EXE đang chạy, nên muốn tự thay thư mục phải sinh thêm một tiến trình
phụ đứng ngoài chờ app thoát. Với quy mô hiện tại (phát hành vài lần một năm,
người dùng nội bộ) chi phí đó không đáng — người dùng bấm link, tải ZIP, giải
nén đè là xong. PyUpdater/Esky giải bài toán này nhưng cả hai đều đã ngừng bảo
trì (Esky 2016/Python 2, PyUpdater 2021), thêm vào là nhận nợ ngay ngày đầu.

Manifest là một file JSON nhỏ, PUBLIC, KHÔNG chứa token:

    {"version": "0.3.0", "url": "https://.../releases/latest"}

``.github/workflows/release.yml`` sinh file này mỗi lần tag. Nơi host là lựa
chọn của người vận hành (server API sẵn có, GitHub Pages, ...) vì repo đang
private nên URL asset của Release đòi đăng nhập.

``UPDATE_MANIFEST_URL`` rỗng (mặc định) = tắt hẳn, không có request nào đi ra.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

log = logging.getLogger(__name__)

__all__ = ["Update", "check_for_update", "is_newer"]

# (connect, read) — cùng kiểu tách timeout như upload_api.
_TIMEOUT = (3, 5)


class Update(NamedTuple):
    version: str
    url: str


def _parts(version: str) -> tuple[int, ...]:
    """``'v1.2.3'`` → ``(1, 2, 3)``.

    Dừng ở đoạn đầu tiên không có chữ số: ``'1.2.0rc1'`` → ``(1, 2, 0)``. Bản
    pre-release không so sánh được chính xác nên coi như bản chính thức cùng số.
    """

    out: list[int] = []
    for chunk in version.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def is_newer(remote: str, local: str) -> bool:
    """True khi ``remote`` mới hơn ``local``. Chuỗi rác → False (không báo bừa)."""

    remote_parts = _parts(remote)
    return bool(remote_parts) and remote_parts > _parts(local)


def check_for_update(current_version: str, manifest_url: str) -> Update | None:
    """Đọc manifest, trả về ``Update`` khi có bản mới hơn, ngược lại ``None``.

    Nuốt mọi lỗi: mạng hỏng, JSON sai, server 500 — không có cái nào đáng để
    làm hỏng lúc khởi động app.
    """

    if not manifest_url.strip():
        return None
    try:
        import requests

        data = requests.get(manifest_url, timeout=_TIMEOUT).json()
        remote = str(data.get("version", ""))
        if not is_newer(remote, current_version):
            return None
        return Update(remote, str(data.get("url", "")))
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
    assert check_for_update("0.2.0", "") is None
    print("update_check OK")
