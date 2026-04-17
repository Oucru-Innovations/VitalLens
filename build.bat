@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="

if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
if not defined PYTHON_EXE where py >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"

if not defined PYTHON_EXE (
    echo [ERROR] Could not find a working Python launcher.
    echo [ERROR] Activate your venv or Conda env first, then rerun this script.
    exit /b 1
)

echo [INFO] Building VitalLens...

if /i "%PYTHON_EXE%"=="py" (
    %PYTHON_EXE% -m PyInstaller build_exe.spec --noconfirm --clean
) else (
    "%PYTHON_EXE%" -m PyInstaller build_exe.spec --noconfirm --clean
)

if errorlevel 1 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [OK] Build completed: dist\VitalLens
exit /b 0
