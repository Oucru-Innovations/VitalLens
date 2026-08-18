# Runbook — Build & Phát hành VitalLens

Quy trình tạo một file `VitalLens_v<version>.exe` bằng Nuitka onefile và phát
hành qua GitHub Actions. PyInstaller onedir chỉ còn là đường build nhanh để debug.

**Nguyên tắc số 1: bản phát hành KHÔNG chứa credential.** Mỗi người dùng tự tạo
`.env` trên máy mình. Chi tiết xem [RUNBOOK-secrets.md](RUNBOOK-secrets.md).

---

## 1. Chuẩn bị máy build

| Yêu cầu | Ghi chú |
| --- | --- |
| Windows | Nền tảng build duy nhất được hỗ trợ |
| Python 3.12 env | Cài `requirements-build.txt`; conda hoặc `.venv` đều được |
| PaddleX models đã tải | Nằm ở `%USERPROFILE%\.paddlex\official_models` |
| `.env.example` có ở repo root | Chỉ `build.bat` (PyInstaller debug) cần copy template này |
| `database\database_medical.csv` có ở repo root | Danh mục dịch vụ cho lọc XML4; `build_exe.spec` dừng nếu thiếu **hoặc** sai vân tay SHA-256 |

Tải model trước nếu máy build còn trắng — chạy app một lần rồi vào trang X-Ray,
hoặc để `paddlex` tự tải:

```powershell
conda activate vitallens
python main.py
```

---

## 2. Build

### Build debug nhanh (PyInstaller onedir)

```powershell
conda activate vitallens
build.bat
```

`build.bat` chạy 4 bước và **dừng với exit code 1** nếu bước nào hỏng:

