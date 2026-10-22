#!/usr/bin/env bash
# ==============================================================================
# drive-unix Production Deployment & Operations Management Script
#
# Supported Environments:
#   1. Docker & Docker Compose (Containerized Production - Recommended)
#   2. Linux Systemd (Native Linux Daemon Service)
#   3. Python Virtualenv (Direct Execution / Development / Testing)
#
# Subcommands:
#   build       - Build Docker images or initialize Python virtualenv
#   start       - Start services in background
#   stop        - Gracefully stop services
#   restart     - Gracefully restart services
#   status      - Query running status of services
#   healthcheck - Probe /api/health with retry loop and response verification
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 0. Terminal Colors & Formatting
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
# 1. Path & Configuration Resolution
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SCRIPT_DIR}"

HOST="${DRIVE_UNIX_HOST:-127.0.0.1}"
PORT="${DRIVE_UNIX_PORT:-8000}"

CONFIG_DIR="${DRIVE_UNIX_CONFIG_DIR:-${HOME}/.config/drive-unix}"
LEGACY_CONFIG_DIR="${HOME}/.config/mycli"
LOG_DIR="${CONFIG_DIR}/logs"
PROJECT_LOG_DIR="${SCRIPT_DIR}/logs"
DEBUG_DIR="${DRIVE_UNIX_DEBUG_DIR:-${CONFIG_DIR}/debug}"
PID_FILE="${CONFIG_DIR}/web.pid"

# ------------------------------------------------------------------------------
# 2. Environment Auto-Detection
# ------------------------------------------------------------------------------
detect_environment() {
  # 1. Docker & Docker Compose check
  if command -v docker >/dev/null 2>&1 && (docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1); then
    echo "docker"
    return 0
  fi

  # 2. Linux Systemd check
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    echo "systemd"
    return 0
  fi

  # 3. Python virtualenv / toolchain check
  if command -v uv >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    echo "venv"
    return 0
  fi

  echo "unknown"
}

# Resolve execution mode (allow override via DEPLOY_MODE)
MODE="${DEPLOY_MODE:-$(detect_environment)}"

docker_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    log_error "Neither 'docker compose' nor 'docker-compose' command found!"
    return 1
  fi
}

get_venv_python() {
  if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    echo "${SCRIPT_DIR}/.venv/bin/python"
  elif [ -x "${SCRIPT_DIR}/.venv/Scripts/python.exe" ]; then
    echo "${SCRIPT_DIR}/.venv/Scripts/python.exe"
  elif [ -x "${SCRIPT_DIR}/.venv/Scripts/python" ]; then
    echo "${SCRIPT_DIR}/.venv/Scripts/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    log_error "No python executable found."
    return 1
  fi
}

# ------------------------------------------------------------------------------
# 3. Directory & Security Initialization
# ------------------------------------------------------------------------------
init_directories() {
  log_info "Initializing directory structure and security permissions..."

  # Create configuration, logs, and debug directories
  mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${PROJECT_LOG_DIR}" "${DEBUG_DIR}"

  # Enforce directory permissions: 0700
  chmod 700 "${CONFIG_DIR}" 2>/dev/null || true
  chmod 700 "${LOG_DIR}" 2>/dev/null || true
  chmod 700 "${DEBUG_DIR}" 2>/dev/null || true

  # Create compatibility symlink: ~/.config/mycli -> ~/.config/drive-unix
  if [ ! -e "${LEGACY_CONFIG_DIR}" ] && [ ! -L "${LEGACY_CONFIG_DIR}" ]; then
    mkdir -p "$(dirname "${LEGACY_CONFIG_DIR}")"
    ln -s "${CONFIG_DIR}" "${LEGACY_CONFIG_DIR}" 2>/dev/null || true
    log_info "Created compatibility symlink: ${LEGACY_CONFIG_DIR} -> ${CONFIG_DIR}"
  fi

  # Enforce restrictive permissions (0600) on sensitive configuration and secret files
  local sensitive_files=(
    "${CONFIG_DIR}/secrets.json"
    "${CONFIG_DIR}/config.toml"
    "${LEGACY_CONFIG_DIR}/secrets.json"
    "${LEGACY_CONFIG_DIR}/config.toml"
    "${SCRIPT_DIR}/.env"
    "${SCRIPT_DIR}/.env.production"
  )
  for file_path in "${sensitive_files[@]}"; do
    if [ -f "${file_path}" ]; then
      chmod 600 "${file_path}" 2>/dev/null || true
      log_info "Locked down permissions (0600) on: ${file_path}"
    fi
  done

  log_success "Directory structure & security permissions initialized (CONFIG_DIR: ${CONFIG_DIR})."
}

