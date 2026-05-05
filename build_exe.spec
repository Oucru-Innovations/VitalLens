# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec - VitalLens (onedir mode).

Build command:
  conda activate paddleocr
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
_icon_file = _pl.Path('icon.ico')
if _icon_file.is_file():
    _all_datas.append((str(_icon_file), '.'))

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
