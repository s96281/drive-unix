"""Synchronization and checksum CLI commands."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime
import json
import os
import sys
import tempfile

import typer

from application.sync_service import SyncService
from cli.context import CLIContext
from cli.presentation import echo, render_error, render_warning, secho
from cli.formatting import format_size, format_time
from cli.sync_ui import (
    clear_scan_progress,
    execute_sync_plan,
    render_delete_risks,
    render_plan,
    scan_progress,
    summarize_plan,
)
from core.constants import DEFAULT_SCAN_THROTTLE_SECONDS, DEFAULT_WORKERS
from core.factory import get_storage_provider, parse_remote_path
from core.hashing import calculate_local_hash
from domain.sync.models import SyncOptions
from domain.errors import SyncConflictError
from domain.sync.planner import SyncPlanner
from domain.sync.scanner import get_all_files_recursive
from storage.base import managed_storage

def _sync_impl(
    source: str = typer.Argument(..., help="來源路徑 (例如: src_sp:/docs)"),
    dest: str = typer.Argument(..., help="目標路徑 (例如: dest_sp:/backup)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="僅顯示將要執行的操作，不實際改動檔案"),
    one_way: bool = typer.Option(
        True,
        "--one-way/--two-way",
        help="同步模式：--one-way 為來源 -> 目標（預設），--two-way 為雙向同步",
    ),
    delete: bool = typer.Option(False, "--delete", help="刪除目標端存在，但來源端不存在的檔案與資料夾"),
    exclude_pattern: str = typer.Option(None, "--exclude", help="排除符合模式的檔案 (例如 *.tmp)"),
    include_pattern: str = typer.Option(None, "--include", help="僅包含符合模式的檔案 (例如 *.pdf)"),
    conflict: str = typer.Option(
        "auto",
        "--conflict",
        help="衝突策略: auto, newer, rename, abort, prefer-source, prefer-destination",
    ),
    checksum: bool = typer.Option(False, "--checksum", help="使用雜湊值比對"),
    progress: bool = typer.Option(False, "--progress", help="顯示整體同步進度"),
    workers: int = typer.Option(DEFAULT_WORKERS, "--workers", "-w", help=f"併發執行緒數量 (預設為 {DEFAULT_WORKERS})"),
    yes: bool = typer.Option(False, "--yes", "-y", help="自動同意所有操作"),
    throttle: float = typer.Option(0.0, "--throttle", help="操作間的強制延遲秒數"),
    full_plan: bool = typer.Option(False, "--full-plan", help="顯示同步計畫中的每一個操作"),
    json_output: bool = typer.Option(False, "--json", help="輸出 JSON 結果；實際執行時需搭配 --yes"),
) -> None:
    """建立並執行同步計畫。"""
    config_manager = CLIContext.create().config
    storage_stack = ExitStack()
    try:
        options = SyncOptions(
            one_way=one_way,
            delete=delete,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
            conflict=conflict,
            checksum=checksum,
        )
        options.validate()
        if workers < 1:
            raise ValueError("workers 必須大於等於 1")
        if throttle < 0:
            raise ValueError("throttle 不可小於 0")

        src_remote, src_path = parse_remote_path(source, config_manager.config.default_remote)
        dst_remote, dst_path = parse_remote_path(dest, config_manager.config.default_remote)
        src_storage = storage_stack.enter_context(
            managed_storage(get_storage_provider(src_remote, config_manager))
        )
        dst_storage = (
            src_storage
            if src_remote == dst_remote
            else storage_stack.enter_context(
                managed_storage(get_storage_provider(dst_remote, config_manager))
            )
        )
        src_type = config_manager.get_remote(src_remote).type
        dst_type = config_manager.get_remote(dst_remote).type

        if not one_way and (src_type == "googlephotos" or dst_type == "googlephotos"):
            secho("⚠️ Google Photos 不支援雙向同步 (bisync)，以避免版本污染與衝突複本。", fg=typer.colors.RED)
            echo("提示：請改用單向同步 `drive-unix sync --one-way`。")
            raise typer.Exit(code=2)

        mode = "單向" if one_way else "雙向"
        connector = "→" if one_way else "↔"
        if json_output and not dry_run and not yes:
            raise ValueError("--json 的實際同步必須搭配 --yes，避免腳本停在互動確認。")

        if not json_output:
            secho(
                f"🔄 開始準備{mode}同步計畫: [{src_remote}]{src_path} {connector} "
                f"[{dst_remote}]{dst_path}",
                fg=typer.colors.CYAN,
                bold=True,
            )
        if dry_run and not json_output:
            secho(
                "🧪 [DRY RUN 模式] 以下操作僅為模擬，不會修改任何檔案",
                fg=typer.colors.YELLOW,
                bold=True,
            )

        service = SyncService(
            source_remote=src_remote,
            source_storage=src_storage,
            source_type=src_type,
            destination_remote=dst_remote,
            destination_storage=dst_storage,
            destination_type=dst_type,
            source_path=src_path,
            destination_path=dst_path,
        )
        source_snapshot, destination_snapshot = service.scan(
            strict=True,
            source_throttle=0.0 if src_type == "local" else DEFAULT_SCAN_THROTTLE_SECONDS,
            destination_throttle=0.0 if dst_type == "local" else DEFAULT_SCAN_THROTTLE_SECONDS,
            scan_workers=max(1, min(workers, 4)),
            on_source_progress=None if json_output else scan_progress("來源"),
            on_destination_progress=None if json_output else scan_progress("目標"),
        )
        if not json_output:
            clear_scan_progress()
        plan = service.build_plan(
            source_snapshot=source_snapshot,
            destination_snapshot=destination_snapshot,
            options=options,
        )
        if plan.is_empty:
            if json_output:
                echo(json.dumps({"status": "noop", "operations": 0}, ensure_ascii=False))
            else:
                secho("✅ 兩端已完全同步，無須任何操作。", fg=typer.colors.GREEN, bold=True)
            return

        summary = summarize_plan(plan)
        irreversible_deletes = 0
        if summary.delete_source and src_storage.delete_capability.value == "permanent_only":
            irreversible_deletes += summary.delete_source
        if summary.delete_destination and dst_storage.delete_capability.value == "permanent_only":
            irreversible_deletes += summary.delete_destination

        if not json_output:
            render_plan(plan, full_plan=full_plan)
            irreversible_deletes = render_delete_risks(
                plan,
                source_storage=src_storage,
                destination_storage=dst_storage,
            )
        if dry_run:
            if json_output:
                echo(
                    json.dumps(
                        {
                            "status": "dry-run",
                            "mode": "one-way" if one_way else "two-way",
                            "operations": plan.count,
                            "transfers": summary.transfers,
                            "directories": summary.directories,
                            "renames": summary.renames,
                            "deletes": summary.deletes,
                            "irreversible_deletes": irreversible_deletes,
                            "transfer_bytes": summary.transfer_bytes,
                            "delete_bytes": summary.delete_bytes,
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                secho("🛑 Dry run 結束。若要執行，請移除 --dry-run。", fg=typer.colors.YELLOW)
            return

        if not yes:
            prompt = "確定要執行上述同步計畫嗎？"
            if irreversible_deletes:
                prompt = (
                    f"上述計畫包含 {irreversible_deletes} 個永久刪除操作。確定要執行嗎？"
                )
            if not typer.confirm(prompt):
                raise typer.Abort()

        if json_output:
            result = service.execute(
                plan,
                workers=workers,
                throttle=throttle,
            )
        else:
            result = execute_sync_plan(
                service,
                plan,
                workers=workers,
                throttle=throttle,
                detailed_progress=progress,
            )
        if json_output:
            echo(
                json.dumps(
                    {
                        "status": "ok" if result.success else "partial-failure",
                        "operations": plan.count,
                        "succeeded": result.succeeded,
                        "failed": result.failed,
                        "skipped": result.skipped,
                        "errors": [
                            {"path": action.item.path, "error": str(error)}
                            for action, error in result.errors
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            if not result.success:
                raise typer.Exit(code=1)
            return

        if result.success:
            secho(
                f"\n🎉 同步完成！成功 {result.succeeded} 個操作。",
                fg=typer.colors.GREEN,
                bold=True,
            )
            return

        render_error(
            "同步未完整完成。",
            cause=(
                f"{result.failed} 個操作失敗；成功 {result.succeeded} 個，"
                f"略過 {result.skipped} 個。"
            ),
            next_steps=(
                "檢查下方失敗項目後修正權限、網路或路徑問題。",
                "先使用 `--dry-run` 重新確認計畫，再重試同步。",
            ),
        )
        for action, error in result.errors:
            secho(f"  - {action.item.name}: {error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except typer.Abort:
        if json_output:
            echo(json.dumps({"status": "aborted"}, ensure_ascii=False))
        else:
            secho("🛑 已取消同步操作。", fg=typer.colors.YELLOW)
    except typer.Exit:
        raise
    except SyncConflictError as exc:
        if json_output:
            echo(
                json.dumps(
                    {"status": "conflict", "error": str(exc)},
                    ensure_ascii=False,
                )
            )
        else:
            render_warning(
                "同步計畫因無法安全解決的衝突而停止。",
                next_steps=(
                    "使用 `--conflict rename` 保留兩份版本（較安全）。",
                    "或明確指定 `prefer-source` / `prefer-destination` 後重新執行。",
                ),
            )
            echo(f"原因：{exc}")
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        if json_output:
            echo(
                json.dumps(
                    {"status": "error", "error": str(exc)},
                    ensure_ascii=False,
                )
            )
        else:
            render_error(
                "同步失敗。",
                cause=exc,
                next_steps=(
                    "確認來源與目標 Remote 的認證、路徑與讀寫權限。",
                    "使用 `--dry-run` 檢查同步計畫；必要時執行 `drive-unix remote test NAME`。",
                ),
            )
        raise typer.Exit(code=1) from exc
    finally:
        storage_stack.__exit__(*sys.exc_info())


def sync_items(
    source: str = typer.Argument(..., help="來源路徑 (例如: src_sp:/docs)"),
    dest: str = typer.Argument(..., help="目標路徑 (例如: dest_sp:/backup)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="僅顯示將要執行的操作，不實際改動檔案"),
    one_way: bool = typer.Option(
        True,
        "--one-way/--two-way",
        help="同步模式：--one-way 為來源 -> 目標（預設），--two-way 為雙向同步",
    ),
    delete: bool = typer.Option(False, "--delete", help="刪除目標端存在，但來源端不存在的檔案與資料夾"),
    exclude_pattern: str = typer.Option(None, "--exclude", help="排除符合模式的檔案 (例如 *.tmp)"),
    include_pattern: str = typer.Option(None, "--include", help="僅包含符合模式的檔案 (例如 *.pdf)"),
    conflict: str = typer.Option(
        "auto",
        "--conflict",
        help="衝突策略: auto, newer, rename, abort, prefer-source, prefer-destination",
    ),
    checksum: bool = typer.Option(False, "--checksum", help="使用雜湊值比對"),
    progress: bool = typer.Option(False, "--progress", help="顯示整體同步進度"),
    workers: int = typer.Option(DEFAULT_WORKERS, "--workers", "-w", help=f"併發執行緒數量 (預設為 {DEFAULT_WORKERS})"),
    yes: bool = typer.Option(False, "--yes", "-y", help="自動同意所有操作"),
    throttle: float = typer.Option(0.0, "--throttle", help="操作間的強制延遲秒數"),
    full_plan: bool = typer.Option(False, "--full-plan", help="顯示同步計畫中的每一個操作"),
    json_output: bool = typer.Option(False, "--json", help="輸出 JSON 結果；實際執行時需搭配 --yes"),
) -> None:
    """建立並執行同步計畫。"""

    _sync_impl(
        source=source,
        dest=dest,
        dry_run=dry_run,
        one_way=one_way,
        delete=delete,
        exclude_pattern=exclude_pattern,
        include_pattern=include_pattern,
        conflict=conflict,
        checksum=checksum,
        progress=progress,
        workers=workers,
        yes=yes,
        throttle=throttle,
        full_plan=full_plan,
        json_output=json_output,
    )


def bisync_items(
    source: str = typer.Argument(..., help="左側路徑 (例如: laptop:/docs)"),
    dest: str = typer.Argument(..., help="右側路徑 (例如: cloud:/docs)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="僅顯示將要執行的操作，不實際改動檔案"),
    exclude_pattern: str = typer.Option(None, "--exclude", help="排除符合模式的檔案 (例如 *.tmp)"),
    include_pattern: str = typer.Option(None, "--include", help="僅包含符合模式的檔案 (例如 *.pdf)"),
    conflict: str = typer.Option(
        "auto",
        "--conflict",
        help="衝突策略: auto, newer, rename, abort, prefer-source, prefer-destination",
    ),
    checksum: bool = typer.Option(False, "--checksum", help="使用雜湊值比對"),
    progress: bool = typer.Option(False, "--progress", help="顯示整體同步進度"),
    workers: int = typer.Option(DEFAULT_WORKERS, "--workers", "-w", help=f"併發執行緒數量 (預設為 {DEFAULT_WORKERS})"),
    yes: bool = typer.Option(False, "--yes", "-y", help="自動同意所有操作"),
    throttle: float = typer.Option(0.0, "--throttle", help="操作間的強制延遲秒數"),
    full_plan: bool = typer.Option(False, "--full-plan", help="顯示同步計畫中的每一個操作"),
    json_output: bool = typer.Option(False, "--json", help="輸出 JSON 結果；實際執行時需搭配 --yes"),
) -> None:
    """雙向同步兩個位置；無法判定新舊時預設保留衝突版本。"""

    sync_items(
        source=source,
        dest=dest,
        dry_run=dry_run,
        one_way=False,
        delete=False,
        exclude_pattern=exclude_pattern,
        include_pattern=include_pattern,
        conflict=conflict,
        checksum=checksum,
        progress=progress,
        workers=workers,
        yes=yes,
        throttle=throttle,
        full_plan=full_plan,
        json_output=json_output,
    )

def diff_items(
    source: str = typer.Argument(..., help="來源路徑 (例如: my_sp:/docs)"),
    dest: str = typer.Argument(..., help="目標路徑 (例如: my_sp:/backup)"),
    show_same: bool = typer.Option(False, "--show-same", "-s", help="顯示完全相同的檔案 (預設隱藏以保持版面乾淨)"),
    checksum: bool = typer.Option(False, "--checksum", help="使用與 sync 相同的 Checksum comparison policy"),
    json_output: bool = typer.Option(False, "--json", help="輸出穩定 JSON，適合腳本使用"),
):
    """比較兩個位置的目錄與檔案差異。"""
    ctx = CLIContext.create()
    config_manager = ctx.config
    storage_stack = ExitStack()
    try:
        src_remote, src_path = parse_remote_path(source, config_manager.config.default_remote)
        dst_remote, dst_path = parse_remote_path(dest, config_manager.config.default_remote)

        src_storage = storage_stack.enter_context(
            managed_storage(get_storage_provider(src_remote, config_manager))
        )
        dst_storage = (
            src_storage
            if src_remote == dst_remote
            else storage_stack.enter_context(
                managed_storage(get_storage_provider(dst_remote, config_manager))
            )
        )
        src_type = config_manager.get_remote(src_remote).type
        dst_type = config_manager.get_remote(dst_remote).type

        if not json_output:
            secho(
                f"🔍 正在比較: [{src_remote}]{src_path} <--> [{dst_remote}]{dst_path}",
                fg=typer.colors.CYAN,
                bold=True,
            )

        if not json_output:
            echo("📊 正在掃描來源端結構...")
        src_files = get_all_files_recursive(src_storage, src_path)
        if not json_output:
            echo("📊 正在掃描目標端結構...")
        dst_files = get_all_files_recursive(dst_storage, dst_path)

        planner = SyncPlanner()
        options = SyncOptions(one_way=False, checksum=checksum)
        service = SyncService(
            source_remote=src_remote,
            source_storage=src_storage,
            source_type=src_type,
            destination_remote=dst_remote,
            destination_storage=dst_storage,
            destination_type=dst_type,
            source_path=src_path,
            destination_path=dst_path,
            planner=planner,
        )

        checksum_comparator = None
        if (
            checksum
            and src_type in SyncService.CHECKSUM_SUPPORTED_TYPES
            and dst_type in SyncService.CHECKSUM_SUPPORTED_TYPES
        ):
            checksum_executor = storage_stack.enter_context(
                ThreadPoolExecutor(max_workers=2)
            )

            def compare_with_parallel_hashes(source_item, destination_item):
                return service.compare_checksums(
                    source_item,
                    destination_item,
                    executor=checksum_executor,
                )

            checksum_comparator = compare_with_parallel_hashes

        only_in_src: list[str] = []
        only_in_dst: list[str] = []
        diff_size: list[tuple[str, int, int]] = []
        diff_time: list[tuple[str, datetime | None, datetime | None]] = []
        diff_other: list[tuple[str, str]] = []
        same: list[str] = []

        all_keys = set(src_files) | set(dst_files)

        for key in sorted(all_keys):
            if key not in dst_files:
                only_in_src.append(key)
                continue
            if key not in src_files:
                only_in_dst.append(key)
                continue

            src_item = src_files[key]
            dst_item = dst_files[key]
            different, reason = planner.compare_items(
                src_item,
                dst_item,
                destination_type=dst_type,
                options=options,
                checksum_comparator=checksum_comparator,
            )
            if not different:
                same.append(key)
                continue

            if reason.startswith("大小不同"):
                diff_size.append((key, src_item.size, dst_item.size))
            elif reason == "修改時間不同":
                diff_time.append((key, src_item.modified_at, dst_item.modified_at))
            else:
                diff_other.append((key, reason or "內容不同"))

        if json_output:
            echo(
                json.dumps(
                    {
                        "source_total": len(src_files),
                        "destination_total": len(dst_files),
                        "only_in_source": only_in_src,
                        "only_in_destination": only_in_dst,
                        "different_size": [
                            {"path": path, "source_size": s, "destination_size": d}
                            for path, s, d in diff_size
                        ],
                        "different_modified_time": [
                            {
                                "path": path,
                                "source_modified": s.isoformat() if s else None,
                                "destination_modified": d.isoformat() if d else None,
                            }
                            for path, s, d in diff_time
                        ],
                        "other_differences": [
                            {"path": path, "reason": reason} for path, reason in diff_other
                        ],
                        "same": same if show_same else [],
                    },
                    ensure_ascii=False,
                )
            )
            return

        echo("\n" + "=" * 60)

        if only_in_src:
            secho(
                f"📦 僅存在來源端 ({len(only_in_src)}):",
                fg=typer.colors.GREEN,
                bold=True,
            )
            for item in only_in_src:
                secho(f"  + {item}", fg=typer.colors.GREEN)

        if only_in_dst:
            secho(
                f"\n🗑️ 僅存在目標端 ({len(only_in_dst)}):",
                fg=typer.colors.RED,
                bold=True,
            )
            for item in only_in_dst:
                secho(f"  - {item}", fg=typer.colors.RED)

        if diff_size:
            secho(
                f"\n📏 大小不同 ({len(diff_size)}):",
                fg=typer.colors.YELLOW,
                bold=True,
            )
            for item, s_size, d_size in diff_size:
                secho(
                    f"  ~ {item} (來源: {format_size(s_size)} -> 目標: {format_size(d_size)})",
                    fg=typer.colors.YELLOW,
                )

        if diff_time:
            secho(
                f"\n⏱️ 修改時間不同 ({len(diff_time)}):",
                fg=typer.colors.BLUE,
                bold=True,
            )
            for item, s_time, d_time in diff_time:
                s_time_str = format_time(s_time.isoformat()) if s_time else "N/A"
                d_time_str = format_time(d_time.isoformat()) if d_time else "N/A"
                secho(
                    f"  ~ {item} (來源: {s_time_str} != 目標: {d_time_str})",
                    fg=typer.colors.BLUE,
                )

        if diff_other:
            secho(
                f"\n⚠️ 其他差異 ({len(diff_other)}):",
                fg=typer.colors.MAGENTA,
                bold=True,
            )
            for item, reason in diff_other:
                secho(f"  ~ {item} ({reason})", fg=typer.colors.MAGENTA)

        if show_same and same:
            secho(
                f"\n✅ 相同 ({len(same)}):",
                fg=typer.colors.WHITE,
                bold=True,
            )
            for item in same:
                echo(f"  = {item}")

        echo("=" * 60)
        secho("📊 差異摘要：", fg=typer.colors.CYAN, bold=True)
        echo(f"  來源端總數 : {len(src_files)}")
        echo(f"  目標端總數 : {len(dst_files)}")
        echo("-" * 60)
        echo(f"  僅存在來源端 : {len(only_in_src)}")
        echo(f"  僅存在目標端 : {len(only_in_dst)}")
        echo(f"  大小不同     : {len(diff_size)}")
        echo(f"  修改時間不同 : {len(diff_time)}")
        echo(f"  其他差異     : {len(diff_other)}")
        echo(f"  相同         : {len(same)}")
        echo("=" * 60)

    except Exception as exc:
        if json_output:
            echo(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            render_error(
                "比較失敗。",
                cause=exc,
                next_steps=(
                    "確認兩端 Remote 路徑與讀取權限。",
                    "若使用 `--checksum`，請確認 Provider 支援雜湊比較或改用一般比較。",
                ),
            )
        raise typer.Exit(code=1) from exc
    finally:
        storage_stack.__exit__(*sys.exc_info())

def get_checksum(
    remote_path: str = typer.Argument(..., help="遠端檔案路徑 (例如: my_sp:/docs/A.pdf)"),
    algo: str = typer.Option("sha256", "--algo", help="雜湊演算法: md5, sha1, sha256, quickXorHash"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="Checksum 模式: auto（預設，自動 fallback）, remote, download",
    ),
    remote: bool = typer.Option(False, "--remote", help="相容舊版：等同 --mode remote"),
    download: bool = typer.Option(False, "--download", help="相容舊版：等同 --mode download"),
):
    """
    取得或計算檔案的雜湊值 (Checksum)
    """
    if remote and download:
        raise typer.BadParameter("--remote 與 --download 不可同時使用；請改用 --mode。")
    if remote:
        mode = "remote"
    if download:
        mode = "download"
    mode = mode.lower().strip()
    if mode not in {"auto", "remote", "download"}:
        raise typer.BadParameter("--mode 必須是 auto、remote 或 download。")

    ctx = CLIContext.create()
    config_manager = ctx.config
    storage_stack = ExitStack()
    try:
        remote_name, parsed_remote_path = parse_remote_path(remote_path, config_manager.config.default_remote)
        storage = storage_stack.enter_context(
            managed_storage(get_storage_provider(remote_name, config_manager))
        )
        
        algo_display = algo.upper() if algo.lower() != 'quickxorhash' else 'quickXorHash'
        
        # Remote / Auto：先嘗試直接向 Provider 取得 hash。
        if mode in {"auto", "remote"}:
            echo(f"🌐 正在向 [{remote_name}] 伺服器請求 {algo_display} 值...")
            try:
                hash_value = storage.get_hash(parsed_remote_path, algo)
                echo("-" * 50)
                secho(f"{hash_value}  {parsed_remote_path}", fg=typer.colors.GREEN, bold=True)
                return
            except (ValueError, NotImplementedError) as e:
                if mode == "remote":
                    secho(f"⚠️ Provider 無法直接提供 {algo_display}: {e}", fg=typer.colors.YELLOW)
                    echo("下一步：改用 `--mode download`，或使用預設 `--mode auto` 自動 fallback。")
                    raise typer.Exit(code=2)
                secho(
                    f"ℹ️ Provider 無法直接提供 {algo_display}，改為下載後本機計算。",
                    fg=typer.colors.YELLOW,
                )

        # Download / Auto fallback：下載後本機計算。
        if mode in {"auto", "download"}:
            echo(f"📥 啟動本機計算模式，正在將檔案下載至暫存區...")
            with tempfile.TemporaryDirectory() as temp_dir:
                filename = parsed_remote_path.strip("/").split("/")[-1]
                temp_file_path = os.path.join(temp_dir, filename)
                
                # 呼叫已經寫好的下載功能
                storage.download(parsed_remote_path, temp_file_path)
                
                echo(f"⚙️ 下載完成，正在計算 {algo_display}...")
                hash_value = calculate_local_hash(temp_file_path, algo)
                
                echo("-" * 50)
                secho(f"{hash_value}  {parsed_remote_path}", fg=typer.colors.GREEN, bold=True)
                
    except typer.Exit:
        raise
    except Exception as exc:
        render_error(
            "無法取得 Checksum。",
            cause=exc,
            next_steps=(
                "確認檔案路徑與 Provider 讀取權限。",
                "確認 `--algo` 為 md5、sha1、sha256 或 quickXorHash。",
                "若遠端不提供 hash，可使用 `--mode auto` 或 `--mode download`。",
            ),
        )
        raise typer.Exit(code=1) from exc
    finally:
        storage_stack.__exit__(*sys.exc_info())

def register(app: typer.Typer) -> None:
    app.command("sync")(sync_items)
    app.command("bisync")(bisync_items)
    app.command("diff")(diff_items)
    app.command("checksum")(get_checksum)
