"""Upload, download and transfer CLI commands."""

from __future__ import annotations

import os
import posixpath
import sys
from contextlib import ExitStack
from urllib.parse import unquote

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from application.transfer_service import DownloadJob, TransferService, UploadJob
from cli.context import CLIContext
from cli.presentation import echo, is_plain, live_output_enabled, plain_text, render_error, secho
from cli.formatting import MarqueeColumn
from cli.transfer_ui import TransferProgressHooks
from core.constants import DEFAULT_WORKERS
from core.factory import get_storage_provider, parse_remote_path
from storage.base import managed_storage


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        MarqueeColumn(width=35),
        BarColumn(bar_width=None),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        expand=True,
        disable=not live_output_enabled(),
    )


def copy_item(
    source: str = typer.Argument(..., help="來源路徑 (例如: src_sp:/docs/A.pdf)"),
    dest: str = typer.Argument(..., help="目標路徑 (例如: dest_sp:/backup/A.pdf)"),
) -> None:
    """複製檔案或資料夾，支援同節點與跨節點傳輸。"""
    config_manager = CLIContext.create().config
    try:
        src_remote, src_path = parse_remote_path(source, config_manager.config.default_remote)
        dst_remote, dst_path = parse_remote_path(dest, config_manager.config.default_remote)
        secho(
            f"🚀 準備複製: [{src_remote}]{src_path} -> [{dst_remote}]{dst_path}",
            fg=typer.colors.CYAN,
        )

        with ExitStack() as stack:
            src_storage = stack.enter_context(
                managed_storage(get_storage_provider(src_remote, config_manager))
            )
            dst_storage = (
                src_storage
                if src_remote == dst_remote
                else stack.enter_context(
                    managed_storage(get_storage_provider(dst_remote, config_manager))
                )
            )
            with _progress() as progress:
                task = progress.add_task(
                    "", filename="準備中...", icon="🚀", color="cyan", total=100
                )

                def dl_cb(transferred: int, total: int) -> None:
                    progress.update(
                        task,
                        filename="跨節點下載中...",
                        icon="⬇",
                        color="blue",
                        completed=transferred,
                        total=total,
                    )

                def ul_cb(transferred: int, total: int) -> None:
                    progress.update(
                        task,
                        filename="跨節點上傳中...",
                        icon="⬆",
                        color="magenta",
                        completed=transferred,
                        total=total,
                    )

                def direct_cb(transferred: int, total: int) -> None:
                    progress.update(
                        task,
                        filename="伺服器端處理中...",
                        icon="🔄",
                        color="green",
                        completed=transferred,
                        total=total,
                    )

                TransferService().copy_between(
                    src_remote,
                    src_storage,
                    src_path,
                    dst_remote,
                    dst_storage,
                    dst_path,
                    download_callback=dl_cb,
                    upload_callback=ul_cb,
                    direct_callback=direct_cb,
                )
                progress.update(
                    task,
                    filename="複製完成！",
                    icon="✅",
                    color="green",
                    completed=100,
                    total=100,
                )

        secho("\n✅ 複製流程結束！", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            "複製操作失敗。",
            cause=exc,
            next_steps=(
                "確認來源與目標皆使用 `REMOTE:/path` 格式且路徑存在。",
                "執行 `drive-unix remote test <REMOTE>` 檢查來源/目標 Remote。",
            ),
        )
        raise typer.Exit(code=1) from exc