1. PyInstaller đóng gói theo `build_exe.spec` (onedir)
2. Copy `.env.example` → `dist\VitalLens\.env.example` (**template, không phải secret**)
3. Copy `icon.ico`; xoá `dist\VitalLens\database\` nếu còn sót từ bản build cũ
4. Quét secret trong `dist\` — chặn build nếu thấy `.env`, `env`, hoặc `config_debug.log`

Danh mục dịch vụ chỉ nằm **một** chỗ: `_internal\database\` bên trong bundle.
Bản phát hành **không** kèm CSV cạnh EXE — người dùng không có file nào để sửa,
và app cũng không đọc đường dẫn đó nữa.

Bước 1 (PyInstaller) còn đối chiếu SHA-256 của CSV với hằng số `CATALOG_SHA256`
trong `apps\services\medical_catalog.py` và **dừng build** nếu lệch, nên không
thể lỡ tay phát hành EXE ghép với danh mục khác bản đã duyệt.

### Build release (Nuitka onefile)

```powershell
conda activate vitallens
build_nuitka.bat
```

Kết quả là **một** file `dist_nuitka\VitalLens.exe`, không có `_internal\` đi
kèm. Đây là thứ `release.yml` chạy khi có tag và là thứ người dùng tải về;
`build.bat` ở trên giữ lại cho việc đóng gói nhanh và debug tại chỗ.

Script chạy 4 bước, cùng kiểu chặn exit code 1: (1) `verify_catalog.py` đối chiếu
vân tay danh mục, (2) kiểm tra model PaddleX đã tải sẵn ở
`%USERPROFILE%\.paddlex\official_models`, (3) Nuitka biên dịch, (4) quét secret
trong `dist_nuitka\`.

Nếu có `.env` ở repo root, `build_nuitka.bat` **dừng theo mặc định** trước khi
gọi Nuitka. Bản build release phải hiện `[INFO] Khong co .env`. Chỉ khi làm bản
nội bộ có chủ đích mới được chạy `set VITALLENS_EMBED_ENV=1`; script sẽ nhúng
file và in `[WARN]`, nhưng ai cầm EXE cũng moi được token nên artifact đó không
được phát hành.

Lần đầu biên dịch mất 30–90 phút vì phải dịch cả paddle. Đừng chạy hai lần build
song song vào cùng `dist_nuitka\`: Nuitka không khoá thư mục build, tiến trình
thứ hai sẽ chết với `AssertionError: ...main.build\module.<X>.c`. Muốn build lại
từ đầu thì dừng hết tiến trình rồi `Remove-Item -Recurse -Force dist_nuitka`.

### Cập nhật danh mục dịch vụ

Danh mục là dữ liệu của bản phát hành, đổi nó = ra bản mới:

```powershell
# 1. Thay database\database_medical.csv
# 2. Lấy vân tay mới
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('database/database_medical.csv').read_bytes()).hexdigest())"
# 3. Dán vào CATALOG_SHA256 trong apps\services\medical_catalog.py
# 4. Commit CẢ HAI file trong cùng một commit, rồi chạy build_nuitka.bat
```

Quên bước 3 thì build dừng ngay và in sẵn vân tay đúng để dán vào.

Bước 4 là chốt chặn tự động. Nếu nó báo `[LEAK]`, **đừng phát hành artifact đó**
— xoá file được liệt kê rồi build lại từ checkout sạch.

### Build thủ công (khi cần debug)

```powershell
conda activate vitallens
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env.example dist\VitalLens\.env.example
```

Lưu ý: build thủ công **không có bước quét secret**. Phải tự chạy mục 3 bên dưới.
Không copy danh mục ra `dist\VitalLens\database\` — bản đó không được đọc và chỉ
làm người dùng tưởng là sửa được.

---

## 2b. Phát hành tự động bằng GitHub Actions

Cách phát hành **được khuyến nghị**, và với bản Nuitka thì gần như bắt buộc.
Runner CI khởi tạo trắng; workflow kiểm tra `.env` cả lúc checkout lẫn ngay trước
build. Bản build tay cũng được script bảo vệ bằng cách từ chối `.env` mặc định,
nhưng CI cho quy trình lặp lại và truy vết được.

```powershell
# 1. Tăng __version__ trong apps\__init__.py, commit
# 2. Tag đúng số đó (workflow dừng nếu tag lệch __version__)
git tag v0.4.0
git push origin v0.4.0
```

`.github/workflows/release.yml` chạy trên `windows-latest`:

1. Đối chiếu tag với `__version__` trong `apps\__init__.py`
2. Chặn nếu `.env` / `env` / `config_debug.log` bị commit vào repo
3. Cài deps vào `.venv` (chính là priority 2 của `build_nuitka.bat`)
4. Khôi phục cache PaddleX models + cache Nuitka, rồi tải model còn thiếu bằng
   `apps.processing.xray._get_ocr()`
5. Kiểm tra lại repo root không có `.env`, ép `VITALLENS_EMBED_ENV=0`, xoá
   `CONDA_PREFIX` (runner có sẵn Miniconda — để nguyên thì `.bat` bắt nhầm python
   của conda base), rồi chạy `build_nuitka.bat`
6. Đổi tên `dist_nuitka\VitalLens.exe` thành `VitalLens_v<version>.exe`
7. `gh release create` — đính kèm **file .exe** + `latest.json`

`workflow_dispatch` chạy hết bước 6 nhưng **không** tạo Release: dùng để kiểm
tra build còn xanh mà không phát hành. Lưu ý bản build của lần chạy tay hiện
không được giữ lại — muốn tải về test trước khi tag thì phải thêm
`actions/upload-artifact`.

**Chi phí:** repo private + runner Windows = hệ số 2x phút Actions. Nuitka biên
dịch cả paddle nên lần đầu ~60–90 phút (≈120–180 phút bị tính); cache Nuitka
(key theo `requirements*.txt`) kéo các lần sau xuống ~20–30 phút. Vì thế job chỉ
chạy khi có tag. `ci.yml` (compileall + self-check + quét secret + vân tay danh
mục) chạy trên `ubuntu-latest` ở mọi PR và gần như miễn phí.

### `.env` và CI

**Không** đưa token thật vào GitHub Secrets để ghi thành `.env` lúc build: bản
Nuitka nhúng file đó vào binary, ai tải bản phát hành cũng moi ra được. Mô hình hiện tại (`.env.example` + token
cấp riêng từng người) vẫn đúng — CI chỉ làm nó khó phá hơn:

Không có cờ Nuitka hay ACL nào vừa cho app chạy dưới tài khoản user đọc token,
vừa cấm chính user đó xem/sửa/xoá. DPAPI/Credential Manager chỉ cải thiện bảo vệ
plaintext trên đĩa, không tạo ranh giới với cùng tài khoản. Xem phân tích threat
model tại [RUNBOOK-secrets.md](RUNBOOK-secrets.md#2-có-thể-cấm-user-xem-sửa-hoặc-xoá-env-không).

| Rủi ro | Chốt chặn |
| --- | --- |
| `.env` của máy dev bị NHÚNG vào EXE | Script từ chối mặc định; CI kiểm tra lại ngay trước build và ép opt-in = 0 |
| Ai đó commit `.env` vào repo | `ci.yml` + `release.yml` dừng ngay |
| Build tay có `.env` thật ở repo | Script dừng trước khi gọi Nuitka; opt-in nội bộ hiện cảnh báo lớn |
| Phát hành mang số version cũ | Tag phải khớp `__version__` |

Giá trị **không bí mật** cho cả tổ chức (ví dụ `API_UPLOAD_URL`) nếu muốn điền
sẵn thì dùng GitHub **Variables** ghi đè vào `.env.example` trong workflow —
tuyệt đối không làm thế với `API_BEARER_TOKEN`.

### Thông báo bản mới cho người dùng

`release.yml` sinh `latest.json` (`{"version", "url"}`, không chứa token). Host
file đó ở một URL công khai rồi đặt `UPDATE_MANIFEST_URL` trong `.env` của người
dùng — trang chủ sẽ hiện "đã có bản X, bấm để tải". App **chỉ báo, không tự
cài**: xem `apps/services/update_check.py` để biết lý do.

Repo đang private nên link asset của Release đòi đăng nhập, không dùng trực tiếp
làm `url` tải được; `latest.json` trỏ về trang Release (trình duyệt của người
dùng đã đăng nhập sẵn).

---

## 3. Kiểm tra trước khi phát hành

Trước khi build, xác nhận bộ pin còn giải được dependency và codec DICOM cần
dùng. `pip install --dry-run` không thay đổi môi trường:

```powershell
python -m pip install --dry-run -r requirements-build.txt
python -m pip check
python -c "from pydicom.pixels.decoders import base as b; names=['JPEGBaseline8BitDecoder','JPEGLosslessDecoder','JPEGLSLosslessDecoder','JPEG2000Decoder','RLELosslessDecoder']; assert all(getattr(b,n).is_available for n in names); print('DICOM decoders OK')"
python -m compileall -q apps main.py
python -m apps.services.export_store
```

Pin được rà gần nhất ngày 2026-08-18. `numpy==2.3.5` là trần `<2.4`, còn
`opencv-contrib-python==4.10.0.84` là wheel chính xác mà `paddlex[ocr-core]`
3.7.x yêu cầu. Không nâng riêng chúng theo số version lớn nhất trên PyPI và
không cài thêm wheel OpenCV headless cùng namespace `cv2`.

Môi trường cũ có thể còn cả hai wheel vì pip không tự gỡ package đã biến mất
khỏi requirements. Máy build release nên tạo `.venv` mới. Nếu buộc sửa env cũ:

```powershell
python -m pip uninstall opencv-python-headless opencv-contrib-python
python -m pip install -r requirements-build.txt
```

Bộ 5 lệnh dưới đây kiểm tra **bundle onedir của `build.bat`**. Bản Nuitka
onefile không có thư mục để quét — với nó, chốt chặn là script từ chối
repo-root `.env` trước build, log phải có `[INFO] Khong co .env`, rồi bước 4
kiểm tra không có `.env` / `config_debug.log` rời cạnh EXE.

Chạy đủ 5 lệnh này trên `dist\VitalLens\`. Tất cả phải sạch:

```powershell
# 1. Không có file credential nào
Get-ChildItem dist\VitalLens\ -Force -Include .env,env,config_debug.log -Recurse

