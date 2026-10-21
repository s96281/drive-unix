"""Application service for synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections.abc import Callable

from core.constants import DEFAULT_SCAN_THROTTLE_SECONDS, DEFAULT_SCAN_WORKERS
from domain.models import FileItem
from domain.errors import ScanIncompleteError
from domain.sync.models import SyncAction, SyncActionType, SyncOptions, SyncPlan, SyncSnapshot
from domain.sync.planner import SyncPlanner
from domain.sync.scanner import scan_storage_tree
from application.transfer_service import TransferService
from storage.base import StorageProvider
from infrastructure.rate_limit import RateLimiter



@dataclass(frozen=True)
class SyncActionToken:
    """Opaque token used by UI callbacks to associate progress with a worker."""

    action_id: int


@dataclass(frozen=True)
class SyncExecutionResult:
    """Aggregated execution outcome."""

    succeeded: int
    failed: int
    skipped: int
    errors: tuple[tuple[SyncAction, Exception], ...]

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.skipped == 0


class SyncHooks:
    """Optional event callbacks for CLI/UI integrations."""

    def action_started(self, action: SyncAction) -> SyncActionToken | None:
        return None

    def progress(
        self,
        token: SyncActionToken | None,
        stage: str,
        transferred: int,
        total: int,
    ) -> None:
        return None

    def action_finished(
        self,
        action: SyncAction,
        token: SyncActionToken | None,
        error: Exception | None,
    ) -> None:
        return None

    def message(self, message: str) -> None:
        return None


class SyncExecutor:
    """Execute a pre-built synchronization plan."""

    def __init__(self, transfer_service: TransferService | None = None) -> None:
        self.transfer_service = transfer_service or TransferService()

    def execute(
        self,
        plan: SyncPlan,
        *,
        source_remote: str,
        source_storage: StorageProvider,
        destination_remote: str,
        destination_storage: StorageProvider,
        workers: int = DEFAULT_SCAN_WORKERS,
        throttle: float = 0.0,
        hooks: SyncHooks | None = None,
    ) -> SyncExecutionResult:
        if workers < 1:
            raise ValueError("workers 必須大於等於 1")

        hooks = hooks or SyncHooks()
        limiter = RateLimiter(throttle)

        def apply_throttle() -> None:
            limiter.acquire()

        def run_action(action: SyncAction) -> None:
            apply_throttle()
            token = hooks.action_started(action)

            def progress_factory(stage: str):
                def on_progress(transferred: int, total: int) -> None:
                    hooks.progress(token, stage, transferred, total)

                return on_progress

            try:
                self._execute_action(
                    action,
                    source_remote=source_remote,
                    source_storage=source_storage,
                    destination_remote=destination_remote,
                    destination_storage=destination_storage,
                    download_callback=progress_factory("download"),
                    upload_callback=progress_factory("upload"),
                    direct_callback=progress_factory("copy"),
                )
            except Exception as exc:
                hooks.action_finished(action, token, exc)
                raise
            else:
                hooks.action_finished(action, token, None)

        errors: list[tuple[SyncAction, Exception]] = []
        succeeded = 0
        skipped = 0

        for batch_index, batch in enumerate(plan.batches):
            batch_errors: list[tuple[SyncAction, Exception]] = []

            if workers == 1 or batch.count == 1:
                for action in batch.actions:
                    try:
                        run_action(action)
                        succeeded += 1
                    except Exception as exc:
                        batch_errors.append((action, exc))
            else:
                batch_succeeded, batch_errors = self._run_parallel_batch(
                    batch.actions,
                    workers=workers,
                    run_action=run_action,
                )
                succeeded += batch_succeeded

            if batch_errors:
                errors.extend(batch_errors)
                skipped = sum(
                    remaining_batch.count
                    for remaining_batch in plan.batches[batch_index + 1 :]
                )
                hooks.message(
                    f"批次 {batch.name} 執行失敗；略過後續 {skipped} 個相依操作。"
                )
                break

        return SyncExecutionResult(
            succeeded=succeeded,
            failed=len(errors),
            skipped=skipped,
            errors=tuple(errors),
        )


    @staticmethod
    def _run_parallel_batch(
        actions: tuple[SyncAction, ...],
        *,
        workers: int,
        run_action: Callable[[SyncAction], None],
    ) -> tuple[int, list[tuple[SyncAction, Exception]]]:
        """Execute a batch with at most ``workers`` futures alive at once."""

        action_iter = iter(actions)
        succeeded = 0
        errors: list[tuple[SyncAction, Exception]] = []

        with ThreadPoolExecutor(max_workers=min(workers, len(actions))) as executor:
            in_flight = {}

            def submit_next() -> bool:
                try:
                    action = next(action_iter)
                except StopIteration:
                    return False
                future = executor.submit(run_action, action)
                in_flight[future] = action
                return True

            for _ in range(min(workers, len(actions))):
                submit_next()

            while in_flight:
                done, _ = wait(
                    tuple(in_flight),
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    action = in_flight.pop(future)
                    try:
                        future.result()
                        succeeded += 1
                    except Exception as exc:
                        errors.append((action, exc))
                    submit_next()

        return succeeded, errors

    def _execute_action(
        self,
        action: SyncAction,
        *,
        source_remote: str,
        source_storage: StorageProvider,
        destination_remote: str,
        destination_storage: StorageProvider,
        download_callback: Callable[[int, int], None],
        upload_callback: Callable[[int, int], None],
        direct_callback: Callable[[int, int], None],
    ) -> None:
        kind = action.action_type

        if kind == SyncActionType.COPY_TO_DEST:
            self.transfer_service.copy_between(
                source_remote,
                source_storage,
                action.item.path,
                destination_remote,
                destination_storage,
                action.target_path,
                download_callback=download_callback,
                upload_callback=upload_callback,
                direct_callback=direct_callback,
            )
            return

        if kind == SyncActionType.COPY_TO_SRC:
            self.transfer_service.copy_between(
                destination_remote,
                destination_storage,
                action.item.path,
                source_remote,
                source_storage,
                action.target_path,
                download_callback=download_callback,
                upload_callback=upload_callback,
                direct_callback=direct_callback,
            )
            return

        if kind == SyncActionType.SYNC_OFFICE:
            self.transfer_service.copy_between(
                source_remote,
                source_storage,
                action.item.path,
                destination_remote,
                destination_storage,
                action.target_path,
                download_callback=download_callback,
                upload_callback=upload_callback,
                direct_callback=direct_callback,
            )
            self.transfer_service.copy_between(
                destination_remote,
                destination_storage,
                action.target_path,
                source_remote,
                source_storage,
                action.item.path,
                download_callback=download_callback,
                upload_callback=upload_callback,
                direct_callback=direct_callback,
            )
            return

        if kind == SyncActionType.MKDIR_DEST:
            self._require_success(
                destination_storage.mkdir(action.target_path, parents=True),
                f"建立目標資料夾 {action.target_path}",
            )
            return

        if kind == SyncActionType.MKDIR_SRC:
            self._require_success(
                source_storage.mkdir(action.target_path, parents=True),
                f"建立來源資料夾 {action.target_path}",
            )
            return

        if kind == SyncActionType.DELETE_DEST:
            self._require_success(
                destination_storage.delete(action.target_path, permanent=False),
                f"刪除目標項目 {action.target_path}",
            )
            return

        if kind == SyncActionType.DELETE_SRC:
            self._require_success(
                source_storage.delete(action.target_path, permanent=False),
                f"刪除來源項目 {action.target_path}",
            )
            return

        if kind == SyncActionType.RENAME_DEST:
            self._require_success(
                destination_storage.move(action.item.path, action.target_path),
                f"重新命名目標項目 {action.item.path}",
            )
            return

        if kind == SyncActionType.RENAME_SRC:
            self._require_success(
                source_storage.move(action.item.path, action.target_path),
                f"重新命名來源項目 {action.item.path}",
            )
            return

        raise ValueError(f"Unsupported sync action: {kind}")

    @staticmethod
    def _require_success(result, operation: str) -> None:
        if result is False:
            raise RuntimeError(f"{operation} 失敗：Provider 回傳 False")



class SyncService:
    """Coordinate snapshotting, planning and execution."""

    CHECKSUM_SUPPORTED_TYPES = frozenset({"local", "sharepoint"})

    def __init__(
        self,
        *,
        source_remote: str,
        source_storage: StorageProvider,
        source_type: str,
        destination_remote: str,
        destination_storage: StorageProvider,
        destination_type: str,
        source_path: str,
        destination_path: str,
        planner: SyncPlanner | None = None,
        executor: SyncExecutor | None = None,
    ) -> None:
        self.source_remote = source_remote
        self.source_storage = source_storage
        self.source_type = source_type
        self.destination_remote = destination_remote
        self.destination_storage = destination_storage
        self.destination_type = destination_type
        self._source_base_path = source_path
        self._destination_base_path = destination_path
        self.planner = planner or SyncPlanner()
        self.executor = executor or SyncExecutor()

    def scan(
        self,
        *,
        strict: bool = True,
        source_throttle: float = DEFAULT_SCAN_THROTTLE_SECONDS,
        destination_throttle: float = DEFAULT_SCAN_THROTTLE_SECONDS,
        scan_workers: int = 4,
        on_source_progress: Callable[[int, int], None] | None = None,
        on_destination_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[SyncSnapshot, SyncSnapshot]:
        if scan_workers < 1:
            raise ValueError("scan_workers 必須大於等於 1")

        if self.source_remote == self.destination_remote:
            source_snapshot = scan_storage_tree(
                self.source_storage,
                self._source_base_path,
                strict=strict,
                throttle=source_throttle,
                max_workers=scan_workers,
                on_progress=on_source_progress,
            )
            destination_snapshot = scan_storage_tree(
                self.destination_storage,
                self._destination_base_path,
                strict=strict,
                throttle=destination_throttle,
                max_workers=scan_workers,
                on_progress=on_destination_progress,
            )
            return source_snapshot, destination_snapshot

        with ThreadPoolExecutor(max_workers=2) as executor:
            source_future = executor.submit(
                scan_storage_tree,
                self.source_storage,
                self._source_base_path,
                strict=strict,
                throttle=source_throttle,
                max_workers=scan_workers,
                on_progress=on_source_progress,
            )
            destination_future = executor.submit(
                scan_storage_tree,
                self.destination_storage,
                self._destination_base_path,
                strict=strict,
                throttle=destination_throttle,
                max_workers=scan_workers,
                on_progress=on_destination_progress,
            )
            return source_future.result(), destination_future.result()

    def build_plan(
        self,
        *,
        source_snapshot: SyncSnapshot,
        destination_snapshot: SyncSnapshot,
        options: SyncOptions,
    ) -> SyncPlan:
        if not source_snapshot.complete or not destination_snapshot.complete:
            raise ScanIncompleteError(
                "無法建立同步計畫：Snapshot 並不完整。"
            )

        checksum_executor = None
        checksum_comparator = None
        if (
            options.checksum
            and self.source_type in self.CHECKSUM_SUPPORTED_TYPES
            and self.destination_type in self.CHECKSUM_SUPPORTED_TYPES
        ):
            checksum_executor = ThreadPoolExecutor(max_workers=2)

            def compare_with_parallel_hashes(source_item, destination_item):
                return self.compare_checksums(
                    source_item,
                    destination_item,
                    executor=checksum_executor,
                )

            checksum_comparator = compare_with_parallel_hashes

        try:
            return self.planner.build_plan(
                source_items=source_snapshot.items,
                destination_items=destination_snapshot.items,
                source_base_path=source_snapshot.base_path,
                destination_base_path=destination_snapshot.base_path,
                source_type=self.source_type,
                destination_type=self.destination_type,
                options=options,
                checksum_comparator=checksum_comparator,
            )
        finally:
            if checksum_executor is not None:
                checksum_executor.shutdown(wait=True, cancel_futures=True)

    def execute(
        self,
        plan: SyncPlan,
        *,
        workers: int = 4,
        throttle: float = 0.0,
        hooks: SyncHooks | None = None,
    ) -> SyncExecutionResult:
        return self.executor.execute(
            plan,
            source_remote=self.source_remote,
            source_storage=self.source_storage,
            destination_remote=self.destination_remote,
            destination_storage=self.destination_storage,
            workers=workers,
            throttle=throttle,
            hooks=hooks,
        )

    def compare_checksums(
        self,
        source_item: FileItem,
        destination_item: FileItem,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> tuple[bool, str]:
        if executor is None:
            source_hash = self.source_storage.get_hash(source_item.path, "quickXorHash")
            destination_hash = self.destination_storage.get_hash(destination_item.path, "quickXorHash")
        else:
            source_future = executor.submit(
                self.source_storage.get_hash,
                source_item.path,
                "quickXorHash",
            )
            destination_future = executor.submit(
                self.destination_storage.get_hash,
                destination_item.path,
                "quickXorHash",
            )
            source_hash = source_future.result()
            destination_hash = destination_future.result()

        if source_hash != destination_hash:
            return True, "內容已變更 (QuickXorHash 不符)"
        return False, ""

    def _compare_checksums(
        self,
        source_item: FileItem,
        destination_item: FileItem,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> tuple[bool, str]:
        """Backward-compatible alias for the former private checksum helper."""

        return self.compare_checksums(
            source_item,
            destination_item,
            executor=executor,
        )
