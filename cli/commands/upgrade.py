"""Software upgrade CLI command for drive-unix."""

from __future__ import annotations

import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.presentation import echo, render_error, secho
from core.upgrade import (
    UpgradeStatus,
    check_for_updates,
    compare_versions,
    detect_install_mode,
    upgrade_manager,
)
from core.version import get_version

console = Console()


def upgrade_command(
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="僅檢查是否有新版本可用，不執行實際安裝與更新。",
    ),
    channel: str = typer.Option(
        "stable",
        "--channel",
        help="升級來源頻道 ('stable' 為正式釋出標籤，'main' 為主幹最新代碼)。",
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        "-v",
        help="升級或切換至特定版本號 (例如: v0.2.0)。",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="模擬升級流程，不實際寫入檔案或變更套件。",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="若版本相同或未偵測到更新，仍強制執行重新安裝。",
    ),
    backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="升級前是否自動封裝現有環境組態與認證備份 (預設啟用)。",
    ),
    restart: bool = typer.Option(
        False,
        "--restart/--no-restart",
        help="升級完成後是否自動重新載入背景服務。",
    ),
) -> None:
    """檢查並一鍵升級 drive-unix 至最新版本。"""
    current_ver = get_version()
    mode = detect_install_mode()

    # Mode 1: Check Only
    if check:
        secho("🔍 正在向 GitHub 查詢最新版本資訊...", fg=typer.colors.CYAN)
        status = check_for_updates(force=True)

        table = Table(title="drive-unix 版本資訊", box=None)
        table.add_column("項目", style="bold cyan")
        table.add_column("內容", style="white")

        table.add_row("目前安裝版本", f"v{status.current_version}")
        if status.git_commit:
            table.add_row("Git Commit", status.git_commit)
        table.add_row("安裝模式", status.install_mode.upper())
        table.add_row("最新發布版本", f"v{status.latest_version}")
        if status.release_date:
            table.add_row("發布時間", status.release_date)

        console.print(table)

        if status.has_update:
            secho(f"\n🎉 發現新版本 v{status.latest_version} 可用！", fg=typer.colors.GREEN, bold=True)
            if status.release_notes:
                console.print(Panel(status.release_notes.strip(), title="更新日誌 (Changelog)", border_style="green"))
            echo("👉 執行 [bold green]drive-unix upgrade[/bold green] 即可一鍵完成升級。")
        else:
            secho(f"\n✅ 目前已是最新版本 (v{current_ver})。", fg=typer.colors.GREEN)
        return

    # Mode 2: Execute Upgrade
    status = check_for_updates(force=False)
    if not status.has_update and not version and not force and channel != "main":
        secho(f"✅ 目前已是最新版本 (v{current_ver})。", fg=typer.colors.GREEN)
        echo("💡 若欲強制重新拉取與安裝，請加上 '--force'。")
        return

    echo(f"🚀 開始執行升級流程 [目前: v{current_ver} -> 目標: v{version or status.latest_version}]...")

    def on_event(event_type: str, data: dict):
        if event_type == "log":
            echo(data.get("text", ""))
        elif event_type == "step":
            pct = data.get("percent", 0)
            msg = data.get("message", "")
            secho(f"[{pct:>2}%] {msg}", fg=typer.colors.BLUE, bold=True)

    unsub = upgrade_manager.subscribe(on_event)

    try:
        success = upgrade_manager.run_upgrade(
            target_version=version,
            channel=channel,
            backup_config=backup,
            force=force,
            dry_run=dry_run,
            restart_after=restart,
        )
        if not success:
            render_error("升級過程中遇到錯誤，未能順利完成。")
            raise typer.Exit(code=1)
    except Exception as exc:
        render_error(f"升級執行失敗: {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        unsub()


def register(app: typer.Typer) -> None:
    """Register upgrade command on the root Typer app."""
    app.command("upgrade", help="檢查並升級 drive-unix 至最新版本")(upgrade_command)
    app.command("update", help="檢查並升級 drive-unix (upgrade 別名)", hidden=True)(upgrade_command)
