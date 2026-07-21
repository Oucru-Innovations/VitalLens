# Runbook — Build & Phát hành VitalLens

Quy trình đóng gói `dist\VitalLens\` thành bản phát hành cho máy người dùng cuối.

**Nguyên tắc số 1: bản phát hành KHÔNG chứa credential.** Mỗi người dùng tự tạo
`.env` trên máy mình. Chi tiết xem [RUNBOOK-secrets.md](RUNBOOK-secrets.md).

---

## 1. Chuẩn bị máy build

| Yêu cầu | Ghi chú |
| --- | --- |
| Windows | Nền tảng build duy nhất được hỗ trợ |
| Conda env `paddleocr` | `conda activate paddleocr` trước khi chạy build |
| PaddleX models đã tải | Nằm ở `%USERPROFILE%\.paddlex\official_models` |
| `.env.example` có ở repo root | `build.bat` sẽ dừng nếu thiếu file này |

Tải model trước nếu máy build còn trắng — chạy app một lần rồi vào trang X-Ray,
hoặc để `paddlex` tự tải:

```powershell
conda activate paddleocr
python main.py
```

---

## 2. Build

```powershell
conda activate paddleocr
build.bat
```

`build.bat` chạy 4 bước và **dừng với exit code 1** nếu bước nào hỏng:

1. PyInstaller đóng gói theo `build_exe.spec` (onedir)
2. Copy `.env.example` → `dist\VitalLens\.env.example` (**template, không phải secret**)
3. Copy `icon.ico`
4. Quét secret trong `dist\` — chặn build nếu thấy `.env`, `env`, hoặc `config_debug.log`

Bước 4 là chốt chặn tự động. Nếu nó báo `[LEAK]`, **đừng zip thư mục đó** — xoá
file được liệt kê rồi build lại.

### Build thủ công (khi cần debug)

```powershell
conda activate paddleocr
python -m PyInstaller build_exe.spec --noconfirm --clean
copy .env.example dist\VitalLens\.env.example
```

Lưu ý: build thủ công **không có bước quét secret**. Phải tự chạy mục 3 bên dưới.

---

## 3. Kiểm tra trước khi phát hành

Chạy đủ 4 lệnh này trên `dist\VitalLens\`. Tất cả phải sạch:

```powershell
# 1. Không có file credential nào
Get-ChildItem dist\VitalLens\ -Force -Include .env,env,config_debug.log -Recurse

# 2. Template có mặt
Test-Path dist\VitalLens\.env.example

# 3. EXE chạy được
.\dist\VitalLens\VitalLens.exe

# 4. Không có chuỗi giống token trong thư mục dist (hex >= 32 ký tự)
Get-ChildItem dist\VitalLens\ -File -Recurse |
  Select-String -Pattern '[0-9a-f]{32,}' -List |
  Select-Object Path, LineNumber
```

Lệnh 1 phải **không trả về gì**. Lệnh 4 có thể báo false positive từ file nhị
phân của PyInstaller — chỉ cần xác nhận không có hit nào trong file text cấu hình.

### Checklist phát hành

- [ ] `build.bat` kết thúc với `[OK] No secret files found`
- [ ] 4 lệnh kiểm tra ở trên đều sạch
- [ ] EXE khởi động và mở được cả 4 trang chức năng
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
| `build.bat` báo `[ERROR] Could not find Python` | Chưa activate conda env | `conda activate paddleocr` |
| `[LEAK] dist\VitalLens\.env exists` | Còn sót từ bản build cũ | `Remove-Item dist\VitalLens\.env` rồi build lại |
| `[ERROR] .env.example not found` | Thiếu template ở repo root | Khôi phục `.env.example` từ git |
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
