"""Canonical authentication identity resolution for cross-node credential deduplication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from core.config import (
    ConfigManager,
    GoogleDriveRemote,
    GooglePhotosRemote,
    OneDriveBusinessRemote,
    OneDriveRemote,
    RemoteConfig,
    SharePointRemote,
)


def _extract_domain(url: str) -> str:
    """Extract and normalize host domain from URL."""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or parsed.path).split(":")[0].strip().lower()
        return host or url.strip().lower()
    except Exception:
        return url.strip().lower()


def get_canonical_auth_identity(
    remote_name: str,
    remote: RemoteConfig,
    config_manager: ConfigManager | None = None,
) -> str:
    """Determine the canonical authentication identity for a remote.

    Remotes sharing the same service and user account will produce identical
    canonical identities, enabling Single Sign-On (SSO) and unified Upstash token sync.
    """
    # 1. SharePoint: Share session across different sites of the same tenant and email
    if isinstance(remote, SharePointRemote):
        if getattr(remote, "cache_source", None) and remote.cache_source != "sharepoint_main":
            return f"sharepoint:{remote.cache_source.strip().lower()}"
        domain = _extract_domain(remote.base_url)
        email = remote.email.strip().lower()
        return f"sharepoint:{domain}:{email}"

    # 2. OneDrive Business: Share authentication with SharePoint on the same tenant/account
    if isinstance(remote, OneDriveBusinessRemote):
        domain = _extract_domain(remote.base_url)
        email = remote.email.strip().lower()
        return f"sharepoint:{domain}:{email}"

    # 3. Google Drive / Google Photos: Deduplicate by OAuth client_id / credentials file
    if isinstance(remote, (GoogleDriveRemote, GooglePhotosRemote)):
        cred_path = Path(remote.credentials_json).expanduser()
        if not cred_path.is_absolute() and config_manager:
            cred_path = config_manager.config_path.parent / cred_path

        client_id: str | None = None
        if cred_path.exists():
            try:
                data = json.loads(cred_path.read_text(encoding="utf-8"))
                for section in ("installed", "web"):
                    if section in data and "client_id" in data[section]:
                        client_id = data[section]["client_id"]
                        break
            except Exception:
                pass

        ident = client_id or cred_path.name
        return f"google:{ident}:{remote.type}"

    # 4. Microsoft Graph OneDrive: Deduplicate by client_id and tenant
    if isinstance(remote, OneDriveRemote):
        return f"onedrive:{remote.client_id.strip().lower()}:{remote.tenant.strip().lower()}"

    # 5. Default fallback to remote-specific identity
    return f"{remote.type}:{remote_name}"


def build_identity_cache_key(identity: str) -> str:
    """Generate a stable 64-character SHA-256 hash from a canonical identity."""
    return hashlib.sha256(identity.strip().encode("utf-8")).hexdigest()
