# drive-unix

多 Provider 檔案管理與同步 CLI + Web 介面。以一致的 `REMOTE:/path` 語法操作 Local、FTP/FTPS、SFTP、WebDAV、SharePoint、OneDrive、OneDrive Business、Google Drive、Google Photos、PikPak 等儲存後端，支援單向／雙向同步、跨 Provider 傳輸、排程與端對端加密多端同步。

> 正式支援 **Python 3.12+**（CI 覆蓋 3.12 / 3.13 / 3.14）。

## 文件

| 文件 | 內容 |
|---|---|
| [完整使用手冊](docs/user-guide.md) | 安裝、Provider 設定、命令參考、同步安全模型、排程、自動化與錯誤排查 |
| [機制文件總覽](docs/mechanisms/README.md) | 全機制分門別類說明與流程圖（系統總覽、驗證、Provider、傳輸/同步、排程、Upstash、Web、CLI、基礎設施、維運） |
| [架構筆記](docs/architecture.md) | 分階段架構變更與決策紀錄 |
| [部署指南](docs/DEPLOYMENT.md) | Web / renew 部署、systemd unit、profile 與 env 設定 |
| [VPS Token 換發中心](docs/vps-deployment-token-center.md) | 將 VPS 設為憑證換發中心的操作教學 |

對機制有興趣者請直接讀 **[docs/mechanisms/](docs/mechanisms/README.md)**，每章皆附 Mermaid 流程圖。

## 快速開始

```bash
python -m pip install .
drive-unix --help
```

第一次使用建議從互動導引開始：

```bash
drive-unix init
drive-unix remote list
drive-unix remote test work
drive-unix ls work:/
```

或直接以新版 task-oriented CLI 管理 Remote：

```bash
drive-unix remote add
drive-unix remote add local --name laptop
drive-unix remote add google-drive --name gdrive
drive-unix remote list
drive-unix remote test work
```

### 同步範例

```bash
# 先預覽計畫，再正式執行
drive-unix sync local:/docs cloud:/backup --dry-run
drive-unix sync local:/docs cloud:/backup

# 鏡像（刪除目標端多餘項目）
drive-unix sync local:/docs cloud:/backup --delete --dry-run

# 雙向同步
drive-unix bisync laptop:/docs cloud:/docs --dry-run
drive-unix bisync laptop:/docs cloud:/docs
```

`sync --two-way` 仍可使用以維持相容；新腳本建議用 `bisync`。雙向同步預設 `--conflict auto`：時間能安全判定時取較新版本，無法判定時先保留衝突版本，不隱式選擇第一個參數。

可用 conflict 策略：`auto` / `newer` / `rename` / `abort` / `prefer-source` / `prefer-destination`（`abort` 與 `prefer-destination` 僅適用雙向）。

### 跨 Provider 傳輸

```bash
drive-unix cp work:/docs/A.pdf backup:/archive/A.pdf
drive-unix mv work:/docs/A.pdf nas:/archive/A.pdf
drive-unix upload ./report.pdf work:/docs/report.pdf
drive-unix download work:/docs/report.pdf ./downloads/
```

### 排程

```bash
drive-unix schedule add nightly '0 2 * * *' 'sync local:/data cloud:/backup --yes'
drive-unix schedule list
drive-unix schedule service install   # Linux systemd / macOS LaunchAgent / Windows Task Scheduler
drive-unix schedule service start
drive-unix schedule service status
```

### Upstash 雲端同步（E2EE）

```bash
drive-unix upstash config
drive-unix upstash test
drive-unix upstash push -p 'MySecretPassphrase'
drive-unix upstash status
drive-unix upstash pull -p 'MySecretPassphrase' --dry-run
drive-unix upstash pull -p 'MySecretPassphrase'

# 憑證主動續期（常用於 VPS 常駐）
drive-unix upstash renew-tokens --interval 1800 --leeway 60
```

## 主要功能

- **多 Provider**：Local、FTP/FTPS、SFTP、WebDAV、SharePoint、OneDrive、OneDrive Business、Google Drive、Google Photos、PikPak（AList 類型保留、尚未實作）。
- **瀏覽與搜尋**：`ls`／`tree`／`find`（client-side 遞迴）／`search`（Provider 原生）、`stat`、分頁與背景預熱。
- **檔案操作**：`mkdir`／`rm`／`cp`／`mv`／`upload`／`download`／`download-link`，跨 Provider 橋接傳輸與批次併發。
- **同步**：`sync`（單向＋可選 `--delete` 鏡像）、`bisync`（雙向）、`diff`（預檢）、`checksum`（Provider-side／下載後計算、`quickXorHash`）。
- **刪除安全模型**：各 Provider 明確宣告 `DeleteCapability`；Local／FTP／SFTP／WebDAV 為永久刪除，Google／Microsoft 365 支援回收桶，同步計畫會標示永久刪除數量。
- **排程**：內建 5 欄 Cron、missed-run 補執行、OS 級背景 service（systemd／launchd／Task Scheduler）、missed-run 上限 7 天。
- **Upstash 多端同步**：設定 Bundle E2EE 同步（`merge`／`replace`）、per-identity Token 細粒度同步、分散式鎖避免多機換發競態、VPS 換發中心。
- **Web 介面**：FastAPI + SPA，含目錄瀏覽、連線池、兩級目錄快取、傳輸／同步背景任務、SSE 即時進度、遠端管理、排程與 Upstash 管理。
- **自動化**：`--json`、`--plain`／`NO_COLOR`、exit code 語意、受控確認（實際 sync 的 `--json` 須搭配 `--yes`）。

