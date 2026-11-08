"""Real-time task and transfer progress event management (SSE/WebSocket bridge)."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass, field
import json
import threading
import time
from typing import Any, Literal

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


@dataclass
class TaskRecord:
    id: str
    kind: Literal["sync", "transfer", "renew"] = "sync"
    title: str = ""
    source_uri: str | None = None
    dest_uri: str | None = None
    status: Literal["running", "pausing", "paused", "completed", "failed", "cancelled"] = "running"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    bytes_done: int = 0
    bytes_total: int = 0
    files_done: int = 0
    files_total: int = 0
    errors: int = 0
    speed_bps: float = 0.0  # EMA throughput in bytes/sec
    eta_seconds: float | None = None
    message: str = ""
    request_payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBroadcaster:
    """Thread-safe fan-out broadcaster to global SSE subscribers with sequence ID replay."""

    def __init__(self, max_history: int = 500) -> None:
        self._lock = threading.Lock()
        self._seq: int = 0
        self._history: deque[tuple[int, str, str]] = deque(maxlen=max_history)
        self._subscribers: set[tuple[asyncio.Queue[str | None], asyncio.AbstractEventLoop]] = set()

    def publish(self, event: str, data: dict[str, Any] | Any) -> int:
        """Publish an event to all active SSE subscribers."""
        if isinstance(data, dict):
            payload_str = json.dumps(data, ensure_ascii=False)
        else:
            payload_str = str(data)

        with self._lock:
            self._seq += 1
            seq_id = self._seq
            self._history.append((seq_id, event, payload_str))
            subscribers_snapshot = list(self._subscribers)

        formatted_msg = f"id: {seq_id}\nevent: {event}\ndata: {payload_str}\n\n"

        for queue, loop in subscribers_snapshot:
            if loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._push_queue, queue, formatted_msg)
                except Exception:
                    pass
            else:
                self._push_queue(queue, formatted_msg)

        return seq_id

    @staticmethod
    def _push_queue(queue: asyncio.Queue[str | None], msg: str) -> None:
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Drop earliest or force resync message
            pass

    async def stream(self, last_event_id: int | None = None) -> AsyncGenerator[str, None]:
        """Async generator yielding SSE messages with replay and heartbeats."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1000)
        sub_key = (queue, loop)

        with self._lock:
            self._subscribers.add(sub_key)
            current_seq = self._seq
            history_snapshot = list(self._history)

        # 1. Send hello event
        yield (
            f"id: {current_seq}\nevent: hello\n"
            f'data: {json.dumps({"server_time": time.time(), "replayed": bool(last_event_id)})}\n\n'
        )

        # 2. Replay if requested
        if last_event_id is not None and last_event_id < current_seq:
            if history_snapshot and last_event_id < history_snapshot[0][0] - 1:
                # Subscriber is too far behind the ring buffer
                yield "event: resync\ndata: {}\n\n"
            else:
                for seq_id, ev_name, ev_payload in history_snapshot:
                    if seq_id > last_event_id:
                        yield f"id: {seq_id}\nevent: ev_name\ndata: {ev_payload}\n\n"

        # 3. Main event loop with heartbeat
        heartbeat_interval = 15.0
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    if msg is None:
                        break
                    yield msg
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': time.time()})}\n\n"
        finally:
            with self._lock:
                self._subscribers.discard(sub_key)


broadcaster = EventBroadcaster()