# ------------------------------------------------------------------------------
# 4. Subcommands Implementation
# ------------------------------------------------------------------------------

# [Subcommand: build]
do_build() {
  init_directories
  log_info "Executing build workflow [Mode: ${MODE}]..."
  case "${MODE}" in
    docker)
      log_info "Building Docker images via Docker Compose..."
      docker_compose_cmd build
      log_success "Docker Compose build complete."
      ;;
    systemd|venv)
      if command -v uv >/dev/null 2>&1; then
        log_info "Setting up Python virtualenv using uv..."
        uv venv .venv --python 3.12 2>/dev/null || uv venv .venv
        if [ -f ".venv/bin/activate" ]; then
          # shellcheck disable=SC1091
          source .venv/bin/activate
        elif [ -f ".venv/Scripts/activate" ]; then
          # shellcheck disable=SC1091
          source .venv/Scripts/activate
        fi
        log_info "Installing dependencies via uv pip install..."
        uv pip install -e ".[all,web]"
      else
        log_info "Setting up Python virtualenv using python -m venv..."
        local py_bin
        py_bin="$(command -v python3 || command -v python)"
        "${py_bin}" -m venv .venv
        if [ -f ".venv/bin/activate" ]; then
          # shellcheck disable=SC1091
          source .venv/bin/activate
        elif [ -f ".venv/Scripts/activate" ]; then
          # shellcheck disable=SC1091
          source .venv/Scripts/activate
        fi
        python -m pip install --upgrade pip
        python -m pip install -e ".[all,web]"
      fi
      log_success "Python virtualenv and package dependencies built successfully."
      ;;
    *)
      log_error "Unrecognized or unsupported deployment mode: '${MODE}'"
      exit 1
      ;;
  esac
}

# [Subcommand: start]
do_start() {
  init_directories
  log_info "Starting drive-unix services [Mode: ${MODE}]..."
  case "${MODE}" in
    docker)
      log_info "Launching Docker containers in detached background mode..."
      docker_compose_cmd up -d
      log_success "Docker containers started successfully."
      log_info "Check service status: $0 status"
      ;;
    systemd)
      if [ -f "/etc/systemd/system/drive-unix.service" ]; then
        log_info "Reloading systemd and enabling drive-unix.service..."
        sudo systemctl daemon-reload
        sudo systemctl enable --now drive-unix.service
        log_success "Systemd service 'drive-unix.service' started."
      elif [ -f "/etc/systemd/system/drive-unix-web.service" ]; then
        log_info "Reloading systemd and enabling drive-unix-web.service..."
        sudo systemctl daemon-reload
        sudo systemctl enable --now drive-unix-web.service
        if [ -f "/etc/systemd/system/drive-unix-renew.service" ]; then
          sudo systemctl enable --now drive-unix-renew.service
          log_info "Systemd service 'drive-unix-renew.service' enabled and started."
        fi
        log_success "Systemd services started."
      else
        log_warn "No systemd service unit found in /etc/systemd/system/."
        log_info "Deploy unit file first:"
        log_info "  sudo cp deploy/systemd/drive-unix.service /etc/systemd/system/"
        log_info "  sudo systemctl daemon-reload"
        log_info "  sudo systemctl enable --now drive-unix.service"
        exit 1
      fi
      ;;
    venv)
      if [ -f "${PID_FILE}" ]; then
        local existing_pid
        existing_pid="$(cat "${PID_FILE}")"
        if kill -0 "${existing_pid}" 2>/dev/null; then
          log_warn "Web server is already running (PID: ${existing_pid})."
          log_info "To restart, execute: $0 restart"
          return 0
        else
          rm -f "${PID_FILE}"
        fi
      fi

      local py_exec
      py_exec="$(get_venv_python)"
      log_info "Starting web server in background (${py_exec} -m web --host ${HOST} --port ${PORT})..."
      nohup "${py_exec}" -m web --host "${HOST}" --port "${PORT}" > "${PROJECT_LOG_DIR}/web.log" 2>&1 &
      local new_pid=$!
      echo "${new_pid}" > "${PID_FILE}"
      sleep 1

      if kill -0 "${new_pid}" 2>/dev/null; then
        log_success "Web service running in background (PID: ${new_pid})."
        log_info "Log location: ${PROJECT_LOG_DIR}/web.log"
      else
        log_error "Web service failed to start! Check logs at: ${PROJECT_LOG_DIR}/web.log"
        rm -f "${PID_FILE}"
        exit 1
      fi
      ;;
    *)
      log_error "Unrecognized or unsupported deployment mode: '${MODE}'"
      exit 1
      ;;
  esac
}

