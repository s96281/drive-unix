# 02 Remote 與各 Provider 設定

[← 上一章](01-getting-started.md) | [手冊目錄](README.md) | [下一章 →](03-browse-and-manage-files.md)

> 本章目標：把每個 Remote 接好、測通，並理解「密碼從不寫進 config.toml」這條規則。接好 Remote 之後，後續章節的指令都是直接用 `別名:/路徑` 操作。

## 2.1 Remote 管理

### 2.1.1 建議入口：互動 wizard

```bash
drive-unix remote add          # 問你選擇 Provider，再逐欄詢問
drive-unix remote add local --name laptop    # 一次把名稱給齊
drive-unix remote add google-drive --name gdrive
```

`remote add` 的參數：

- 位置參數 `[provider_or_name]`：可給 Provider 類型（`local`、`google-drive`、`sharepoint`…），或給一個尚未建立的 Remote 名稱（會反問你要哪種 Provider）。
- `--name / -n`：Remote 別名。省略時 wizard 會幫你建議。
- `--type / -t`：Provider 類型（與上列交互用）。

支援的 `remote add` 類型與別名：`local`、`google-drive`（`gdrive`）、`google-photos`（`gphotos`/`photos`）、`onedrive`、`onedrive-business`（`odb`）、`sharepoint`（`sp`）、`sftp`、`ftp`、`webdav`、`pikpak`。連字號與底線混寫（`google_drive` / `google-drive`）都接受，內部一律正規化為 `google_drive`、`onedrive_business` 等 canonical 名。

`init` 指令的關係：`drive-unix init` 在「已有 Remote」時只列舉提示，在「一個都沒有」時等同跑一次 wizard。兩者擇一即可。

### 2.1.2 列舉、改名、刪除

```bash
drive-unix remote list           # 列全部 Remote（永不印出 secret）
drive-unix remote list -v        # 附帶 config 檔路徑，方便手動修檔
drive-unix remote rename old new
drive-unix remote remove work
```

注意：`remote remove` 只移除設定檔裡的 Remote 與它持有的 secret ref，**不刪除遠端上的資料**。要刪遠端檔案請改用 `rm`（見 [第三章](03-browse-and-manage-files.md)）。

### 2.1.3 修改既有 Remote

```bash
# 改 URL / 範圍 / Email
drive-unix remote edit work --base-url https://other.sharepoint.com --site /sites/new

# 換密碼：三者只能擇一（環境變數引用 / 終端隱藏輸入 / 清除引用）
drive-unix remote edit work --password-env WORK_PASSWORD
drive-unix remote edit work --password-prompt
drive-unix remote edit work --clear-password
```

`remote edit` 只支援一小部分欄位（`base-url`、`site`、`email`、密碼三選一）。像 SFTP Host/Key、Google credentials 檔、OneDrive Client ID 這類結構性欄位，目前比較可靠的做法是 `remove` 後重建；也可以由熟悉 TOML 格式的人直接改 `config.toml`。

**何時不必改用手動修檔：** 如果只是換密碼，優先用 `--password-env`，避免把明文寫進 shell history。

### 2.1.4 測試連線

```bash
drive-unix remote test work           # 驗證認證 + 能成功 list 根目錄
drive-unix remote test work --write   # 再額外建一個暫存目錄、寫入、刪除，證明能寫入
```

手冊中所有範例彙整了 `--write` 的常見用途：你在 SharePoint/ADB 換密碼或改 site 路徑後，先跑一次 `--write` 比只跑 `ls` 更穩妥。

## 2.2 各 Provider 設定

> 通用：CLI 從不接受 `--password 明文`。互動時用 hidden prompt，自動化用 `--password-env VAR`（`VAR` 須先存在且非空）或 `--secret-env VAR`。

### 2.2.1 Local（本機目錄）

```bash
uv sync --extra speedups   # 選配：fuzzy 搜尋加速
drive-unix remote add local --name laptop
```

Wizard 會問本機根目錄，例如 `D:\Data`、`/home/user/data`。刪除是**永久刪除**，沒有回收桶。

### 2.2.2 Google Drive / Google Photos

```bash
uv sync --extra google
drive-unix remote add google-drive --name gdrive
drive-unix remote add google-photos --name photos
```

需要 Google Cloud OAuth `credentials.json` 檔。Wizard 會讓你填該檔路徑；檔案會複製到 `config/secret-files/` 由 drive-unix 管理。第一次 `ls gdrive:/` 會跳瀏覽器登入。