def move_item(
    source: str = typer.Argument(..., help="來源路徑 (例如: src_sp:/docs/A.pdf)"),
    dest: str = typer.Argument(..., help="目標路徑 (例如: dest_sp:/backup/A.pdf)"),
) -> None:
    """移動檔案或資料夾；跨節點時使用安全橋接傳輸。"""
    config_manager = CLIContext.create().config
    try:
        src_remote, src_path = parse_remote_path(source, config_manager.config.default_remote)
        dst_remote, dst_path = parse_remote_path(dest, config_manager.config.default_remote)
        secho(
            f"🚀 準備移動: [{src_remote}]{src_path} -> [{dst_remote}]{dst_path}",
            fg=typer.colors.CYAN,
        )

        with ExitStack() as stack:
            src_storage = stack.enter_context(
                managed_storage(get_storage_provider(src_remote, config_manager))
            )
            dst_storage = (
                src_storage
                if src_remote == dst_remote
                else stack.enter_context(
                    managed_storage(get_storage_provider(dst_remote, config_manager))
                )
            )

            if src_remote == dst_remote:
                TransferService().move_between(
                    src_remote, src_storage, src_path, dst_remote, dst_storage, dst_path
                )
            else:
                secho(
                    "🌉 偵測到跨節點操作，啟動中繼橋接模式...",
                    fg=typer.colors.YELLOW,
                )
                with _progress() as progress:
                    task = progress.add_task(
                        "", filename="準備中...", icon="🚀", color="cyan", total=100
                    )

                    def dl_cb(transferred: int, total: int) -> None:
                        progress.update(
                            task,
                            filename="從來源提取中...",
                            icon="⬇",
                            color="blue",
                            completed=transferred,
                            total=total,
                        )

                    def ul_cb(transferred: int, total: int) -> None:
                        progress.update(
                            task,
                            filename="注入至目標端...",
                            icon="⬆",
                            color="magenta",
                            completed=transferred,
                            total=total,
                        )

                    TransferService().move_between(
                        src_remote,
                        src_storage,
                        src_path,
                        dst_remote,
                        dst_storage,
                        dst_path,
                        download_callback=dl_cb,
                        upload_callback=ul_cb,
                    )

        secho("\n✅ 移動完成！", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            "移動操作失敗。",
            cause=exc,
            next_steps=(
                "確認來源可讀取、目標可寫入，且路徑格式正確。",
                "跨 Remote 移動會先複製再刪除來源；請檢查兩端權限。",
            ),
        )
        raise typer.Exit(code=1) from exc


def upload(
    local_path: str = typer.Argument(..., help="本機檔案或資料夾路徑"),
    remote_path: str = typer.Argument(..., help="遠端目標路徑 (例如: my_sp:/Shared Documents/)"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="是否遞迴上傳整個資料夾"),
    workers: int = typer.Option(
        DEFAULT_WORKERS,
        "--workers",
        "-w",
        help=f"併發執行緒數量 (預設為 {DEFAULT_WORKERS})",
    ),
) -> None:
    """上傳本機檔案或整個資料夾到雲端。"""
    config_manager = CLIContext.create().config
    service = TransferService()
    try:
        if workers < 1:
            raise ValueError("workers 必須大於等於 1")
        remote_name, parsed_remote_path = parse_remote_path(
            remote_path, config_manager.config.default_remote
        )
        with managed_storage(get_storage_provider(remote_name, config_manager)) as storage:
            if os.path.isdir(local_path):
                if not recursive:
                    raise ValueError(
                        f"'{local_path}' 是一個資料夾，請加上 --recursive 或 -r。"
                    )
                plan = service.build_recursive_upload_plan(local_path, parsed_remote_path)
                secho(
                    f"🚀 準備遞迴上傳資料夾: {local_path} -> "
                    f"[{remote_name}]{plan.remote_root}",
                    fg=typer.colors.CYAN,
                )

                if not plan.jobs:
                    result = service.upload_tree(storage, plan, workers=workers)
                    if not result.success:
                        raise RuntimeError("空資料夾建立失敗")
                    secho("✅ 資料夾沒有檔案；空目錄結構已建立。", fg=typer.colors.GREEN)
                    return

                with _progress() as progress:
                    overall = progress.add_task(
                        "",
                        filename="總體上傳進度",
                        icon="📦",
                        color="bold green",
                        total=len(plan.jobs),
                    )
                    hooks = TransferProgressHooks[UploadJob](
                        progress,
                        workers=workers,
                        overall_task=overall,
                        filename=lambda job: os.path.basename(job.local_path),
                        icon="⬆",
                        color="cyan",
                    )
                    result = service.upload_tree(
                        storage,
                        plan,
                        workers=workers,
                        on_started=hooks.started,
                        on_finished=hooks.finished,
                    )
                    for failure in result.failures:
                        message = (
                            f"處理 {os.path.basename(failure.job.local_path)} 時失敗："
                            f"{failure.error}"
                        )
                        if is_plain():
                            progress.console.print(plain_text(message), markup=False)
                        else:
                            progress.console.print(f"[red]❌ {message}[/red]")

                if not result.success:
                    raise RuntimeError(
                        f"資料夾上傳未完成：{result.failed} 個檔案失敗，"
                        f"{result.succeeded} 個成功。"
                    )
                secho("🎉 整個資料夾上傳流程結束。", fg=typer.colors.GREEN)
                return

            service.ensure_remote_directory(storage, posixpath.dirname(parsed_remote_path))
            secho(
                f"🚀 準備上傳檔案: {local_path} -> [{remote_name}]{parsed_remote_path}",
                fg=typer.colors.CYAN,
            )
            file_size = os.path.getsize(local_path)
            with _progress() as progress:
                task = progress.add_task(
                    "",
                    filename=f"上傳 {os.path.basename(local_path)}",
                    icon="⬆",
                    color="cyan",
                    total=file_size,
                )
                service.call_upload(
                    storage,
                    local_path,
                    parsed_remote_path,
                    callback=lambda transferred, total: progress.update(
                        task, completed=transferred, total=total
                    ),
                )
            secho("🎉 檔案上傳流程結束。", fg=typer.colors.GREEN)
    except typer.Exit:
        raise
    except Exception as exc:
        render_error(
            "上傳失敗。",
            cause=exc,
            next_steps=(
                "確認本機來源存在；上傳資料夾時加上 `--recursive`。",
                "確認目標 Remote 具備寫入權限。",
            ),
        )
        raise typer.Exit(code=1) from exc


