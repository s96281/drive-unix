from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from application.scheduler_daemon import SchedulerDaemonManager, SYSTEMD_UNIT_NAME


def test_detached_start_uses_new_session_and_tracks_pid(tmp_path) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=4242)

    manager = SchedulerDaemonManager(
        config_dir=tmp_path,
        executable="/python",
        script_path="/drive-unix",
        platform="freebsd",
        popen_command=fake_popen,
    )

    status = manager.start()

    assert status.running is True
    assert status.installed is False
    assert status.pid == 4242
    assert manager.pid_path.read_text(encoding="ascii") == "4242"
    command, kwargs = calls[0]
    assert command == ["/python", "/drive-unix", "--plain", "schedule", "_run-service"]
    assert kwargs["start_new_session"] is True


def test_claim_and_release_current_process_manage_pidfile(tmp_path) -> None:
    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="freebsd")

    manager.claim_current_process()
    assert int(manager.pid_path.read_text(encoding="ascii")) == os.getpid()

    manager.release_current_process()
    assert not manager.pid_path.exists()


def test_is_ancestor_process_real() -> None:
    current = os.getpid()
    parent = os.getppid()
    assert SchedulerDaemonManager._is_ancestor_process(current, current) is True
    assert SchedulerDaemonManager._is_ancestor_process(parent, current) is True
    assert SchedulerDaemonManager._is_ancestor_process(current, parent) is False
    assert SchedulerDaemonManager._is_ancestor_process(999999, current) is False
    assert SchedulerDaemonManager._is_ancestor_process(-1, current) is False
    assert SchedulerDaemonManager._is_ancestor_process(current, -1) is False



def test_linux_install_writes_user_systemd_unit(monkeypatch, tmp_path) -> None:
    unit_path = tmp_path / "systemd" / SYSTEMD_UNIT_NAME
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        SchedulerDaemonManager,
        "systemd_unit_path",
        property(lambda self: unit_path),
    )
    manager = SchedulerDaemonManager(
        config_dir=tmp_path / "config",
        executable="/usr/bin/python3",
        script_path="/opt/drive unix/main.py",
        platform="linux",
        run_command=fake_run,
    )

    manager.install()

    content = unit_path.read_text(encoding="utf-8")
    assert "Description=drive-unix scheduler" in content
    assert '"/opt/drive unix/main.py"' in content
    assert '"schedule" "_run-service"' in content
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", SYSTEMD_UNIT_NAME] in calls


def test_uninstall_stops_detached_fallback_when_no_os_service(monkeypatch, tmp_path) -> None:
    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="freebsd")
    manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    manager.pid_path.write_text("5151", encoding="ascii")
    terminated: list[int] = []

    monkeypatch.setattr(manager, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        manager,
        "_terminate_pid",
        lambda pid, *, timeout: terminated.append(pid),
    )

    manager.uninstall()

    assert terminated == [5151]
    assert not manager.pid_path.exists()


def test_claim_process_adopts_launcher_ancestor(monkeypatch, tmp_path) -> None:
    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="win32")
    manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    # Simulate parent/launcher writing its PID
    launcher_pid = 99991
    manager.pid_path.write_text(str(launcher_pid), encoding="ascii")

    # Mock _pid_alive to True for launcher, and mock _is_ancestor_process to True
    monkeypatch.setattr(manager, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_is_ancestor_process", lambda ancestor, child: ancestor == launcher_pid)

    # Calling claim_current_process should NOT raise, but update pid file to current process
    manager.claim_current_process()
    assert int(manager.pid_path.read_text(encoding="ascii")) == os.getpid()


def test_claim_process_rejects_unrelated_running_scheduler(monkeypatch, tmp_path) -> None:
    import pytest

    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="win32")
    manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    unrelated_pid = 88882
    manager.pid_path.write_text(str(unrelated_pid), encoding="ascii")

    monkeypatch.setattr(manager, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(manager, "_is_ancestor_process", lambda ancestor, child: False)

    with pytest.raises(RuntimeError, match="Scheduler 已在執行中"):
        manager.claim_current_process()


def test_claim_process_overwrites_dead_pid(monkeypatch, tmp_path) -> None:
    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="win32")
    manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    stale_pid = 77773
    manager.pid_path.write_text(str(stale_pid), encoding="ascii")

    # Stale process is dead
    monkeypatch.setattr(manager, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(manager, "_is_ancestor_process", lambda ancestor, child: False)

    manager.claim_current_process()
    assert int(manager.pid_path.read_text(encoding="ascii")) == os.getpid()


def test_release_current_process_removes_launcher_pid(monkeypatch, tmp_path) -> None:
    manager = SchedulerDaemonManager(config_dir=tmp_path, platform="win32")
    manager.runtime_dir.mkdir(parents=True, exist_ok=True)
    launcher_pid = 99991
    manager.pid_path.write_text(str(launcher_pid), encoding="ascii")

    monkeypatch.setattr(manager, "_is_ancestor_process", lambda ancestor, child: ancestor == launcher_pid)

    manager.release_current_process()
    assert not manager.pid_path.exists()


def test_is_ancestor_process_real() -> None:
    current = os.getpid()
    parent = os.getppid()
    assert SchedulerDaemonManager._is_ancestor_process(current, current) is True
    assert SchedulerDaemonManager._is_ancestor_process(parent, current) is True
    assert SchedulerDaemonManager._is_ancestor_process(current, parent) is False
    assert SchedulerDaemonManager._is_ancestor_process(999999, current) is False
    assert SchedulerDaemonManager._is_ancestor_process(-1, current) is False
    assert SchedulerDaemonManager._is_ancestor_process(current, -1) is False


