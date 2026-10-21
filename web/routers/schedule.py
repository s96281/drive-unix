"""Cron schedule management API router (/api/schedule)."""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.config import ConfigManager, CronTask
from web.dependencies import get_config_manager

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


class TaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="任務名稱")
    schedule: str = Field(..., description="Cron 表達式 (例如 0 * * * *)")
    command: str = Field(..., description="執行命令 (例如 drive-unix sync local:/data remote:/backup)")
    enabled: bool = True


class TaskToggleRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[TaskItemResponse])
def list_tasks(
    config_manager: ConfigManager = Depends(get_config_manager),
) -> list[TaskItemResponse]:
    """列出所有已排程之 Cron 任務。"""
    tasks = config_manager.config.tasks
    return [
        TaskItemResponse(
            name=name,
            schedule=t.schedule,
            command=t.command,
            enabled=t.enabled,
            last_run=t.last_run,
            last_attempt_at=t.last_attempt_at,
            last_success_at=t.last_success_at,
            last_exit_code=t.last_exit_code,
        )
        for name, t in tasks.items()
    ]


@router.post("", response_model=TaskItemResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    req: TaskCreateRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> TaskItemResponse:
    """新增 Cron 排程任務。"""
    name = req.name.strip()
    if name in config_manager.config.tasks:
        raise HTTPException(status_code=409, detail=f"任務 '{name}' 已經存在。")

    task = CronTask(
        name=name,
        schedule=req.schedule,
        command=req.command,
        enabled=req.enabled,
    )
    config_manager.add_task(name, task)

    return TaskItemResponse(
        name=name,
        schedule=task.schedule,
        command=task.command,
        enabled=task.enabled,
        last_run=task.last_run,
        last_attempt_at=task.last_attempt_at,
        last_success_at=task.last_success_at,
        last_exit_code=task.last_exit_code,
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
    return TaskItemResponse(
        name=name,
        schedule=task.schedule,
        command=task.command,
        enabled=task.enabled,
        last_run=task.last_run,
        last_attempt_at=task.last_attempt_at,
        last_success_at=task.last_success_at,
        last_exit_code=task.last_exit_code,
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
        return {
            "status": "triggered",
            "name": name,
            "pid": proc.pid,
            "attempted_at": now_str,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"無法啟動命令進程: {exc}") from exc
