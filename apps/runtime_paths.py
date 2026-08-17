"""Định vị thư mục lúc chạy — dùng chung cho PyInstaller lẫn Nuitka.

Hai bộ đóng gói báo hiệu "đang chạy dạng đóng gói" theo hai cách khác nhau và
KHÔNG cách nào nhận ra cách kia:

    PyInstaller : ``sys.frozen`` = True, tài nguyên nằm ở ``sys._MEIPASS``
    Nuitka      : biến toàn cục ``__compiled__`` được bơm vào mọi module đã
                  biên dịch; **không có** ``sys._MEIPASS``

Trước đây năm chỗ trong app tự kiểm tra ``sys.frozen``/``sys._MEIPASS`` tại
chỗ. Với bản Nuitka, chúng sẽ im lặng coi như "đang chạy từ source": danh mục
dịch vụ tìm sai đường dẫn, model OCR không được bung ra, log ghi nhầm vào
thư mục cài đặt. Gom về một nơi để không còn chỗ nào sót.

Module này chỉ import stdlib và không có tác dụng phụ, nên ``logging_setup``
gọi được mà không phá thứ tự import load-bearing ở ``main.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["is_frozen", "bundle_dir", "exe_dir"]


def is_frozen() -> bool:
    """True khi đang chạy dạng đóng gói (EXE PyInstaller hoặc binary Nuitka)."""

    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def bundle_dir() -> Path | None:
    """Thư mục tài nguyên **bên trong** gói. ``None`` khi chạy từ source.

    Đây là nơi các data file được nhúng lúc build (``database/``,
    ``paddlex_models/``, ``.env`` nhúng) đi tới. Ở chế độ onefile của Nuitka
    đó là thư mục bung tạm, KHÔNG phải chỗ người dùng đặt EXE — dùng
    ``exe_dir()`` cho việc đó.
    """

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    compiled = globals().get("__compiled__")
    if compiled is not None:
        return Path(compiled.containing_dir)
    return None


def exe_dir() -> Path | None:
    """Thư mục chứa file người dùng bấm vào. ``None`` khi chạy từ source.

    Ở onefile, ``sys.executable`` trỏ vào binary đã bung trong thư mục tạm;
    chỉ ``sys.argv[0]`` mới là đường dẫn EXE gốc. Nhầm hai thứ này nghĩa là
    ``.env`` cạnh EXE không bao giờ được đọc.
    """

    compiled = globals().get("__compiled__")
    if compiled is not None and getattr(compiled, "onefile", False):
        return Path(sys.argv[0]).resolve().parent
    if compiled is not None or getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


if __name__ == "__main__":
    import types

    assert not is_frozen() and bundle_dir() is None and exe_dir() is None

    sys.frozen = True                                    # giả lập PyInstaller
    sys._MEIPASS = str(Path.cwd() / "_internal")
    assert is_frozen()
    assert bundle_dir() == Path.cwd() / "_internal"
    assert exe_dir() == Path(sys.executable).resolve().parent
    del sys.frozen, sys._MEIPASS

    # Giả lập Nuitka onefile: __compiled__ nằm trong globals của chính module.
    globals()["__compiled__"] = types.SimpleNamespace(
        containing_dir=str(Path.cwd() / "unpacked"), onefile=True
    )
    assert is_frozen()
    assert bundle_dir() == Path.cwd() / "unpacked"       # tài nguyên: chỗ bung tạm
    assert exe_dir() == Path(sys.argv[0]).resolve().parent   # EXE: chỗ user bấm
    print("runtime_paths OK")
