"""Shared CLI presentation policy.

The module keeps output behavior consistent across commands without leaking
presentation concerns into application/domain code.  ``--plain`` removes
emoji/ANSI styling, ``NO_COLOR`` disables color, and non-interactive stdout
suppresses live/animated progress output.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import sys
from collections.abc import Iterable
from typing import Any

import typer


_SYMBOLS = (
    "⚠️", "ℹ️", "⚙️", "⏱️",
    "❌", "✅", "💡", "📋", "🕒", "🟢", "🔴", "🛑", "🔍",
    "📁", "📄", "🌲", "🎯", "⚡", "📊", "📦", "📅", "📍",
    "📏", "💿", "🗂️", "🚀", "🌉", "⬇", "⬆", "🔄", "🎉",
    "⏩", "🎁", "ℹ", "⚠", "🧪", "🗑️", "🌐", "📥", "⠧",
)
_SYMBOL_RE = re.compile(
    "(?:"
    + "|".join(re.escape(symbol) for symbol in sorted(_SYMBOLS, key=len, reverse=True))
    + r")[ \t]?"
)


@dataclass(slots=True)
class PresentationState:
    plain: bool = False
    color: bool = True


_STATE = PresentationState()


def configure_presentation(*, plain: bool = False) -> None:
    """Configure process-wide presentation for the current CLI invocation."""
    _STATE.plain = bool(plain)
    _STATE.color = not _STATE.plain and "NO_COLOR" not in os.environ


def is_plain() -> bool:
    return _STATE.plain


def color_enabled() -> bool:
    return _STATE.color


def live_output_enabled() -> bool:
    """Return whether animated/live terminal output is appropriate."""
    try:
        return not _STATE.plain and bool(sys.stdout.isatty())
    except (AttributeError, OSError):
        return False


def plain_text(value: Any) -> str:
    text = str(value)
    if not _STATE.plain:
        return text
    text = _SYMBOL_RE.sub("", text)
    # Remove emoji variation selectors that may remain after symbol stripping.
    return text.replace("\ufe0f", "")


def echo(message: Any = None, **kwargs: Any) -> None:
    if message is not None:
        message = plain_text(message)
    typer.echo(message, **kwargs)


def secho(message: Any = None, **kwargs: Any) -> None:
    if message is not None:
        message = plain_text(message)
    if not _STATE.color:
        for key in (
            "fg", "bg", "bold", "dim", "underline", "overline", "italic",
            "blink", "reverse", "strikethrough",
        ):
            kwargs.pop(key, None)
        kwargs["color"] = False
    typer.secho(message, **kwargs)


def style(message: Any, **kwargs: Any) -> str:
    text = plain_text(message)
    if not _STATE.color:
        return text
    return typer.style(text, **kwargs)


def render_error(
    problem: str,
    *,
    cause: BaseException | str | None = None,
    next_steps: Iterable[str] = (),
) -> None:
    """Render an actionable, consistent CLI error block."""
    secho(f"❌ {problem}", fg=typer.colors.RED, bold=True)
    if cause is not None and str(cause).strip():
        echo(f"原因：{cause}")
    steps = tuple(step for step in next_steps if step)
    if steps:
        echo("下一步：")
        for step in steps:
            echo(f"  - {step}")


def render_warning(message: str, *, next_steps: Iterable[str] = ()) -> None:
    secho(f"⚠️ {message}", fg=typer.colors.YELLOW, bold=True)
    steps = tuple(step for step in next_steps if step)
    if steps:
        echo("下一步：")
        for step in steps:
            echo(f"  - {step}")


__all__ = [
    "color_enabled",
    "configure_presentation",
    "echo",
    "is_plain",
    "live_output_enabled",
    "plain_text",
    "render_error",
    "render_warning",
    "secho",
    "style",
]
