# Runbook — Quản lý & Xoay Token

Quy trình cấp, xoay và thu hồi credential cho VitalLens.

---

## 1. Nguyên tắc

| Quy tắc | Lý do |
| --- | --- |
| Bản phát hành **không bao giờ** chứa `.env` | Một ZIP lộ token là mọi người nhận ZIP đều có credential production |
| Mỗi máy người dùng tự có `.env` riêng | Thu hồi được một máy mà không ảnh hưởng máy khác |
| Không log giá trị secret | Log hay bị đính vào báo cáo lỗi và gửi đi lung tung |
| Endpoint phải là `https://` | `http://` gửi bearer token dạng cleartext trên đường truyền |

---

## 2. Secret nằm ở đâu

| Vị trí | Nội dung | Trong git? |
| --- | --- | --- |
| `%APPDATA%\VitalLens\.env` | **Nơi khuyến nghị** — token thật của từng user | Không (ngoài repo) |
| `<app root>\.env` | Cách cũ, vẫn đọc được | Không (`.gitignore`) |
| `<app root>\env` | Fallback cho Windows Explorer | Không (`.gitignore`) |
| `.env.example` | Template, chỉ có placeholder | **Có** — an toàn |
| `config_debug.log` | Chẩn đoán, đã redact, chỉ ghi khi bật cờ | Không (`.gitignore`) |

**App root** = thư mục chứa `main.py` khi chạy từ source, hoặc thư mục chứa
`VitalLens.exe` khi chạy bản đóng gói.

Cả ba file đều được nạp theo đúng thứ tự trên, `override=False` nên **file nào
đặt khoá trước thì thắng** — và biến môi trường cấp OS thắng tất cả (tiện khi
cần override tạm mà không sửa file).

Vì sao ưu tiên `%APPDATA%`: bản phát hành là ZIP giải nén đè, config nằm trong
thư mục app thì mỗi lần cập nhật phải chép tay sang. Và người dùng hay copy
nguyên thư mục app cho đồng nghiệp — token đi theo. Xem
`apps/services/user_config.py`.

---

## 3. Cấp cho người dùng mới

1. Xin backend cấp token riêng cho người/máy đó (đừng dùng chung token)
2. Gửi bản build ZIP qua kênh thường
3. Gửi token qua **kênh khác** (password manager, tin nhắn mã hoá) — không gửi
   chung email với file ZIP
4. Hướng dẫn người dùng — **không cần sửa file nào**:

> Mở `VitalLens.exe` → ở cuối trang chủ bấm **⚙ Cấu hình kết nối** → điền 3 ô
> → **Lưu** → khởi động lại app.

App ghi vào `%APPDATA%\VitalLens\.env`, không đụng tới thư mục cài đặt.

| Ô | Giá trị |
| --- | --- |
| Địa chỉ server | `https://vital-ei.oucru.org/api/v2/file/upload` |
| Token | token được cấp riêng cho người đó |
| Email mặc định | `ten.ban@oucru.org` |

Địa chỉ **phải là `https://`**. Gõ `http://` thì dialog cảnh báo và bắt bấm Lưu
lần thứ hai — cố ý, để không ai lỡ tay gửi token qua kênh không mã hoá.

<details>
<summary>Cách cũ (sửa file tay) — vẫn dùng được</summary>

```powershell
cd C:\VitalLens
copy .env.example .env
notepad .env
```

```env
API_UPLOAD_URL=https://vital-ei.oucru.org/api/v2/file/upload
API_BEARER_TOKEN=<token được cấp riêng>
API_UPLOAD_OWNER=ten.ban@oucru.org
```

Nhược điểm: mất khi giải nén đè bản mới, và đi theo nếu ai đó copy cả thư mục.
</details>

5. Xác nhận hoạt động: mở app → trang Upload PDF → bấm Upload. Nếu hiện dialog
   "CHƯA CÓ BACKEND ENDPOINT" nghĩa là `.env` chưa được đọc — kiểm tra file có
   nằm đúng cạnh `VitalLens.exe` không.

---

## 4. Xoay token định kỳ

