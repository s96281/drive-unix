"""Synchronization planning and execution API router (/api/sync)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.sync_service import SyncActionToken, SyncExecutor, SyncHooks
from core.config import ConfigManager
from domain.sync.models import ConflictStrategy, SyncAction, SyncActionType, SyncOptions, SyncPlan
from domain.sync.planner import SyncPlanner
from domain.sync.scanner import scan_storage_tree
from storage.base import managed_storage
from web.bandwidth import bandwidth_limiter
from web.cache import directory_cache
from web.dependencies import get_config_manager, parse_uri, resolve_storage
from web.events import TaskEvent, broadcaster, task_event_manager
from web.settings import web_settings_manager

router = APIRouter(prefix="/api/sync", tags=["Sync"])


class PlanRequest(BaseModel):
    source_uri: str | None = Field(None, description="來源遠端路徑 (例如 local:/data)")
    dest_uri: str | None = Field(None, description="目的遠端路徑 (例如 backup:/data)")
    source: str | None = Field(None, description="來源遠端路徑別名 (例如 local:/data)")
    destination: str | None = Field(None, description="目的遠端路徑別名 (例如 backup:/data)")
    two_way: bool = Field(False, description="是否為雙向同步")
    mode: str | None = Field(None, description="同步模式: copy, sync, mirror, two_way")
    conflict: str = Field("auto", description="衝突解決策略 (auto, newer, rename, abort, prefer-source, prefer-destination)")
    conflict_resolution: str | None = Field(None, description="衝突解決策略別名")
    delete: bool = Field(False, description="是否鏡像刪除目的端多餘項目")
    delete_extra: bool | None = Field(None, description="是否刪除目的端多餘項目別名")
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
    source: str | None = None
    destination: str | None = None
    mode: str | None = None
    to_add: int = 0
    to_update: int = 0
    to_delete: int = 0
    bytes_to_transfer: int = 0
    items: list[dict[str, Any]] = []
    total_actions: int
    has_destructive: bool
    permanent_delete_count: int
    trash_delete_count: int
    actions: list[SyncActionDto]
    batches: list[dict[str, Any]]
    capabilities: dict[str, str]


class SyncExecuteRequest(PlanRequest):
    workers: int | None = Field(None, ge=1, le=16, description="並行傳輸工作緒數量 (留空使用系統預設)")


class WebSyncHooks(SyncHooks):
    """Bridge sync execution hooks to the TaskEventManager SSE stream with pause and rate limiting."""

    def __init__(self, task_id: str, total_actions: int, total_bytes: int = 0) -> None:
        self.task_id = task_id
        self.total_actions = total_actions
        self.total_bytes = total_bytes
        self.finished_actions = 0
        self.bytes_done = 0
        self._token_transferred: dict[int, int] = {}
        self._lock = threading.Lock()
        self._last_speed_time = time.time()
        self._last_speed_bytes = 0
        self._speed_bps = 0.0

    def action_started(self, action: SyncAction) -> SyncActionToken | None:
        # Check pause gate before starting next action
        task_event_manager.wait_if_paused(self.task_id)

        if task_event_manager.is_cancelled(self.task_id):
            raise RuntimeError("使用者已手動取消同步作業。")

        broadcaster.publish("task.log", {
            "task_id": self.task_id,
            "level": "INFO",
            "action": action.action_type.value,
            "target": action.target_path,
            "message": f"執行 {action.action_type.value}: {action.target_path}",
            "ts": time.time(),
        })

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
        task_event_manager.wait_if_paused(self.task_id)

        if task_event_manager.is_cancelled(self.task_id):
            raise RuntimeError("使用者已手動取消同步作業。")

        token_id = token.action_id if token else 0
        delta = 0
        with self._lock:
            prev = self._token_transferred.get(token_id, 0)
            if transferred > prev:
                delta = transferred - prev
                self._token_transferred[token_id] = transferred
                self.bytes_done += delta

            now = time.time()
            elapsed = now - self._last_speed_time
            if elapsed >= 0.5:
                window_bytes = self.bytes_done - self._last_speed_bytes
                current_speed = window_bytes / elapsed if elapsed > 0 else 0.0
                self._speed_bps = (
                    0.7 * self._speed_bps + 0.3 * current_speed
                    if self._speed_bps > 0
                    else current_speed
                )
                self._last_speed_time = now
                self._last_speed_bytes = self.bytes_done

        if delta > 0:
            bandwidth_limiter.consume(delta)

        remaining_bytes = max(0, self.total_bytes - self.bytes_done)
        eta = (remaining_bytes / self._speed_bps) if self._speed_bps > 0 else None

        task_event_manager.emit_progress(
            self.task_id,
            transferred=self.bytes_done if self.total_bytes > 0 else transferred,
            total=self.total_bytes if self.total_bytes > 0 else total,
            message=f"{stage} 傳輸中: {self.bytes_done}/{self.total_bytes} 位元組",
            speed_bps=round(self._speed_bps, 1),
            eta_seconds=round(eta, 1) if eta is not None else None,
            files_done=self.finished_actions,
            files_total=self.total_actions,
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
            broadcaster.publish("task.log", {
                "task_id": self.task_id,
                "level": "ERROR",
                "target": action.target_path,
                "error": str(error),
                "message": f"{action.target_path} 執行失敗: {error}",
                "ts": time.time(),
            })
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
            broadcaster.publish("task.log", {
                "task_id": self.task_id,
                "level": "INFO",
                "target": action.target_path,
                "message": f"完成: {action.target_path}",
                "ts": time.time(),
            })
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
    src_raw = req.source_uri or req.source
    dst_raw = req.dest_uri or req.destination
    if not src_raw or not src_raw.strip():
        raise HTTPException(status_code=400, detail="缺少來源遠端路徑 (source_uri 或 source)")
    if not dst_raw or not dst_raw.strip():
        raise HTTPException(status_code=400, detail="缺少目的遠端路徑 (dest_uri 或 destination)")

    src_remote, src_path = parse_uri(src_raw.strip(), config_manager.config.default_remote)
    dst_remote, dst_path = parse_uri(dst_raw.strip(), config_manager.config.default_remote)

    if src_remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到來源節點 '{src_remote}'")
    if dst_remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到目的節點 '{dst_remote}'")

    src_storage = resolve_storage(src_remote, config_manager, use_pool=False)
    dst_storage = resolve_storage(dst_remote, config_manager, use_pool=False)

    is_two_way = req.two_way or (req.mode == "two_way")
    is_delete = req.delete or (req.delete_extra is True) or (req.mode == "mirror")
    conflict_val = req.conflict_resolution or req.conflict

    options = SyncOptions(
        one_way=not is_two_way,
        delete=is_delete,
        conflict=conflict_val,  # type: ignore[arg-type]
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

    to_add = 0
    to_update = 0
    to_delete = 0
    bytes_to_transfer = 0
    items_dto: list[dict[str, Any]] = []

    actions_dto: list[SyncActionDto] = []
    for action in plan.actions:
        action_type_str = action.action_type.value
        act_size = action.item.size if action.item else 0
        act_is_dir = action.item.is_dir if action.item else False

        actions_dto.append(
            SyncActionDto(
                type=action_type_str,
                target=action.target_path,
                reason=action.reason,
                bytes=act_size,
                is_dir=act_is_dir,
            )
        )

        item_action = "identical"
        if "DELETE" in action_type_str:
            item_action = "delete"
            to_delete += 1
        elif "COPY" in action_type_str or "CREATE" in action_type_str:
            item_action = "add"
            to_add += 1
            if not act_is_dir:
                bytes_to_transfer += act_size
        elif "UPDATE" in action_type_str or "OVERWRITE" in action_type_str:
            item_action = "update"
            to_update += 1
            if not act_is_dir:
                bytes_to_transfer += act_size

        items_dto.append({
            "action": item_action,
            "path": action.target_path,
            "size": act_size,
            "reason": action.reason,
        })

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

    src_uri = req.source_uri or req.source or ""
    dst_uri = req.dest_uri or req.destination or ""
    is_two_way = req.two_way or (req.mode == "two_way")
    is_delete = req.delete or (req.delete_extra is True) or (req.mode == "mirror")

    return SyncPlanResponse(
        source_uri=src_uri,
        dest_uri=dst_uri,
        source=src_uri,
        destination=dst_uri,
        mode=req.mode or ("mirror" if is_delete else ("two_way" if is_two_way else "sync")),
        to_add=to_add,
        to_update=to_update,
        to_delete=to_delete,
        bytes_to_transfer=bytes_to_transfer,
        items=items_dto,
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

        total_bytes = sum(a.item.size for a in plan.actions if a.item and not a.item.is_dir)
        hooks = WebSyncHooks(task_id=task_id, total_actions=plan.count, total_bytes=total_bytes)
        executor = SyncExecutor()

        effective_workers = req.workers or web_settings_manager.settings.transfer.max_workers

        with managed_storage(src_storage), managed_storage(dst_storage):
            result = executor.execute(
                plan,
                source_remote=src_remote,
                source_storage=src_storage,
                destination_remote=dst_remote,
                destination_storage=dst_storage,
                workers=effective_workers,
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


@router.get("/tasks")
def list_sync_tasks(
    limit: int = Query(50, ge=1, le=200, description="最大回傳任務數量"),
) -> list[dict[str, Any]]:
    """取得所有進行中與歷史任務清單。"""
    records = task_event_manager.list_records(limit=limit)
    return [r.to_dict() for r in records]


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
def execute_sync(
    req: SyncExecuteRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """啟動非同步同步工作，回傳 task_id 可供 SSE 訂閱。"""
    src_uri = req.source_uri or req.source or ""
    dst_uri = req.dest_uri or req.destination or ""
    req.source_uri = src_uri
    req.dest_uri = dst_uri

    task_id = str(uuid.uuid4())
    task_event_manager.register_task(
        task_id,
        kind="sync",
        title=f"同步: {src_uri} -> {dst_uri}",
        source_uri=src_uri,
        dest_uri=dst_uri,
        request_payload=req.model_dump(),
    )

    # 啟動背景執行緒
    worker_thread = threading.Thread(
        target=_run_sync_worker,
        args=(task_id, req, config_manager),
        daemon=True,
    )
    worker_thread.start()

    return {"status": "started", "task_id": task_id}


@router.post("/tasks/{task_id}/pause")
def pause_sync_task(task_id: str) -> dict[str, Any]:
    """暫停指定之同步工作（於當前動作結束後生效）。"""
    ok = task_event_manager.pause(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="無法暫停該工作（工作不存在或已結束）。")
    return {"status": "paused", "task_id": task_id}


@router.post("/tasks/{task_id}/resume")
def resume_sync_task(task_id: str) -> dict[str, Any]:
    """恢復已暫停之同步工作。"""
    ok = task_event_manager.resume(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="無法恢復該工作（工作不存在或非處於暫停狀態）。")
    return {"status": "resumed", "task_id": task_id}


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_sync_task(
    task_id: str,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """重新發起先前已結束或失敗的同步任務。"""
    old_record = task_event_manager.get_record(task_id)
    if not old_record or not old_record.request_payload:
        raise HTTPException(status_code=404, detail="找不到指定之任務或缺少原始請求參數。")

    try:
        new_req = SyncExecuteRequest(**old_record.request_payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析原始任務參數失敗: {exc}") from exc

    return execute_sync(new_req, config_manager=config_manager)


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
