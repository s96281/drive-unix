from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from application.upstash_sync_service import UpstashSyncService
from core.config import (
    ConfigManager,
    CronTask,
    LocalRemote,
    SharePointRemote,
)
from core.crypto import DecryptionError
from core.secrets import SecretRepository
from infrastructure.upstash_client import UpstashClient


class MockMemoryUpstashClient:
    """In-memory Upstash client for deterministic unit testing."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex_seconds: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def exists(self, key: str) -> bool:
        return key in self.store


def _create_test_manager(base_dir: Path) -> ConfigManager:
    config_path = base_dir / "config.toml"
    repo = SecretRepository(base_dir / "secrets.json", prefer_keyring=False)
    return ConfigManager(config_path, secret_store=repo)


def test_upstash_sync_push_and_pull_lifecycle(tmp_path: Path):
    dir_a = tmp_path / "dev_a"
    dir_b = tmp_path / "dev_b"
    dir_a.mkdir()
    dir_b.mkdir()

    mgr_a = _create_test_manager(dir_a)
    mgr_b = _create_test_manager(dir_b)

    # 1. Setup device A with remotes & secrets & secret file
    pass_ref = mgr_a.store_remote_secret("work_sp", "password", "SuperSecretPass123")
    sp_remote = SharePointRemote(
        type="sharepoint",
        base_url="https://company.sharepoint.com",
        site="/sites/team",
        email="user@company.com",
        password_ref=pass_ref,
    )
    mgr_a.add_remote("work_sp", sp_remote)

    local_remote = LocalRemote(type="local", root_path=str(dir_a))
    mgr_a.add_remote("my_local", local_remote)

    # Add a secret file
    mgr_a.secret_files_dir.mkdir(parents=True, exist_ok=True)
    (mgr_a.secret_files_dir / "oauth_creds.json").write_text('{"client_id": "xyz"}', encoding="utf-8")

    # Add a task
    mgr_a.add_task("backup_task", CronTask(name="backup_task", schedule="0 2 * * *", command="sync work_sp:/ my_local:/"))

    mock_client = MockMemoryUpstashClient()
    service_a = UpstashSyncService(mgr_a, client=mock_client)
    service_b = UpstashSyncService(mgr_b, client=mock_client)

    passphrase = "master-sync-passphrase"

    # 2. Push from Device A
    push_res = service_a.push(passphrase, iterations=10_000)
    assert push_res["status"] == "ok"
    assert push_res["remotes_count"] == 2
    assert "drive-unix:sync:default" in mock_client.store

    # 3. Check status from Device B (without decrypting)
    status_res = service_b.fetch_status()
    assert status_res["exists"] is True
    assert status_res["remotes_count"] == 2
    assert "work_sp" in status_res["remote_names"]
    assert "my_local" in status_res["remote_names"]

    # 4. Dry-run pull on Device B
    dry_run_res = service_b.pull(passphrase, dry_run=True)
    assert dry_run_res["status"] == "dry_run"
    assert "work_sp" in dry_run_res["new_remotes"]
    assert len(mgr_b.config.remotes) == 0  # Still empty

    # 5. Full pull on Device B
    pull_res = service_b.pull(passphrase)
    assert pull_res["status"] == "ok"
    assert "work_sp" in pull_res["restored_remotes"]
    assert "my_local" in pull_res["restored_remotes"]

    # Verify Device B state
    assert len(mgr_b.config.remotes) == 2
    restored_sp = mgr_b.get_remote("work_sp")
    assert isinstance(restored_sp, SharePointRemote)
    assert restored_sp.email == "user@company.com"

    # Verify secret was restored and resolvable in Device B's local secret store
    resolved_pass = mgr_b.resolve_secret(restored_sp.password_ref, remote_name="work_sp", label="password")
    assert resolved_pass == "SuperSecretPass123"

    # Verify secret file was restored on Device B
    restored_file = mgr_b.secret_files_dir / "oauth_creds.json"
    assert restored_file.exists()
    assert json.loads(restored_file.read_text(encoding="utf-8")) == {"client_id": "xyz"}

    # Verify tasks were restored
    assert "backup_task" in mgr_b.config.tasks


def test_upstash_pull_wrong_passphrase_leaves_local_untouched(tmp_path: Path):
    dir_a = tmp_path / "dev_a"
    dir_b = tmp_path / "dev_b"
    mgr_a = _create_test_manager(dir_a)
    mgr_b = _create_test_manager(dir_b)

    mgr_a.add_remote("r1", LocalRemote(type="local", root_path=str(dir_a)))
    mock_client = MockMemoryUpstashClient()

    service_a = UpstashSyncService(mgr_a, client=mock_client)
    service_b = UpstashSyncService(mgr_b, client=mock_client)

    service_a.push("correct-pass", iterations=10_000)

    # Initial remote on device B
    mgr_b.add_remote("existing_b", LocalRemote(type="local", root_path=str(dir_b)))

    with pytest.raises(DecryptionError):
        service_b.pull("wrong-pass")

    # Ensure device B was not modified
    assert list(mgr_b.config.remotes.keys()) == ["existing_b"]


def test_upstash_merge_and_overwrite_strategies(tmp_path: Path):
    dir_a = tmp_path / "dev_a"
    dir_b = tmp_path / "dev_b"
    mgr_a = _create_test_manager(dir_a)
    mgr_b = _create_test_manager(dir_b)

    mgr_a.add_remote("common", LocalRemote(type="local", root_path="/path/from/a"))
    mgr_a.add_remote("a_only", LocalRemote(type="local", root_path="/path/a"))

    mgr_b.add_remote("common", LocalRemote(type="local", root_path="/path/from/b"))
    mgr_b.add_remote("b_only", LocalRemote(type="local", root_path="/path/b"))

    mock_client = MockMemoryUpstashClient()
    service_a = UpstashSyncService(mgr_a, client=mock_client)
    service_b = UpstashSyncService(mgr_b, client=mock_client)

    service_a.push("pass", iterations=10_000)

    # Strategy 1: merge without overwrite
    res1 = service_b.pull("pass", strategy="merge", overwrite=False)
    assert res1["restored_remotes"] == ["a_only"]
    assert res1["skipped_remotes"] == ["common"]
    assert mgr_b.get_remote("common").root_path == "/path/from/b"
    assert "b_only" in mgr_b.config.remotes

    # Strategy 2: merge with overwrite
    res2 = service_b.pull("pass", strategy="merge", overwrite=True)
    assert "common" in res2["overwritten_remotes"]
    assert mgr_b.get_remote("common").root_path == "/path/from/a"

    # Strategy 3: replace
    res3 = service_b.pull("pass", strategy="replace")
    assert "b_only" not in mgr_b.config.remotes
    assert set(mgr_b.config.remotes.keys()) == {"common", "a_only"}