Nên xoay mỗi 90 ngày, hoặc ngay khi có người rời dự án.

1. Backend cấp token mới, **giữ token cũ còn sống** trong thời gian chuyển tiếp
2. Gửi token mới cho từng người dùng
3. Người dùng sửa `API_BEARER_TOKEN` trong `.env` — **không cần build lại**
4. Xác nhận mọi máy đã upload được bằng token mới
5. Backend thu hồi token cũ
6. Ghi lại ngày xoay vào log vận hành của nhóm

---

## 5. Ứng phó khi lộ token

Chạy theo đúng thứ tự. Bước 1 là gấp nhất.

### Bước 1 — Thu hồi ngay (trong vòng vài phút)

Vào backend `vital-ei.oucru.org`, vô hiệu hoá token bị lộ. Làm việc này **trước**
mọi bước dọn dẹp — chừng nào token còn sống thì việc xoá file chỉ là hình thức.

### Bước 2 — Xác định phạm vi

Trả lời 3 câu:

- Token lộ qua đường nào? (ZIP phát hành / log / commit / ảnh chụp màn hình)
- Đã gửi cho những ai, từ khi nào?
- Backend có log truy cập để rà hoạt động bất thường không?

### Bước 3 — Dọn artifact tại chỗ

```powershell
# Bản build còn chứa credential
Remove-Item dist\VitalLens\.env -Force -ErrorAction SilentlyContinue
Remove-Item dist\VitalLens\config_debug.log -Force -ErrorAction SilentlyContinue
Remove-Item config_debug.log -Force -ErrorAction SilentlyContinue

# ZIP đã đóng gói kèm secret
Get-ChildItem -Recurse -Filter *.zip | Where-Object { $_.FullName -like '*dist*' }
```

Xoá luôn các bản ZIP đã phát hành mà bạn còn giữ, và yêu cầu người nhận xoá bản
họ đang có.

### Bước 4 — Kiểm tra lịch sử git

`.gitignore` đã chặn `.env` và `*.log`, nhưng vẫn nên xác nhận:

```powershell
git log --all --full-history -- .env env config_debug.log
git grep -I -n "API_BEARER_TOKEN=" $(git rev-list --all) 2>$null | Select-Object -First 20
```

Nếu có kết quả, secret đã nằm trong lịch sử git → phải viết lại history
(`git filter-repo`) **và** coi như mọi clone đều đã lộ.

### Bước 5 — Cấp lại

Làm theo mục 3 cho từng người dùng với token mới.

### Bước 6 — Chặn tái diễn

Xác nhận các chốt chặn còn nguyên:

- [ ] `build.bat` bước 4 quét secret và chặn được build
- [ ] `build.bat` chỉ copy `.env.example`, không copy `.env`
- [ ] `apps/config.py` không ghi giá trị secret ra log
- [ ] `config_debug.log` chỉ sinh ra khi bật `VITALLENS_DEBUG_CONFIG`
- [ ] `.gitignore` còn chặn `.env`, `.env.*`, `/env`, `*.log`

---

## 6. Sự cố đã xảy ra

### 2026-07 — Token lộ trong bản phát hành V9

**Phát hiện:** review toàn dự án.

**Nguyên nhân kép:**

1. `build.bat` copy thẳng `.env` của máy build vào `dist\VitalLens\` — token lọt
   vào `Vitallens V9.zip` đã phát hành
2. `apps/config.py` dump nguyên văn từng dòng `.env` (gồm cả token) vào
   `config_debug.log`, chạy vô điều kiện mỗi lần khởi động

**Phạm vi:** token 64 ký tự nằm ở `dist\VitalLens\.env`,
`dist\VitalLens\config_debug.log`, `config_debug.log` ở repo root, và bên trong
ZIP phát hành. Không lọt vào git.

**Đã sửa:**

- `build.bat` chuyển sang copy `.env.example`, thêm bước quét secret chặn build
- `apps/config.py` bỏ dump raw, redact secret, và chỉ ghi log khi bật cờ

**Còn phải làm:** thu hồi token cũ, cấp token riêng theo người dùng, chuyển
endpoint sang `https://`.
