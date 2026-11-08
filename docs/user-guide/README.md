# drive-unix 完整使用手冊

> 適用版本：`drive-unix 0.1.0`（Phase 6 UX/Safety/Polish 版本）
>
> `drive-unix` 是一套多 Provider 檔案管理與同步 CLI，可用一致的命令操作 Local、Google Drive、OneDrive、OneDrive Business、SharePoint、SFTP、FTP/FTPS 與 WebDAV。

本手冊按用途分門別類撰寫，依序閱讀即可完成從安裝到維運的完整流程。
如需理解內部機制（呼叫鏈、資料結構與流程圖），請見 [docs/mechanisms/](../mechanisms/README.md)。

## 手冊地圖

| 章節 | 內容 |
|---|---|
| [01 入門：功能概覽、安裝與基本操作](01-getting-started.md) | 功能概覽、Python/pip/uv 安裝、Provider extras、第一次使用導引、命令與路徑規則 |
| [02 Remote 與各 Provider 設定](02-providers-and-secrets.md) | Remote 增刪改查、Local / Google / Microsoft / SharePoint / SFTP / FTP / WebDAV 設定、能力摘要、Secret 與認證資料 |
| [03 瀏覽、建立與傳輸檔案](03-browse-and-manage-files.md) | `ls` / `tree` / `find` / `search` / `stat`、`mkdir` / `rm`、`cp` / `mv` / `upload` / `download` / `download-link` |
| [04 差異比較與同步](04-diff-and-sync.md) | `diff`、`sync`（dry-run、`--delete`、include/exclude、checksum、workers、throttle）、`bisync`、衝突策略、Checksum |
| [05 排程與自動化](05-scheduling-and-automation.md) | JSON / Plain / `NO_COLOR`、exit code、CI 用法、Cron 排程與背景 service、環境備份與還原 |
| [06 完整命令速查](06-command-reference.md) | 全部指令一頁查 |
| [07 常見情境與錯誤排查](07-scenarios-and-troubleshooting.md) | 常見使用情境、錯誤排查、舊版相容命令 |

## 建議閱讀順序

1. 新手：01 → 02 → 03 → 04
2. 自動化／維運：05 → 07
3. 查命令：06
4. 部署 / Token 換發：另見 [DEPLOYMENT](../DEPLOYMENT.md) 與 [VPS Token 換發中心](../vps-deployment-token-center.md)

