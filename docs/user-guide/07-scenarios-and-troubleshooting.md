# 07 常見情境與錯誤排查

[← 上一章](06-command-reference.md) | [手冊目錄](README.md)

## 7.1 常見情境

### 7.1.1 新手第一次接 Google Drive

```bash
uv sync --extra google
drive-unix remote add google-drive --name gdrive
# 在 Wizard 按提示貼上 credentials.json 路徑，瀏覽器完成 OAuth
drive-unix remote test gdrive
drive-unix ls gdrive:/
```

### 7.1.2 Laptop 本機資料備份到雲端

```bash
drive-unix remote add local --name laptop
# （gdrive 已在上一節建好）
drive-unix diff laptop:/docs gdrive:/docs
drive-unix sync laptop:/docs gdrive:/docs --dry-run --full-plan
drive-unix sync laptop:/docs gdrive:/docs --yes
```

### 7.1.3 定時夜間備份

```bash
drive-unix schedule add nightly '0 2 * * *' 'sync local:/data cloud:/backup --yes'
drive-unix schedule service install
drive-unix schedule service start
drive-unix schedule service status
# 重開機後可查 ~/.config/mycli/scheduler/scheduler.log
```

### 7.1.4 找百份 PDF、跨廠商查同一檔名

```bash
# 本機遞迴找（任何 Provider 都可用）
drive-unix find work:/ --name '*.pdf' --type file --max-depth 5
# Provider 原生搜尋（支援時更快）
drive-unix search gdrive:/ invoice
```

### 7.1.5 換一台電腦還要能登入

```bash
# 舊電腦
drive-unix env export backup.zip
# 新電腦：先裝依賴，再匯入
uv sync --extra all
drive-unix env import backup.zip --force
drive-unix remote test work
```

憑證不要用這個流程傳（除非你把 `--include-secrets` 的檔案視為高敏感並經加密通道傳遞）。

### 7.1.6 VPS 第二台機器當換發中心

需求：VPS 幫多台自動換 token（完全見 [VPS Token 換發中心](../vps-deployment-token-center.md)）。

```bash
uv sync --extra all
# 設好 UPSTASH_REDIS_REST_URL / TOKEN（或用 upstash config）
drive-unix upstash renew-tokens --interval 1800 --leeway 60 -p 'MySecretPassphrase'
```

## 7.2 錯誤排查

| 症狀 | 可能原因與下一步 |
|---|---|
| `remote test` 顯示讀取失敗 | 帳號 / site / root 設定錯；先 `remote list --verbose` 對路徑，再 `remote test <name>` 細看錯誤訊息。 |
| `search` 報支援錯誤 | Provider 沒有原生搜尋；改用 `find <remote>:/ --name ...`。 |
| `rm --permanent` 被拒絕 | Provider 只有回收桶（OneDrive 個人版）；拿掉 `--permanent`。 |
| sync 提示「永久刪除數量」 | 目標端是 Local/SFTP/FTP/WebDAV 且 `--delete` 開了；先 `--dry-run --full-plan`，再決定是否加 `--yes`。 |
| `bisync` exit 2 | 衝突無法判定新舊（`newer` 策略）或 Photos 雙向；改 `auto`/`rename`，或避開 Photos。 |
| `checksum --mode remote` exit 2 | Provider 不提供遠端 hash（例如 FTP）；改 `--mode auto` 或 `--mode download`。 |
| `--json` 執行卡住 | 忘了加 `--yes`；實際執行時的 `--json` 必須搭配 `--yes`。 |
| `=False` 形式的旗標被拒絕 | 布林旗標不要加等號；`--two-way=False` → `--two-way`。 |
| Scheduler 沒跑 | 查 `schedule service status` 與 `~/.config/mycli/scheduler/scheduler.log`；前景版（`schedule start`）不具登入自動啟動能力。 |
| Upstash 密碼錯誤 | passphrase 錯誤或 bundle 損壞；重跑 `upstash config` 即可重置（不會刪雲端資料）；勿把明文 passphrase 寫進腳本。 |

### 7.2.1 能力對照速查

| Provider | 刪除 | `search` | `download-link` | extras |
|---|---|---|---|---|
| Local | 永久 | 有 | `file://` | — |
| Google Drive | 回收桶+永久 | 有 | 有（分享 URL） | `google` |
| Google Photos | 永久（移除連結） | 無 | 有 | `google` |
| OneDrive | 回收桶 | 有 | 有（Graph URL） | `onedrive` |
| SharePoint / ODB | 回收桶+永久 | 有 | 有 | `sharepoint` |
| SFTP | 永久 | 無 | 有（含帳密） | `sftp` |
| FTP | 永久 | 無 | 有（含帳密） | — |
| WebDAV | 永久 | 無 | 有（含帳密） | — |
| PikPak | 回收桶+永久 | 無 | 有 | — |

## 7.3 需要更多幫助

- 機制原理（呼叫鏈、快取、Upstash 分散式鎖、Office 同步）：[docs/mechanisms/](../mechanisms/README.md)
- 伺服器部署（systemd、nginx、SSE、Profile、env）：[DEPLOYMENT](../DEPLOYMENT.md)
- Windows/Linux 跨機部署實務：看 `deploy/` 與 `docker-compose.yml`

> 相容別名：`add-local`、`add-gdrive`、`add-sp`、`add-odb`、`add-ftp`、`add-webdav`、`list-nodes`、`cron-add`、`export-env` 等仍有效，適合舊腳本平滑過渡；新的自動化請逐步改用 `remote` / `schedule` / `env` 子指令。
