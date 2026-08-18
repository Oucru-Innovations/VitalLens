# Runbook — Quản lý & Xoay Token

Quy trình cấp, xoay và thu hồi credential cho VitalLens.

---

## 1. Nguyên tắc

| Quy tắc | Lý do |
| --- | --- |
| Bản phát hành chính thức không chứa credential | Một EXE có token vẫn trích xuất được; onefile không phải kho bí mật |
| Mỗi máy người dùng tự có `.env` riêng | Thu hồi được một máy mà không ảnh hưởng máy khác |
| Không log giá trị secret | Log hay bị đính vào báo cáo lỗi và gửi đi lung tung |
| Endpoint phải là `https://` | `http://` gửi bearer token dạng cleartext trên đường truyền |

GitHub Actions build từ checkout sạch, không có `.env`, nên file
`VitalLens_v<version>.exe` chính thức không mang token. Không đưa token vào
GitHub Secrets chỉ để sinh `.env` trong job build: Nuitka sẽ nhúng file đó vào
binary và người tải EXE vẫn có thể lấy ra.

---

## 2. Có thể cấm user xem, sửa hoặc xoá `.env` không?

**Không thể bảo đảm điều đó khi VitalLens và người dùng chạy dưới cùng một tài
khoản Windows.** Nếu tiến trình của user có quyền đọc token để gửi request, chủ
tài khoản cũng có thể chạy code với cùng quyền. Cờ read-only, file ẩn hoặc ACL
chỉ giảm sửa nhầm/ngăn tài khoản khác; chủ sở hữu hoặc admin vẫn đổi quyền, xoá
file hoặc xoá cả thư mục cha.

| Cách | Bảo vệ được gì | Giới hạn còn lại |
| --- | --- | --- |
| Read-only / hidden / ACL | Sửa nhầm; tài khoản Windows khác | Chủ tài khoản/admin đổi quyền hoặc xoá |
| Nhúng `.env` vào EXE | Không còn file `.env` rời | Secret vẫn trích xuất được; user override bằng config ưu tiên cao hơn; xoay token phải build lại |
| DPAPI (`CryptProtectData`) | Không lộ plaintext trên đĩa; bản sao sang máy/tài khoản khác thường không giải được | Code cùng tài khoản vẫn giải được; user vẫn xoá/ghi đè blob |
| Windows Credential Manager | Lưu credential mã hoá, tránh file plaintext | User quản lý/xoá được; tiến trình cùng user vẫn lấy được theo API |

Nếu chỉ cần chống đọc trộm file offline hoặc vô tình mở Notepad, DPAPI/Credential
Manager là nâng cấp hợp lý. Nếu phải chống **chính người dùng máy**, không đặt
long-lived shared secret trong client: dùng SSO/OAuth device flow, chứng thư theo
máy/Windows Hello, token ngắn hạn + scope tối thiểu, audit và revoke ở backend.
Client cục bộ không tự tạo được ranh giới bảo mật với chủ máy.

Quyết định hiện tại: token riêng từng user, lưu plaintext trong profile và không
coi obfuscation/Nuitka là mã hoá. Xem `apps/services/user_config.py`.

Nếu user sửa/xoá file, app không thể chặn hay tự khôi phục bí mật: sau khi khởi
động lại nó dùng giá trị đã sửa, rơi xuống config ưu tiên thấp hơn, hoặc về demo
khi không còn `API_UPLOAD_URL`. Nhập lại qua dialog; nếu có khả năng token đã bị
lộ thì revoke/cấp lại ở backend, không chỉ tạo lại file cũ.