def download(
    remote_path: str = typer.Argument(..., help="遠端檔案或資料夾路徑"),
    local_path: str = typer.Argument(None, help="本機儲存路徑；預設為目前目錄"),
    workers: int = typer.Option(
        DEFAULT_WORKERS,
        "--workers",
        "-w",
        help=f"併發執行緒數量 (預設為 {DEFAULT_WORKERS})",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="強制重新下載大小相同的檔案"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="下載資料夾及其所有內容"),
) -> None:
    """下載雲端檔案或整個資料夾到本機。"""
    config_manager = CLIContext.create().config
    service = TransferService()
    try:
        if workers < 1:
            raise ValueError("workers 必須大於等於 1")
        remote_name, parsed_remote_path = parse_remote_path(
            remote_path, config_manager.config.default_remote
        )
        local_path = local_path or os.getcwd()
        secho(
            f"🚀 準備從節點: [{remote_name}] 下載: {parsed_remote_path}",
            fg=typer.colors.CYAN,
        )

        with managed_storage(get_storage_provider(remote_name, config_manager)) as storage:
            target_file_path = local_path
            if os.path.isdir(local_path):
                filename = unquote(parsed_remote_path.strip("/").split("/")[-1])
                target_file_path = os.path.join(local_path, filename)

            if not force and os.path.isfile(target_file_path):
                try:
                    remote_stat = storage.stat(parsed_remote_path)
                except Exception:
                    remote_stat = {}
                remote_size = remote_stat.get("size")
                if isinstance(remote_size, int) and os.path.getsize(target_file_path) == remote_size:
                    secho(
                        f"⏩ 本機已存在相同大小的檔案，略過下載: {target_file_path}",
                        fg=typer.colors.YELLOW,
                    )
                    return

            try:
                with _progress() as progress:
                    task = progress.add_task(
                        "", filename="下載中...", icon="⬇", color="blue", total=None
                    )
                    service.call_download(
                        storage,
                        parsed_remote_path,
                        target_file_path,
                        recursive=False,
                        callback=lambda transferred, total: progress.update(
                            task, completed=transferred, total=total
                        ),
                    )
                secho("🎉 檔案下載成功！", fg=typer.colors.GREEN)
                return
            except IsADirectoryError:
                secho("\n📁 注意：目標是一個資料夾。", fg=typer.colors.YELLOW)

            if not recursive:
                if sys.stdin.isatty() and typer.confirm("是否要下載整個資料夾及其所有內容？"):
                    recursive = True
                else:
                    raise ValueError("目標是資料夾；請加上 --recursive 或 -r。")

            plan = service.build_recursive_download_plan(
                storage,
                parsed_remote_path,
                local_path,
                force=force,
            )
            if plan.skipped:
                secho(
                    f"⏩ 已略過 {plan.skipped} 個大小相符的已存在檔案。",
                    fg=typer.colors.YELLOW,
                )
            if not plan.jobs:
                os.makedirs(plan.local_root, exist_ok=True)
                for directory in plan.directories:
                    os.makedirs(directory, exist_ok=True)
                secho(
                    "✅ 資料夾無新檔案或所有檔案均已存在且大小相符，無需下載。",
                    fg=typer.colors.GREEN,
                )
                return

            with _progress() as progress:
                overall = progress.add_task(
                    "",
                    filename="總體下載進度",
                    icon="📦",
                    color="bold green",
                    total=len(plan.jobs),
                )
                hooks = TransferProgressHooks[DownloadJob](
                    progress,
                    workers=workers,
                    overall_task=overall,
                    filename=lambda job: job.item.name,
                    icon="⬇",
                    color="blue",
                )
                result = service.download_tree(
                    storage,
                    plan,
                    workers=workers,
                    on_started=hooks.started,
                    on_finished=hooks.finished,
                )
                for failure in result.failures:
                    message = f"下載 {failure.job.item.name} 時失敗：{failure.error}"
                    if is_plain():
                        progress.console.print(plain_text(message), markup=False)
                    else:
                        progress.console.print(f"[red]❌ {message}[/red]")

            if not result.success:
                raise RuntimeError(
                    f"資料夾下載未完成：{result.failed} 個檔案失敗，"
                    f"{result.succeeded} 個成功。"
                )
            secho("🎉 資料夾及其內容下載完成！", fg=typer.colors.GREEN)
    except typer.Exit:
        raise
    except Exception as exc:
        render_error(
            "下載失敗。",
            cause=exc,
            next_steps=(
                "確認遠端路徑存在且可讀取。",
                "下載資料夾時加上 `--recursive`；確認本機目標目錄可寫入。",
            ),
        )
        raise typer.Exit(code=1) from exc


