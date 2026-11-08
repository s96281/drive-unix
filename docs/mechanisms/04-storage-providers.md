# 04 儲存 Provider

## 4.1 Contract：`StorageProvider`

`storage/base.py` 定義所有後端必須實作的抽象 contract、`DeleteCapability`、進度回呼與資料模型。

```mermaid
flowchart TB
    subgraph Contract[StorageProvider contract]
        List[list_dir]
        Up[upload]
        Down[download]
        Del[delete]
        Move[move]
        Copy[copy]
        Mkdir[mkdir]
        Stat[stat]
        Hash[get_hash]
        Link[get_share_link / get_download_link]
        Thumb[get_thumbnail_link]
        Search[search]
        Close[close]
    end
    Contract --> Managed[managed_storage<br/>contextmanager 保證 close]
    Contract --> FileList[list → FileList<br/>夾帶 total_count 供分頁]
    Contract --> Capability[delete_capability<br/>trash / permanent_only]
```

- `ProgressCallback = Callable[[int, int], None]`（transferred, total）。
- `FileList` 是 `list[FileItem]` 子類，可帶 `total_count`，Web 分頁直接用它決定總數或背景預熱。
- `managed_storage(provider)` contextmanager 在退出時呼叫 `provider.close()`，Web pool 時由 `PooledStorageProxy` 攔截以復用連線。

## 4.2 Registry 與建立流程

`storage/registry.py::ProviderRegistry`、`core/factory.py::get_storage_provider()`：

```mermaid
flowchart TB
    A[get_storage_provider<br/>remote_name] --> B[ConfigManager.get_remote<br/>失敗 → ValueError]
    B --> C[Registry.get type<br/>未知 type → 列出支援類型]
    C --> D{取 builder}
    D -->|sharepoint/onedrive_business| E[_build_* Cookie Provider<br/>OAuth/檔案 + CachedAuthProvider<br/>+ identity_key + profile_dir]
    D -->|onedrive| F[OneDriveAuthProvider<br/>token_cache_path *_onedrive_token.json]
    D -->|google_drive/photos| G[Google*AuthProvider<br/>credentials + token_cache_path]
    D -->|pikpak| H[PikPakAuthProvider]
    D -->|ftp/webdav/sftp/local| I[直接解 secret<br/>建連線型 Storage]
    D -->|alist| J[NotImplementedError]
    E --> K[回傳 StorageProvider]
    F --> K
    G --> K
    H --> K
    I --> K
```

- 密碼走 `_secret_or_legacy_env()`（見第 02 章）：先 `resolve_secret(password_ref)`，再 fallback 舊版 env（如 `SHAREPOINT_PASSWORD`）。
- 需要 OAuth 的 Provider（OneDrive、Google）都會帶 `raw_cache_path`，讓 Upstash Token 同步能一併還原底層 raw token 檔。
- SharePoint／OneDrive Business 用 `DEFAULT_SHAREPOINT_EXPIRY_SECONDS`（1d）做 cache TTL。

## 4.3 各 Provider 一覽

| 類型 | 實作 | 驗證 | 刪除語義 | 備註 |
|---|---|---|---|---|
| `local` | `providers/local.py:LocalStorage` | 無 | 資料夾／檔案操作 | `root_path` 錨點 |
| `ftp` | `providers/ftp.py:FTPStorage` | 帳密 / anonymous | `PERMANENT_ONLY` | PASV/TLS 選項 |
| `sftp` | `providers/sftp.py:SFTPStorage` | 帳密或 key | `PERMANENT_ONLY` | `paramiko` |
| `webdav` | `providers/webdav.py:WebDAVStorage` | 帳密 | 視伺服器（trash／permanent） |  |
| `sharepoint` | `providers/sharepoint.py:SharePointStorage` + `microsoft365/client.py` | Cookie（Playwright） | `trash`（可還原） | `rtFa+FedAuth`，OAuth 互動在 `auth/providers/sharepoint_cookie.py` |
| `onedrive_business` | `providers/onedrive_business.py:OneDriveBusinessStorage` | Cookie（同上） | `trash` | 與 SharePoint 共 identity |
| `onedrive` | `providers/onedrive.py:OneDriveStorage` | Microsoft Graph OAuth | `trash` | `requests-oauthlib`，callback server 本地接 OAuth |
| `google_drive` | `providers/google_drive.py:GoogleDriveStorage` | Google OAuth | `trash` | `root_folder_id` |
| `googlephotos` | `providers/google/photos.py:GooglePhotosStorage` + `GooglePhotosClient` | Google OAuth（獨立 token） | `PERMANENT_ONLY` 傾向 | library 導向 |
| `pikpak` | `providers/pikpak.py:PikPakStorage` | PikPak 帳密自研 | — | `auth/providers/pikpak.py:PikPakAuthProvider` |
| `alist` | 未實作 | — | — | 型別保留 |

## 4.4 `DeleteCapability`

```mermaid
flowchart LR
    A[Provider] --> B{delete_capability}
    B -->|trash| C[delete permanent=False 可還原<br/>Web 同步計畫統計為 trash_delete]
    B -->|permanent_only| D[delete 即永久刪除<br/>Web 同步計畫統計為 permanent_delete<br/>FTP/SFTP 照這類處理]
```

- `validate_delete_request(permanent)` 由 contract 預設實作，`permanent` 與 capability 矛盾時拒絕。
- Web `POST /api/sync/plan` 回傳 `permanent_delete_count / trash_delete_count` 供 UI 危險提示。
- `SyncPlanner` 刪除 Office 等破壞性動作會依 capability 區分批次（見第 05 章 §5.4 precondition/cleanup）。
