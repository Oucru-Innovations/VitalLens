@echo off
setlocal
cd /d "%~dp0"

:: ====================================================================
:: VitalLens - Nuitka build (onefile: MOT file VitalLens.exe duy nhat)
:: Usage: conda activate vitallens && build_nuitka.bat
::
:: Khac biet so voi build.bat (PyInstaller):
::   - Ket qua la 1 file .exe, khong co thu muc _internal\ di kem.
::   - Neu ton tai .env o repo root, file do duoc NHUNG vao binary.
::     => Token nam trong file phat hanh. Doc muc [WARN] ben duoi.
:: ====================================================================

set "PYTHON_EXE="
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
if not defined PYTHON_EXE if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"
if not defined PYTHON_EXE (
    echo [ERROR] Could not find Python. Run: conda activate vitallens
    exit /b 1
)
echo [INFO] Python: %PYTHON_EXE%

"%PYTHON_EXE%" -c "import nuitka" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Nuitka chua cai. Chay: pip install -r requirements-build.txt
    exit /b 1
)

:: Lay version tu apps/__init__.py de khong phai nho cap nhat o hai noi.
:: Version di vao ca metadata cua EXE lan duong dan cache giai nen onefile:
:: doi version => thu muc cache moi => nang cap khong dung ban cu.
:: Qua file tam thay vi `for /f`: cmd nuot mat cap nhay khi dong lenh vua mo
:: vua dong bang dau nhay, lam hong duong dan python co khoang trang.
"%PYTHON_EXE%" -c "import apps;print(apps.__version__)" > "%TEMP%\vitallens_ver.txt"
set /p APP_VERSION=<"%TEMP%\vitallens_ver.txt"
del "%TEMP%\vitallens_ver.txt" >nul 2>nul
if not defined APP_VERSION (
    echo [ERROR] Khong doc duoc apps.__version__
    exit /b 1
)
echo [INFO] Version: %APP_VERSION%

:: --- Step 1: Cong danh muc dich vu (giong build_exe.spec) ---
echo.
echo [1/4] Verifying medical catalogue...
"%PYTHON_EXE%" verify_catalog.py
if errorlevel 1 exit /b 1

:: --- Step 2: Model OCR phai duoc tai truoc (chay app 1 lan la co) ---
echo.
echo [2/4] Checking pre-downloaded PaddleX models...
set "MODELS=%USERPROFILE%\.paddlex\official_models"
if not exist "%MODELS%\PP-OCRv5_mobile_det" (
    echo [ERROR] Thieu %MODELS%\PP-OCRv5_mobile_det
    echo [ERROR] Chay `python main.py` va xu ly thu 1 anh X-Ray de tai model.
    exit /b 1
)
if not exist "%MODELS%\en_PP-OCRv5_mobile_rec" (
    echo [ERROR] Thieu %MODELS%\en_PP-OCRv5_mobile_rec
    exit /b 1
)
echo [OK] Models found.

:: --- .env: nhung vao binary neu co (KHONG dat trong () de %VAR% no ra ngay) ---
set "ENV_OPT="
if exist ".env" set "ENV_OPT=--include-data-files=.env=.env"
if exist ".env" echo.
if exist ".env" echo [WARN] NHUNG file: %~dp0.env
if exist ".env" echo [WARN] .env se duoc NHUNG vao VitalLens.exe.
if exist ".env" echo [WARN] Bearer token nam trong binary phat hanh: ai co file exe
if exist ".env" echo [WARN] deu rut duoc token ra. Chi lam vay khi token dung chung
if exist ".env" echo [WARN] cho ca nhom va ban chap nhan phai build lai khi doi token.
if exist ".env" echo [WARN] Khong muon nhung: doi ten .env roi build lai.
if not exist ".env" echo [INFO] Khong co .env - build sach, nguoi dung tu nhap qua dialog Cai dat.

