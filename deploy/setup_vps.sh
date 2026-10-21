#!/usr/bin/env bash
# ==============================================================================
# drive-unix VPS 憑證換發中心 (Token Renewal Center) 一鍵安裝與佈署腳本
# 適用於: Ubuntu 22.04 / 24.04, Debian 12
# 特色:
#   1. 使用 astral-sh/uv 高速工具鏈，免加 PPA 自動管理 Python 3.12
#   2. 以使用者家目錄 (~/drive-unix) 為核心，完全由當前使用者持有，杜絕權限衝突
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}   drive-unix 家目錄憑證換發中心 (uv 高速安裝導引)   ${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. 識別實際執行者與目錄
ACTUAL_USER="${SUDO_USER:-$USER}"
if [ "$ACTUAL_USER" = "root" ]; then
  ACTUAL_HOME="/root"
else
  ACTUAL_HOME="$(getent passwd "$ACTUAL_USER" | cut -d: -f6)"
fi

echo -e "目標執行使用者: ${GREEN}${ACTUAL_USER}${NC}"
echo -e "使用者家目錄:   ${GREEN}${ACTUAL_HOME}${NC}"

run_as_root() {
  if [ "$EUID" -ne 0 ]; then
    if command -v sudo &> /dev/null; then
      sudo "$@"
    else
      echo -e "${RED}❌ 需要管理員權限，但系統未找到 sudo 指令！${NC}"
      exit 1
    fi
  else
    "$@"
  fi
}

run_as_user() {
  if [ "$EUID" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    sudo -u "$SUDO_USER" "$@"
  else
    "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${SCRIPT_DIR}/pyproject.toml" ]; then
  INSTALL_DIR="${SCRIPT_DIR}"
else
  INSTALL_DIR="${ACTUAL_HOME}/drive-unix"
fi
echo -e "專案工作目錄:   ${GREEN}${INSTALL_DIR}${NC}"

# 2. 安裝系統基礎底層套件
echo -e "\n${YELLOW}[1/5] 安裝基礎套件 (curl, git, build-essential, ca-certificates)...${NC}"
run_as_root apt-get update -y
run_as_root apt-get install -y --no-install-recommends \
  curl \
  git \
  build-essential \
  ca-certificates

# 確保目錄歸屬當前使用者
if [ ! -d "${INSTALL_DIR}" ]; then
  mkdir -p "${INSTALL_DIR}"
  if [ -f "${SCRIPT_DIR}/pyproject.toml" ] && [ "${SCRIPT_DIR}" != "${INSTALL_DIR}" ]; then
    cp -r "${SCRIPT_DIR}/." "${INSTALL_DIR}/"
  fi
fi
run_as_root chown -R "${ACTUAL_USER}:${ACTUAL_USER}" "${INSTALL_DIR}"

# 3. 為使用者安裝/確認 uv
echo -e "\n${YELLOW}[2/5] 檢查/安裝 uv 工具鏈...${NC}"
run_as_user bash -c "
  if ! command -v uv &> /dev/null; then
    echo '正在為 ${ACTUAL_USER} 安裝 uv...'
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
"

# 4. 透過 uv 自動下載 Python 3.12 並建立虛擬環境
echo -e "\n${YELLOW}[3/5] 透過 uv 自動配置 Python 3.12 與安裝完整相依依賴 (all, web)...${NC}"
run_as_user bash -c "
  export PATH='${ACTUAL_HOME}/.local/bin:\$PATH'
  cd '${INSTALL_DIR}'
  uv python install 3.12
  uv venv .venv --python 3.12
  source .venv/bin/activate
  uv pip install -e '.[all,web]'
"

# 5. 安裝 Playwright Chromium (支援 SharePoint 驗證)
echo -e "\n${YELLOW}[4/5] 安裝 Headless Chromium 與系統圖形庫 (用於 SharePoint 驗證)...${NC}"
run_as_user bash -c "
  cd '${INSTALL_DIR}'
  source .venv/bin/activate
  playwright install chromium
"
run_as_root "${INSTALL_DIR}/.venv/bin/playwright" install-deps chromium || true

# 6. 配置 Systemd 服務 (以當前使用者執行)
echo -e "\n${YELLOW}[5/5] 設定 Systemd 背景守護服務 (以使用者 ${ACTUAL_USER} 身分執行)...${NC}"

cat <<EOF | run_as_root tee /etc/systemd/system/drive-unix-renew.service > /dev/null
[Unit]
Description=drive-unix Upstash Token Renewal Center Daemon (憑證換發中心)
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${ACTUAL_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${INSTALL_DIR}/.venv/bin/drive-unix upstash renew-tokens --interval 1800 --leeway 60

Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF | run_as_root tee /etc/systemd/system/drive-unix-web.service > /dev/null
[Unit]
Description=drive-unix Web Management UI & REST API Server
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${ACTUAL_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${INSTALL_DIR}/.venv/bin/python -m web --host 127.0.0.1 --port 8000

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

run_as_root systemctl daemon-reload

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}  🎉 drive-unix (uv) 憑證換發中心環境已成功安裝完畢！  ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "接下來請依序執行以下指令完成設定與啟動："
echo -e ""
echo -e "1. 啟用虛擬環境："
echo -e "   ${BLUE}cd ${INSTALL_DIR}${NC}"
echo -e "   ${BLUE}source .venv/bin/activate${NC}"
echo -e ""
echo -e "2. 連線至 Upstash 並拉取雲端節點設定與憑證："
echo -e "   ${BLUE}drive-unix upstash config${NC}"
echo -e "   ${BLUE}drive-unix upstash pull -p '您的主密碼'${NC}"
echo -e ""
echo -e "3. 測試單次換發巡檢："
echo -e "   ${BLUE}drive-unix upstash renew-tokens --leeway 60${NC}"
echo -e ""
echo -e "4. 啟動開機自啟憑證換發中心背景服務 (每 30 分鐘主動巡檢換發)："
echo -e "   ${BLUE}sudo systemctl enable --now drive-unix-renew.service${NC}"
echo -e "   查看即時運行狀態: ${BLUE}sudo journalctl -u drive-unix-renew.service -f${NC}"
echo -e "======================================================"
