# 04 差異比較與同步

[← 手冊目錄](README.md) | [← 上一章](03-browse-and-manage-files.md) | [下一章 →](05-scheduling-and-automation.md)

本章內容：

- # 10. 差異比較 `diff`
- # 11. 單向同步 `sync`
- # 12. 雙向同步 `bisync`
- # 13. 衝突策略
- # 14. Checksum

---

## 10. 差異比較 `diff`

基本比較：

```bash
drive-unix diff source:/docs backup:/docs
```

顯示相同項目：

```bash
drive-unix diff source:/docs backup:/docs --show-same
## 或
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

#### 一般單向 comparison policy

對一般檔案，主要考慮：

1. File / directory type 是否不同。
2. Size 是否不同。
3. 使用 `--checksum` 時，以 Checksum 進一步比較。
4. 有修改時間時，來源比目標新會視為需要更新。

Microsoft Office 檔案在 Microsoft Provider 上有特殊處理，因為 server-side processing 可能讓 binary size 改變，因此不完全依賴 size。

`--checksum` 比一般 metadata comparison 更精確，但會增加 Provider API / I/O 成本。

---

## 11. 單向同步 `sync`

最基本：

```bash
drive-unix sync source:/docs backup:/docs
```

預設是：

```text
source -> destination
```

也就是來源是 canonical side。

### 11.1 強烈建議先 Dry Run

```bash
drive-unix sync source:/docs backup:/docs --dry-run
```

Dry run 只建立並顯示同步計畫，不修改檔案。

正式執行：

```bash
drive-unix sync source:/docs backup:/docs
```

### 11.2 `--delete`

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

### 11.3 Include / Exclude

只同步 PDF：

```bash
drive-unix sync source:/docs backup:/docs --include '*.pdf'
```

排除 temporary files：

```bash
drive-unix sync source:/docs backup:/docs --exclude '*.tmp'
```

目前 pattern 是以**項目檔名**進行 `fnmatch`，不是完整相對路徑 pattern。

### 11.4 Checksum comparison

```bash
drive-unix sync source:/docs backup:/docs --checksum
```

適合：

- metadata 時間戳不可靠的 Provider
- 高完整性要求
- 需要較準確 rename detection 的 mirror

使用 `--checksum` 會增加掃描成本。

### 11.5 Progress

```bash
drive-unix sync source:/docs backup:/docs --progress
```

`--plain` 或非 TTY 環境會自動停用 live progress。

### 11.6 Workers

```bash
drive-unix sync source:/docs backup:/docs --workers 8
```

預設：

```text
4
```

workers 必須 >= 1。

### 11.7 Throttle

每個操作間強制延遲：

```bash
drive-unix sync source:/docs backup:/docs --throttle 0.5
```

適合容易 rate limit 的服務。

### 11.8 Full Plan

大量同步時預設偏向摘要與重要風險。

若要逐項檢查：

```bash
drive-unix sync source:/docs backup:/docs --dry-run --full-plan
```

### 11.9 跳過確認

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

### 11.10 `--one-way` / `--two-way`

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

#### Boolean flag 注意

請勿使用：

```bash
## 錯誤
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

## 12. 雙向同步 `bisync`

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

#### 雙向同步不支援 `--delete`

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

#### 範例

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

## 13. 衝突策略

可用：

```text
auto
newer
rename
abort
prefer-source
prefer-destination
```

### 13.1 `auto`（預設）

```bash
drive-unix bisync A:/ B:/ --conflict auto
```

行為：

- 修改時間能安全判定較新側 → 使用較新版本。
- 內容不同，但時間戳缺失或差距在安全容忍範圍內 → 不猜 winner，先保留衝突舊版本，再更新 canonical path。
- File / directory type conflict 在雙向 auto 中也優先備份 losing side，再替換。

這是一般雙向同步的推薦預設。

### 13.2 `newer`

```bash
drive-unix bisync A:/ B:/ --conflict newer
```

只接受可以安全判斷哪一邊較新的情況。

若內容不同但無法判定 winner，會停止並回傳 conflict error，而不是默認 source wins。

適合：

- 兩端修改時間可信
- 希望不產生 conflict copy
- 遇到 ambiguity 時寧願中止

### 13.3 `rename`

```bash
drive-unix bisync A:/ B:/ --conflict rename
```

更新前先把將被覆蓋的一側重新命名保留。

Conflict backup 名稱會帶原 modification timestamp；若無時間則使用 fallback suffix。

適合最保守的人工作業流程。

### 13.4 `abort`

```bash
drive-unix bisync A:/ B:/ --conflict abort
```

只要遇到雙方同路徑內容不同，就停止 planning。

適合：

- 資料極重要
- 希望所有 conflict 都由人決定

`abort` 僅適用雙向同步。

### 13.5 `prefer-source`

```bash
drive-unix bisync A:/ B:/ --conflict prefer-source
```

衝突時固定採左側 / source 版本。

這是**明確覆蓋策略**，請只在你確定左側是 authoritative side 時使用。

單向 sync 也可使用此策略。

### 13.6 `prefer-destination`

```bash
drive-unix bisync A:/ B:/ --conflict prefer-destination
```

衝突時固定採右側 / destination 版本。

僅適用雙向同步。

### 13.7 選擇建議

| 情境 | 建議策略 |
|---|---|
| 一般雙向同步 | `auto` |
| 不想猜時間戳衝突 | `newer` |
| 最重視保留舊版本 | `rename` |
| 所有 conflict 都要人工處理 | `abort` |
| 左側是 authoritative | `prefer-source` |
| 右側是 authoritative | `prefer-destination` |

---

## 14. Checksum

### 14.1 基本用法

```bash
drive-unix checksum work:/docs/A.pdf
```

預設：

```text
--algo sha256
--mode auto
```

### 14.2 Algorithm

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

### 14.3 `--mode auto`

```bash
drive-unix checksum work:/docs/A.pdf --mode auto
```

流程：

1. 先向 Provider 取得 remote hash。
2. 若 Provider 不提供指定 algorithm，自動下載到暫存目錄。
3. 在本機計算。
4. 暫存資料由 temporary directory 清理。

這是一般使用的推薦模式。

### 14.4 `--mode remote`

```bash
drive-unix checksum work:/docs/A.pdf --mode remote
```

只允許 Provider-side hash，不下載檔案。

若 Provider 不支援，命令會以 exit code `2` 結束並提示改用 download / auto。

### 14.5 `--mode download`

```bash
drive-unix checksum work:/docs/A.pdf --mode download
```

強制下載檔案後本機計算。

適合：

- Provider hash algorithm 不符合需求
- 想統一使用同一套本機 hash implementation

### 14.6 舊版 flags

仍相容：

```bash
drive-unix checksum work:/A.pdf --remote
drive-unix checksum work:/A.pdf --download
```

新腳本建議改用 `--mode`。

`--remote` 與 `--download` 不可同時使用。

---

[← 手冊目錄](README.md)
