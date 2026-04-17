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
    |-- app.py
    |-- config.py
    |-- widgets.py
    |-- pages/
    |   |-- home.py
    |   |-- xml_page.py
    |   |-- xray_page.py
    |   |-- ocr_page.py
    |   `-- upload_pdf_page.py
    `-- processing/
        |-- xml_to_excel.py
        `-- xray.py
```

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

Edit runtime config in `apps/config.py`.

Important settings:

- `SFTP_DEMO_MODE = True`: use local folders instead of a real SFTP server
- `SFTP_HOST`, `SFTP_PORT`: SFTP connection settings
- `SFTP_PATH`: local demo folder or remote root path
- `API_UPLOAD_URL`: backend endpoint for PDF + CSV upload
- `API_BEARER_TOKEN`: optional bearer token for upload requests

You can also place a `.env` file in the repo root:

```env
API_UPLOAD_URL=https://your-api.example/upload
API_BEARER_TOKEN=your_token_here
```

## Build EXE

Quick build:

```powershell
build.bat
```

Manual build:

```powershell
python -m PyInstaller build_exe.spec --noconfirm --clean
```

The packaged app is generated in `dist\VitalLens\`.

## Notes

- `build_exe.spec` collects Paddle / OCR dependencies and bundles pre-downloaded PaddleX models when available in `%USERPROFILE%\.paddlex\official_models`.
- The upload flow falls back to a demo confirmation when `API_UPLOAD_URL` is empty.
- PDF redaction is rendered back to PDF from rasterized pages, so output files may be larger than the originals.
