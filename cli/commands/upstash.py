"""Upstash E2EE multi-device synchronization CLI commands."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import typer

from application.upstash_sync_service import UpstashSyncService
from cli.context import CLIContext
from cli.presentation import echo, render_error, secho
from core.crypto import DecryptionError, PayloadCorruptedError
from infrastructure.upstash_client import (
    UpstashAuthError,
    UpstashConnectionError,
    UpstashError,
)


def _resolve_passphrase(
    passphrase: str | None,
    passphrase_env: str | None,
    *,
    prompt_text: str = "請輸入 E2EE 主密碼 (Passphrase)",
    confirm: bool = False,
) -> str:
    """Resolve passphrase from argument, environment variable, or interactive prompt."""
    if passphrase:
        return passphrase

    if passphrase_env:
        val = os.getenv(passphrase_env)
        if not val:
            raise typer.BadParameter(f"環境變數 {passphrase_env} 未設定或內容為空。")
        return val

    env_fallback = os.getenv("UPSTASH_SYNC_PASSPHRASE")
    if env_fallback:
        return env_fallback

    val = typer.prompt(prompt_text, hide_input=True, confirmation_prompt=confirm)
    if not val:
        raise typer.BadParameter("主密碼不可為空。")
    return val


def upstash_config(
    url: str | None = typer.Option(None, "--url", help="Upstash REST URL (例如: https://...upstash.io)"),
    token: str | None = typer.Option(None, "--token", help="Upstash REST Token"),
    token_env: str | None = typer.Option(None, "--token-env", help="從指定環境變數讀取 REST Token"),
    sync_key: str | None = typer.Option(None, "--sync-key", help="自訂同步金鑰 (預設: drive-unix:sync:default)"),
    passphrase: str | None = typer.Option(None, "--passphrase", "-p", help="預先設定 E2EE 主密碼 (加密儲存於 SecretStore)"),
    passphrase_env: str | None = typer.Option(None, "--passphrase-env", help="從指定環境變數讀取主密碼"),
    auto_sync_tokens: bool | None = typer.Option(None, "--auto-sync-tokens/--no-auto-sync-tokens", help="過期時是否自動由 Upstash 查詢獲取其他機器換發的憑證"),
    auto_push_tokens: bool | None = typer.Option(None, "--auto-push-tokens/--no-auto-push-tokens", help="換發憑證後是否自動加密推送至 Upstash"),
    renew_leeway: int | None = typer.Option(None, "--renew-leeway", help="巡檢換發緩衝分鐘數 (預設: 30)"),
) -> None:
    """設定 Upstash 雲端連線參數與金鑰 (Token 將加密存入 SecretStore)。"""
    ctx = CLIContext.create()
    config_mgr = ctx.config

    cur_url, _, cur_key = config_mgr.get_upstash_config()

    if not url:
        default_url = cur_url or ""
        url = typer.prompt("Upstash REST URL", default=default_url)

    if token_env:
        resolved_token = os.getenv(token_env)
        if not resolved_token:
            render_error(
                f"無法讀取環境變數 {token_env}。",
                cause="環境變數不存在或為空字串。",
                next_steps=("請確認 export UPSTASH_TOKEN=... 後再重試。",),
            )
            raise typer.Exit(code=1)
    elif token:
        resolved_token = token
    else:
        resolved_token = typer.prompt("Upstash REST Token", hide_input=True, default="")

    effective_key = sync_key or cur_key or "drive-unix:sync:default"
    if not sync_key and not cur_key:
        effective_key = typer.prompt("同步金鑰 (Sync Key)", default="drive-unix:sync:default")

    resolved_pass: str | None = None
    if passphrase_env:
        resolved_pass = os.getenv(passphrase_env)
        if not resolved_pass:
            raise typer.BadParameter(f"環境變數 {passphrase_env} 未設定或內容為空。")
    elif passphrase:
        resolved_pass = passphrase

    try:
        config_mgr.set_upstash_config(
            rest_url=url,
            rest_token=resolved_token if resolved_token else None,
            sync_key=effective_key,
            passphrase=resolved_pass,
            auto_sync_tokens=auto_sync_tokens,
            auto_push_tokens=auto_push_tokens,
            renew_leeway_minutes=renew_leeway,
        )
        secho("✅ Upstash 同步設定已更新！(Token 與 Passphrase 已安全加密保存於 SecretStore)", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            "儲存 Upstash 設定失敗。",
            cause=exc,
            next_steps=("檢查設定檔權限與磁碟空間後重試。",),
        )
        raise typer.Exit(code=1) from exc


def upstash_test(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 格式輸出測試結果"),
) -> None:
    """測試與 Upstash REST 伺服器的連線與認證狀態。"""
    ctx = CLIContext.create()
    service = UpstashSyncService(ctx.config)

    t0 = time.perf_counter()
    try:
        client = service.get_client()
        pong = client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if json_output:
            echo(json.dumps({
                "status": "ok" if pong else "failed",
                "ping": pong,
                "latency_ms": round(latency_ms, 2),
                "url": client.rest_url,
            }, ensure_ascii=False))
            return

        secho("✅ Upstash 連線與認證測試成功！", fg=typer.colors.GREEN)
        echo(f"   伺服器端點: {client.rest_url}")
        echo(f"   往返延遲:   {latency_ms:.1f} ms")
        echo("   狀態回應:   PONG")

    except UpstashAuthError as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": "auth_failed", "detail": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "Upstash 認證失敗。",
                cause=exc,
                next_steps=(
                    "確認 REST Token 是否正確或未過期。",
                    "執行 `drive-unix upstash config` 重新輸入 Token。",
                ),
            )
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": "connection_failed", "detail": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "無法連線至 Upstash 伺服器。",
                cause=exc,
                next_steps=(
                    "確認網路連線是否正常，且可連至 Upstash HTTPS 端點。",
                    "檢查 URL 格式是否為 https://<db>.upstash.io。",
                ),
            )
        raise typer.Exit(code=1) from exc


def upstash_status(
    sync_key: str | None = typer.Option(None, "--sync-key", help="自訂同步金鑰"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 格式輸出狀態"),
) -> None:
    """檢視 Upstash 雲端同步中繼資料與本機節點比對。"""
    ctx = CLIContext.create()
    service = UpstashSyncService(ctx.config)

    try:
        info = service.fetch_status(sync_key=sync_key)
        if json_output:
            echo(json.dumps(info, ensure_ascii=False))
            return

        echo("☁️  Upstash 雲端同步狀態:")
        echo(f"   同步金鑰 (Sync Key): {info['sync_key']}")

        if not info["exists"]:
            secho("   雲端狀態: 尚無備份資料 (Key 不存在)", fg=typer.colors.YELLOW)
            echo(f"   本機節點數量: {info['local_remotes_count']} ({', '.join(info['local_remote_names']) or '無'})")
            echo("   提示: 使用 `drive-unix upstash push` 上傳本機節點。")
            return

        secho("   雲端狀態: 已存在備份封包", fg=typer.colors.GREEN)
        echo(f"   上次同步時間: {info.get('created_at') or '未知'}")
        echo(f"   來源設備名稱: {info.get('device_name') or '未知'}")
        echo(f"   加密演算法:   {info.get('algorithm')} (E2EE)")
        echo(f"   雲端節點數量: {info.get('remotes_count')} ({', '.join(info.get('remote_names', []))})")
        echo(f"   本機節點數量: {info['local_remotes_count']} ({', '.join(info['local_remote_names']) or '無'})")

    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error("取得 Upstash 狀態失敗。", cause=exc, next_steps=("確認網路連線與 Token 設定後重試。",))
        raise typer.Exit(code=1) from exc


def upstash_push(
    passphrase: str | None = typer.Option(None, "--passphrase", "-p", help="E2EE 加密主密碼"),
    passphrase_env: str | None = typer.Option(None, "--passphrase-env", help="從環境變數讀取主密碼"),
    sync_key: str | None = typer.Option(None, "--sync-key", help="自訂同步金鑰"),
    include_auth_cache: bool = typer.Option(False, "--include-auth-cache", help="同時備份登入 Session/Token 快取 (包含敏感 Token)"),
    include_tasks: bool = typer.Option(True, "--include-tasks/--no-tasks", help="同時備份排程任務"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳過上傳確認提示"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 格式輸出結果"),
) -> None:
    """將本機節點拓撲與機密帳號資訊經端對端加密 (E2EE) 上傳至 Upstash。"""
    ctx = CLIContext.create()
    service = UpstashSyncService(ctx.config)

    remotes_count = len(ctx.config.config.remotes)
    if remotes_count == 0 and not yes:
        secho("⚠️  警告：目前本機尚未設定任何 Remote 節點。", fg=typer.colors.YELLOW)
        if not typer.confirm("仍要繼續上傳空白節點設定嗎？"):
            raise typer.Abort()

    if not yes and not json_output:
        echo(f"即將備份 {remotes_count} 個遠端節點與相關機密認證資訊至 Upstash。")
        if not typer.confirm("確定要繼續嗎？"):
            raise typer.Abort()

    try:
        pw = _resolve_passphrase(
            passphrase,
            passphrase_env,
            prompt_text="請設定 E2EE 加密主密碼 (拉取時需相同密碼)",
            confirm=(not passphrase and not passphrase_env and not os.getenv("UPSTASH_SYNC_PASSPHRASE")),
        )

        res = service.push(
            pw,
            sync_key=sync_key,
            include_auth_cache=include_auth_cache,
            include_tasks=include_tasks,
        )

        if json_output:
            echo(json.dumps(res, ensure_ascii=False))
            return

        secho("🎉 成功加密並上傳節點與機密資訊至 Upstash！", fg=typer.colors.GREEN)
        echo(f"   同步金鑰 (Sync Key): {res['sync_key']}")
        echo(f"   備份節點數:          {res['remotes_count']}")
        echo(f"   資料封包大小:        {res['payload_size_bytes']} bytes")
        echo(f"   建立時間 (UTC):      {res['created_at']}")
        echo(f"   來源設備名稱:        {res['device_name']}")

    except typer.Abort:
        secho("🛑 已取消上傳操作。", fg=typer.colors.YELLOW)
    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "Upstash 上傳同步失敗。",
                cause=exc,
                next_steps=(
                    "確認已執行 `drive-unix upstash config` 設定正確的 URL 與 Token。",
                    "確認網路能夠連線至 Upstash 伺服器。",
                ),
            )
        raise typer.Exit(code=1) from exc


def upstash_pull(
    passphrase: str | None = typer.Option(None, "--passphrase", "-p", help="E2EE 解密主密碼"),
    passphrase_env: str | None = typer.Option(None, "--passphrase-env", help="從環境變數讀取主密碼"),
    sync_key: str | None = typer.Option(None, "--sync-key", help="自訂同步金鑰"),
    strategy: str = typer.Option("merge", "--strategy", help="合併策略: merge (合併新節點) 或 replace (完全取代本機節點)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="當節點名稱重複時，強制以雲端版本覆蓋"),
    dry_run: bool = typer.Option(False, "--dry-run", help="僅預覽差異，不修改本機設定與密碼"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳過覆蓋確認提示"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 格式輸出結果"),
) -> None:
    """從 Upstash 下載加密備份封包，解密並還原/合併至本機節點與 SecretStore。"""
    ctx = CLIContext.create()
    service = UpstashSyncService(ctx.config)

    try:
        pw = _resolve_passphrase(passphrase, passphrase_env, prompt_text="請輸入 E2EE 解密主密碼")

        if dry_run:
            res = service.pull(pw, sync_key=sync_key, strategy=strategy, overwrite=overwrite, dry_run=True)
            if json_output:
                echo(json.dumps(res, ensure_ascii=False))
                return

            echo("🔍 [Dry Run 預覽] 雲端備份分析:")
            echo(f"   來源主機:     {res['device_name']}")
            echo(f"   備份時間:     {res['created_at']}")
            echo(f"   雲端節點清單: {', '.join(res['incoming_remotes']) or '(空)'}")
            echo(f"   預計新增節點: {', '.join(res['new_remotes']) or '(無)'}")
            if res['conflicting_remotes']:
                action = "將覆蓋本機" if overwrite else "將保留本機 (略過)"
                secho(f"   同名衝突節點: {', '.join(res['conflicting_remotes'])} ({action})", fg=typer.colors.YELLOW)
            echo("\n提示：確認無誤後，移除 `--dry-run` 執行正式拉取。")
            return

        if strategy == "replace" and not yes:
            secho("⚠️  警告：replace 策略將會清空本機現有所有節點設定！", fg=typer.colors.YELLOW)
            if not typer.confirm("確定要繼續嗎？"):
                raise typer.Abort()

        res = service.pull(pw, sync_key=sync_key, strategy=strategy, overwrite=overwrite, dry_run=False)

        if json_output:
            echo(json.dumps(res, ensure_ascii=False))
            return

        secho("🎉 成功自 Upstash 拉取並同步完成！", fg=typer.colors.GREEN)
        echo(f"   新增節點數: {len(res['restored_remotes'])} ({', '.join(res['restored_remotes']) or '無'})")
        if res['overwritten_remotes']:
            echo(f"   覆蓋節點數: {len(res['overwritten_remotes'])} ({', '.join(res['overwritten_remotes'])})")
        if res['skipped_remotes']:
            echo(f"   略過節點數: {len(res['skipped_remotes'])} ({', '.join(res['skipped_remotes'])})")
        echo(f"   還原排程任務: {res['tasks_restored']} 個")
        echo(f"   目前本機總節點數: {res['total_local_remotes']}")

    except typer.Abort:
        secho("🛑 已取消拉取操作。", fg=typer.colors.YELLOW)
    except DecryptionError as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": "decryption_failed", "detail": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "無法解密 Upstash 備份封包。",
                cause=exc,
                next_steps=(
                    "確認輸入的主密碼與當初在來源設備上傳時完全相同。",
                    "密碼有大小寫區分，請再次確認輸入內容。",
                ),
            )
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "Upstash 拉取同步失敗。",
                cause=exc,
                next_steps=(
                    "確認指定的同步金鑰與 Upstash 連線設定是否正確。",
                    "先執行 `drive-unix upstash status` 確認雲端資料是否存在。",
                ),
            )
        raise typer.Exit(code=1) from exc


def upstash_delete(
    sync_key: str | None = typer.Option(None, "--sync-key", help="自訂同步金鑰"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳過確認提示"),
) -> None:
    """從 Upstash 雲端永久清除同步封包。"""
    ctx = CLIContext.create()
    service = UpstashSyncService(ctx.config)
    target_key = service.get_sync_key(sync_key)

    if not yes:
        secho(f"⚠️  警告：即將永久刪除 Upstash 上的同步資料 (Key: {target_key})！", fg=typer.colors.YELLOW)
        if not typer.confirm("確定要刪除嗎？"):
            raise typer.Abort()

    try:
        deleted = service.delete_bundle(sync_key=target_key)
        if deleted:
            secho(f"✅ 已成功自 Upstash 刪除金鑰 '{target_key}' 之資料。", fg=typer.colors.GREEN)
        else:
            echo(f"ℹ️  Upstash 上本就無金鑰 '{target_key}' 之資料。")
    except Exception as exc:
        render_error("刪除雲端資料失敗。", cause=exc, next_steps=("確認網路與 Token 權限後重試。",))
        raise typer.Exit(code=1) from exc


def upstash_renew_tokens(
    leeway: int = typer.Option(30, "--leeway", "-l", help="過期緩衝分鐘數 (例如: 30 表示 30 分鐘內即將過期的 Token 均提前換發)"),
    remote: str | None = typer.Option(None, "--remote", "-r", help="僅針對特定遠端節點執行巡檢換發 (預設巡檢所有已設定節點)"),
    interval: int | None = typer.Option(None, "--interval", "-i", help="常駐背景巡檢間隔秒數 (若未指定則僅執行單次巡檢)"),
    passphrase: str | None = typer.Option(None, "--passphrase", "-p", help="E2EE 主密碼 (若未預先設定至 SecretStore，可由此指定)"),
    passphrase_env: str | None = typer.Option(None, "--passphrase-env", help="從指定環境變數讀取主密碼"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 格式輸出換發結果"),
) -> None:
    """[憑證換發中心] 定時或單次巡檢本機節點憑證，即將過期自動換發並回寫 Upstash。"""
    ctx = CLIContext.create()
    from application.upstash_token_service import UpstashTokenService

    resolved_pass: str | None = None
    if passphrase_env:
        resolved_pass = os.getenv(passphrase_env)
        if not resolved_pass:
            raise typer.BadParameter(f"環境變數 {passphrase_env} 未設定或內容為空。")
    elif passphrase:
        resolved_pass = passphrase

    orig_env_pass = os.environ.get("UPSTASH_SYNC_PASSPHRASE")
    if resolved_pass:
        os.environ["UPSTASH_SYNC_PASSPHRASE"] = resolved_pass

    service = UpstashTokenService(ctx.config)

    def _cli_progress(data: dict[str, Any]) -> None:
        evt = data.get("event")
        if evt == "start":
            total = data["total_remotes"]
            uc = data["unique_count"]
            cloud_on = data["cloud_enabled"]
            reason = data["cloud_disabled_reason"]
            echo(f"🔍 啟動憑證換發中心巡檢 (緩衝時間: {leeway} 分鐘)...")
            if cloud_on:
                secho("   ☁️  Upstash 雲端同步: 已啟用 (換發後將自動 E2EE 加密回寫)", fg=typer.colors.GREEN)
            else:
                secho(f"   ⚠️  Upstash 雲端同步: 未啟用 ({reason})", fg=typer.colors.YELLOW)
                echo("      提示: 憑證僅於本地刷新，不會同步至 Upstash 雲端。")
            echo(f"   共發現 {total} 個遠端節點，聚合為 {uc} 組獨立驗證帳號。")
            echo("-" * 55)

        elif evt == "checking":
            idx = data["index"]
            tot = data["total"]
            ident = data["identity"]
            remotes = ", ".join(data["remotes"])
            echo(f"\n[{idx}/{tot}] 正在巡檢帳號: {ident}")
            echo(f"      關聯節點: {remotes}")

        elif evt == "skipped":
            rem_sec = data.get("remaining_seconds")
            if rem_sec is not None:
                rem_min = rem_sec / 60.0
                echo(f"      狀態: 💤 憑證仍有效 (剩餘約 {rem_min:.1f} 分鐘 > 緩衝 {leeway} 分鐘)，略過換發。")
            else:
                echo("      狀態: 💤 憑證有效 (無特定過期限制)，略過換發。")

        elif evt == "refreshing":
            rem_sec = data.get("remaining_seconds")
            if rem_sec is not None and rem_sec > 0:
                rem_min = rem_sec / 60.0
                secho(f"      狀態: 🔄 憑證即將過期 (剩餘約 {rem_min:.1f} 分鐘 <= 緩衝 {leeway} 分鐘)，開始換發...", fg=typer.colors.CYAN)
            elif rem_sec is not None and rem_sec <= 0:
                secho("      狀態: 🔄 憑證已過期，開始換發...", fg=typer.colors.CYAN)
            else:
                secho("      狀態: 🔄 開始換發憑證...", fg=typer.colors.CYAN)
            echo("      ⏳ 正在連線驗證伺服器換發 Token (如需網頁驗證可能耗時數十秒，請稍候)...")

        elif evt == "renewed":
            sync_action = data.get("sync_action", "")
            tok_key = data.get("token_key")
            secho("      ✅ 本機憑證換發/更新成功！", fg=typer.colors.GREEN)
            if sync_action == "pushed":
                secho(f"      ☁️  已透過 E2EE 加密回寫 Upstash (Key: {tok_key})", fg=typer.colors.GREEN)
            elif sync_action == "picked":
                secho(f"      ☁️  已自 Upstash 雲端拾取其他設備換發之最新憑證 (Key: {tok_key})", fg=typer.colors.GREEN)
            elif sync_action == "failed":
                secho(f"      ⚠️  未能成功回寫 Upstash (Key: {tok_key})", fg=typer.colors.YELLOW)
            else:
                secho("      ⚠️  未回寫雲端 (Upstash 同步未啟用)", fg=typer.colors.YELLOW)

        elif evt == "error":
            err = data.get("error")
            secho(f"      ❌ 換發失敗: {err}", fg=typer.colors.RED)

    def _run_once(use_progress: bool = True) -> dict[str, Any]:
        cb = _cli_progress if (use_progress and not json_output) else None
        return service.renew_all_tokens(leeway_minutes=leeway, remote_filter=remote, progress_cb=cb)

    if interval:
        if interval < 5:
            raise typer.BadParameter("常駐巡檢間隔不可小於 5 秒。")
        secho(f"🔄 啟動 [憑證換發中心] 常駐守護行程，每 {interval} 秒巡檢一次 (緩衝: {leeway} 分鐘)...", fg=typer.colors.CYAN)
        cloud_on, reason = service.get_sync_status()
        if not cloud_on:
            secho(f"⚠️  警告: Upstash 雲端同步未啟用 ({reason})，背景換發將僅更新本地快取！", fg=typer.colors.YELLOW)
        try:
            while True:
                res = _run_once(use_progress=False)
                if json_output:
                    echo(json.dumps(res, ensure_ascii=False))
                else:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    renewed = res.get("renewed_remotes", [])
                    pushed = res.get("pushed_remotes", [])
                    picked = res.get("picked_remotes", [])
                    skipped = res.get("skipped_remotes", [])
                    cloud_synced = res.get("cloud_synced_remotes", [])
                    errs = res.get("errors", {})
                    if pushed:
                        secho(f"[{ts}] ✅ 已換發 {len(pushed)} 個節點並回寫雲端: {', '.join(pushed)}", fg=typer.colors.GREEN)
                    if picked:
                        secho(f"[{ts}] ☁️  已自雲端拾取 {len(picked)} 個節點最新憑證: {', '.join(picked)}", fg=typer.colors.GREEN)
                    local_only = [r for r in renewed if r not in pushed and r not in picked]
                    if local_only:
                        secho(f"[{ts}] ⚠️ 已換發 {len(local_only)} 個節點 (僅限本地，未同步雲端): {', '.join(local_only)}", fg=typer.colors.YELLOW)
                    if not renewed and not errs:
                        echo(f"[{ts}] 💤 所有節點憑證皆有效，略過 ({len(skipped)} 個節點)")
                    elif errs:
                        secho(f"[{ts}] ⚠️ 換發發生錯誤: {errs}", fg=typer.colors.YELLOW)
                time.sleep(interval)
        except KeyboardInterrupt:
            secho("\n🛑 已停止憑證換發中心守護行程。", fg=typer.colors.YELLOW)
            return

    try:
        res = _run_once(use_progress=True)
        if json_output:
            echo(json.dumps(res, ensure_ascii=False))
            return

        echo("\n" + "=" * 55)
        echo("🛡️  憑證換發中心巡檢結果摘要:")
        echo(f"   獨立帳號識別數:   {res.get('unique_identities_count', 0)}")
        renewed = res.get("renewed_remotes", [])
        skipped = res.get("skipped_remotes", [])
        cloud_synced = res.get("cloud_synced_remotes", [])
        cloud_enabled = res.get("cloud_enabled", False)
        reason = res.get("cloud_disabled_reason")
        errs = res.get("errors", {})

        if renewed:
            secho(f"   本機已換發節點數: {len(renewed)} 個 ({', '.join(renewed)})", fg=typer.colors.GREEN)
            pushed = res.get("pushed_remotes", [])
            picked = res.get("picked_remotes", [])
            if pushed:
                echo(f"     └─ 成功回寫雲端: {len(pushed)} 個 ({', '.join(pushed)})")
            if picked:
                echo(f"     └─ 自雲端拾取:   {len(picked)} 個 ({', '.join(picked)})")
        else:
            echo("   本機已換發節點數: 0 (憑證均尚未臨近過期)")

        if skipped:
            echo(f"   本機略過節點數:   {len(skipped)} 個 ({', '.join(skipped)})")

        if errs:
            secho(f"   換發失敗節點數:   {len(errs)}", fg=typer.colors.RED)
            for rk, ev in errs.items():
                echo(f"     - {rk}: {ev}")

        echo("-" * 55)
        if cloud_enabled:
            if cloud_synced:
                secho(f"   ☁️  雲端同步狀態: 成功同步 {len(cloud_synced)} 個節點之憑證至 Upstash (或自雲端拾取最新憑證)", fg=typer.colors.GREEN)
            elif renewed:
                secho("   ☁️  雲端同步狀態: ⚠️  換發完成，但未能成功回寫至 Upstash (請檢查連線或權限)", fg=typer.colors.YELLOW)
            else:
                echo("   ☁️  雲端同步狀態: 💤 本次無新換發憑證需要上傳")
        else:
            secho("   ☁️  雲端同步狀態: ⚠️  未啟用雲端同步！", fg=typer.colors.YELLOW)
            if reason:
                echo(f"      原因: {reason}")
            echo("      提示: 請執行 `drive-unix upstash config --passphrase <密碼>`")
            echo("            或指定 `--passphrase <密碼>` / 設定 UPSTASH_SYNC_PASSPHRASE，以啟用多設備憑證共享。")
        echo("=" * 55)
    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error("憑證換發巡檢失敗。", cause=exc, next_steps=("確認各節點設定與 Upstash 連線正常。",))
        raise typer.Exit(code=1) from exc
    finally:
        if resolved_pass:
            if orig_env_pass is None:
                os.environ.pop("UPSTASH_SYNC_PASSPHRASE", None)
            else:
                os.environ["UPSTASH_SYNC_PASSPHRASE"] = orig_env_pass


def register_upstash(app: typer.Typer) -> None:
    """Register upstash command handlers."""
    app.command("config")(upstash_config)
    app.command("test")(upstash_test)
    app.command("status")(upstash_status)
    app.command("push")(upstash_push)
    app.command("pull")(upstash_pull)
    app.command("delete")(upstash_delete)
    app.command("renew-tokens")(upstash_renew_tokens)
