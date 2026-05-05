# VitalLens

VitalLens is a Python/Tkinter desktop app for medical data processing. The project groups several internal workflows into one Windows-friendly UI.

## Main Modules

| Module | Purpose |
| --- | --- |
| XML → Excel | Decode Base64 payloads from BHYT XML files, extract `XML4`, and export Excel |
| X-Ray Anonymization | Detect burned-in text with PaddleOCR and anonymize DICOM metadata |
| OCR Review | Review OCR output from LAB / bedside monitor folders, correct JSON, and export Excel |
| Lab PDF Upload | View PDFs, redact sensitive regions, fill metadata, save PDF + CSV, and optionally upload via API |

## Project Structure

```text
VitalLens/
├── main.py                  # Entry point (sets Paddle env flags before UI)
├── requirements.txt
├── build_exe.spec           # PyInstaller spec (onedir)
├── build.bat                # One-click build script
├── .env.example             # Template for secrets
├── icon.ico
├── README.md
└── apps/
    ├── __init__.py
    ├── app.py               # Root Tk window + page navigation
    ├── config.py            # Theme constants + Settings dataclass (env-aware)
    ├── logging_setup.py     # Centralized logging + Paddle env flags
    ├── widgets/             # Shared UI widgets
    │   ├── buttons.py       # StyledButton
    │   ├── status.py        # StatusBar
    │   ├── header.py        # make_header / make_section
    │   └── date_picker.py   # DatePicker (calendar popup)
    ├── pages/               # UI layer (tkinter Frames)
    │   ├── home.py
    │   ├── xml_page.py
    │   ├── xray_page.py
    │   ├── ocr/             # OCR review (multi-file)
    │   │   ├── page.py      # UI shell
    │   │   ├── form_builder.py
    │   │   └── media_viewer.py
    │   └── upload/          # Lab PDF upload
    │       └── page.py
    ├── services/            # Business logic + I/O (pure Python)
    │   ├── storage.py       # StorageBackend (Local + SFTP)
    │   ├── payload_io.py    # JSON / CSV via storage
    │   ├── excel_export.py  # list[dict] → .xlsx
    │   ├── lab_records.py   # Scan PROCESSING directory
    │   ├── pdf_redact.py    # Render PDF + redact regions
    │   └── upload_api.py    # HTTP POST (PDF + CSV pair)
    └── processing/          # CPU-bound: OCR, XML decode
        ├── xml_to_excel.py
        └── xray.py          # PaddleOCR text removal + DICOM anonymization
```

### Three-Layer Architecture

- **pages/** — UI only (tkinter). No direct file I/O, no socket calls.
- **services/** — Pure Python business logic. Testable with pytest, reusable from CLI. All I/O goes through `StorageBackend` so local/SFTP share the same code path.
- **processing/** — CPU-bound work (OCR, PDF render). No UI or storage knowledge.

## Requirements

- **OS**: Windows (primary target for running and building)
- **Python**: 3.10+ (tested with 3.12)
- **Conda environment**: `paddleocr` (recommended for PaddlePaddle dependencies)

## Setup

### Using Conda (recommended)

```powershell
conda create -n paddleocr python=3.12 -y
conda activate paddleocr
pip install -r requirements.txt
```

### Using venv

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run Locally

```powershell
conda activate paddleocr
python main.py
```

`main.py` sets Paddle/OCR environment flags **before** the UI is imported, which is important for startup stability.

## Configuration

Runtime defaults live in `apps/config.py` (`Settings` dataclass). Secrets and per-deployment overrides are loaded from a dotenv file at startup.

### Where Secrets are Loaded From

At startup `apps/config.py` looks for a config file **in the app root** and loads it into `os.environ` (without overriding existing env vars):

1. `.env` (preferred, standard dotenv convention)
2. `env` (fallback — handy on Windows where Explorer refuses to create filenames starting with a dot)

When `python-dotenv` is not available (common in PyInstaller bundles), a built-in fallback parser reads the `.env` file directly.

**App root** means:
- During development (`python main.py`): the repo root (same folder as `main.py`).
- In the packaged EXE: the folder containing `VitalLens.exe` (i.e. `dist\VitalLens\`).

### Dev Setup

```powershell
copy .env.example .env
notepad .env
```

`.env` example:

```env
API_UPLOAD_URL=https://your-api.example.org/upload
API_BEARER_TOKEN=your_token_here

# SFTP overrides (optional — defaults live in apps/config.py)
# SFTP_HOST=datastore.oucru.org
# SFTP_PORT=22
# SFTP_DEMO_MODE=false
# SFTP_PATH=/EI_SHARE/.received/13NV/PROCESSING
```

Important keys:

- `API_UPLOAD_URL` — Backend endpoint for PDF + CSV upload. When empty, the upload flow falls back to a demo confirmation dialog.
- `API_BEARER_TOKEN` — Bearer token appended as `Authorization: Bearer ...`.
- `SFTP_DEMO_MODE=true` — Use local folders instead of a real SFTP server.
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_PATH` — SFTP connection settings.

`.env` / `env` are gitignored. Never commit real tokens. Share `.env.example` only.

## Build EXE

### Prerequisites

```powershell
conda activate paddleocr
```

Ensure PaddleOCR models are downloaded before building (run the app once, or let `paddlex` download them automatically to `%USERPROFILE%\.paddlex\official_models`).

### Quick Build

```powershell
conda activate paddleocr
build.bat
```

The script automatically:
1. Detects the active Conda `paddleocr` environment
2. Runs PyInstaller with `build_exe.spec`
3. Copies `.env` next to the EXE
4. Copies `icon.ico` to the dist folder

### Manual Build

```powershell
conda activate paddleocr
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env dist\VitalLens\.env
```

### Output Layout

```text
dist\VitalLens\
├── VitalLens.exe
├── .env               ← secrets, NOT bundled into the EXE
├── icon.ico
├── _internal\...      ← PyInstaller runtime + bundled packages
└── ...
```

### Ship to End Users

1. Run `build.bat` on a build machine that has `.env` filled in.
2. Zip the entire `dist\VitalLens\` folder and hand it to the user.
3. If the user needs to change the API URL/token later, edit `dist\VitalLens\.env` directly — no rebuild required.

## OCR Confidence Thresholds

The X-Ray text removal uses PaddleOCR with configurable confidence filters to prevent false-positive detections (e.g. noise or artifacts mistakenly identified as text):

| Parameter | Default | Description |
| --- | --- | --- |
| `OCR_REC_SCORE_THRESHOLD` | 0.6 | Recognition confidence — skip text recognized with < 60% confidence |
| `OCR_DET_SCORE_THRESHOLD` | 0.5 | Detection confidence — skip text regions detected with < 50% confidence |
| `OCR_MIN_TEXT_LENGTH` | 2 | Skip results with fewer than 2 characters |

These constants are defined at the top of `apps/processing/xray.py`. Increase thresholds to reduce false positives; decrease to catch more real text.

## Notes

- `build_exe.spec` collects Paddle/OCR dependencies and bundles pre-downloaded PaddleX models from `%USERPROFILE%\.paddlex\official_models`.
- The upload flow falls back to a demo confirmation when `API_UPLOAD_URL` is empty.
- PDF redaction renders pages as rasterized images, so output files may be larger than the originals.
- The `.env` fallback parser handles both `KEY=VALUE` and `KEY="VALUE"` formats with proper quote stripping.
