#!/usr/bin/env bash
# ==============================================================================
# drive-unix VPS 一鍵安裝轉接腳本 (Backward Compatibility Wrapper)
#
# 說明:
#   為保持專案指令與維運入口單一化 (Single Source of Truth)，
#   本腳本已統一委派轉接至核心維運腳本: scripts/deploy.sh setup-vps
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "${SCRIPT_DIR}/scripts/deploy.sh" ]; then
  exec "${SCRIPT_DIR}/scripts/deploy.sh" setup-vps "$@"
else
  echo "❌ 找不到核心腳本 ${SCRIPT_DIR}/scripts/deploy.sh" >&2
  exit 1
fi
