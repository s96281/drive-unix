"""Pure scheduling rules shared by the scheduler service and CLI boundary."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.constants import MAX_SCHEDULER_LOOKBACK


CRON_FIELD_COUNT = 5


def validate_cron_expression(expression: str) -> None:
    """Validate the basic five-field Cron shape used by the built-in scheduler."""
    if len(expression.split()) != CRON_FIELD_COUNT:
        raise ValueError("Cron 格式錯誤，必須包含 5 個部分 (分 時 日 月 星期)。")


def _cron_field_matches(value: int, expression: str) -> bool:
    if expression == "*":
        return True
    if "," in expression:
        return any(_cron_field_matches(value, part) for part in expression.split(","))
    if "/" in expression:
        base, raw_step = expression.split("/", 1)
        step = int(raw_step)
        if step <= 0:
            raise ValueError("Cron step 必須大於 0。")
        if base == "*":
            return value % step == 0
        if "-" in base:
            start, end = map(int, base.split("-", 1))
            return start <= value <= end and (value - start) % step == 0
        return value % step == 0
    if "-" in expression:
        start, end = map(int, expression.split("-", 1))
        return start <= value <= end
    return int(expression) == value


def is_cron_match(cron_expr: str, target_time: datetime) -> bool:
    """Return whether a five-field Cron expression matches ``target_time``."""
    validate_cron_expression(cron_expr)
    minute, hour, day, month, day_of_week = cron_expr.split()

    cron_day_of_week = target_time.isoweekday() % 7
    day_of_week_match = (
        _cron_field_matches(cron_day_of_week, day_of_week)
        or _cron_field_matches(target_time.isoweekday(), day_of_week)
    )

    return (
        _cron_field_matches(target_time.minute, minute)
        and _cron_field_matches(target_time.hour, hour)
        and _cron_field_matches(target_time.day, day)
        and _cron_field_matches(target_time.month, month)
        and day_of_week_match
    )


def has_missed_run(
    cron_expr: str,
    last_run_str: str | None,
    current_time: datetime,
) -> bool:
    """Return whether the scheduler missed a Cron occurrence since the last run."""
    if not last_run_str:
        return False

    try:
        last_run = datetime.strptime(
            last_run_str,
            "%Y-%m-%d %H:%M:%S",
        ).replace(second=0, microsecond=0)
        target = current_time.replace(second=0, microsecond=0)
        if last_run >= target:
            return False

        start = max(last_run, target - MAX_SCHEDULER_LOOKBACK)
        cursor = start + timedelta(minutes=1)
        while cursor < target:
            if is_cron_match(cron_expr, cursor):
                return True
            cursor += timedelta(minutes=1)
        return False
    except (ValueError, OverflowError):
        return False


def next_cron_occurrence(
    cron_expr: str,
    after: datetime,
    *,
    horizon_days: int = 366,
) -> datetime | None:
    """Calculate the next matching occurrence after ``after`` within ``horizon_days``."""
    validate_cron_expression(cron_expr)
    minute, hour, day, month, day_of_week = cron_expr.split()

    cursor = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    end_limit = after + timedelta(days=horizon_days)

    while cursor <= end_limit:
        # 1. Month check
        if not _cron_field_matches(cursor.month, month):
            if cursor.month == 12:
                cursor = datetime(cursor.year + 1, 1, 1, 0, 0)
            else:
                cursor = datetime(cursor.year, cursor.month + 1, 1, 0, 0)
            continue

        # 2. Day & Day-of-week check
        cron_dow = cursor.isoweekday() % 7
        dow_match = (
            _cron_field_matches(cron_dow, day_of_week)
            or _cron_field_matches(cursor.isoweekday(), day_of_week)
        )
        day_match = _cron_field_matches(cursor.day, day)
        if not (day_match and dow_match):
            next_day = cursor + timedelta(days=1)
            cursor = next_day.replace(hour=0, minute=0)
            continue

        # 3. Hour check
        if not _cron_field_matches(cursor.hour, hour):
            next_hour = cursor + timedelta(hours=1)
            cursor = next_hour.replace(minute=0)
            continue

        # 4. Minute check
        if _cron_field_matches(cursor.minute, minute):
            return cursor

        cursor += timedelta(minutes=1)

    return None


def resolve_runtime_entrypoint(
    executable: str | None = None,
    script_path: str | None = None,
    *,
    platform: str | None = None,
) -> tuple[str, str]:
    """Sniff and resolve the optimal Python executable and main.py script path.

    This detects project environments where the scheduler may be invoked via an
    entrypoint binary (like `drive-unix` or `.venv/Scripts/drive-unix`), resolving
    back to the correct Python interpreter and `main.py` entrypoint.
    If explicit executable and script_path are passed and script_path is already
    a python script (ends with .py) or executable is explicitly provided without
    requiring auto-sniffing, those explicit values are respected.
    """
    import os
    import sys
    from pathlib import Path

    current_platform = platform or sys.platform

    # If caller explicitly provided script_path and executable, respect them without sniffing.
    if executable is not None and script_path is not None:
        return executable, script_path

    # Determine if script_path is a CLI binary/wrapper (e.g. drive-unix or drive-unix.exe)
    # or if it's missing/not a python script.
    search_dirs: list[Path] = []

    # 1. From explicit or argv script_path
    for sp in (script_path, sys.argv[0] if sys.argv and sys.argv[0] else None):
        if sp:
            try:
                p = Path(sp)
                cur = p if p.is_dir() else p.parent
                search_dirs.append(cur)
                # Traverse up to 4 parent levels (e.g. .venv/Scripts -> .venv -> root)
                for _ in range(3):
                    cur = cur.parent
                    search_dirs.append(cur)
            except Exception:
                pass

    # 2. From cwd
    try:
        search_dirs.append(Path.cwd())
    except Exception:
        pass

    # 3. From executable
    for exe in (executable, sys.executable):
        if exe:
            try:
                pe = Path(exe)
                cur = pe if pe.is_dir() else pe.parent
                search_dirs.append(cur)
                for _ in range(3):
                    cur = cur.parent
                    search_dirs.append(cur)
            except Exception:
                pass

    # Find main.py
    main_py_path: Path | None = None
    for directory in search_dirs:
        try:
            cand = (directory / "main.py").resolve()
            if cand.is_file():
                main_py_path = cand
                break
        except Exception:
            continue

    project_root = main_py_path.parent if main_py_path else Path.cwd()

    # Sniff python executable
    python_candidates: list[Path] = []

    # If an explicit executable was provided, consider it
    if executable is not None:
        python_candidates.append(Path(executable))

    # Next: Virtualenv python next to project root / main.py
    if current_platform == "win32":
        python_candidates.append(project_root / ".venv" / "Scripts" / "python.exe")
        python_candidates.append(project_root / "venv" / "Scripts" / "python.exe")
    else:
        python_candidates.append(project_root / ".venv" / "bin" / "python")
        python_candidates.append(project_root / "venv" / "bin" / "python")

    # Fallback to sys.executable
    python_candidates.append(Path(sys.executable))

    resolved_py: Path | None = None
    for cand in python_candidates:
        try:
            if cand.is_file():
                resolved_py = cand.resolve()
                break
        except Exception:
            continue

    final_executable = str(resolved_py) if resolved_py else (executable or sys.executable)
    final_script = (
        str(main_py_path)
        if main_py_path
        else (script_path or os.path.abspath(sys.argv[0]))
    )

    # If caller provided explicit values and no main.py was found, keep caller's script_path
    if script_path is not None and not main_py_path:
        final_script = script_path
    if executable is not None and not resolved_py:
        final_executable = executable

    return final_executable, final_script

