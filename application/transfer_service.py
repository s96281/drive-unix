"""Cross-provider transfer application service."""

from __future__ import annotations

import os
import posixpath
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import Generic, TypeVar

from domain.models import FileItem
from domain.sync.scanner import get_all_files_recursive
from storage.base import ProgressCallback, StorageProvider
T = TypeVar("T")


@dataclass(frozen=True)
class UploadJob:
    local_path: str
    remote_path: str


@dataclass(frozen=True)
class DownloadJob:
    item: FileItem
    local_path: str


@dataclass(frozen=True)
class RecursiveUploadPlan:
    remote_root: str
    jobs: tuple[UploadJob, ...]
    empty_directories: tuple[str, ...]


@dataclass(frozen=True)
class RecursiveDownloadPlan:
    local_root: str
    jobs: tuple[DownloadJob, ...]
    directories: tuple[str, ...]
    skipped: int


class TransferOperationError(RuntimeError):
    """Raised when a provider explicitly reports an unsuccessful operation."""


@dataclass(frozen=True)
class BatchTransferFailure(Generic[T]):
    job: T
    error: Exception


@dataclass(frozen=True)
class BatchTransferResult(Generic[T]):
    succeeded: int
    failures: tuple[BatchTransferFailure[T], ...]

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def success(self) -> bool:
        return not self.failures


