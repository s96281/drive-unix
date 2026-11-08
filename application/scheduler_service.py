"""Application service for the built-in scheduler daemon."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime

from application.scheduling import has_missed_run, is_cron_match
from core.config import ConfigManager, CronTask
from core.logging import get_logger

logger = get_logger("scheduler")

TaskOutput = Callable[[str, str], None]
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class SchedulerService:
    """Evaluate configured tasks and execute them without CLI presentation logic."""

    def __init__(
        self,
        config_manager_factory: Callable[[], ConfigManager] = ConfigManager,
        *,
        executable: str | None = None,
        script_path: str | None = None,
    ) -> None:
        self.config_manager_factory = config_manager_factory
        self.executable = executable or sys.executable
        self.script_path = script_path or os.path.abspath(sys.argv[0])
        self._running_tasks: set[str] = set()
        self._lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._last_run_keys: dict[str, str] = {}

    def run_forever(
        self,
        *,
        output: TaskOutput | None = None,
        sleep_interval: float = 1.0,
    ) -> None:
        """Run the scheduler loop until interrupted.

        ``tick`` already isolates individual task failures.  The outer guard is
        intentional as a final daemon boundary so an unexpected scheduler bug
        cannot permanently stop all future tasks.
        """
        while True:
            now = datetime.now()
            try:
                self.tick(now, output=output)
            except Exception as exc:  # pragma: no cover - defensive daemon boundary
                logger.exception("Scheduler tick failed")
                self._emit(output, "error", f"排程器本輪執行失敗: {exc}")
            time.sleep(sleep_interval)

    def tick(
        self,
        now: datetime,
        *,
        output: TaskOutput | None = None,
    ) -> None:
        """Evaluate one scheduler tick. Kept separate for deterministic tests."""
        manager = self.config_manager_factory()
        for task_name, task in manager.config.tasks.items():
            try:
                self._evaluate_task(
                    manager,
                    task_name,
                    task,
                    now,
                    output=output,
                )
            except Exception as exc:
                # A malformed/broken task must never prevent later tasks from
                # being evaluated during the same scheduler tick.
                logger.exception("Scheduled task evaluation failed for %s", task_name)
                self._emit(output, "error", f"排程任務 {task_name} 無法觸發: {exc}")

        self._prune_run_keys(now)

    def _evaluate_task(
        self,
        manager: ConfigManager,
        task_name: str,
        task: CronTask,
        now: datetime,
        *,
        output: TaskOutput | None,
    ) -> None:
        if not task.enabled:
            return

        try:
            due_now = is_cron_match(task.schedule, now)
            missed = has_missed_run(
                task.schedule,
                self._task_last_attempt(task),
                now,
            )
        except ValueError:
            logger.warning("Ignoring invalid Cron expression for %s", task_name)
            self._emit(output, "error", f"無效 Cron 排程: {task_name}")
            return

        if not (due_now or missed):
            return

        run_key = self._build_run_key(task_name, now, missed and not due_now)
        if self._last_run_keys.get(task_name) == run_key:
            return

        # Validate before mutating any scheduler state.  In particular, an
        # empty command must not leave the task permanently marked as running.
        try:
            args = self._normalize_command(task.command)
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid command for scheduled task %s: %s", task_name, exc)
            self._emit(output, "error", f"無效排程指令 {task_name}: {exc}")
            return

        if not self._try_mark_running(task_name):
            if due_now:
                self._emit(output, "warning", f"略過任務: {task_name} (上一輪仍在執行)")
            return

        attempted_at = now.strftime(_TIMESTAMP_FORMAT)
        self._last_run_keys[task_name] = run_key

        try:
            # Persist before launching. If state persistence fails, do not run
            # the task because the next tick could otherwise launch a duplicate.
            with self._config_lock:
                manager.update_task_attempt(task_name, attempted_at)

            thread = threading.Thread(
                target=self._run_job,
                args=(task_name, args, output),
                daemon=True,
                name=f"scheduler-{task_name}",
            )
            thread.start()
        except Exception as exc:
            with self._lock:
                self._running_tasks.discard(task_name)
            logger.exception("Failed to launch scheduled task %s", task_name)
            self._record_task_result(task_name, exit_code=-1)
            self._emit(output, "error", f"無法啟動任務 {task_name}: {exc}")
            return

        self._emit(
            output,
            "info",
            f"{'補執行' if missed and not due_now else '觸發'}任務: {task_name}",
        )

    def _run_job(
        self,
        task_name: str,
        args: list[str],
        output: TaskOutput | None,
    ) -> None:
        exit_code = -1
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            command = [self.executable, self.script_path, *args]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            exit_code = result.returncode
            if result.returncode == 0:
                self._emit(output, "success", f"任務成功: {task_name}")
            else:
                message = f"任務失敗: {task_name} (Exit code: {result.returncode})"
                if result.stderr:
                    message += f"\n{result.stderr.strip()}"
                self._emit(output, "error", message)
        except Exception as exc:
            logger.exception("Failed to execute scheduled task %s", task_name)
            self._emit(output, "error", f"無法執行任務 {task_name}: {exc}")
        finally:
            self._record_task_result(task_name, exit_code=exit_code)
            with self._lock:
                self._running_tasks.discard(task_name)

    def _record_task_result(self, task_name: str, *, exit_code: int) -> None:
        completed_at = datetime.now().strftime(_TIMESTAMP_FORMAT)
        try:
            # Reload inside the lock so concurrent jobs do not save stale
            # ConfigManager snapshots over one another.
            with self._config_lock:
                manager = self.config_manager_factory()
                manager.update_task_result(
                    task_name,
                    completed_at=completed_at,
                    exit_code=exit_code,
                )
        except Exception:
            # Result persistence must not leak a running-state entry or crash a
            # worker thread after the subprocess has already finished.
            logger.exception("Failed to persist scheduler result for %s", task_name)

    @staticmethod
    def _task_last_attempt(task: CronTask) -> str | None:
        last_attempt = getattr(task, "last_attempt_at", None)
        if isinstance(last_attempt, str) and last_attempt:
            return last_attempt
        legacy_last_run = getattr(task, "last_run", None)
        if isinstance(legacy_last_run, str) and legacy_last_run:
            return legacy_last_run
        return None

    def _try_mark_running(self, task_name: str) -> bool:
        with self._lock:
            if task_name in self._running_tasks:
                return False
            self._running_tasks.add(task_name)
            return True

    @staticmethod
    def _build_run_key(task_name: str, now: datetime, missed: bool) -> str:
        suffix = "missed" if missed else "scheduled"
        return f"{task_name}:{suffix}:{now:%Y-%m-%d %H:%M}"

    @staticmethod
    def _normalize_command(command: str) -> list[str]:
        if not isinstance(command, str):
            raise TypeError("排程 command 必須是字串。")
        args = shlex.split(command)
        while args and args[0] in {
            "mycli",
            "drive-unix",
            "python",
            "python3",
            "uv",
            "run",
            "main.py",
            "./main.py",
        }:
            args.pop(0)
        if not args:
            raise ValueError("排程 command 不可為空。")
        return args

    def _prune_run_keys(self, now: datetime) -> None:
        current_minute = now.strftime("%Y-%m-%d %H:%M")
        self._last_run_keys = {
            name: value
            for name, value in self._last_run_keys.items()
            if value.endswith(current_minute)
        }

    @staticmethod
    def _emit(output: TaskOutput | None, level: str, message: str) -> None:
        if output is not None:
            output(level, message)