# 2. Template có mặt
Test-Path dist\VitalLens\.env.example

# 3. Danh mục CHỈ nằm trong bundle (lệnh đầu phải False, lệnh sau phải True)
Test-Path dist\VitalLens\database\database_medical.csv
Test-Path dist\VitalLens\_internal\database\database_medical.csv

# 3b. Vân tay bản đóng gói khớp hằng số trong source
(Get-FileHash dist\VitalLens\_internal\database\database_medical.csv -Algorithm SHA256).Hash
Select-String -Path apps\services\medical_catalog.py -Pattern 'CATALOG_SHA256'

# 4. EXE chạy được
.\dist\VitalLens\VitalLens.exe

# 5. Không có chuỗi giống token trong thư mục dist (hex >= 32 ký tự)
Get-ChildItem dist\VitalLens\ -File -Recurse |
  Select-String -Pattern '[0-9a-f]{32,}' -List |
  Select-Object Path, LineNumber
```

Lệnh 1 phải **không trả về gì**. Lệnh 5 có thể báo false positive từ file nhị
phân của PyInstaller — chỉ cần xác nhận không có hit nào trong file text cấu hình.

### Checklist phát hành

- [ ] Script build kết thúc sạch (`[OK] No secret files found` với `build.bat`;
      với `build_nuitka.bat` phải có **cả** `[INFO] Khong co .env` và
      `Build complete`)
- [ ] Resolver, `pip check` và kiểm tra 5 decoder DICOM ở trên đều xanh
- [ ] 5 lệnh kiểm tra ở trên đều sạch (bản onedir)
- [ ] EXE khởi động và mở được cả 4 trang chức năng — với onefile nhớ chạy thử
      từ **thư mục khác** repo, để chắc nó không đọc nhầm file trong repo
- [ ] Trang XML → Excel chạy thử 1 file: ra 2 sheet, cột `Name_Method` có dữ liệu
- [ ] Trên profile test sạch (không có `%APPDATA%\VitalLens\.env`), trang Upload
      PDF hiện dialog demo — máy dev có config user thì không dùng để kiểm mục này
- [ ] Trang Upload PDF: lưu 2 cặp cùng bệnh nhân/type/ngày → hai file CSV phải
      **khác nội dung** nhờ UUID `export_id`; `file_name` phải khớp đúng PDF
- [ ] Đã tăng `__version__` và số đó có trong tên file phát hành

---

## 4. Đóng gói & giao cho người dùng

Phát hành qua GitHub Actions (mục 2b) đã tự làm bước này. Bản Nuitka là
**onefile**: không có thư mục nào để nén, chỉ đổi tên cho biết version:

```powershell
$version = "0.4.0"   # phải khớp __version__ trong apps\__init__.py
Move-Item dist_nuitka\VitalLens.exe "VitalLens_v$version.exe"
```

Đặt file **ngoài** `dist_nuitka\` để lần build sau không nuốt nó vào gói.

Tên file theo semver (`VitalLens_v0.4.0.exe`) chứ không theo lối cũ
(`VitalLens_V12.zip`): `services/update_check.py` so sánh version bằng cách tách
số theo dấu chấm, `V13` không so được với `V12`.

(Bản PyInstaller onedir vẫn nén bằng `Compress-Archive -Path dist\VitalLens\*`
nếu bạn cần dùng lại đường build cũ để debug.)

Gửi kèm hướng dẫn cho người dùng:

> **Cài lần đầu**
> 1. Chép `VitalLens_v0.4.0.exe` vào thư mục bất kỳ (ví dụ `C:\VitalLens\`)
> 2. Chạy file đó. **Lần chạy đầu tiên mất vài phút** — app tự bung ~1.5 GB vào
>    thư mục cache theo version; các lần sau mở nhanh.
> 3. Cuối trang chủ bấm **⚙ Cấu hình kết nối**, điền địa chỉ server + token
>    được cấp riêng, bấm **Lưu**
> 4. Khởi động lại app
>
> **Cập nhật bản mới:** chép file .exe mới vào, chạy nó. Không phải làm lại bước
> 3 — cấu hình nằm ở `%APPDATA%\VitalLens\`, ngoài thư mục app.
>
> Chưa cấu hình thì chức năng Upload chạy ở chế độ demo (không gửi lên server).

---

## 5. Rollback

Bản build là một file .exe độc lập, không có installer và không đụng registry:

1. Người dùng xoá (hoặc đổi tên) file .exe bản mới
2. Chạy lại file .exe bản cũ — mỗi version bung ra một thư mục cache riêng nên
   hai bản không giẫm lên nhau
3. Không phải làm gì với cấu hình — `%APPDATA%\VitalLens\.env` nằm ngoài thư
   mục app nên không bị đụng tới. (Người dùng cài từ bản cũ có thể còn `.env`
   cạnh EXE; file đó vẫn được đọc, nhưng nhớ chép sang trước khi xoá thư mục.)

Dữ liệu đã xuất (`output_pdf\pending\`, `output_pdf\uploaded\`) **không** nằm
trong thư mục app, nên rollback không làm mất cặp PDF+CSV nào.

---

## 6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `build.bat` báo `[ERROR] Could not find Python` | Chưa activate conda env | `conda activate vitallens` |
| `[LEAK] dist\VitalLens\.env exists` | Còn sót từ bản build cũ | `Remove-Item dist\VitalLens\.env` rồi build lại |
| `[ERROR] .env.example not found` | Thiếu template ở repo root | Khôi phục `.env.example` từ git |
| `[ERROR] database\database_medical.csv not found` | Thiếu danh mục ở repo root | Khôi phục `database\database_medical.csv` từ git rồi build lại |
| `[ERROR] Catalogue fingerprint mismatch` lúc build | CSV đã đổi nhưng chưa cập nhật `CATALOG_SHA256` | Dán vân tay `actual` mà build in ra vào `CATALOG_SHA256`, commit cùng file CSV |
| Máy người dùng báo `vân tay SHA-256 không khớp` | Danh mục trong `_internal\` bị sửa hoặc hỏng | Cài lại bản phát hành gốc. Đây là chốt chặn cố ý — **không** hướng dẫn người dùng tự sửa hằng số |
| Trang XML → Excel báo `Không nạp được danh mục dịch vụ` | Danh mục bị xoá khỏi bundle | Message nêu rõ vị trí + lý do. Cài lại bản phát hành |
| Tất cả bản ghi rơi vào sheet `XML4_ChuaPhanLoai` | `MA_DICH_VU` trong XML không cùng hệ mã với `ID_SERVICE` | Đối chiếu vài mã trong XML với cột `ID_SERVICE`; sai hệ mã thì phải đổi danh mục, không phải đổi app |
| EXE khởi động rồi tắt ngay | Thiếu PaddleX models | Chạy app từ source một lần để tải models, build lại |
| EXE báo lỗi SSL khi khởi động | Certificate store Windows hỏng | Đã có `patch_windows_ssl_cert_store()` xử lý; nếu vẫn lỗi, kiểm tra antivirus/proxy công ty |
| Upload luôn ra dialog demo | `.env` thiếu hoặc `API_UPLOAD_URL` rỗng | Kiểm tra `%APPDATA%\VitalLens\.env` trước, sau đó mới tới `.env` cạnh EXE |
| DICOM nén chạy từ source nhưng lỗi trong EXE | Thiếu plugin/entry-point metadata khi đóng gói | Xác nhận build config còn `pydicom...pylibjpeg`, `_libjpeg` và metadata `pylibjpeg-libjpeg`; build lại |

### Chẩn đoán việc nạp `.env`

Mặc định app **không** ghi file log cấu hình. Khi cần điều tra, bật tường minh:

```powershell
$env:VITALLENS_DEBUG_CONFIG = "1"
.\dist_nuitka\VitalLens.exe
notepad dist_nuitka\config_debug.log
```

File này chỉ ghi tên khoá đọc được và **redact giá trị bí mật** (token chỉ hiện
độ dài). Xoá file sau khi điều tra xong.
