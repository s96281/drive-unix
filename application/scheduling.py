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