class TransferService:
    """Perform provider-to-provider copies without UI concerns."""

    @staticmethod
    def _require_success(result: bool, operation: str) -> None:
        if result is False:
            raise TransferOperationError(
                f"{operation} 失敗：Provider 回傳 False"
            )

    @classmethod
    def call_upload(
        cls,
        storage: StorageProvider,
        local_path: str,
        remote_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        result = storage.upload(
            local_path,
            remote_path,
            callback=callback,
        )
        cls._require_success(result, f"上傳 {local_path} -> {remote_path}")
        if callback and not os.path.exists(local_path):
            callback(0, 0)
        return True

    @classmethod
    def call_download(
        cls,
        storage: StorageProvider,
        remote_path: str,
        local_path: str,
        *,
        recursive: bool = False,
        callback: ProgressCallback | None = None,
    ) -> bool:
        result = storage.download(
            remote_path,
            local_path,
            recursive=recursive,
            callback=callback,
        )
        cls._require_success(result, f"下載 {remote_path} -> {local_path}")
        return True

    @staticmethod
    def run_batch(
        jobs: Iterable[T],
        worker: Callable[[T], None],
        *,
        workers: int,
    ) -> BatchTransferResult[T]:
        """Run independent transfer jobs concurrently and aggregate every failure."""

        if workers < 1:
            raise ValueError("workers 必須大於等於 1")

        job_list = list(jobs)
        if not job_list:
            return BatchTransferResult(succeeded=0, failures=())

        succeeded = 0
        failures: list[BatchTransferFailure[T]] = []

        job_iter = iter(job_list)
        with ThreadPoolExecutor(max_workers=min(workers, len(job_list))) as executor:
            in_flight = {}

            def submit_next() -> bool:
                try:
                    job = next(job_iter)
                except StopIteration:
                    return False
                in_flight[executor.submit(worker, job)] = job
                return True

            for _ in range(min(workers, len(job_list))):
                submit_next()

            while in_flight:
                done, _ = wait(
                    tuple(in_flight),
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    job = in_flight.pop(future)
                    try:
                        future.result()
                        succeeded += 1
                    except Exception as exc:
                        failures.append(BatchTransferFailure(job=job, error=exc))
                    submit_next()

        return BatchTransferResult(
            succeeded=succeeded,
            failures=tuple(failures),
        )

    @classmethod
    def ensure_remote_directory(
        cls,
        storage: StorageProvider,
        remote_dir: str,
    ) -> None:
        """Ensure a remote directory exists without hiding mkdir failures."""
        if not remote_dir or remote_dir == "/":
            return
        try:
            info = storage.stat(remote_dir)
        except Exception:
            info = None
        if info and info.get("type") in {"folder", "remote"}:
            return
        cls._require_success(
            storage.mkdir(remote_dir, parents=True),
            f"建立遠端資料夾 {remote_dir}",
        )

    @staticmethod
    def build_recursive_upload_plan(
        local_path: str,
        remote_path: str,
    ) -> RecursiveUploadPlan:
        """Build a deterministic recursive upload plan without performing I/O."""
        local_dir_name = os.path.basename(os.path.normpath(local_path))
        remote_leaf = posixpath.basename(remote_path.rstrip("/"))
        if remote_leaf == local_dir_name:
            remote_root = remote_path
        else:
            remote_root = posixpath.join(remote_path, local_dir_name).replace("\\", "/")

        jobs: list[UploadJob] = []
        empty_directories: list[str] = []
        for root, dirs, files in os.walk(local_path):
            if not dirs and not files:
                relative = os.path.relpath(root, local_path)
                target = (
                    remote_root
                    if relative == "."
                    else posixpath.join(remote_root, relative).replace("\\", "/")
                )
                empty_directories.append(target)
            for filename in files:
                local_file = os.path.join(root, filename)
                relative = os.path.relpath(local_file, local_path)
                target = posixpath.join(remote_root, relative).replace("\\", "/")
                jobs.append(UploadJob(local_path=local_file, remote_path=target))

        return RecursiveUploadPlan(
            remote_root=remote_root,
            jobs=tuple(jobs),
            empty_directories=tuple(empty_directories),
        )

    @classmethod
    def upload_tree(
        cls,
        storage: StorageProvider,
        plan: RecursiveUploadPlan,
        *,
        workers: int,
        on_started: Callable[[UploadJob], ProgressCallback | None] | None = None,
        on_finished: Callable[[UploadJob, Exception | None], None] | None = None,
    ) -> BatchTransferResult[UploadJob]:
        """Execute a recursive upload plan with thread-safe directory creation."""
        known_directories: set[str] = set()
        directory_lock = threading.Lock()

        def ensure_directory(remote_dir: str) -> None:
            if not remote_dir or remote_dir == "/":
                return
            with directory_lock:
                if remote_dir in known_directories:
                    return
                cls.ensure_remote_directory(storage, remote_dir)
                known_directories.add(remote_dir)

        for remote_dir in plan.empty_directories:
            ensure_directory(remote_dir)

        def worker(job: UploadJob) -> None:
            callback = on_started(job) if on_started else None
            error: Exception | None = None
            try:
                ensure_directory(posixpath.dirname(job.remote_path))
                cls.call_upload(storage, job.local_path, job.remote_path, callback=callback)
            except Exception as exc:
                error = exc
                raise
            finally:
                if on_finished:
                    on_finished(job, error)

        return cls.run_batch(plan.jobs, worker, workers=workers)

    @staticmethod
    def build_recursive_download_plan(
        storage: StorageProvider,
        remote_path: str,
        local_path: str,
        *,
        force: bool = False,
    ) -> RecursiveDownloadPlan:
        """Scan a remote tree and decide what needs to be downloaded."""
        remote_files = get_all_files_recursive(storage, remote_path)
        remote_dir_name = remote_path.strip("/").split("/")[-1]
        local_root = os.path.join(local_path, remote_dir_name)
        jobs: list[DownloadJob] = []
        directories: list[str] = []
        skipped = 0

        for relative_path, item in remote_files.items():
            target = os.path.join(local_root, relative_path)
            if item.is_dir:
                directories.append(target)
                continue
            if (
                not force
                and os.path.isfile(target)
                and item.size is not None
                and os.path.getsize(target) == item.size
            ):
                skipped += 1
                continue
            jobs.append(DownloadJob(item=item, local_path=target))

        return RecursiveDownloadPlan(
            local_root=local_root,
            jobs=tuple(jobs),
            directories=tuple(directories),
            skipped=skipped,
        )

    @classmethod
    def download_tree(
        cls,
        storage: StorageProvider,
        plan: RecursiveDownloadPlan,
        *,
        workers: int,
        on_started: Callable[[DownloadJob], ProgressCallback | None] | None = None,
        on_finished: Callable[[DownloadJob, Exception | None], None] | None = None,
    ) -> BatchTransferResult[DownloadJob]:
        """Execute a recursive download plan."""
        os.makedirs(plan.local_root, exist_ok=True)
        for directory in plan.directories:
            os.makedirs(directory, exist_ok=True)

        def worker(job: DownloadJob) -> None:
            os.makedirs(os.path.dirname(job.local_path), exist_ok=True)
            callback = on_started(job) if on_started else None
            error: Exception | None = None
            try:
                cls.call_download(
                    storage,
                    job.item.path,
                    job.local_path,
                    recursive=False,
                    callback=callback,
                )
            except Exception as exc:
                error = exc
                raise
            finally:
                if on_finished:
                    on_finished(job, error)

        return cls.run_batch(plan.jobs, worker, workers=workers)

    def move_between(
        self,
        source_remote: str,
        source_storage: StorageProvider,
        source_path: str,
        destination_remote: str,
        destination_storage: StorageProvider,
        destination_path: str,
        *,
        download_callback: ProgressCallback | None = None,
        upload_callback: ProgressCallback | None = None,
    ) -> None:
        """Move within one provider or bridge across providers safely."""
        if source_remote == destination_remote:
            self._require_success(
                source_storage.move(source_path, destination_path),
                f"移動 {source_path} -> {destination_path}",
            )
            return

        with tempfile.TemporaryDirectory(prefix="drive-unix-move-") as temp_dir:
            filename = source_path.strip("/").split("/")[-1]
            temp_file_path = os.path.join(temp_dir, filename)
            self.call_download(
                source_storage,
                source_path,
                temp_file_path,
                callback=download_callback,
            )
            self.ensure_remote_directory(
                destination_storage,
                posixpath.dirname(destination_path),
            )
            self.call_upload(
                destination_storage,
                temp_file_path,
                destination_path,
                callback=upload_callback,
            )
            self._require_success(
                source_storage.delete(source_path, permanent=False),
                f"刪除移動來源 {source_path}",
            )

    def copy_between(
        self,
        source_remote: str,
        source_storage: StorageProvider,
        source_path: str,
        destination_remote: str,
        destination_storage: StorageProvider,
        destination_path: str,
        *,
        download_callback: ProgressCallback | None = None,
        upload_callback: ProgressCallback | None = None,
        direct_callback: ProgressCallback | None = None,
    ) -> None:
        self.ensure_remote_directory(
            destination_storage,
            posixpath.dirname(destination_path),
        )

        if source_remote == destination_remote:
            result = source_storage.copy(
                source_path,
                destination_path,
                overwrite=True,
            )
            self._require_success(
                result,
                f"複製 {source_path} -> {destination_path}",
            )
            if direct_callback:
                direct_callback(100, 100)
            return

        with tempfile.TemporaryDirectory(prefix="drive-unix-transfer-") as temp_dir:
            filename = source_path.strip("/").split("/")[-1]
            temp_file_path = os.path.join(temp_dir, filename)

            self.call_download(
                source_storage,
                source_path,
                temp_file_path,
                callback=download_callback,
            )
            self.call_upload(
                destination_storage,
                temp_file_path,
                destination_path,
                callback=upload_callback,
            )
