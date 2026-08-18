# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python 3.12 / Tkinter desktop app (Windows is the primary target) bundling four medical-data workflows: BHYT XML → Excel decode, X-Ray anonymization (PaddleOCR + DICOM tag stripping), OCR review of LAB/monitor folders, and Lab PDF redact + upload. `README.md` documents the user-facing side in depth; this file covers what you need before editing.

## Commands

```powershell
# Setup (conda or venv both fine — everything installs via pip)
pip install -r requirements.txt          # run from source
pip install -r requirements-build.txt    # + PyInstaller/Nuitka, build machines only

python main.py                           # run the app

python -m compileall -q apps main.py     # syntax check (see "Verifying changes")

build.bat                                # Windows: PyInstaller + secret-scan gate
build_nuitka.bat                         # Windows release: Nuitka onefile
python -m PyInstaller build_exe.spec --noconfirm --clean   # manual, skips the gate
```

### Verifying changes

**There is no pytest suite** and `pytest` is not a dependency. Run `python -m compileall -q apps main.py` plus the tkinter-free module self-checks wired in `.github/workflows/ci.yml`; beyond that, exercise the affected page by running the app. Ad-hoc scripts driving `apps.services.*` directly work well because that layer has no tkinter import.

The repo checkout may be on macOS, but the app targets Windows: `build.bat` is a batch file, the PaddleOCR/DICOM stack is verified on Windows only, and `App.__init__` has a Darwin branch purely so the window opens during dev on a Mac.

## Architecture

Three layers with enforced direction — `pages/` → `services/` → `processing/`, never the reverse:

- **`apps/pages/`** — tkinter only. No `open()`, no sockets, no `os.listdir`. All I/O is delegated.
- **`apps/services/`** — pure Python business logic, no tkinter import anywhere. Every filesystem/SFTP access goes through the `StorageBackend` protocol (`services/storage.py`) so local and remote share one code path. Adding a direct `open()` in a service breaks SFTP mode silently.
- **`apps/processing/`** — CPU-bound work (PaddleOCR, XML decode). Knows nothing about UI or storage.

When adding file access, extend `StorageBackend` (both `LocalBackend` and `SftpBackend`) rather than special-casing. Note the SFTP backend resolves paths case-insensitively via `resolve_existing_data_dir` — the server's casing does not match what users type.

### Startup ordering is load-bearing

`main.py` calls `setup_logging()`, `patch_windows_ssl_cert_store()`, and `patch_paddlex_when_frozen()` **before** `from apps.app import App`. Those set Paddle env flags (`FLAGS_enable_pir_api`, `GLOG_minloglevel`, …) and monkey-patch `ssl.SSLContext._load_windows_store_certs`, all of which must land before anything imports paddle or creates an SSL context. Do not move imports above that block or add a module-level paddle import anywhere that `apps.app` reaches at import time.

### Config is import-time and snapshotted

`apps/config.py` loads the dotenv file **as a module import side effect**, then freezes the values into a `Settings` instance *and* into flat module constants (`API_UPLOAD_URL`, `SFTP_HOST`, …). Pages do `from apps.config import API_UPLOAD_URL`, so those are bound once at import — mutating `os.environ` later has no effect. To make a setting live-reloadable you must read `SETTINGS`/`os.environ` at call time instead.

`APP_DIR` resolves to the repo root in dev and to the folder containing `VitalLens.exe` when frozen. Dotenv locations are loaded **in order, all of them** (not first-match): `%APPDATA%\VitalLens\.env` (`services/user_config.py`), then `APP_DIR/.env`, then `APP_DIR/env` (no dot — Windows Explorer refuses dotfiles), then `bundle_dir()/.env` if a manual Nuitka build embedded one. `override=False` throughout, so the earliest file to set a key wins and OS env vars beat every file. A built-in parser substitutes for `python-dotenv` inside packaged builds.

The `%APPDATA%` location is the one users get: `widgets/settings_dialog.py` writes it so nobody has to rename `.env.example` in Explorer, and it survives replacing the EXE. Official CI releases ship **no** config file. `build_nuitka.bat` rejects a repo-root `.env` by default; `VITALLENS_EMBED_ENV=1` is an explicit internal-build escape hatch and never makes the embedded value secret because EXE contents are extractable. Because config is snapshotted at import, the dialog tells the user to restart rather than pretending the new values are live.

