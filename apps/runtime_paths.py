"""Định vị thư mục lúc chạy cho bản build Nuitka.

Nuitka báo hiệu "đang chạy dạng đóng gói" bằng biến toàn cục ``__compiled__``
được bơm vào mọi module đã biên dịch (không có ``sys.frozen``/``sys._MEIPASS``).

Ở chế độ onefile của Nuitka, hai đường dẫn dưới đây trỏ đi hai nơi khác nhau
(đã đo bằng ``smoke_nuitka.py``, đừng suy diễn từ tên biến):

    sys.executable              -> <thư mục bung tạm>\\python.exe   (tài nguyên)
    __compiled__.containing_dir -> <thư mục chứa EXE gốc>           (chỗ user thấy)

Tên ``containing_dir`` nghe như "chỗ chứa tài nguyên" nhưng nó là chỗ chứa
**EXE**. Lẫn hai cái này thì `.env` nhúng và danh mục dịch vụ đều không đọc
được, mà app vẫn chạy tiếp với cấu hình rỗng.

Mọi chỗ cần biết "đang chạy dạng đóng gói" đều đi qua module này: kiểm tra lẻ
tẻ ở nơi khác dễ sót, và chỗ sót sẽ im lặng coi như "đang chạy từ source"
(danh mục dịch vụ tìm sai đường dẫn, log ghi nhầm thư mục).

Module này chỉ import stdlib và không có tác dụng phụ, nên ``logging_setup``
gọi được mà không phá thứ tự import load-bearing ở ``main.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["is_frozen", "bundle_dir", "exe_dir", "writable_exe_dir"]


def is_frozen() -> bool:
    """True khi đang chạy dạng binary Nuitka."""

    return globals().get("__compiled__") is not None


def bundle_dir() -> Path | None:
    """Thư mục tài nguyên **bên trong** gói. ``None`` khi chạy từ source.

    Đây là nơi các data file được nhúng lúc build (``database/``,
    ``paddlex_models/``, ``.env`` nhúng) đi tới. Ở chế độ onefile của Nuitka
    đó là thư mục bung tạm, KHÔNG phải chỗ người dùng đặt EXE — dùng
    ``exe_dir()`` cho việc đó.
    """

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
    if compiled is None:
        return None
    # Đúng cho cả onefile lẫn standalone; không dùng sys.argv[0] vì nó có thể
    # là đường dẫn tương đối tuỳ chỗ gọi.
    return Path(compiled.containing_dir)


def writable_exe_dir() -> Path | None:
    """``exe_dir()`` nếu THẬT SỰ ghi được vào đó, ngược lại ``None``.

    Dùng cho những thứ app phải tự ghi (log, `.env` do dialog Cài đặt lưu):
    mặc định đặt cạnh EXE để người dùng mở thư mục là thấy, không phải lần mò
    %APPDATA%/%LOCALAPPDATA%. Nhưng EXE có thể nằm ở `C:\\Program Files` hoặc
    một ổ mạng chỉ-đọc — lúc đó phải lui về thư mục profile chứ không được để
    app chết vì không ghi nổi log.

    Thử ghi thật chứ không dùng ``os.access``: trên Windows ``os.access`` đọc
    cờ read-only của file chứ không hỏi ACL, nên nó báo ghi được ở cả những
    thư mục mà ghi vào sẽ ném PermissionError.
    """

    directory = exe_dir()
    if directory is None:
        return None
    probe = directory / ".vitallens-write-test"
    try:
        probe.touch()
        probe.unlink()
    except OSError:
        return None
    return directory


if __name__ == "__main__":
    import types

    assert not is_frozen() and bundle_dir() is None and exe_dir() is None
    assert writable_exe_dir() is None, "chay tu source thi khong co exe_dir"

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

    # writable_exe_dir: ghi được thì trả về chính nó, không ghi được thì None.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        globals()["__compiled__"] = types.SimpleNamespace(
            containing_dir=tmp, onefile=True, standalone=True
        )
        assert writable_exe_dir() == Path(tmp)
        assert not (Path(tmp) / ".vitallens-write-test").exists(), "phai don file thu"

    globals()["__compiled__"] = types.SimpleNamespace(
        containing_dir=str(Path(tempfile.gettempdir()) / "khong-ton-tai-vitallens"),
        onefile=True, standalone=True,
    )
    assert writable_exe_dir() is None, "thu muc khong ghi duoc phai tra ve None"
    print("runtime_paths OK")
