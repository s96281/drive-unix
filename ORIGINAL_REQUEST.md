# Original User Request

## 2026-10-22T07:04:10Z

撰寫 `drive-unix` 多雲端儲存管理與同步系統的生產級全方位佈署手冊與完整佈署範本套件，涵蓋 Docker/Docker Compose 容器化、Linux Systemd 常駐守護行程、VPS/NAS 私有雲掛載、Nginx 反向代理 (SSE 串流優化) 及自動化佈署腳本。

Working directory: h:\drive_unix_phase6_ux_polish_with_help\drive_unix_phase6
Integrity mode: development

## Requirements

### R1. 生產級全方位佈署手冊 (`docs/DEPLOYMENT.md`)
編寫結構嚴謹、圖文並茂的繁體中文佈署指南，完整涵蓋以下內容：
1. **系統架構概觀與先決條件**：軟硬體規格需求、Python 3.12+ / Node 18+ / Docker 需求、網路連接埠 (`8000`) 與雲端 API 存取權限。
2. **三種核心佈署拓撲實務**：
   - **方案 A (推薦容器化)**：Docker 與 Docker Compose 快速佈署、Volume 持久化配置。
   - **方案 B (傳統 Linux 服務)**：Systemd 守護行程常駐執行、背景排程器與權限隔離。
   - **方案 C (本機/Windows/輕量執行)**：Python 虛擬環境直接執行、Windows Task Scheduler、前端靜態打包整合。
3. **雲端儲存私有雲 / NAS (Synology / QNAP) 掛載指引**：持久化資料夾權限 (UID/GID)、本機儲存與 WebDAV/SFTP 網路對齊。
4. **反向代理與安全強化**：Nginx / Caddy 反向代理設定、SSL/TLS 憑證 (Let's Encrypt)、SSE 即時事件推播 (`/api/events`) 緩衝區關閉 (`proxy_buffering off`) 與超時設定。
5. **Upstash E2EE 憑證同步與生產密鑰管理**：REST Token、加密主密碼 (Passphrase) 之環境變數與 SecretStore 最佳實踐。
6. **維運、備份與常見問題排錯 (Troubleshooting)**：日誌檢視、Daemon 未啟動、429 速率限制、Token 過期續約失敗之應對方針。

### R2. 生產環境設定檔與範本套件 (`deploy/`)
建立實體、語法嚴謹且開箱即用的設定檔：
1. **`Dockerfile`**：基於 Python 3.12-slim 之多階段建置或最佳化映像檔構建，正確包含後端依賴與 `web/static/` 現代化 Web 控制台靜態資源。
2. **`docker-compose.yml`**：預配置環境變數、配置目錄 Volume 掛載 (`~/.config/drive-unix` 與儲存目標目錄)、容器健全度檢查 (`healthcheck`) 與重啟政策。
3. **`deploy/systemd/drive-unix.service`**：Linux Systemd 服務定義檔，配置自動重啟 (`Restart=always`)、適當使用者權限與環境變數載入。
4. **`deploy/nginx/drive-unix.conf`**：完整之 Nginx 虛擬主機設定檔，包含靜態資源快取、FastAPI API 轉發、以及特別針對 `/api/events` (SSE) 關閉快取緩衝的正確代理標頭。
5. **`.env.production.example`**：列出所有可用的生產環境變數範例（伺服器主機、連接埠、Upstash 憑證、限速與工作緒預設值）。

### R3. 自動化安裝與維護腳本 (`scripts/deploy.sh`)
提供具備防呆機制的 Shell 腳本，支援：
1. 自動偵測環境（Docker / Systemd / Python）。
2. 初始化必要之設定目錄與權限。
3. 支援一鍵建置/啟動、服務健康狀態檢查與停止重啟指令。

### R4. 與現有 Codebase 嚴格對齊
手冊內的所有命令、模組呼叫 (`python -m web`)、預設埠號 (`8000`)、端點命名 (`/api/events`, `/api/remotes` 等)、靜態目錄位置 (`web/static/`) 與資料庫設定必須與目前倉庫完全一致，絕不憑空捏造無效指令。

---

## Acceptance Criteria

### 文件與文檔結構
- [ ] 產出繁體中文 `docs/DEPLOYMENT.md`，內容結構完整包含架構圖 (Mermaid)、方案比較、逐步指令、設定檔註解與排錯指南。
- [ ] 手冊中詳細說明 `/api/events` SSE 傳輸於反向代理時必須關閉 buffering 的技術原因與確切設定。

### 設定檔與腳本驗證
- [ ] 專案根目錄或 `deploy/` 下存在可用的 `Dockerfile` 與 `docker-compose.yml`，YAML 語法經檢驗無語法錯誤。
- [ ] 存在 `deploy/systemd/drive-unix.service`，具備完整的服務定義、使用者指派與重啟設定。
- [ ] 存在 `deploy/nginx/drive-unix.conf`，明確定義 `/api/events` 關閉 `proxy_buffering` 與自訂逾時時間。
- [ ] 存在 `.env.production.example`，涵蓋伺服器、安全與快取參數。
- [ ] 存在 `scripts/deploy.sh`，通過 `bash -n` 語法檢驗，包含 `set -e` 錯誤中斷與防呆引導。

### 系統對齊與無害性
- [ ] 所有設定檔與手冊範例之埠號、路徑與指令皆與目前 codebase 吻合。
- [ ] 既有程式碼 (`web/`, `application/`, `core/`, `frontend/`) 未受到破壞，既有單元測試維持全綠。
