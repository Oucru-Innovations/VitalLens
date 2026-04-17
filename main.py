"""
VitalLens - Entry point.
Thiết lập environment trước khi import bất kỳ module nào khác.
"""

import os
import sys
import warnings
import logging

# === Paddle / OCR environment (phải set trước khi import paddle) ===
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['GLOG_minloglevel'] = '2'
warnings.filterwarnings('ignore', message='No ccache found')
warnings.filterwarnings('ignore', message=".*doesn't match a supported version")

logging.getLogger('paddle').setLevel(logging.ERROR)
logging.getLogger('paddleocr').setLevel(logging.ERROR)
logging.getLogger('paddlex').setLevel(logging.ERROR)
logging.getLogger('ppocr').setLevel(logging.ERROR)

# === Patch PaddleX trong frozen EXE ===
if getattr(sys, 'frozen', False):
    try:
        import paddlex.utils.deps as _pdx_deps
        _pdx_deps.is_dep_available = lambda *a, **kw: True
        _pdx_deps.is_extra_available = lambda *a, **kw: True
        _pdx_deps.require_deps = lambda *a, **kw: None
        _pdx_deps.require_extra = lambda *a, **kw: None
    except Exception:
        pass

# === Khởi chạy ứng dụng ===
from apps.app import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
