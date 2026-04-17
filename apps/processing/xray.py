"""Xử lý ảnh X-Quang: OCR xóa text burned-in, anonymize DICOM metadata."""

import os
import sys
import logging
import threading
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}

_ocr = None
_ocr_lock = threading.Lock()

DICOM_PATIENT_TAGS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
    "PatientAge", "PatientWeight", "PatientAddress",
    "OtherPatientIDs", "OtherPatientNames",
    "InstitutionName", "InstitutionAddress",
    "ReferringPhysicianName", "PerformingPhysicianName",
    "OperatorsName", "PhysiciansOfRecord",
    "AccessionNumber", "StudyID",
]


def _plan_output_paths(image_files, output_dir):
    indexed_files = list(enumerate(image_files, start=1))
    base_names = {}
    collisions = Counter()

    for index, file_path in indexed_files:
        suffix = ".dcm" if Path(file_path).suffix.lower() == ".dcm" else ".png"
        base_name = f"{Path(file_path).stem}_clean{suffix}"
        base_names[index] = base_name
        collisions[base_name] += 1

    seen = Counter()
    output_paths = {}
    for index, _ in indexed_files:
        base_name = base_names[index]
        seen[base_name] += 1
        if collisions[base_name] > 1:
            base_path = Path(base_name)
            final_name = f"{base_path.stem}_{seen[base_name]}{base_path.suffix}"
        else:
            final_name = base_name
        output_paths[index] = os.path.join(output_dir, final_name)

    return indexed_files, output_paths


def anonymize_dicom(ds):
    """Xóa thông tin bệnh nhân khỏi metadata DICOM."""
    for tag_name in DICOM_PATIENT_TAGS:
        if hasattr(ds, tag_name):
            try:
                ds.data_element(tag_name).value = ""
            except Exception:
                pass
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = "VitalLens - Anonymized"
    ds.BurnedInAnnotation = "NO"
    return ds


def _save_clean_dicom(ds, raw_pixels, bboxes, output_path):
    """Anonymize metadata. Nếu có bboxes thì xóa text trên pixel."""
    from pydicom.uid import ExplicitVRLittleEndian

    anonymize_dicom(ds)

    if bboxes:
        for (x1, y1, x2, y2) in bboxes:
            raw_pixels[y1:y2 + 1, x1:x2 + 1] = 0
        ds.PixelData = raw_pixels.tobytes()
        if hasattr(ds, 'file_meta'):
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds.save_as(output_path)


def _deploy_bundled_models():
    """Copy models từ bundle vào ~/.paddlex/ nếu chưa có (chỉ khi frozen EXE)."""
    if not getattr(sys, 'frozen', False):
        return
    import shutil
    src_root = Path(sys._MEIPASS) / 'paddlex_models'
    dst_root = Path.home() / '.paddlex' / 'official_models'
    if not src_root.is_dir():
        return
    for model_name in ['PP-OCRv5_mobile_det', 'en_PP-OCRv5_mobile_rec']:
        src = src_root / model_name
        dst = dst_root / model_name
        if src.is_dir() and not (dst / 'inference.pdiparams').exists():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)


def _get_ocr():
    global _ocr
    if _ocr is not None:
        return _ocr
    with _ocr_lock:
        if _ocr is None:
            _deploy_bundled_models()
            from paddleocr import PaddleOCR
            _ocr = PaddleOCR(
                text_detection_model_name='PP-OCRv5_mobile_det',
                text_recognition_model_name='en_PP-OCRv5_mobile_rec',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                enable_mkldnn=False,
                use_textline_orientation=False,
            )
        return _ocr
    return _ocr


def load_image(file_path, return_dataset=False):
    """Load ảnh từ file.
    Nếu return_dataset=True, trả về (PIL Image, pydicom Dataset, pixel_array gốc) cho DCM,
    hoặc (PIL Image, None, None) cho ảnh thường.
    """
    import pydicom
    import numpy as np
    from PIL import Image
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".dcm":
        ds = pydicom.dcmread(file_path)
        raw_pixels = ds.pixel_array.copy()
        arr = raw_pixels.astype(np.float32)
        lo, hi = arr.min(), arr.max()
        if hi != lo:
            arr = (arr - lo) / (hi - lo) * 255.0
        img = Image.fromarray(arr.astype(np.uint8))
        return (img, ds, raw_pixels) if return_dataset else img
    if suffix in IMAGE_EXTS:
        img = Image.open(file_path).convert("L")
        return (img, None, None) if return_dataset else img
    raise ValueError(f"Định dạng không hỗ trợ: {suffix}")