### Web 介面

```bash
python -m web          # 啟動 FastAPI（詳細參數見 docs/DEPLOYMENT.md）
```

Web 提供（`/api/health` 健康檢查、`docs_url=/docs`）：

| 前綴 | 範圍 |
|---|---|
| `/api/fs` | 瀏覽、stat、mkdir/delete、上傳／下載、跨節點傳輸 |
| `/api/remotes` | 節點 CRUD、連線測試、容量 |
| `/api/sync` | 同步計畫預檢、背景執行、SSE 進度、暫停／恢復／重試／取消 |
| `/api/schedule` | Cron 任務 CRUD、daemon 啟停與狀態、立即執行 |
| `/api/settings` | 快取／連線池維運、登入除錯截圖與 MFA 狀態 |
| `/api/upstash` | 雲端同步設定、push/pull、Token 查看與手動續期 |
| `/api/events` | 全域 SSE 事件（hello replay + heartbeat） |

## 架構

```text
CLI / Web UI
  -> Application (transfer / sync / scheduling / upstash)
      -> Domain (scanner / planner / SyncPlan batches)
      -> Storage (contract + Provider Registry)
          -> Providers (local / ftp / sftp / webdav / ms365 / google / pikpak)
      -> Infrastructure (HTTP / Retry / RateLimiter / BandwidthLimiter / Crypto / UpstashClient)
      -> Auth (CachedAuthProvider -> AuthCache + Upstash Token + Browser Profile)
```

主要模組：

- `cli/`：Typer 指令樹、Rich presentation
- `application/`：同步、跨 Provider 傳輸、排程、Upstash 同步／Token 換發
- `domain/`：`FileItem`、`SyncSnapshot`、`SyncPlanner`、`SyncPlan`（9 種動作與 batches 依賴屏障）
- `storage/`：`StorageProvider` contract、`ProviderRegistry`
- `providers/`：各儲存後端實作
- `web/`：FastAPI、連線池、目錄快取、SSE 事件、傳輸 Job、限速
- `infrastructure/`：HTTP client、RetryPolicy、RateLimiter、UpstashClient
- `auth/`：canonical identity、AuthCache、OAuth／Cookie 驗證、per-identity browser profile
- `core/`：設定（`config.toml` + secret reference）、E2EE 加密、路徑與常數

細部機制與流程圖見 **[機制文件](docs/mechanisms/README.md)**。

## 核心設計原則

1. **一個 identity、三層憑證**：Browser Profile → 本機 `AuthCache` → Upstash E2EE Token；同一身份禁止共用 Profile。
2. **設定只存 reference**：`config.toml` 不存明文，密碼／secret 以 `env:`／`keyring:`／`file:` 引用，Provider 建立時才解析。
3. **計畫與執行分離**：`scan → build_plan → execute`；計畫以 batches 做依賴屏障，批次內併發、批次間嚴格順序，失敗即略過後續。
4. **同 Remote 直通、跨 Remote 橋接**：同節點直接 `copy`／`move`，跨節點經暫存檔橋接，move 先寫成功才刪來源。
5. **Pool + Cache 是 Web 效能核心**：連線池復用、兩級目錄快取（記憶體 + SQLite）、寫入後精確失效。
6. **零信任雲端**：Upstash 只見 AES-256-GCM 密文，metadata 僅含非敏感統計；Token 換發以分散式鎖協調。

## Provider extras

核心安裝不會強制所有大型 SDK：

```bash
# Google Drive / Google Photos
python -m pip install '.[google]'

# SFTP
python -m pip install '.[sftp]'

# SharePoint / OneDrive Business (Playwright)
python -m pip install '.[sharepoint]'
playwright install chromium

# OneDrive OAuth
python -m pip install '.[onedrive]'

# 全部
python -m pip install '.[all]'
```

使用 uv 時以 `pyproject.toml` 為源：`uv sync`、`uv run drive-unix --help`、`uv sync --extra google` 等；一次全開可用 `uv sync --all-extras`。

缺少 extra 時 Provider factory 會提示應安裝的 `drive-unix[...]`。

## 憑證與 Secret

`config.toml` 不保存密碼或 Client Secret 明文，只保存 secret reference。CLI 不接受 `--password <明文>`；互動輸入走 hidden prompt，自動化用 `--password-env`／`--secret-env`。

```bash
export WORK_SP_PASSWORD='...'
drive-unix remote add sharepoint --name work --password-env WORK_SP_PASSWORD
```

- 優先使用 OS keyring；無可用 backend 時 fallback 至 `0600` 的 `secrets.json`（目錄 `0700`）。
- 舊版明文會在首次載入時自動遷移到 secret store 並原子重寫設定。
- `env export` 預設排除 secret store、OAuth 憑證檔與登入快取；可攜式備份須明確加 `--include-secrets`／`--include-auth-cache`，視為憑證妥善保管。

## 開發與驗證

```bash
python -m pip install -e '.[all,dev]'
python -m compileall -q application auth cli core domain infrastructure providers storage main.py
ruff check .
mypy
python -m pytest
```

或使用 uv：

```bash
uv sync --extra all --extra dev
uv run python -m compileall -q application auth cli core domain infrastructure providers storage main.py
uv run ruff check .
uv run mypy
uv run python -m pytest
```

依賴版本只維護在 `pyproject.toml`（`requirements*.txt` 僅為舊流程相容墊片）。GitHub Actions 會在 Python 3.12／3.13／3.14 執行 compile、Ruff、mypy 與 pytest，並驗證 wheel／sdist 打包中繼資料。
