# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec - VitalLens (onedir).

  pyinstaller build_exe.spec --noconfirm --clean
"""
from PyInstaller.utils.hooks import (
    collect_all,
    collect_dynamic_libs,
)

block_cipher = None

# Monkey-patch cho PyInstaller cũ
import PyInstaller.compat as _compat
if not hasattr(_compat, 'is_py314'):
    _compat.is_py314 = False

# ---- Thu thập TẤT CẢ từ các package chính ----
_all_datas = []
_all_binaries = []
_all_hiddenimports = []

for _pkg in [
    'paddle', 'paddleocr', 'paddlex',
    'openpyxl', 'pydicom', 'pypdfium2',
    'pylibjpeg', 'paramiko', 'shapely',
    'pyclipper', 'yaml', 'cv2', 'numpy',
    'PIL', 'google.protobuf', 'safetensors',
    'filelock', 'requests', 'dotenv',
]:
    try:
        _d, _b, _h = collect_all(_pkg)
        _all_datas += _d
        _all_binaries += _b
        _all_hiddenimports += _h
    except Exception:
        pass

# Thêm dynamic libs quan trọng
_all_binaries += collect_dynamic_libs('paddle')
_all_binaries += collect_dynamic_libs('pypdfium2')

# ---- Bundle PaddleX models đã download sẵn ----
import pathlib as _pl
_models_root = _pl.Path.home() / '.paddlex' / 'official_models'
for _m in ['PP-OCRv5_mobile_det', 'en_PP-OCRv5_mobile_rec']:
    _md = _models_root / _m
    if _md.is_dir():
        for _f in _md.iterdir():
            if _f.is_file() and _f.suffix in {'.json', '.pdiparams', '.yml', '.yaml'}:
                _all_datas.append((str(_f), f'paddlex_models/{_m}'))

_icon_file = _pl.Path('icon.ico')
if _icon_file.is_file():
    _all_datas.append((str(_icon_file), '.'))

# ---- Hidden imports thủ công (lazy / dynamic imports) ----
_all_hiddenimports += [
    'pydicom.encoders.gdcm',
    'pydicom.encoders.pylibjpeg',
    'pylibjpeg.libjpeg',
    'PIL.ImageTk',
    'xml.etree.ElementTree',
    'json', 'base64', 'collections',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_all_binaries,
    datas=_all_datas,
    hiddenimports=_all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'IPython', 'notebook', 'pytest'],
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
    console=False,
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
