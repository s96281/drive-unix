"""Domain models for synchronization planning and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from domain.models import FileItem

ConflictStrategy = Literal[
    "auto",
    "newer",
    "rename",
    "abort",
    "prefer-source",
    "prefer-destination",
]


class SyncActionType(str, Enum):
    """Executable synchronization actions."""

    COPY_TO_DEST = "COPY_TO_DEST"
    COPY_TO_SRC = "COPY_TO_SRC"
    SYNC_OFFICE = "SYNC_OFFICE"
    MKDIR_DEST = "MKDIR_DEST"
    MKDIR_SRC = "MKDIR_SRC"
    DELETE_DEST = "DELETE_DEST"
    DELETE_SRC = "DELETE_SRC"
    RENAME_DEST = "RENAME_DEST"
    RENAME_SRC = "RENAME_SRC"


@dataclass(frozen=True)
class SyncOptions:
    """Business rules used to build a synchronization plan."""

    one_way: bool = True
    delete: bool = False
    include_pattern: str | None = None
    exclude_pattern: str | None = None
    conflict: ConflictStrategy = "auto"
    checksum: bool = False

    def validate(self) -> None:
        if not self.one_way and self.delete:
            raise ValueError(
                "雙向同步模式下不支援 --delete，因為無法安全判斷檔案刪除來源。"
            )
        if self.conflict not in {
            "auto",
            "newer",
            "rename",
            "abort",
            "prefer-source",
            "prefer-destination",
        }:
            raise ValueError(f"不支援的 conflict 策略: {self.conflict}")
        if self.one_way and self.conflict in {"abort", "prefer-destination"}:
            raise ValueError(
                f"--conflict {self.conflict} 僅適用於雙向同步。"
                "單向 sync 可使用 auto、newer、rename 或 prefer-source。"
            )


@dataclass(frozen=True)
class SyncAction:
    """One mutation in a synchronization plan."""

    action_type: SyncActionType
    item: FileItem
    target_path: str
    reason: str


@dataclass(frozen=True)
class SyncExecutionBatch:
    """Actions that may execute concurrently after all earlier batches finish."""

    name: str
    actions: tuple[SyncAction, ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        return len(self.actions)


@dataclass(frozen=True)
class SyncPlan:
    """Immutable, dependency-aware synchronization plan."""

    batches: tuple[SyncExecutionBatch, ...] = field(default_factory=tuple)

    @classmethod
    def from_actions(cls, actions: tuple[SyncAction, ...] | list[SyncAction]) -> "SyncPlan":
        """Build execution barriers from a deterministic action sequence.

        Destructive mutations that overlap a later write are prerequisites. Directory
        creation is performed shallow-to-deep, transfers run concurrently, and
        independent delete cleanup is deferred until all writes have succeeded.
        """

        ordered_actions = tuple(actions)
        if not ordered_actions:
            return cls()

        destination_write_index = _build_overlap_index(
            {
                action.target_path
                for action in ordered_actions
                if action.action_type
                in {
                    SyncActionType.COPY_TO_DEST,
                    SyncActionType.SYNC_OFFICE,
                    SyncActionType.MKDIR_DEST,
                }
            }
        )
        source_write_index = _build_overlap_index(
            {
                action.target_path
                for action in ordered_actions
                if action.action_type
                in {
                    SyncActionType.COPY_TO_SRC,
                    SyncActionType.MKDIR_SRC,
                }
            }
        )

        prerequisite_deletes: list[SyncAction] = []
        cleanup_deletes: list[SyncAction] = []
        prerequisite_renames: list[SyncAction] = []
        transfer_actions: list[SyncAction] = []
        mkdir_actions: list[SyncAction] = []

        for action in ordered_actions:
            kind = action.action_type
            if kind == SyncActionType.DELETE_DEST:
                if _overlaps_any(action.target_path, destination_write_index):
                    prerequisite_deletes.append(action)
                else:
                    cleanup_deletes.append(action)
                continue

            if kind == SyncActionType.DELETE_SRC:
                if _overlaps_any(action.target_path, source_write_index):
                    prerequisite_deletes.append(action)
                else:
                    cleanup_deletes.append(action)
                continue

            if kind == SyncActionType.RENAME_DEST:
                if _overlaps_any(action.item.path, destination_write_index):
                    prerequisite_renames.append(action)
                else:
                    transfer_actions.append(action)
                continue

            if kind == SyncActionType.RENAME_SRC:
                if _overlaps_any(action.item.path, source_write_index):
                    prerequisite_renames.append(action)
                else:
                    transfer_actions.append(action)
                continue

            if kind in {SyncActionType.MKDIR_DEST, SyncActionType.MKDIR_SRC}:
                mkdir_actions.append(action)
                continue

            transfer_actions.append(action)

        batches: list[SyncExecutionBatch] = []
        batches.extend(
            _group_by_depth(
                prerequisite_deletes,
                name_prefix="prepare-delete-depth",
                deepest_first=True,
            )
        )

        if prerequisite_renames:
            batches.append(
                SyncExecutionBatch(
                    "prepare-backup",
                    tuple(prerequisite_renames),
                )
            )

        batches.extend(
            _group_by_depth(
                mkdir_actions,
                name_prefix="mkdir-depth",
                deepest_first=False,
            )
        )

        if transfer_actions:
            batches.append(SyncExecutionBatch("transfer", tuple(transfer_actions)))

        batches.extend(
            _group_by_depth(
                cleanup_deletes,
                name_prefix="cleanup-delete-depth",
                deepest_first=True,
            )
        )

        return cls(tuple(batches))

    @property
    def actions(self) -> tuple[SyncAction, ...]:
        return tuple(action for batch in self.batches for action in batch.actions)

    @property
    def is_empty(self) -> bool:
        return not self.batches

    @property
    def count(self) -> int:
        return sum(batch.count for batch in self.batches)


@dataclass(frozen=True)
class SyncSnapshot:
    """Complete storage snapshot used by the planner."""

    base_path: str
    items: dict[str, FileItem]
    complete: bool = True


def _normalise_path(path: str) -> str:
    normalised = "/" + path.strip("/")
    return normalised if normalised != "" else "/"


def _path_depth(path: str) -> int:
    normalised = _normalise_path(path)
    if normalised == "/":
        return 0
    return len(normalised.strip("/").split("/"))


def _iter_ancestors(path: str):
    normalised = _normalise_path(path)
    yield normalised
    while normalised != "/":
        parent = normalised.rsplit("/", 1)[0] or "/"
        normalised = parent
        yield normalised


def _build_overlap_index(candidates: set[str]) -> tuple[set[str], set[str]]:
    normalised_candidates = {_normalise_path(path) for path in candidates}
    candidate_ancestors: set[str] = set()
    for candidate in normalised_candidates:
        candidate_ancestors.update(_iter_ancestors(candidate))
    return normalised_candidates, candidate_ancestors


def _overlaps_any(
    path: str,
    index: tuple[set[str], set[str]],
) -> bool:
    candidates, candidate_ancestors = index
    normalised = _normalise_path(path)

    # The queried path is an ancestor of (or equal to) a write target.
    if normalised in candidate_ancestors:
        return True

    # A write target is an ancestor of the queried path.
    return any(ancestor in candidates for ancestor in _iter_ancestors(normalised))


def _group_by_depth(
    actions: list[SyncAction],
    *,
    name_prefix: str,
    deepest_first: bool,
) -> list[SyncExecutionBatch]:
    if not actions:
        return []

    grouped: dict[int, list[SyncAction]] = {}
    for action in actions:
        grouped.setdefault(_path_depth(action.target_path), []).append(action)

    return [
        SyncExecutionBatch(f"{name_prefix}-{depth}", tuple(grouped[depth]))
        for depth in sorted(grouped, reverse=deepest_first)
    ]
