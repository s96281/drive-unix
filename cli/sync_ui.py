"""Presentation adapters for synchronization commands."""

from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import dataclass

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from application.sync_service import (
    SyncActionToken,
    SyncExecutionResult,
    SyncHooks,
    SyncService,
)
from cli.formatting import MarqueeColumn, format_size
from cli.presentation import echo, live_output_enabled, secho
from domain.sync.models import SyncAction, SyncActionType, SyncPlan
from storage.base import DeleteCapability, StorageProvider

_ACTION_LABELS = {
    SyncActionType.COPY_TO_DEST: "[+] 傳輸 (來源->目標)",
    SyncActionType.COPY_TO_SRC: "[+] 傳輸 (目標->來源)",
    SyncActionType.SYNC_OFFICE: "[+] 傳輸並回寫 (來源->目標->來源)",
    SyncActionType.MKDIR_DEST: "[+] 建立資料夾 (目標)",
    SyncActionType.MKDIR_SRC: "[+] 建立資料夾 (來源)",
    SyncActionType.DELETE_DEST: "[-] 刪除 (目標)",
    SyncActionType.DELETE_SRC: "[-] 刪除 (來源)",
    SyncActionType.RENAME_DEST: "[~] 重新命名/移動 (目標)",
    SyncActionType.RENAME_SRC: "[~] 重新命名/移動 (來源)",
}

_ACTION_COLORS = {
    SyncActionType.COPY_TO_DEST: typer.colors.GREEN,
    SyncActionType.COPY_TO_SRC: typer.colors.BLUE,
    SyncActionType.SYNC_OFFICE: typer.colors.MAGENTA,
    SyncActionType.MKDIR_DEST: typer.colors.GREEN,
    SyncActionType.MKDIR_SRC: typer.colors.BLUE,
    SyncActionType.DELETE_DEST: typer.colors.RED,
    SyncActionType.DELETE_SRC: typer.colors.RED,
    SyncActionType.RENAME_DEST: typer.colors.MAGENTA,
    SyncActionType.RENAME_SRC: typer.colors.MAGENTA,
}


def scan_progress(label: str) -> Callable[[int, int], None]:
    if not live_output_enabled():
        return lambda folders, files: None

    def render(folders: int, files: int) -> None:
        print(
            f"📊 {label}掃描中... {folders} 個資料夾, {files} 個檔案",
            end="\r",
            flush=True,
        )

    return render


def clear_scan_progress() -> None:
    if live_output_enabled():
        print(" " * 100, end="\r", flush=True)


@dataclass(frozen=True)
class SyncPlanSummary:
    transfers: int
    directories: int
    renames: int
    delete_source: int
    delete_destination: int
    transfer_bytes: int
    delete_bytes: int

    @property
    def deletes(self) -> int:
        return self.delete_source + self.delete_destination


def summarize_plan(plan: SyncPlan) -> SyncPlanSummary:
    transfer_types = {
        SyncActionType.COPY_TO_DEST,
        SyncActionType.COPY_TO_SRC,
        SyncActionType.SYNC_OFFICE,
    }
    directory_types = {SyncActionType.MKDIR_DEST, SyncActionType.MKDIR_SRC}
    rename_types = {SyncActionType.RENAME_DEST, SyncActionType.RENAME_SRC}

    actions = plan.actions
    return SyncPlanSummary(
        transfers=sum(action.action_type in transfer_types for action in actions),
        directories=sum(action.action_type in directory_types for action in actions),
        renames=sum(action.action_type in rename_types for action in actions),
        delete_source=sum(action.action_type == SyncActionType.DELETE_SRC for action in actions),
        delete_destination=sum(
            action.action_type == SyncActionType.DELETE_DEST for action in actions
        ),
        transfer_bytes=sum(
            action.item.size
            for action in actions
            if action.action_type in transfer_types and not action.item.is_dir
        ),
        delete_bytes=sum(
            action.item.size
            for action in actions
            if action.action_type in {SyncActionType.DELETE_SRC, SyncActionType.DELETE_DEST}
            and not action.item.is_dir
        ),
    )


def render_plan(plan: SyncPlan, *, full_plan: bool = False, detail_limit: int = 20) -> None:
    summary = summarize_plan(plan)
    echo("-" * 50)
    secho(f"📋 同步計畫總結（共 {plan.count} 個操作）", fg=typer.colors.CYAN, bold=True)
    echo(f"  傳輸/更新 : {summary.transfers} ({format_size(summary.transfer_bytes)})")
    echo(f"  建立資料夾: {summary.directories}")
    echo(f"  重新命名  : {summary.renames}")
    delete_text = f"{summary.deletes} ({format_size(summary.delete_bytes)})"
    if summary.deletes:
        secho(f"  刪除      : {delete_text}", fg=typer.colors.RED, bold=True)
    else:
        echo(f"  刪除      : {delete_text}")

    actions_to_render = plan.actions
    if not full_plan and plan.count > detail_limit:
        risky = tuple(
            action
            for action in plan.actions
            if action.action_type
            in {
                SyncActionType.DELETE_DEST,
                SyncActionType.DELETE_SRC,
                SyncActionType.RENAME_DEST,
                SyncActionType.RENAME_SRC,
            }
        )
        actions_to_render = risky[:detail_limit]
        echo("-" * 50)
        if actions_to_render:
            echo(
                f"僅顯示前 {len(actions_to_render)} 個高風險操作；"
                "使用 --full-plan 顯示完整計畫。"
            )
        else:
            echo("操作數量較多；使用 --full-plan 顯示完整逐項計畫。")

    for action in actions_to_render:
        target_text = (
            action.item.path
            if action.action_type in {SyncActionType.DELETE_DEST, SyncActionType.DELETE_SRC}
            else f"{action.item.path} -> {action.target_path}"
        )
        secho(
            f"  {_ACTION_LABELS[action.action_type]}: {target_text} ({action.reason})",
            fg=_ACTION_COLORS[action.action_type],
        )
    echo("-" * 50)


