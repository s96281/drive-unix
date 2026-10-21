"""Pure synchronization planning rules."""

from __future__ import annotations

import fnmatch
import logging
import mimetypes
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from core.constants import MICROSOFT_PROVIDER_TYPES, OFFICE_EXTENSIONS
from domain.errors import SyncConflictError
from domain.models import FileItem
from domain.sync.models import SyncAction, SyncActionType, SyncOptions, SyncPlan

logger = logging.getLogger(__name__)

SUPPORTED_MEDIA_PREFIXES = ("image/", "video/")


def is_supported_media_file(filename_or_path: str) -> bool:
    mime, _ = mimetypes.guess_type(filename_or_path)
    return bool(mime and any(mime.startswith(prefix) for prefix in SUPPORTED_MEDIA_PREFIXES))


HashComparator = Callable[[FileItem, FileItem], tuple[bool, str]]


MTIME_TOLERANCE_SECONDS = 1.0


def should_exclude(
    rel_path: str,
    include_pattern: str | None,
    exclude_pattern: str | None,
) -> bool:
    """Return True when an item should be excluded from planning."""

    filename = rel_path.rsplit("/", 1)[-1]
    if include_pattern and not fnmatch.fnmatch(filename, include_pattern):
        return True
    if exclude_pattern and fnmatch.fnmatch(filename, exclude_pattern):
        return True
    return False


def is_office_file(item: FileItem) -> bool:
    return not item.is_dir and any(
        item.name.lower().endswith(ext) for ext in OFFICE_EXTENSIONS
    )


def _join_remote_path(base_path: str, relative_path: str) -> str:
    return f"{base_path.rstrip('/')}/{relative_path.lstrip('/') or ''}".rstrip("/") or "/"


def _renamed_path(
    path: str,
    modified_at: datetime | None,
    fallback: str = "conflict",
) -> str:
    timestamp = modified_at.strftime("%Y%m%d_%H%M%S") if modified_at else fallback
    name, sep, extension = path.rpartition(".")
    if sep and name:
        return f"{name}_{timestamp}.{extension}"
    return f"{path}_{timestamp}"


