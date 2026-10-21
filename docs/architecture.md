# Architecture Notes

## Phase 4: Secret References and Credential Hardening

Phase 4 將長期憑證從 `config.toml` 移出。Remote 設定只保存 `password_ref` / `client_secret_ref`，Provider 建立時才由 `ConfigManager` 解析 secret reference。

```text
config.toml
  -> password_ref = "env:WORK_PASSWORD"
  -> client_secret_ref = "keyring:remote/ms/client-secret"
                      ↓
              SecretRepository
                ├─ env:      environment variable (read-only)
                ├─ keyring:  OS credential store (preferred)
                └─ file:     0600 JSON fallback
```

主要規則：

- CLI 不再接受 `--password <value>` / `--secret <value>`；互動密碼使用 hidden prompt，自動化使用 `--password-env` / `--secret-env`。
- OS keyring 可用時，互動 secret 優先保存於 keyring；無可用 backend 的 headless 環境才使用 `secrets.json` fallback，檔案權限鎖定為 `0600`、目錄為 `0700`。
- 舊版 `password` / `client_secret` 會在首次載入時自動遷移到 secret store，並原子重寫 `config.toml` 移除明文值。
- Remote 被刪除時，同步刪除其持有的 file/keyring secret reference；`env:` reference 不修改程序環境。
- Google OAuth client credential files 改存放於 `secret-files/`。`export-env` 預設排除 `secrets.json`、`secret-files/` 與舊版 `secrets/`；只有明確指定 `--include-secrets` 才會打包可攜式 secret material。OS keyring 本身不會被匯出。
- Auth cache 仍獨立於 static secret store，預設不匯出，並維持既有 `0600` / metadata sanitization 防護。

## Phase 3: Scheduler Robustness and Resource Ownership

Phase 3 明確區分「資源擁有者」與「使用者」。`SyncExecutor` 只使用外部注入的 Storage Provider，不再自行 `close()`；CLI composition root 才負責 Provider 的生命週期。

```text
CLI command
  -> acquire provider(s)
  -> scan / plan / dry-run / execute
  -> close provider(s)

Application service
  -> borrow provider(s)
  -> never assume ownership
```

`StorageProvider` 支援 context-manager protocol，並提供 `managed_storage()` 給輕量 test double / legacy provider 使用。因此同步在 empty-plan、dry-run、scan failure、execution failure 等所有 return/exception 路徑都會確定性釋放資源。

HTTP transport 不再只保存呼叫執行緒的 Session。`HttpClient` 會註冊所有 worker thread 建立的 `requests.Session`，provider 關閉時統一釋放，避免長生命週期 process 累積 connection pool。SharePoint、OneDrive Business、OneDrive 與 WebDAV 都將 `close()` 傳遞到共用 HTTP client。

### Scheduler state model

Cron task 保留舊 `last_run` 欄位以維持既有 `config.toml` 相容性，同時新增：

- `last_attempt_at`：最近一次被 scheduler 接受並準備執行的時間。
- `last_success_at`：最近一次 exit code 0 的完成時間。
- `last_exit_code`：最近一次 process 結束碼；啟動/執行層例外使用 `-1`。

補跑判斷優先使用 `last_attempt_at`，舊設定則 fallback 到 `last_run`。Command normalization 會在 running-state mutation 之前完成，因此無效 command 不會留下永久 running task。每個 task 的評估都有 exception boundary，一個壞 task 不會阻止同一 tick 中的其他 task；daemon loop 另有最外層防護，避免非預期 exception 永久停止 scheduler。

Scheduler process lifecycle 由 `application/scheduler_daemon.py` 管理。`schedule start` 直接在前景執行 `SchedulerService`；`schedule service` 提供背景 lifecycle。Linux 使用 user-level systemd、macOS 使用 LaunchAgent、Windows 使用 Task Scheduler；未安裝 OS service 時可 fallback 為 detached child。service child 以 PID file 暴露本機 process state，stdout/stderr 寫入 scheduler log。

## Phase 2: Dependency-aware Sync Execution

同步計畫不再只是單一 `SyncAction` 序列。`SyncPlan` 會依操作之間的路徑相依性建立 `SyncExecutionBatch`，同一 batch 可平行執行，而 batch 之間形成明確 barrier。

```text
prepare-delete (deep -> shallow)
        ↓
prepare-backup / rename
        ↓
mkdir (shallow -> deep)
        ↓
transfer
        ↓
cleanup-delete (deep -> shallow)
```

主要規則：

