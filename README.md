# VitalLens

VitalLens is a Python/Tkinter desktop app for medical data processing. The project groups several internal workflows into one Windows-friendly UI.

## Main Modules

| Module | Purpose |
| --- | --- |
| XML → Excel | Decode Base64 payloads from BHYT XML files (`XML4` only), look up `MA_DICH_VU` in the medical service catalogue, and export the `Include` group plus an unclassified sheet |
| X-Ray Anonymization | Detect burned-in text with PaddleOCR and anonymize DICOM metadata |
| OCR Review | Review OCR output from LAB / bedside monitor folders, correct JSON, and export Excel |
| Lab PDF Upload | View PDFs, redact sensitive regions, fill metadata, save PDF + CSV, and optionally upload via API |

## Project Structure

```text
VitalLens/
├── main.py                  # Entry point (sets Paddle env flags before UI)
├── requirements.txt         # Runtime deps (pinned)
├── requirements-build.txt   # Runtime + PyInstaller (build machines only)
├── build_exe.spec           # PyInstaller spec (onedir)
├── build.bat                # One-click build script
├── .env.example             # Template for secrets (the ONLY config file that ships)
├── icon.ico
├── README.md
├── database/
│   └── database_medical.csv # Service catalogue (SHA-256 pinned in medical_catalog.py)
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
    │   ├── medical_catalog.py  # Catalogue lookup + integrity check
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

### XML4 → Excel — catalogue lookup & filter

Only `LOAIHOSO` = **XML4** is decoded; every other record type is skipped.
Each decoded row is matched against the service catalogue on
`MA_DICH_VU` = `ID_SERVICE`, which decides both the added `TEN_DICH_VU` (formerly `Name_Method` in operation database) and
where the row lands:

```text
  XML4 record ──► MA_DICH_VU ──► database_medical.csv (ID_SERVICE)
                                          │
              ┌───────────────────────────┼───────────────────────────┐
         Group=Include                Group=Exclude              no match
              │                            │                          │
              ▼                            ▼                          ▼
   sheet "XML4_Include"                 dropped            sheet "XML4_ChuaPhanLoai"
   + TEN_DICH_VU filled              (counted only)        + TEN_DICH_VU blank
```

- `TEN_DICH_VU` is inserted immediately after `MA_DICH_VU` so the code and its
  name read together.
- Matching ignores surrounding whitespace and letter case — a few catalogue
  codes carry a lowercase letter (`27.205b.0463`).
- Rows with a **missing or empty** `MA_DICH_VU` go to the unclassified sheet, not
  the bin: without a code there is no evidence the row is `Exclude`.
- A `Group` value that is neither `Include` nor `Exclude` (typo in the CSV) also
  lands in the unclassified sheet and is logged.
- If no usable catalogue can be loaded, the run **fails with an error instead of
  exporting an unfiltered file**. The message names the location and the reason.

#### Step 2 — optional Excel file (two modes)

The XML page has one file picker for an optional Excel file. Which mode runs is
decided by the **header row**, so there is no extra switch to remember:

| Header contains | Mode | What happens |
| --- | --- | --- |
| `USUBJID` **and** `EMR_ID` | study list | adds a `MA_NTG` column, filters by date, hides `ID` and `MA_LK` |
| anything else | plain mapping | A1 names the XML4 field to join on; the remaining columns are appended, nothing is filtered |

**Study list.** Columns `USUBJID`, `EMR_ID`, plus an optional date range
(`START_DATE` and one of `END_DATE` / `FROM_DATE` / `TO_DATE`). Order does not
matter. The `USUBJID` value is exported under the column name `MA_NTG` — the
header in your file stays `USUBJID`. `EMR_ID` is matched to a record two ways,
in this order:

```text
  EMR_ID ──► MA_LK                      (whole value)
         └─► last 10 chars of ID, then of ID_GOC
