"""Scheduler-related Typer commands."""

from __future__ import annotations

import os
import signal
import sys
from datetime import datetime

import typer

from application.scheduler_daemon import SchedulerDaemonManager, SchedulerDaemonStatus
from application.scheduler_service import SchedulerService
from application.scheduling import validate_cron_expression
from cli.presentation import echo, render_error, secho
from core.config import ConfigManager, CronTask


def cron_add(
    name: str = typer.Argument(..., help="排程名稱 (例如: nightly_backup)"),
    schedule: str = typer.Argument(..., help="Cron 運算式 (例如: '0 2 * * *')"),
    command: str = typer.Argument(..., help="要執行的 CLI 指令與參數"),
) -> None:
    """新增一項自動排程任務。"""
    config_manager = ConfigManager()

    try:
        validate_cron_expression(schedule)
    except ValueError as exc:
        render_error(
            "無法新增排程：Cron 格式無效。",
            cause=exc,
            next_steps=(
                "使用五欄 Cron 格式：分 時 日 月 星期。",
                "範例：`drive-unix schedule add nightly '0 2 * * *' \"sync src:/ dst:/ --yes\"`。",
            ),
        )
        raise typer.Exit(code=1) from exc

    task = CronTask(name=name, schedule=schedule, command=command, enabled=True)
    try:
        config_manager.add_task(name, task)
    except Exception as exc:
        render_error(
            f"無法儲存排程任務 `{name}`。",
            cause=exc,
            next_steps=("確認設定目錄可寫入後重試。",),
        )
        raise typer.Exit(code=1) from exc

    secho(f"✅ 已新增排程任務 `{name}`。", fg=typer.colors.GREEN)
    echo("下一步：執行 `drive-unix schedule service start` 在背景啟動排程器，")
    echo("或使用 `drive-unix schedule start` 在目前終端機以前景方式執行。")


def cron_ls() -> None:
    """列出所有排程任務。"""
    config_manager = ConfigManager()
    tasks = config_manager.config.tasks

    if not tasks:
        secho(
            "⚠️ 目前沒有排程任務。可使用 `drive-unix schedule add` 新增。",
            fg=typer.colors.YELLOW,
        )
        return

    secho(f"📋 排程任務：{len(tasks)} 個\n", fg=typer.colors.CYAN, bold=True)
    for name, task in tasks.items():
        status = "🟢 啟用" if task.enabled else "🔴 停用"
        secho(f"🕒 [{name}] {status}", fg=typer.colors.GREEN, bold=True)
        last_attempt = task.last_attempt_at or task.last_run or "尚未執行"
        last_success = task.last_success_at or "尚無成功紀錄"
        exit_code = "尚無結果" if task.last_exit_code is None else str(task.last_exit_code)
        echo(f"   ├─ 排程: {task.schedule}")
        echo(f"   ├─ 最後嘗試: {last_attempt}")
        echo(f"   ├─ 最後成功: {last_success}")
        echo(f"   ├─ Exit code: {exit_code}")
        echo(f"   └─ 指令: {task.command}\n")


def cron_rm(name: str = typer.Argument(..., help="要移除的排程名稱")) -> None:
    """從設定檔中移除指定的排程任務。"""
    config_manager = ConfigManager()
    try:
        config_manager.remove_task(name)
        secho(f"✅ 已移除排程任務 `{name}`。", fg=typer.colors.GREEN)
    except ValueError as exc:
        render_error(
            f"找不到排程任務 `{name}`。",
            cause=exc,
            next_steps=("執行 `drive-unix schedule list` 查看可用任務名稱。",),
        )
        raise typer.Exit(code=1) from exc


def cron_toggle(
    name: str = typer.Argument(..., help="要切換狀態的排程名稱"),
    enable: bool = typer.Option(True, "--enable/--disable", help="啟用或停用該任務"),
) -> None:
    """啟用或停用指定的排程任務。"""
    config_manager = ConfigManager()
    try:
        config_manager.toggle_task(name, enable)
    except ValueError as exc:
        render_error(
            f"無法更新排程任務 `{name}`。",
            cause=exc,
            next_steps=("執行 `drive-unix schedule list` 確認任務名稱。",),
        )
        raise typer.Exit(code=1) from exc

    status = "啟用" if enable else "停用"
    secho(f"✅ 已{status}排程任務 `{name}`。", fg=typer.colors.GREEN)


def _scheduler_renderer(level: str, message: str) -> None:
    colors = {
        "success": typer.colors.GREEN,
        "error": typer.colors.RED,
        "warning": typer.colors.YELLOW,
        "info": typer.colors.MAGENTA,
    }
    secho(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}",
        fg=colors.get(level, typer.colors.WHITE),
    )


def _run_scheduler_foreground(*, service_child: bool = False) -> None:
    daemon = SchedulerDaemonManager(
        executable=sys.executable,
        script_path=os.path.abspath(sys.argv[0]),
    )
    if service_child:
        daemon.claim_current_process()

        def _terminate(_signum, _frame) -> None:
            raise KeyboardInterrupt

        try:
            signal.signal(signal.SIGTERM, _terminate)
        except (AttributeError, ValueError):
            pass

    service = SchedulerService(
        executable=sys.executable,
        script_path=os.path.abspath(sys.argv[0]),
    )
    try:
        service.run_forever(output=_scheduler_renderer)
    except KeyboardInterrupt:
        if not service_child:
            secho("\n🛑 排程器已停止。", fg=typer.colors.YELLOW)
    finally:
        if service_child:
            daemon.release_current_process()