# [Subcommand: stop]
do_stop() {
  log_info "Stopping drive-unix services [Mode: ${MODE}]..."
  case "${MODE}" in
    docker)
      log_info "Stopping Docker Compose containers..."
      docker_compose_cmd down
      log_success "Docker containers stopped."
      ;;
    systemd)
      log_info "Stopping Systemd services..."
      if systemctl is-active --quiet drive-unix.service 2>/dev/null; then
        sudo systemctl stop drive-unix.service
        log_success "Stopped drive-unix.service."
      fi
      if systemctl is-active --quiet drive-unix-web.service 2>/dev/null; then
        sudo systemctl stop drive-unix-web.service
        log_success "Stopped drive-unix-web.service."
      fi
      if systemctl is-active --quiet drive-unix-renew.service 2>/dev/null; then
        sudo systemctl stop drive-unix-renew.service
        log_success "Stopped drive-unix-renew.service."
      fi
      log_success "Systemd stop operation finished."
      ;;
    venv)
      if [ -f "${PID_FILE}" ]; then
        local pid
        pid="$(cat "${PID_FILE}")"
        if kill -0 "${pid}" 2>/dev/null; then
          log_info "Sending SIGTERM to Web process PID ${pid}..."
          kill "${pid}" 2>/dev/null || true
          local count=0
          while kill -0 "${pid}" 2>/dev/null && [ "${count}" -lt 5 ]; do
            sleep 1
            count=$((count + 1))
          done
          if kill -0 "${pid}" 2>/dev/null; then
            log_warn "Process PID ${pid} did not terminate within 5s, sending SIGKILL..."
            kill -9 "${pid}" 2>/dev/null || true
          fi
          log_success "Web server process terminated (PID: ${pid})."
        else
          log_warn "Process PID ${pid} was not actively running."
        fi
        rm -f "${PID_FILE}"
      else
        log_info "No PID file found at ${PID_FILE}. Attempting fallback pkill..."
        pkill -f "python.* -m web" 2>/dev/null || true
        log_success "Stop signal processed."
      fi
      ;;
    *)
      log_error "Unrecognized or unsupported deployment mode: '${MODE}'"
      exit 1
      ;;
  esac
}

# [Subcommand: restart]
do_restart() {
  log_info "Restarting drive-unix services [Mode: ${MODE}]..."
  case "${MODE}" in
    docker)
      docker_compose_cmd restart 2>/dev/null || {
        do_stop
        sleep 2
        do_start
      }
      log_success "Docker services restarted."
      ;;
    systemd)
      if [ -f "/etc/systemd/system/drive-unix.service" ]; then
        sudo systemctl restart drive-unix.service
        log_success "Restarted drive-unix.service."
      else
        sudo systemctl restart drive-unix-web.service 2>/dev/null || true
        sudo systemctl restart drive-unix-renew.service 2>/dev/null || true
        log_success "Restarted Systemd services."
      fi
      ;;
    venv)
      do_stop
      sleep 2
      do_start
      ;;
    *)
      log_error "Unrecognized or unsupported deployment mode: '${MODE}'"
      exit 1
      ;;
  esac
}

