"""Application factory for the command-line interface."""

from __future__ import annotations

import os

import typer

from cli.commands import cron, environment, files, nodes, sync, transfer, upstash
from cli.presentation import configure_presentation


def create_app() -> typer.Typer:
    """Create and configure the root Typer application."""
    app = typer.Typer(help="多 Provider 檔案管理與同步 CLI", no_args_is_help=True)

    @app.callback()
    def root_options(
        ctx: typer.Context,
        plain: bool = typer.Option(
            False,
            "--plain",
            help="使用純文字輸出：停用色彩、emoji 與動態進度，適合 log/CI/screen reader。",
        ),
    ) -> None:
        """Configure global presentation options before dispatching commands."""
        configure_presentation(plain=plain)
        if plain or "NO_COLOR" in os.environ:
            ctx.color = False

    remote_app = typer.Typer(help="管理 Remote 設定與連線測試", no_args_is_help=True)
    schedule_app = typer.Typer(help="管理與啟動排程任務", no_args_is_help=True)
    environment_app = typer.Typer(help="匯入或匯出 drive-unix 環境", no_args_is_help=True)
    upstash_app = typer.Typer(help="Upstash 雲端多端安全同步 (E2EE)", no_args_is_help=True)

    nodes.register_remote(remote_app)
    cron.register_schedule(schedule_app)
    environment.register_environment(environment_app)
    upstash.register_upstash(upstash_app)

    app.add_typer(remote_app, name="remote")
    app.add_typer(schedule_app, name="schedule")
    app.add_typer(environment_app, name="env")
    app.add_typer(upstash_app, name="upstash")

    files.register(app)
    transfer.register(app)
    sync.register(app)
    nodes.register(app)
    environment.register(app)
    cron.register(app)

    return app
