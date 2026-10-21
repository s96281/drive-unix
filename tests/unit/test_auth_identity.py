from __future__ import annotations

from pathlib import Path
import pytest

from auth.identity import build_identity_cache_key, get_canonical_auth_identity
from core.config import (
    OneDriveBusinessRemote,
    OneDriveRemote,
    SharePointRemote,
)


def test_sharepoint_same_tenant_and_email_deduplicates():
    remote_a = SharePointRemote(
        type="sharepoint",
        base_url="https://company.sharepoint.com",
        site="/sites/team-alpha",
        email="Alice@Company.com",
    )
    remote_b = SharePointRemote(
        type="sharepoint",
        base_url="https://company.sharepoint.com",
        site="/sites/team-beta",
        email="alice@company.com",  # case-insensitive
    )

    ident_a = get_canonical_auth_identity("sp_a", remote_a)
    ident_b = get_canonical_auth_identity("sp_b", remote_b)

    assert ident_a == ident_b == "sharepoint:company.sharepoint.com:alice@company.com"
    assert build_identity_cache_key(ident_a) == build_identity_cache_key(ident_b)


def test_onedrive_business_shares_identity_with_sharepoint():
    remote_odb = OneDriveBusinessRemote(
        type="onedrive_business",
        base_url="https://company-my.sharepoint.com",
        site="/personal/alice_company_com",
        email="alice@company.com",
    )
    ident_odb = get_canonical_auth_identity("odb", remote_odb)
    assert ident_odb == "sharepoint:company-my.sharepoint.com:alice@company.com"


def test_onedrive_graph_deduplication():
    r1 = OneDriveRemote(type="onedrive", client_id="app-123", tenant="common")
    r2 = OneDriveRemote(type="onedrive", client_id="APP-123", tenant="COMMON")

    assert get_canonical_auth_identity("od1", r1) == get_canonical_auth_identity("od2", r2)
