# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec - VitalLens (onedir mode).

Build command:
  conda activate vitallens
  pyinstaller build_exe.spec --noconfirm --clean

Or use the wrapper script:
  build.bat
"""
from PyInstaller.utils.hooks import (
    collect_all,
    collect_dynamic_libs,
)

block_cipher = None

# Compatibility patch for older PyInstaller versions
import PyInstaller.compat as _compat
if not hasattr(_compat, 'is_py314'):
    _compat.is_py314 = False

# =====================================================================
# Collect all data/binaries/hidden-imports from key packages
# =====================================================================
_all_datas = []
_all_binaries = []
_all_hiddenimports = []

_PACKAGES_TO_COLLECT = [
    # --- PaddlePaddle / OCR ---
    'paddle', 'paddleocr', 'paddlex',
    # --- Image / Medical ---
    'pydicom', 'pypdfium2', 'pylibjpeg',
    'cv2', 'numpy', 'PIL',
    # --- OCR dependencies ---
    'shapely', 'pyclipper', 'yaml',
    'google.protobuf', 'safetensors',
    # --- Office / Network ---
    'openpyxl', 'paramiko',
    'filelock', 'requests', 'dotenv',
]

for _pkg in _PACKAGES_TO_COLLECT:
    try:
        _d, _b, _h = collect_all(_pkg)
        _all_datas += _d
        _all_binaries += _b
        _all_hiddenimports += _h
    except Exception:
        pass

# Ensure critical native libraries are included
for _lib_pkg in ('paddle', 'pypdfium2'):
    try:
        _all_binaries += collect_dynamic_libs(_lib_pkg)
    except Exception:
        pass

# =====================================================================
# Bundle pre-downloaded PaddleX OCR models
# =====================================================================
import pathlib as _pl

# PyInstaller không chdir tới thư mục spec, nên đường dẫn tương đối sẽ hỏng khi
# chạy `pyinstaller VitalLens/build_exe.spec` từ thư mục khác. SPECPATH do
# PyInstaller bơm vào namespace của spec chính là để dùng cho việc này.
_SPEC_DIR = _pl.Path(globals().get('SPECPATH', '.')).resolve()

_models_root = _pl.Path.home() / '.paddlex' / 'official_models'
_MODEL_NAMES = ['PP-OCRv5_mobile_det', 'en_PP-OCRv5_mobile_rec']
_MODEL_EXTENSIONS = {'.json', '.pdiparams', '.pdmodel', '.yml', '.yaml'}

for _m in _MODEL_NAMES:
    _md = _models_root / _m
    if _md.is_dir():
        for _f in _md.iterdir():
            if _f.is_file() and _f.suffix in _MODEL_EXTENSIONS:
                _all_datas.append((str(_f), f'paddlex_models/{_m}'))

# Bundle icon
_icon_file = _SPEC_DIR / 'icon.ico'
if _icon_file.is_file():
    _all_datas.append((str(_icon_file), '.'))

# =====================================================================
# Bundle danh mục dịch vụ y tế (XML4 lookup + filter)
#
# Chỉ nằm TRONG bundle (_internal\database\), không copy ra cạnh EXE: bản
# phát hành không có file danh mục nào cho người dùng sửa.
#
# Đồng thời đối chiếu SHA-256 với hằng số CATALOG_SHA256 trong
# apps/services/medical_catalog.py. Đọc hằng số bằng ast thay vì import
# apps.* — import sẽ kéo theo tkinter/config và nạp .env lúc build.
# =====================================================================
import ast as _ast
import hashlib as _hashlib

_catalog_file = _SPEC_DIR / 'database' / 'database_medical.csv'
if not _catalog_file.is_file():
    raise SystemExit(
        f'[ERROR] Missing {_catalog_file} - XML4 export cannot filter without it.'
    )

_mc_source = _SPEC_DIR / 'apps' / 'services' / 'medical_catalog.py'
_expected_sha = None
for _node in _ast.parse(_mc_source.read_text(encoding='utf-8')).body:
    if isinstance(_node, _ast.Assign) and any(
        getattr(_t, 'id', '') == 'CATALOG_SHA256' for _t in _node.targets
    ):
        # break: lay lan gan DAU TIEN. Khong break thi neu hang so bi gan hai
        # lan, build se am tham kiem tra theo lan gan sau.
        _expected_sha = _ast.literal_eval(_node.value)
        break

if not _expected_sha:
    raise SystemExit(f'[ERROR] CATALOG_SHA256 not found in {_mc_source}')

_actual_sha = _hashlib.sha256(_catalog_file.read_bytes()).hexdigest()
if _actual_sha != _expected_sha:
    raise SystemExit(
        f'[ERROR] Catalogue fingerprint mismatch - refusing to build.\n'
        f'        file    : {_catalog_file}\n'
        f'        actual  : {_actual_sha}\n'
        f'        expected: {_expected_sha}\n'
        f'        If the catalogue was updated on purpose, set CATALOG_SHA256\n'
        f'        in {_mc_source} to the actual value and commit both together.'
    )

print(f'[OK] Catalogue fingerprint verified: {_actual_sha[:12]}...')
_all_datas.append((str(_catalog_file), 'database'))

# =====================================================================
# Hidden imports (lazy / dynamic imports not auto-detected)
# =====================================================================
_all_hiddenimports += [
    # pydicom decoders
    'pydicom.encoders.gdcm',
    'pydicom.encoders.pylibjpeg',
    'pylibjpeg.libjpeg',
    # Tkinter image support
    'PIL.ImageTk',
    # Standard library modules used dynamically
    'xml.etree.ElementTree',
    'json', 'base64', 'collections',
    # numpy internals (numpy 2.x restructured core → _core)
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    'numpy.core.multiarray',
    'numpy.core.numeric',
    'numpy.core._methods',
    'numpy._core',
    'numpy._core._multiarray_umath',
    'numpy._core.multiarray',
    'numpy._core._methods',
    'numpy.random',
    'numpy.random._common',
    'numpy.fft',
    'numpy.linalg',
    'numpy.linalg._umath_linalg',
]

# =====================================================================
# Packages to exclude (reduce bundle size)
# =====================================================================
_EXCLUDES = [
    'matplotlib', 'scipy', 'IPython', 'notebook', 'pytest',
    'tkinter.test',
]

# =====================================================================
# Analysis
# =====================================================================
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_all_binaries,
    datas=_all_datas,
    hiddenimports=_all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VitalLens',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                    # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VitalLens',
)
