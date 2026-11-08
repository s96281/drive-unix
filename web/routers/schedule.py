"""Cron schedule management and daemon control API router (/api/schedule)."""

from __future__ import annotations

import shlex
import subprocess
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from application.scheduler_daemon import SchedulerDaemonManager
from application.scheduling import next_cron_occurrence, validate_cron_expression
from core.config import ConfigManager, CronTask
from web.dependencies import get_config_manager
from web.events import broadcaster

router = APIRouter(prefix="/api/schedule", tags=["Schedule"])


class TaskItemResponse(BaseModel):
    name: str
    schedule: str
    command: str
    enabled: bool
    last_run: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    last_exit_code: int | None
    next_run: str | None = None


class TaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="任務名稱")
    schedule: str = Field(..., description="Cron 表達式 (例如 0 * * * *)")
    command: str = Field(..., description="執行命令 (例如 drive-unix sync local:/data remote:/backup)")
    enabled: bool = True


class TaskUpdateRequest(BaseModel):
    schedule: str | None = Field(None, description="新 Cron 表達式")
    command: str | None = Field(None, description="新執行命令")
    enabled: bool | None = Field(None, description="是否啟用")


class TaskToggleRequest(BaseModel):
    enabled: bool


def _calculate_next_run(schedule: str, enabled: bool) -> str | None:
    if not enabled:
        return None
    try:
        nxt = next_cron_occurrence(schedule, datetime.now())
        return nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None
    except Exception:
        return None


# ---------------------------------------------------------
# Daemon Management Endpoints (Declared BEFORE /{name})
# ---------------------------------------------------------


@router.get("/daemon/status")
def get_daemon_status() -> dict[str, Any]:
    """檢視 Scheduler 背景守護行程運作狀態、PID 與最新日誌。"""
    mgr = SchedulerDaemonManager()
    st = mgr.status()

    log_tail: list[str] = []
    if st.log_path.is_file():
        try:
            lines = st.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = lines[-50:]
        except Exception:
            pass

    return {
        "installed": st.installed,
        "running": st.running,
        "pid": st.pid,
        "backend": st.backend,
        "log_path": str(st.log_path),
        "log_tail": log_tail,
    }


@router.post("/daemon/start")
def start_daemon() -> dict[str, Any]:
    """啟動排程守護行程。"""
    mgr = SchedulerDaemonManager()
    try:
        st = mgr.start()
        broadcaster.publish("system", {"topic": "daemon", "action": "started", "pid": st.pid})
        return {"status": "ok", "running": st.running, "pid": st.pid}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"啟動 Daemon 失敗: {exc}") from exc


@router.post("/daemon/stop")
def stop_daemon() -> dict[str, Any]:
    """停止排程守護行程。"""
    mgr = SchedulerDaemonManager()
    try:
        st = mgr.stop()
        broadcaster.publish("system", {"topic": "daemon", "action": "stopped"})
        return {"status": "ok", "running": st.running, "pid": st.pid}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"停止 Daemon 失敗: {exc}") from exc


@router.post("/daemon/restart")
def restart_daemon() -> dict[str, Any]:
    """重啟排程守護行程。"""
    mgr = SchedulerDaemonManager()
    try:
        mgr.stop()
        st = mgr.start()
        broadcaster.publish("system", {"topic": "daemon", "action": "restarted", "pid": st.pid})
        return {"status": "ok", "running": st.running, "pid": st.pid}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重啟 Daemon 失敗: {exc}") from exc


# ---------------------------------------------------------
# Scheduled Tasks CRUD Endpoints
# ---------------------------------------------------------


@router.get("", response_model=list[TaskItemResponse])
def list_tasks(
    config_manager: ConfigManager = Depends(get_config_manager),
) -> list[TaskItemResponse]:
    """列出所有已排程之 Cron 任務與下次執行時間。"""
    tasks = config_manager.config.tasks
    results: list[TaskItemResponse] = []
    for name, t in tasks.items():
        next_str = _calculate_next_run(t.schedule, t.enabled)
        results.append(
            TaskItemResponse(
                name=name,
                schedule=t.schedule,
                command=t.command,
                enabled=t.enabled,
                last_run=t.last_run,
                last_attempt_at=t.last_attempt_at,
                last_success_at=t.last_success_at,
                last_exit_code=t.last_exit_code,
                next_run=next_str,
            )
        )
    return results