def remove_text_from_image(file_path, output_path):
    """Xóa text burned-in. Nếu input là DICOM → anonymize metadata và lưu .dcm."""
    import numpy as np
    from PIL import ImageDraw
    file_path = Path(file_path)
    image, ds, raw_pixels = load_image(file_path, return_dataset=True)
    ocr = _get_ocr()
    ocr_input = np.array(image.convert("RGB") if image.mode != "RGB" else image)
    results = ocr.predict(ocr_input)

    bboxes = []
    for res in results:
        if not res or not res.get("dt_polys"):
            continue
        texts = res.get("rec_texts", [])
        for idx, bbox in enumerate(res["dt_polys"]):
            if idx < len(texts) and len(texts[idx].strip()) <= 1:
                continue
            xs = [int(p[0]) for p in bbox]
            ys = [int(p[1]) for p in bbox]
            bboxes.append((min(xs), min(ys), max(xs), max(ys)))

    removed = len(bboxes)
    if ds is not None:
        _save_clean_dicom(ds, raw_pixels, bboxes, output_path)
    else:
        if bboxes:
            draw = ImageDraw.Draw(image)
            for (x1, y1, x2, y2) in bboxes:
                draw.rectangle([x1, y1, x2, y2], fill=0)
        image.save(output_path)
    return removed


def run_xray_processing(image_files, output_dir, callback):
    """Xử lý danh sách ảnh X-Quang: load → OCR xóa text → anonymize metadata → lưu DICOM."""
    try:
        import numpy as np
        from PIL import ImageDraw

        if not image_files:
            callback(False, "Không có file ảnh để xử lý.")
            return

        indexed_files, output_paths = _plan_output_paths(image_files, output_dir)
        total = len(indexed_files)
        max_workers = min(8, total, os.cpu_count() or 4)
        errors = []

        callback("progress", "Đang khởi tạo OCR model...")
        ocr = _get_ocr()

        BATCH_SIZE = 16
        with ThreadPoolExecutor(max_workers=max_workers) as save_pool:
            save_futures = []

            for batch_start in range(0, total, BATCH_SIZE):
                batch = indexed_files[batch_start:batch_start + BATCH_SIZE]

                loaded = {}
                with ThreadPoolExecutor(max_workers=max_workers) as load_pool:
                    future_to_item = {
                        load_pool.submit(load_image, fp, True): (index, fp)
                        for index, fp in batch
                    }
                    for future in as_completed(future_to_item):
                        index, fp = future_to_item[future]
                        try:
                            loaded[index] = future.result()
                        except Exception as e:
                            errors.append(f"{Path(fp).name}: {e}")
                            log.warning("Lỗi tải ảnh %s: %s", fp, e)

                for index, fpath in batch:
                    if index not in loaded:
                        continue
                    image, ds, raw_pixels = loaded.pop(index)

                    ocr_input = np.array(image.convert("RGB") if image.mode != "RGB" else image)
                    results = ocr.predict(ocr_input)

                    bboxes = []
                    for res in results:
                        if not res or not res.get("dt_polys"):
                            continue
                        texts = res.get("rec_texts", [])
                        for idx, bbox in enumerate(res["dt_polys"]):
                            if idx < len(texts) and len(texts[idx].strip()) <= 1:
                                continue
                            xs = [int(p[0]) for p in bbox]
                            ys = [int(p[1]) for p in bbox]
                            bboxes.append((min(xs), min(ys), max(xs), max(ys)))

                    removed = len(bboxes)

                    if ds is not None:
                        out = output_paths[index]
                        save_futures.append(
                            save_pool.submit(_save_clean_dicom, ds, raw_pixels, bboxes, out)
                        )
                    else:
                        out = output_paths[index]
                        if bboxes:
                            draw = ImageDraw.Draw(image)
                            for (x1, y1, x2, y2) in bboxes:
                                draw.rectangle([x1, y1, x2, y2], fill=0)
                        save_futures.append(save_pool.submit(image.save, out))

                    status_msg = (f"xóa {removed} vùng text" if removed
                                  else "không có text, chỉ anonymize")
                    callback("progress", f"[{index}/{total}] {Path(fpath).name}: {status_msg}")

            for f in save_futures:
                f.result()

        processed = total - len(errors)
        if errors:
            callback(True, f"Hoàn thành! {processed}/{total} ảnh ({len(errors)} lỗi).")
        else:
            callback(True, f"Hoàn thành! {total} ảnh đã xử lý ({max_workers} luồng).")
    except Exception as e:
        import traceback
        log.error("run_xray_processing failed:\n%s", traceback.format_exc())
        callback(False, f"Lỗi: {e}\n\n{traceback.format_exc()}")
