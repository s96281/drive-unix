# 02 Remote 與各 Provider 設定

[← 手冊目錄](README.md) | [← 上一章](01-getting-started.md) | [下一章 →](03-browse-and-manage-files.md)

本章內容：

- # 5. Remote 管理
- # 6. 各 Provider 設定
- # 18. Secret 與認證資料

---

## 5. Remote 管理

Remote 是一個命名的 Storage Provider 設定。

### 5.1 新增 Remote

互動式：

```bash
drive-unix remote add
```

直接指定 Provider：

```bash
drive-unix remote add local
drive-unix remote add google-drive
drive-unix remote add onedrive
drive-unix remote add onedrive-business
drive-unix remote add sharepoint
drive-unix remote add sftp
drive-unix remote add ftp
drive-unix remote add webdav
```

指定名稱：

```bash
drive-unix remote add local --name laptop
```

Provider alias 也支援：

```text
sp
odb
gdrive
google_drive
onedrive_business
```

建議新使用者使用 Wizard，而不是直接編輯 `config.toml`。

### 5.2 列出 Remote

```bash
drive-unix remote list
```

顯示額外診斷資訊：

```bash
drive-unix remote list --verbose
```

`--verbose` 會顯示目前實際讀取的設定檔路徑。

### 5.3 測試 Remote

只測試認證與讀取：

```bash
drive-unix remote test work
```

同時測試寫入：

```bash
drive-unix remote test work --write
```

遇到 Provider 登入、權限或路徑問題時，應優先執行這個命令，而不是直接反覆執行 sync。

### 5.4 重新命名

```bash
drive-unix remote rename old-name new-name
```

如果舊名稱是預設 Remote，預設 Remote 名稱會一起更新。

### 5.5 編輯 Remote

目前 `remote edit` 主要提供 SharePoint / OneDrive Business / WebDAV 這類帳號型設定的共用欄位：

```bash
drive-unix remote edit work --base-url https://example.com

drive-unix remote edit work --site /sites/project

drive-unix remote edit work --email user@example.com
```

更新密碼有三種方式，三者只能擇一：

```bash
## 綁定環境變數
drive-unix remote edit work --password-env WORK_PASSWORD

## 終端機隱藏輸入
drive-unix remote edit work --password-prompt

## 移除現有 password reference
drive-unix remote edit work --clear-password
```

修改後建議：

```bash
drive-unix remote test work
```

> `remote edit` 並不是所有 Provider 所有欄位的通用 editor。像 SFTP host/key、Google credentials、OneDrive Client ID 等結構性設定，現階段較適合移除後重新建立 Remote，或由熟悉設定格式的使用者手動管理設定檔。

### 5.6 移除 Remote

```bash
drive-unix remote remove work
```

這會移除 Remote 設定與由該 Remote 管理的 secret reference；**不會刪除 Remote 上的檔案**。

---

## 6. 各 Provider 設定

### 6.1 Local

```bash
drive-unix remote add local --name laptop
```

Wizard 會詢問本機根目錄，例如：

```text
D:\Data
/home/user/data
/Users/user/Documents
```

Local Remote 的刪除屬於**永久刪除**，沒有 drive-unix 回收桶。

舊版直接命令仍可使用：

```bash
drive-unix add-local laptop D:\Data
```

若路徑尚不存在，舊命令會要求確認；也可以：

```bash
drive-unix add-local future D:\Future --allow-missing
```

### 6.2 Google Drive

先安裝：

```bash
uv sync --extra google
```

準備 Google Cloud OAuth `credentials.json`，然後：

```bash
drive-unix remote add google-drive --name gdrive
```

Wizard 會要求 OAuth credentials JSON 路徑。檔案會複製到 drive-unix 管理的 secret-files 位置。

第一次實際存取，例如：

```bash
drive-unix ls gdrive:/
```

會觸發瀏覽器 OAuth 登入。

Google Drive 支援回收桶，也可要求永久刪除：

```bash
drive-unix rm gdrive:/old/file.txt
drive-unix rm gdrive:/old/file.txt --permanent
```

### 6.3 Microsoft OneDrive

安裝：

```bash
uv sync --extra onedrive
```

需要 Microsoft Entra / Azure AD 應用程式 Client ID。

```bash
drive-unix remote add onedrive --name personal
```

Wizard 會詢問：

- Client ID
- Tenant，預設 `common`
- 是否設定 Client Secret

應用程式 redirect URI 需設定：

```text
http://localhost:8080
```

第一次使用會進行瀏覽器授權。

目前 Microsoft Graph OneDrive adapter 的刪除語意是**移至回收桶**；不支援 `--permanent`：