The per-user `.env` is plaintext. No ACL can let an app running under a Windows account read a long-lived token while making that token impossible for the same account to read/change/delete. DPAPI or Credential Manager improve at-rest protection but are not a security boundary against code running as that same user; for that threat model, authentication must move server-side (SSO/OAuth/device identity + short-lived scoped credentials). Keep this limitation synchronized with `docs/RUNBOOK-secrets.md`.

`is_secure_endpoint()` is the single definition of "safe to send the bearer token here" (empty or `https://`, or `http://` on localhost). Both the startup log warning and the settings dialog call it; it warns rather than blocks, because blocking would push users of an `http://` endpoint back to Notepad and lose the warning entirely.

### Upload state machine (`services/export_store.py`)

`<output_dir>/pending/` and `<output_dir>/uploaded/` hold triples of `<name>.pdf`, `<name>.csv`, `<name>.meta.json`. **`meta.json` is the source of truth, not the UI** — on startup `read_all()` rescans both folders and rebuilds the lists, so a crash mid-batch loses nothing. Any change to what a pair carries must go through `write_meta` (atomic tmp + `os.replace`) *and* the reader in `_load_folder`, or the field silently disappears on restart.

`pdf_sent` / `csv_sent` are per-file delivery flags: the backend uses `upload.single("file")`, so a pair is two separate POSTs, and a retry must skip whichever already landed.

The backend deduplicates by **content hash, ignoring filename**, and cannot be changed. Two saves for the same patient/type/dates would otherwise produce a byte-identical CSV, so the server silently drops the second one — the PDF lands, its metadata does not. `export_store.write_csv` appends `file_name` to link the PDF and a stable random `export_id` UUID to make the content unique even across independent workspaces/machines. `_unique_export_names` still checks `pending/` and `uploaded/`, but only to prevent local file overwrite; never use it as a global nonce. Legacy pairs are patched by `ensure_csv_identity` immediately before upload, and `CsvMigrationError` must stop that pair rather than sending the stale CSV. `python -m apps.services.export_store` checks identity, migration and formula escaping (wired into `ci.yml`).

### Retry policy (`services/upload_api.py`)

The endpoint has **no idempotency key**, so an auto-retry of a request the server already processed creates a duplicate record. Auto-retry is therefore limited to cases where nothing could have reached the app: connection-phase exceptions (`ConnectTimeout`, `ConnectionError`, `ProxyError`, `SSLError`) and statuses 408/425/429/502/503/504. `ReadTimeout`, `ChunkedEncodingError`, and 500 are **never** auto-retried — they return `retryable=True` so the user decides. Preserve this distinction when touching error handling.

A batch never stops at the first failure; failed pairs stay in `pending/` with `last_error` + `attempts` and remain ticked for the next attempt.

### XML4 export depends on a data file

`processing/xml_to_excel.py` decodes **only** `LOAIHOSO` = XML4 and classifies every row against `database/database_medical.csv` (`MA_DICH_VU` = `ID_SERVICE`): `Include` → main sheet with `Name_Method` filled, `Exclude` → dropped, no match → separate "chưa phân loại" sheet. Two deliberate choices: a missing/blank `MA_DICH_VU` is *unclassified*, not excluded (no code is not evidence of exclusion), and a missing catalogue file **fails the run** rather than exporting unfiltered data.