Tham khảo chính thức của Microsoft: [DPAPI `CryptProtectData`](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata),
[Credential Locker](https://learn.microsoft.com/en-us/windows/apps/develop/security/credential-locker)
và [Windows access control](https://learn.microsoft.com/en-us/windows/security/identity-protection/access-control/access-control).

---

## 3. Secret nằm ở đâu

| Vị trí | Nội dung | Trong git? |
| --- | --- | --- |
| `%APPDATA%\VitalLens\.env` | **Nơi khuyến nghị** — token thật của từng user | Không (ngoài repo) |
| `<app root>\.env` | Cách cũ, vẫn đọc được | Không (`.gitignore`) |
| `<app root>\env` | Fallback cho Windows Explorer | Không (`.gitignore`) |
| `.env` trong bundle Nuitka | Chỉ có khi build nội bộ opt-in bằng `VITALLENS_EMBED_ENV=1`; ưu tiên thấp nhất | Không được phép ở release chính thức |
| `.env.example` | Template, chỉ có placeholder | **Có** — an toàn; onefile không ship file rời này |
| `config_debug.log` | Chẩn đoán, đã redact, chỉ ghi khi bật cờ | Không (`.gitignore`) |

**App root** = thư mục chứa `main.py` khi chạy từ source, hoặc thư mục chứa
`VitalLens.exe` khi chạy bản đóng gói.

Các file được nạp theo đúng thứ tự trên, sau cùng mới tới `.env` nhúng,
`override=False` nên **giá trị đặt trước thắng** — và biến môi trường cấp OS
thắng tất cả.

Vì sao ưu tiên `%APPDATA%`: bản phát hành hiện là một EXE thay thế theo version;
config ngoài thư mục app tồn tại qua cập nhật. Người dùng cũng hay copy file app
cho đồng nghiệp — config đặt cạnh EXE sẽ đi theo. Xem
`apps/services/user_config.py`.

---

## 4. Cấp cho người dùng mới

1. Xin backend cấp token riêng cho người/máy đó (đừng dùng chung token)
2. Gửi link GitHub Release tới `VitalLens_v<version>.exe`
3. Gửi token qua **kênh khác** (password manager, tin nhắn mã hoá) — không gửi
   chung email với link/file phát hành
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
   "CHƯA CÓ BACKEND ENDPOINT", kiểm tra `%APPDATA%\VitalLens\.env` trước; file
   cạnh EXE là đường tương thích cũ và có ưu tiên thấp hơn.

---

## 5. Xoay token định kỳ

Nên xoay mỗi 90 ngày, hoặc ngay khi có người rời dự án.

1. Backend cấp token mới, **giữ token cũ còn sống** trong thời gian chuyển tiếp
2. Gửi token mới cho từng người dùng
3. Người dùng mở dialog Cấu hình, thay token, lưu và khởi động lại — **không cần build lại**
4. Xác nhận mọi máy đã upload được bằng token mới
5. Backend thu hồi token cũ
6. Ghi lại ngày xoay vào log vận hành của nhóm

---

## 6. Ứng phó khi lộ token

Chạy theo đúng thứ tự. Bước 1 là gấp nhất.

### Bước 1 — Thu hồi ngay (trong vòng vài phút)

Vào backend `vital-ei.oucru.org`, vô hiệu hoá token bị lộ. Làm việc này **trước**
mọi bước dọn dẹp — chừng nào token còn sống thì việc xoá file chỉ là hình thức.

### Bước 2 — Xác định phạm vi

Trả lời 3 câu:

- Token lộ qua đường nào? (EXE/ZIP cũ / `.env` / log / commit / ảnh chụp màn hình)
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

Xoá/thu hồi mọi artifact đã phát hành có chứa secret và yêu cầu người nhận bỏ
bản họ đang có. Việc này không thay thế bước thu hồi token ở backend.

### Bước 4 — Kiểm tra lịch sử git

`.gitignore` đã chặn `.env` và `*.log`, nhưng vẫn nên xác nhận:

```powershell
git log --all --full-history -- .env env config_debug.log
git grep -I -n "API_BEARER_TOKEN=" $(git rev-list --all) 2>$null | Select-Object -First 20
```

Nếu có kết quả, secret đã nằm trong lịch sử git → phải viết lại history
(`git filter-repo`) **và** coi như mọi clone đều đã lộ.

### Bước 5 — Cấp lại

Làm theo mục 4 cho từng người dùng với token mới.

### Bước 6 — Chặn tái diễn

Xác nhận các chốt chặn còn nguyên:

- [ ] `release.yml` build từ checkout sạch và chặn file secret bị track
- [ ] `build_nuitka.bat` vẫn từ chối repo-root `.env` theo mặc định; log release có `[INFO] Khong co .env`
- [ ] `build.bat` (đường debug PyInstaller) chỉ copy `.env.example`, không copy `.env`
- [ ] `apps/config.py` không ghi giá trị secret ra log
- [ ] `config_debug.log` chỉ sinh ra khi bật `VITALLENS_DEBUG_CONFIG`
- [ ] `.gitignore` còn chặn `.env`, `.env.*`, `/env`, `*.log`

---

## 7. Sự cố đã xảy ra

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
