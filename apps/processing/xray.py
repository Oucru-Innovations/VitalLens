"""X-Ray image processing: OCR text removal + DICOM metadata anonymization."""

import os
import logging
import threading
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}

_ocr = None
_ocr_lock = threading.Lock()

# ── Text detection + validation thresholds ────────────────────────────
# Strategy: detection model finds candidate regions, recognition model
# VALIDATES which ones are real text. Only confirmed text gets erased.
#
# This prevents erasing non-text artifacts (edges, lines, noise) that
# the detection model may flag as text-like.
OCR_DET_SCORE_THRESHOLD: float = 0.8   # Detection confidence (candidate regions)
OCR_REC_SCORE_THRESHOLD: float = 0.8   # Recognition confidence (text validation)
OCR_MIN_TEXT_LENGTH: int = 2            # Skip results with fewer characters
OCR_MIN_BBOX_AREA: int = 100           # Skip tiny detections (width*height px)

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
    """Pre-compute output paths for all files, handling name collisions."""
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
    """Remove patient information from DICOM metadata."""
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
    """Anonymize metadata and optionally erase text regions from pixels."""
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
    """Copy OCR models from the packaged bundle to ~/.paddlex/ if missing."""
    from apps.runtime_paths import bundle_dir

    bundle = bundle_dir()
    if bundle is None:
        return
    import shutil
    src_root = bundle / 'paddlex_models'
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
    """Lazy-initialize PaddleOCR with detection + recognition (thread-safe).

    Both models run: detection finds candidate regions, recognition
    validates which ones are actual text. Only validated text is erased.
    """
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


def _filter_ocr_bboxes(results):
    """Extract bounding boxes from OCR results using recognition as validator.

    Strategy:
    1. Detection model finds candidate text regions (dt_polys / dt_scores)
    2. Recognition model reads each region (rec_texts / rec_scores)
    3. Only regions where recognition CONFIRMS real text are kept

    A region is considered real text only if ALL conditions are met:
    - Detection confidence >= OCR_DET_SCORE_THRESHOLD
    - Recognition confidence >= OCR_REC_SCORE_THRESHOLD
    - Recognized text has >= OCR_MIN_TEXT_LENGTH characters
    - Recognized text contains at least one alphanumeric character
    - Bounding box area >= OCR_MIN_BBOX_AREA

    Returns a list of (x1, y1, x2, y2) tuples for confirmed text regions.
    """
    bboxes = []
    for res in results:
        if not res or not res.get("dt_polys"):
            continue
        det_scores = res.get("dt_scores", [])
        rec_texts = res.get("rec_texts", [])
        rec_scores = res.get("rec_scores", [])
        for idx, bbox in enumerate(res["dt_polys"]):
            # 1) Detection confidence check
            if idx < len(det_scores) and det_scores[idx] < OCR_DET_SCORE_THRESHOLD:
                continue

            # 2) Recognition must exist and confirm it is text
            if idx >= len(rec_texts) or idx >= len(rec_scores):
                continue  # No recognition result → skip (don't erase)

            text = rec_texts[idx].strip()
            score = rec_scores[idx]

            # 3) Recognition confidence must be high
            if score < OCR_REC_SCORE_THRESHOLD:
                continue

            # 4) Text must have minimum length
            if len(text) < OCR_MIN_TEXT_LENGTH:
                continue

            # 5) Text must contain at least one letter or digit
            #    (filters out pure symbols/noise like "---", "...", "|||")
            if not any(c.isalnum() for c in text):
                continue

            # 6) Bounding box must have minimum area
            xs = [int(p[0]) for p in bbox]
            ys = [int(p[1]) for p in bbox]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            if (x2 - x1) * (y2 - y1) < OCR_MIN_BBOX_AREA:
                continue

            bboxes.append((x1, y1, x2, y2))
    return bboxes


def load_image(file_path, return_dataset=False):
    """Load an image from file.

    If ``return_dataset=True``, returns ``(PIL Image, pydicom Dataset,
    raw pixel_array)`` for DICOM files, or ``(PIL Image, None, None)``
    for regular images.
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
    raise ValueError(f"Unsupported format: {suffix}")


def remove_text_from_image(file_path, output_path):
    """Remove burned-in text. DICOM files also get metadata anonymized."""
    import numpy as np
    from PIL import ImageDraw
    file_path = Path(file_path)
    image, ds, raw_pixels = load_image(file_path, return_dataset=True)
    ocr = _get_ocr()
    ocr_input = np.array(image.convert("RGB") if image.mode != "RGB" else image)
    results = ocr.predict(ocr_input)

    bboxes = _filter_ocr_bboxes(results)

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
    """Process a list of X-Ray images: load → OCR text removal → anonymize → save."""
    try:
        import numpy as np
        from PIL import ImageDraw

        if not image_files:
            callback(False, "No image files to process.")
            return

        indexed_files, output_paths = _plan_output_paths(image_files, output_dir)
        total = len(indexed_files)
        max_workers = min(8, total, os.cpu_count() or 4)
        errors = []

        callback("progress", "Initializing OCR model...")
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
                            log.warning("Failed to load image %s: %s", fp, e)

                for index, fpath in batch:
                    if index not in loaded:
                        continue
                    image, ds, raw_pixels = loaded.pop(index)

                    ocr_input = np.array(image.convert("RGB") if image.mode != "RGB" else image)
                    results = ocr.predict(ocr_input)

                    bboxes = _filter_ocr_bboxes(results)
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

                    status_msg = (f"removed {removed} text regions" if removed
                                  else "no text found, anonymize only")
                    callback("progress", f"[{index}/{total}] {Path(fpath).name}: {status_msg}")

            for f in save_futures:
                f.result()

        processed = total - len(errors)
        if errors:
            callback(True, f"Done! {processed}/{total} images ({len(errors)} errors).")
        else:
            callback(True, f"Done! {total} images processed ({max_workers} threads).")
    except Exception as e:
        import traceback
        log.error("run_xray_processing failed:\n%s", traceback.format_exc())
        callback(False, f"Error: {e}\n\n{traceback.format_exc()}")
