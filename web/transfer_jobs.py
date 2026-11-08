"""Background execution worker for multi-source cross-remote file transfers."""

from __future__ import annotations

import logging
import posixpath
import threading
import time
from typing import Any, Literal

from application.sync_service import SyncExecutor
from application.transfer_service import TransferService
from core.config import ConfigManager
from domain.sync.models import SyncOptions
from domain.sync.planner import SyncPlanner
from domain.sync.scanner import scan_storage_tree
from storage.base import managed_storage
from web.bandwidth import bandwidth_limiter
from web.cache import directory_cache
from web.dependencies import parse_uri, resolve_storage
from web.events import TaskEvent, broadcaster, task_event_manager

logger = logging.getLogger(__name__)


def run_transfer_job(
    task_id: str,
    sources: list[str],
    dest_dir_uri: str,
    mode: Literal["copy", "move"],
    config_manager: ConfigManager,
) -> None:
    """Worker executing cross-provider transfer (copy or move) for a batch of files/directories."""
    try:
        dst_remote, dst_base_path = parse_uri(dest_dir_uri, config_manager.config.default_remote)
        if dst_remote not in config_manager.config.remotes:
            raise ValueError(f"找不到目的節點 '{dst_remote}'")

        dst_storage = resolve_storage(dst_remote, config_manager, use_pool=False)
        transfer_svc = TransferService()

        total_items = len(sources)
        succeeded = 0
        failed = 0

        task_event_manager.emit(
            task_id,
            TaskEvent(task_id=task_id, event_type="info", message=f"開始傳輸 {total_items} 個項目..."),
        )

        with managed_storage(dst_storage):
            for idx, src_uri in enumerate(sources, start=1):
                task_event_manager.wait_if_paused(task_id)
                if task_event_manager.is_cancelled(task_id):
                    raise RuntimeError("使用者手動取消傳輸作業。")

                src_remote, src_path = parse_uri(src_uri, config_manager.config.default_remote)
                if src_remote not in config_manager.config.remotes:
                    logger.error("找不到來源節點 '%s'", src_remote)
                    failed += 1
                    continue

                src_storage = resolve_storage(src_remote, config_manager, use_pool=False)
                item_name = posixpath.basename(src_path.rstrip("/"))
                target_dest_path = posixpath.join(dst_base_path.rstrip("/"), item_name).replace("//", "/")

                task_event_manager.emit_progress(
                    task_id,
                    transferred=idx - 1,
                    total=total_items,
                    message=f"[{idx}/{total_items}] 處理: {src_uri} -> {dst_remote}:{target_dest_path}",
                    files_done=idx - 1,
                    files_total=total_items,
                )

                try:
                    with managed_storage(src_storage):
                        stat_info = src_storage.stat(src_path)
                        is_folder = stat_info.get("type") == "folder"

                        if not is_folder:
                            # Transfer single file
                            def on_progress(transferred: int, total: int) -> None:
                                task_event_manager.wait_if_paused(task_id)
                                bandwidth_limiter.consume(transferred)

                            transfer_svc.copy_between(
                                source_remote=src_remote,
                                source_storage=src_storage,
                                source_path=src_path,
                                destination_remote=dst_remote,
                                destination_storage=dst_storage,
                                destination_path=target_dest_path,
                                upload_callback=on_progress,
                            )

                            if mode == "move":
                                src_storage.delete(src_path, permanent=False)
                        else:
                            # Recursive folder transfer via SyncPlanner + SyncExecutor
                            src_snap = scan_storage_tree(src_storage, src_path)
                            dst_snap = scan_storage_tree(dst_storage, target_dest_path)
                            options = SyncOptions(one_way=True, delete=False, conflict="auto")

                            planner = SyncPlanner()
                            plan = planner.build_plan(
                                source_items=src_snap.items,
                                destination_items=dst_snap.items,
                                source_base_path=src_snap.base_path,
                                destination_base_path=dst_snap.base_path,
                                source_type=config_manager.config.remotes[src_remote].type,
                                destination_type=config_manager.config.remotes[dst_remote].type,
                                options=options,
                            )
                            executor = SyncExecutor()
                            res = executor.execute(
                                plan,
                                source_remote=src_remote,
                                source_storage=src_storage,
                                destination_remote=dst_remote,
                                destination_storage=dst_storage,
                                workers=4,
                            )
                            if not res.success:
                                raise RuntimeError(f"目錄同步遇到錯誤: {res.failed} 個失敗項目")

                            if mode == "move":
                                src_storage.delete(src_path, permanent=False)

                        directory_cache.invalidate(src_remote, src_path)
                        directory_cache.invalidate(dst_remote, target_dest_path)
                        succeeded += 1

                except Exception as exc:
                    logger.error("傳輸 %s 失敗: %s", src_uri, exc)
                    failed += 1
                    broadcaster.publish("task.log", {
                        "task_id": task_id,
                        "level": "ERROR",
                        "message": f"傳輸失敗 {src_uri}: {exc}",
                        "ts": time.time(),
                    })

        if failed == 0:
            task_event_manager.complete(
                task_id,
                message=f"傳輸作業完成！成功傳輸 {succeeded} 個項目。",
                data={"succeeded": succeeded, "failed": failed},
            )
        else:
            task_event_manager.fail(
                task_id,
                f"傳輸作業結束：成功 {succeeded} 個，失敗 {failed} 個。",
            )

    except Exception as exc:
        task_event_manager.fail(task_id, f"傳輸作業中斷失敗: {exc}")
