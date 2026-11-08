# 01 入門：功能概覽、安裝與基本操作

[← 手冊目錄](README.md) | [下一章 →](02-providers-and-secrets.md)

本章內容：

- # 1. 功能概覽
- # 2. 安裝
- # 3. 第一次使用
- # 4. 命令與路徑基本規則

---

## 1. 功能概覽

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

## 2. 安裝

### 2.1 Python 版本

需要：

```text
Python 3.12+
```

### 2.2 使用 pip

在專案根目錄：

```bash
python -m pip install .
drive-unix --help
```

開發模式：

```bash
python -m pip install -e '.[all,dev]'
```

### 2.3 使用 uv

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

### 2.4 Provider optional dependencies

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

## 3. 第一次使用

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

## 4. 命令與路徑基本規則

### 4.1 Remote 路徑格式

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

### 4.2 預設 Remote

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

### 4.3 Local Remote 與本機路徑的差異

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

### 4.4 全域 `--plain`

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

### 4.5 `NO_COLOR`

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

[← 手冊目錄](README.md)
