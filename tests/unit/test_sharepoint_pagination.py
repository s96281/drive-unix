from datetime import datetime, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from domain.models import FileItem
from providers.sharepoint import SharePointStorage, _set_url_query_param


def _create_mock_sharepoint_storage():
    mock_auth = MagicMock()
    storage = SharePointStorage(
        auth_provider=mock_auth,
        base_url="https://contoso.sharepoint.com",
        site="/sites/test",
    )
    # Mock session
    storage.session = MagicMock()
    storage._get_headers = MagicMock(return_value={"Authorization": "Bearer test"})
    return storage


def test_set_url_query_param_helper():
    url = "https://contoso.sharepoint.com/_api/v2.0/drive/root/children?%24skiptoken=abc&%24top=1000"
    res = _set_url_query_param(url, "$top", 50)
    parsed = urlparse(res)
    qs = parse_qs(parsed.query)
    assert qs["$top"] == ["50"]
    assert qs["$skiptoken"] == ["abc"]
    assert "1000" not in res


def test_sharepoint_list_dir_zero_or_negative_limit():
    storage = _create_mock_sharepoint_storage()
    # Zero or negative limit should return empty list immediately with 0 network calls
    assert storage.list_dir("folder", offset=0, limit=0) == []
    assert storage.list_dir("folder", offset=10, limit=-5) == []
    assert storage.session.get.call_count == 0