class TaskEventManager:
    """Manages active task queues, pause barriers, records, and SSE event distribution."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[TaskEvent | None]] = {}
        self._loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._cancel_tokens: dict[str, threading.Event] = {}
        self._pause_gates: dict[str, threading.Event] = {}  # Set = unpaused, Cleared = paused
        self._task_statuses: dict[str, dict[str, Any]] = {}
        self._task_records: dict[str, TaskRecord] = {}
        self._last_broadcast_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def register_task(
        self,
        task_id: str,
        *,
        kind: Literal["sync", "transfer", "renew"] = "sync",
        title: str = "",
        source_uri: str | None = None,
        dest_uri: str | None = None,
        request_payload: dict[str, Any] | None = None,
    ) -> threading.Event:
        """Register a new task and return its cancellation token."""
        with self._lock:
            self._queues[task_id] = asyncio.Queue()
            token = threading.Event()
            self._cancel_tokens[task_id] = token

            gate = threading.Event()
            gate.set()  # Initial state: unpaused
            self._pause_gates[task_id] = gate

            record = TaskRecord(
                id=task_id,
                kind=kind,
                title=title or f"{kind} 工作 ({task_id[:8]})",
                source_uri=source_uri,
                dest_uri=dest_uri,
                status="running",
                created_at=time.time(),
                message="工作已建立",
                request_payload=request_payload,
            )
            self._task_records[task_id] = record
            self._task_statuses[task_id] = {
                "status": "running",
                "percent": 0.0,
                "message": record.message,
            }

        broadcaster.publish("task.update", record.to_dict())
        return token

    def get_cancel_token(self, task_id: str) -> threading.Event | None:
        with self._lock:
            return self._cancel_tokens.get(task_id)

    def is_cancelled(self, task_id: str) -> bool:
        token = self.get_cancel_token(task_id)
        return token.is_set() if token else False

    def cancel(self, task_id: str) -> bool:
        """Signal cancellation for a running task and unblock any pause gate."""
        with self._lock:
            token = self._cancel_tokens.get(task_id)
            gate = self._pause_gates.get(task_id)
            if gate:
                gate.set()  # Unblock so cancelled thread can terminate

            if token:
                token.set()
                self._task_statuses[task_id] = {
                    "status": "cancelled",
                    "percent": 0.0,
                    "message": "作業已被使用者取消",
                }
                record = self._task_records.get(task_id)
                if record:
                    record.status = "cancelled"
                    record.finished_at = time.time()
                    record.message = "作業已被使用者取消"
                    broadcaster.publish("task.update", record.to_dict())

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

    def pause(self, task_id: str) -> bool:
        """Signal task to pause at the next available action/chunk boundary."""
        with self._lock:
            record = self._task_records.get(task_id)
            gate = self._pause_gates.get(task_id)
            if not record or not gate:
                return False
            if record.status in ("completed", "failed", "cancelled"):
                return False

            gate.clear()  # Block callers of wait_if_paused
            record.status = "paused"
            record.message = "作業已暫停"
            self._task_statuses[task_id]["status"] = "paused"
            self._task_statuses[task_id]["message"] = "作業已暫停"

        broadcaster.publish("task.update", record.to_dict())
        return True

    def resume(self, task_id: str) -> bool:
        """Resume a paused task."""
        with self._lock:
            record = self._task_records.get(task_id)
            gate = self._pause_gates.get(task_id)
            if not record or not gate:
                return False
            if record.status != "paused":
                return False

            gate.set()  # Unblock callers
            record.status = "running"
            record.message = "作業已繼續執行"
            self._task_statuses[task_id]["status"] = "running"
            self._task_statuses[task_id]["message"] = "作業已繼續執行"

        broadcaster.publish("task.update", record.to_dict())
        return True

    def wait_if_paused(self, task_id: str, timeout: float | None = None) -> bool:
        """Called by worker threads. Blocks if the task is paused until resumed or cancelled."""
        gate = None
        with self._lock:
            gate = self._pause_gates.get(task_id)

        if gate is not None:
            return gate.wait(timeout=timeout)
        return True

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
        speed_bps: float = 0.0,
        eta_seconds: float | None = None,
        files_done: int = 0,
        files_total: int = 0,
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
                data={
                    "speed_bps": speed_bps,
                    "eta_seconds": eta_seconds,
                    "files_done": files_done,
                    "files_total": files_total,
                },
            ),
        )

        # Throttle task.update broadcast to >= 250ms
        now = time.time()
        should_broadcast = False
        with self._lock:
            last_t = self._last_broadcast_time.get(task_id, 0.0)
            record = self._task_records.get(task_id)
            if record:
                record.bytes_done = transferred
                record.bytes_total = total
                record.speed_bps = speed_bps
                record.eta_seconds = eta_seconds
                record.files_done = files_done
                record.files_total = files_total
                if message:
                    record.message = message
                if now - last_t >= 0.25:
                    self._last_broadcast_time[task_id] = now
                    should_broadcast = True
                    rec_dict = record.to_dict()

        if should_broadcast:
            broadcaster.publish("task.update", rec_dict)

    def complete(self, task_id: str, message: str = "", data: dict[str, Any] | None = None) -> None:
        """Mark task as successfully completed and signal end of stream."""
        with self._lock:
            self._task_statuses[task_id] = {
                "status": "completed",
                "percent": 100.0,
                "message": message or "作業順利完成",
                "data": data or {},
            }
            record = self._task_records.get(task_id)
            if record:
                record.status = "completed"
                record.finished_at = time.time()
                record.speed_bps = 0.0
                record.eta_seconds = 0.0
                record.message = message or "作業順利完成"
                if record.bytes_total > 0:
                    record.bytes_done = record.bytes_total
                if record.files_total > 0:
                    record.files_done = record.files_total
                broadcaster.publish("task.update", record.to_dict())

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
        self._finish_queue(task_id)

    def fail(self, task_id: str, error: str) -> None:
        """Mark task as failed and signal end of stream."""
        with self._lock:
            self._task_statuses[task_id] = {
                "status": "failed",
                "percent": 0.0,
                "message": error,
            }
            record = self._task_records.get(task_id)
            if record:
                record.status = "failed"
                record.finished_at = time.time()
                record.speed_bps = 0.0
                record.eta_seconds = None
                record.errors += 1
                record.message = error
                broadcaster.publish("task.update", record.to_dict())

        self.emit(
            task_id,
            TaskEvent(
                task_id=task_id,
                event_type="failed",
                message=error,
            ),
        )
        self._finish_queue(task_id)

    def _finish_queue(self, task_id: str) -> None:
        with self._lock:
            queue = self._queues.get(task_id)
            loop = self._loops.get(task_id)
            gate = self._pause_gates.get(task_id)
            if gate:
                gate.set()

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
            record = self._task_records.get(task_id)
            if record:
                base = dict(self._task_statuses.get(task_id, {}))
                base.update(record.to_dict())
                return base
            return self._task_statuses.get(task_id)

    def get_record(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._task_records.get(task_id)

    def list_records(self, limit: int = 100) -> list[TaskRecord]:
        with self._lock:
            records = list(self._task_records.values())
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    def create_progress_callback(self, task_id: str) -> ProgressCallback:
        """Create a standard ProgressCallback callable for transfer services."""
        def callback(transferred: int, total: int) -> None:
            self.emit_progress(task_id, transferred, total)

        return callback

    async def subscribe(self, task_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to an SSE event stream for a single task."""
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
                self._pause_gates.pop(task_id, None)


# Global event manager instance
task_event_manager = TaskEventManager()
