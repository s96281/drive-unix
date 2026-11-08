# 01 入門：功能概覽、安裝與基本操作

[← 手冊目錄](README.md) | [下一章：Remote 與各 Provider 設定 →](02-providers-and-secrets.md)

## 1.1 功能概覽

`drive-unix` 把十幾種儲存後端收進同一個 CLI 介面。你面對的只有 Remote 別名與 `REMOTE:/path` 路徑，不用切換每家廠商自己的工具。

核心能力可分為四類（括號內為主指令，細節在後續章節）：

- **瀏覽與查詢**：`ls` 列目錄、`tree` 樹狀展開、`find` 條件遞迴搜尋、`search` 交給 Provider 原生搜尋、`stat` 看容量與時間資訊。
- **單檔操作**：`mkdir` 建資料夾、`rm` 刪除（依 Provider 決定是進回收桶還是永久刪除）、複製／移動／上傳／下載（`cp`／`mv`／`upload`／`download`），跨不同廠商的內容會自動經本機中繼。
- **比對與同步**：`diff` 只比對不改動；`sync` 單向把來源推到目標（可選 `--delete` 做鏡像）；`bisync` 雙向拉齊；`checksum` 驗證內容是否一致。
- **自動化與多機**：Cron 排程 + OS 背景 service、環備份還原（`env export/import`）、Upstash E2EE 雲端同步（多台電腦共用 topology 與 token）。

支援的 Provider 型別（在設定檔中的 `type`）：`local`、`google_drive`、`googlephotos`、`onedrive`、`onedrive_business`、`sharepoint`、`sftp`、`ftp`、`webdav`、`pikpak`，以及尚未實作的 `alist`（保留型別，會直接報錯）。各家差異（刪除模式、extras、必填欄位）見 [下一章](02-providers-and-secrets.md)。

## 1.2 安裝

需求：Python 3.12 或以上。CI 會在 3.12 / 3.13 / 3.14 都跑完整測試。

### 1.2.1 用 pip 安裝

```bash
# 核心 CLI
python -m pip install .
drive-unix --help
```

如果只是想確認安裝是否正確，先跑 `drive-unix --help`；根指令沒有參數時會直接顯示說明（`no_args_is_help`）。

### 1.2.2 用 uv 管理

專案根目錄有 `.python-version`（預設 3.12），uv 會自動下載缺少的 Python：

```bash
uv python install 3.12
uv sync
uv run drive-unix --help
```

### 1.2.3 Provider extras

核心安裝不含大型 SDK。各 Provider 用到第三方套件時，請按需安裝 extras（缺少 extras 時，Provider factory 會直接告訴你要裝哪一個）：

| extras | 用途 |
|---|---|
| `google` | Google Drive / Google Photos（`google-api-python-client`、`google-auth`、`google-auth-oauthlib`） |
| `onedrive` | Microsoft OneDrive（`requests-oauthlib`） |
| `sharepoint` | SharePoint / OneDrive Business（Playwright 瀏覽器自動化，裝完還要 `playwright install chromium`） |
| `sftp` | SFTP（`paramiko`） |
| `all` | 上述全部加上 `httpx`、`uvicorn` 等 Web / 傳輸依賴 |
| `dev` | 開發檢查工具（`build`、`mypy`、`pytest`、`ruff`） |

uv 寫法：`uv sync --extra google`；多個 extra 可重複指定，或 `uv sync --all-extras`。

> 本機驗證（與 CI 同步）：`python -m compileall`、`ruff check .`、`mypy`、`python -m pytest`。uv 環境下在每條後面加 `uv run` 即可。

## 1.3 第一次使用：三分鐘導引

最省事的入口是互動式導引：

```bash
drive-unix init
```

行為：若已存在至少一個 Remote，會列出來並提示下一步；若一個都沒有，會直接啟動 `remote add` wizard 問你要接哪一家。

第一次正式操作建議固定三步走（先建 Remote、再測連線、最後看根目錄）：

```bash
drive-unix remote add local --name laptop      # 互動 wizard，選 local 並填本機根目錄
drive-unix remote test laptop                  # 驗證認證 + 讀取
drive-unix ls laptop:/
```

若想直接以命令列方式建立，不走 wizard，可參考 [下一章](02-providers-and-secrets.md) 的舊版直供指令（`add-local`、`add-gdrive` 等，屬相容別名）。

## 1.4 命令與路徑基本規則

### 1.4.1 `REMOTE:/path` 語法

| 寫法 | 意義 |
|---|---|
| `work:/` | Remote `work` 的根目錄 |
| `work:/docs/a.pdf` | Remote `work` 下 `docs/a.pdf` |
| `drive-unix ls gdrive:/docs` | 列出 `gdrive` 的 `/docs` |
| `drive-unix upload ./report.pdf work:/docs/report.pdf` | 本機檔上傳到遠端 |

規則：

- Remote 名稱不可含 `:` 或 `/`；路徑一律以 `/` 分隔，首尾斜線可省略（`work:/docs` 與 `work:/docs/` 相同）。
- 本機相對路徑（`./x`、`../x`）只有在 `upload` 的來源與 `download` 的目標時才合法；其餘指令的來源/目標必須是 `REMOTE:/path`。
- Remote 名稱大小寫敏感；Provider `type` 會被轉成小寫。
- 第一個 Remote 會自動成為 `default_remote`；`remote list` 中 `⭐ (預設)` 即為預設。預設 Remote 的作用在於 Web 介面與部分工具的初始選擇，不影響 CLI 上所有 `REMOTE:/path` 指令。

### 1.4.2 全域選項只有兩個

```bash
drive-unix --plain ls work:/          # 純文字：關色彩、emoji、動態進度
NO_COLOR=1 drive-unix ls work:/       # 只關色彩
```

- `--plain` 特別適合 CI log、檔案輸出或 screen reader。它會關閉 ANSI 色彩、emoji/符號、以及 Rich 的 live 進度動畫。注意：它是 root 指令的參數，必須放在子指令之前。
- `NO_COLOR` 只關色彩，不關 emoji，也不關 live 進度。
- 當輸出不是 TTY（例如 pipe 到檔案），live 進度會自動關閉，無須加參數。

### 1.4.3 設定檔與權限

預設設定檔在 `~/.config/mycli/config.toml`，同目錄下還有：

- `secrets.json`（`0600`，keyring 後備）
- `secret-files/`（Google OAuth JSON 等）
- `scheduler/`（PID 與 `scheduler.log`）

本機瀏覽器 profile（SharePoint/ODB 的持久登入狀態）在 `~/.config/drive-unix/browser-profiles/`，每台 identity 獨立一份，權限 `0700`。可用 `DRIVE_UNIX_BROWSER_PROFILE_DIR` 改根目錄，設為 `0/false/off/no/none/disabled` 則停用。