能力：Drive 支援回收桶 + `--permanent` 永久刪除；Photos 只有永久移除連結的概念。Drive 有原生 `search` 與分享連結；Photos 沒有 `search`（請改用 `find`），但有 preview 連結。

### 2.2.3 Microsoft OneDrive（個人版）

```bash
uv sync --extra onedrive
drive-unix remote add onedrive --name personal
```

必填：Microsoft Entra Client ID；可選：Tenant（預設 `common`）、Client Secret。App 的 redirect URI 須填 `http://localhost:8080`。

刪除語意：**只能進回收桶**，不支援 `--permanent`（加了會報錯）。

### 2.2.4 SharePoint / OneDrive Business（組織版）

```bash
uv sync --extra sharepoint
uv run playwright install chromium
drive-unix remote add sharepoint --name work
drive-unix remote add onedrive-business --name work-drive
```

- SharePoint 必填：`base_url`（如 `https://tenant.sharepoint.com`）、`site`（如 `/sites/project`）、`email`、`password_ref`。
- OneDrive Business 必填：`base_url`、`email`、`password_ref`；`site` 可留空，系統會從 `/my` 自動解析個人站點。

兩者都走 Playwright 瀏覽器登入，支援回收桶 + 永久刪除。登入狀態會存在每台 identity 獨立的 browser profile；同一台帳號的換發不可並行執行（profile 會鎖），排程請錯開時間。

### 2.2.5 SFTP

```bash
uv sync --extra sftp
drive-unix remote add sftp --name server
```

Wizard 依序詢問：Host、Port（預設 22）、Username、SSH key 路徑（可空）、密碼（未給 key 才需）、Remote root（預設 `/`）。免密金鑰與密碼任給其一即可，兩者都沒有會報錯。

刪除是**永久刪除**。`download-link` 會產生形如 `sftp://user:密碼@host:port/path` 的連結，**內含明文密碼**，不要公開傳播。

### 2.2.6 FTP / FTPS

```bash
drive-unix remote add ftp --name ftp-server
```

Wizard 依序詢問：Host、Port（預設 21）、Username（預設 `anonymous`）、密碼（非 anonymous 才需）、是否啟用 TLS、Root path。匿名帳號可免密碼。

刪除是**永久刪除**。`download-link` 會自動產生含帳密的 `ftp://` URL，風險同上。

### 2.2.7 WebDAV（NAS、群暉等）

```bash
drive-unix remote add webdav --name nas
```

必填：`base_url`（如 `https://nas.example.com:5006`）、`username`；密碼可選。群暉會要求使用者名稱與密碼；若伺服器是免密分享，也可不填密碼。

刪除是**永久刪除**。

### 2.2.8 能力對照表（精簡版）

完整刪除語意、Provider extras 與搜尋/連結能力總表，另見本章附錄的說明文字；日常判斷只要記三條：

1. Local / SFTP / FTP / WebDAV 的 `rm` 是**永久**（「沒回收桶」，刪了就回不來）。
2. Google Drive / SharePoint / ODB / PikPak 可**回收桶或永久**（視是否加 `--permanent`）。
3. OneDrive（個人版）**只能回收桶**；Google Photos 是移除連結。

> `search` 是否可用，看 Provider 有無原生搜尋 API：
> Local、Google Drive、OneDrive（個人版）、SharePoint、ODB 有；SFTP、FTP、WebDAV、PikPak、Photos 沒有（請改用 `find`）。

## 2.3 密碼為什麼不進 config.toml

`config.toml` 只存 secret **引用**，不存明文。引用有三種寫法：

| 引用 | 來源 | 適合情境 |
|---|---|---|
| `env:VAR` | 環境變數 `VAR` | 伺服器、CI、可攜 |
| `keyring:remote/<名稱>/<欄位>` | OS 憑證庫（首選） | 個人電腦 |
| `file:<key>` | 同目錄 `secrets.json`（`0600` 後備） | 無 keyring 的 headless 環境 |

`remote add --password-env` 會把 TOML 裡的欄位寫成 `env:VAR`，而不是把值抄進檔案。密文值本身放在 keyring 或 `secrets.json`。Google `credentials.json` 這類檔案證則放在 `secret-files/`。

舊版明文（`password` / `client_secret` 欄位）會在第一次載入時自動遷移到 secret store 並重寫設定檔，不用手動處理。

舊版的直供指令（`add-local`、`add-gdrive`、`add-sp`…）仍可用作相容別名，參數與 `remote add` 幾乎相同，但不會出現在 root help。新建 Remote 一律建議用 `remote add`。