```

- The full match is tried first because it is the stronger evidence. If two
  `EMR_ID`s share the same last 10 characters, matching by `ID` is disabled for
  those codes rather than guessing — a wrong `MA_NTG` mixes up patients.
- With a date range, `NGAY_KQ` is compared on **date only** (`yyyymmdd`); the
  time part is ignored so both endpoints count as whole days. Rows with no
  dates in the list are not filtered.
- A date the app cannot read **fails the run** — silently ignoring it would
  export data from outside the study window with nobody noticing. A row that
  matches an `EMR_ID` but has no readable `NGAY_KQ` is kept and reported.
- Rows that match no `EMR_ID` are **not thrown away**: they go to sheet
  `XML4_KhongKhopHRN`, which keeps `ID` and `MA_LK` so the list can be
  corrected. `ID_GOC` stays on every sheet.

#### The catalogue is release data, not user config

The filter decides which services appear in an export, so it must produce the
same result on every machine and any deviation must be visible. It is locked
down in three ways:

| Control | Effect |
| --- | --- |
| **Bundle-only path** | A packaged build reads *only* `sys._MEIPASS/database/` (inside `_internal\`). No CSV ships next to `VitalLens.exe`, and a file dropped there is never read. Running from source reads the repo copy. |
| **SHA-256 fingerprint** | `CATALOG_SHA256` in [`medical_catalog.py`](apps/services/medical_catalog.py) is checked on every load, *before* parsing. A modified catalogue stops the XML4 feature with an error — it never silently filters by different rules. |
| **Build-time gate** | `build_exe.spec` recomputes the hash and **refuses to build** on mismatch, so a release can never pair an EXE with a catalogue it does not expect. |

The fingerprint lives in source, so it is under version control: changing the
catalogue requires editing the CSV *and* the constant in the same commit, going
through review, and rebuilding. The loaded fingerprint is logged, so a support
question ("which catalogue did that export use?") has an answer.

**Updating the catalogue** now requires a release — this is the cost of the
lockdown, and it is deliberate:

```powershell
# 1. replace database\database_medical.csv
# 2. get the new fingerprint
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('database/database_medical.csv').read_bytes()).hexdigest())"
# 3. paste it into CATALOG_SHA256 in apps\services\medical_catalog.py
# 4. commit both files together, then build.bat
```

> **What this does and does not stop.** It stops accidental edits, well-meaning
> "I'll just fix one row" changes, corruption, and a swapped-in file — the
> realistic risks for a clinical desktop tool. It does **not** stop a user with
> local admin, who can unpack the bundle and patch the constant out of the
> bytecode. Any check that ships with the app can be removed from the app. If
> the catalogue must be tamper-proof in a hostile sense, the filtering has to
> happen server-side, behind the API the app already talks to.

Re-saving the CSV from Excel must use **CSV UTF-8** — the file is full of
Vietnamese text and the default `CSV (Comma delimited)` writes cp1258, which
changes the bytes and therefore the fingerprint.

> **Caveat — `MA_BS_DOC_KQ` is not scrubbed at decode time.**
> `XML4_EXCLUDED_COLUMNS` is applied only in `_sheet_columns()`, i.e. when
> choosing worksheet headers. The doctor identifier is still parsed into every
> record dict and lives in memory for the whole run. Any new export path that
> does not route through `_sheet_columns()` — a debug dump, a JSON writer, an
> extra sheet — will leak it.

### Where PII is removed

| Stage | What is stripped | Code |
| --- | --- | --- |
| Lab PDF | User-drawn regions are rasterized over in black — the underlying text is gone, not just covered | `services/pdf_redact.py` |
| X-Ray | Burned-in text detected via PaddleOCR and painted out; DICOM metadata anonymized | `processing/xray.py` |
| XML → Excel | `MA_BS_DOC_KQ` omitted when picking sheet columns (it *is* decoded and held in memory — see caveat below); only `Include` services reach the main sheet; with a study list, `ID`/`MA_LK` give way to `STUDY_ID` on the matched sheets | `processing/xml_to_excel.py` |
| CSV export | Cells starting with `= + - @` are prefixed with `'` to block formula injection in Excel/Sheets | `pages/upload/page.py` |

## Requirements

- **OS**: Windows (primary target for running and building)
- **Python**: 3.12 (pins in `requirements.txt` are verified on 3.12.13)
- **Environment**: conda or venv — both work. Everything installs via pip, so neither is smaller than the other.

Dependencies are split so a runtime machine never pulls the build toolchain:

| File | Contents | Install when |
| --- | --- | --- |
| `requirements.txt` | Runtime deps, pinned with `==` | Running from source |
| `requirements-build.txt` | The above **plus** PyInstaller | Building the EXE |

## Setup

### Using Conda (recommended)

```powershell
conda create -n vitallens python=3.12 -y
conda activate vitallens
pip install -r requirements-build.txt      # or requirements.txt to just run
```

### Using venv

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-build.txt
```

### Why the pins

Versions are pinned so two builds made months apart produce the same bundle.
Only directly-used packages are pinned; pip resolves the rest.

Two entries are worth knowing about:

- **`opencv-python-headless`** — no package declares OpenCV as a dependency, but `paddlex` imports `cv2` in 47 files, so it must be pinned explicitly. The `headless` variant is used because this is a Tkinter app that never opens an OpenCV window (the previously-installed `opencv-contrib-python` cost ~121 MB versus roughly a third of that).
- **`gdcm` was removed** — the PyPI package by that name is not the official GDCM binding and fails to import (`DLL load failed while importing _gdcmswig`), so `pydicom` reported it unavailable the whole time. For full codec coverage in one package, use `python-gdcm` instead.

### DICOM compression support

`pydicom` cannot decode compressed pixel data on its own. The pinned set covers
**JPEG baseline/lossless** via `pylibjpeg-libjpeg`. JPEG2000 and RLE have **no
decoder** in the current set — `ds.pixel_array` will raise on such files. If your
X-rays use them, uncomment these in `requirements.txt`:

```text
pylibjpeg-openjpeg==2.5.0    # JPEG2000 — common for CR/DX
pylibjpeg-rle==2.2.0         # RLE Lossless
```

Check what your data actually uses before deciding:

```powershell
python -c "import pydicom,sys; print(pydicom.dcmread(sys.argv[1]).file_meta.TransferSyntaxUID)" path\to\file.dcm
```

## Run Locally

```powershell
conda activate vitallens
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
conda activate vitallens
```

Ensure PaddleOCR models are downloaded before building (run the app once, or let `paddlex` download them automatically to `%USERPROFILE%\.paddlex\official_models`).

### Quick Build

```powershell
conda activate vitallens
build.bat
```

The script automatically:
1. Detects the active Conda `vitallens` environment
2. Runs PyInstaller with `build_exe.spec`
3. Copies **`.env.example`** (the template — never the real `.env`) next to the EXE
4. Copies `icon.ico`, and removes any stale `dist\VitalLens\database\` left by an
   older build — the catalogue ships inside `_internal\` only
5. Scans the dist folder for secrets and **fails the build** if any are found

The PyInstaller step also verifies the catalogue fingerprint and aborts on
mismatch, so this happens before anything else runs.

### Manual Build

```powershell
conda activate vitallens
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
│   └── database\database_medical.csv   ← the only catalogue copy; fingerprint-checked
└── ...
```

There is deliberately **no `database\`** folder next to the EXE. If you see one,
it is a leftover from an older build — the app ignores it, and its presence only
misleads users into thinking the catalogue is theirs to edit.

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
