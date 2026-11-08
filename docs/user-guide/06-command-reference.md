# 06 完整命令速查

[← 手冊目錄](README.md) | [← 上一章](05-scheduling-and-automation.md) | [下一章 →](07-scenarios-and-troubleshooting.md)

本章內容：

- # 19. 完整命令速查

---

## 19. 完整命令速查

### Global

```text
drive-unix [--plain] COMMAND ...
```

### Setup / Remote

```text
drive-unix init

drive-unix remote add [PROVIDER] [--name NAME]
drive-unix remote list [--verbose]
drive-unix remote test NAME [--write]
drive-unix remote edit NAME [OPTIONS]
drive-unix remote rename OLD NEW
drive-unix remote remove NAME
```

`remote edit` options：

```text
--base-url, -b TEXT
--site, -s TEXT
--email, -e TEXT
--password-env TEXT
--password-prompt
--clear-password
```

### Browse / Search

```text
drive-unix ls PATH [--json]

drive-unix tree REMOTE_PATH
  [--depth INTEGER | -L INTEGER]
  [--files-only]
  [--dirs-only | -d]
  [--max-items INTEGER]

drive-unix find REMOTE_PATH
  [--name TEXT | -n TEXT]
  [--fuzzy-threshold INTEGER]
  [--type file|folder | -t file|folder]
  [--size-gt SIZE]
  [--size-lt SIZE]
  [--modified-after DATE]
  [--modified-before DATE]
  [--max-depth INTEGER]

drive-unix search REMOTE_PATH QUERY

drive-unix stat REMOTE_PATH [--json]
```

### File operations

```text
drive-unix mkdir REMOTE_PATH [--parents | -p]

drive-unix rm REMOTE_PATH
  [--permanent | -p]
  [--force | -f]

drive-unix cp SOURCE DEST

drive-unix mv SOURCE DEST
```

### Transfer

```text
drive-unix upload LOCAL_PATH REMOTE_PATH
  [--recursive | -r]
  [--workers INTEGER | -w INTEGER]

drive-unix download REMOTE_PATH [LOCAL_PATH]
  [--workers INTEGER | -w INTEGER]
  [--force | -f]
  [--recursive | -r]

drive-unix download-link REMOTE_PATH
```

### Diff / Sync

```text
drive-unix diff SOURCE DEST
  [--show-same | -s]
  [--checksum]
  [--json]

drive-unix sync SOURCE DEST
  [--dry-run]
  [--one-way | --two-way]
  [--delete]
  [--exclude PATTERN]
  [--include PATTERN]
  [--conflict STRATEGY]
  [--checksum]
  [--progress]
  [--workers INTEGER | -w INTEGER]
  [--yes | -y]
  [--throttle FLOAT]
  [--full-plan]
  [--json]

drive-unix bisync SOURCE DEST
  [--dry-run]
  [--exclude PATTERN]
  [--include PATTERN]
  [--conflict STRATEGY]
  [--checksum]
  [--progress]
  [--workers INTEGER | -w INTEGER]
  [--yes | -y]
  [--throttle FLOAT]
  [--full-plan]
  [--json]
```

Conflict strategy：

```text
auto | newer | rename | abort | prefer-source | prefer-destination
```

### Checksum

```text
drive-unix checksum REMOTE_PATH
  [--algo md5|sha1|sha256|quickXorHash]
  [--mode auto|remote|download]
```

Compatibility flags：

```text
--remote
--download
```

### Schedule

```text
drive-unix schedule add NAME 'CRON' 'COMMAND'
drive-unix schedule list
drive-unix schedule enable NAME
drive-unix schedule disable NAME
drive-unix schedule remove NAME
drive-unix schedule start

drive-unix schedule service install
drive-unix schedule service start
drive-unix schedule service status
drive-unix schedule service stop
drive-unix schedule service uninstall
```

### Environment

```text
drive-unix env export OUTPUT.zip
  [--include-auth-cache]
  [--include-secrets]

drive-unix env import INPUT.zip
  [--force | -f]
```

---

[← 手冊目錄](README.md)
