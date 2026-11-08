# 05 排程與自動化

[← 上一章](04-diff-and-sync.md) | [手冊目錄](README.md) | [下一章 →](06-command-reference.md)

## 5.1 JSON / Plain / exit code

### 5.1.1 讓腳本讀的輸出

```bash
drive-unix ls work:/ --json
drive-unix stat work:/docs/report.pdf --json
drive-unix diff A:/ B:/ --json
drive-unix sync A:/ B:/ --dry-run --json
```

- `--json` 的錯誤狀態不會假裝正常：會輸出 `{status: "error", ...}`。
- 真正執行 sync 並加 `--json` 時，必須同時加 `--yes`，避免腳本卡在互動確認。
- Sync JSON 中的 status 可能為 `noop`、`dry-run`、`ok`、`partial-failure`、`conflict`、`aborted`、`error`。
- 通用失敗 exit 1；衝突中止（`abort` / `newer` 判定失敗）exit 2。CI 判斷只要看 exit code 即可。

### 5.1.2 讓人／log 讀的純文字

```bash
drive-unix --plain ls work:/      # 關色彩、emoji、live 進度
NO_COLOR=1 ls work:/              # 只關色彩
```

`--plain` 是全域參數，要放在子指令之前。`ls`、`stat`、`diff`、`sync`、`bisync` 都支援 `--json`；真正執行同步時的 `--json` 必須搭配 `--yes`。

### 5.1.3 CI 範式

```bash
# 1) 只看計畫
drive-unix sync A:/ B:/ --dry-run --json
# 2) 按計畫執行（跳過確認，失敗就 exit 非零）
drive-unix sync A:/ B:/ --yes --json
```

## 5.2 排程（Cron）

### 5.2.1 任務管理

```bash
drive-unix schedule add nightly '0 2 * * *' 'sync local:/data cloud:/backup --yes'
drive-unix schedule list
drive-unix schedule disable nightly
drive-unix schedule enable nightly
drive-unix schedule remove nightly
```

- `schedule` 用 5 欄 Cron：`分 時 日 月 星期`，每欄支援 `*`、單一數字、範圍 `a-b`、`*/step`、逗號列表。不支援秒、`@daily`、英文星期名（`MON`）。
- 星期欄 `0` 與 `7` 都代表星期日；`1` 到 `6` 代表週一到週六。
- 日與星期用 **AND**（兩欄都要吻合），與傳統 Vixie cron 的 OR 不同。寫每天凌晨 2 點請用 `0 2 * * *`，不要寫 `0 2 * * 1-5` 來表達平日時段（那會變成「平日 + 每天」）。
- 指令字串可以省略前綴（`drive-unix`、`python main.py`、`mycli` 等），執行前會自動正規化；空指令會被擋下並提示錯誤。

### 5.2.2 前景與背景

```bash
drive-unix schedule start          # 前景常駐，Ctrl+C 停止
drive-unix schedule service install  # 註冊 OS service，登入自動啟動
drive-unix schedule service start
drive-unix schedule service status
drive-unix schedule service stop
drive-unix schedule service uninstall
```

| 平台 | 後端 | 安裝產物 |
|---|---|---|
| Linux | `systemd-user` | `~/.config/systemd/user/drive-unix-scheduler.service` |
| macOS | `launchd` | `~/Library/LaunchAgents/io.drive-unix.scheduler.plist` |
| Windows | Task Scheduler | `DriveUnixScheduler`（登入觸發）|
| 其他 | detached process | 只有 PID 檔 |

- `service status` 會印 backend、是否已安裝、PID 與 log 路徑。
- Daemon 的 stdout/stderr 都寫到單一檔案：`~/.config/mycli/scheduler/scheduler.log`（啟動失敗請先去那裡看）。
- 排程執行失敗時，只有失敗時的 stderr 會被記錄下來；成功／失敗最終寫回 `config.toml` 的 `last_success_at` / `last_exit_code` 供 `schedule list` 查詢。

### 5.2.3 補跑（Missed-run）

若 Scheduler 有一段時間沒開（例如筆電休眠三天），下次啟動會從「上次執行」補查最近 7 天內遺漏的時段：只要有任一分鐘符合 Cron，就會補執行一次（同一分鐘不會重跑）。新任務從未跑過時不會立即補跑，會等到下一個排定時間。

## 5.3 環境備份與還原

```bash
drive-unix env export backup.zip
drive-unix env import backup.zip
drive-unix env import backup.zip --force
```

| 項目 | 預設 | 含密文時 |
|---|---|---|
| `config/`（Remote 拓撲與任務） | 一定含 | — |
| `secrets.json`、`secret-files/` | **排除** | `--include-secrets` |
| `auth_cache/`（OAuth token/cookie） | **排除** | `--include-auth-cache` |

- 匯出 zip 的權限是 `0600`：即使不含秘密，拓撲與帳號識別仍可能敏感。
- `--include-secrets` / `--include-auth-cache` 產出的檔案請視為憑證妥善保管，絕不公開分享。
- 匯入時會拒絕 Zip Slip（`..`、絕對路徑、symlink），且只接受 `config/`、`auth_cache/` 頂層，復原檔案自動設回 `0600` / `0700`。

## 5.4 Upstash E2EE 多端同步

> Upstash 只看到 AES-256-GCM 密文，密碼與憑證在離開本機前完成加密。家裡多台電腦、或把 VPS 設為「換發中心」，都用這套。

### 5.4.1 一次性設定

```bash
export UPSTASH_REDIS_REST_URL='https://.../...'     # 或 upstash config --url
export UPSTASH_REDIS_REST_TOKEN='...'              # 或 --token / --token-env
drive-unix upstash config --passphrase-env MY_SECRET
drive-unix upstash test
drive-unix upstash push -p 'MySecretPassphrase'
drive-unix upstash status
```

- `--sync-key` 預設 `drive-unix:sync:default`；多台各有自己的群組就用不同 key 區隔。
- `--token-env` 優於 `--token`；顯式 `--url/--token` 會覆寫環境變數。
- Token 與 passphrase 存進 secret store，不會寫明文到 `config.toml`。

### 5.4.2 push / pull

```bash
drive-unix upstash push -p 'MySecretPassphrase' --yes
drive-unix upstash pull -p 'MySecretPassphrase' --dry-run --strategy merge
drive-unix upstash pull -p 'MySecretPassphrase' --strategy replace --yes
```

- `push` 會加密本機 topology 與 secrets 後上傳；沒有任何 Remote 時會警告。
- `pull` 預設 `merge`（同名 Remote 預設跳過）；`replace` 會先清掉本機全部 Remote 再覆寫，必須加 `--yes`。
- `env:` 引用會原樣保留（機器專屬的參照不傳遞）；其餘密文會在新機器上重新放入 secret store 並對應。

### 5.4.3 Token 續期（renew-tokens）

```bash
drive-unix upstash renew-tokens --interval 1800 --leeway 60
```

- 無 `--interval` 時跑一次；有 `--interval` 時變成常駐迴圈（最小 5 秒）。
- `--leeway`（預設 30 分鐘）：還有幾分鐘就過期的 token 會提早換發。
- 未在各台機器開 Upstash 時，`renew-tokens` 會回傳 disabled 或 failed，不會崩潰。

VPS 常駐換發中心（開 Upstash 時建議必開）：

```bash
drive-unix upstash renew-tokens --interval 1800 --leeway 60 -p 'MySecretPassphrase'
```

設定好 `--auto-sync-tokens`（從雲端撿 token）與 `--auto-push-tokens`（換完推回雲端）後，網內其他電腦會自動拿到最新 token，不必各自登入。
