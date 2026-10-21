# drive-unix 完整使用手冊

> 適用版本：`drive-unix 0.1.0`（Phase 6 UX/Safety/Polish 版本）
>
> `drive-unix` 是一套多 Provider 檔案管理與同步 CLI，可用一致的命令操作 Local、Google Drive、OneDrive、OneDrive Business、SharePoint、SFTP、FTP/FTPS 與 WebDAV。

---

## 目錄

1. [功能概覽](#1-功能概覽)
2. [安裝](#2-安裝)
3. [第一次使用](#3-第一次使用)
4. [命令與路徑基本規則](#4-命令與路徑基本規則)
5. [Remote 管理](#5-remote-管理)
6. [各 Provider 設定](#6-各-provider-設定)
7. [瀏覽、搜尋與資訊查詢](#7-瀏覽搜尋與資訊查詢)
8. [建立與刪除](#8-建立與刪除)
9. [複製、移動、上傳與下載](#9-複製移動上傳與下載)
10. [差異比較 diff](#10-差異比較-diff)
11. [單向同步 sync](#11-單向同步-sync)
12. [雙向同步 bisync](#12-雙向同步-bisync)
13. [衝突策略](#13-衝突策略)
14. [Checksum](#14-checksum)
15. [JSON、Plain 與自動化](#15-jsonplain-與自動化)
16. [排程](#16-排程)
17. [環境備份與還原](#17-環境備份與還原)
18. [Secret 與認證資料](#18-secret-與認證資料)
19. [完整命令速查](#19-完整命令速查)
20. [常見使用情境](#20-常見使用情境)
21. [錯誤排查](#21-錯誤排查)
22. [相容舊版命令](#22-相容舊版命令)

---

# 1. 功能概覽

`drive-unix` 的核心能力包括：

- 用同一套 `REMOTE:/path` 語法操作多種儲存服務。
- 瀏覽、樹狀顯示、條件搜尋與 Provider 原生搜尋。
- 建立、刪除、複製、移動檔案與資料夾。
- Local ↔ Remote 上傳與下載。
- Remote ↔ Remote 跨 Provider 傳輸。
- 單向 `sync` 與安全雙向 `bisync`。
- `diff` 與同步共用相同 comparison policy。
- Provider-side 或下載後本機 Checksum。
- Cron 排程與 OS-level 背景 Scheduler service。
- JSON output、`--plain`、`NO_COLOR`，可用於 CI / Script / Log。
- Secret reference、OS keyring 與權限限制的 fallback secret store。

目前公開的頂層命令：

```text
drive-unix
├── init
├── remote
├── ls
├── tree
├── find
├── search
├── mkdir
├── rm
├── stat
├── cp
├── mv
├── upload
├── download
├── download-link
├── diff
├── sync
├── bisync
├── checksum
├── schedule
└── env
```

隨時可以用：

```bash
drive-unix --help
drive-unix COMMAND --help
drive-unix remote --help
drive-unix schedule service --help
```

---

# 2. 安裝

## 2.1 Python 版本

需要：

```text
Python 3.12+
```

## 2.2 使用 pip

在專案根目錄：

```bash
python -m pip install .
drive-unix --help
```

開發模式：

```bash
python -m pip install -e '.[all,dev]'
```

## 2.3 使用 uv

推薦使用 `uv`：

```bash
uv python install 3.12
uv sync
uv run drive-unix --help
```

開發環境：

```bash
uv sync --extra dev
```

全部 Provider 與開發工具：

```bash
uv sync --extra all --extra dev
```

或：

```bash
uv sync --all-extras
```

## 2.4 Provider optional dependencies

核心安裝不會強制安裝所有大型 SDK。依需要啟用：

| Provider / 功能 | pip | uv |
|---|---|---|
| Google Drive | `pip install '.[google]'` | `uv sync --extra google` |
| OneDrive OAuth | `pip install '.[onedrive]'` | `uv sync --extra onedrive` |
| SharePoint / OneDrive Business | `pip install '.[sharepoint]'` | `uv sync --extra sharepoint` |
| SFTP | `pip install '.[sftp]'` | `uv sync --extra sftp` |
| fuzzy search speedup | `pip install '.[speedups]'` | `uv sync --extra speedups` |
| 全部 | `pip install '.[all]'` | `uv sync --extra all` |

SharePoint / OneDrive Business 另外需要 Chromium：

```bash
playwright install chromium
```

使用 uv：

```bash
uv run playwright install chromium
```

如果缺少 Provider 套件，CLI 會顯示需要安裝的 `drive-unix[...]` extra。

---

# 3. 第一次使用

最簡單的方式：

```bash
drive-unix init
```

若目前沒有任何 Remote，`init` 會：

1. 讓你選擇 Provider。
2. 詢問 Remote 名稱。
3. 收集必要的連線或認證資料。
4. 儲存 Remote。
5. 提示執行連線測試與第一個 `ls`。

例如建立完成後：

```bash
drive-unix remote test work
drive-unix ls work:/
```

若需要確認寫入權限：

```bash
drive-unix remote test work --write
```

`--write` 會建立一個暫存測試資料夾，之後立即清理。清理方式會依 Provider 的刪除能力而不同。

如果已經有 Remote，`init` 不會覆蓋現有設定，只會列出 Remote 並提示後續操作。

---

# 4. 命令與路徑基本規則

## 4.1 Remote 路徑格式

標準格式：

```text
REMOTE:/path/to/item
```

例如：

```text
work:/Shared Documents/report.xlsx
nas:/backup/photos
local:/Projects/app
```

根目錄：

```text
work:/
```

路徑含空白時，建議用引號：

```bash
drive-unix ls 'work:/Shared Documents'
```

Windows PowerShell：

```powershell
drive-unix ls 'work:/Shared Documents'
```

## 4.2 預設 Remote

第一次透過 `drive-unix remote add` / `drive-unix init` 建立的 Remote，如果當時還沒有預設 Remote，會成為 `default_remote`。

有預設 Remote 時，部分命令允許省略 `REMOTE:`；但為了避免腳本在不同環境指到錯誤位置，**建議正式指令與排程一律明確寫出 Remote 名稱**。

推薦：

```bash
drive-unix ls work:/docs
```

不推薦在自動化中依賴：

```bash
drive-unix ls /docs
```

## 4.3 Local Remote 與本機路徑的差異

若已建立：

```text
local -> D:\Data
```

那麼：

```text
local:/docs/report.pdf
```

代表的是：

```text
D:\Data\docs\report.pdf
```

`drive-unix` 的 Remote 指令中應使用 `local:/...`，不要直接把 `D:\Data\...` 當作 Remote 路徑。

例外是 `upload` 的第一個參數與 `download` 的本機目的地，這兩處本來就接受 OS 本機路徑。

## 4.4 全域 `--plain`

任何命令前都可以加：

```bash
drive-unix --plain ls work:/
```

`--plain` 會：

- 關閉 ANSI 色彩。
- 移除 emoji / decorative symbols。
- 關閉動態 progress。
- 提供較適合 CI、redirected log 與 screen reader 的文字輸出。

例如：

```bash
drive-unix --plain sync source:/data backup:/data --dry-run
```

## 4.5 `NO_COLOR`

若只想停用色彩，不想使用完整 plain mode：

Linux / macOS：

```bash
NO_COLOR=1 drive-unix ls work:/
```

PowerShell：

```powershell
$env:NO_COLOR = '1'
drive-unix ls work:/
```

非 TTY stdout 會自動停用 live progress，避免控制字元污染 log。

---

# 5. Remote 管理

Remote 是一個命名的 Storage Provider 設定。

## 5.1 新增 Remote

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

## 5.2 列出 Remote

```bash
drive-unix remote list
```

顯示額外診斷資訊：

```bash
drive-unix remote list --verbose
```

`--verbose` 會顯示目前實際讀取的設定檔路徑。

## 5.3 測試 Remote

只測試認證與讀取：

```bash
drive-unix remote test work
```

同時測試寫入：

```bash
drive-unix remote test work --write
```

遇到 Provider 登入、權限或路徑問題時，應優先執行這個命令，而不是直接反覆執行 sync。

## 5.4 重新命名

```bash
drive-unix remote rename old-name new-name
```

如果舊名稱是預設 Remote，預設 Remote 名稱會一起更新。

## 5.5 編輯 Remote

目前 `remote edit` 主要提供 SharePoint / OneDrive Business / WebDAV 這類帳號型設定的共用欄位：

```bash
drive-unix remote edit work --base-url https://example.com

drive-unix remote edit work --site /sites/project

drive-unix remote edit work --email user@example.com
```

更新密碼有三種方式，三者只能擇一：

```bash
# 綁定環境變數
drive-unix remote edit work --password-env WORK_PASSWORD

# 終端機隱藏輸入
drive-unix remote edit work --password-prompt

# 移除現有 password reference
drive-unix remote edit work --clear-password
```

修改後建議：

```bash
drive-unix remote test work
```

> `remote edit` 並不是所有 Provider 所有欄位的通用 editor。像 SFTP host/key、Google credentials、OneDrive Client ID 等結構性設定，現階段較適合移除後重新建立 Remote，或由熟悉設定格式的使用者手動管理設定檔。

## 5.6 移除 Remote

```bash
drive-unix remote remove work
```

這會移除 Remote 設定與由該 Remote 管理的 secret reference；**不會刪除 Remote 上的檔案**。

---

# 6. 各 Provider 設定

## 6.1 Local

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

## 6.2 Google Drive

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

## 6.3 Microsoft OneDrive

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
# 可用
drive-unix rm personal:/old.txt

# 會被拒絕
drive-unix rm personal:/old.txt --permanent
```

## 6.4 SharePoint

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

## 6.5 OneDrive Business

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

## 6.6 SFTP

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

## 6.7 FTP / FTPS

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

## 6.8 WebDAV

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

## 6.9 Provider 能力摘要

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

# 7. 瀏覽、搜尋與資訊查詢

## 7.1 `ls`：列出目錄

```bash
drive-unix ls work:/docs
```

JSON：

```bash
drive-unix ls work:/docs --json
```

`--json` 適合 script 使用，失敗時也輸出 JSON error object。

## 7.2 `tree`：樹狀瀏覽

```bash
drive-unix tree work:/docs
```

限制深度：

```bash
drive-unix tree work:/docs --depth 2
# 或
drive-unix tree work:/docs -L 2
```

只顯示檔案：

```bash
drive-unix tree work:/docs --files-only
```

只顯示資料夾：

```bash
drive-unix tree work:/docs --dirs-only
# 或
drive-unix tree work:/docs -d
```

限制最多載入項目：

```bash
drive-unix tree work:/ --max-items 500
```

預設 `--max-items 1000`，用來避免意外展開極大型目錄。

`--files-only` 與 `--dirs-only` 不可同時使用。

## 7.3 `find`：跨 Provider 客戶端遞迴搜尋

基本搜尋：

```bash
drive-unix find work:/docs --name report
```

如果 `--name` 沒有 `*` / `?`，會使用 fuzzy partial match。

調整模糊門檻：

```bash
drive-unix find work:/docs --name report --fuzzy-threshold 85
```

萬用字元：

```bash
drive-unix find work:/docs --name '*.xlsx'
drive-unix find work:/docs --name 'report_??.pdf'
```

類型：

```bash
drive-unix find work:/docs --type file
drive-unix find work:/docs --type folder
```

大小：

```bash
drive-unix find work:/docs --size-gt 10MB
drive-unix find work:/docs --size-lt 1.5GB
```

支援 B / KB / MB / GB / TB 類似格式；實際倍率以 1024 為基礎。

日期：

```bash
drive-unix find work:/docs --modified-after 2026-01-01
drive-unix find work:/docs --modified-before 2026-10-01
```

也接受可由 Python ISO-8601 parser 解析的 timestamp。

限制深度：

```bash
drive-unix find work:/ --max-depth 3
```

條件可組合：

```bash
drive-unix find work:/projects \
  --name '*.pdf' \
  --type file \
  --size-gt 1MB \
  --modified-after 2026-01-01 \
  --max-depth 5
```

## 7.4 `search`：Provider 原生搜尋

```bash
drive-unix search work:/docs invoice
```

這通常比 `find` 快，但並非每個 Provider 都支援。

如果 Provider 不支援，改用：

```bash
drive-unix find work:/docs --name invoice
```

選擇原則：

- 想要跨 Provider 一致性 → `find`
- Provider 支援原生 API、資料量大、追求速度 → `search`

## 7.5 `stat`：查看項目資訊

Remote root：

```bash
drive-unix stat work:/
```

單一檔案：

```bash
drive-unix stat work:/docs/report.pdf
```

JSON：

```bash
drive-unix stat work:/docs/report.pdf --json
```

Provider 如果有提供容量資料，root stat 會顯示總容量、已用空間等資訊；若 Provider 不提供，欄位可能顯示為未提供。

---

# 8. 建立與刪除

## 8.1 `mkdir`

建立一層：

```bash
drive-unix mkdir work:/docs/new-folder
```

自動建立父目錄：

```bash
drive-unix mkdir work:/a/b/c --parents
# 或
drive-unix mkdir work:/a/b/c -p
```

## 8.2 `rm`

一般刪除：

```bash
drive-unix rm work:/docs/old.txt
```

CLI 會在執行前顯示這個 Provider 實際的刪除語意。

跳過確認：

```bash
drive-unix rm work:/docs/old.txt --force
```

要求永久刪除：

```bash
drive-unix rm work:/docs/old.txt --permanent
```

或：

```bash
drive-unix rm work:/docs/old.txt -p
```

### 刪除安全規則

- Local / FTP / SFTP / WebDAV：無回收桶，本來就是永久刪除。
- Google Drive / SharePoint / OneDrive Business：預設走回收機制，可依 Provider 支援要求永久刪除。
- OneDrive：目前只支援移至回收桶；`--permanent` 會被拒絕。

對永久刪除型 Provider：

```bash
drive-unix rm local:/important/data
```

CLI 會明確提示「永久刪除」，不會誤稱為移至回收桶。

> `--force` 只會跳過確認，不會改變 Provider 的刪除模式。請勿把 `--force` 當成一般互動操作的預設選項。

---

# 9. 複製、移動、上傳與下載

## 9.1 `cp`

同 Remote：

```bash
drive-unix cp work:/docs/A.pdf work:/archive/A.pdf
```

跨 Remote：

```bash
drive-unix cp work:/docs/A.pdf gdrive:/backup/A.pdf
```

`drive-unix` 會由 TransferService 選擇同 Provider 直接操作或跨 Provider bridge transfer。

## 9.2 `mv`

同 Remote：

```bash
drive-unix mv work:/docs/A.pdf work:/archive/A.pdf
```

跨 Remote：

```bash
drive-unix mv work:/docs/A.pdf nas:/archive/A.pdf
```

跨 Remote move 的心理模型是：

```text
copy to destination -> successful destination write -> remove source
```

因此跨 Remote `mv` 同時需要：

- Source read / delete permission
- Destination write permission

若資料非常重要，建議先用 `cp` 驗證目標，再手動 `rm`，而不是直接使用跨 Remote `mv`。

## 9.3 `upload`

上傳單一檔案：

```bash
drive-unix upload ./report.pdf work:/docs/report.pdf
```

資料夾必須明確指定遞迴：

```bash
drive-unix upload ./Photos work:/backup/Photos --recursive
# 或
drive-unix upload ./Photos work:/backup/Photos -r
```

控制併發：

```bash
drive-unix upload ./Photos work:/backup/Photos -r --workers 8
```

預設 workers：

```text
4
```

`workers` 必須至少為 1。

## 9.4 `download`

下載檔案到目前目錄：

```bash
drive-unix download work:/docs/report.pdf
```

指定本機路徑：

```bash
drive-unix download work:/docs/report.pdf ./downloads/
```

資料夾：

```bash
drive-unix download work:/Photos ./backup --recursive
```

或：

```bash
drive-unix download work:/Photos ./backup -r
```

控制併發：

```bash
drive-unix download work:/Photos ./backup -r --workers 8
```

若本機已有**相同大小**的檔案，預設可能略過下載。

強制重新下載：

```bash
drive-unix download work:/docs/report.pdf ./downloads --force
```

對資料夾也可以：

```bash
drive-unix download work:/Photos ./backup -r --force
```

> 「相同大小」不是完整內容驗證。如果你需要內容級完整性確認，下載後再使用 checksum 或其他驗證流程。

互動式 TTY 中，如果下載目標其實是資料夾但沒有指定 `-r`，CLI 可能詢問是否遞迴；在 CI / 非互動環境則必須明確提供 `--recursive`。

## 9.5 `download-link`

取得 Provider 提供的直接下載或分享 URL：

```bash
drive-unix download-link work:/docs/report.pdf
```

此功能取決於 Provider 是否實作 download-link。

目前可用於：

- OneDrive
- OneDrive Business
- SharePoint
- FTP / FTPS
- WebDAV

若 Provider 不支援，使用：

```bash
drive-unix download work:/docs/report.pdf
```

> 有效期限與認證方式由 Provider 決定。FTP / WebDAV 的目前實作可能把帳號或密碼直接放進 URL；這類連結應視為敏感憑證，不要貼到公開聊天、Issue、Log 或文件。

---

# 10. 差異比較 `diff`

基本比較：

```bash
drive-unix diff source:/docs backup:/docs
```

顯示相同項目：

```bash
drive-unix diff source:/docs backup:/docs --show-same
# 或
drive-unix diff source:/docs backup:/docs -s
```

使用 Checksum：

```bash
drive-unix diff source:/docs backup:/docs --checksum
```

JSON：

```bash
drive-unix diff source:/docs backup:/docs --json
```

`diff` 使用共用 `SyncPlanner` comparison policy，因此它與 `sync` 對「是否有差異」的判定規則保持一致。

### 一般單向 comparison policy

對一般檔案，主要考慮：

1. File / directory type 是否不同。
2. Size 是否不同。
3. 使用 `--checksum` 時，以 Checksum 進一步比較。
4. 有修改時間時，來源比目標新會視為需要更新。

Microsoft Office 檔案在 Microsoft Provider 上有特殊處理，因為 server-side processing 可能讓 binary size 改變，因此不完全依賴 size。

`--checksum` 比一般 metadata comparison 更精確，但會增加 Provider API / I/O 成本。

---

# 11. 單向同步 `sync`

最基本：

```bash
drive-unix sync source:/docs backup:/docs
```

預設是：

```text
source -> destination
```

也就是來源是 canonical side。

## 11.1 強烈建議先 Dry Run

```bash
drive-unix sync source:/docs backup:/docs --dry-run
```

Dry run 只建立並顯示同步計畫，不修改檔案。

正式執行：

```bash
drive-unix sync source:/docs backup:/docs
```

## 11.2 `--delete`

建立 mirror：

```bash
drive-unix sync source:/docs backup:/docs --delete
```

這會刪除 destination 上存在、source 上不存在的項目。

**先執行：**

```bash
drive-unix sync source:/docs backup:/docs --delete --dry-run
```

Sync Plan 會列出刪除數量，若目標 Provider 是 permanent-only，也會額外標示不可復原刪除風險。

## 11.3 Include / Exclude

只同步 PDF：

```bash
drive-unix sync source:/docs backup:/docs --include '*.pdf'
```

排除 temporary files：

```bash
drive-unix sync source:/docs backup:/docs --exclude '*.tmp'
```

目前 pattern 是以**項目檔名**進行 `fnmatch`，不是完整相對路徑 pattern。

## 11.4 Checksum comparison

```bash
drive-unix sync source:/docs backup:/docs --checksum
```

適合：

- metadata 時間戳不可靠的 Provider
- 高完整性要求
- 需要較準確 rename detection 的 mirror

使用 `--checksum` 會增加掃描成本。

## 11.5 Progress

```bash
drive-unix sync source:/docs backup:/docs --progress
```

`--plain` 或非 TTY 環境會自動停用 live progress。

## 11.6 Workers

```bash
drive-unix sync source:/docs backup:/docs --workers 8
```

預設：

```text
4
```

workers 必須 >= 1。

## 11.7 Throttle

每個操作間強制延遲：

```bash
drive-unix sync source:/docs backup:/docs --throttle 0.5
```

適合容易 rate limit 的服務。

## 11.8 Full Plan

大量同步時預設偏向摘要與重要風險。

若要逐項檢查：

```bash
drive-unix sync source:/docs backup:/docs --dry-run --full-plan
```

## 11.9 跳過確認

```bash
drive-unix sync source:/docs backup:/docs --yes
```

或：

```bash
drive-unix sync source:/docs backup:/docs -y
```

建議只在：

- 已驗證過 dry-run
- CI
- Scheduler
- 明確理解 `--delete` 風險

時使用。

## 11.10 `--one-way` / `--two-way`

`sync` 預設就是單向：

```bash
drive-unix sync A:/ B:/
```

也可明確寫：

```bash
drive-unix sync A:/ B:/ --one-way
```

相容舊流程仍可：

```bash
drive-unix sync A:/ B:/ --two-way
```

但新指令建議使用：

```bash
drive-unix bisync A:/ B:/
```

### Boolean flag 注意

請勿使用：

```bash
# 錯誤
drive-unix sync A:/ B:/ --one-way=False
```

`--one-way/--two-way` 是 flag pair，不接受 `=False`。

需要雙向時直接使用：

```bash
drive-unix sync A:/ B:/ --two-way
```

或更推薦：

```bash
drive-unix bisync A:/ B:/
```

---

# 12. 雙向同步 `bisync`

基本用法：

```bash
drive-unix bisync laptop:/docs cloud:/docs
```

推薦先：

```bash
drive-unix bisync laptop:/docs cloud:/docs --dry-run
```

雙向同步會：

- 只在左側存在 → 複製到右側。
- 只在右側存在 → 複製到左側。
- 兩邊都有且內容不同 → 根據 conflict strategy 決定。

### 雙向同步不支援 `--delete`

這是刻意的安全限制。

原因是單次 snapshot 無法可靠判斷：

```text
「只存在一邊」
```

究竟代表：

```text
另一邊新增
```

還是：

```text
這一邊曾經刪除
```

因此 `bisync` 不提供 `--delete`，`sync --two-way --delete` 也會被拒絕。

### 範例

雙向 + checksum：

```bash
drive-unix bisync laptop:/docs cloud:/docs --checksum --dry-run
```

保留所有衝突舊版本：

```bash
drive-unix bisync laptop:/docs cloud:/docs --conflict rename
```

自動執行：

```bash
drive-unix bisync laptop:/docs cloud:/docs --yes
```

---

# 13. 衝突策略

可用：

```text
auto
newer
rename
abort
prefer-source
prefer-destination
```

## 13.1 `auto`（預設）

```bash
drive-unix bisync A:/ B:/ --conflict auto
```

行為：

- 修改時間能安全判定較新側 → 使用較新版本。
- 內容不同，但時間戳缺失或差距在安全容忍範圍內 → 不猜 winner，先保留衝突舊版本，再更新 canonical path。
- File / directory type conflict 在雙向 auto 中也優先備份 losing side，再替換。

這是一般雙向同步的推薦預設。

## 13.2 `newer`

```bash
drive-unix bisync A:/ B:/ --conflict newer
```

只接受可以安全判斷哪一邊較新的情況。

若內容不同但無法判定 winner，會停止並回傳 conflict error，而不是默認 source wins。

適合：

- 兩端修改時間可信
- 希望不產生 conflict copy
- 遇到 ambiguity 時寧願中止

## 13.3 `rename`

```bash
drive-unix bisync A:/ B:/ --conflict rename
```

更新前先把將被覆蓋的一側重新命名保留。

Conflict backup 名稱會帶原 modification timestamp；若無時間則使用 fallback suffix。

適合最保守的人工作業流程。

## 13.4 `abort`

```bash
drive-unix bisync A:/ B:/ --conflict abort
```

只要遇到雙方同路徑內容不同，就停止 planning。

適合：

- 資料極重要
- 希望所有 conflict 都由人決定

`abort` 僅適用雙向同步。

## 13.5 `prefer-source`

```bash
drive-unix bisync A:/ B:/ --conflict prefer-source
```

衝突時固定採左側 / source 版本。

這是**明確覆蓋策略**，請只在你確定左側是 authoritative side 時使用。

單向 sync 也可使用此策略。

## 13.6 `prefer-destination`

```bash
drive-unix bisync A:/ B:/ --conflict prefer-destination
```

衝突時固定採右側 / destination 版本。

僅適用雙向同步。

## 13.7 選擇建議

| 情境 | 建議策略 |
|---|---|
| 一般雙向同步 | `auto` |
| 不想猜時間戳衝突 | `newer` |
| 最重視保留舊版本 | `rename` |
| 所有 conflict 都要人工處理 | `abort` |
| 左側是 authoritative | `prefer-source` |
| 右側是 authoritative | `prefer-destination` |

---

# 14. Checksum

## 14.1 基本用法

```bash
drive-unix checksum work:/docs/A.pdf
```

預設：

```text
--algo sha256
--mode auto
```

## 14.2 Algorithm

支援：

```text
md5
sha1
sha256
quickXorHash
```

例如：

```bash
drive-unix checksum work:/docs/A.pdf --algo md5
```

## 14.3 `--mode auto`

```bash
drive-unix checksum work:/docs/A.pdf --mode auto
```

流程：

1. 先向 Provider 取得 remote hash。
2. 若 Provider 不提供指定 algorithm，自動下載到暫存目錄。
3. 在本機計算。
4. 暫存資料由 temporary directory 清理。

這是一般使用的推薦模式。

## 14.4 `--mode remote`

```bash
drive-unix checksum work:/docs/A.pdf --mode remote
```

只允許 Provider-side hash，不下載檔案。

若 Provider 不支援，命令會以 exit code `2` 結束並提示改用 download / auto。

## 14.5 `--mode download`

```bash
drive-unix checksum work:/docs/A.pdf --mode download
```

強制下載檔案後本機計算。

適合：

- Provider hash algorithm 不符合需求
- 想統一使用同一套本機 hash implementation

## 14.6 舊版 flags

仍相容：

```bash
drive-unix checksum work:/A.pdf --remote
drive-unix checksum work:/A.pdf --download
```

新腳本建議改用 `--mode`。

`--remote` 與 `--download` 不可同時使用。

---

# 15. JSON、Plain 與自動化

## 15.1 提供 JSON 的命令

目前：

```text
ls
stat
diff
sync
bisync
```

### `ls`

```bash
drive-unix ls work:/ --json
```

### `stat`

```bash
drive-unix stat work:/docs/A.pdf --json
```

### `diff`

```bash
drive-unix diff A:/ B:/ --json
```

### Sync dry run

```bash
drive-unix sync A:/ B:/ --dry-run --json
```

典型 JSON summary 包含：

```text
status
mode
operations
transfers
directories
renames
deletes
irreversible_deletes
transfer_bytes
delete_bytes
```

### 實際 JSON sync

實際修改檔案時必須搭配 `--yes`：

```bash
drive-unix sync A:/ B:/ --json --yes
```

這是為了避免 script 卡在互動確認。

如果寫：

```bash
drive-unix sync A:/ B:/ --json
```

而又不是 `--dry-run`，CLI 會拒絕執行。

## 15.2 Sync JSON status

可能包含：

```text
noop
```

代表沒有操作需要執行。

```text
dry-run
```

代表只產生 plan。

```text
ok
```

全部操作成功。

```text
partial-failure
```

有部分 action 失敗。

```text
conflict
```

Planner 因安全衝突停止。

```text
error
```

其他錯誤。

## 15.3 Exit code

一般原則：

| Exit code | 含義 |
|---:|---|
| `0` | 成功、noop、正常 dry-run 或使用者已正常取消某些互動流程 |
| `1` | 一般錯誤、部分執行失敗 |
| `2` | 特定可辨識情況，例如 sync conflict、Provider 不支援要求的 remote checksum / native search |

腳本不要只解析人類文字；有 `--json` 的命令應優先搭配 exit code 與 JSON `status`。

## 15.4 CI 建議

例如先驗證同步計畫：

```bash
drive-unix --plain sync source:/data backup:/data --dry-run --json > plan.json
```

正式執行：

```bash
drive-unix --plain sync source:/data backup:/data --yes --json > result.json
```

> `--plain` 對 JSON 本身沒有額外價值，但如果同一套 wrapper 還會執行其他人類輸出命令，可保持統一的非互動 presentation policy。

---

# 16. 排程

`drive-unix` 內建五欄 Cron scheduler。

格式：

```text
分 時 日 月 星期
```

例如每天 02:00：

```text
0 2 * * *
```

每 15 分鐘：

```text
*/15 * * * *
```

工作日 09:00：

```text
0 9 * * 1-5
```

Scheduler 支援：

- `*`
- 數值
- comma list，例如 `1,3,5`
- range，例如 `1-5`
- step，例如 `*/15`、`1-20/2`

## 16.1 新增排程

```bash
drive-unix schedule add nightly '0 2 * * *' \
  'sync local:/data cloud:/backup --yes'
```

也可以把 command 寫成包含 executable 的形式：

```bash
drive-unix schedule add nightly '0 2 * * *' \
  'drive-unix sync local:/data cloud:/backup --yes'
```

或現有 uv workflow：

```bash
drive-unix schedule add nightly '0 2 * * *' \
  'uv run drive-unix sync local:/data cloud:/backup --yes'
```

Scheduler 會正規化這些常見 executable prefix，再由目前 drive-unix Python process 執行內部命令。

### 排程 command 建議

實際 sync 排程通常應包含：

```text
--yes
```

否則 background scheduler 無法回答確認問題。

推薦先手動 dry-run：

```bash
drive-unix sync local:/data cloud:/backup --dry-run
```

確認後再新增：

```bash
drive-unix schedule add nightly '0 2 * * *' \
  'sync local:/data cloud:/backup --yes'
```

## 16.2 列出排程

```bash
drive-unix schedule list
```

每個 task 會顯示：

- enabled / disabled
- Cron expression
- 最後嘗試時間
- 最後成功時間
- 最後 exit code
- command

## 16.3 Enable / Disable

```bash
drive-unix schedule disable nightly
drive-unix schedule enable nightly
```

## 16.4 移除

```bash
drive-unix schedule remove nightly
```

## 16.5 前景模式

```bash
drive-unix schedule start
```

這會在目前終端機中持續執行 scheduler。

停止：

```text
Ctrl+C
```

適合：

- 開發
- Debug
- 觀察 task output

不適合需要長期背景執行的正式環境。

## 16.6 背景 Service

安裝 service：

```bash
drive-unix schedule service install
```

啟動：

```bash
drive-unix schedule service start
```

狀態：

```bash
drive-unix schedule service status
```

停止：

```bash
drive-unix schedule service stop
```

移除：

```bash
drive-unix schedule service uninstall
```

### OS backend

| OS | Backend |
|---|---|
| Linux | user-level systemd |
| macOS | LaunchAgent / launchd |
| Windows | Task Scheduler |
| 其他 / 未安裝 service | detached process fallback |

如果尚未執行 `service install`，仍可：

```bash
drive-unix schedule service start
```

此時會使用 detached process，但不代表已設定 login auto-start。

### Log

Scheduler log 預設位於設定目錄下：

```text
~/.config/mycli/scheduler/scheduler.log
```

Windows 上 `~` 代表目前使用者 home directory。

查看狀態時也會顯示實際 log path：

```bash
drive-unix schedule service status
```

## 16.7 Missed run

Scheduler 會檢查先前 task 是否錯過符合的 Cron 時點；目前最多回看約 7 天。

這讓短暫中斷後重新啟動 scheduler 時，可以補執行近期錯過的 task。

---

# 17. 環境備份與還原

## 17.1 一般設定備份

```bash
drive-unix env export backup.zip
```

預設主要匯出設定，不包含敏感 secret store 與 auth cache。

## 17.2 包含 Secrets

```bash
drive-unix env export backup.zip --include-secrets
```

這可能包含：

- secret store
- OAuth client credential files

屬於高度敏感資料。

## 17.3 包含 Auth Cache

```bash
drive-unix env export backup.zip --include-auth-cache
```

這可能包含：

- Refresh token
- Cookie
- OAuth cache

同樣屬於敏感資料。

## 17.4 完整可攜備份

```bash
drive-unix env export full-backup.zip \
  --include-secrets \
  --include-auth-cache
```

請把這類檔案當作 credential bundle 保護，不應上傳公共雲端、Git repository 或聊天內容。

Export 會盡力把 archive 權限設定為只有目前使用者可讀寫。

## 17.5 Import

```bash
drive-unix env import backup.zip
```

如果本機已有設定，會要求確認。

自動覆蓋：

```bash
drive-unix env import backup.zip --force
```

Import 有 Zip Slip 與 symbolic-link escape 防護，只允許預期的 archive top-level 內容。

---

# 18. Secret 與認證資料

`config.toml` 不應保存明文 password / client secret，而是保存 reference。

Reference 可能是：

```text
env:NAME
keyring:key
file:key
```

## 18.1 環境變數

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

## 18.2 Interactive Secret

若透過 Wizard 輸入密碼，會優先嘗試 OS keyring。

若系統沒有可用 keyring backend，會 fallback 到權限限制的 local secret store。

## 18.3 設定與 Cache 預設位置

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

# 19. 完整命令速查

## Global

```text
drive-unix [--plain] COMMAND ...
```

## Setup / Remote

```text
drive-unix init

drive-unix remote add [PROVIDER] [--name NAME]
drive-unix remote list [--verbose]
drive-unix remote test NAME [--write]
drive-unix remote edit NAME [OPTIONS]
drive-unix remote rename OLD NEW
drive-unix remote remove NAME
```

`remote edit` options：

```text
--base-url, -b TEXT
--site, -s TEXT
--email, -e TEXT
--password-env TEXT
--password-prompt
--clear-password
```

## Browse / Search

```text
drive-unix ls PATH [--json]

drive-unix tree REMOTE_PATH
  [--depth INTEGER | -L INTEGER]
  [--files-only]
  [--dirs-only | -d]
  [--max-items INTEGER]

drive-unix find REMOTE_PATH
  [--name TEXT | -n TEXT]
  [--fuzzy-threshold INTEGER]
  [--type file|folder | -t file|folder]
  [--size-gt SIZE]
  [--size-lt SIZE]
  [--modified-after DATE]
  [--modified-before DATE]
  [--max-depth INTEGER]

drive-unix search REMOTE_PATH QUERY

drive-unix stat REMOTE_PATH [--json]
```

## File operations

```text
drive-unix mkdir REMOTE_PATH [--parents | -p]

drive-unix rm REMOTE_PATH
  [--permanent | -p]
  [--force | -f]

drive-unix cp SOURCE DEST

drive-unix mv SOURCE DEST
```

## Transfer

```text
drive-unix upload LOCAL_PATH REMOTE_PATH
  [--recursive | -r]
  [--workers INTEGER | -w INTEGER]

drive-unix download REMOTE_PATH [LOCAL_PATH]
  [--workers INTEGER | -w INTEGER]
  [--force | -f]
  [--recursive | -r]

drive-unix download-link REMOTE_PATH
```

## Diff / Sync

```text
drive-unix diff SOURCE DEST
  [--show-same | -s]
  [--checksum]
  [--json]

drive-unix sync SOURCE DEST
  [--dry-run]
  [--one-way | --two-way]
  [--delete]
  [--exclude PATTERN]
  [--include PATTERN]
  [--conflict STRATEGY]
  [--checksum]
  [--progress]
  [--workers INTEGER | -w INTEGER]
  [--yes | -y]
  [--throttle FLOAT]
  [--full-plan]
  [--json]

drive-unix bisync SOURCE DEST
  [--dry-run]
  [--exclude PATTERN]
  [--include PATTERN]
  [--conflict STRATEGY]
  [--checksum]
  [--progress]
  [--workers INTEGER | -w INTEGER]
  [--yes | -y]
  [--throttle FLOAT]
  [--full-plan]
  [--json]
```

Conflict strategy：

```text
auto | newer | rename | abort | prefer-source | prefer-destination
```

## Checksum

```text
drive-unix checksum REMOTE_PATH
  [--algo md5|sha1|sha256|quickXorHash]
  [--mode auto|remote|download]
```

Compatibility flags：

```text
--remote
--download
```

## Schedule

```text
drive-unix schedule add NAME 'CRON' 'COMMAND'
drive-unix schedule list
drive-unix schedule enable NAME
drive-unix schedule disable NAME
drive-unix schedule remove NAME
drive-unix schedule start

drive-unix schedule service install
drive-unix schedule service start
drive-unix schedule service status
drive-unix schedule service stop
drive-unix schedule service uninstall
```

## Environment

```text
drive-unix env export OUTPUT.zip
  [--include-auth-cache]
  [--include-secrets]

drive-unix env import INPUT.zip
  [--force | -f]
```

---

# 20. 常見使用情境

## 20.1 本機資料夾備份到 Google Drive

建立兩個 Remote：

```bash
drive-unix remote add local --name laptop
drive-unix remote add google-drive --name cloud
```

驗證：

```bash
drive-unix remote test laptop --write
drive-unix remote test cloud --write
```

Dry run：

```bash
drive-unix sync laptop:/Documents cloud:/DocumentsBackup --dry-run
```

執行：

```bash
drive-unix sync laptop:/Documents cloud:/DocumentsBackup
```

Mirror：

```bash
drive-unix sync laptop:/Documents cloud:/DocumentsBackup --delete --dry-run
```

確認後：

```bash
drive-unix sync laptop:/Documents cloud:/DocumentsBackup --delete
```

## 20.2 Laptop 與 Cloud 雙向文件同步

```bash
drive-unix bisync laptop:/Documents cloud:/Documents --dry-run
```

確認後：

```bash
drive-unix bisync laptop:/Documents cloud:/Documents
```

如果任何 conflict 都希望完整保留：

```bash
drive-unix bisync laptop:/Documents cloud:/Documents --conflict rename
```

## 20.3 比較兩份資料是否一致

快速 metadata comparison：

```bash
drive-unix diff A:/data B:/data
```

完整度較高：

```bash
drive-unix diff A:/data B:/data --checksum
```

給 script：

```bash
drive-unix diff A:/data B:/data --checksum --json > diff.json
```

## 20.4 每晚 02:00 備份

先測試：

```bash
drive-unix sync laptop:/data cloud:/backup --dry-run
```

新增：

```bash
drive-unix schedule add nightly '0 2 * * *' \
  'sync laptop:/data cloud:/backup --yes'
```

安裝並啟動 background service：

```bash
drive-unix schedule service install
drive-unix schedule service start
drive-unix schedule service status
```

## 20.5 只備份 PDF

```bash
drive-unix sync work:/docs archive:/docs \
  --include '*.pdf' \
  --dry-run
```

## 20.6 排除暫存檔

```bash
drive-unix sync work:/docs archive:/docs --exclude '*.tmp'
```

目前 `--exclude` / `--include` 各接受一個 glob pattern，請不要假設重複提供 option 會累積多組規則。需要多組 filter rule 時，應拆成不同同步流程或後續擴充 filter-list 功能。

## 20.7 找出最近的大型 PDF

```bash
drive-unix find work:/docs \
  --name '*.pdf' \
  --type file \
  --size-gt 20MB \
  --modified-after 2026-01-01
```

## 20.8 CI 中安全檢查 mirror plan

```bash
drive-unix --plain sync source:/data mirror:/data \
  --delete \
  --dry-run \
  --json > plan.json
```

正式執行：

```bash
drive-unix --plain sync source:/data mirror:/data \
  --delete \
  --yes \
  --json > result.json
```

---

# 21. 錯誤排查

CLI 的人類可讀 error 預設採：

```text
問題
原因
下一步
```

排查時建議依下列順序。

## 21.1 找不到 Remote

```bash
drive-unix remote list
```

確認名稱後再：

```bash
drive-unix remote test NAME
```

## 21.2 認證錯誤

```bash
drive-unix remote test NAME
```

檢查：

- OAuth 是否完成
- Password env 是否存在
- Secret reference 是否仍有效
- Browser auth Provider 是否已安裝 Playwright Chromium

## 21.3 寫入 / 刪除失敗

```bash
drive-unix remote test NAME --write
```

確認帳號具備：

- create directory
- write
- delete / trash

權限。

## 21.4 Provider 套件缺失

例如會看到類似：

```text
Google Drive provider 缺少選用套件 ...
```

依 Provider 安裝對應 extra：

```bash
uv sync --extra google
uv sync --extra onedrive
uv sync --extra sharepoint
uv sync --extra sftp
```

## 21.5 `search` 不支援

使用：

```bash
drive-unix find REMOTE:/path --name keyword
```

## 21.6 `checksum --mode remote` 不支援

改：

```bash
drive-unix checksum REMOTE:/file --mode auto
```

或：

```bash
drive-unix checksum REMOTE:/file --mode download
```

## 21.7 Sync conflict exit code 2

先：

```bash
drive-unix bisync A:/ B:/ --dry-run --full-plan
```

再依需求：

```bash
drive-unix bisync A:/ B:/ --conflict rename
```

或：

```bash
drive-unix bisync A:/ B:/ --conflict prefer-source
```

或：

```bash
drive-unix bisync A:/ B:/ --conflict prefer-destination
```

## 21.8 Sync 有永久刪除風險

不要直接加 `-y`。

先：

```bash
drive-unix sync A:/ B:/ --delete --dry-run --full-plan
```

確認 `irreversible_deletes` / 人類可讀風險摘要，再正式執行。

## 21.9 Scheduler 沒有執行

```bash
drive-unix schedule list
drive-unix schedule service status
```

檢查 log：

```text
~/.config/mycli/scheduler/scheduler.log
```

若要直接觀察：

```bash
drive-unix schedule start
```

以前景模式確認 task 能否觸發。

## 21.10 `--one-way=False` 錯誤

錯誤：

```bash
drive-unix sync A:/ B:/ --one-way=False
```

正確單向：

```bash
drive-unix sync A:/ B:/
```

正確雙向：

```bash
drive-unix bisync A:/ B:/
```

或 compatibility form：

```bash
drive-unix sync A:/ B:/ --two-way
```

---

# 22. 相容舊版命令

目前新版 root help 不再顯示以下命令，但為了既有 script 相容仍可使用。

## Remote aliases

```text
add-sp
add-odb
add-gdrive
add-local
add-ftp
add-webdav
add-onedrive
list-nodes
remove-node
rename-node
edit-node
```

推薦逐步改成：

```text
remote add
remote list
remote remove
remote rename
remote edit
```

SFTP 建議直接使用新版 Wizard：

```bash
drive-unix remote add sftp
```

## Environment aliases

```text
export-env
import-env
```

推薦：

```text
env export
env import
```

## Scheduler aliases

```text
cron-add
cron-ls
cron-rm
cron-toggle
cron-start
```

推薦：

```text
schedule add
schedule list
schedule remove
schedule enable / disable
schedule start
```

## Two-way sync compatibility

舊腳本：

```bash
drive-unix sync A:/ B:/ --two-way
```

仍可執行。

新腳本推薦：

```bash
drive-unix bisync A:/ B:/
```

---

# 最佳實務摘要

日常操作建議遵守以下原則：

1. **第一次設定先用 `init` / `remote add`，設定後用 `remote test`。**
2. **正式腳本一律明確寫 `REMOTE:/path`。**
3. **同步前先 `--dry-run`；mirror `--delete` 更應如此。**
4. **雙向同步優先使用 `bisync`，預設 `auto` 已針對 ambiguity 做保守處理。**
5. **重要資料遇到 conflict 優先選 `rename` 或 `abort`，不要任意 prefer 某一側。**
6. **Local / FTP / SFTP / WebDAV 的刪除是永久的。**
7. **自動化 sync 要加 `--yes`；使用 JSON 時實際 sync 強制要求 `--yes`。**
8. **CI / Log 使用 `--plain`；機器判斷優先使用 `--json` 與 exit code。**
9. **排程先手動 dry-run，再加入 `schedule add`。**
10. **包含 secrets / auth cache 的環境備份視同帳號憑證保存。**

需要查看任何單一命令的即時參數時，以程式本身為最終依據：

```bash
drive-unix COMMAND --help
```
