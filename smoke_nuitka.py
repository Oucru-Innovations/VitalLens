r"""Smoke test cho khau dong goi Nuitka - chay TRUOC khi build ban that.

Build that keo ca paddle nen mat 30-90 phut. Nhung thu de hong lai khong nam o
paddle ma o khau duong dan: Nuitka khong co ``sys._MEIPASS``, va che do onefile
tach lam hai thu muc (cho bung tam vs cho dat EXE). File nay bien dich rieng
phan do trong ~2 phut.

    :: 1) Build ban smoke (chay tu repo root)
    python -m nuitka smoke_nuitka.py --standalone --onefile ^
        --output-dir=dist_nuitka ^
        --include-data-files=.env=.env ^
        --include-data-dir=database=database ^
        --company-name=OUCRU --product-name=VitalLensSmoke ^
        --file-version=0.3.0 --product-version=0.3.0 ^
        "--onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}" ^
        --assume-yes-for-downloads

    :: 2) Chay tu cho khac de chac chan khong doc nham file cua repo
    cd %TEMP% && %USERPROFILE%\...\dist_nuitka\smoke_nuitka.exe

Ky vong khi da nhung .env:
    is_frozen        -> True
    bundle_dir       -> thu muc bung tam (KHAC exe_dir)
    exe_dir          -> thu muc chua .exe
    API_UPLOAD_URL   -> gia tri trong .env, khong phai (EMPTY)
    catalog entries  -> 9190 (SHA-256 khop)

Bat ky dong nao ra (EMPTY)/None nghia la khau nhung hoac khau duong dan hong -
sua truoc, dung build ban that.
"""

from apps.runtime_paths import bundle_dir, exe_dir, is_frozen
from apps import config
from apps.services import medical_catalog


def _dump_raw() -> None:
    """In cac gia tri THO de doi chieu khi duong dan sai.

    Giu lai vi da mot lan tuong ``__compiled__.containing_dir`` la thu muc bung
    onefile - thuc te no la thu muc chua EXE goc. Doan tiep thi lai sai tiep.
    """
    import sys

    print(f"{'sys.executable':<17}: {sys.executable}")
    print(f"{'sys.argv[0]':<17}: {sys.argv[0]}")
    print(f"{'__main__.__file__':<17}: {getattr(sys.modules['__main__'], '__file__', None)}")
    compiled = globals().get("__compiled__")
    if compiled is None:
        print(f"{'__compiled__':<17}: (khong co - dang chay tu source)")
        return
    for attr in sorted(a for a in dir(compiled) if not a.startswith("_")):
        print(f"  __compiled__.{attr:<20}: {getattr(compiled, attr)}")


def main() -> None:
    _dump_raw()
    print("-" * 60)
    token = config.API_BEARER_TOKEN
    rows = [
        ("is_frozen", is_frozen()),
        ("bundle_dir", bundle_dir()),
        ("exe_dir", exe_dir()),
        ("APP_DIR", config.APP_DIR),
        ("API_UPLOAD_URL", config.API_UPLOAD_URL or "(EMPTY)"),
        ("API_UPLOAD_OWNER", config.API_UPLOAD_OWNER or "(EMPTY)"),
        # Chi in do dai: file nay co the chay tren may nguoi khac, khong duoc
        # de token hien ra man hinh hay lot vao anh chup log.
        ("API_BEARER_TOKEN", f"(set, len={len(token)})" if token else "(EMPTY)"),
        ("catalog paths", medical_catalog.catalog_search_paths()),
    ]
    for name, value in rows:
        print(f"{name:<17}: {value}")

    try:
        print(f"{'catalog entries':<17}: {len(medical_catalog.load_catalog())}")
    except medical_catalog.CatalogError as e:
        print(f"{'catalog entries':<17}: LOI - {e}")

    input("\nEnter de dong...")


if __name__ == "__main__":
    main()