# [Subcommand: status]
do_status() {
  log_info "Querying drive-unix service status [Mode: ${MODE}]..."
  case "${MODE}" in
    docker)
      docker_compose_cmd ps
      ;;
    systemd)
      if [ -f "/etc/systemd/system/drive-unix.service" ]; then
        sudo systemctl status drive-unix.service --no-pager || true
      fi
      if [ -f "/etc/systemd/system/drive-unix-web.service" ]; then
        sudo systemctl status drive-unix-web.service --no-pager || true
      fi
      if [ -f "/etc/systemd/system/drive-unix-renew.service" ]; then
        sudo systemctl status drive-unix-renew.service --no-pager || true
      fi
      ;;
    venv)
      if [ -f "${PID_FILE}" ]; then
        local pid
        pid="$(cat "${PID_FILE}")"
        if kill -0 "${pid}" 2>/dev/null; then
          log_success "Web service is running (PID: ${pid})."
          log_info "Target URL: http://${HOST}:${PORT}"
          log_info "Log file:   ${PROJECT_LOG_DIR}/web.log"
        else
          log_warn "PID file exists (${PID_FILE}, PID: ${pid}) but process is NOT running (stale PID)."
        fi
      else
        log_warn "No PID file found (${PID_FILE}). Web service does not appear to be running."
      fi
      ;;
    *)
      log_error "Unrecognized or unsupported deployment mode: '${MODE}'"
      exit 1
      ;;
  esac
}

# [Subcommand: healthcheck]
do_healthcheck() {
  local target_url="http://${HOST}:${PORT}/api/health"
  local max_retries="${HEALTHCHECK_MAX_RETRIES:-10}"
  local retry_interval="${HEALTHCHECK_INTERVAL:-2}"
  local count=0
  local resp=""

  log_info "Probing system health endpoint: ${target_url}"
  log_info "Max retries: ${max_retries}, Interval: ${retry_interval}s"

  while [ "${count}" -lt "${max_retries}" ]; do
    count=$((count + 1))

    if command -v curl >/dev/null 2>&1; then
      resp="$(curl -fsSL --connect-timeout 3 --max-time 5 "${target_url}" 2>/dev/null || echo "CONNECT_FAILED")"
    elif command -v wget >/dev/null 2>&1; then
      resp="$(wget -qO- --timeout=5 -T 3 "${target_url}" 2>/dev/null || echo "CONNECT_FAILED")"
    else
      local py_exec
      py_exec="$(get_venv_python 2>/dev/null || command -v python3 || command -v python || echo "")"
      if [ -n "${py_exec}" ]; then
        resp="$("${py_exec}" -c "import urllib.request, sys; sys.stdout.write(urllib.request.urlopen('${target_url}', timeout=3).read().decode())" 2>/dev/null || echo "CONNECT_FAILED")"
      else
        resp="CONNECT_FAILED"
      fi
    fi

    if [[ "${resp}" == *"\"status\":\"ok\""* ]] || [[ "${resp}" == *"\"status\": \"ok\""* ]]; then
      log_success "Healthcheck PASSED! System is operational and healthy."
      log_info "Response: ${resp}"
      return 0
    fi

    log_warn "Probe attempt ${count}/${max_retries} failed or service initializing. Retrying in ${retry_interval}s..."
    sleep "${retry_interval}"
  done

  log_error "Healthcheck FAILED after ${max_retries} attempts! Could not verify 'status: ok' at ${target_url}."
  if [ -n "${resp}" ] && [ "${resp}" != "CONNECT_FAILED" ]; then
    log_error "Last received response: ${resp}"
  fi
  return 1
}