def cron_start() -> None:
    """在目前終端機以前景方式啟動排程器。"""
    secho("🕒 啟動排程器（前景模式）...", fg=typer.colors.CYAN, bold=True)
    echo("按下 Ctrl+C 可停止。需要背景執行時，請使用 `drive-unix schedule service start`。")
    _run_scheduler_foreground(service_child=False)


def _run_service_child() -> None:
    """Internal service entry point. Managed by ``schedule service``."""
    _run_scheduler_foreground(service_child=True)


def _render_service_status(status: SchedulerDaemonStatus) -> None:
    state = "執行中" if status.running else "已停止"
    install_state = "已安裝" if status.installed else "未安裝（使用 detached process 模式）"
    secho(
        f"{'✅' if status.running else '⚠️'} Scheduler service: {state}",
        fg=typer.colors.GREEN if status.running else typer.colors.YELLOW,
        bold=True,
    )
    echo(f"Backend : {status.backend}")
    echo(f"Service : {install_state}")
    echo(f"PID     : {status.pid if status.pid is not None else '-'}")
    echo(f"Log     : {status.log_path}")


def service_install() -> None:
    """註冊登入後自動啟動的 OS-level scheduler service。"""
    manager = SchedulerDaemonManager()
    try:
        manager.install()
    except Exception as exc:
        render_error(
            "Scheduler service 安裝失敗。",
            cause=exc,
            next_steps=(
                "確認目前帳號可使用對應的 user service（systemd/launchd/Task Scheduler）。",
                "若只需要本次登入階段，可直接執行 `drive-unix schedule service start`。",
            ),
        )
        raise typer.Exit(code=1) from exc
    secho("✅ Scheduler service 已安裝並設定為登入後自動啟動。", fg=typer.colors.GREEN)
    echo("執行 `drive-unix schedule service start` 可立即啟動。")


def service_start() -> None:
    """在背景啟動 scheduler service。"""
    manager = SchedulerDaemonManager()
    try:
        status = manager.start()
    except Exception as exc:
        render_error(
            "Scheduler service 無法啟動。",
            cause=exc,
            next_steps=(
                "執行 `drive-unix schedule service status` 查看目前狀態。",
                f"檢查 scheduler log：{manager.log_path}",
            ),
        )
        raise typer.Exit(code=1) from exc
    _render_service_status(status)
    if not status.running:
        render_error(
            "已送出啟動要求，但 scheduler 尚未進入執行狀態。",
            next_steps=(f"檢查 log：{manager.log_path}",),
        )
        raise typer.Exit(code=1)


def service_status() -> None:
    """顯示 scheduler service 的安裝與執行狀態。"""
    manager = SchedulerDaemonManager()
    try:
        _render_service_status(manager.status())
    except Exception as exc:
        render_error("無法取得 Scheduler service 狀態。", cause=exc)
        raise typer.Exit(code=1) from exc


def service_stop() -> None:
    """停止背景 scheduler service。"""
    manager = SchedulerDaemonManager()
    try:
        before = manager.status()
        status = manager.stop()
    except Exception as exc:
        render_error(
            "Scheduler service 無法停止。",
            cause=exc,
            next_steps=(f"檢查 log：{manager.log_path}",),
        )
        raise typer.Exit(code=1) from exc
    if not before.running:
        secho("⚠️ Scheduler service 原本就沒有執行。", fg=typer.colors.YELLOW)
    else:
        secho("✅ Scheduler service 已停止。", fg=typer.colors.GREEN)
    _render_service_status(status)


def service_uninstall() -> None:
    """移除 OS-level scheduler service 註冊。"""
    manager = SchedulerDaemonManager()
    try:
        manager.uninstall()
    except Exception as exc:
        render_error(
            "Scheduler service 無法解除安裝。",
            cause=exc,
            next_steps=("先執行 `drive-unix schedule service stop` 後再重試。",),
        )
        raise typer.Exit(code=1) from exc
    secho("✅ Scheduler service 已解除安裝。", fg=typer.colors.GREEN)


def register(app: typer.Typer) -> None:
    """Register backwards-compatible root aliases."""
    app.command("cron-add", hidden=True)(cron_add)
    app.command("cron-ls", hidden=True)(cron_ls)
    app.command("cron-rm", hidden=True)(cron_rm)
    app.command("cron-toggle", hidden=True)(cron_toggle)
    app.command("cron-start", hidden=True)(cron_start)


def schedule_enable(name: str = typer.Argument(..., help="排程名稱")) -> None:
    cron_toggle(name=name, enable=True)


def schedule_disable(name: str = typer.Argument(..., help="排程名稱")) -> None:
    cron_toggle(name=name, enable=False)


def register_schedule(app: typer.Typer) -> None:
    service_app = typer.Typer(help="管理背景 Scheduler service", no_args_is_help=True)
    service_app.command("install")(service_install)
    service_app.command("start")(service_start)
    service_app.command("status")(service_status)
    service_app.command("stop")(service_stop)
    service_app.command("uninstall")(service_uninstall)

    app.command("add")(cron_add)
    app.command("list")(cron_ls)
    app.command("remove")(cron_rm)
    app.command("enable")(schedule_enable)
    app.command("disable")(schedule_disable)
    app.command("start")(cron_start)
    app.command("_run-service", hidden=True)(_run_service_child)
    app.add_typer(service_app, name="service")
