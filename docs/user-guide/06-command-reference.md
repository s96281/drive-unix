# 06 完整命令速查

[← 上一章](05-scheduling-and-automation.md) | [手冊目錄](README.md) | [下一章 →](07-scenarios-and-troubleshooting.md)

> 速查表只列「預設行為與必備參數」。細節請點進對應章節，不要靠猜測用指令。

## 6.1 全域

```bash
drive-unix --plain <指令>            # 純文字：關色彩、emoji、live 進度
NO_COLOR=1 drive-unix <指令>         # 只關色彩
```

## 6.2 設定與 Remote

| 指令 | 參數 | 說明 |
|---|---|---|
| `init` | — | 首次導引；有 Remote 列舉，無則開 wizard |
| `remote add` | `[provider_or_name]` `--name/-n` `--type/-t` | 互動 wizard（建議入口） |
| `remote list` | `--verbose/-v` | 不印 secret；`-v` 附 config 路徑 |
| `remote remove` | `<name>` | 移除設定（不刪遠端檔） |
| `remote rename` | `<old> <new>` | 改名並更新預設指向 |
| `remote edit` | `<name>` `--base-url` `--site` `--email` `--password-env` `--password-prompt` `--clear-password` | 密碼三選一 |
| `remote test` | `<name>` `--write` | 驗證可讀；`--write` 再驗可寫入並清理暫存目錄 |

## 6.3 瀏覽與查詢

| 指令 | 必填參數 | 常用選項 |
|---|---|---|
| `ls` | `<remote>:/<path>` | `--offset 0` `--limit/-n` `--json` |
| `tree` | `<remote>:/<path>` | `--depth/-L` `--files-only` `--dirs-only/-d` `--max-items 1000` |
| `find` | `<remote>:/<path>` | `--name/-n` `--fuzzy-threshold 70` `--type/-t file/folder` `--size-gt/lt` `--modified-after/before` `--max-depth` |
| `search` | `<remote>:/<path>` `<query>` | 無選項（不支援的 Provider 報錯） |
| `stat` | `<remote>:/<path>` | `--json` |
| `mkdir` | `<remote>:/<path>` | `--parents/-p` |
| `rm` | `<remote>:/<path>` | `--permanent/-p` `--force/-f`（Provider 語意見 [第三章](03-browse-and-manage-files.md)） |
| `download-link` | `<remote>:/<path>` | 無 |

## 6.4 傳輸

| 指令 | 必填參數 | 常用選項 |
|---|---|---|
| `cp` | `<src> <dst>` | 無 |
| `mv` | `<src> <dst>` | 無（跨 Remote 先複製成功才刪來源） |
| `upload` | `<local> <dst>` | `--recursive/-r`（目錄必加） `--workers/-w 4` |
| `download` | `<src> [local]` | `--workers/-w 4` `--force/-f` `--recursive/-r` |

## 6.5 比對與同步

| 指令 | 必填參數 | 常用選項 |
|---|---|---|
| `diff` | `<A> <B>` | `--show-same/-s` `--checksum` `--json` |
| `sync` | `<A> <B>` | `--dry-run --full-plan --delete --include --exclude --conflict auto --checksum --workers/-w 4 --throttle --progress --yes/-y --json` |
| `bisync` | `<A> <B>` | 同 `sync` 但沒有 `--delete`（硬固定雙向） |
| `checksum` | `<remote>:/<path>` | `--algo sha256` `--mode auto/remote/download` |

## 6.6 排程與環境

| 指令 | 必填參數 | 說明 |
|---|---|---|
| `schedule add` | `<name> '<cron>' '<cmd>'` | 5 欄 Cron |
| `schedule list/remove/enable/disable` | `<name>` | 任務 CRUD |
| `schedule start` | — | 前景常駐 |
| `schedule service install/start/stop/status/uninstall` | — | OS 背景 service |
| `env export` | `<backup.zip>` | `--include-secrets --include-auth-cache`（預設不含）|
| `env import` | `<backup.zip>` | `--force/-f` 跳過覆寫確認 |

## 6.7 Upstash E2EE

| 指令 | 參數 | 說明 |
|---|---|---|
| `upstash config` | `--url --token --token-env --sync-key --passphrase/-p --passphrase-env` | 互動式或參數式設定 |
| `upstash test` | `--json` | 連線測試（ping / latency） |
| `upstash status` | `--sync-key --json` | 云端 bundle 與本機對比 |
| `upstash push` | `--passphrase/-p --passphrase-env --sync-key --include-auth-cache --include-tasks --yes --json` | 上傳加密 bundle |
| `upstash pull` | `--passphrase/-p --passphrase-env --strategy merge --dry-run --yes --json` | `merge` / `replace` |
| `upstash delete` | `--yes` | 永久刪除云端 bundle |
| `upstash renew-tokens` | `--interval --leeway 30 --remote --passphrase/-p` | 單次或常駐換發（VPS 中心用） |

舊版別名（`add-sp`、`add-odb`、`add-gdrive`、`list-nodes`、`cron-add`、`export-env` 等）仍可使用，但不會出現在 root help；新實作請用上表正式指令。
