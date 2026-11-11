"""Version management for drive-unix."""

from __future__ import annotations

import importlib.metadata
import subprocess
from pathlib import Path

__version__ = "0.1.0"


def get_version() -> str:
    """Return the installed version of drive-unix or the fallback constant."""
    try:
        return importlib.metadata.version("drive-unix")
    except Exception:
        return __version__


def get_git_commit(cwd: Path | None = None) -> str | None:
    """Return the short git commit hash if running in a git repository."""
    try:
        repo_dir = cwd or Path(__file__).resolve().parent.parent
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0:
            commit = res.stdout.strip()
            return commit if commit else None
    except Exception:
        pass
    return None
