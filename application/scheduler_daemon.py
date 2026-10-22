"""Lifecycle management for the long-running drive-unix scheduler process."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import time
from collections.abc import Callable

from core.config import DEFAULT_CONFIG_DIR


WINDOWS_TASK_NAME = "DriveUnixScheduler"
SYSTEMD_UNIT_NAME = "drive-unix-scheduler.service"
LAUNCHD_LABEL = "io.drive-unix.scheduler"


@dataclass(frozen=True, slots=True)
class SchedulerDaemonStatus:
    installed: bool
    running: bool
    pid: int | None
    backend: str
    log_path: Path


RunCommand = Callable[..., subprocess.CompletedProcess]
PopenCommand = Callable[..., subprocess.Popen]


def _get_uid() -> int:
    return int(getattr(os, "getuid", lambda: 0)())


class SchedulerDaemonManager:
    """Install, start, stop and inspect the scheduler as an OS-level service.

    Linux uses a user-level systemd unit, macOS uses a LaunchAgent, and
    Windows uses Task Scheduler.  If no service has been installed yet,
    ``start`` still works by spawning a detached child and tracking its PID.
    """

    def __init__(
        self,
        *,
        config_dir: Path | None = None,
        executable: str | None = None,
        script_path: str | None = None,
        platform: str | None = None,
        run_command: RunCommand = subprocess.run,
        popen_command: PopenCommand = subprocess.Popen,
    ) -> None:
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)
        self.runtime_dir = self.config_dir / "scheduler"
        self.pid_path = self.runtime_dir / "scheduler.pid"
        self.log_path = self.runtime_dir / "scheduler.log"
        self.executable = executable or sys.executable
        self.script_path = script_path or os.path.abspath(sys.argv[0])
        self.platform = platform or sys.platform
        self._run = run_command
        self._popen = popen_command

    @property
    def backend(self) -> str:
        if self.platform == "win32":
            return "windows-task-scheduler"
        if self.platform == "darwin":
            return "launchd"
        if self.platform.startswith("linux"):
            return "systemd-user"
        return "detached-process"

    @property
    def systemd_unit_path(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT_NAME

    @property
    def launchd_plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

    def child_command(self) -> list[str]:
        return [
            self.executable,
            self.script_path,
            "--plain",
            "schedule",
            "_run-service",
        ]

    def installed(self) -> bool:
        if self.platform == "win32":
            result = self._run(
                ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME],
                capture_output=True,
                check=False,
            )
            return result.returncode == 0
        if self.platform == "darwin":
            return self.launchd_plist_path.exists()
        if self.platform.startswith("linux"):
            return self.systemd_unit_path.exists()
        return False

    def install(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self.platform == "win32":
            # Task Scheduler owns the foreground child process and starts it at logon.
            command = subprocess.list2cmdline(self.child_command())
            result = self._run(
                [
                    "schtasks", "/Create",
                    "/TN", WINDOWS_TASK_NAME,
                    "/TR", command,
                    "/SC", "ONLOGON",
                    "/F",
                ],
                capture_output=True,
                check=False,
            )
            self._require_success(result, "無法建立 Windows Scheduler service")
            return

        if self.platform == "darwin":
            path = self.launchd_plist_path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": LAUNCHD_LABEL,
                "ProgramArguments": self.child_command(),
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(self.log_path),
                "StandardErrorPath": str(self.log_path),
            }
            with path.open("wb") as handle:
                plistlib.dump(payload, handle)
            return

        if self.platform.startswith("linux"):
            path = self.systemd_unit_path
            path.parent.mkdir(parents=True, exist_ok=True)
            exec_start = " ".join(self._systemd_quote(arg) for arg in self.child_command())
            unit = (
                "[Unit]\n"
                "Description=drive-unix scheduler\n"
                "After=network-online.target\n\n"
                "[Service]\n"
                "Type=simple\n"
                f"ExecStart={exec_start}\n"
                "Restart=on-failure\n"
                "RestartSec=5\n"
                "Environment=PYTHONIOENCODING=utf-8\n"
                f"StandardOutput=append:{self.log_path}\n"
                f"StandardError=append:{self.log_path}\n\n"
                "[Install]\n"
                "WantedBy=default.target\n"
            )
            path.write_text(unit, encoding="utf-8")
            reload_result = self._run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(reload_result, "systemd user daemon-reload 失敗")
            enable_result = self._run(
                ["systemctl", "--user", "enable", SYSTEMD_UNIT_NAME],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(enable_result, "無法啟用 systemd user service")
            return

        raise RuntimeError(f"此平台不支援 service install: {self.platform}")

    def uninstall(self) -> None:
        if self.platform == "win32":
            if self.installed():
                self._run(
                    ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME],
                    capture_output=True,
                    check=False,
                )
                result = self._run(
                    ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
                    capture_output=True,
                    check=False,
                )
                self._require_success(result, "無法移除 Windows Scheduler service")
                self._remove_pidfile()
            else:
                self.stop()
            return

        if self.platform == "darwin":
            path = self.launchd_plist_path
            if path.exists():
                self._run(
                    ["launchctl", "bootout", f"gui/{_get_uid()}", str(path)],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                path.unlink(missing_ok=True)
                self._remove_pidfile()
            else:
                self.stop()
            return

        if self.platform.startswith("linux"):
            path = self.systemd_unit_path
            if path.exists():
                self._run(
                    ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT_NAME],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                path.unlink(missing_ok=True)
                self._run(
                    ["systemctl", "--user", "daemon-reload"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self._remove_pidfile()
            else:
                self.stop()
            return

        self.stop()

    def start(self) -> SchedulerDaemonStatus:
        current = self.status()
        if current.running:
            return current

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if current.installed and self.platform == "win32":
            result = self._run(
                ["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME],
                capture_output=True,
                check=False,
            )
            self._require_success(result, "無法啟動 Windows Scheduler service")
            return self._wait_for_running()

        if current.installed and self.platform == "darwin":
            result = self._run(
                [
                    "launchctl", "bootstrap", f"gui/{_get_uid()}",
                    str(self.launchd_plist_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            # bootstrap returns non-zero when already loaded; kickstart is the
            # authoritative start operation in either case.
            del result
            result = self._run(
                ["launchctl", "kickstart", "-k", f"gui/{_get_uid()}/{LAUNCHD_LABEL}"],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(result, "無法啟動 launchd scheduler service")
            return self._wait_for_running()

        if current.installed and self.platform.startswith("linux"):
            result = self._run(
                ["systemctl", "--user", "start", SYSTEMD_UNIT_NAME],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(result, "無法啟動 systemd user scheduler service")
            return self._wait_for_running()

        # No service registration: still provide a real detached daemon for
        # users who only want the current session/lifecycle.
        with self.log_path.open("a", encoding="utf-8") as log_file:
            kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "close_fds": True,
                "env": {**os.environ, "PYTHONIOENCODING": "utf-8"},
            }
            if self.platform == "win32":
                kwargs["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                )
            else:
                kwargs["start_new_session"] = True
            process = self._popen(self.child_command(), **kwargs)
        self._write_pid(process.pid)
        return SchedulerDaemonStatus(
            installed=False,
            running=True,
            pid=process.pid,
            backend="detached-process",
            log_path=self.log_path,
        )

    def stop(self, *, timeout: float = 5.0) -> SchedulerDaemonStatus:
        current = self.status()
        if not current.running:
            self._remove_pidfile()
            return current

        if current.installed and self.platform == "win32":
            result = self._run(
                ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME],
                capture_output=True,
                check=False,
            )
            self._require_success(result, "無法停止 Windows Scheduler service")
        elif current.installed and self.platform == "darwin":
            result = self._run(
                [
                    "launchctl", "bootout", f"gui/{_get_uid()}",
                    str(self.launchd_plist_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(result, "無法停止 launchd scheduler service")
        elif current.installed and self.platform.startswith("linux"):
            result = self._run(
                ["systemctl", "--user", "stop", SYSTEMD_UNIT_NAME],
                capture_output=True,
                check=False,
                text=True,
            )
            self._require_success(result, "無法停止 systemd user scheduler service")
        elif current.pid is not None:
            self._terminate_pid(current.pid, timeout=timeout)

        self._remove_pidfile()
        return SchedulerDaemonStatus(
            installed=current.installed,
            running=False,
            pid=None,
            backend=current.backend,
            log_path=self.log_path,
        )

    def status(self) -> SchedulerDaemonStatus:
        installed = self.installed()
        pid = self._read_pid()
        running = pid is not None and self._pid_alive(pid)
        if not running and pid is not None:
            self._remove_pidfile()
            pid = None

        # A managed backend may be active before the child has written its PID.
        if installed and not running:
            backend_running = self._managed_backend_running()
            running = backend_running

        return SchedulerDaemonStatus(
            installed=installed,
            running=running,
            pid=pid,
            backend=self.backend if installed else "detached-process",
            log_path=self.log_path,
        )

    def claim_current_process(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_pid()
        current = os.getpid()
        if existing is not None and existing != current and self._pid_alive(existing):
            raise RuntimeError(f"Scheduler 已在執行中 (PID {existing})。")
        self._write_pid(current)

    def release_current_process(self) -> None:
        pid = self._read_pid()
        if pid is None or pid == os.getpid():
            self._remove_pidfile()

    def _managed_backend_running(self) -> bool:
        if self.platform == "win32":
            # The localized schtasks status text is not stable across Windows
            # languages, so PID tracking remains authoritative.
            return False
        if self.platform == "darwin":
            result = self._run(
                ["launchctl", "print", f"gui/{_get_uid()}/{LAUNCHD_LABEL}"],
                capture_output=True,
                check=False,
                text=True,
            )
            return result.returncode == 0
        if self.platform.startswith("linux"):
            result = self._run(
                ["systemctl", "--user", "is-active", "--quiet", SYSTEMD_UNIT_NAME],
                capture_output=True,
                check=False,
                text=True,
            )
            return result.returncode == 0
        return False

    def _wait_for_running(self, timeout: float = 3.0) -> SchedulerDaemonStatus:
        deadline = time.monotonic() + timeout
        latest = self.status()
        while not latest.running and time.monotonic() < deadline:
            time.sleep(0.05)
            latest = self.status()
        return latest

    def _read_pid(self) -> int | None:
        try:
            value = self.pid_path.read_text(encoding="ascii").strip()
            pid = int(value)
            return pid if pid > 0 else None
        except (FileNotFoundError, OSError, ValueError):
            return None

    def _write_pid(self, pid: int) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temp = self.pid_path.with_suffix(".tmp")
        temp.write_text(str(pid), encoding="ascii")
        os.replace(temp, self.pid_path)

    def _remove_pidfile(self) -> None:
        self.pid_path.unlink(missing_ok=True)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    @staticmethod
    def _terminate_pid(pid: int, *, timeout: float) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not SchedulerDaemonManager._pid_alive(pid):
                return
            time.sleep(0.05)
        if hasattr(signal, "SIGKILL"):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _systemd_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _require_success(result: subprocess.CompletedProcess, message: str) -> None:
        if result.returncode == 0:
            return
        stderr = getattr(result, "stderr", None)
        stdout = getattr(result, "stdout", None)
        detail = stderr or stdout or "unknown error"
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        raise RuntimeError(f"{message}: {str(detail).strip()}")


__all__ = [
    "LAUNCHD_LABEL",
    "SYSTEMD_UNIT_NAME",
    "WINDOWS_TASK_NAME",
    "SchedulerDaemonManager",
    "SchedulerDaemonStatus",
]
