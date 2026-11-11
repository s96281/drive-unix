"""Web upgrade management API router (/api/upgrade)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.upgrade import (
    UpgradeStatus,
    check_for_updates,
    restart_service,
    upgrade_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upgrade", tags=["Upgrade"])


class UpgradeExecuteRequest(BaseModel):
    target_version: str | None = Field(default=None, description="指定升級的目標版本 (例如 0.2.0)")
    channel: str = Field(default="stable", description="升級頻道 ('stable' 或 'main')")
    backup_config: bool = Field(default=True, description="升級前是否備份系統設定")
    force: bool = Field(default=False, description="是否強制重新安裝")
    restart_after: bool = Field(default=False, description="升級完成後是否自動重新載入服務")


@router.get("/status", response_model=dict[str, Any])
def get_upgrade_status(force: bool = Query(False, description="是否強制重新查詢遠端")) -> dict[str, Any]:
    """取得目前版本、最新版本、更新日誌與升級狀態。"""
    status_obj = check_for_updates(force=force)
    data = status_obj.to_dict()
    data["logs"] = upgrade_manager.logs[-50:]
    data["current_step"] = upgrade_manager.current_step
    data["percent"] = upgrade_manager.percent
    return data


@router.post("/check", response_model=dict[str, Any])
def force_check_updates() -> dict[str, Any]:
    """強制向 GitHub 查詢最新版本資訊。"""
    status_obj = check_for_updates(force=True)
    return status_obj.to_dict()


@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
def execute_upgrade(req: UpgradeExecuteRequest) -> dict[str, Any]:
    """在背景非同步啟動軟體升級程序。"""
    if upgrade_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已有正在執行中的升級任務，請稍候再試。",
        )

    def _worker():
        try:
            upgrade_manager.run_upgrade(
                target_version=req.target_version,
                channel=req.channel,
                backup_config=req.backup_config,
                force=req.force,
                dry_run=False,
                restart_after=req.restart_after,
            )
        except Exception as exc:
            logger.exception("Upgrade task failed: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {
        "status": "started",
        "message": "升級程序已在背景啟動",
        "target_version": req.target_version,
        "channel": req.channel,
    }


@router.get("/stream")
async def stream_upgrade_events() -> StreamingResponse:
    """即時串流 (SSE) 升級日誌與進度更新。"""
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # Pre-send existing logs if any
    for log_line in upgrade_manager.logs:
        payload = json.dumps({"text": log_line}, ensure_ascii=False)
        await queue.put(f"event: log\ndata: {payload}\n\n")

    if upgrade_manager.current_step:
        step_payload = json.dumps(
            {"step": upgrade_manager.current_step, "percent": upgrade_manager.percent},
            ensure_ascii=False,
        )
        await queue.put(f"event: step\ndata: {step_payload}\n\n")

    def _callback(event_type: str, data: dict[str, Any]):
        msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    unsub = upgrade_manager.subscribe(_callback)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                # Keep alive heartbeat or message
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            unsub()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/restart", status_code=status.HTTP_200_OK)
def trigger_restart() -> dict[str, Any]:
    """發送信號重新載入背景服務。"""
    reloaded = restart_service()
    return {
        "status": "restarting" if reloaded else "failed",
        "message": "已成功發送重新載入訊號，服務將於數秒後重啟。" if reloaded else "無法自動重啟服務，請手動重啟。",
    }
