import unittest
from unittest.mock import patch

from providers.ftp import FTPStorage
try:
    from providers.sftp import SFTPStorage
except ModuleNotFoundError:
    SFTPStorage = None


class FakeFTP:
    def __init__(self):
        self.sock = object()
        self.closed = False
        self.noop_calls = 0

    def connect(self, *args, **kwargs):
        return None

    def login(self, *args, **kwargs):
        return None

    def set_pasv(self, *args, **kwargs):
        return None

    def voidcmd(self, command):
        self.noop_calls += 1
        return "200 OK"

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class FakeSFTP:
    def close(self):
        return None


class FakeTransport:
    def is_active(self):
        return True


class FakeSSH:
    def __init__(self):
        self.sftp = FakeSFTP()

    def get_transport(self):
        return FakeTransport()

    def close(self):
        return None


class ConnectionReuseTests(unittest.TestCase):
    def test_ftp_reuses_connection_on_same_thread(self):
        ftp = FakeFTP()
        provider = FTPStorage("example.test")
        with patch.object(provider, "_create_connection", return_value=ftp) as create:
            with provider._get_connection() as first:
                pass
            with provider._get_connection() as second:
                pass

        self.assertIs(first, second)
        create.assert_called_once()
        self.assertEqual(ftp.noop_calls, 1)

    @unittest.skipIf(SFTPStorage is None, "paramiko is not installed in the test environment")
    def test_sftp_reuses_connection_on_same_thread(self):
        provider = SFTPStorage("example.test", 22, "user")
        pair = (FakeSSH(), FakeSFTP())
        with patch.object(provider, "_create_connection", return_value=pair) as create:
            with provider._get_connection() as first:
                pass
            with provider._get_connection() as second:
                pass

        self.assertIs(first, second)
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