# [Subcommand: logs]
do_logs() {
  case "${MODE}" in
    docker)
      log_info "Streaming Docker Compose logs (Ctrl+C to exit)..."
      local compose_cmd
      compose_cmd="$(get_docker_compose_cmd)"
      ${compose_cmd} logs -f "$@"
      ;;
    systemd)
      log_info "Streaming Systemd logs for drive-unix services (Ctrl+C to exit)..."
      journalctl -u drive-unix-web.service -u drive-unix-renew.service -f "$@"
      ;;
    venv)
      local log_target=""
      if [ -f "${LOG_DIR}/web.log" ]; then
        log_target="${LOG_DIR}/web.log"
      elif [ -f "${PROJECT_LOG_DIR}/web.log" ]; then
        log_target="${PROJECT_LOG_DIR}/web.log"
      fi
      if [ -n "${log_target}" ]; then
        log_info "Tailing log file: ${log_target} (Ctrl+C to exit)..."
        tail -f "${log_target}" "$@"
      else
        log_warn "No log files found in ${LOG_DIR} or ${PROJECT_LOG_DIR}."
      fi
      ;;
    *)
      log_error "Unsupported mode for logs: ${MODE}"
      exit 1
      ;;
  esac
}

# [Subcommand: setup-vps]
do_setup_vps() {
  local actual_user="${SUDO_USER:-${USER:-$(id -un 2>/dev/null || whoami 2>/dev/null || echo "driveunix")}}"
  local actual_home
  if [ "${actual_user}" = "root" ]; then
    actual_home="/root"
  elif command -v getent >/dev/null 2>&1; then
    actual_home="$(getent passwd "${actual_user}" 2>/dev/null | cut -d: -f6 || echo "${HOME:-/home/${actual_user}}")"
  else
    actual_home="${HOME:-/home/${actual_user}}"
  fi
  local current_euid="${EUID:-$(id -u 2>/dev/null || echo 1000)}"

  run_as_root() {
    if [ "${current_euid}" -ne 0 ]; then
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
    if [ "${current_euid}" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
      sudo -u "${SUDO_USER}" "$@"
    else
      "$@"
    fi
  }

  echo -e "${CYAN}======================================================================${NC}"
  echo -e "${CYAN}${BOLD}     drive-unix 生產級 VPS 伺服器一鍵安裝與服務設定導引               ${NC}"
  echo -e "${CYAN}======================================================================${NC}"
  echo -e "目標執行使用者: ${GREEN}${actual_user}${NC}"
  echo -e "使用者家目錄:   ${GREEN}${actual_home}${NC}"
  echo -e "專案工作目錄:   ${GREEN}${SCRIPT_DIR}${NC}"

  # 1. 安裝系統基礎套件
  log_info "[1/7] 安裝系統基礎套件 (curl, git, build-essential, ca-certificates, jq)..."
  run_as_root apt-get update -y
  run_as_root apt-get install -y --no-install-recommends \
    curl git build-essential ca-certificates jq
  run_as_root chown -R "${actual_user}:${actual_user}" "${SCRIPT_DIR}"

  # 2. 安裝/確認 uv 工具鏈
  log_info "[2/7] 檢查並配置 uv 高速 Python 工具鏈..."
  run_as_user bash -c "
    if ! command -v uv >/dev/null 2>&1 && [ ! -f '${actual_home}/.local/bin/uv' ]; then
      echo '正在為 ${actual_user} 安裝 uv...'
      curl -LsSf https://astral.sh/uv/install.sh | sh
    else
      echo 'uv 工具鏈已就緒。'
    fi
  "

  # 3. 透過 uv 配置 Python 3.12 與安裝相依套件
  log_info "[3/7] 透過 uv 配置 Python 3.12 與安裝完整相依套件 (all, web)..."
  run_as_user bash -c "
    export PATH='${actual_home}/.local/bin:\$PATH'
    cd '${SCRIPT_DIR}'
    uv python install 3.12
    uv venv .venv --python 3.12
    source .venv/bin/activate
    uv pip install -e '.[all,web]'
  "

  # 4. 檢查前端靜態資源
  log_info "[4/7] 檢查前端 Web UI 控制台靜態資源 (web/static/)..."
  if [ -f "${SCRIPT_DIR}/web/static/index.html" ] && [ -d "${SCRIPT_DIR}/web/static/assets" ]; then
    log_success "前端靜態資源已就緒 (web/static/)。"
  else
    log_warn "未偵測到編譯後的前端靜態資源，嘗試進行建置..."
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
      run_as_user bash -c "
        cd '${SCRIPT_DIR}/frontend'
        npm install
        npm run build
      "
      log_success "前端編譯成功！"
    else
      log_warn "系統尚未安裝 Node.js / npm。若需即刻使用前端，可安裝 Node 20 LTS："
      echo -e "   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
      echo -e "   sudo apt-get install -y nodejs"
      echo -e "   cd ${SCRIPT_DIR}/frontend && npm install && npm run build"
    fi
  fi

  # 5. 安裝 Playwright Chromium
  log_info "[5/7] 安裝 Headless Chromium 與系統圖形依賴 (用於 SharePoint 驗證)..."
  run_as_user bash -c "
    cd '${SCRIPT_DIR}'
    source .venv/bin/activate
    playwright install chromium
  "
  run_as_root "${SCRIPT_DIR}/.venv/bin/playwright" install-deps chromium || true

  # 6. 生產環境設定檔初始化 (.env)
  log_info "[6/7] 初始化生產環境組態檔案 (.env)..."
  if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    if [ -f "${SCRIPT_DIR}/.env.production.example" ]; then
      run_as_user cp "${SCRIPT_DIR}/.env.production.example" "${SCRIPT_DIR}/.env"
      run_as_user chmod 600 "${SCRIPT_DIR}/.env"
      log_success "已從 .env.production.example 建立預設 .env 檔案 (權限設為 600)。"
    else
      run_as_user touch "${SCRIPT_DIR}/.env"
      run_as_user chmod 600 "${SCRIPT_DIR}/.env"
    fi
  else
    log_info "既有 .env 檔案已存在，保留設定。"
  fi

  # 7. 配置 Systemd 服務
  log_info "[7/7] 設定 Systemd 背景服務與聯合 Target..."

  cat <<EOF | run_as_root tee /etc/systemd/system/drive-unix-web.service > /dev/null
[Unit]
Description=drive-unix Web Management UI & REST API Server
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target
PartOf=drive-unix.target

[Service]
Type=simple
User=${actual_user}
Group=${actual_user}
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=-${SCRIPT_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${SCRIPT_DIR}/.venv/bin/python -m web --host 0.0.0.0 --port 8000

Restart=always
RestartSec=10
LimitNOFILE=65535

ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target drive-unix.target
EOF

  cat <<EOF | run_as_root tee /etc/systemd/system/drive-unix-renew.service > /dev/null
[Unit]
Description=drive-unix Upstash Token Renewal Center Daemon
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target
PartOf=drive-unix.target

[Service]
Type=simple
User=${actual_user}
Group=${actual_user}
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=-${SCRIPT_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${SCRIPT_DIR}/.venv/bin/drive-unix upstash renew-tokens --interval 1800 --leeway 60

Restart=always
RestartSec=15
LimitNOFILE=65535

ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target drive-unix.target
EOF

  cat <<EOF | run_as_root tee /etc/systemd/system/drive-unix.target > /dev/null
[Unit]
Description=drive-unix Multi-Cloud Storage Suite (Web Console & Token Daemon)
Wants=drive-unix-web.service drive-unix-renew.service
After=network.target

[Install]
WantedBy=multi-user.target
EOF

  run_as_root systemctl daemon-reload

  # Nginx 範本複製
  if [ -d "/etc/nginx/sites-available" ] && [ -f "${SCRIPT_DIR}/deploy/nginx/drive-unix.conf" ]; then
    log_info "正在複製 Nginx 最佳化反向代理範本至 /etc/nginx/sites-available/drive-unix.conf ..."
    run_as_root cp "${SCRIPT_DIR}/deploy/nginx/drive-unix.conf" /etc/nginx/sites-available/drive-unix.conf
  fi

  echo -e "\n${GREEN}======================================================================${NC}"
  echo -e "${GREEN}${BOLD}  🎉 drive-unix 生產級 VPS 伺服器環境已成功安裝並配置完畢！          ${NC}"
  echo -e "${GREEN}======================================================================${NC}"
  echo -e "接下來可使用統一指令管理服務：\n"
  echo -e "   - 啟動全套服務:     ${CYAN}./scripts/deploy.sh start${NC}  (或 sudo systemctl enable --now drive-unix.target)"
  echo -e "   - 檢查系統健康度:   ${CYAN}./scripts/deploy.sh healthcheck${NC}"
  echo -e "   - 查詢服務運行狀態: ${CYAN}./scripts/deploy.sh status${NC}"
  echo -e "   - 查看即時日誌:     ${CYAN}./scripts/deploy.sh logs${NC}"
  echo -e "   - 控制台直接訪問:   ${GREEN}http://<伺服器_IP>:8000${NC}\n"
}

# [Help Guide]
show_help() {
  echo -e "${CYAN}======================================================================${NC}"
  echo -e "${CYAN}${BOLD}       drive-unix Production Deployment & Management Script            ${NC}"
  echo -e "${CYAN}======================================================================${NC}"
  echo -e "Detected Mode: ${GREEN}${MODE}${NC}"
  echo -e "Target Host:   ${GREEN}${HOST}${NC}"
  echo -e "Target Port:   ${GREEN}${PORT}${NC}"
  echo -e "Config Dir:    ${GREEN}${CONFIG_DIR}${NC}"
  echo -e ""
  echo -e "${BOLD}Usage:${NC}"
  echo -e "  $0 <command>"
  echo -e ""
  echo -e "${BOLD}Subcommands:${NC}"
  echo -e "  ${YELLOW}setup-vps${NC}    Bootstrap full Ubuntu/Debian VPS environment (apt, uv, venv, systemd, nginx)"
  echo -e "  ${YELLOW}build${NC}        Build Docker image or set up Python venv with dependencies"
  echo -e "  ${YELLOW}start${NC}        Start services in background (docker-compose, systemd, or nohup venv)"
  echo -e "  ${YELLOW}stop${NC}         Gracefully stop running services"
  echo -e "  ${YELLOW}restart${NC}      Gracefully restart services"
  echo -e "  ${YELLOW}status${NC}       Display service status (containers, systemd unit, or venv PID)"
  echo -e "  ${YELLOW}healthcheck${NC}  Probe http://${HOST}:${PORT}/api/health with retry loop"
  echo -e "  ${YELLOW}logs${NC}         Stream live application logs (docker, systemd, or local file)"
  echo -e "  ${YELLOW}help${NC}         Display this help message"
  echo -e ""
  echo -e "${BOLD}Environment Variables:${NC}"
  echo -e "  ${CYAN}DEPLOY_MODE${NC}              Override mode (docker | systemd | venv)"
  echo -e "  ${CYAN}DRIVE_UNIX_HOST${NC}          Server host/IP (default: 127.0.0.1)"
  echo -e "  ${CYAN}DRIVE_UNIX_PORT${NC}          Server port (default: 8000)"
  echo -e "  ${CYAN}DRIVE_UNIX_CONFIG_DIR${NC}    Config directory (default: ~/.config/drive-unix)"
  echo -e "  ${CYAN}DRIVE_UNIX_DEBUG_DIR${NC}     Debug directory (default: ~/.config/drive-unix/debug)"
  echo -e "  ${CYAN}HEALTHCHECK_MAX_RETRIES${NC}  Healthcheck retry limit (default: 10)"
  echo -e "  ${CYAN}HEALTHCHECK_INTERVAL${NC}     Seconds between healthcheck probes (default: 2)"
  echo -e "  ${CYAN}NO_COLOR${NC}                 Disable colored output (1 to disable)"
  echo -e "${CYAN}======================================================================${NC}"
}

# ------------------------------------------------------------------------------
# 5. CLI Dispatcher
# ------------------------------------------------------------------------------
ACTION="${1:-}"
shift || true

case "${ACTION}" in
  setup-vps|setup|init-vps)
    do_setup_vps "$@"
    ;;
  build)
    do_build "$@"
    ;;
  start)
    do_start "$@"
    ;;
  stop)
    do_stop "$@"
    ;;
  restart)
    do_restart "$@"
    ;;
  status)
    do_status "$@"
    ;;
  healthcheck)
    do_healthcheck "$@"
    ;;
  logs|log)
    do_logs "$@"
    ;;
  help|--help|-h|"")
    show_help
    if [ -z "${ACTION}" ]; then
      exit 1
    else
      exit 0
    fi
    ;;
  *)
    log_error "Unknown command: '${ACTION}'"
    echo ""
    show_help
    exit 1
    ;;
esac
