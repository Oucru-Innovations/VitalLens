@echo off
setlocal
cd /d "%~dp0"

:: ====================================================================
:: VitalLens - Build Script
:: Usage: conda activate paddleocr && build.bat
:: ====================================================================

set "PYTHON_EXE="

:: Priority 1: Conda env (paddleocr)
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" (
    set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
    echo [INFO] Using Conda env: %CONDA_PREFIX%
)

:: Priority 2: Local venv
if not defined PYTHON_EXE if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo [INFO] Using local .venv
)

:: Priority 3: System Python
if not defined PYTHON_EXE where py >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    echo [ERROR] Could not find Python.
    echo [ERROR] Run: conda activate paddleocr
    exit /b 1
)

echo.
echo ============================================================
echo  VitalLens - PyInstaller Build
echo ============================================================
echo.

:: --- Step 1: Build with PyInstaller ---
echo [1/3] Running PyInstaller...
if /i "%PYTHON_EXE%"=="py" (
    %PYTHON_EXE% -m PyInstaller build_exe.spec --noconfirm --clean
) else (
    "%PYTHON_EXE%" -m PyInstaller build_exe.spec --noconfirm --clean
)

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

:: --- Step 2: Ship the TEMPLATE only, never the real .env ---
:: The build machine's .env holds a live bearer token. Copying it here put
:: that token into every distributed ZIP. Each end user fills in their own.
set "DIST_DIR=dist\VitalLens"
echo.
echo [2/4] Copying runtime config template...

if exist ".env.example" (
    copy /Y ".env.example" "%DIST_DIR%\.env.example" >nul
    echo [OK] Copied .env.example to %DIST_DIR%\.env.example
) else (
    echo [ERROR] .env.example not found - cannot ship a config template.
    exit /b 1
)

:: --- Step 3: Copy icon ---
echo.
echo [3/4] Copying assets...
if exist "icon.ico" (
    copy /Y "icon.ico" "%DIST_DIR%\icon.ico" >nul 2>nul
    echo [OK] Copied icon.ico
)

:: --- Step 4: Refuse to finish if a secret leaked into the dist folder ---
echo.
echo [4/4] Scanning dist for secrets...
set "LEAK=0"

if exist "%DIST_DIR%\.env" (
    echo [LEAK] %DIST_DIR%\.env exists - real credentials must not ship.
    set "LEAK=1"
)
if exist "%DIST_DIR%\env" (
    echo [LEAK] %DIST_DIR%\env exists - real credentials must not ship.
    set "LEAK=1"
)
if exist "%DIST_DIR%\config_debug.log" (
    echo [LEAK] %DIST_DIR%\config_debug.log exists - may contain config values.
    set "LEAK=1"
)

if "%LEAK%"=="1" (
    echo.
    echo [ERROR] Build stopped: remove the files above from %DIST_DIR%\,
    echo [ERROR] then re-run build.bat. Do NOT zip this folder as-is.
    exit /b 1
)
echo [OK] No secret files found in %DIST_DIR%\

echo.
echo ============================================================
echo  Build complete: %DIST_DIR%\VitalLens.exe
echo ============================================================
echo.
echo  To distribute: zip the entire %DIST_DIR%\ folder.
echo  Each user then copies .env.example to .env and fills in
echo  their own API_UPLOAD_URL / API_BEARER_TOKEN.
echo.
exit /b 0
