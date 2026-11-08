# 04 差異比較與同步

[← 上一章](03-browse-and-manage-files.md) | [手冊目錄](README.md) | [下一章 →](05-scheduling-and-automation.md)

## 4.1 先做 diff，再做 sync

`diff` 是唯讀的比較器，不會改動任何資料；`sync`/`bisync` 是執行器，會真正寫入。

```bash
drive-unix diff laptop:/docs gdrive:/docs
drive-unix diff laptop:/docs gdrive:/docs --show-same
drive-unix diff laptop:/docs gdrive:/docs --checksum --json
```

輸出會分群：`only_in_source`、`only_in_destination`、`different_size`、`different_modified_time`、`other_differences`，並附摘要。`--show-same` 才會把相同項目也列出來；`--json` 供腳本用。

比較原則（`diff` 與 `sync` 共用）：

1. 先比「型態」：檔案 vs 目錄衝突最先判定。
2. 目錄直接視為相同（不比內容）。
3. 檔案依序：大小 → 遠端 hash（若兩邊都有）→ 可選 checksum（需兩邊都支援）→ 修改時間。
4. 修改時間比較容忍 1.0 秒誤差；Office 檔案同步到 Microsoft（OneDrive/SharePoint/ODB）時，伺服器會重寫二進位，**大小本來就會變**，因此這類檔案只比修改時間。
5. Google Photos 只看修改時間（大小與 hash 不參考）。

建議習慣：任何需要 `--delete` 的同步，先跑裸 `diff` 看有哪些只在目標端的孤兒檔案，再跑 `sync --dry-run`。

## 4.2 單向同步 sync

```bash
drive-unix sync laptop:/docs gdrive:/backup --dry-run
drive-unix sync laptop:/docs gdrive:/backup --dry-run --full-plan
drive-unix sync laptop:/docs gdrive:/backup --yes
```

### 常用選項

| 選項 | 預設 | 說明 |
|---|---|---|
| `--dry-run` | off | 只印計畫，不執行。`--full-plan` 展開全部操作（否則只顯示摘要 + 高風險）|
| `--one-way` / `--two-way` | `--one-way` | 預設來源→目標；`--two-way` 變雙向（無 `--delete`，見下）|
| `--delete` | off | 鏡像：目標端多出的項目會被刪除 |
| `--include` / `--exclude` | — | glob 只比對檔名（basename）：`--include '*.pdf'`、`--exclude '*.tmp'` |
| `--conflict` | `auto` | 衝突策略（單向只用在無法判定的 type 衝突上）|
| `--checksum` | off | 內容哈希比對（見 [4.5](#45-checksum)）|
| `--workers / -w` | `4` | 傳輸並發數 |
| `--throttle` | `0`（本機不出限） | 每次操作的最小間隔（秒）|
| `--progress` | off | 顯示進度 |
| `--yes / -y` | off | 跳過確認（大量刪除時會提醒永久刪除數量）|
| `--json` | off | 機器可讀輸出；**實際執行時須搭配 `--yes`** |

### 鏡像（--delete）的風險

```bash
drive-unix sync laptop:/docs gdrive:/backup --delete --dry-run --full-plan
```

代表目標端「只保來源有的」。目標端若是 Local/SFTP/FTP/WebDAV，刪除是永久的；若是 Google/SharePoint，進回收桶（除非 Provider 不給還原）。所以永遠先 `--dry-run`。

### 布林旗標提醒

舊版或腳本中可能出現 `--one-way=False`（把等號當成參數傳入），那是錯誤寫法，請改用 `--two-way`。判斷方式：只要看到 `=False`/`=True` 出現，立刻改寫。

## 4.3 雙向同步 bisync

`bisync` 與 `sync --two-way` 等價，但語意更明確：

```bash
drive-unix bisync laptop:/docs cloud:/docs --dry-run
drive-unix bisync laptop:/docs cloud:/docs --yes
```

差異：`bisync` 沒有 `--delete`；一邊多出的檔案會補到另一邊，不會刪除孤兒。Google Photos 不可做雙向，會直接報錯（exit 2）。

### 衝突策略（--conflict）

預設 `auto`：「能安全判定誰新就用誰，判定不了就備份不猜」。

| 策略 | 行為 |
|---|---|
| `auto`（預設）| 修改時間差 >1 秒時選新者；不行就把舊版備份成 `_YYYYMMDD_HHMMSS` 後再覆蓋 |
| `newer` | 時間無法判定時直接 abort exit 2，逼你選策略 |
| `rename` | 永遠備份舊版再覆蓋 |
| `abort` | 一遇到衝突就中止（僅雙向）|
| `prefer-source` / `prefer-destination` | 固定偏向一方（僅雙向）|

範例：

```bash
# 先用 auto 預覽
drive-unix bisync A:/ B:/ --dry-run
# 明確要 abort 才中止並檢查
drive-unix bisync A:/ B:/ --conflict abort --dry-run
```

### 排程執行考量

同步會先掃描兩端（掃描並行）、再依賴分批（刪除→備份→建目錄→傳輸→後刪），任一 batch 失敗會跳過後面所有 batch（`partial-failure`）。長時間同步建議搭配 [排程與自動化](05-scheduling-and-automation.md) 的 `schedule add`，而不是自己寫 while 迴圈。

## 4.4 排除規則（include / exclude）

只影響檔名，不影響資料夾範圍：

```bash
drive-unix sync laptop:/docs gdrive:/backup --exclude '*.tmp' --include '*.pdf' --dry-run
```

- 設了 `--include`，不合的 basename 一律跳過。
- 設了 `--exclude`，合的 basename 一律跳過。
- 目錄被排除時，其子項目會各自被過濾。

## 4.5 Checksum

```bash
drive-unix checksum work:/docs/report.pdf
drive-unix checksum work:/docs/report.pdf --mode remote
drive-unix checksum work:/docs/report.pdf --mode download --algo sha256
```

- `--algo`：預設 `sha256`，可選 `md5|sha1|sha256|quickXorHash`。
- `--mode auto`（預設）：先問 Provider 有沒有遠端 hash，有就直接用，沒有就下載到暫存檔在本機算。
- `--mode remote`：Provider 不支援就直接報錯（exit 2），不降級。
- `--mode download`：永遠下載後本機計算。

**注意：** `sync --checksum` 只在兩邊都是 `local` 或 `sharepoint` 時啟用（會兩邊平行抓 `quickXorHash`）；其他組合的 `--checksum` 會被靜默忽略，只用大小與時間比對。若兩邊都支援，單向同步的 rename 偵測會利用 checksum 把「同名內容搬家」辨識為一次 rename，而不是刪除加複製。
