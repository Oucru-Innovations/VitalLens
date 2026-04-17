# VitalLens

VitalLens is a Python/Tkinter desktop app for medical data processing. The project groups several internal workflows into one Windows-friendly UI.

## Main modules

| Module | Purpose |
| --- | --- |
| XML -> Excel | Decode Base64 payloads from BHYT XML files, extract `XML4`, and export Excel |
| X-ray anonymization | Detect burned-in text with OCR and anonymize DICOM metadata |
| OCR review | Review OCR output from LAB / bedside monitor folders, correct JSON, and export Excel |
| Lab PDF upload | View PDFs, redact sensitive regions, fill metadata, save PDF + CSV, and optionally upload via API |

## Project structure

```text
VitalLens/
|-- main.py
|-- requirements.txt
|-- build_exe.spec
|-- build.bat
|-- README.md
`-- apps/
    |-- __init__.py
    |-- app.py                  # Root Tk window + navigation
    |-- config.py               # Theme + Settings dataclass (env-aware)
    |-- logging_setup.py        # Cấu hình logging + Paddle env flags
    |-- widgets/                # Widgets dùng chung
    |   |-- __init__.py         # re-export để giữ API cũ
    |   |-- buttons.py          # StyledButton
    |   |-- status.py           # StatusBar
    |   |-- header.py           # make_header / make_section
    |   `-- date_picker.py      # DatePicker (popup lịch)
    |-- pages/                  # UI layer
    |   |-- home.py
    |   |-- xml_page.py
    |   |-- xray_page.py
    |   |-- ocr/                # OCR review (đã split)
    |   |   |-- __init__.py
    |   |   |-- page.py         # UI shell
    |   |   |-- form_builder.py # dựng form lab / monitor
    |   |   `-- media_viewer.py # xem trước PDF / ảnh / DICOM
    |   `-- upload/             # Upload PDF xét nghiệm
    |       |-- __init__.py
    |       `-- page.py
    |-- services/               # Business + I/O thuần Python
    |   |-- __init__.py
    |   |-- storage.py          # StorageBackend (Local + SFTP)
    |   |-- payload_io.py       # JSON / CSV qua storage
    |   |-- excel_export.py     # list[dict] -> .xlsx
    |   |-- lab_records.py      # scan PROCESSING dir
    |   |-- pdf_redact.py       # render PDF + tô đen
    |   `-- upload_api.py       # HTTP POST pair PDF+CSV
    `-- processing/             # CPU-bound: OCR, XML decode
        |-- xml_to_excel.py
        `-- xray.py
```

### Kiến trúc 3 lớp

- **pages/** chỉ chứa UI (tkinter). Không tự mở socket, không gọi `open()`
  trực tiếp, không biết gì về SFTP protocol.
- **services/** là code thuần Python - test được bằng pytest, dùng lại được
  cho CLI. Mọi I/O đi qua `StorageBackend` nên local/SFTP dùng cùng code path.
- **processing/** là CPU-bound (OCR, PDF render). Không biết UI hay storage.

## Requirements

- Windows is the primary target for running and building.
- Python 3.10+ is recommended.
- PaddleOCR / PaddlePaddle dependencies are large, so using a virtual environment or Conda env is strongly recommended.

## Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If you use Conda instead:

```powershell
conda create -n vitallens python=3.10 -y
conda activate vitallens
pip install -r requirements.txt
```

## Run locally

```powershell
python main.py
```

`main.py` sets Paddle / OCR environment flags before the UI is imported, which is important for startup stability.

## Configuration

Runtime defaults live in `apps/config.py` (`Settings` dataclass). Secrets and
per-deployment overrides are loaded from a dotenv file at startup via
`python-dotenv`.

### Where secrets are loaded from

At startup `apps/config.py` looks for a config file **in the app root** and
loads it into `os.environ` (without overriding existing env vars):

1. `.env` (preferred, standard dotenv convention)
2. `env` (fallback - handy on Windows where Explorer refuses to create
   filenames starting with a dot)

"App root" means:

- During `python main.py`: the repo root (same folder as `main.py`).
- In the packaged EXE: the folder that contains `VitalLens.exe`
  (i.e. `dist\VitalLens\`).

### Dev setup

Copy the template and fill in real values:

```powershell
copy .env.example .env
notepad .env
```

`.env` example:

```env
API_UPLOAD_URL=https://your-api.example.org/upload
API_BEARER_TOKEN=your_token_here

# SFTP overrides (optional - defaults live in apps/config.py)
# SFTP_HOST=datastore.oucru.org
# SFTP_PORT=22
# SFTP_DEMO_MODE=false
# SFTP_PATH=/EI_SHARE/.received/13NV/PROCESSING
```

Important keys:

- `API_UPLOAD_URL`: backend endpoint for PDF + CSV upload. When empty, the
  upload flow falls back to a demo confirmation dialog.
- `API_BEARER_TOKEN`: bearer token appended as `Authorization: Bearer ...`.
- `SFTP_DEMO_MODE=true`: use local folders instead of a real SFTP server.
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_PATH`: SFTP connection settings.

`.env` / `env` are gitignored. Never commit real tokens. Share
`.env.example` only.

## Build EXE

Quick build (also auto-copies `.env` next to the EXE):

```powershell
build.bat
```

Manual build:

```powershell
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env dist\VitalLens\.env
```

The packaged app is generated in `dist\VitalLens\`. Final layout for a
usable distribution:

```text
dist\VitalLens\
|-- VitalLens.exe
|-- .env                <-- secrets, NOT bundled into the EXE
|-- _internal\...       <-- PyInstaller runtime
`-- ...
```

### Ship to end users

1. Run `build.bat` on a build machine that already has `.env` filled in.
2. Zip the whole `dist\VitalLens\` folder and hand it to the user.
3. If the user needs to change the API URL/token later, edit
   `dist\VitalLens\.env` directly - no rebuild required.

## Notes

- `build_exe.spec` collects Paddle / OCR dependencies and bundles pre-downloaded PaddleX models when available in `%USERPROFILE%\.paddlex\official_models`.
- The upload flow falls back to a demo confirmation when `API_UPLOAD_URL` is empty.
- PDF redaction is rendered back to PDF from rasterized pages, so output files may be larger than the originals.