**The catalogue is release data, deliberately not user-editable.** `services/medical_catalog.py` reads it from `runtime_paths.bundle_dir()/database/` when packaged and from `APP_DIR/database/` otherwise — a packaged build never looks next to the EXE, so a CSV dropped there has no effect. Every load verifies SHA-256 against the `CATALOG_SHA256` constant *before* parsing; both build paths re-verify before packaging. Changing the catalogue means editing the CSV and the constant in one commit, then rebuilding; `build.bat` also deletes any stale `dist\VitalLens\database\`.

Do not "helpfully" restore an `APP_DIR` override or soften the hash check to a warning — both were removed on purpose. The guarantee being bought is that the same input yields the same filtered export on every machine, and that deviation is loud. It is not resistance to a determined local admin, and the module docstring says so; if that is ever needed, the filter belongs server-side.

`load_catalog()` raises `CatalogError` with a user-readable message naming the location and reason, and returns a `MappingProxyType` because the result is a process-wide cache a caller mutation would silently poison.

Note `XML4_EXCLUDED_COLUMNS` is applied only in `_sheet_columns()`; excluded fields are still parsed and held in memory, so a new export path that bypasses that function will emit them.

### The step-2 Excel file has two modes, picked by header

One optional file picker on the XML page feeds two different services. `_collect_and_save` tries `study_mapping.load_study_mapping()` first; it returns `None` — not an error — when the header lacks `USUBJID` + `EMR_ID` (`study_mapping.COL_STUDY_ID` / `COL_HRN` — renamed from the original `STUDY_ID`/`HRN` header names), and only then does the generic `mapping_excel.load_mapping()` run. Neither is cached: editing the file and re-running must show the new result.

| | `services/mapping_excel.py` | `services/study_mapping.py` |
| --- | --- | --- |
| Trigger | anything else | header has both `USUBJID` and `EMR_ID` |
| Headers | user-defined; A1 = the XML4 field to join on | fixed names, column order irrelevant |
| Effect | appends its columns, filters nothing | exports source `USUBJID` as `MA_NTG`, filters by date, hides `ID`/`MA_LK` |

Study mode specifics:

- `EMR_ID` is matched against `MA_LK` in full first, then against the **last 10 characters** of `ID` and `ID_GOC` (`STUDY_SUFFIX_FIELDS`). Full match wins because it is the stronger evidence. A value shorter than `ID_SUFFIX_LENGTH`, or two EMR_IDs sharing the same last 10 characters, yields *no* match rather than a guess — a wrong `USUBJID` attaches one patient's data to another.
- Date filtering compares **`yyyymmdd` only**, deliberately dropping the time part of `NGAY_KQ`, because both endpoints must count as full days. Start comes from `START_DATE`; end from the first of `END_DATE_HEADERS` present — `FROM_DATE` is in that list because real files name the end column that way.
- An unparseable date in the mapping file **fails the run** (`StudyMappingError`); a record that matches an EMR_ID but has no readable `NGAY_KQ` is **kept** and counted, same principle as a blank `MA_DICH_VU`.
- A record that matches `EMR_ID` but whose `NGAY_KQ` falls **outside** that row's mapping date range is **dropped entirely** — not written to any sheet, not counted as unmatched. This is deliberate: being outside the study window is conclusive evidence the record doesn't belong, unlike a missing `HRN`/`EMR_ID` match (which could be a typo the user needs to fix) or a missing date (which is inconclusive). Tracked separately in `stats["out_of_range"]` for the UI message.
- Records with no `EMR_ID` match (not date-filtered ones — see above) go to sheet `XML4_KhongKhopHRN`, which **keeps `ID` and `MA_LK`** — the sheet exists so the user can fix their list, and hiding the identifiers there would make it useless. `ID_GOC` stays on every sheet.
- Catalogue split runs first, so `Exclude` services never reach any sheet, including the unmatched one.
- `_sheet_columns()` takes `lead_column` / `hidden_columns` per sheet; that is the only place `ID`/`MA_LK` are dropped, so the `XML4_EXCLUDED_COLUMNS` caveat above applies to them too.
- In study mode, a `Summary` sheet is written first (before `XML4_Include` etc.), one row per source `USUBJID` (exported as `MA_NTG`), built by `_build_summary_rows()`: the mapping file's declared date range for that study (min start / max end across its rows, from `_study_mapping_ranges()`) next to the actual `NGAY_KQ` range found in the exported records, plus distinct `MA_DICH_VU` count and row counts split into "hợp lệ" (catalogue-`Include`) vs "unknown" (unclassified). Only records that made it into a real sheet count here — dropped out-of-range records are invisible to the summary too.
- If the step-2 file's name matches `LabRequest_<suffix>.xlsx` (case-insensitive), `study_mapping.derive_output_filename()` returns `LabResult_<suffix>.xlsx`, and `xml_page.py._pick_mapping` uses it to overwrite the BƯỚC-3 output filename (keeping whatever directory was already selected). Filenames that don't match the convention leave the output path untouched — no guessing.

### UI threading

Long work runs on daemon threads; Tk is touched only from the main thread. Two patterns coexist: most pages use `self.controller.after(0, ...)` / `self.after(...)`, while `pages/upload/page.py` uses a `queue.Queue` drained by `_poll_ui_queue` every 80 ms with `_post()` / `_run_async(work, done)` helpers. Follow whichever the file already uses. Pages may define `on_close()` — `App._on_close` calls it on every page to release PDF handles and SFTP transports.

### Where PII is removed

| Stage | Mechanism | Code |
| --- | --- | --- |
| Lab PDF | Pages rasterized via pypdfium2, regions painted black — underlying text is gone, not covered | `services/pdf_redact.py` |
| X-Ray | PaddleOCR detects burned-in text and paints it out; DICOM tags in `DICOM_PATIENT_TAGS` anonymized | `processing/xray.py` |
| XML → Excel | Only XML4 is decoded; `XML4_EXCLUDED_COLUMNS` omitted **at column-selection time only**, and only catalogue-`Include` services reach the main sheet. With a study list, `ID`/`MA_LK` are replaced by `MA_NTG` (sourced from `USUBJID`) on the matched sheets, but not on `XML4_KhongKhopHRN` | `processing/xml_to_excel.py` |
| CSV export | Cells starting with `= + - @` get a `'` prefix (formula injection) | `services/export_store.py` |

