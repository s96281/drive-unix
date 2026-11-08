# 03 瀏覽、建立與傳輸檔案

[← 手冊目錄](README.md) | [← 上一章](02-providers-and-secrets.md) | [下一章 →](04-diff-and-sync.md)

本章內容：

- # 7. 瀏覽、搜尋與資訊查詢
- # 8. 建立與刪除
- # 9. 複製、移動、上傳與下載

---

## 7. 瀏覽、搜尋與資訊查詢

### 7.1 `ls`：列出目錄

```bash
drive-unix ls work:/docs
```

JSON：

```bash
drive-unix ls work:/docs --json
```

`--json` 適合 script 使用，失敗時也輸出 JSON error object。

### 7.2 `tree`：樹狀瀏覽

```bash
drive-unix tree work:/docs
```

限制深度：

```bash
drive-unix tree work:/docs --depth 2
## 或
drive-unix tree work:/docs -L 2
```

只顯示檔案：

```bash
drive-unix tree work:/docs --files-only
```

只顯示資料夾：

```bash
drive-unix tree work:/docs --dirs-only
## 或
drive-unix tree work:/docs -d
```

限制最多載入項目：

```bash
drive-unix tree work:/ --max-items 500
```

預設 `--max-items 1000`，用來避免意外展開極大型目錄。

`--files-only` 與 `--dirs-only` 不可同時使用。

### 7.3 `find`：跨 Provider 客戶端遞迴搜尋

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

### 7.4 `search`：Provider 原生搜尋

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

### 7.5 `stat`：查看項目資訊

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

## 8. 建立與刪除

### 8.1 `mkdir`

建立一層：

```bash
drive-unix mkdir work:/docs/new-folder
```

自動建立父目錄：

```bash
drive-unix mkdir work:/a/b/c --parents
## 或
drive-unix mkdir work:/a/b/c -p
```

### 8.2 `rm`

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

#### 刪除安全規則

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

## 9. 複製、移動、上傳與下載

### 9.1 `cp`

同 Remote：

```bash
drive-unix cp work:/docs/A.pdf work:/archive/A.pdf
```

跨 Remote：

```bash
drive-unix cp work:/docs/A.pdf gdrive:/backup/A.pdf
```

`drive-unix` 會由 TransferService 選擇同 Provider 直接操作或跨 Provider bridge transfer。

### 9.2 `mv`

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

### 9.3 `upload`

上傳單一檔案：

```bash
drive-unix upload ./report.pdf work:/docs/report.pdf
```

資料夾必須明確指定遞迴：

```bash
drive-unix upload ./Photos work:/backup/Photos --recursive
## 或
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

### 9.4 `download`

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

### 9.5 `download-link`

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

[← 手冊目錄](README.md)
