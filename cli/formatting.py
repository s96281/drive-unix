"""CLI formatting helpers independent of command implementation."""

from __future__ import annotations

from datetime import datetime

from rich.progress import ProgressColumn
from rich.text import Text

from core.constants import LOCAL_TIMEZONE


SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_size(size_in_bytes: int) -> str:
    """Format a byte count for human-readable CLI output."""
    if size_in_bytes == 0:
        return "0 B"

    value = float(size_in_bytes)
    unit_index = 0
    while value >= 1024.0 and unit_index < len(SIZE_UNITS) - 1:
        value /= 1024.0
        unit_index += 1
    return f"{value:.2f} {SIZE_UNITS[unit_index]}"


def format_time(iso_time_str: str) -> str:
    """Format an ISO-8601 timestamp in the configured local timezone."""
    if not iso_time_str:
        return "未知"

    try:
        parsed = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso_time_str


class MarqueeColumn(ProgressColumn):
    """Render long filenames as a terminal-friendly marquee."""

    def __init__(self, width: int = 35, speed: float = 4.0) -> None:
        super().__init__()
        self.width = width
        self.speed = speed

    def render(self, task) -> Text:
        filename = task.fields.get("filename")
        if filename is None:
            return Text.from_markup(task.description or "")

        icon = task.fields.get("icon", "")
        style = task.fields.get("color", "blue")
        if not filename:
            return Text(" " * self.width)

        if len(filename) <= self.width - 3:
            display_text = filename
        else:
            padded = f"{filename} • "
            shift = int(datetime.now().timestamp() * self.speed) % len(padded)
            display_text = padded[shift:] + padded[:shift]

        text = Text()
        if icon:
            text.append(f"{icon} ", style=style)
        text.append(display_text, style=style)
        text.truncate(self.width, overflow="", pad=True)
        return text
