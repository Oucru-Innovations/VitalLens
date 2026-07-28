# Runbook — Build & Phát hành VitalLens

Quy trình đóng gói `dist\VitalLens\` thành bản phát hành cho máy người dùng cuối.

**Nguyên tắc số 1: bản phát hành KHÔNG chứa credential.** Mỗi người dùng tự tạo
`.env` trên máy mình. Chi tiết xem [RUNBOOK-secrets.md](RUNBOOK-secrets.md).

---

## 1. Chuẩn bị máy build

| Yêu cầu | Ghi chú |
| --- | --- |
| Windows | Nền tảng build duy nhất được hỗ trợ |
| Conda env `vitallens` | `conda activate vitallens` trước khi chạy build |
| PaddleX models đã tải | Nằm ở `%USERPROFILE%\.paddlex\official_models` |
| `.env.example` có ở repo root | `build.bat` sẽ dừng nếu thiếu file này |
| `database\database_medical.csv` có ở repo root | Danh mục dịch vụ cho lọc XML4; `build_exe.spec` dừng nếu thiếu **hoặc** sai vân tay SHA-256 |

Tải model trước nếu máy build còn trắng — chạy app một lần rồi vào trang X-Ray,
hoặc để `paddlex` tự tải:

```powershell
conda activate vitallens
python main.py
```

---

## 2. Build

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

### Cập nhật danh mục dịch vụ

Danh mục là dữ liệu của bản phát hành, đổi nó = ra bản mới:

```powershell
# 1. Thay database\database_medical.csv
# 2. Lấy vân tay mới
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('database/database_medical.csv').read_bytes()).hexdigest())"
# 3. Dán vào CATALOG_SHA256 trong apps\services\medical_catalog.py
# 4. Commit CẢ HAI file trong cùng một commit, rồi build.bat
```

Quên bước 3 thì build dừng ngay và in sẵn vân tay đúng để dán vào.

Bước 4 là chốt chặn tự động. Nếu nó báo `[LEAK]`, **đừng zip thư mục đó** — xoá
file được liệt kê rồi build lại.

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

## 3. Kiểm tra trước khi phát hành

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

- [ ] `build.bat` kết thúc với `[OK] No secret files found`
- [ ] 5 lệnh kiểm tra ở trên đều sạch
- [ ] EXE khởi động và mở được cả 4 trang chức năng
- [ ] Trang XML → Excel chạy thử 1 file: ra 2 sheet, cột `Name_Method` có dữ liệu
- [ ] Trang Upload PDF hiện dialog demo (do chưa có `.env` → đúng như mong đợi)
- [ ] Đã tăng số version trong tên file ZIP

---

## 4. Đóng gói & giao cho người dùng

```powershell
$version = "V10"
Compress-Archive -Path dist\VitalLens\* -DestinationPath "VitalLens_$version.zip" -Force
```

Đặt ZIP **ngoài** `dist\` để lần build sau không nuốt nó vào gói (bản `V9` đã
dính lỗi này — ZIP nằm trong `dist\VitalLens\`).

Gửi kèm hướng dẫn cho người dùng:

> 1. Giải nén vào thư mục bất kỳ (ví dụ `C:\VitalLens\`)
> 2. Đổi tên `.env.example` thành `.env`
> 3. Mở `.env` bằng Notepad, điền `API_UPLOAD_URL` và `API_BEARER_TOKEN` được cấp riêng
> 4. Chạy `VitalLens.exe`
>
> Không có `.env`, chức năng Upload sẽ chạy ở chế độ demo (không gửi lên server).

---

## 5. Rollback

Bản build là onedir độc lập, không có installer và không đụng registry:

1. Người dùng xoá thư mục bản mới
2. Giải nén lại ZIP bản cũ
3. Giữ nguyên `.env` — file này thuộc về người dùng, không nằm trong ZIP

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
| Upload luôn ra dialog demo | `.env` thiếu hoặc `API_UPLOAD_URL` rỗng | Kiểm tra `.env` nằm **cùng thư mục** với `VitalLens.exe` |

### Chẩn đoán việc nạp `.env`

Mặc định app **không** ghi file log cấu hình. Khi cần điều tra, bật tường minh:

```powershell
$env:VITALLENS_DEBUG_CONFIG = "1"
.\dist\VitalLens\VitalLens.exe
notepad dist\VitalLens\config_debug.log
```

File này chỉ ghi tên khoá đọc được và **redact giá trị bí mật** (token chỉ hiện
độ dài). Xoá file sau khi điều tra xong.