class SyncPlanner:
    """Build a deterministic synchronization plan from two snapshots."""

    def compare_items(
        self,
        source_item: FileItem,
        destination_item: FileItem,
        *,
        destination_type: str,
        options: SyncOptions,
        checksum_comparator: HashComparator | None = None,
        source_type: str = "",
    ) -> tuple[bool, str]:
        """Compare two matching-path items using the planner's sync policy.

        ``one_way`` uses the source-to-destination update policy, while two-way
        mode performs a symmetric content comparison.  Keeping this entry point
        public lets read-only commands such as ``diff`` share exactly the same
        size, mtime, Office-file and checksum rules as synchronization planning.
        """

        options.validate()

        if source_item.is_dir != destination_item.is_dir:
            return True, "型態不同"
        if source_item.is_dir:
            return False, ""

        office_mode = (
            destination_type in MICROSOFT_PROVIDER_TYPES
            and is_office_file(source_item)
        )
        photos_mode = (
            destination_type == "googlephotos"
            or source_type == "googlephotos"
        )

        if options.one_way:
            return self._compare_items(
                source_item,
                destination_item,
                office_mode=office_mode,
                photos_mode=photos_mode,
                checksum_enabled=options.checksum,
                checksum_comparator=checksum_comparator,
            )

        return self._content_differs_two_way(
            source_item,
            destination_item,
            office_mode=office_mode,
            photos_mode=photos_mode,
            checksum_enabled=options.checksum,
            checksum_comparator=checksum_comparator,
        )

    def build_plan(
        self,
        *,
        source_items: dict[str, FileItem],
        destination_items: dict[str, FileItem],
        source_base_path: str,
        destination_base_path: str,
        source_type: str,
        destination_type: str,
        options: SyncOptions,
        checksum_comparator: HashComparator | None = None,
    ) -> SyncPlan:
        options.validate()

        actions: list[SyncAction] = []
        pending_add: list[tuple[str, FileItem, str]] = []
        pending_delete: list[tuple[str, FileItem, str]] = []
        consumed_rel_paths: set[str] = set()

        all_keys = sorted(set(source_items) | set(destination_items))

        for rel_path in all_keys:
            if rel_path in consumed_rel_paths:
                continue
            if should_exclude(
                rel_path,
                options.include_pattern,
                options.exclude_pattern,
            ):
                continue

            source_item = source_items.get(rel_path)
            destination_item = destination_items.get(rel_path)
            source_target = _join_remote_path(source_base_path, rel_path)
            destination_target = _join_remote_path(destination_base_path, rel_path)

            if destination_type == "googlephotos" and source_item and not source_item.is_dir:
                if not is_supported_media_file(rel_path):
                    logger.warning("略過不支援的媒體檔案: %s (Google Photos 僅支援照片與影片)", rel_path)
                    continue

            if (
                source_item
                and destination_item
                and source_item.is_dir != destination_item.is_dir
            ):
                if options.one_way:
                    consumed_rel_paths.update(
                        self._plan_type_replacement(
                            actions=actions,
                            rel_path=rel_path,
                            source_item=source_item,
                            destination_item=destination_item,
                            destination_items=destination_items,
                            destination_base_path=destination_base_path,
                            destination_target=destination_target,
                            destination_type=destination_type,
                            options=options,
                        )
                    )
                else:
                    consumed_rel_paths.update(
                        self._plan_two_way_type_replacement(
                            actions=actions,
                            rel_path=rel_path,
                            source_item=source_item,
                            destination_item=destination_item,
                            source_items=source_items,
                            destination_items=destination_items,
                            source_base_path=source_base_path,
                            destination_base_path=destination_base_path,
                            source_target=source_target,
                            destination_target=destination_target,
                            destination_type=destination_type,
                            options=options,
                        )
                    )
                continue

            if options.one_way:
                self._plan_one_way(
                    actions,
                    pending_add,
                    pending_delete,
                    rel_path,
                    source_item,
                    destination_item,
                    source_target,
                    destination_target,
                    source_type,
                    destination_type,
                    options,
                    checksum_comparator,
                )
            else:
                self._plan_two_way(
                    actions,
                    rel_path,
                    source_item,
                    destination_item,
                    source_target,
                    destination_target,
                    source_type,
                    destination_type,
                    options,
                    checksum_comparator,
                )

        if options.one_way and options.delete:
            self._apply_rename_detection(
                actions,
                pending_add,
                pending_delete,
                checksum_comparator if options.checksum else None,
            )

        for _, item, target in pending_add:
            actions.append(
                SyncAction(
                    SyncActionType.COPY_TO_DEST,
                    item,
                    target,
                    "目標不存在",
                )
            )

        pending_delete.sort(
            key=lambda entry: len(entry[0].split("/")),
            reverse=True,
        )
        for _, item, target in pending_delete:
            actions.append(
                SyncAction(
                    SyncActionType.DELETE_DEST,
                    item,
                    target,
                    "來源已無此資料夾" if item.is_dir else "來源已無此檔案",
                )
            )

        return SyncPlan.from_actions(actions)

    def _plan_one_way(
        self,
        actions: list[SyncAction],
        pending_add: list[tuple[str, FileItem, str]],
        pending_delete: list[tuple[str, FileItem, str]],
        rel_path: str,
        source_item: FileItem | None,
        destination_item: FileItem | None,
        source_target: str,
        destination_target: str,
        source_type: str,
        destination_type: str,
        options: SyncOptions,
        checksum_comparator: HashComparator | None,
    ) -> None:
        if source_item and not destination_item:
            if source_item.is_dir:
                actions.append(
                    SyncAction(
                        SyncActionType.MKDIR_DEST,
                        source_item,
                        destination_target,
                        "同步空資料夾",
                    )
                )
            elif is_office_file(source_item) and destination_type in MICROSOFT_PROVIDER_TYPES:
                actions.append(
                    SyncAction(
                        SyncActionType.SYNC_OFFICE,
                        source_item,
                        destination_target,
                        "目標不存在 (Office 檔案上傳並回寫)",
                    )
                )
            else:
                pending_add.append((rel_path, source_item, destination_target))
            return

        if not source_item and destination_item and options.delete:
            pending_delete.append((rel_path, destination_item, destination_target))
            return

        if not source_item or not destination_item:
            return
        if source_item.is_dir and destination_item.is_dir:
            return

        office_mode = (
            destination_type in MICROSOFT_PROVIDER_TYPES
            and is_office_file(source_item)
        )

        needs_update, reason = self.compare_items(
            source_item,
            destination_item,
            destination_type=destination_type,
            source_type=source_type,
            options=options,
            checksum_comparator=checksum_comparator,
        )
        if not needs_update:
            return

        self._append_destination_update(
            actions=actions,
            source_item=source_item,
            destination_item=destination_item,
            destination_target=destination_target,
            office_mode=office_mode,
            options=options,
            reason=reason,
            destination_type=destination_type,
        )

    def _plan_two_way(
        self,
        actions: list[SyncAction],
        rel_path: str,
        source_item: FileItem | None,
        destination_item: FileItem | None,
        source_target: str,
        destination_target: str,
        source_type: str,
        destination_type: str,
        options: SyncOptions,
        checksum_comparator: HashComparator | None,
    ) -> None:
        if source_item and not destination_item:
            if source_item.is_dir:
                actions.append(
                    SyncAction(
                        SyncActionType.MKDIR_DEST,
                        source_item,
                        destination_target,
                        "目標不存在，同步資料夾",
                    )
                )
            elif is_office_file(source_item) and destination_type in MICROSOFT_PROVIDER_TYPES:
                actions.append(
                    SyncAction(
                        SyncActionType.SYNC_OFFICE,
                        source_item,
                        destination_target,
                        "目標不存在，從來源拷貝並回寫",
                    )
                )
            else:
                actions.append(
                    SyncAction(
                        SyncActionType.COPY_TO_DEST,
                        source_item,
                        destination_target,
                        "目標不存在，從來源拷貝",
                    )
                )
            return

        if not source_item and destination_item:
            if destination_item.is_dir:
                actions.append(
                    SyncAction(
                        SyncActionType.MKDIR_SRC,
                        destination_item,
                        source_target,
                        "來源不存在，同步資料夾",
                    )
                )
            else:
                actions.append(
                    SyncAction(
                        SyncActionType.COPY_TO_SRC,
                        destination_item,
                        source_target,
                        "來源不存在，從目標拷貝",
                    )
                )
            return

        if not source_item or not destination_item:
            return
        if source_item.is_dir and destination_item.is_dir:
            return

        office_mode = (
            destination_type in MICROSOFT_PROVIDER_TYPES
            and is_office_file(source_item)
        )

        content_differs, content_reason = self.compare_items(
            source_item,
            destination_item,
            destination_type=destination_type,
            source_type=source_type,
            options=options,
            checksum_comparator=checksum_comparator,
        )
        if not content_differs:
            return

        strategy = options.conflict
        if strategy == "abort":
            raise SyncConflictError(
                self._conflict_message(rel_path, source_item, destination_item, content_reason)
            )
        if strategy == "prefer-source":
            self._append_destination_update(
                actions=actions,
                source_item=source_item,
                destination_item=destination_item,
                destination_target=destination_target,
                office_mode=office_mode,
                options=options,
                reason=f"{content_reason or '內容不同'}，依策略使用來源版本",
            )
            return
        if strategy == "prefer-destination":
            self._append_source_update(
                actions=actions,
                source_item=source_item,
                destination_item=destination_item,
                source_target=source_target,
                options=options,
                reason=f"{content_reason or '內容不同'}，依策略使用目標版本",
            )
            return

        newer_side = self._newer_side(source_item, destination_item)
        if newer_side == "destination":
            reason = content_reason or "目標較新"
            self._append_source_update(
                actions=actions,
                source_item=source_item,
                destination_item=destination_item,
                source_target=source_target,
                options=options,
                reason=reason,
            )
            return

        if newer_side == "source":
            reason = content_reason or "來源較新"
            self._append_destination_update(
                actions=actions,
                source_item=source_item,
                destination_item=destination_item,
                destination_target=destination_target,
                office_mode=office_mode,
                options=options,
                reason=reason,
            )
            return

        # Both sides differ, but their mtimes do not establish a safe winner.
        # ``auto`` preserves the destination version before using source as the
        # canonical path.  Explicit ``newer`` refuses to guess.
        if strategy == "newer":
            raise SyncConflictError(
                self._conflict_message(rel_path, source_item, destination_item, content_reason)
            )

        ambiguous_options = options
        if strategy == "auto":
            ambiguous_options = replace(options, conflict="rename")

        reason = f"{content_reason or '內容不同'}，無法安全判定較新版本，已保留衝突版本"

        self._append_destination_update(
            actions=actions,
            source_item=source_item,
            destination_item=destination_item,
            destination_target=destination_target,
            office_mode=office_mode,
            options=ambiguous_options,
            reason=reason,
        )

    def _plan_type_replacement(
        self,
        *,
        actions: list[SyncAction],
        rel_path: str,
        source_item: FileItem,
        destination_item: FileItem,
        destination_items: dict[str, FileItem],
        destination_base_path: str,
        destination_target: str,
        destination_type: str,
        options: SyncOptions,
    ) -> set[str]:
        """Replace a destination item whose file/directory type conflicts with source.

        Type conflicts keep the historical source-precedence behavior, but now perform
        the required delete/backup operation before creating the source-side type.
        """

        consumed: set[str] = set()
        should_preserve = options.conflict == "rename" or (
            options.conflict == "auto" and not options.one_way
        )
        if should_preserve:
            backup_target = _renamed_path(
                destination_target,
                destination_item.modified_at,
            )
            actions.append(
                SyncAction(
                    SyncActionType.RENAME_DEST,
                    destination_item,
                    backup_target,
                    "備份目標型態衝突項目",
                )
            )
            if destination_item.is_dir:
                consumed.update(
                    key
                    for key in destination_items
                    if key.startswith(f"{rel_path}/")
                )
        else:
            if destination_item.is_dir:
                descendants = sorted(
                    (
                        key
                        for key in destination_items
                        if key.startswith(f"{rel_path}/")
                    ),
                    key=lambda key: len(key.split("/")),
                    reverse=True,
                )
                for child_rel in descendants:
                    child = destination_items[child_rel]
                    actions.append(
                        SyncAction(
                            SyncActionType.DELETE_DEST,
                            child,
                            _join_remote_path(destination_base_path, child_rel),
                            "移除型態衝突資料夾內容",
                        )
                    )
                consumed.update(descendants)

            actions.append(
                SyncAction(
                    SyncActionType.DELETE_DEST,
                    destination_item,
                    destination_target,
                    "移除目標型態衝突項目",
                )
            )

        if source_item.is_dir:
            actions.append(
                SyncAction(
                    SyncActionType.MKDIR_DEST,
                    source_item,
                    destination_target,
                    "來源與目標型態不同，建立來源資料夾",
                )
            )
            return consumed

        office_mode = (
            destination_type in MICROSOFT_PROVIDER_TYPES
            and is_office_file(source_item)
        )
        action_type = SyncActionType.SYNC_OFFICE if office_mode else SyncActionType.COPY_TO_DEST
        actions.append(
            SyncAction(
                action_type,
                source_item,
                destination_target,
                "來源與目標型態不同，以來源檔案取代目標",
            )
        )
        return consumed

    def _plan_two_way_type_replacement(
        self,
        *,
        actions: list[SyncAction],
        rel_path: str,
        source_item: FileItem,
        destination_item: FileItem,
        source_items: dict[str, FileItem],
        destination_items: dict[str, FileItem],
        source_base_path: str,
        destination_base_path: str,
        source_target: str,
        destination_target: str,
        destination_type: str,
        options: SyncOptions,
    ) -> set[str]:
        strategy = options.conflict
        newer_side = self._newer_side(source_item, destination_item)

        if strategy == "abort":
            raise SyncConflictError(
                self._conflict_message(rel_path, source_item, destination_item, "型態不同")
            )
        if strategy == "prefer-source":
            return self._plan_type_replacement(
                actions=actions,
                rel_path=rel_path,
                source_item=source_item,
                destination_item=destination_item,
                destination_items=destination_items,
                destination_base_path=destination_base_path,
                destination_target=destination_target,
                destination_type=destination_type,
                options=options,
            )
        if strategy == "prefer-destination":
            return self._plan_source_type_replacement(
                actions=actions,
                rel_path=rel_path,
                source_item=source_item,
                destination_item=destination_item,
                source_items=source_items,
                source_base_path=source_base_path,
                source_target=source_target,
                options=options,
            )
        if strategy == "newer" and newer_side is None:
            raise SyncConflictError(
                self._conflict_message(rel_path, source_item, destination_item, "型態不同")
            )

        # Type replacements are inherently destructive.  In ``auto`` mode we
        # always preserve the losing side before replacing it, even when mtime
        # establishes a winner.
        safe_options = replace(options, conflict="rename") if strategy == "auto" else options
        if newer_side == "destination":
            return self._plan_source_type_replacement(
                actions=actions,
                rel_path=rel_path,
                source_item=source_item,
                destination_item=destination_item,
                source_items=source_items,
                source_base_path=source_base_path,
                source_target=source_target,
                options=safe_options,
            )

        return self._plan_type_replacement(
            actions=actions,
            rel_path=rel_path,
            source_item=source_item,
            destination_item=destination_item,
            destination_items=destination_items,
            destination_base_path=destination_base_path,
            destination_target=destination_target,
            destination_type=destination_type,
            options=safe_options,
        )

    def _plan_source_type_replacement(
        self,
        *,
        actions: list[SyncAction],
        rel_path: str,
        source_item: FileItem,
        destination_item: FileItem,
        source_items: dict[str, FileItem],
        source_base_path: str,
        source_target: str,
        options: SyncOptions,
    ) -> set[str]:
        """Replace a source-side type conflict with the destination-side item."""

        consumed: set[str] = set()
        if options.conflict == "rename":
            backup_target = _renamed_path(source_target, source_item.modified_at)
            actions.append(
                SyncAction(
                    SyncActionType.RENAME_SRC,
                    source_item,
                    backup_target,
                    "備份來源型態衝突項目",
                )
            )
            if source_item.is_dir:
                consumed.update(
                    key for key in source_items if key.startswith(f"{rel_path}/")
                )
        else:
            if source_item.is_dir:
                descendants = sorted(
                    (
                        key
                        for key in source_items
                        if key.startswith(f"{rel_path}/")
                    ),
                    key=lambda key: len(key.split("/")),
                    reverse=True,
                )
                for child_rel in descendants:
                    child = source_items[child_rel]
                    actions.append(
                        SyncAction(
                            SyncActionType.DELETE_SRC,
                            child,
                            _join_remote_path(source_base_path, child_rel),
                            "移除來源型態衝突資料夾內容",
                        )
                    )
                consumed.update(descendants)

            actions.append(
                SyncAction(
                    SyncActionType.DELETE_SRC,
                    source_item,
                    source_target,
                    "移除來源型態衝突項目",
                )
            )

        if destination_item.is_dir:
            actions.append(
                SyncAction(
                    SyncActionType.MKDIR_SRC,
                    destination_item,
                    source_target,
                    "來源與目標型態不同，建立目標端資料夾型態",
                )
            )
        else:
            actions.append(
                SyncAction(
                    SyncActionType.COPY_TO_SRC,
                    destination_item,
                    source_target,
                    "來源與目標型態不同，以目標檔案取代來源",
                )
            )
        return consumed

    def _append_destination_update(
        self,
        *,
        actions: list[SyncAction],
        source_item: FileItem,
        destination_item: FileItem,
        destination_target: str,
        office_mode: bool,
        options: SyncOptions,
        reason: str,
        destination_type: str = "",
    ) -> None:
        if destination_type == "googlephotos":
            target = destination_target
            if options.conflict == "rename":
                target = _renamed_path(destination_target, source_item.modified_at)
                reason_desc = f"建立新衝突項目 ({reason})"
            else:
                reason_desc = f"更新 ({reason})"
            actions.append(
                SyncAction(
                    SyncActionType.COPY_TO_DEST,
                    source_item,
                    target,
                    reason_desc,
                )
            )
            return

        if options.conflict == "rename":
            backup_target = _renamed_path(
                destination_target,
                destination_item.modified_at,
            )
            actions.append(
                SyncAction(
                    SyncActionType.RENAME_DEST,
                    destination_item,
                    backup_target,
                    f"備份目標舊版本 ({reason})",
                )
            )

        action_type = SyncActionType.SYNC_OFFICE if office_mode else SyncActionType.COPY_TO_DEST
        action_reason = (
            f"更新並回寫 ({reason})"
            if office_mode
            else f"更新 ({reason})"
        )
        actions.append(
            SyncAction(
                action_type,
                source_item,
                destination_target,
                action_reason,
            )
        )

    @staticmethod
    def _conflict_message(
        rel_path: str,
        source_item: FileItem,
        destination_item: FileItem,
        reason: str,
    ) -> str:
        source_time = source_item.modified_at.isoformat() if source_item.modified_at else "未知"
        destination_time = (
            destination_item.modified_at.isoformat()
            if destination_item.modified_at
            else "未知"
        )
        return (
            f"無法安全解決雙向同步衝突: {rel_path} ({reason or '內容不同'})。"
            f"來源修改時間={source_time}，目標修改時間={destination_time}。"
            "請使用 --conflict rename、--conflict prefer-source 或 "
            "--conflict prefer-destination 明確指定處理方式。"
        )

    def _append_source_update(
        self,
        *,
        actions: list[SyncAction],
        source_item: FileItem,
        destination_item: FileItem,
        source_target: str,
        options: SyncOptions,
        reason: str,
    ) -> None:
        if options.conflict == "rename":
            backup_target = _renamed_path(
                source_target,
                source_item.modified_at,
            )
            actions.append(
                SyncAction(
                    SyncActionType.RENAME_SRC,
                    source_item,
                    backup_target,
                    f"備份來源舊版本 ({reason})",
                )
            )

        actions.append(
            SyncAction(
                SyncActionType.COPY_TO_SRC,
                destination_item,
                source_target,
                f"更新來源 ({reason})",
            )
        )

    def _content_differs_two_way(
        self,
        source_item: FileItem,
        destination_item: FileItem,
        *,
        office_mode: bool,
        photos_mode: bool = False,
        checksum_enabled: bool,
        checksum_comparator: HashComparator | None,
    ) -> tuple[bool, str]:
        if photos_mode:
            if source_item.modified_at and destination_item.modified_at:
                diff_seconds = abs(
                    (
                        source_item.modified_at
                        - destination_item.modified_at
                    ).total_seconds()
                )
                if diff_seconds > MTIME_TOLERANCE_SECONDS:
                    return True, "修改時間不同"
                return False, ""
            return False, ""

        # For ordinary files, a size mismatch is already conclusive and avoids
        # unnecessary remote hash calls. Office providers are exempt because
        # server-side processing can legitimately change the binary size.
        if not office_mode and source_item.size != destination_item.size:
            return True, "大小不同"

        if source_item.remote_hash and destination_item.remote_hash:
            if source_item.remote_hash != destination_item.remote_hash:
                return True, "遠端雜湊不符"
            return False, ""

        if checksum_enabled and checksum_comparator:
            try:
                different, reason = checksum_comparator(
                    source_item,
                    destination_item,
                )
                if different:
                    return True, reason or "Checksum 不符"
                return False, ""
            except Exception as exc:
                return True, f"內容狀態未知 (Checksum計算失敗: {exc})"

        if source_item.modified_at and destination_item.modified_at:
            diff_seconds = abs(
                (
                    source_item.modified_at
                    - destination_item.modified_at
                ).total_seconds()
            )
            if diff_seconds > MTIME_TOLERANCE_SECONDS:
                return True, "修改時間不同"

            if office_mode:
                # Office providers can change binary size during server-side processing.
                return False, ""

        if source_item.size != destination_item.size:
            return True, "大小不同"

        return False, ""

    @staticmethod
    def _newer_side(
        source_item: FileItem,
        destination_item: FileItem,
    ) -> str | None:
        if not source_item.modified_at or not destination_item.modified_at:
            return None

        diff_seconds = (
            source_item.modified_at
            - destination_item.modified_at
        ).total_seconds()
        if diff_seconds > MTIME_TOLERANCE_SECONDS:
            return "source"
        if diff_seconds < -MTIME_TOLERANCE_SECONDS:
            return "destination"
        return None

    def _compare_items(
        self,
        source_item: FileItem,
        destination_item: FileItem,
        *,
        office_mode: bool,
        photos_mode: bool = False,
        checksum_enabled: bool,
        checksum_comparator: HashComparator | None,
    ) -> tuple[bool, str]:
        if photos_mode:
            if source_item.modified_at and destination_item.modified_at:
                diff_seconds = (
                    source_item.modified_at
                    - destination_item.modified_at
                ).total_seconds()
                if diff_seconds > MTIME_TOLERANCE_SECONDS:
                    return True, "來源檔案較新"
                return False, ""
            return False, ""

        if office_mode:
            if source_item.modified_at and destination_item.modified_at:
                diff_seconds = (
                    source_item.modified_at
                    - destination_item.modified_at
                ).total_seconds()
                if diff_seconds > MTIME_TOLERANCE_SECONDS:
                    return True, "來源檔案較新 (略過 Office 大小比對)"
                return False, ""
            if source_item.size != destination_item.size:
                return True, "大小不同 (無法比對時間)"
            return False, ""

        if source_item.size != destination_item.size:
            return True, "大小不同"

        if source_item.remote_hash and destination_item.remote_hash:
            if source_item.remote_hash != destination_item.remote_hash:
                return True, "遠端雜湊不符"
            return False, ""

        if checksum_enabled and checksum_comparator:
            try:
                different, reason = checksum_comparator(source_item, destination_item)
                if different:
                    return True, reason
            except Exception as exc:
                return True, f"內容狀態未知 (Checksum計算失敗: {exc})"

        if source_item.modified_at and destination_item.modified_at:
            if source_item.modified_at > destination_item.modified_at:
                return True, "來源檔案較新"

        return False, ""

    def _apply_rename_detection(
        self,
        actions: list[SyncAction],
        pending_add: list[tuple[str, FileItem, str]],
        pending_delete: list[tuple[str, FileItem, str]],
        checksum_comparator: HashComparator | None,
    ) -> None:
        """Detect renames only when content identity can be verified by checksum."""

        if checksum_comparator is None:
            return

        unmatched_adds = list(pending_add)
        unmatched_deletes = list(pending_delete)

        for add_entry in list(unmatched_adds):
            rel_path, item, target = add_entry
            if item.is_dir:
                continue

            identical_candidates: list[tuple[str, FileItem, str]] = []
            for delete_entry in unmatched_deletes:
                old_rel, old_item, _ = delete_entry
                if old_item.is_dir or old_item.size != item.size:
                    continue
                try:
                    different, _ = checksum_comparator(item, old_item)
                except Exception:
                    continue
                if not different:
                    identical_candidates.append(delete_entry)

            if len(identical_candidates) != 1:
                continue

            old_rel, old_item, _ = identical_candidates[0]
            actions.append(
                SyncAction(
                    SyncActionType.RENAME_DEST,
                    old_item,
                    target,
                    f"Checksum 驗證後重新命名自 {old_rel}",
                )
            )
            unmatched_adds.remove(add_entry)
            unmatched_deletes.remove(identical_candidates[0])

        pending_add[:] = unmatched_adds
        pending_delete[:] = unmatched_deletes
