@echo off
rem ==============================================================================
rem drive-unix Windows 一鍵架設與初始化管理入口 (Unified Bootstrap & Setup)
rem
rem 支援系統: Windows 10 / Windows 11 / Windows Server 2019+
rem 功能:
rem   1. 自動偵測與配置 uv 高速 Python 工具鏈 (或使用既有 Python 3.12+)
rem   2. 自動建立虛擬環境 (.venv) 並安裝完整相依套件 (all, web)
rem   3. 啟動互動式設定精靈 (PC / VPS 模式、Upstash E2EE 跨端同步、Web 控制台)
rem ==============================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ======================================================================
echo        drive-unix Windows 一鍵架設與初始化管理程序 (Setup)
echo ======================================================================
echo.

cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

rem 1. 尋找 uv 工具鏈
set "UV_CMD="
where uv >nul 2>&1
if !errorlevel! equ 0 (
    set "UV_CMD=uv"
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
) else if exist "%LOCALAPPDATA%\bin\uv.exe" (
    set "UV_CMD=%LOCALAPPDATA%\bin\uv.exe"
    set "PATH=%LOCALAPPDATA%\bin;%PATH%"
) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.cargo\bin\uv.exe"
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
)

rem 2. 若未安裝 uv，嘗試自動安裝 uv
if "%UV_CMD%"=="" (
    echo [INFO] 未偵測到 Astral uv 工具鏈，正在為您自動下載安裝...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    )
)

rem 3. 檢查或建立虛擬環境 (.venv)
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] 正在建立 Python 3.12 虛擬環境 (.venv)...
    if not "%UV_CMD%"=="" (
        "%UV_CMD%" python install 3.12 >nul 2>&1
        "%UV_CMD%" venv .venv --python 3.12 >nul 2>&1
        if not exist ".venv\Scripts\python.exe" (
            "%UV_CMD%" venv .venv
        )
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            python -m venv .venv
        ) else (
            echo [ERROR] 系統未安裝 Python 或 uv 工具鏈，請先安裝 Python 3.12+ (https://python.org) 或 Astral uv！
            pause
            exit /b 1
        )
    )
)

rem 4. 安裝/更新專案依賴套件
echo [INFO] 正在確認相依套件完整性 (all, web)...
if not "%UV_CMD%"=="" (
    "%UV_CMD%" pip install -e ".[all,web]"
) else (
    .\.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
    .\.venv\Scripts\python.exe -m pip install -e ".[all,web]"
)

echo.
echo [SUCCESS] 核心工具鏈與虛擬環境已就緒！
echo.

rem 5. 執行核心安裝與初始化導引
.\.venv\Scripts\python.exe scripts\setup.py %*

if !errorlevel! neq 0 (
    echo.
    echo [WARN] 設定過程非正常結束 (結束碼: !errorlevel!)。
)

echo.
pause
