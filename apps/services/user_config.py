"""Cấu hình riêng của từng người dùng — nằm NGOÀI thư mục app.

Vì sao không để `.env` cạnh `VitalLens.exe` (cách cũ, vẫn đọc được để tương
thích ngược):

- Bản phát hành hiện là một EXE onefile thay theo version. Config nằm cạnh EXE
  nghĩa là mỗi lần đổi file/đổi thư mục người dùng phải chép tay `.env` sang —
  bước thủ công và dễ quên.
- Người dùng hay copy nguyên thư mục app cho đồng nghiệp. Token đi theo.
- Windows Explorer từ chối tạo file bắt đầu bằng dấu chấm, nên "đổi tên
  `.env.example` thành `.env`" là bước hỏng nhiều nhất trong hướng dẫn cài đặt
  (cũng chính là lý do `config.py` phải chấp nhận cả tên `env` không dấu chấm).

Nhờ vậy bản phát hành chính thức **không chứa file config nào**. Runner CI sạch
không có `.env` để Nuitka nhúng; `build.bat` vẫn giữ cổng quét tuyệt đối cho
bundle PyInstaller dùng debug.

Giới hạn bảo mật: token hiện nằm dạng plaintext trong profile người dùng. Không
thể vừa cho app chạy dưới chính tài khoản đó đọc token, vừa bảo đảm chủ tài
khoản không đọc/sửa/xoá được nó; cờ read-only hay ACL chỉ ngăn nhầm tay hoặc
tài khoản khác và chủ sở hữu/admin có thể đổi lại quyền.

DPAPI (`CryptProtectData`) hoặc Windows Credential Manager sẽ tốt hơn cho dữ
liệu lưu trên đĩa: file không còn lộ plaintext và bản sao đem sang máy/tài khoản
khác thường không giải được. Chúng vẫn không phải ranh giới bảo mật với tiến
trình chạy dưới cùng tài khoản, và user vẫn có thể xoá/ghi đè credential. Vì
thế hiện chưa mã hoá giả tạo; nếu threat model đổi, xem RUNBOOK-secrets.md rồi
đổi cả chỗ ghi lẫn chỗ nạp trong `config.py` theo một migration có version.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

__all__ = ["USER_CONFIG_DIR", "USER_ENV_PATH", "save_user_env"]


def _user_config_dir() -> Path:
    """`%APPDATA%\\VitalLens` trên Windows, `~/.config/VitalLens` chỗ khác."""

    base = os.environ.get("APPDATA")
    return Path(base) / "VitalLens" if base else Path.home() / ".config" / "VitalLens"


USER_CONFIG_DIR: Path = _user_config_dir()
USER_ENV_PATH: Path = USER_CONFIG_DIR / ".env"


def save_user_env(values: Mapping[str, str]) -> Path:
    """Ghi/cập nhật các khoá trong ``values`` vào file config của người dùng.

    Giữ nguyên mọi dòng khác (comment, khoá do người dùng tự thêm như
    ``SFTP_BUFFER_PATH``) — dialog chỉ quản vài khoá, không được xoá phần còn
    lại của người ta.

    Ghi kiểu tmp + ``os.replace`` như ``export_store.write_meta``: mất điện
    giữa chừng thì file cũ vẫn nguyên vẹn, không còn lại file rỗng.
    """

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    old_lines: list[str] = []
    if USER_ENV_PATH.is_file():
        old_lines = USER_ENV_PATH.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    new_lines: list[str] = []
    for line in old_lines:
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)
    new_lines.extend(f"{k}={v}" for k, v in remaining.items())

    tmp = USER_ENV_PATH.with_name(USER_ENV_PATH.name + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.replace(tmp, USER_ENV_PATH)
    try:
        # Không có tác dụng trên Windows (đã dựa vào ACL của profile), nhưng
        # đúng khi chạy từ source trên macOS/Linux lúc phát triển.
        os.chmod(USER_ENV_PATH, 0o600)
    except OSError:
        pass
    return USER_ENV_PATH


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        USER_CONFIG_DIR = Path(tmpdir)
        USER_ENV_PATH = USER_CONFIG_DIR / ".env"
        USER_ENV_PATH.write_text(
            "# ghi chu cua nguoi dung\nAPI_BEARER_TOKEN=cu\nSFTP_BUFFER_PATH=/giu_lai\n",
            encoding="utf-8",
        )
        save_user_env({"API_BEARER_TOKEN": "moi", "API_UPLOAD_OWNER": "a@b.c"})
        out = USER_ENV_PATH.read_text(encoding="utf-8").splitlines()
        assert "API_BEARER_TOKEN=moi" in out, out
        assert "SFTP_BUFFER_PATH=/giu_lai" in out, out   # khoá lạ không bị xoá
        assert "# ghi chu cua nguoi dung" in out, out    # comment giữ nguyên
        assert "API_UPLOAD_OWNER=a@b.c" in out, out      # khoá mới được thêm
        assert "API_BEARER_TOKEN=cu" not in out, out     # không ghi trùng key
        assert not list(USER_CONFIG_DIR.glob("*.tmp"))   # dọn file tạm
    print("user_config OK")
