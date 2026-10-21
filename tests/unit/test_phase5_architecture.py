from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

import application.transfer_service as transfer_module
from application.sync_service import SyncExecutor
from application.transfer_service import TransferOperationError, TransferService
from providers.local import LocalStorage
from storage.base import ProgressCallback, StorageProvider, StorageStat

ROOT = Path(__file__).resolve().parents[2]


def _python_tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_application_layer_does_not_import_cli() -> None:
    offenders: list[str] = []
    for path in (ROOT / "application").glob("*.py"):
        for node in ast.walk(_python_tree(path)):
            if isinstance(node, ast.Import):
                if any(alias.name == "cli" or alias.name.startswith("cli.") for alias in node.names):
                    offenders.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "cli" or node.module.startswith("cli.")):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_provider_layer_has_no_direct_print_calls() -> None:
    offenders: list[str] = []
    for directory in (ROOT / "providers", ROOT / "auth" / "providers"):
        for path in directory.rglob("*.py"):
            for node in ast.walk(_python_tree(path)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_storage_contract_type_hints_are_reused_by_application_and_provider() -> None:
    provider_upload = get_type_hints(LocalStorage.upload)
    provider_stat = get_type_hints(LocalStorage.stat)
    executor = get_type_hints(SyncExecutor.execute)
    transfer_upload = get_type_hints(TransferService.call_upload)

    assert provider_upload["callback"] == ProgressCallback | None
    assert provider_stat["return"] is StorageStat
    assert executor["source_storage"] is StorageProvider
    assert executor["destination_storage"] is StorageProvider
    assert transfer_upload["storage"] is StorageProvider
    assert transfer_upload["callback"] == ProgressCallback | None


def test_phase2_transfer_compatibility_wrappers_are_removed() -> None:
    for name in ("_call_upload", "_call_download", "_execute_copy"):
        assert not hasattr(transfer_module, name)


def test_phase5_cli_hotspots_are_decomposed() -> None:
    from cli.commands.sync import sync_items
    from cli.commands.transfer import download, upload

    def line_count(function) -> int:
        lines, _ = inspect.getsourcelines(function)
        return len(lines)

    assert line_count(sync_items) < 180
    assert line_count(upload) < 130
    assert line_count(download) < 150


def test_recursive_upload_plan_is_application_owned(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "a.txt").write_text("a", encoding="utf-8")
    (source / "empty").mkdir()

    plan = TransferService.build_recursive_upload_plan(str(source), "/backup")

    assert plan.remote_root == "/backup/source"
    assert [(Path(job.local_path).name, job.remote_path) for job in plan.jobs] == [
        ("a.txt", "/backup/source/nested/a.txt")
    ]
    assert "/backup/source/empty" in plan.empty_directories


class _MoveSource:
    def __init__(self) -> None:
        self.deleted = False

    def download(self, remote_path, local_path, recursive=False, callback=None):
        Path(local_path).write_text("payload", encoding="utf-8")
        return True

    def delete(self, remote_path, permanent=False):
        self.deleted = True
        return True


class _FailingMoveDestination:
    def stat(self, path):
        return {"type": "folder"}

    def upload(self, local_path, remote_path, callback=None):
        return False


def test_cross_provider_move_does_not_delete_source_when_upload_fails() -> None:
    source = _MoveSource()
    destination = _FailingMoveDestination()

    with pytest.raises(TransferOperationError):
        TransferService().move_between(
            "source",
            source,  # type: ignore[arg-type]
            "/a.txt",
            "destination",
            destination,  # type: ignore[arg-type]
            "/folder/a.txt",
        )

    assert source.deleted is False


def test_all_storage_providers_use_shared_callback_and_stat_annotations() -> None:
    offenders: list[str] = []
    for path in (ROOT / "providers").glob("*.py"):
        tree = _python_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name in {"upload", "download"}:
                callback = next((arg for arg in node.args.args if arg.arg == "callback"), None)
                if callback is None or callback.annotation is None:
                    offenders.append(f"{path.name}:{node.lineno}:callback")
                else:
                    annotation = ast.unparse(callback.annotation)
                    if annotation != "ProgressCallback | None":
                        offenders.append(f"{path.name}:{node.lineno}:{annotation}")
            if node.name == "stat":
                annotation = ast.unparse(node.returns) if node.returns is not None else ""
                if annotation != "StorageStat":
                    offenders.append(f"{path.name}:{node.lineno}:stat={annotation}")
    assert offenders == []


def test_storage_stat_file_count_key_is_normalized() -> None:
    for path in (ROOT / "providers").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert '"fileCount":' not in source
        assert "'fileCount':" not in source