```bash
## 可用
drive-unix rm personal:/old.txt

## 會被拒絕
drive-unix rm personal:/old.txt --permanent
```

### 6.4 SharePoint

安裝：

```bash
uv sync --extra sharepoint
uv run playwright install chromium
```

建立：

```bash
drive-unix remote add sharepoint --name work-sp
```

需要：

- SharePoint root URL，例如 `https://tenant.sharepoint.com`
- Site path，例如 `/sites/project`
- Email
- Password

密碼不會直接寫進 `config.toml`。

SharePoint 支援回收桶與永久刪除。

### 6.5 OneDrive Business

與 SharePoint 使用同一組 browser-auth optional dependency：

```bash
uv sync --extra sharepoint
uv run playwright install chromium
```

建立：

```bash
drive-unix remote add onedrive-business --name work-drive
```

需要：

- OneDrive Business root URL
- Email
- 個人 site path；可留空讓系統自動解析
- Password

支援回收桶與永久刪除。

### 6.6 SFTP

安裝：

```bash
uv sync --extra sftp
```

目前建議透過 Wizard 建立：

```bash
drive-unix remote add sftp --name server
```

會詢問：

- Host
- Port，預設 `22`
- Username
- SSH private key path，可留空
- 若未指定 key，可使用 password authentication
- Remote root path，預設 `/`

SFTP 刪除屬於**永久刪除**。

### 6.7 FTP / FTPS

```bash
drive-unix remote add ftp --name ftp-server
```

Wizard 會詢問：

- Host
- Port，預設 `21`
- Username，預設 `anonymous`
- 非 anonymous 時輸入 password
- 是否啟用 FTPS / TLS
- Root path

舊版直接命令範例：

```bash
drive-unix add-ftp ftp-server ftp.example.com \
  --port 21 \
  --user backup \
  --password-env FTP_PASSWORD \
  --tls \
  --root /backup
```

FTP / FTPS 刪除屬於**永久刪除**。

### 6.8 WebDAV

```bash
drive-unix remote add webdav --name nas
```

需要：

- WebDAV URL
- Username
- Password

例如：

```text
https://nas.example.com:5006
```

WebDAV 刪除屬於**永久刪除**。

### 6.9 Provider 能力摘要

| Provider | 刪除模式 | Provider `search` | `download-link` | 額外套件 |
|---|---|---:|---|---|
| Local | 永久 | 有 | 無 | 無 |
| Google Drive | 回收桶 + 永久 | 有 | 無 | `google` |
| OneDrive | 回收桶 | 有 | Provider 管理的下載 URL | `onedrive` |
| OneDrive Business | 回收桶 + 永久 | 有 | Provider 管理的下載 URL | `sharepoint` |
| SharePoint | 回收桶 + 永久 | 有 | Provider 管理的下載 URL | `sharepoint` |
| SFTP | 永久 | 無 | 無 | `sftp` |
| FTP / FTPS | 永久 | 無 | 直接 URL，可能包含帳密 | 無 |
| WebDAV | 永久 | 無 | 直接 URL，可能包含帳密 | 無 |

> `find` 是 client-side recursive search，設計上可用於所有 Provider；`search` 則依賴 Provider 原生搜尋能力。

---

## 18. Secret 與認證資料

`config.toml` 不應保存明文 password / client secret，而是保存 reference。

Reference 可能是：

```text
env:NAME
keyring:key
file:key
```

### 18.1 環境變數

適合 CI / Server：

Linux / macOS：

```bash
export WORK_PASSWORD='...'
drive-unix add-sp work https://tenant.sharepoint.com /sites/work user@example.com \
  --password-env WORK_PASSWORD
```

PowerShell：

```powershell
$env:WORK_PASSWORD = '...'
```

OneDrive Client Secret：

```bash
export ONEDRIVE_SECRET='...'
drive-unix add-onedrive personal CLIENT_ID --secret-env ONEDRIVE_SECRET
```

### 18.2 Interactive Secret

若透過 Wizard 輸入密碼，會優先嘗試 OS keyring。

若系統沒有可用 keyring backend，會 fallback 到權限限制的 local secret store。

### 18.3 設定與 Cache 預設位置

目前版本：

```text
Config directory:
~/.config/mycli/

Config:
~/.config/mycli/config.toml

Fallback secret store:
~/.config/mycli/secrets.json

Managed credential files:
~/.config/mycli/secret-files/

Authentication cache:
~/.auth_cache/
```

> 目錄名稱 `mycli` 是目前實作保留的歷史路徑。不要假設未來版本一定不會遷移；需要診斷時使用 `drive-unix remote list --verbose` 取得實際 config path。

---

[← 手冊目錄](README.md)
