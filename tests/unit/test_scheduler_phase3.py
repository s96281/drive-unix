from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from application.scheduler_service import SchedulerService
from core.config import ConfigManager, CronTask


def _task(name: str, command: str = "echo ok") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        enabled=True,
        schedule="* * * * *",
        command=command,
        last_run=None,
        last_attempt_at=None,
        last_success_at=None,
        last_exit_code=None,
    )


def test_invalid_command_does_not_pollute_running_or_attempt_state() -> None:
    manager = Mock()
    manager.config.tasks = {"bad": _task("bad", "python")}
    service = SchedulerService(config_manager_factory=lambda: manager)
    output = Mock()

    service.tick(datetime(2026, 1, 1, 12, 0), output=output)

    assert service._running_tasks == set()
    assert "bad" not in service._last_run_keys
    manager.update_task_attempt.assert_not_called()
    messages = [call.args for call in output.call_args_list]
    assert any(level == "error" and "無效排程指令 bad" in message for level, message in messages)


def test_one_task_state_write_failure_does_not_block_later_task() -> None:
    manager = Mock()
    manager.config.tasks = {
        "broken": _task("broken"),
        "healthy": _task("healthy"),
    }

    def update_attempt(name: str, attempted_at: str) -> None:
        if name == "broken":
            raise OSError("disk unavailable")

    manager.update_task_attempt.side_effect = update_attempt
    service = SchedulerService(config_manager_factory=lambda: manager)
    service._run_job = Mock()
    output = Mock()

    service.tick(datetime(2026, 1, 1, 12, 0), output=output)

    attempted_names = [call.args[0] for call in manager.update_task_attempt.call_args_list]
    assert attempted_names == ["broken", "healthy"]
    assert "broken" not in service._running_tasks
    assert service._run_job.called
    messages = [call.args for call in output.call_args_list]
    assert any(level == "error" and "無法啟動任務 broken" in message for level, message in messages)
    assert any(level == "info" and "healthy" in message for level, message in messages)


def test_run_job_persists_exit_code() -> None:
    manager = Mock()
    service = SchedulerService(config_manager_factory=lambda: manager)
    output = Mock()
    result = SimpleNamespace(returncode=7, stderr="boom")

    with patch("application.scheduler_service.subprocess.run", return_value=result):
        service._run_job("job", ["sync", "a", "b"], output)

    manager.update_task_result.assert_called_once()
    kwargs = manager.update_task_result.call_args.kwargs
    assert kwargs["exit_code"] == 7
    assert isinstance(kwargs["completed_at"], str)
    assert "job" not in service._running_tasks
    output.assert_called_once()
    assert output.call_args.args[0] == "error"


def test_config_manager_tracks_attempt_success_and_failure(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    manager = ConfigManager(config_path)
    manager.add_task(
        "nightly",
        CronTask(name="nightly", schedule="0 2 * * *", command="sync a b"),
    )

    manager.update_task_attempt("nightly", "2026-01-02 02:00:00")
    manager.update_task_result(
        "nightly",
        completed_at="2026-01-02 02:05:00",
        exit_code=0,
    )
    manager.update_task_attempt("nightly", "2026-01-03 02:00:00")
    manager.update_task_result(
        "nightly",
        completed_at="2026-01-03 02:01:00",
        exit_code=3,
    )

    reloaded = ConfigManager(config_path).config.tasks["nightly"]
    assert reloaded.last_run == "2026-01-03 02:00:00"
    assert reloaded.last_attempt_at == "2026-01-03 02:00:00"
    assert reloaded.last_success_at == "2026-01-02 02:05:00"
    assert reloaded.last_exit_code == 3


def test_legacy_last_run_remains_scheduler_fallback() -> None:
    task = SimpleNamespace(last_attempt_at=None, last_run="2026-01-01 01:00:00")
    assert SchedulerService._task_last_attempt(task) == "2026-01-01 01:00:00"


def test_scheduler_normalizes_installed_cli_prefix() -> None:
    assert SchedulerService._normalize_command(
        "uv run drive-unix sync source:/ destination:/ --yes"
    ) == ["sync", "source:/", "destination:/", "--yes"]