def render_delete_risks(
    plan: SyncPlan,
    *,
    source_storage: StorageProvider,
    destination_storage: StorageProvider,
) -> int:
    """Render provider-aware deletion consequences and return irreversible count."""

    summary = summarize_plan(plan)
    irreversible = 0

    def render_side(label: str, count: int, storage: StorageProvider) -> None:
        nonlocal irreversible
        if not count:
            return
        if storage.delete_capability == DeleteCapability.PERMANENT_ONLY:
            irreversible += count
            secho(
                f"⚠️ {label} Provider 不支援回收桶；{count} 個刪除操作將永久刪除，"
                "無法由 drive-unix 復原。",
                fg=typer.colors.RED,
                bold=True,
            )
        else:
            secho(
                f"ℹ️ {label}的 {count} 個刪除操作會移至 Provider 回收桶。",
                fg=typer.colors.YELLOW,
            )

    render_side("來源端", summary.delete_source, source_storage)
    render_side("目標端", summary.delete_destination, destination_storage)
    return irreversible


class RichSyncHooks(SyncHooks):
    def __init__(self, progress_bar: Progress, worker_count: int, overall_task: int) -> None:
        self.progress_bar = progress_bar
        self.overall_task = overall_task
        self.task_queue: queue.Queue[int] = queue.Queue()
        self.labels: dict[int, str] = {}
        for index in range(worker_count):
            task_id = progress_bar.add_task(
                "",
                filename=f"閒置線程 {index + 1}",
                icon="⠧",
                color="dim",
                total=100,
            )
            self.task_queue.put(task_id)

    def action_started(self, action: SyncAction) -> SyncActionToken:
        task_id = self.task_queue.get()
        self.labels[task_id] = action.item.name
        return SyncActionToken(task_id)

    def progress(
        self,
        token: SyncActionToken | None,
        stage: str,
        transferred: int,
        total: int,
    ) -> None:
        if token is None:
            return
        task_id = token.action_id
        icon = {"download": "⬇", "upload": "⬆", "copy": "🔄"}.get(stage, "🔄")
        color = {"download": "cyan", "upload": "magenta", "copy": "green"}.get(
            stage, "green"
        )
        self.progress_bar.update(
            task_id,
            filename=self.labels.get(task_id, "處理中"),
            icon=icon,
            color=color,
            completed=transferred,
            total=total,
        )

    def action_finished(
        self,
        action: SyncAction,
        token: SyncActionToken | None,
        error: Exception | None,
    ) -> None:
        del action, error
        if token is None:
            return
        task_id = token.action_id
        self.progress_bar.update(
            task_id,
            filename="閒置線程",
            icon="⠧",
            color="dim",
            completed=0,
            total=100,
        )
        self.progress_bar.update(self.overall_task, advance=1)
        self.task_queue.put(task_id)


class VerboseSyncHooks(SyncHooks):
    def action_started(self, action: SyncAction) -> None:
        echo(f"🚀 執行: {action.item.name} -> {action.target_path}")
        return None

    def action_finished(
        self,
        action: SyncAction,
        token: SyncActionToken | None,
        error: Exception | None,
    ) -> None:
        del token
        if error:
            secho(f"❌ 處理 {action.item.name} 時失敗: {error}", fg=typer.colors.RED)


def execute_sync_plan(
    service: SyncService,
    plan: SyncPlan,
    *,
    workers: int,
    throttle: float,
    detailed_progress: bool,
) -> SyncExecutionResult:
    if not detailed_progress:
        return service.execute(
            plan,
            workers=workers,
            throttle=throttle,
            hooks=VerboseSyncHooks(),
        )

    with Progress(
        SpinnerColumn(),
        MarqueeColumn(width=35),
        BarColumn(bar_width=None),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        expand=True,
        disable=not live_output_enabled(),
    ) as progress_bar:
        overall_task = progress_bar.add_task(
            "",
            filename="總體同步進度",
            icon="✅",
            color="bold green",
            total=plan.count,
        )
        return service.execute(
            plan,
            workers=workers,
            throttle=throttle,
            hooks=RichSyncHooks(progress_bar, workers, overall_task),
        )
