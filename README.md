# VitalLens

VitalLens is a Python/Tkinter desktop app for medical data processing. The project groups several internal workflows into one Windows-friendly UI.

## Main Modules

| Module | Purpose |
| --- | --- |
| XML → Excel | Decode Base64 payloads from BHYT XML files (`XML4` only), look up `MA_DICH_VU` in the medical service catalogue, and export the `Include` group plus an unclassified sheet |
| X-Ray Anonymization | Detect burned-in text with PaddleOCR and anonymize DICOM metadata |
| OCR Review | Review OCR output from LAB / bedside monitor folders, correct JSON, and export Excel |
| Lab PDF Upload | View PDFs, redact sensitive regions, fill metadata, save PDF + CSV, and optionally upload via API |
| Upload File đã xử lý | Pick any already-processed files, auto-parse study/patient/type/date from the filename, and route each to SFTP or the HTTP API |

## Project Structure

```text
VitalLens/
├── main.py                  # Entry point (sets Paddle env flags before UI)
├── verify_catalog.py        # Standalone catalogue fingerprint check (also step 1 of build_nuitka.bat)
├── smoke_nuitka.py          # Manual smoke test for a built EXE
├── requirements.txt         # Runtime deps (pinned)
├── requirements-build.txt   # Runtime + PyInstaller + Nuitka
├── build_exe.spec           # PyInstaller spec (onedir)
├── build.bat                # Fast local/debug build (PyInstaller onedir)
├── build_nuitka.bat         # Release build (Nuitka onefile)
├── .env.example             # Tracked template only; no real credential
├── icon.ico
├── README.md
├── database/
│   └── database_medical.csv # Service catalogue (SHA-256 pinned in medical_catalog.py)
├── docs/
│   ├── RUNBOOK-build-release.md   # Build, verify, package, roll back
│   └── RUNBOOK-secrets.md         # Issue / rotate / revoke tokens
├── .github/workflows/
│   ├── ci.yml            # compileall + tkinter-free module self-checks
│   └── release.yml       # Tag → build → publish EXE + latest.json
└── apps/
    ├── __init__.py          # __version__
    ├── app.py               # Root Tk window + page navigation
    ├── config.py            # Theme constants + Settings dataclass (env-aware)
    ├── logging_setup.py     # Centralized logging + Paddle env flags
    ├── runtime_paths.py     # Locate bundle/app dirs under PyInstaller vs Nuitka
    ├── widgets/             # Shared UI widgets
    │   ├── buttons.py       # StyledButton
    │   ├── status.py        # StatusBar
    │   ├── header.py        # make_header / make_section
    │   ├── scrollable.py    # ScrollableFrame
    │   ├── dialogs.py       # Copyable info/warning/error + batch report
    │   ├── date_picker.py   # DatePicker (calendar popup)
    │   ├── settings_dialog.py  # ⚙ Cấu hình kết nối popup → %APPDATA%\VitalLens\.env
    │   ├── sftp.py          # SFTP login popup, shared across pages
    │   └── upload_batch.py  # SFTP/HTTP upload-method chooser + batch runner
    ├── pages/               # UI layer (tkinter Frames)
    │   ├── home.py
    │   ├── xml_page.py
    │   ├── xray_page.py
    │   ├── multi_upload_page.py   # Upload File đã xử lý (auto-route by filename)
    │   ├── ocr/             # OCR review (multi-file)
    │   │   ├── page.py      # UI shell
    │   │   ├── form_builder.py
    │   │   └── media_viewer.py
    │   └── upload/          # Lab PDF upload
    │       └── page.py
    ├── services/            # Business logic + I/O (pure Python)
    │   ├── storage.py       # StorageBackend (Local + SFTP)
    │   ├── sftp_session.py  # Singleton SFTP session shared across pages
    │   ├── payload_io.py    # JSON / CSV via storage
    │   ├── excel_export.py  # list[dict] → .xlsx
    │   ├── lab_records.py   # Scan PROCESSING directory
    │   ├── medical_catalog.py  # Catalogue lookup + integrity check
    │   ├── mapping_excel.py    # Step-2 Excel, plain-mapping mode
    │   ├── study_mapping.py    # Step-2 Excel, study-list mode (USUBJID/EMR_ID)
    │   ├── pdf_redact.py    # Render PDF + redact regions
    │   ├── export_store.py  # Durable pending/uploaded state (meta.json)
    │   ├── upload_api.py    # HTTP POST (PDF + CSV pair) / SFTP upload + retry
    │   ├── update_check.py  # Poll UPDATE_MANIFEST_URL, never auto-installs
    │   ├── user_config.py   # Reads/writes %APPDATA%\VitalLens\.env
    │   └── parser/
    │       └── file_name.py # FileNameParser — guesses study/patient/type/date
    └── processing/          # CPU-bound: OCR, XML decode
        ├── xml_to_excel.py
        └── xray.py          # PaddleOCR text removal + DICOM anonymization
```

