# 01 系統總覽與分層架構

## 1.1 分層

drive-unix 採嚴格分層，CLI 只做輸入解析與呈現，Application 做跨 Provider 協調，Domain 放純商業規則，Storage 以 contract + registry 區隔 Provider 細節。

```mermaid
flowchart TB
    subgraph Presentation[表現層]
        CLI[cli/<br/>Typer + Rich]
        Web[web/<br/>FastAPI + SSE]
    end
    subgraph Application[Application 層]
        Transfer[TransferService]
        Sync[SyncService / SyncExecutor<br/>SyncHooks]
        SchedSvc[SchedulerService]
        UpstashSvc[UpstashSyncService<br/>UpstashTokenService]
    end
    subgraph Domain[Domain 層]
        Models[FileItem / StorageStat<br/>domain/models.py]
        Scanner[Scanner<br/>domain/sync/scanner.py]
        Planner[Planner<br/>domain/sync/planner.py]
        Plan[SyncPlan / batches<br/>domain/sync/models.py]
    end
    subgraph Storage[Storage 層]
        Contract[StorageProvider contract<br/>storage/base.py]
        Registry[ProviderRegistry<br/>storage/registry.py]
    end
    subgraph Providers[Provider 實作]
        P1[Local / FTP / SFTP / WebDAV]
        P2[Microsoft 365<br/>SharePoint / OneDrive*]
        P3[Google Drive / Photos]
        P4[PikPak]
    end
    subgraph Infra[基礎設施]
        HTTP[HTTP client + RetryPolicy]
        RL[RateLimiter]
        BW[BandwidthLimiter]
        Crypto[E2EE AES-256-GCM<br/>PBKDF2]
        UpstashClient[UpstashClient]
    end
    subgraph Auth[驗證層]
        Base[AuthContext / AuthProvider]
        Cache[AuthCache<br/>CachedAuthProvider]
        Identity[identity 去重]
        TokenSvc[UpstashTokenService<br/>分散式鎖]
    end

    Presentation --> Application
    Application --> Domain
    Application --> Storage
    Application --> Infra
    Application --> Auth
    Storage --> Contract
    Registry --> Providers
    Providers --> Infra
    Providers --> Auth
```

| 層 | 職責 | 代表檔案 |
|---|---|---|
| CLI | 參數解析、互動提示、Rich 呈現、調 Application | `cli/app.py`, `cli/commands/*.py`, `cli/presentation.py`, `cli/context.py` |
| Application | 同步、跨 Provider 傳輸、排程、Upstash 同步協調 | `application/*.py` |
| Domain | Snapshot、Sync Plan、純商業規則（無 I/O） | `domain/models.py`, `domain/sync/*.py` |
| Storage | Provider contract、registry、統一列舉／上傳／下載／刪除 | `storage/base.py`, `storage/registry.py` |
| Providers | 各雲端／協定實作 | `providers/*.py`, `providers/microsoft365/client.py`, `providers/google/photos.py` |
| Infrastructure | HTTP、重試、限流、加密、Upstash 操作 | `infrastructure/*.py`, `core/crypto.py` |
| Auth | OAuth / Cookie 驗證、安全 cache、identity | `auth/*.py`, `auth/providers/*.py` |

## 1.2 呼叫鏈

### CLI 同步

```mermaid
sequenceDiagram
    participant U as 使用者
    participant CLI as cli/commands/sync.py
    participant App as application/sync_service.py
    participant Dom as domain/sync/*
    participant Prov as StorageProvider
    U->>CLI: drive-unix sync SRC DST --delete --checksum
    CLI->>App: SyncService.scan()
    App->>Prov: list_dir 遞迴掃描
    Prov-->>App: FileItem 樹
    App->>App: SyncSnapshot
    CLI->>App: build_plan(options)
    App->>Dom: SyncPlanner.build_plan()
    Dom-->>App: SyncPlan(batches)
    CLI->>App: execute(plan, workers, hooks)
    App->>Prov: mkdir / copy / delete / move
    Prov-->>App: bool / 例外
    App-->>U: SyncExecutionResult(succeeded/failed/skipped)
```

### Web 瀏覽

```mermaid
sequenceDiagram
    participant B as 瀏覽器
    participant R as web/routers/files.py
    participant C as DirectoryCacheManager
    participant Pool as WebStoragePool
    participant P as StorageProvider
    B->>R: GET /api/fs/{remote}/ls?path=/a
    R->>C: directory_cache.get(remote, path)
    alt 快取命中
        C-->>R: FileItem 列表
    else 未命中
        R->>Pool: acquire(remote)
        Pool->>P: list_dir()
        P-->>Pool: items
        R->>C: put(remote, path, items)
    end
    R-->>B: ListDirResponse
```

### 排程觸發

```mermaid
sequenceDiagram
    participant OS as OS 服務
    participant D as SchedulerService.tick()
    participant S as subprocess
    OS->>D: 每秒 tick 或排程時間到
    D->>D: is_cron_match / has_missed_run
    alt 應執行
        D->>S: [python, main.py, sync ...]
        S-->>D: exit code
    end
```

## 1.3 核心物件

| 物件 | 定義 | 說明 |
|---|---|---|
| `FileItem` | `domain/models.py` | 檔名、path、is_dir、size、modified_at、thumbnail_url |
| `StorageStat` | `storage/base.py` | 單檔 stat 結果 |
| `AuthContext` | `auth/base.py` | headers / cookies / query_params / expires_at / metadata，刻意不預設驗證方式 |
| `SyncSnapshot` | `domain/sync/models.py` | `base_path + items{rel_path:FileItem} + complete` |
| `SyncPlan` | `domain/sync/models.py` | `SyncExecutionBatch` 序列，見第 05 章 |
| `SyncAction` | `domain/sync/models.py` | 9 種動作 `SyncActionType`，見第 05 章 |

## 1.4 元件關係速查

```mermaid
flowchart LR
    subgraph Entry[入口]
        CLI[CLI]
        Web[Web]
    end
    Entry -->|create| Registry[ProviderRegistry]
    Registry -->|create| Provider[StorageProvider]
    Provider -->|auth_provider| Cached[CachedAuthProvider]
    Cached -->|provider| Raw[Raw AuthProvider]
    Cached -->|cache| AuthCache[AuthCache]
    Cached -->|remote_token_service| TokenSvc[UpstashTokenService]
    TokenSvc -->|encrypt/decrypt| Crypto[E2EE]
    TokenSvc -->|GET/SET/LOCK| Upstash[(Upstash Redis)]
    TokenSvc -->|raw file| TokenFile[~/.auth_cache/*.json]
    Raw -->|profile_dir| BrowserProfile[browser-profiles/<sha256>]
```
