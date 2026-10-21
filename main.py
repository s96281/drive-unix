"""CLI composition root for drive_unix."""

from __future__ import annotations

import sys

from cli.app import create_app
from core.logging import configure_logging


app = create_app()


def main() -> None:
    """Run the command-line application."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    configure_logging()
    app()


if __name__ == "__main__":
    main()
