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

    def request(self, method, url, **kwargs):
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


if __name__ == "__main__":
    unittest.main()