@router.post("", response_model=TaskItemResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    req: TaskCreateRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> TaskItemResponse:
    """新增 Cron 排程任務。"""
    name = req.name.strip()
    if name in config_manager.config.tasks:
        raise HTTPException(status_code=409, detail=f"任務 '{name}' 已經存在。")

    try:
        validate_cron_expression(req.schedule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"無效的 Cron 表達式: {exc}") from exc

    task = CronTask(
        name=name,
        schedule=req.schedule.strip(),
        command=req.command.strip(),
        enabled=req.enabled,
    )
    config_manager.add_task(name, task)
    broadcaster.publish("system", {"topic": "schedule", "action": "created", "name": name})

    return TaskItemResponse(
        name=name,
        schedule=task.schedule,
        command=task.command,
        enabled=task.enabled,
        last_run=task.last_run,
        last_attempt_at=task.last_attempt_at,
        last_success_at=task.last_success_at,
        last_exit_code=task.last_exit_code,
        next_run=_calculate_next_run(task.schedule, task.enabled),
    )


@router.put("/{name}", response_model=TaskItemResponse)
def update_task(
    name: str,
    req: TaskUpdateRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> TaskItemResponse:
    """更新指定之排程任務參數。"""
    if name not in config_manager.config.tasks:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的任務。")

    task = config_manager.config.tasks[name]

    if req.schedule is not None:
        try:
            validate_cron_expression(req.schedule)
            task.schedule = req.schedule.strip()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"無效的 Cron 表達式: {exc}") from exc

    if req.command is not None:
        task.command = req.command.strip()

    if req.enabled is not None:
        task.enabled = req.enabled

    config_manager.save()
    broadcaster.publish("system", {"topic": "schedule", "action": "updated", "name": name})

    return TaskItemResponse(
        name=name,
        schedule=task.schedule,
        command=task.command,
        enabled=task.enabled,
        last_run=task.last_run,
        last_attempt_at=task.last_attempt_at,
        last_success_at=task.last_success_at,
        last_exit_code=task.last_exit_code,
        next_run=_calculate_next_run(task.schedule, task.enabled),
    )


@router.delete("/{name}", status_code=status.HTTP_200_OK)
def delete_task(
    name: str,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """刪除指定排程任務。"""
    if name not in config_manager.config.tasks:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的任務。")

    config_manager.remove_task(name)
    broadcaster.publish("system", {"topic": "schedule", "action": "deleted", "name": name})
    return {"status": "deleted", "name": name}


@router.post("/{name}/toggle", response_model=TaskItemResponse)
def toggle_task(
    name: str,
    req: TaskToggleRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> TaskItemResponse:
    """啟用或停用指定排程任務。"""
    if name not in config_manager.config.tasks:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的任務。")

    config_manager.toggle_task(name, req.enabled)
    task = config_manager.config.tasks[name]
    broadcaster.publish("system", {"topic": "schedule", "action": "toggled", "name": name, "enabled": req.enabled})

    return TaskItemResponse(
        name=name,
        schedule=task.schedule,
        command=task.command,
        enabled=task.enabled,
        last_run=task.last_run,
        last_attempt_at=task.last_attempt_at,
        last_success_at=task.last_success_at,
        last_exit_code=task.last_exit_code,
        next_run=_calculate_next_run(task.schedule, task.enabled),
    )


@router.post("/{name}/run")
def run_task_now(
    name: str,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """手動即刻觸發一次排程命令。"""
    if name not in config_manager.config.tasks:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的任務。")

    task = config_manager.config.tasks[name]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config_manager.update_task_attempt(name, now_str)

    # 非阻塞執行命令
    try:
        args = shlex.split(task.command)
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        broadcaster.publish("system", {"topic": "schedule", "action": "triggered", "name": name, "pid": proc.pid})
        return {
            "status": "triggered",
            "name": name,
            "pid": proc.pid,
            "attempted_at": now_str,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"無法啟動命令進程: {exc}") from exc
