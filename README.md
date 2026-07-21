# VitalLens

VitalLens is a Python/Tkinter desktop app for medical data processing. The project groups several internal workflows into one Windows-friendly UI.

## Main Modules

| Module | Purpose |
| --- | --- |
| XML → Excel | Decode Base64 payloads from BHYT XML files (`XML3`/`XML4` only, no column filtering) and export one Excel sheet per type |
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
├── .env.example             # Template for secrets (the ONLY config file that ships)
├── icon.ico
├── README.md
├── docs/
│   ├── RUNBOOK-build-release.md   # Build, verify, package, roll back
│   └── RUNBOOK-secrets.md         # Issue / rotate / revoke tokens
└── apps/
    ├── __init__.py
    ├── app.py               # Root Tk window + page navigation
    ├── config.py            # Theme constants + Settings dataclass (env-aware)
    ├── logging_setup.py     # Centralized logging + Paddle env flags
    ├── widgets/             # Shared UI widgets
    │   ├── buttons.py       # StyledButton
    │   ├── status.py        # StatusBar
    │   ├── header.py        # make_header / make_section
    │   ├── scrollable.py    # ScrollableFrame
    │   ├── dialogs.py       # Copyable info/warning/error + batch report
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
    │   ├── export_store.py  # Durable pending/uploaded state (meta.json)
    │   └── upload_api.py    # HTTP POST (PDF + CSV pair) + retry
    └── processing/          # CPU-bound: OCR, XML decode
        ├── xml_to_excel.py
        └── xray.py          # PaddleOCR text removal + DICOM anonymization
```

### Three-Layer Architecture

- **pages/** — UI only (tkinter). No direct file I/O, no socket calls.
- **services/** — Pure Python business logic. Testable with pytest, reusable from CLI. All I/O goes through `StorageBackend` so local/SFTP share the same code path.
- **processing/** — CPU-bound work (OCR, PDF render). No UI or storage knowledge.

## Data Flow

### Lab PDF Upload — pending → uploaded

The upload workflow is built around a **durable on-disk state machine**, so
closing the app mid-batch never loses track of what has been sent.

```text
  source PDF  ──►  redact + fill form  ──►  Save
                                              │
                                              ▼
                        <output_dir>/pending/                 ← "chưa upload"
                          ├── <name>.pdf         (rasterized, regions blacked out)
                          ├── <name>.csv         (form metadata)
                          └── <name>.meta.json   (ledger — source of truth)
                                              │
                                     tick ☑ + press Upload
                                              │
                          ┌───────────────────┴───────────────────┐
                       success                                 failure
                          │                                       │
                          ▼                                       ▼
             <output_dir>/uploaded/                stays in pending/, meta.json
               (all 3 files moved)                 records last_error + attempts,
                                                   pair stays ticked for retry
```

`meta.json` is the authority, not the UI. On startup `export_store.read_all()`
rescans both folders and rebuilds the lists, so pending work survives a restart,
a crash, or a machine swap (the whole `<output_dir>` is portable).

Fields that drive retry behavior:

| Field | Meaning |
| --- | --- |
| `pdf_sent` / `csv_sent` | Per-file delivery flags — a retry skips whatever already landed, so a half-sent pair never uploads the same file twice |
| `attempts` | How many times this pair has been tried |
| `last_error` | Why the last attempt failed (shown in the list and status bar) |
| `last_attempt_at` / `uploaded_at` | Timestamps for the audit trail |

A batch **does not stop at the first failure** — every ticked pair is attempted,
and a report at the end lists what went up and what did not, with reasons.

### Where PII is removed

| Stage | What is stripped | Code |
| --- | --- | --- |
| Lab PDF | User-drawn regions are rasterized over in black — the underlying text is gone, not just covered | `services/pdf_redact.py` |
| X-Ray | Burned-in text detected via PaddleOCR and painted out; DICOM metadata anonymized | `processing/xray.py` |
| XML → Excel | Non-whitelisted columns dropped during decode | `processing/xml_to_excel.py` |
| CSV export | Cells starting with `= + - @` are prefixed with `'` to block formula injection in Excel/Sheets | `pages/upload/page.py` |

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

### Setup (same steps for developers and end users)

**Every machine creates its own `.env`.** Builds ship `.env.example` only — no
release artifact ever contains a real credential.

```powershell
copy .env.example .env
notepad .env
```

`.env` example:

```env
API_UPLOAD_URL=https://your-api.example.org/api/v2/file/upload
API_BEARER_TOKEN=your_token_here
API_UPLOAD_OWNER=you@example.org

# SFTP overrides (optional — defaults live in apps/config.py)
# SFTP_HOST=datastore.oucru.org
# SFTP_PORT=22
# SFTP_DEMO_MODE=false
# SFTP_PATH=/EI_SHARE/.received/13NV/PROCESSING
```

Important keys:

- `API_UPLOAD_URL` — Backend endpoint for PDF + CSV upload. **Use `https://`** — the bearer token travels in this request, and plain `http://` puts it on the wire in cleartext. When empty, the upload flow falls back to a demo confirmation dialog.
- `API_BEARER_TOKEN` — Bearer token appended as `Authorization: Bearer ...`.
- `API_UPLOAD_OWNER` — Default value pre-filled in the owner-email prompt.
- `SFTP_DEMO_MODE=true` — Use local folders instead of a real SFTP server.
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_PATH` — SFTP connection settings.

OS-level environment variables win over `.env` (`override=False`), which is handy
for a temporary override without editing the file.

### Secret Handling Rules

- `.env` / `env` are gitignored. Never commit real tokens. Share `.env.example` only.
- Tokens are issued **per user**, not shared — one leak revokes one account.
- The app never logs secret values. `config_debug.log` is written **only** when `VITALLENS_DEBUG_CONFIG=1` is set, and redacts secrets to a length.
- `build.bat` refuses to finish if `.env`, `env`, or `config_debug.log` is found in the dist folder.

Full procedures for issuing, rotating, and revoking tokens — plus the leaked-token
incident checklist — are in **[docs/RUNBOOK-secrets.md](docs/RUNBOOK-secrets.md)**.

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
3. Copies **`.env.example`** (the template — never the real `.env`) next to the EXE
4. Copies `icon.ico` to the dist folder
5. Scans the dist folder for secrets and **fails the build** if any are found

### Manual Build

```powershell
conda activate paddleocr
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env.example dist\VitalLens\.env.example
```

A manual build skips the automatic secret scan — run the verification checklist
in the release runbook before shipping.

### Output Layout

```text
dist\VitalLens\
├── VitalLens.exe
├── .env.example       ← template; the user renames it to .env and fills it in
├── icon.ico
├── _internal\...      ← PyInstaller runtime + bundled packages
└── ...
```

There is deliberately **no `.env`** here. If you see one, the folder is not
shippable — see the runbook.

### Ship to End Users

1. Run `build.bat` and confirm it ends with `[OK] No secret files found`.
2. Zip `dist\VitalLens\` to a path **outside** `dist\`, then hand the ZIP over.
3. Send the user's token through a separate channel (password manager or encrypted message), never in the same email as the ZIP.
4. The user copies `.env.example` to `.env` and fills in their own values — no rebuild required for later changes.

Step-by-step build, verification, packaging, and rollback procedures are in
**[docs/RUNBOOK-build-release.md](docs/RUNBOOK-build-release.md)**.

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
