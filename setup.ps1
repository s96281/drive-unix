# ==============================================================================
# drive-unix Windows PowerShell 一鍵架設與初始化管理入口 (setup.ps1)
# ==============================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "       drive-unix Windows 一鍵架設與初始化管理程序 (PowerShell)       " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 1. 檢查 uv 工具鏈
$uvCmd = Get-Command "uv" -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    $fallbackPaths = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\bin\uv.exe",
        "$env:USERPROFILE\.cargo\bin\uv.exe"
    )
    foreach ($p in $fallbackPaths) {
        if (Test-Path $p) {
            $env:Path = (Split-Path -Parent $p) + ";" + $env:Path
            $uvCmd = Get-Command "uv" -ErrorAction SilentlyContinue
            break
        }
    }
}

if (-not $uvCmd) {
    Write-Host "[INFO] 正在為您自動下載並配置 Astral uv 高速 Python 工具鏈..." -ForegroundColor Blue
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $uvLocal = "$env:USERPROFILE\.local\bin"
        if (Test-Path "$uvLocal\uv.exe") {
            $env:Path = "$uvLocal;" + $env:Path
            $uvCmd = Get-Command "uv" -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "[WARN] 自動安裝 uv 失敗: $_" -ForegroundColor Yellow
    }
}

# 2. 建立虛擬環境 (.venv)
$VenvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[INFO] 正在配置 Python 3.12 虛擬環境 (.venv)..." -ForegroundColor Blue
    if ($uvCmd) {
        & uv python install 3.12 2>$null
        & uv venv .venv --python 3.12 2>$null
        if (-not (Test-Path $VenvPy)) {
            & uv venv .venv
        }
    } else {
        $sysPy = Get-Command "python" -ErrorAction SilentlyContinue
        if ($sysPy) {
            & python -m venv .venv
        } else {
            Write-Host "[ERROR] 系統未安裝 Python 或 uv 工具鏈，請先安裝 Python 3.12+ (https://python.org)！" -ForegroundColor Red
            Exit 1
        }
    }
}

# 3. 安裝相依套件
Write-Host "[INFO] 正在檢查與安裝專案依賴套件 (all, web)..." -ForegroundColor Blue
if ($uvCmd) {
    & uv pip install -e ".[all,web]"
} else {
    & $VenvPy -m pip install --upgrade pip 2>$null
    & $VenvPy -m pip install -e ".[all,web]"
}

Write-Host "`n[SUCCESS] 虛擬環境與套件已就緒！`n" -ForegroundColor Green

# 4. 執行核心安裝精靈
& $VenvPy "$ScriptDir\scripts\setup.py" @args