OCR false-positive thresholds (`OCR_DET_SCORE_THRESHOLD`, `OCR_REC_SCORE_THRESHOLD`, `OCR_MIN_TEXT_LENGTH`, `OCR_MIN_BBOX_AREA`) are constants at the top of `processing/xray.py`. Detection proposes regions, recognition validates them — only confirmed text is erased.

## Conventions

- **Vietnamese is the working language** for docstrings, inline comments, log messages, and all user-facing UI strings. New code should match; English-only comments read as foreign here. Module docstrings routinely explain *why* a constraint exists (the retry policy, the meta.json ledger) — keep that habit, it is where the non-obvious knowledge lives.
- Services and widgets export an explicit `__all__` and re-export through `__init__.py`; add new public names to both.
- `apps/config.py` keeps legacy flat constants alongside `Settings` for backward compatibility — when adding a setting, wire it into `Settings.from_env()`, the flat constant, `__all__`, and `.env.example`.
- The `lab_records` scanner depends on a filename convention: `<Type><SubType>_<patient_id>_<dd.mm.yyyy.hh.mm.ss><tail>.<ext>` under `<root>/<studyID>/PROCESSING/<patient_id>/<ddmmyyyy>/Image/`. Renaming logic there ripples into the OCR page.

## Secrets

`.env` / `env` / `config_debug.log` are gitignored. Official GitHub releases are built on a clean runner and contain no credential; `build.bat` fails if loose secret files reach its onedir output, while `build_nuitka.bat` fails on a repo-root `.env` by default. `VITALLENS_EMBED_ENV=1` is only an explicit internal-build escape hatch, and its artifact is not shippable. Tokens are per-user. `config_debug.log` is written only when `VITALLENS_DEBUG_CONFIG=1`, and values for keys in `_SECRET_KEYS` are redacted to a length. `API_UPLOAD_URL` must be `https://`; `config.py` logs a warning for non-localhost `http://`.

Procedures for issuing/rotating/revoking tokens and the leak checklist live in [docs/RUNBOOK-secrets.md](docs/RUNBOOK-secrets.md); build/verify/package/rollback in [docs/RUNBOOK-build-release.md](docs/RUNBOOK-build-release.md).

## Dependencies

Runtime deps are pinned with `==` for reproducible bundles and were audited on 2026-08-18. Keep `opencv-contrib-python==4.10.0.84` because PaddleOCR pulls PaddleX 3.7's `ocr-core` extra, which requires that exact wheel; do not add a headless OpenCV wheel beside it because both install the `cv2` namespace. Keep `numpy==2.3.5` because PaddleX requires `<2.4`; these are compatibility ceilings, not stale pins. The current DICOM set already covers JPEG/JPEG-LS through `pylibjpeg-libjpeg`, JPEG2000 through Pillow, and RLE through pydicom. The PyPI `gdcm` package is not the official binding; use `python-gdcm` only if that separate codec stack is deliberately selected.

Both build paths bundle pre-downloaded models from `%USERPROFILE%\.paddlex\official_models` (`PP-OCRv5_mobile_det`, `en_PP-OCRv5_mobile_rec`) — run the app once before building so they exist. For compressed DICOM, packaging must include `pydicom.pixels.decoders.pylibjpeg`, package `libjpeg`, native module `_libjpeg`, and the `pylibjpeg-libjpeg` distribution metadata because codec discovery uses entry points. numpy 2.x internals are listed as hidden imports under both `numpy.core` and `numpy._core` in the PyInstaller path.