### Three-Layer Architecture

- **pages/** — UI only (tkinter). No direct file I/O, no socket calls.
- **services/** — Pure Python business logic, reusable from CLI and suitable for direct self-checks. The repo has no pytest suite. All I/O goes through `StorageBackend` so local/SFTP share the same code path.
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
| `id` | Stable random UUID for the pair; also written as CSV `export_id` |
| `pdf_sent` / `csv_sent` | Per-file delivery flags — a retry skips whatever already landed, so a half-sent pair never uploads the same file twice |
| `attempts` | How many times this pair has been tried |
| `last_error` | Why the last attempt failed (shown in the list and status bar) |
| `last_attempt_at` / `uploaded_at` | Timestamps for the audit trail |

A batch **does not stop at the first failure** — every ticked pair is attempted,
and a report at the end lists what went up and what did not, with reasons.

#### The CSV carries a stable pair identity

The backend deduplicates uploads by **content hash and ignores the filename**,
and it cannot be changed. Two pairs for the same patient, type and dates would
otherwise produce a byte-identical CSV, and the server silently drops the second
one — the PDF lands, its metadata does not.

`export_store.write_csv` therefore appends two fields: `file_name` links the row
to its PDF, while `export_id` is a random UUID stored in `meta.json` and makes
the bytes globally distinct even if another workspace or machine creates the
same filename at the same second. Pairs saved before these fields existed are
patched in place by `ensure_csv_identity` immediately before upload. If that
rewrite fails (for example, a read-only file), the pair stays pending with an
actionable error instead of sending the old CSV and risking silent loss.

The UI requires **SID** and **Patient Code**; `Type` also becomes the filename
prefix. `python -m apps.services.export_store` self-checks CSV identity,
migration and formula escaping (it is part of `ci.yml`); the required-field and
filename rules are enforced by the page itself.

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
| XML → Excel | `MA_BS_DOC_KQ` omitted when picking sheet columns (it *is* decoded and held in memory — see caveat below); only `Include` services reach the main sheet; with a study list, `ID`/`MA_LK` give way to `MA_NTG` on the matched sheets | `processing/xml_to_excel.py` |
| CSV export | Cells starting with `= + - @` are prefixed with `'` to block formula injection in Excel/Sheets | `services/export_store.py` |

### Upload File đã xử lý — route by parsed filename

`MultiUploadPage` lets the user pick any already-processed files (PDF, X-ray,
ECG, Ultrasound, CT, MRI, …) and routes each one automatically instead of
asking which pipe to use:

```text
  file path ──► FileNameParser.parse() ──► study / patient / data_type / date
                                                      │
                                    data_type in SFTP_TYPES?
                                  ┌───────────────────┴────────────────────┐
                                 yes                                      no
                                  │                                        │
                                  ▼                                        ▼
     SFTP  <SFTP_BUFFER_PATH>/<study>/<patient>/<date>/<data_type>/   HTTP  same endpoint as
                                                                       Lab PDF Upload
```

- `apps/services/parser/file_name.py` guesses study / patient / data type /
  date from the path using the same conventions as the existing OUCRU data
  pipeline; any field it gets wrong is editable in place (double-click a cell).
- `Xray/ECG/Ultrasound/CT/MRI/Others` route to SFTP, grouped into one job per
  `<study>/<patient>/<date>/<data_type>` folder; `Image`/`Metadata` route to
  the HTTP API. A file missing patient, date, or data type — or an SFTP file
  missing study — is blocked from upload until fixed in the table.
- A file that fails upload stays in the list with its error shown so it can be
  retried without re-picking every other file.

## Requirements

- **OS**: Windows (primary target for running and building)
- **Python**: 3.12 (pins last audited on 2026-08-18 with Python 3.12.13)
- **Environment**: conda or venv — both work. Everything installs via pip, so neither is smaller than the other.

Dependencies are split so a runtime machine never pulls the build toolchain:

| File | Contents | Install when |
| --- | --- | --- |
| `requirements.txt` | Runtime deps, pinned with `==` | Running from source |
| `requirements-build.txt` | The above **plus** PyInstaller and Nuitka | Building the EXE |

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

The pins were checked against the latest stable releases on 2026-08-18. Two
deliberate compatibility ceilings and one removed package matter:

- **`opencv-contrib-python==4.10.0.84`** — OpenCV 5 exists, but PaddleOCR
  3.7 pulls `paddlex[ocr-core]`, which requires this exact wheel. Do not add a
  headless OpenCV wheel alongside it: both distributions install the same `cv2`
  namespace and pip would still retain `contrib` for PaddleX.
- **`numpy==2.3.5`** — newer NumPy releases exist, but PaddleX 3.7.2 requires `numpy>=1.24,<2.4`.
- **`gdcm` was removed** — the PyPI package by that name is not the official GDCM binding and fails to import (`DLL load failed while importing _gdcmswig`), so `pydicom` reported it unavailable the whole time. For full codec coverage in one package, use `python-gdcm` instead.

An existing environment created from an older requirements file may still have
both OpenCV wheels installed; `pip install -r ...` does not remove an orphaned
package. Prefer recreating that environment. To repair it in place, uninstall
both OpenCV distributions first, then reinstall the requirements so only
`opencv-contrib-python` returns.

### DICOM compression support

The pinned set currently provides:

- JPEG baseline/extended and JPEG2000 through Pillow;
- JPEG baseline/lossless and JPEG-LS through `pylibjpeg-libjpeg`;
- RLE Lossless through pydicom's built-in Python decoder.

The optional packages below are alternative/native backends, not prerequisites
for basic JPEG2000 or RLE support. If enabled, their modules and distribution
metadata must also be added to both packaging configurations:

```text
pylibjpeg-openjpeg==2.5.0    # alternative JPEG2000 backend
pylibjpeg-rle==2.2.0         # alternative native RLE backend
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

At startup `apps/config.py` loads **every** file below, in this order, into `os.environ` without overriding what is already set — so the first file to define a key wins, and OS-level env vars beat all of them:

1. `%APPDATA%\VitalLens\.env` — per-user config written by the in-app settings dialog. Lives **outside** the app folder, so it survives replacing the EXE and does not travel when someone copies the app folder to a colleague. (`~/.config/VitalLens/.env` off Windows.)
2. `<app root>\.env` — the original location, still read for existing installs.
3. `<app root>\env` — fallback, handy on Windows where Explorer refuses to create filenames starting with a dot.
4. `<bundle root>\.env` — only present when a manual Nuitka build deliberately embeds the repo-root `.env`; it has the lowest file priority.

When `python-dotenv` is not available in a packaged build, a built-in fallback parser reads the file directly.

**App root** means:
- During development (`python main.py`): the repo root (same folder as `main.py`).
- In either packaged build: the folder containing the EXE. For Nuitka onefile,
  bundled data is extracted elsewhere and is represented separately as
  `<bundle root>`.

### Setup

**Official GitHub release artifacts contain no credential.** The release workflow
builds on a clean CI runner and checks again immediately before compilation.
`build_nuitka.bat` now refuses to run when the repo root contains `.env`. A
controlled internal build can explicitly opt in with `VITALLENS_EMBED_ENV=1`,
but its value is extractable and that EXE must never be published.

End users normally do not edit a file by hand: run the app, click **⚙ Cấu hình kết nối** at the bottom of the home page, fill in server address + token, save, restart. That writes `%APPDATA%\VitalLens\.env` (see `apps/services/user_config.py`). An `http://` address to anything but localhost is warned about and requires a second click — the bearer token would otherwise travel in cleartext.

Editing a file by hand still works, e.g. when running from source:

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
# SFTP_BUFFER_PATH=/EI_SHARE/.received/VITAL-LOG
```

Important keys:

- `API_UPLOAD_URL` — Backend endpoint for PDF + CSV upload. **Use `https://`** — the bearer token travels in this request, and plain `http://` puts it on the wire in cleartext. When empty, the upload flow falls back to a demo confirmation dialog.
- `API_BEARER_TOKEN` — Bearer token appended as `Authorization: Bearer ...`.
- `API_UPLOAD_OWNER` — Default value pre-filled in the owner-email prompt.
- `SFTP_DEMO_MODE=true` — Use local folders instead of a real SFTP server.
- `SFTP_HOST`, `SFTP_PORT`, `SFTP_PATH` — SFTP connection settings; `SFTP_PATH` is the OCR review page's PROCESSING root.
- `SFTP_BUFFER_PATH` — Destination root for **Upload File đã xử lý**'s SFTP-routed files (`Xray/ECG/Ultrasound/CT/MRI/Others`). Empty = that route is blocked with a warning.
- `UPDATE_MANIFEST_URL` — Optional URL of a small public JSON (`{"version": "0.4.0", "url": "..."}`). The home page then shows "a new version is available" with a download link. The app never downloads or installs anything itself. Unset (default) = no outbound request at all.

OS-level environment variables win over `.env` (`override=False`), which is handy
for a temporary override without editing the file.

### Secret Handling Rules

- `.env` / `env` are gitignored. Never commit real tokens. Share `.env.example` only.
- Tokens are issued **per user**, not shared — one leak revokes one account.
- The app never logs secret values. `config_debug.log` is written **only** when `VITALLENS_DEBUG_CONFIG=1` is set, and redacts secrets to a length.
- `build.bat` rejects loose secret files in the PyInstaller dist folder;
  `build_nuitka.bat` rejects repo-root `.env` by default, and CI asserts it is
  absent immediately before compilation.

`%APPDATA%\VitalLens\.env` is plaintext and therefore readable, editable, and
deletable by the same Windows account that runs VitalLens. There is no Nuitka
option or file ACL that can simultaneously let an app running as that user read
the token while making it impossible for that user to change it. DPAPI or
Windows Credential Manager would hide plaintext at rest and protect a copied
file from another account/machine, but code running as the same logged-in user
can still retrieve the secret and the user can still remove or replace it. For
a hostile-local-user threat model, use server-side identity (SSO/OAuth/device
certificate) and short-lived scoped credentials instead of a permanent secret
inside the client.

If that file is edited or deleted, VitalLens does not somehow restore/protect
it: the next restart uses the changed value, falls back to a lower-priority
config, or enters demo mode when no upload URL remains. Re-enter the settings;
if tampering may have exposed a token, revoke and reissue it server-side.

Full procedures for issuing, rotating, and revoking tokens — plus the leaked-token
incident checklist — are in **[docs/RUNBOOK-secrets.md](docs/RUNBOOK-secrets.md)**.

## Build EXE

### Prerequisites

```powershell
conda activate vitallens
```

Ensure PaddleOCR models are downloaded before building (run the app once, or let `paddlex` download them automatically to `%USERPROFILE%\.paddlex\official_models`).

### Fast local/debug build (PyInstaller onedir)

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

### Release build (Nuitka onefile)

```powershell
conda activate vitallens
build_nuitka.bat
```

Nuitka compiles to a **single** `dist_nuitka\VitalLens.exe`: no `_internal\`
folder, nothing to zip. This is what `release.yml` runs on tag and what end users
download. Budget 30–90 minutes for the first build (it compiles paddle); the
PyInstaller path above stays for fast local packaging and debugging.

Step 1 of the script runs `verify_catalog.py`, the same catalogue fingerprint
check `build_exe.spec` does for PyInstaller, so a mismatch aborts before Nuitka
even starts compiling.

If a `.env` sits at the repo root, `build_nuitka.bat` **stops by default**. For a
controlled internal-only build, `set VITALLENS_EMBED_ENV=1` opts in to embedding
and prints a `[WARN]` block. Anyone holding that EXE can extract the token; never
use the opt-in artifact as a release.

### Manual Build

```powershell
conda activate vitallens
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env.example dist\VitalLens\.env.example
```

A manual build skips the automatic secret scan — run the verification checklist
in the release runbook before shipping.

### PyInstaller debug output layout

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

Releases come from CI: push a tag `vX.Y.Z` and `release.yml` publishes
`VitalLens_v<version>.exe` + `latest.json` to GitHub Releases. Hand over the
link, not a file.

For a hand-built copy:

1. Make sure the repo root has no `.env`, run `build_nuitka.bat`, and confirm the
   log contains `[INFO] Khong co .env` **and** ends with `Build complete`.
2. Send `dist_nuitka\VitalLens.exe` — one file, no ZIP, no folder.
3. Send the user's token through a separate channel (password manager or encrypted message), never alongside the EXE.
4. The user fills in URL + token via **⚙ Cấu hình kết nối** on the home page; it writes `%APPDATA%\VitalLens\.env`, so later changes need no rebuild.

Step-by-step build, verification, packaging, and rollback procedures are in
**[docs/RUNBOOK-build-release.md](docs/RUNBOOK-build-release.md)**.

## OCR Confidence Thresholds

The X-Ray text removal uses PaddleOCR with configurable confidence filters to prevent false-positive detections (e.g. noise or artifacts mistakenly identified as text):

| Parameter | Default | Description |
| --- | --- | --- |
| `OCR_DET_SCORE_THRESHOLD` | 0.8 | Detection confidence — skip text regions detected with < 80% confidence |
| `OCR_REC_SCORE_THRESHOLD` | 0.8 | Recognition confidence — skip text recognized with < 80% confidence |
| `OCR_MIN_TEXT_LENGTH` | 2 | Skip results with fewer than 2 characters |
| `OCR_MIN_BBOX_AREA` | 100 | Skip detections smaller than 100 px² (width × height) — filters tiny noise |

These constants are defined at the top of `apps/processing/xray.py`. Increase thresholds to reduce false positives; decrease to catch more real text.

## Notes

- Both build paths bundle the pre-downloaded PaddleX models from `%USERPROFILE%\.paddlex\official_models`. They also include the `pylibjpeg-libjpeg` entry-point metadata and native `_libjpeg` module; without both, compressed DICOM can work from source but silently become unavailable in the packaged app.
- The upload flow falls back to a demo confirmation when `API_UPLOAD_URL` is empty.
- PDF redaction renders pages as rasterized images, so output files may be larger than the originals.
- The `.env` fallback parser handles both `KEY=VALUE` and `KEY="VALUE"` formats with proper quote stripping.
