# 03 瀏覽、建立與傳輸檔案

[← 上一章](02-providers-and-secrets.md) | [手冊目錄](README.md) | [下一章 →](04-diff-and-sync.md)

## 3.1 瀏覽：ls / tree / stat

所有瀏覽指令的第一參數都是 `REMOTE:/path`。路徑根目錄寫成 `別名:/` 即可。

### ls — 列目錄

```bash
drive-unix ls work:/
drive-unix ls work:/docs --limit 50 --offset 0
drive-unix --plain ls gdrive:/docs --json
```

- `--limit / -n`（預設不限）、`--offset`（預設 0）：分頁取用。想完整列出大目錄時用 `--limit 0` 相當於不限制。
- `--json`：輸出穩定 JSON `{remote, path, items[]}`，供腳本解析。錯誤時輸出 `{status: "error", ...}`。

### tree — 樹狀展開

```bash
drive-unix tree work:/docs --depth 2          # 只展開兩層
drive-unix tree work:/docs -L 2               # 同上短寫
drive-unix tree work:/docs --files-only       # 只看檔案
drive-unix tree work:/docs --dirs-only        # 只看資料夾（-d）
drive-unix tree work:/ --max-items 500        # 限制載入筆數（預設 1000）
```

- `--files-only` 與 `--dirs-only` 不能同時用。
- `--max-items` 預設 1000，刻意防呆，避免一口氣展開極大目錄把終端洗掉。

### stat — 資訊檢視

```bash
drive-unix stat work:/                    # Remote 根目錄的總容量等資訊
drive-unix stat work:/docs/report.pdf
drive-unix stat work:/docs/report.pdf --json
```

Provider 沒提供容量時，根目錄的容量欄位會是「未提供」，不是錯誤。

## 3.2 搜尋：find vs search

兩條搜尋指令分工不同，先理解差異再示範：

| 指令 | 運作方式 | 適用情境 |
|---|---|---|
| `find` | 本機遞迴爬目錄，用條件過濾 | 任何 Provider 都能用；要跨 Provider 一致時用 |
| `search` | 交給 Provider 原生 API | Provider 支援且資料量大、求速度時用 |

### find

```bash
drive-unix find work:/docs --name report
drive-unix find work:/docs --name report --fuzzy-threshold 85   # 模糊門檻（預設 70）
drive-unix find work:/docs --name '*.xlsx'                      # 萬用字元
drive-unix find work:/docs --type file --size-gt 10MB --modified-after 2026-01-01
drive-unix find work:/ --max-depth 3
```

- `--name` 若不含 `*`/`?`，會用 fuzzy partial match；含才用 fnmatch。
- `--fuzzy-threshold 0–100`，預設 70（`--fuzzy-threshold` 越高越嚴格）。
- `--size-gt / --size-lt` 接受 `B/KB/MB/GB/TB`，以 1024 為倍率。
- `--modified-after / --modified-before` 接受 `YYYY-MM-DD` 或 ISO timestamp。
- `--max-depth`（預設無限）防止在極大樹中失控。

### search

```bash
drive-unix search work:/docs invoice
```

不支援原生搜尋的 Provider（SFTP、FTP、WebDAV、PikPak、Photos）會報錯並提示改用 `find`。

## 3.3 建立與刪除

### mkdir

```bash
drive-unix mkdir work:/docs/new-folder
drive-unix mkdir work:/a/b/c --parents    # 自動建父目錄（-p）
```

### rm — 先搞懂刪除安全模型

`rm` 是否可還原，完全看 Provider 的 `DeleteCapability`。刪之前先想想：

| Provider | `rm` 預設 | `--permanent` | `--force` |
|---|---|---|---|
| Local / SFTP / FTP / WebDAV | **永久刪除** | 無此概念（本來就是永久） | 跳過確認 |
| Google Drive / SharePoint / ODB / PikPak | 進回收桶 | 永久刪除 | 跳過確認 |
| OneDrive（個人版） | 進回收桶 | 會被拒絕（報錯） | 跳過確認 |
| Google Photos | 移除連結 | 移除連結 | — |

```bash
drive-unix rm gdrive:/old/file.txt              # 回收桶
drive-unix rm gdrive:/old/file.txt --permanent  # 永久
drive-unix rm work:/docs --force                # 不提示直接刪目錄
```

> 誤認常見點：Local 的 `rm` 雖然不帶 `--permanent`，仍然是永久刪除。同步引擎會在執行前統計「永久刪除的數量」並在提示裡標示；大量同步時先用 `--dry-run` 看清單。

## 3.4 複製、移動、上傳與下載

### cp / mv（Remote 取用）

```bash
drive-unix cp work:/docs/a.pdf gdrive:/archive/a.pdf
drive-unix mv work:/docs/tmp.pdf gdrive:/archive/
```

_behavior：同一台 Remote 內盡量走伺服器端直接複製/移動；跨 Remote 則用「下載→本機暫存→上傳」中繼。目標若是目錄，檔案會保留檔名放入該目錄。

`mv` 跨 Remote 採安全橋接：**先完整複製成功，才刪來源**。中途失敗不會兩邊同時被刪。

### upload（本機 → Remote）

```bash
drive-unix upload ./report.pdf work:/docs/report.pdf
drive-unix upload ./docs work:/docs --recursive --workers 8
```

- 單檔：自動建立遠端父目錄。
- 目錄：必須加 `--recursive / -r`；空目錄會建立空殼。
- `--workers / -w`（預設 4）：目錄上傳時的並發數。

### download（Remote → 本機）

```bash
drive-unix download work:/docs/report.pdf ./downloads/
drive-unix download work:/docs ./backup --recursive
drive-unix download work:/docs/report.pdf ./downloads/ --force
```

- 目標省略時落在當前工作目錄。
- 若本機同名同大小，已存在即跳過；要強制重下加 `--force`。
- 下載目錄必須加 `--recursive`（TTY 下會先提示你補上）。
- `--workers / -w`（預設 4）。

### download-link（分享）

```bash
drive-unix download-link personal:/docs/report.pdf
```

這會吐出 Provider 的暫存下載 URL。SFTP / FTP / WebDAV 的 URL 可能內含明文帳密，**不要公開傳播**，請轉成加密傳輸。Local 的分享連結是 `file://` 形式。
