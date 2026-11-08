import unittest

import requests

from auth.base import AuthContext, StaticAuthProvider
from infrastructure.http import HttpClient, RetryPolicy
from providers.microsoft365.client import Microsoft365Client


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.auth = None
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.url = url
        response.request = requests.Request(method, url).prepare()
        return response

    def close(self):
        pass


def response(status, payload):
    value = requests.Response()
    value.status_code = status
    value._content = __import__("json").dumps(payload).encode("utf-8")
    return value


class Microsoft365ClientTests(unittest.TestCase):
    def test_drive_cache_and_metadata_are_shared(self):
        auth = StaticAuthProvider(
            AuthContext(headers={"Cookie": "FedAuth=test"})
        )
        client = Microsoft365Client(
            auth_provider=auth,
            base_url="https://tenant.example.com",
            site="sites/demo",
        )
        fake = FakeSession([
            response(200, {
                "value": [
                    {
                        "id": "drive-1",
                        "name": "Documents",
                        "webUrl": "https://tenant.example.com/Shared Documents",
                    }
                ]
            }),
            response(200, {
                "name": "hello.txt",
                "size": 42,
            }),
        ])
        client.http._local.session = fake

        metadata, url = client.get_v2_metadata("/Documents/hello.txt")

        self.assertEqual(client.drive_id_cache["Documents"], "drive-1")
        self.assertEqual(client.drive_id_cache["Shared Documents"], "drive-1")
        self.assertEqual(metadata["name"], "hello.txt")
        self.assertIn("drives/drive-1/root:/hello.txt", url)
        self.assertEqual(fake.responses, [])

    def test_failed_drive_initialization_does_not_poison_cache(self):
        auth = StaticAuthProvider(AuthContext(headers={"Cookie": "FedAuth=test"}))
        client = Microsoft365Client(
            auth_provider=auth,
            base_url="https://tenant.example.com",
            site="sites/demo",
        )
        client.http = HttpClient(
            retry_policy=RetryPolicy(max_attempts=1)
        )
        fake = FakeSession([
            response(500, {"error": "temporary"}),
            response(200, {"value": []}),
        ])
        client.http._local.session = fake

        with self.assertRaises(requests.HTTPError):
            client.init_drives_cache()

        self.assertIsNone(client.drive_id_cache)

        client.init_drives_cache()
        self.assertEqual(client.drive_id_cache, {})

    def test_sharepoint_and_onedrive_business_headers_and_thumbnail(self):
        from providers.sharepoint import SharePointStorage
        from providers.onedrive_business import OneDriveBusinessStorage

        auth = StaticAuthProvider(AuthContext(headers={"Cookie": "FedAuth=test"}))
        sp = SharePointStorage(auth, "https://tenant.example.com", "sites/demo")
        odb = OneDriveBusinessStorage(auth, "https://tenant.example.com", "personal/user")

        # Test _get_headers with extra
        sp_headers = sp._get_headers({"Accept": "application/json;odata.metadata=minimal"})
        self.assertEqual(sp_headers.get("Accept"), "application/json;odata.metadata=minimal")
        self.assertIn("FedAuth=test", sp_headers.get("Cookie", ""))

        odb_headers = odb._get_headers({"Accept": "application/json;odata.metadata=minimal"})
        self.assertEqual(odb_headers.get("Accept"), "application/json;odata.metadata=minimal")

        # Test SharePoint thumbnail success
        fake_sp_success = FakeSession([
            response(200, {
                "value": [
                    {
                        "large": {"url": "https://cdn.example.com/sp_large.jpg"},
                    }
                ]
            })
        ])
        sp.session._local.session = fake_sp_success
        sp._get_v2_metadata = lambda path: ({"name": "test.mp4"}, "https://tenant.example.com/item")
        url = sp.get_thumbnail_link("/test.mp4")
        self.assertEqual(url, "https://cdn.example.com/sp_large.jpg")

        # Test SharePoint thumbnail 404 maps to ValueError
        fake_sp_404 = FakeSession([response(404, {"error": "itemNotFound"})])
        sp.session._local.session = fake_sp_404
        with self.assertRaises(ValueError):
            sp.get_thumbnail_link("/missing.mp4")

        # Test OneDriveBusiness thumbnail success
        fake_odb_success = FakeSession([
            response(200, {
                "value": [
                    {
                        "medium": {"url": "https://cdn.example.com/odb_med.jpg"},
                    }
                ]
            })
        ])
        odb.session._local.session = fake_odb_success
        odb._get_v2_metadata = lambda path: ({"name": "test.docx"}, "https://tenant.example.com/item")
        odb_url = odb.get_thumbnail_link("/test.docx")
        self.assertEqual(odb_url, "https://cdn.example.com/odb_med.jpg")

        # Test OneDriveBusiness thumbnail 404 maps to ValueError
        fake_odb_404 = FakeSession([response(404, {"error": "itemNotFound"})])
        odb.session._local.session = fake_odb_404
        with self.assertRaises(ValueError):
            odb.get_thumbnail_link("/missing.docx")

    def test_server_relative_path_resolution_with_localized_and_aliases(self):
        auth = StaticAuthProvider(AuthContext(headers={"Cookie": "FedAuth=test"}))
        client = Microsoft365Client(
            auth_provider=auth,
            base_url="https://mailswdpsntpcedutw.sharepoint.com",
            site="/sites/drive",
        )
        fake = FakeSession([
            response(200, {
                "value": [
                    {
                        "id": "drive-main",
                        "name": "文件",
                        "webUrl": "https://mailswdpsntpcedutw.sharepoint.com/sites/drive/Shared%20Documents",
                    }
                ]
            }),
        ])
        client.http._local.session = fake

        # Test aliases and localized names resolve to correct server-relative URL
        self.assertEqual(
            client.get_server_relative_path("/文件"),
            "/sites/drive/Shared Documents",
        )
        self.assertEqual(
            client.get_server_relative_path("Shared Documents"),
            "/sites/drive/Shared Documents",
        )
        self.assertEqual(
            client.get_server_relative_path("/Documents"),
            "/sites/drive/Shared Documents",
        )
        self.assertEqual(
            client.get_server_relative_path("/文件/螢幕擷取畫面 2026-08-10 140132.png"),
            "/sites/drive/Shared Documents/螢幕擷取畫面 2026-08-10 140132.png",
        )
        self.assertEqual(
            client.get_server_relative_path(r"\文件\sub\file.txt"),
            "/sites/drive/Shared Documents/sub/file.txt",
        )
        self.assertEqual(
            client.get_server_relative_path("/sites/drive/Shared Documents/file.txt"),
            "/sites/drive/Shared Documents/file.txt",
        )
        self.assertEqual(
            client.get_server_relative_path(""),
            "/sites/drive",
        )

    def test_sharepoint_crud_operations_use_resolved_server_relative_path(self):
        import tempfile
        import os
        from providers.sharepoint import SharePointStorage

        auth = StaticAuthProvider(AuthContext(headers={"Cookie": "FedAuth=test"}))
        sp = SharePointStorage(
            auth,
            "https://mailswdpsntpcedutw.sharepoint.com",
            "/sites/drive",
        )
        # Pre-seed drives cache
        sp.client._drive_id_cache = {
            "文件": "drive-main",
            "Shared Documents": "drive-main",
            "Documents": "drive-main",
        }
        sp.client._drive_path_cache = {
            "文件": "/sites/drive/Shared Documents",
            "Shared Documents": "/sites/drive/Shared Documents",
            "Documents": "/sites/drive/Shared Documents",
        }
        sp._get_request_digest = lambda: "mock_digest"

        # 1. Test Upload resolving /文件 -> /sites/drive/Shared%20Documents
        fake_upload = FakeSession([response(200, {"name": "test.png"})])
        sp.session._local.session = fake_upload
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"fake_image_content")
            tf_path = tf.name

        try:
            ok = sp.upload(tf_path, "/文件/test.png")
            self.assertTrue(ok)
            self.assertEqual(len(fake_upload.calls), 1)
            method, url, _ = fake_upload.calls[0]
            self.assertEqual(method, "POST")
            self.assertIn("GetFolderByServerRelativeUrl('/sites/drive/Shared%20Documents')/Files/Add", url)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

        # 2. Test mkdir resolving /文件/新資料夾
        fake_mkdir = FakeSession([response(201, {"name": "新資料夾"})])
        sp.session._local.session = fake_mkdir
        ok_mkdir = sp.mkdir("/文件/新資料夾")
        self.assertTrue(ok_mkdir)
        self.assertEqual(len(fake_mkdir.calls), 1)
        method, url, _ = fake_mkdir.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("GetFolderByServerRelativeUrl('/sites/drive/Shared%20Documents')/folders/add", url)

        # 3. Test delete resolving /文件/test.png
        sp._get_v2_metadata = lambda path: ({"name": "test.png", "file": {}}, "https://item")
        fake_delete = FakeSession([response(200, {})])
        sp.session._local.session = fake_delete
        ok_delete = sp.delete("/文件/test.png")
        self.assertTrue(ok_delete)
        self.assertEqual(len(fake_delete.calls), 1)
        method, url, _ = fake_delete.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("GetFileByServerRelativeUrl('/sites/drive/Shared%20Documents/test.png')/recycle", url)


if __name__ == "__main__":
    unittest.main()