:: --- Step 3: Nuitka ---
:: Vi sao chon tung flag:
::   --onefile-tempdir-spec : mac dinh onefile giai nen ~1.5GB vao %TEMP% MOI LAN
::       chay roi xoa di => khoi dong cham hang phut. Tro toi mot thu muc co dinh
::       theo version => chi lan chay dau tien moi cham.
::   --deployment           : tat cac self-check debug cua Nuitka luc chay.
::   --lto=no               : LTO tren binary co paddle lam buoc link lau gap boi
::       ma khong giup gi cho phan native cua paddle (da duoc bien dich san).
::   --include-package=paddle/paddleocr/paddlex : ba goi nay import dong rat nhieu,
::       Nuitka khong tu lan het duoc. Tuong duong collect_all() trong spec.
::   KHONG dung --python-flag=no_asserts: paddle dung assert de kiem tra tham so,
::       app xu ly du lieu y te thi khong bo kiem tra de doi vai MB.
::   --include-module=pydicom.pixels.decoders.* : pydicom nap plugin giai nen
::       pixel bang importlib theo ten -> Nuitka khong tu lan toi. Chi liet ke
::       plugin THUC SU dung duoc: pillow (JPEG baseline/extended) va rle. Ten
::       module khong ton tai lam Nuitka FAIL ca build (khac PyInstaller chi
::       canh bao) - pydicom 3.x da doi pydicom.encoders.* thanh pydicom.pixels.*
echo.
echo [3/4] Running Nuitka (chuan bi doi 30-90 phut cho lan build dau)...
"%PYTHON_EXE%" -m nuitka main.py ^
  --standalone ^
  --onefile ^
  --output-dir=dist_nuitka ^
  --output-filename=VitalLens.exe ^
  --remove-output ^
  --assume-yes-for-downloads ^
  --deployment ^
  --lto=no ^
  --jobs=%NUMBER_OF_PROCESSORS% ^
  --enable-plugin=tk-inter ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=icon.ico ^
  --company-name=OUCRU ^
  --product-name=VitalLens ^
  --file-description="VitalLens - medical data processing" ^
  --file-version=%APP_VERSION% ^
  --product-version=%APP_VERSION% ^
  "--onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}" ^
  --include-data-dir=database=database ^
  --include-data-files=icon.ico=icon.ico ^
  "--include-data-dir=%MODELS%\PP-OCRv5_mobile_det=paddlex_models\PP-OCRv5_mobile_det" ^
  "--include-data-dir=%MODELS%\en_PP-OCRv5_mobile_rec=paddlex_models\en_PP-OCRv5_mobile_rec" ^
  %ENV_OPT% ^
  --include-package=paddle ^
  --include-package=paddleocr ^
  --include-package=paddlex ^
  --include-package=google.protobuf ^
  --include-package-data=paddle ^
  --include-package-data=paddleocr ^
  --include-package-data=paddlex ^
  --include-package-data=pypdfium2 ^
  --include-package-data=pypdfium2_raw ^
  --include-package-data=pydicom ^
  --include-package-data=certifi ^
  --include-module=pydicom.pixels.decoders.pillow ^
  --include-module=pydicom.pixels.decoders.rle ^
  --nofollow-import-to=matplotlib ^
  --nofollow-import-to=scipy ^
  --nofollow-import-to=IPython ^
  --nofollow-import-to=notebook ^
  --nofollow-import-to=pytest ^
  --nofollow-import-to=tkinter.test

if errorlevel 1 (
    echo.
    echo [ERROR] Nuitka build failed.
    echo [ERROR] Loi hay gap nhat la thieu module cua paddle luc chay: build lai
    echo [ERROR] voi --windows-console-mode=force de doc traceback, roi them
    echo [ERROR] --include-module=^<ten module^> vao danh sach tren.
    exit /b 1
)

:: --- Step 4: Quet secret (chi con dung cho file ROI canh exe) ---
echo.
echo [4/4] Scanning output...
set "OUT=dist_nuitka\VitalLens.exe"
if not exist "%OUT%" (
    echo [ERROR] Khong thay %OUT%
    exit /b 1
)
if exist "dist_nuitka\.env" (
    echo [LEAK] dist_nuitka\.env ton tai - xoa truoc khi phat hanh.
    exit /b 1
)
if exist "dist_nuitka\config_debug.log" (
    echo [LEAK] dist_nuitka\config_debug.log ton tai - xoa truoc khi phat hanh.
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete: %OUT%
echo ============================================================
echo  Gui thang file .exe nay cho nguoi dung, khong can zip gi them.
if defined ENV_OPT echo  Cau hinh mac dinh da nhung san; nguoi dung van ghi de duoc
if defined ENV_OPT echo  qua dialog Cai dat (%%APPDATA%%\VitalLens\.env thang do uu tien).
if not defined ENV_OPT echo  Nguoi dung nhap API_UPLOAD_URL / API_BEARER_TOKEN qua dialog Cai dat.
echo.
exit /b 0
