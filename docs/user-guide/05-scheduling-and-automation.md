# 05 排程與自動化

[← 手冊目錄](README.md) | [← 上一章](04-diff-and-sync.md) | [下一章 →](06-command-reference.md)

本章內容：

- # 15. JSON、Plain 與自動化
- # 16. 排程
- # 17. 環境備份與還原

---

## 15. JSON、Plain 與自動化

### 15.1 提供 JSON 的命令

目前：

```text
ls
stat
diff
sync
bisync
```

#### `ls`

```bash
drive-unix ls work:/ --json
```

#### `stat`

```bash
drive-unix stat work:/docs/A.pdf --json
```

#### `diff`

```bash
drive-unix diff A:/ B:/ --json
```

#### Sync dry run

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

#### 實際 JSON sync

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

### 15.2 Sync JSON status

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

### 15.3 Exit code

一般原則：

| Exit code | 含義 |
|---:|---|
| `0` | 成功、noop、正常 dry-run 或使用者已正常取消某些互動流程 |
| `1` | 一般錯誤、部分執行失敗 |
| `2` | 特定可辨識情況，例如 sync conflict、Provider 不支援要求的 remote checksum / native search |

腳本不要只解析人類文字；有 `--json` 的命令應優先搭配 exit code 與 JSON `status`。

### 15.4 CI 建議

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

## 16. 排程

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

### 16.1 新增排程

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

#### 排程 command 建議

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

### 16.2 列出排程

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

### 16.3 Enable / Disable

```bash
drive-unix schedule disable nightly
drive-unix schedule enable nightly
```

### 16.4 移除

```bash
drive-unix schedule remove nightly
```

### 16.5 前景模式

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

### 16.6 背景 Service

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

#### OS backend

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

#### Log

Scheduler log 預設位於設定目錄下：

```text
~/.config/mycli/scheduler/scheduler.log
```

Windows 上 `~` 代表目前使用者 home directory。

查看狀態時也會顯示實際 log path：

```bash
drive-unix schedule service status
```

### 16.7 Missed run

Scheduler 會檢查先前 task 是否錯過符合的 Cron 時點；目前最多回看約 7 天。

這讓短暫中斷後重新啟動 scheduler 時，可以補執行近期錯過的 task。

---

## 17. 環境備份與還原

### 17.1 一般設定備份

```bash
drive-unix env export backup.zip
```

預設主要匯出設定，不包含敏感 secret store 與 auth cache。

### 17.2 包含 Secrets

```bash
drive-unix env export backup.zip --include-secrets
```

這可能包含：

- secret store
- OAuth client credential files

屬於高度敏感資料。

### 17.3 包含 Auth Cache

```bash
drive-unix env export backup.zip --include-auth-cache
```

這可能包含：

- Refresh token
- Cookie
- OAuth cache

同樣屬於敏感資料。

### 17.4 完整可攜備份

```bash
drive-unix env export full-backup.zip \
  --include-secrets \
  --include-auth-cache
```

請把這類檔案當作 credential bundle 保護，不應上傳公共雲端、Git repository 或聊天內容。

Export 會盡力把 archive 權限設定為只有目前使用者可讀寫。

### 17.5 Import

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

[← 手冊目錄](README.md)
