# UX / Safety Implementation Notes

本版本依 UI/UX 體檢後的優先順序，先處理資料安全與高風險互動，再降低 CLI 認知負擔與改善 automation 介面。

## P0 — 已完成

### Provider-aware deletion semantics

- `StorageProvider` 新增 `DeleteCapability`：`PERMANENT_ONLY`、`TRASH_ONLY`、`TRASH_AND_PERMANENT`。
- `rm` 的確認文案依 Provider 真實能力顯示，不再把 Local / FTP / SFTP / WebDAV 的永久刪除誤稱為移至回收桶。
- `--permanent` 在不支援永久刪除的 Provider 會被拒絕。
- `sync` 會在執行前顯示來源端 / 目標端刪除的可復原性，並計算不可復原的刪除數量。

### Safe two-way conflict behavior

- 雙向同步預設 conflict policy 改為 `auto`。
- 若內容不同且能安全判定較新版本，`auto` 使用較新版本。
- 若內容不同但無法判定新舊，`auto` 會先重新命名保留衝突版本，再完成同步；不再隱式 source-wins。
- 明確指定 `--conflict newer` 且無法判定新舊時，會以 exit code 2 中止，要求使用者選擇策略。
- 新增 `abort`、`prefer-source`、`prefer-destination` policy。
- source-side type replacement 新增 `DELETE_SRC`，使雙向衝突能對稱處理。

### Sync destructive preflight

- Sync Plan 先顯示傳輸、資料夾、重新命名、刪除、bytes 摘要。
- 大量操作預設只顯示摘要與高風險項目，`--full-plan` 可展開完整計畫。
- 若包含永久刪除，確認提示會顯示不可復原的項目數。

## P1 — 已完成 / 核心部分完成

### Task-oriented CLI

- 新增 `bisync` 作為正式雙向同步入口；`sync --two-way` 保留相容。
- 新增 `remote add/list/remove/rename/edit/test` 群組。
- 新增 `schedule add/list/remove/enable/disable/start` 群組。
- 新增 `env export/import` 群組。
- 舊版 `add-*`、`list-nodes`、`cron-*`、`export-env` / `import-env` 等 root commands 保留為 hidden aliases，避免破壞既有腳本。

### Onboarding

- 新增 `drive-unix init` 首次使用導引。
- 新增互動式 `remote add` wizard。
- 新增 `remote test NAME [--write]`，可驗證認證、讀取及選擇性的寫入能力。
- `add-local` 對不存在路徑會確認；automation 可使用 `--allow-missing`。

### Automation and consistency

- `ls`、`stat`、`diff`、`sync`、`bisync` 新增 JSON output。
- `sync --json` 實際執行需搭配 `--yes`，避免 script 卡在互動確認。
- conflict / generic failures 在 JSON mode 維持 JSON 輸出，並使用非零 exit code。
- `checksum` 新增 `--mode auto|remote|download`；預設 `auto` 在 remote hash 不支援時自動 fallback 到下載後本機計算。
- `download` 的資料夾遞迴行為與 upload 對齊，支援 `--recursive/-r`；非 TTY 不再偷偷互動。
- 單向同步使用 `→`，雙向同步使用 `↔`。
- 修正排程成功訊息中舊的 `mycli cron-start` 指令；`schedule start` 明確描述為前景程序。

## P2 — 已完成

### Plain / accessibility-friendly presentation

- 新增全域 `--plain`：移除 emoji / ANSI styling 並停用動態 progress。
- 支援 `NO_COLOR`；只關閉色彩，不強制改變文案。
- Rich transfer / sync progress 在非 TTY stdout 自動停用，避免 CI log 出現 carriage-return 動畫。
- CLI output 統一經 `cli/presentation.py`，避免各 command 自行決定 color/plain policy。

### Error microcopy rewrite

- command-level error 統一為「問題 → 原因 → 下一步」結構。
- `ls` / `stat` / `diff` 的 `--json` failure 維持 JSON-only output。
- Remote、Transfer、Environment、Sync、Scheduler 錯誤加入可執行的 recovery action。
- Diff 人類可讀輸出的主要 heading / summary 改為一致中文。

### Background scheduler service

- `schedule start` 保留為前景模式。
- 新增 `schedule service install/start/status/stop/uninstall`。
- Linux：user-level systemd service。
- macOS：LaunchAgent。
- Windows：Task Scheduler。
- 未安裝 OS service 時，`service start` fallback 為 detached process。
- service child 使用 PID file 與 scheduler log，並保留既有 task state / missed-run semantics。

## 驗證

- `python -m pytest -q`: **119 passed, 1 skipped**。
- Skip 原因：測試環境未安裝 optional `paramiko`，因此 SFTP connection reuse 測試略過。
- `python -m compileall`: 通過。
- `drive-unix --help`、`remote --help`、`schedule service --help`、`bisync --help`、`checksum --help`: smoke check 通過。
- 此環境沒有安裝 `ruff` 與 `mypy`，因此未能執行這兩個 dev-only static checks。

## 仍可後續深化

目前低優先級 UX debt 已完成主要落地。後續若要再深化，可考慮 machine-readable scheduler status (`--json`)、Windows service wrapper（取代 Task Scheduler）、以及完整 i18n locale layer；這些不影響目前核心安全性與 CLI lifecycle。