def download_link(
    remote_path: str = typer.Argument(
        ..., help="遠端檔案路徑 (例如: my_sp:/Shared Documents/file.pdf)"
    ),
) -> None:
    """取得 Provider 可用的直接下載或分享連結。"""
    config_manager = CLIContext.create().config
    try:
        remote_name, parsed_remote_path = parse_remote_path(
            remote_path, config_manager.config.default_remote
        )
        with managed_storage(get_storage_provider(remote_name, config_manager)) as storage:
            download_url = storage.get_download_link(parsed_remote_path)
        secho(
            "\n🎁 取得下載 / 分享連結（有效期限與認證方式依 Provider 而定）:",
            fg=typer.colors.GREEN,
            bold=True,
        )
        echo(download_url)
        remote_type = config_manager.get_remote(remote_name).type
        if remote_type in {"ftp", "webdav"}:
            secho(
                "⚠️ 此 Provider 的連結可能包含帳號或密碼資訊；請視為敏感憑證，不要公開分享。",
                fg=typer.colors.YELLOW,
            )
    except Exception as exc:
        render_error(
            "無法取得下載連結。",
            cause=exc,
            next_steps=(
                "確認 Provider 支援臨時下載連結，且遠端檔案存在。",
                "若 Provider 不支援此功能，請改用 `drive-unix download`。",
            ),
        )
        raise typer.Exit(code=1) from exc


def register(app: typer.Typer) -> None:
    app.command("cp")(copy_item)
    app.command("mv")(move_item)
    app.command("upload")(upload)
    app.command("download")(download)
    app.command("download-link")(download_link)
