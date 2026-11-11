"""Setup CLI command integrating setup orchestrator."""

from __future__ import annotations

import argparse
from typing import Optional

import typer


def setup_command(
    role: Optional[str] = typer.Option(
        None,
        "--role",
        help="指定安裝角色 (pc: 個人電腦/工作站, vps: 雲端伺服器/換發中心)",
    ),
    host: Optional[str] = typer.Option(
        None,
        "--host",
        help="Web 服務監聽 IP (預設: PC 為 127.0.0.1, VPS 為 0.0.0.0)",
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        help="Web 服務監聽埠號 (預設: 8000)",
    ),
    upstash_url: Optional[str] = typer.Option(
        None,
        "--upstash-url",
        help="Upstash REST URL (例如: https://...upstash.io)",
    ),
    upstash_token: Optional[str] = typer.Option(
        None,
        "--upstash-token",
        help="Upstash REST Token",
    ),
    sync_key: Optional[str] = typer.Option(
        None,
        "--sync-key",
        help="Upstash 同步金鑰 (預設: drive-unix:sync:default)",
    ),
    passphrase: Optional[str] = typer.Option(
        None,
        "--passphrase",
        "-p",
        help="E2EE 主密碼 (Passphrase)",
    ),
    skip_upstash: bool = typer.Option(
        False,
        "--skip-upstash",
        help="略過 Upstash 雲端多端同步設定",
    ),
    skip_playwright: bool = typer.Option(
        False,
        "--skip-playwright",
        help="略過 Playwright Chromium 瀏覽器核心安裝",
    ),
    skip_service: bool = typer.Option(
        False,
        "--skip-service",
        help="略過背景常駐服務 (Systemd) 註冊",
    ),
    start: bool = typer.Option(
        False,
        "--start",
        help="設定完成後自動啟動服務或開啟 Web 介面",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="非互動自動化模式",
    ),
) -> None:
    """啟動 drive-unix 統一安裝與初始化導引精靈 (PC / VPS / Upstash)。"""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from scripts.setup import SetupOrchestrator
    except ImportError:
        import importlib.util
        setup_script = project_root / "scripts" / "setup.py"
        if setup_script.exists():
            spec = importlib.util.spec_from_file_location("setup_module", setup_script)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                SetupOrchestrator = getattr(mod, "SetupOrchestrator")
            else:
                raise
        else:
            raise

    args = argparse.Namespace(
        role=role,
        host=host,
        port=port,
        upstash_url=upstash_url,
        upstash_token=upstash_token,
        sync_key=sync_key,
        passphrase=passphrase,
        skip_upstash=skip_upstash,
        skip_playwright=skip_playwright,
        skip_service=skip_service,
        start=start,
        non_interactive=non_interactive,
    )
    orchestrator = SetupOrchestrator(args)
    orchestrator.run()


def register(app: typer.Typer) -> None:
    """Register setup command to root CLI application."""
    app.command("setup")(setup_command)
