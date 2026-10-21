"""Snapshot scanning logic for storage providers."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable

from domain.errors import ScanIncompleteError
from domain.models import FileItem
from domain.sync.models import SyncSnapshot
from core.constants import DEFAULT_SCAN_THROTTLE_SECONDS, DEFAULT_SCAN_WORKERS
from infrastructure.rate_limit import RateLimiter
from storage.base import StorageProvider


ScanProgressCallback = Callable[[int, int], None]


def scan_storage_tree(
    storage: StorageProvider,
    base_path: str,
    *,
    throttle: float = DEFAULT_SCAN_THROTTLE_SECONDS,
    strict: bool = False,
    on_progress: ScanProgressCallback | None = None,
    max_workers: int = DEFAULT_SCAN_WORKERS,
) -> SyncSnapshot:
    """Scan an entire storage subtree and return a normalized snapshot.

    The scanner uses bounded concurrency for directory listings and a shared
    rate limiter so the whole scan still respects the configured request rate.
    In strict mode any failed directory listing aborts the scan instead of
    returning a partial snapshot.
    """

    if max_workers < 1:
        raise ValueError("max_workers 必須大於等於 1")
    if throttle < 0:
        raise ValueError("throttle 不可小於 0")

    file_dict: dict[str, FileItem] = {}
    folder_count = 0
    file_count = 0
    complete = True
    limiter = RateLimiter(throttle)

    def list_directory(current_path: str, relative_prefix: str):
        limiter.acquire()
        try:
            items = storage.list_dir(current_path)
            return current_path, relative_prefix, items, None
        except Exception as exc:
            return current_path, relative_prefix, None, exc

    pending: dict[Future, tuple[str, str]] = {}
    executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(path: str, prefix: str) -> None:
        future = executor.submit(list_directory, path, prefix)
        pending[future] = (path, prefix)

    submit(base_path, "")

    try:
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)

            for future in done:
                current_path, relative_prefix = pending.pop(future)
                _, _, items, error = future.result()

                if error is not None:
                    message = f"無法讀取目錄 {current_path}: {error}"
                    if strict:
                        for queued in pending:
                            queued.cancel()
                        raise ScanIncompleteError(message) from error
                    complete = False
                    continue

                for item in items:
                    rel_path = f"{relative_prefix}/{item.name}".strip("/")
                    file_dict[rel_path] = item

                    if item.is_dir:
                        folder_count += 1
                        submit(item.path, rel_path)
                    else:
                        file_count += 1

                    if on_progress:
                        on_progress(folder_count, file_count)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    return SyncSnapshot(
        base_path=base_path,
        items=file_dict,
        complete=complete,
    )


# Backward-compatible naming used by the CLI during the migration.
def get_all_files_recursive(
    storage: StorageProvider,
    base_path: str,
    throttle: float = DEFAULT_SCAN_THROTTLE_SECONDS,
    *,
    strict: bool = False,
    max_workers: int = DEFAULT_SCAN_WORKERS,
) -> dict[str, FileItem]:
    """Return only the flattened item dictionary from a snapshot scan."""

    return scan_storage_tree(
        storage,
        base_path,
        throttle=throttle,
        strict=strict,
        max_workers=max_workers,
    ).items
