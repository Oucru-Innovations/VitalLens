"""Định vị thư mục lúc chạy — dùng chung cho PyInstaller lẫn Nuitka.

Hai bộ đóng gói báo hiệu "đang chạy dạng đóng gói" theo hai cách khác nhau và
KHÔNG cách nào nhận ra cách kia:

    PyInstaller : ``sys.frozen`` = True, tài nguyên nằm ở ``sys._MEIPASS``
    Nuitka      : biến toàn cục ``__compiled__`` được bơm vào mọi module đã
                  biên dịch; **không có** ``sys._MEIPASS``

Ở chế độ onefile của Nuitka, hai đường dẫn dưới đây trỏ đi hai nơi khác nhau
(đã đo bằng ``smoke_nuitka.py``, đừng suy diễn từ tên biến):

    sys.executable              -> <thư mục bung tạm>\\python.exe   (tài nguyên)
    __compiled__.containing_dir -> <thư mục chứa EXE gốc>           (chỗ user thấy)

Tên ``containing_dir`` nghe như "chỗ chứa tài nguyên" nhưng nó là chỗ chứa
**EXE**. Lẫn hai cái này thì `.env` nhúng và danh mục dịch vụ đều không đọc
được, mà app vẫn chạy tiếp với cấu hình rỗng.

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
        return Path(meipass)                            # PyInstaller: _internal\
    if globals().get("__compiled__") is None:
        return None
    # Nuitka: sys.executable trỏ vào <thư mục bung>\python.exe — file đó không
    # tồn tại thật, chỉ thư mục cha mới là thứ cần.
    return Path(sys.executable).resolve().parent


def exe_dir() -> Path | None:
    """Thư mục chứa file người dùng bấm vào. ``None`` khi chạy từ source.

    Ở onefile, ``sys.executable`` trỏ vào thư mục bung tạm; nhầm hai thứ này
    nghĩa là ``.env`` người dùng đặt cạnh EXE không bao giờ được đọc.
    """

    compiled = globals().get("__compiled__")
    if compiled is not None:
        # Đúng cho cả onefile lẫn standalone; không dùng sys.argv[0] vì nó có
        # thể là đường dẫn tương đối tuỳ chỗ gọi.
        return Path(compiled.containing_dir)
    if getattr(sys, "frozen", False):
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
    # Giá trị lấy từ lần đo thật bằng smoke_nuitka.py — containing_dir là chỗ
    # chứa EXE, còn tài nguyên đi theo sys.executable.
    globals()["__compiled__"] = types.SimpleNamespace(
        containing_dir=str(Path.cwd() / "dist"), onefile=True, standalone=True
    )
    assert is_frozen()
    assert bundle_dir() == Path(sys.executable).resolve().parent  # chỗ bung tạm
    assert exe_dir() == Path.cwd() / "dist"                       # chỗ user bấm
    assert bundle_dir() != exe_dir(), "hai đường dẫn onefile phải khác nhau"
    print("runtime_paths OK")
