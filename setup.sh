#!/usr/bin/env bash
# ==============================================================================
# drive-unix 全方位一鍵架設與初始化管理入口 (Unified Bootstrap & Setup)
#
# 支援環境:
#   - Linux: Ubuntu 22.04/24.04, Debian 11/12, CentOS/RHEL/Fedora, Arch Linux
#   - macOS: Apple Silicon (M1/M2/M3) & Intel x86_64
#
# 功能:
#   1. 自動偵測作業系統與硬體架構，檢查必要系統工具 (curl, git 等)
#   2. 自動配置 Astral uv 高速 Python 工具鏈 (免手動編譯 Python)
#   3. 自動安裝 Python 3.12 與建立虛擬環境 (.venv)
#   4. 安裝 drive-unix 完整依賴 (all, web)
#   5. 啟動互動式導引：VPS/PC 模式、Upstash E2EE 跨端同步、Systemd 守護行程
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 0. 終端色彩輸出 (Terminal Colors)
# ------------------------------------------------------------------------------
if [[ -t 1 ]] && [[ "${NO_COLOR:-0}" != "1" ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  NC='\033[0m'
else
  RED=''
  GREEN=''
  YELLOW=''
  BLUE=''
  CYAN=''
  BOLD=''
  NC=''
fi

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ------------------------------------------------------------------------------
# 1. 路徑與使用者解析 (Path & User Resolution)
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ACTUAL_USER="${SUDO_USER:-${USER:-$(id -un 2>/dev/null || whoami 2>/dev/null || echo "root")}}"
if [ "${ACTUAL_USER}" = "root" ]; then
  ACTUAL_HOME="/root"
elif command -v getent >/dev/null 2>&1; then
  ACTUAL_HOME="$(getent passwd "${ACTUAL_USER}" 2>/dev/null | cut -d: -f6 || echo "${HOME:-/home/${ACTUAL_USER}}")"
else
  ACTUAL_HOME="${HOME:-/home/${ACTUAL_USER}}"
fi

CURRENT_EUID="${EUID:-$(id -u 2>/dev/null || echo 1000)}"

run_as_root() {
  if [ "${CURRENT_EUID}" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo "$@"
    else
      log_error "需要管理員權限，但系統未找到 sudo 指令！"
      exit 1
    fi
  else
    "$@"
  fi
}

run_as_user() {
  if [ "${CURRENT_EUID}" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    sudo -u "${SUDO_USER}" "$@"
  else
    "$@"
  fi
}

# ------------------------------------------------------------------------------
# 2. 系統基礎套件檢查與安裝 (System Prerequisites)
# ------------------------------------------------------------------------------
echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}${BOLD}       drive-unix 全自動初始化引導程序 (Unified Setup Bootstrap)      ${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo -e "目前使用者: ${GREEN}${ACTUAL_USER}${NC}"
echo -e "專案目錄:   ${GREEN}${SCRIPT_DIR}${NC}\n"

# Debian / Ubuntu package bootstrap
if command -v apt-get >/dev/null 2>&1; then
  MISSING_PKGS=()
  for pkg in curl git build-essential ca-certificates jq; do
    if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
      MISSING_PKGS+=("${pkg}")
    fi
  done
  if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    log_info "正在安裝系統底層套件 (${MISSING_PKGS[*]})..."
    run_as_root apt-get update -y
    run_as_root apt-get install -y --no-install-recommends "${MISSING_PKGS[@]}"
  fi
fi

# Ensure correct file ownership for current user
if [ "${CURRENT_EUID}" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  chown -R "${ACTUAL_USER}:${ACTUAL_USER}" "${SCRIPT_DIR}" 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 3. 配置 uv 高速 Python 工具鏈 (Astral uv Bootstrap)
# ------------------------------------------------------------------------------
export PATH="${ACTUAL_HOME}/.local/bin:${ACTUAL_HOME}/.cargo/bin:/usr/local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1 && [ ! -f "${ACTUAL_HOME}/.local/bin/uv" ]; then
  log_info "正在為 ${ACTUAL_USER} 自動安裝 Astral uv 高速 Python 工具鏈..."
  run_as_user bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
  export PATH="${ACTUAL_HOME}/.local/bin:${PATH}"
fi

UV_BIN="$(command -v uv || echo "${ACTUAL_HOME}/.local/bin/uv")"

# ------------------------------------------------------------------------------
# 4. 建立 Python 3.12 虛擬環境與安裝相依套件 (.venv)
# ------------------------------------------------------------------------------
VENV_DIR="${SCRIPT_DIR}/.venv"
VENV_PY="${VENV_DIR}/bin/python"

if [ ! -f "${VENV_PY}" ]; then
  log_info "正在透過 uv 配置 Python 3.12 虛擬環境 (.venv)..."
  if [ -x "${UV_BIN}" ]; then
    run_as_user bash -c "
      export PATH='${ACTUAL_HOME}/.local/bin:\$PATH'
      cd '${SCRIPT_DIR}'
      '${UV_BIN}' python install 3.12 2>/dev/null || true
      '${UV_BIN}' venv .venv --python 3.12 2>/dev/null || '${UV_BIN}' venv .venv
    "
  else
    log_warn "未找到 uv，嘗試使用系統 python3 建立虛擬環境..."
    run_as_user python3 -m venv "${VENV_DIR}"
  fi
fi

log_info "檢查並安裝專案依賴 (all, web)..."
if [ -x "${UV_BIN}" ]; then
  run_as_user bash -c "
    export PATH='${ACTUAL_HOME}/.local/bin:\$PATH'
    cd '${SCRIPT_DIR}'
    '${UV_BIN}' pip install -e '.[all,web]'
  "
else
  run_as_user "${VENV_PY}" -m pip install --upgrade pip
  run_as_user "${VENV_PY}" -m pip install -e ".[all,web]"
fi

log_success "核心環境與依賴套件配置完成！"

# ------------------------------------------------------------------------------
# 5. 移交核心安裝導引精靈 (Hand off to Python Setup Orchestrator)
# ------------------------------------------------------------------------------
if [ -f "${SCRIPT_DIR}/scripts/setup.py" ]; then
  if [ "${CURRENT_EUID}" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    # Pass through interactive terminal under user
    exec sudo -u "${SUDO_USER}" "${VENV_PY}" "${SCRIPT_DIR}/scripts/setup.py" "$@"
  else
    exec "${VENV_PY}" "${SCRIPT_DIR}/scripts/setup.py" "$@"
  fi
else
  log_error "找不到核心安裝腳本: ${SCRIPT_DIR}/scripts/setup.py"
  exit 1
fi
