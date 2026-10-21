"""Synchronization planning and execution API router (/api/sync)."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.sync_service import SyncActionToken, SyncExecutor, SyncHooks
from core.config import ConfigManager
from domain.sync.models import ConflictStrategy, SyncAction, SyncActionType, SyncOptions, SyncPlan
from domain.sync.planner import SyncPlanner
from domain.sync.scanner import scan_storage_tree
from storage.base import managed_storage
from web.cache import directory_cache
from web.dependencies import get_config_manager, parse_uri, resolve_storage
from web.events import TaskEvent, task_event_manager

router = APIRouter(prefix="/api/sync", tags=["Sync"])


class PlanRequest(BaseModel):
    source_uri: str = Field(..., description="來源遠端路徑 (例如 local:/data)")
    dest_uri: str = Field(..., description="目的遠端路徑 (例如 backup:/data)")
    two_way: bool = Field(False, description="是否為雙向同步")
    conflict: str = Field("auto", description="衝突解決策略 (auto, newer, rename, abort, prefer-source, prefer-destination)")
    delete: bool = Field(False, description="是否鏡像刪除目的端多餘項目")
    checksum: bool = Field(False, description="是否啟用校驗碼對比")


class SyncActionDto(BaseModel):
    type: str
    target: str
    reason: str
    bytes: int
    is_dir: bool


class SyncPlanResponse(BaseModel):
    source_uri: str
    dest_uri: str
    total_actions: int
    has_destructive: bool
    permanent_delete_count: int
    trash_delete_count: int
    actions: list[SyncActionDto]
    batches: list[dict[str, Any]]
    capabilities: dict[str, str]


class SyncExecuteRequest(PlanRequest):
    workers: int = Field(4, ge=1, le=16, description="並行傳輸工作緒數量")


class WebSyncHooks(SyncHooks):
    """Bridge sync execution hooks to the TaskEventManager SSE stream."""

    def __init__(self, task_id: str, total_actions: int) -> None:
        self.task_id = task_id
        self.total_actions = total_actions
        self.finished_actions = 0

    def action_started(self, action: SyncAction) -> SyncActionToken | None:
        if task_event_manager.is_cancelled(self.task_id):
            raise RuntimeError("使用者已手動取消同步作業。")

        task_event_manager.emit(
            self.task_id,
            TaskEvent(
                task_id=self.task_id,
                event_type="action_start",
                message=f"執行 {action.action_type.value}: {action.target_path}",
                data={"target": action.target_path, "type": action.action_type.value},
            ),
        )
        return SyncActionToken(action_id=id(action))

    def progress(
        self,
        token: SyncActionToken | None,
        stage: str,
        transferred: int,
        total: int,
    ) -> None:
        if task_event_manager.is_cancelled(self.task_id):
            raise RuntimeError("使用者已手動取消同步作業。")

        task_event_manager.emit_progress(
            self.task_id,
            transferred=transferred,
            total=total,
            message=f"{stage} 傳輸中: {transferred}/{total} 位元組",
        )

    def action_finished(
        self,
        action: SyncAction,
        token: SyncActionToken | None,
        error: Exception | None,
    ) -> None:
        self.finished_actions += 1
        pct = (
            round((self.finished_actions / self.total_actions) * 100, 1)
            if self.total_actions > 0
            else 100.0
        )
        if error:
            task_event_manager.emit(
                self.task_id,
                TaskEvent(
                    task_id=self.task_id,
                    event_type="action_error",
                    percent=pct,
                    message=f"{action.target_path} 執行失敗: {error}",
                    data={"target": action.target_path, "error": str(error)},
                ),
            )
        else:
            task_event_manager.emit(
                self.task_id,
                TaskEvent(
                    task_id=self.task_id,
                    event_type="action_done",
                    percent=pct,
                    message=f"完成: {action.target_path}",
                    data={"target": action.target_path},
                ),
            )

    def message(self, message: str) -> None:
        task_event_manager.emit(
            self.task_id,
            TaskEvent(task_id=self.task_id, event_type="info", message=message),
        )


def _build_plan_internal(
    req: PlanRequest,
    config_manager: ConfigManager,
) -> tuple[SyncPlan, Any, Any, str, str, str, str]:
    src_remote, src_path = parse_uri(req.source_uri, config_manager.config.default_remote)
    dst_remote, dst_path = parse_uri(req.dest_uri, config_manager.config.default_remote)

    if src_remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到來源節點 '{src_remote}'")
    if dst_remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到目的節點 '{dst_remote}'")

    src_storage = resolve_storage(src_remote, config_manager)
    dst_storage = resolve_storage(dst_remote, config_manager)

    options = SyncOptions(
        one_way=not req.two_way,
        delete=req.delete,
        conflict=req.conflict,  # type: ignore[arg-type]
        checksum=req.checksum,
    )
    try:
        options.validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with managed_storage(src_storage), managed_storage(dst_storage):
        src_snapshot = scan_storage_tree(src_storage, src_path)
        dst_snapshot = scan_storage_tree(dst_storage, dst_path)

        src_type = config_manager.config.remotes[src_remote].type
        dst_type = config_manager.config.remotes[dst_remote].type

        planner = SyncPlanner()
        plan = planner.build_plan(
            source_items=src_snapshot.items,
            destination_items=dst_snapshot.items,
            source_base_path=src_snapshot.base_path,
            destination_base_path=dst_snapshot.base_path,
            source_type=src_type,
            destination_type=dst_type,
            options=options,
        )

    return plan, src_storage, dst_storage, src_remote, dst_remote, src_path, dst_path


@router.post("/plan", response_model=SyncPlanResponse)
def create_sync_plan(
    req: PlanRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> SyncPlanResponse:
    """產生同步預檢計畫（不修改實際儲存空間）。"""
    plan, src_storage, dst_storage, _, _, _, _ = _build_plan_internal(req, config_manager)

    permanent_deletes = 0
    trash_deletes = 0

    dest_perm_only = dst_storage.delete_capability.value == "permanent_only"
    src_perm_only = src_storage.delete_capability.value == "permanent_only"

    actions_dto: list[SyncActionDto] = []
    for action in plan.actions:
        actions_dto.append(
            SyncActionDto(
                type=action.action_type.value,
                target=action.target_path,
                reason=action.reason,
                bytes=action.item.size if action.item else 0,
                is_dir=action.item.is_dir if action.item else False,
            )
        )
        if action.action_type == SyncActionType.DELETE_DEST:
            if dest_perm_only:
                permanent_deletes += 1
            else:
                trash_deletes += 1
        elif action.action_type == SyncActionType.DELETE_SRC:
            if src_perm_only:
                permanent_deletes += 1
            else:
                trash_deletes += 1

    batches_info = [{"name": b.name, "count": b.count} for b in plan.batches]

    return SyncPlanResponse(
        source_uri=req.source_uri,
        dest_uri=req.dest_uri,
        total_actions=plan.count,
        has_destructive=(permanent_deletes > 0 or trash_deletes > 0),
        permanent_delete_count=permanent_deletes,
        trash_delete_count=trash_deletes,
        actions=actions_dto,
        batches=batches_info,
        capabilities={
            "source_deletion": src_storage.delete_capability.value,
            "dest_deletion": dst_storage.delete_capability.value,
        },
    )


def _run_sync_worker(
    task_id: str,
    req: SyncExecuteRequest,
    config_manager: ConfigManager,
) -> None:
    """Background worker executing the sync plan."""
    try:
        task_event_manager.emit(
            task_id,
            TaskEvent(task_id=task_id, event_type="info", message="開始掃描儲存目錄樹..."),
        )
        plan, src_storage, dst_storage, src_remote, dst_remote, _, _ = _build_plan_internal(
            req, config_manager
        )

        task_event_manager.emit(
            task_id,
            TaskEvent(
                task_id=task_id,
                event_type="info",
                message=f"目錄掃描完成，共有 {plan.count} 項同步動作待執行。",
            ),
        )

        if plan.count == 0:
            task_event_manager.complete(task_id, message="兩端內容完全一致，無需同步變更。")
            return

        hooks = WebSyncHooks(task_id=task_id, total_actions=plan.count)
        executor = SyncExecutor()

        with managed_storage(src_storage), managed_storage(dst_storage):
            result = executor.execute(
                plan,
                source_remote=src_remote,
                source_storage=src_storage,
                destination_remote=dst_remote,
                destination_storage=dst_storage,
                workers=req.workers,
                hooks=hooks,
            )

        directory_cache.invalidate(src_remote)
        directory_cache.invalidate(dst_remote)

        if result.success:
            task_event_manager.complete(
                task_id,
                message=f"同步順利完成！成功執行 {result.succeeded} 項操作。",
                data={"succeeded": result.succeeded, "failed": result.failed, "skipped": result.skipped},
            )
        else:
            task_event_manager.fail(
                task_id,
                f"同步結束但有錯誤: 成功 {result.succeeded} 項，失敗 {result.failed} 項，略過 {result.skipped} 項。",
            )
    except Exception as exc:
        task_event_manager.fail(task_id, f"同步作業中斷失敗: {exc}")


@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
def execute_sync(
    req: SyncExecuteRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """啟動非同步同步工作，回傳 task_id 可供 SSE 訂閱。"""
    task_id = str(uuid.uuid4())
    task_event_manager.register_task(task_id)

    # 啟動背景執行緒
    worker_thread = threading.Thread(
        target=_run_sync_worker,
        args=(task_id, req, config_manager),
        daemon=True,
    )
    worker_thread.start()

    return {"status": "started", "task_id": task_id}


@router.post("/tasks/{task_id}/cancel")
def cancel_sync_task(task_id: str) -> dict[str, Any]:
    """發送中斷訊號取消同步工作。"""
    cancelled = task_event_manager.cancel(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="找不到指定之工作或該工作已結束。")
    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks/{task_id}/events")
def stream_sync_events(task_id: str) -> StreamingResponse:
    """SSE 端點：即時串流同步進度與結果。"""
    return StreamingResponse(
        task_event_manager.subscribe(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tasks/{task_id}/status")
def get_sync_task_status(task_id: str) -> dict[str, Any]:
    """查詢同步工作當前狀態與進度。"""
    status_info = task_event_manager.get_status(task_id)
    if not status_info:
        raise HTTPException(status_code=404, detail="找不到指定之工作或該工作資訊已過期。")
    return {"task_id": task_id, **status_info}
