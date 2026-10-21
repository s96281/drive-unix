"""Real-time task and transfer progress event management (SSE/WebSocket bridge)."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass, field
from typing import Any

from storage.base import ProgressCallback


@dataclass
class TaskEvent:
    task_id: str
    event_type: str  # "progress", "completed", "failed", "cancelled", "info"
    transferred: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class TaskEventManager:
    """Manages active task queues and SSE event distribution."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[TaskEvent | None]] = {}
        self._loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._cancel_tokens: dict[str, threading.Event] = {}
        self._task_statuses: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register_task(self, task_id: str) -> threading.Event:
        """Register a new task and return its cancellation token."""
        with self._lock:
            self._queues[task_id] = asyncio.Queue()
            token = threading.Event()
            self._cancel_tokens[task_id] = token
            self._task_statuses[task_id] = {
                "status": "running",
                "percent": 0.0,
                "message": "工作已建立",
            }
            return token

    def get_cancel_token(self, task_id: str) -> threading.Event | None:
        with self._lock:
            return self._cancel_tokens.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """Signal cancellation for a running task."""
        with self._lock:
            token = self._cancel_tokens.get(task_id)
            if token:
                token.set()
                self._task_statuses[task_id] = {
                    "status": "cancelled",
                    "percent": 0.0,
                    "message": "作業已被使用者取消",
                }
        if token:
            self.emit(
                task_id,
                TaskEvent(
                    task_id=task_id,
                    event_type="cancelled",
                    message="作業已被使用者取消",
                ),
            )
            return True
        return False

    def is_cancelled(self, task_id: str) -> bool:
        token = self.get_cancel_token(task_id)
        return token.is_set() if token else False

    def emit(self, task_id: str, event: TaskEvent) -> None:
        """Emit an event safely from worker threads or coroutines."""
        with self._lock:
            queue = self._queues.get(task_id)
            loop = self._loops.get(task_id)
            if task_id in self._task_statuses:
                self._task_statuses[task_id]["percent"] = event.percent
                self._task_statuses[task_id]["message"] = event.message

        if queue:
            if loop and loop.is_running():
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception:
                    pass
            else:
                try:
                    queue.put_nowait(event)
                except Exception:
                    pass

    def emit_progress(
        self,
        task_id: str,
        transferred: int,
        total: int,
        message: str = "",
    ) -> None:
        pct = round((transferred / total) * 100, 2) if total > 0 else 0.0
        self.emit(
            task_id,
            TaskEvent(
                task_id=task_id,
                event_type="progress",
                transferred=transferred,
                total=total,
                percent=pct,
                message=message,
            ),
        )

    def complete(self, task_id: str, message: str = "", data: dict[str, Any] | None = None) -> None:
        """Mark task as successfully completed and signal end of stream."""
        with self._lock:
            self._task_statuses[task_id] = {
                "status": "completed",
                "percent": 100.0,
                "message": message or "作業順利完成",
                "data": data or {},
            }
        self.emit(
            task_id,
            TaskEvent(
                task_id=task_id,
                event_type="completed",
                percent=100.0,
                message=message or "作業順利完成",
                data=data or {},
            ),
        )
        with self._lock:
            queue = self._queues.get(task_id)
            loop = self._loops.get(task_id)
        if queue:
            if loop and loop.is_running():
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                except Exception:
                    pass
            else:
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass

    def fail(self, task_id: str, error: str) -> None:
        """Mark task as failed and signal end of stream."""
        with self._lock:
            self._task_statuses[task_id] = {
                "status": "failed",
                "percent": 0.0,
                "message": error,
            }
        self.emit(
            task_id,
            TaskEvent(
                task_id=task_id,
                event_type="failed",
                message=error,
            ),
        )
        with self._lock:
            queue = self._queues.get(task_id)
            loop = self._loops.get(task_id)
        if queue:
            if loop and loop.is_running():
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                except Exception:
                    pass
            else:
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._task_statuses.get(task_id)

    def create_progress_callback(self, task_id: str) -> ProgressCallback:
        """Create a standard ProgressCallback callable for transfer services."""
        def callback(transferred: int, total: int) -> None:
            self.emit_progress(task_id, transferred, total)

        return callback

    async def subscribe(self, task_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to an SSE event stream for a task."""
        with self._lock:
            queue = self._queues.get(task_id)
            if not queue:
                yield f"event: error\ndata: {json.dumps({'message': 'Task not found'})}\n\n"
                return
            try:
                self._loops[task_id] = asyncio.get_running_loop()
            except RuntimeError:
                pass

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                payload = json.dumps(asdict(event), ensure_ascii=False)
                yield f"event: {event.event_type}\ndata: {payload}\n\n"
        finally:
            with self._lock:
                self._queues.pop(task_id, None)
                self._loops.pop(task_id, None)
                self._cancel_tokens.pop(task_id, None)


# Global event manager instance
task_event_manager = TaskEventManager()
