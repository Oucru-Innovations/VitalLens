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

:: --- Step 2: Copy runtime config (.env) next to EXE ---
set "DIST_DIR=dist\VitalLens"
echo.
echo [2/3] Copying runtime config...

if exist ".env" (
    copy /Y ".env" "%DIST_DIR%\.env" >nul
    echo [OK] Copied .env to %DIST_DIR%\.env
) else if exist "env" (
    copy /Y "env" "%DIST_DIR%\.env" >nul
    echo [OK] Copied env to %DIST_DIR%\.env
) else (
    echo [WARN] No .env or env file found.
    echo [WARN] Copy .env to %DIST_DIR%\ before distributing.
)

:: --- Step 3: Copy icon ---
echo.
echo [3/3] Copying assets...
if exist "icon.ico" (
    copy /Y "icon.ico" "%DIST_DIR%\icon.ico" >nul 2>nul
    echo [OK] Copied icon.ico
)

echo.
echo ============================================================
echo  Build complete: %DIST_DIR%\VitalLens.exe
echo ============================================================
echo.
echo  To distribute: zip the entire %DIST_DIR%\ folder.
echo  To change API config: edit %DIST_DIR%\.env (no rebuild needed).
echo.
exit /b 0
