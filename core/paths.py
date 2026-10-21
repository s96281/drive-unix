"""Path resolution helpers with root-boundary enforcement."""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath


def resolve_local_path(root_path: str, remote_path: str) -> Path:
    """Resolve a virtual remote path while preventing root escape.

    The candidate is resolved with symlinks followed so a path cannot escape
    the configured root through an existing symlink either.
    """
    if "\x00" in remote_path:
        raise ValueError("路徑不可包含 NUL 字元。")

    root = Path(root_path).expanduser().resolve(strict=False)
    relative = PurePosixPath(remote_path.lstrip("/"))

    candidate = (root / Path(*relative.parts)).resolve(strict=False)

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"路徑超出 Local Remote 根目錄範圍: {remote_path}"
        ) from exc

    return candidate


def resolve_posix_path(root_path: str, remote_path: str) -> str:
    """Resolve an SFTP/FTP POSIX path while preventing lexical root escape."""
    if "\x00" in remote_path:
        raise ValueError("路徑不可包含 NUL 字元。")

    root = posixpath.normpath(root_path or "/")
    if not root.startswith("/"):
        raise ValueError(
            f"Remote root_path 必須是絕對 POSIX 路徑: {root_path}"
        )

    relative = remote_path.lstrip("/")
    candidate = posixpath.normpath(posixpath.join(root, relative))

    if posixpath.commonpath((root, candidate)) != root:
        raise ValueError(
            f"路徑超出 Remote 根目錄範圍: {remote_path}"
        )

    return candidate


__all__ = ["resolve_local_path", "resolve_posix_path"]
