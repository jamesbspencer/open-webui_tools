import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Ensure test suite runs even on clean environments without external requests/urllib3 installed
try:
    import requests
except ImportError:
    mock_requests = types.ModuleType("requests")
    class HTTPError(Exception):
        pass
    class ConnectionError(Exception):
        pass
    class Timeout(Exception):
        pass
    mock_requests.HTTPError = HTTPError
    mock_requests.exceptions = types.SimpleNamespace(
        ConnectionError=ConnectionError, Timeout=Timeout
    )
    class DummySession:
        def __init__(self):
            self.headers = {}
            self.cookies = types.SimpleNamespace(clear=lambda: None)
        def close(self):
            pass
        def post(self, *args, **kwargs):
            return None
        def get(self, *args, **kwargs):
            return None
        def request(self, *args, **kwargs):
            return None
    mock_requests.Session = DummySession
    sys.modules["requests"] = mock_requests

try:
    import urllib3
except ImportError:
    mock_urllib3 = types.ModuleType("urllib3")
    mock_urllib3.disable_warnings = lambda *args, **kwargs: None
    mock_urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Exception)
    sys.modules["urllib3"] = mock_urllib3

from tools.openbao_client import Tools


class MockResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestOpenBaoClient(unittest.TestCase):

    def setUp(self):
        self.tool = Tools()
        self.tool.valves.OPENBAO_ADDR = "https://vault.example.com"
        self.tool.valves.SECRETS_MOUNT = "kv"
        self.tool.valves.REQUEST_TIMEOUT = 10

    def tearDown(self):
        self.tool.close()

    def test_resolve_credentials_precedence(self):
        self.tool.valves.OPENBAO_USERNAME = "global_user"
        self.tool.valves.OPENBAO_PASSWORD = "global_password"

        # 1. Fallback to global valves when __user__ is None
        u, p = self.tool._resolve_credentials()
        self.assertEqual(u, "global_user")
        self.assertEqual(p, "global_password")

        # 2. UserValves takes precedence
        class UserValvesMock:
            OPENBAO_USERNAME = "personal_user"
            OPENBAO_PASSWORD = "personal_password"

        user_ctx = {"id": "user123", "valves": UserValvesMock()}
        u, p = self.tool._resolve_credentials(__user__=user_ctx)
        self.assertEqual(u, "personal_user")
        self.assertEqual(p, "personal_password")

    def test_user_token_cache_isolation(self):
        user1 = {"id": "user_1"}
        user2 = {"id": "user_2"}

        key1 = self.tool._get_user_key(user1, "alice")
        key2 = self.tool._get_user_key(user2, "alice")

        self.assertEqual(key1, "user_1:alice")
        self.assertEqual(key2, "user_2:alice")
        self.assertNotEqual(key1, key2)

    def test_sanitize_path(self):
        self.assertEqual(self.tool._sanitize_path("foo/bar"), "foo/bar")
        self.assertEqual(self.tool._sanitize_path("/foo/bar/"), "foo/bar")
        self.assertEqual(self.tool._sanitize_path("foo//bar"), "foo/bar")

        # Path traversal should raise ValueError
        with self.assertRaises(ValueError):
            self.tool._sanitize_path("../secret")

        with self.assertRaises(ValueError):
            self.tool._sanitize_path("foo/../../secret")

    def test_login_success_and_cache(self):
        with patch.object(self.tool.session, "post") as mock_post:
            mock_post.return_value = MockResponse(
                200, {"auth": {"client_token": "token_abc123"}}
            )

            user_ctx = {"id": "user_test"}
            token = self.tool._login("testuser", "secretpass", __user__=user_ctx)
            self.assertEqual(token, "token_abc123")
            self.assertIn("user_test:testuser", self.tool.tokens)

    @patch.object(Tools, "_request_with_auth")
    def test_kv_v2_url_construction(self, mock_request):
        mock_request.return_value = MockResponse(
            200, {"data": {"keys": ["db_password", "api_key"]}}
        )

        # 1. Root listing
        keys = self.tool.list_secrets()
        self.assertEqual(keys, ["db_password", "api_key"])
        mock_request.assert_called_with(
            "GET", "https://vault.example.com/v1/kv/metadata?list=true", __user__=None
        )

        # 2. Subfolder listing
        self.tool.list_secrets("subfolder")
        mock_request.assert_called_with(
            "GET", "https://vault.example.com/v1/kv/metadata/subfolder?list=true", __user__=None
        )

        # 3. Read secret (KV v2 /data/ segment)
        mock_request.return_value = MockResponse(
            200, {"data": {"data": {"username": "admin", "password": "123"}}}
        )
        data = self.tool.read_secret("app/config")
        self.assertEqual(data, {"username": "admin", "password": "123"})
        mock_request.assert_called_with(
            "GET", "https://vault.example.com/v1/kv/data/app/config", __user__=None
        )

        # 4. Write secret (KV v2 /data/ segment with POST)
        mock_request.return_value = MockResponse(200, {"data": {"version": 2}})
        res = self.tool.write_secret("app/config", {"key": "value"})
        self.assertEqual(res, {"data": {"version": 2}})
        mock_request.assert_called_with(
            "POST", "https://vault.example.com/v1/kv/data/app/config", __user__=None, json={"data": {"key": "value"}}
        )

    def test_timeout_and_context_manager(self):
        self.tool.valves.REQUEST_TIMEOUT = 15
        self.assertEqual(self.tool._timeout, (5.0, 15.0))

        with Tools() as t:
            self.assertIsNotNone(t.session)


if __name__ == "__main__":
    unittest.main()
