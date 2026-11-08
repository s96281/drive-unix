"""Rich-progress adapter for application transfer jobs."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Generic, TypeVar

from rich.progress import Progress

from storage.base import ProgressCallback

T = TypeVar("T")


class TransferProgressHooks(Generic[T]):
    """Map concurrent application jobs onto a fixed set of Rich worker rows."""

    def __init__(
        self,
        progress: Progress,
        *,
        workers: int,
        overall_task: int,
        filename: Callable[[T], str],
        icon: str,
        color: str,
    ) -> None:
        self._progress = progress
        self._overall_task = overall_task
        self._filename = filename
        self._icon = icon
        self._color = color
        self._available: queue.Queue[int] = queue.Queue()
        self._active: dict[T, int] = {}
        self._lock = threading.Lock()

        for index in range(workers):
            task_id = progress.add_task(
                "",
                filename=f"閒置線程 {index + 1}",
                icon="⠧",
                color="dim",
                total=100,
            )
            self._available.put(task_id)

    def started(self, job: T) -> ProgressCallback:
        task_id = self._available.get()
        with self._lock:
            self._active[job] = task_id

        self._progress.update(
            task_id,
            filename=self._filename(job),
            icon=self._icon,
            color=self._color,
            completed=0,
        )

        def callback(transferred: int, total: int) -> None:
            self._progress.update(
                task_id,
                completed=transferred,
                total=total,
            )

        return callback

    def finished(self, job: T, error: Exception | None) -> None:
        del error  # Presentation is rendered from the aggregated result.
        with self._lock:
            task_id = self._active.pop(job)
        self._progress.update(
            task_id,
            filename="閒置線程",
            icon="⠧",
            color="dim",
            completed=0,
            total=100,
        )
        self._progress.update(self._overall_task, advance=1)
        self._available.put(task_id)
