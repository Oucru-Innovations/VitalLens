"""Cổng build: chặn nếu ``database/database_medical.csv`` lệch ``CATALOG_SHA256``.

``build_exe.spec`` đã làm việc này cho nhánh PyInstaller. Nuitka không có file
spec để nhét logic vào, nên tách ra đây cho ``build_nuitka.bat`` gọi — thiếu
bước này thì bản Nuitka mất luôn bảo đảm "cùng input ra cùng kết quả lọc".

Đọc hằng số bằng ``ast`` chứ KHÔNG import ``apps.*``: import sẽ kéo theo
tkinter và nạp ``.env`` ngay lúc build.

    python verify_catalog.py     # exit 0 = khớp, exit 1 = lệch/thiếu
"""

from __future__ import annotations

import ast
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
CSV = ROOT / "database" / "database_medical.csv"
SRC = ROOT / "apps" / "services" / "medical_catalog.py"


def expected_sha() -> str:
    for node in ast.parse(SRC.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "CATALOG_SHA256" for t in node.targets
        ):
            # Lấy lần gán ĐẦU TIÊN: gán hai lần thì build sẽ âm thầm kiểm
            # theo lần sau.
            return ast.literal_eval(node.value)
    sys.exit(f"[ERROR] CATALOG_SHA256 not found in {SRC}")


def main() -> None:
    if not CSV.is_file():
        sys.exit(f"[ERROR] Missing {CSV} - XML4 export cannot filter without it.")
    want = expected_sha()
    got = hashlib.sha256(CSV.read_bytes()).hexdigest()
    if got != want:
        sys.exit(
            f"[ERROR] Catalogue fingerprint mismatch - refusing to build.\n"
            f"        file    : {CSV}\n"
            f"        actual  : {got}\n"
            f"        expected: {want}\n"
            f"        Sửa danh mục có chủ ý thì đặt CATALOG_SHA256 trong\n"
            f"        {SRC} bằng giá trị 'actual' và commit chung một lần."
        )
    print(f"[OK] Catalogue fingerprint verified: {got[:12]}...")


if __name__ == "__main__":
    main()
