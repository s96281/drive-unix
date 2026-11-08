# drive-unix 完整使用手冊

> 適用版本：`drive-unix 0.1.0`（Python 3.12+，CI 覆蓋 3.12 / 3.13 / 3.14）
>
> 本手冊是 `drive-unix` 的「使用說明」：教你如何安裝、接上儲存空間、瀏覽與傳輸檔案、做同步、排程自動化，以及出錯時如何排查。
>
> 如果你想知道「內部是怎麼運作的」（分層架構、快取、內部流程與 Mermaid 流程圖），請到 [docs/mechanisms/](../mechanisms/README.md)。
> 如果你要把 Web/Scheduler 部署到伺服器上，請看 [DEPLOYMENT](../DEPLOYMENT.md) 與 [VPS Token 換發中心](../vps-deployment-token-center.md)。

## 手冊地圖

| 章節 | 你會學到什麼 | 建議對象 |
|---|---|---|
| [01 入門：功能概覽、安裝與基本操作](01-getting-started.md) | 元件全貌、pip/uv 安裝與 extras、第一次導引、`REMOTE:/path` 路徑規則、`--plain` / `NO_COLOR`、設定檔位置 | 所有人 |
| [02 Remote 與各 Provider 設定](02-providers-and-secrets.md) | Remote 增刪改查與連線測試、11 種 Provider 的必填欄位與 extras、能力對照表、密碼永不進 `config.toml` 的 secret 引用模型 | 要接新空間的人 |
| [03 瀏覽、建立與傳輸檔案](03-browse-and-manage-files.md) | `ls`/`tree`/`find`/`search`/`stat`、`mkdir`/`rm`、刪除安全模型、`cp`/`mv`/`upload`/`download` | 日常操作 |
| [04 差異比較與同步](04-diff-and-sync.md) | `diff`、`sync`（含 `--delete` 鏡像）、`bisync`、衝突策略、Checksum、workers/throttle | 要做同步的人 |
| [05 排程與自動化](05-scheduling-and-automation.md) | `--json`、exit code、CI 用法、Cron 排程與背景 service、環備份還原、Upstash E2EE 多端同步與 Token 續期 | 自動化／多機／維運 |
| [06 完整命令速查](06-command-reference.md) | 全部可見指令一頁查，不含講解 | 快查 |
| [07 常見情境與錯誤排查](07-scenarios-and-troubleshooting.md) | 實戰情境食譜、按症狀查問題、舊版相容命令、需要更多幫助時去哪找 | 排錯 |

## 心智模型（30 秒版）

想像每個儲存空間是一台「遠端」，你給它一個中文別名（Remote 名稱，例如 `gdrive`、`work`），之後都用 `別名:/路徑` 操作它：

```bash
drive-unix ls gdrive:/
drive-unix sync laptop:/docs gdrive:/backup --dry-run
```

全套能力只分四類：**瀏覽**（看裡面有什麼）、**傳輸**（複製／移動／上傳／下載）、**同步**（比對並把兩邊拉齊）、**自動化**（排程與備份）。學完瀏覽就幾乎會所有操作，因為傳輸和同步選用的都是同一套 `別名:/路徑` 語法。

## 建議閱讀順序

- 第一次接觸：依序讀 01 → 02 → 03，對著一台 Local 或 Google Drive 練手。
- 要做備份同步：直讀 04，先習慣 `--dry-run` 再實作。
- 要放在伺服器或多台電腦：讀 05（Upstash + 排程），再銜接 [DEPLOYMENT](../DEPLOYMENT.md)。
- 只想查參數：跳 06；卡住了：跳 07。

## 本手冊的撰寫原則

- 每個指令都給可直接貼上執行的範例；路徑示例統一用 `gdrive:`（Google Drive）、`work:`（SharePoint）、`laptop:`（Local）三個示範別名。
- 參數預設值以程式碼為準；凡是「預設會印出/不會印出」的行為，都會明確說明。
- 刪除、同步、跨機傳輸等不可逆操作，一定先講「會不會刪到資料」再教指令。不確定時先加 `--dry-run`。
