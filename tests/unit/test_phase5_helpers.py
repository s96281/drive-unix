from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from cli.formatting import format_size, format_time
from cli.parsers import parse_size_to_bytes
from application.scheduling import has_missed_run, is_cron_match, validate_cron_expression
from core.hashing import QuickXorHash, calculate_local_hash
from application.scheduler_service import SchedulerService


def test_quickxor_hash_matches_incremental_and_one_shot() -> None:
    payload = b"drive-unix" * 100

    one_shot = QuickXorHash().update(payload).base64digest()
    incremental = QuickXorHash()
    for offset in range(0, len(payload), 7):
        incremental.update(payload[offset : offset + 7])

    assert incremental.base64digest() == one_shot
    assert len(base64.b64decode(one_shot)) == 20


def test_calculate_local_hash_supports_standard_hashes_and_quickxor(tmp_path: Path) -> None:
    file_path = tmp_path / "hash-input.bin"
    file_path.write_bytes(b"hello")

    assert calculate_local_hash(str(file_path), "sha256") == hashlib.sha256(b"hello").hexdigest()
    assert calculate_local_hash(str(file_path), "qxh") == QuickXorHash().update(b"hello").base64digest()


def test_cli_parsers() -> None:
    assert parse_size_to_bytes("1.5MB") == 1572864
    assert parse_size_to_bytes("512") == 512
    assert format_size(1572864) == "1.50 MB"
    assert format_time("2026-01-01T00:00:00Z") == "2026-01-01 08:00:00"


def test_cron_validation_and_match() -> None:
    validate_cron_expression("*/5 * * * *")
    assert is_cron_match("0 2 * * *", datetime(2026, 1, 1, 2, 0))
    assert not is_cron_match("0 2 * * *", datetime(2026, 1, 1, 3, 0))

    try:
        validate_cron_expression("0 2 * *")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid cron expression should be rejected")


def test_scheduler_detects_missed_run() -> None:
    now = datetime(2026, 1, 2, 3, 0)
    assert has_missed_run("0 2 * * *", "2026-01-02 01:00:00", now)
    assert not has_missed_run("0 2 * * *", "2026-01-02 02:00:00", now)


def test_scheduler_service_does_not_trigger_same_minute_twice() -> None:
    task = Mock(enabled=True, schedule="* * * * *", last_run=None, command="echo test", name="job")
    manager = Mock()
    manager.config.tasks = {"job": task}

    service = SchedulerService(config_manager_factory=lambda: manager)
    service._run_job = Mock()
    output = Mock()
    now = datetime(2026, 1, 1, 12, 0)

    service.tick(now, output=output)
    service.tick(now, output=output)

    assert output.call_count == 1
    manager.update_task_attempt.assert_called_once()
