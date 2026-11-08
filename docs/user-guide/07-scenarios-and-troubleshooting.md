# 07 常見情境與錯誤排查

[← 手冊目錄](README.md) | [← 上一章](06-command-reference.md)

本章內容：

- # 20. 常見使用情境
- # 21. 錯誤排查
- # 22. 相容舊版命令

---

## 20. 常見使用情境

### 20.1 本機資料夾備份到 Google Drive

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

### 20.2 Laptop 與 Cloud 雙向文件同步

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

### 20.3 比較兩份資料是否一致

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

### 20.4 每晚 02:00 備份

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

### 20.5 只備份 PDF

```bash
drive-unix sync work:/docs archive:/docs \
  --include '*.pdf' \
  --dry-run
```

### 20.6 排除暫存檔

```bash
drive-unix sync work:/docs archive:/docs --exclude '*.tmp'
```

目前 `--exclude` / `--include` 各接受一個 glob pattern，請不要假設重複提供 option 會累積多組規則。需要多組 filter rule 時，應拆成不同同步流程或後續擴充 filter-list 功能。

### 20.7 找出最近的大型 PDF

```bash
drive-unix find work:/docs \
  --name '*.pdf' \
  --type file \
  --size-gt 20MB \
  --modified-after 2026-01-01
```

### 20.8 CI 中安全檢查 mirror plan

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

## 21. 錯誤排查

CLI 的人類可讀 error 預設採：

```text
問題
原因
下一步
```

排查時建議依下列順序。

### 21.1 找不到 Remote

```bash
drive-unix remote list
```

確認名稱後再：

```bash
drive-unix remote test NAME
```

### 21.2 認證錯誤

```bash
drive-unix remote test NAME
```

檢查：

- OAuth 是否完成
- Password env 是否存在
- Secret reference 是否仍有效
- Browser auth Provider 是否已安裝 Playwright Chromium

### 21.3 寫入 / 刪除失敗

```bash
drive-unix remote test NAME --write
```

確認帳號具備：

- create directory
- write
- delete / trash

權限。

### 21.4 Provider 套件缺失

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

### 21.5 `search` 不支援

使用：

```bash
drive-unix find REMOTE:/path --name keyword
```

### 21.6 `checksum --mode remote` 不支援

改：

```bash
drive-unix checksum REMOTE:/file --mode auto
```

或：

```bash
drive-unix checksum REMOTE:/file --mode download
```

### 21.7 Sync conflict exit code 2

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

### 21.8 Sync 有永久刪除風險

不要直接加 `-y`。

先：

```bash
drive-unix sync A:/ B:/ --delete --dry-run --full-plan
```

確認 `irreversible_deletes` / 人類可讀風險摘要，再正式執行。

### 21.9 Scheduler 沒有執行

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

### 21.10 `--one-way=False` 錯誤

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

## 22. 相容舊版命令

目前新版 root help 不再顯示以下命令，但為了既有 script 相容仍可使用。

### Remote aliases

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

### Environment aliases

```text
export-env
import-env
```

推薦：

```text
env export
env import
```

### Scheduler aliases

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

### Two-way sync compatibility

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

## 最佳實務摘要

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

---

[← 手冊目錄](README.md)
