@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo [知匣] Killing zombie processes on ports 1420 and 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":1420" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a on port 1420
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a on port 8765
    taskkill /F /PID %%a >nul 2>&1
)

echo [知匣] Initializing MSVC environment for Rust...
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (
    echo ERROR: Failed to initialize MSVC environment. Make sure BuildTools 2022 is installed.
    pause
    exit /b 1
)

echo [知匣] Setting up environment...
set "PATH=C:\Users\bob\.rustup\toolchains\stable-x86_64-pc-windows-msvc\bin;%PATH%"
set "ZHIXIA_PYTHON_EXE=e:\Users\bob\Documents\BobBase\aizsk\filemind_mvp\venv\Scripts\python.exe"
set "ZHIXIA_PYTHON_DIR=e:\Users\bob\Documents\BobBase\aizsk\zhixia\src-tauri\python"

echo [知匣] Starting Tauri dev server...
cd /d "e:\Users\bob\Documents\BobBase\aizsk\zhixia"
npm run tauri dev

pause