- 型態替換所需的 delete 必須先完成，才允許後續 mkdir/copy。
- `conflict=rename` 的 backup rename 必須先完成，才允許 canonical path 寫入。
- 新資料夾依深度由淺到深建立。
- 一般 `--delete` 清理延後到傳輸成功後執行；若 transfer batch 失敗，cleanup batch 會被略過，避免在同步失敗時繼續刪除既有資料。
- 同一 batch 內最多維持 `workers` 個 in-flight Future，避免大型 plan 一次建立所有 Future。
- `SyncExecutionResult` 同時回報 `succeeded`、`failed`、`skipped`，後續相依 batch 因前置失敗而未執行時不再被誤認為成功。

### Batch transfer failure semantics

`TransferService` 將 Provider 明確回傳 `False` 視為真正的 transfer failure，而不是只有 Exception 才算失敗。CLI 的 recursive upload/download 使用共用 batch executor 聚合所有 worker failure；任一檔案失敗時 command 會以非零 exit code 結束。

## Phase 6: CLI Decomposition and Final Architecture Alignment

Phase 6 將 CLI layer 從 `main.py` 完整拆出。`main.py` 現在只負責建立 Typer application、啟用 logging 與啟動程式，所有 command 定義依用途分散到 `cli/commands/`。

```text
main.py
  -> cli/app.py
      -> cli/commands/
          ├── files.py
          ├── transfer.py
          ├── sync.py
          ├── nodes.py
          ├── environment.py
          └── cron.py
              ↓
          application/
              ↓
          domain/
              ↓
          storage/base.py
              ↓
          storage/registry.py
              ↓
          providers/
              ↓
          infrastructure/
```

### CLI composition root

- `main.py`：只建立 application 並啟動 CLI。
- `cli/app.py`：註冊所有 command modules 與全域 `--plain` presentation policy。
- `cli/context.py`：提供 `ConfigManager`、remote path parsing 與 Storage Provider 建立所需的共用 runtime context。
- `cli/presentation.py`：集中管理 color / plain / non-TTY output 與 actionable error blocks。

### CLI command modules

- `cli/commands/files.py`：`ls`、`tree`、`find`、`search`、`mkdir`、`rm`、`stat`
- `cli/commands/transfer.py`：`cp`、`mv`、`upload`、`download`、`download-link`
- `cli/commands/sync.py`：`sync`、`diff`、`checksum`
- `cli/commands/nodes.py`：remote node 新增、列出、修改、移除與重新命名
- `cli/commands/environment.py`：環境設定 export/import 與安全 ZIP extraction
- `cli/commands/cron.py`：Cron task CLI、前景 scheduler 與 background service lifecycle boundary

Command modules 只處理 CLI boundary：參數、互動提示、輸出與 application/service orchestration；實際商業邏輯應持續向 `application/`、`domain/` 或 infrastructure 層下移。

## Phase 5: Architecture and Type-Safety Cleanup

Phase 5 removes the remaining dependency-direction and typing debt left after the
correctness/security phases.  The dependency flow is now:

```text
CLI / presentation
    -> application
        -> domain
        -> storage contract
            -> providers / infrastructure
```

### Scheduling boundary

Cron parsing/matching rules live in `application/scheduling.py`.  `SchedulerService`
therefore no longer imports any module from `cli/`.  `cli/scheduling.py` remains only
as a backwards-compatible re-export shim; new code imports the application module.

### Storage contract

`storage/base.py` is the single source of truth for provider-facing types:

- `ProgressCallback = Callable[[int, int], None]`
- `StorageStat` normalizes metadata, including the `filecount` key.
- Application services explicitly type injected dependencies as `StorageProvider`.
- Every provider uses `ProgressCallback | None` for upload/download and `StorageStat`
  for `stat()`.  The old built-in `callable` annotations are gone.

Provider implementations no longer print progress or status directly.  Operational
diagnostics use the `drive_unix.*` logger namespace; user-facing progress stays at the
CLI boundary through callbacks and Rich adapters.

### Transfer use cases

The Phase-2 compatibility functions `_call_upload`, `_call_download`, and
`_execute_copy` have been removed.  `TransferService` now owns the reusable transfer
use cases directly:

- cross-provider copy / move;
- recursive upload planning and execution;
- recursive download planning, size-based skip decisions, and execution;
- remote directory existence checks;
- bounded batch execution and failure aggregation.

`cli/commands/transfer.py` now handles arguments, confirmation and rendering rather
than filesystem/provider planning.  Worker-row Rich rendering is isolated in
`cli/transfer_ui.py`.

### Sync presentation decomposition

The large `sync_items` command was reduced by extracting plan rendering, scan progress,
and `SyncHooks` implementations into `cli/sync_ui.py`.  The command remains the
composition root while `SyncService` continues to own scan/plan/execute orchestration.

### Enforced architecture rules

Phase-5 regression tests enforce that:

- the Application package cannot import `cli`;
- storage/auth providers cannot call `print()` directly;
- providers use the shared callback/stat annotations;
- removed Phase-2 transfer wrappers do not reappear;
- the refactored CLI hotspots stay below bounded source-size thresholds.