def test_sharepoint_list_dir_single_request_sliding_window():
    storage = _create_mock_sharepoint_storage()
    storage._get_v2_metadata = MagicMock(
        return_value=({"folder": {}}, "https://contoso.sharepoint.com/_api/v2.0/drives/d1/items/item1")
    )

    # User asks for offset=0, limit=20
    # Simulated 20 items returned by SharePoint
    mock_items = [
        {
            "name": f"file_{i}.txt",
            "size": 100 * (i + 1),
            "fileSystemInfo": {"lastModifiedDateTime": "2026-10-01T12:00:00Z"},
        }
        for i in range(20)
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("Documents/subfolder", offset=0, limit=20)

    assert len(items) == 20
    assert items[0].name == "file_0.txt"
    assert items[-1].name == "file_19.txt"

    # Verify exactly 1 request was sent with $top=20
    assert storage.session.get.call_count == 1
    called_url = storage.session.get.call_args[0][0]
    parsed = urlparse(called_url)
    qs = parse_qs(parsed.query)
    assert qs["$top"] == ["20"]


def test_sharepoint_list_dir_offset_window_single_request():
    storage = _create_mock_sharepoint_storage()
    storage._get_v2_metadata = MagicMock(
        return_value=({"folder": {}}, "https://contoso.sharepoint.com/_api/v2.0/drives/d1/items/item1")
    )

    # User asks for offset=50, limit=30 -> target_end = 80
    # First window should be min(80, 1000) = 80
    mock_items = [
        {
            "name": f"file_{i}.txt",
            "size": 100,
            "fileSystemInfo": {"lastModifiedDateTime": "2026-10-01T12:00:00Z"},
        }
        for i in range(80)
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("Documents/subfolder", offset=50, limit=30)

    assert len(items) == 30
    assert items[0].name == "file_50.txt"
    assert items[-1].name == "file_79.txt"

    assert storage.session.get.call_count == 1
    called_url = storage.session.get.call_args[0][0]
    parsed = urlparse(called_url)
    qs = parse_qs(parsed.query)
    assert qs["$top"] == ["80"]


def test_sharepoint_list_dir_multipage_minimal_requests_with_sliding_window(monkeypatch):
    storage = _create_mock_sharepoint_storage()
    # Use root drive item endpoint so default_max_page_size is 200
    storage._get_v2_metadata = MagicMock(
        return_value=({"folder": {}}, "https://contoso.sharepoint.com/_api/v2.0/drives/d1/root")
    )

    # User wants offset=250, limit=60 -> target_end = 310
    # Max page size is 200.
    # Page 1: $top=min(310, 200)=200 items, returns @odata.nextLink
    # Page 2: remaining = 310 - 200 = 110 items. $top should dynamically shrink to 110!
    # Total requests should be exactly 2!
    page1_items = [{"name": f"item_{i}", "folder": {}} for i in range(200)]
    page2_items = [{"name": f"item_{i}", "folder": {}} for i in range(200, 310)]

    resp1 = MagicMock()
    resp1.json.return_value = {
        "value": page1_items,
        "@odata.nextLink": "https://contoso.sharepoint.com/_api/v2.0/drives/d1/root/children?$top=200&$skiptoken=token_abc",
    }

    resp2 = MagicMock()
    resp2.json.return_value = {
        "value": page2_items,
        "@odata.nextLink": "https://contoso.sharepoint.com/_api/v2.0/drives/d1/root/children?$top=110&$skiptoken=token_def",
    }

    storage.session.get.side_effect = [resp1, resp2]

    items = storage.list_dir("Shared Documents", offset=250, limit=60)

    # Verify result slice
    assert len(items) == 60
    assert items[0].name == "item_250"
    assert items[-1].name == "item_309"

    # Verify requests count is the minimal required (2)
    assert storage.session.get.call_count == 2

    # Check request 1 query
    url1 = storage.session.get.call_args_list[0][0][0]
    qs1 = parse_qs(urlparse(url1).query)
    assert qs1["$top"] == ["200"]

    # Check request 2 query: sliding window shrank $top to exactly 110!
    url2 = storage.session.get.call_args_list[1][0][0]
    qs2 = parse_qs(urlparse(url2).query)
    assert qs2["$top"] == ["110"]
    assert qs2["$skiptoken"] == ["token_abc"]


def test_sharepoint_list_dir_fewer_items_than_requested():
    storage = _create_mock_sharepoint_storage()
    storage._get_v2_metadata = MagicMock(
        return_value=({"folder": {}}, "https://contoso.sharepoint.com/_api/v2.0/drives/d1/items/item1")
    )

    # Folder has only 45 items, caller asked offset=30, limit=50 (target_end=80)
    mock_items = [{"name": f"file_{i}.txt"} for i in range(45)]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}  # No nextLink
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("Documents/small_folder", offset=30, limit=50)

    assert len(items) == 15
    assert items[0].name == "file_30.txt"
    assert items[-1].name == "file_44.txt"
    assert storage.session.get.call_count == 1


def test_sharepoint_list_dir_all_items_backward_compatible():
    storage = _create_mock_sharepoint_storage()
    storage._get_v2_metadata = MagicMock(
        return_value=({"folder": {}}, "https://contoso.sharepoint.com/_api/v2.0/drives/d1/items/item1")
    )

    mock_items = [{"name": f"file_{i}.txt"} for i in range(15)]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}
    storage.session.get.return_value = mock_resp

    # No offset or limit passed (default offset=0, limit=None)
    items = storage.list_dir("Documents/folder")
    assert len(items) == 15
    assert items[0].name == "file_0.txt"
    assert storage.session.get.call_count == 1
    url = storage.session.get.call_args[0][0]
    assert "$top=1000" in url


def test_sharepoint_list_dir_root_drives_pagination():
    storage = _create_mock_sharepoint_storage()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "value": [
            {"name": "drive1", "webUrl": "https://.../DriveOne"},
            {"name": "drive2", "webUrl": "https://.../DriveTwo"},
            {"name": "drive3", "webUrl": "https://.../DriveThree"},
            {"name": "drive4", "webUrl": "https://.../DriveFour"},
        ]
    }
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("/", offset=1, limit=2)
    assert len(items) == 2
    assert items[0].name == "DriveTwo"
    assert items[1].name == "DriveThree"
    assert items.total_count == 4


def test_sharepoint_list_dir_total_count_from_childcount():
    storage = _create_mock_sharepoint_storage()
    storage._get_v2_metadata = MagicMock(
        return_value=(
            {"folder": {"childCount": 4500}},
            "https://contoso.sharepoint.com/_api/v2.0/drives/d1/items/item1",
        )
    )

    mock_items = [{"name": f"file_{i}.txt"} for i in range(50)]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("Documents/large_folder", offset=0, limit=50)
    assert len(items) == 50
    assert hasattr(items, "total_count")
    assert items.total_count == 4500
    assert storage.session.get.call_count == 1

