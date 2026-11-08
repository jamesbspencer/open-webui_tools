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

from tools.openwrt_client import Tools


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


class TestOpenWrtClient(unittest.TestCase):

    def setUp(self):
        self.tool = Tools()
        self.tool.valves.OPENWRT_URL = "http://192.168.1.1"
        self.tool.valves.OPENWRT_RPC_PATH = "/ubus"
        self.tool.valves.REQUEST_TIMEOUT = 10

    def tearDown(self):
        self.tool.close()

    def test_user_token_cache_isolation(self):
        user1 = {"id": "user_alpha"}
        user2 = {"id": "user_beta"}

        key1 = self.tool._get_user_key(user1, "root")
        key2 = self.tool._get_user_key(user2, "root")

        self.assertEqual(key1, "user_alpha:root")
        self.assertEqual(key2, "user_beta:root")
        self.assertNotEqual(key1, key2)

    def test_login_and_token_caching(self):
        with patch.object(self.tool.session, "post") as mock_post:
            mock_post.return_value = MockResponse(
                200, {"result": [0, {"ubus_rpc_session": "session_tok_999"}]}
            )

            user_ctx = {"id": "test_user"}
            session_id = self.tool._login("root", "adminpass", __user__=user_ctx)
            self.assertEqual(session_id, "session_tok_999")
            self.assertIn("test_user:root", self.tool.tokens)

    def test_reboot_system_guards(self):
        # 1. Aborted if confirm is False
        res = self.tool.reboot_system(confirm=False)
        self.assertIn("confirm", res)

        # 2. Blocked if user is not admin
        user_regular = {"id": "user_1", "role": "user"}
        with self.assertRaises(PermissionError):
            self.tool.reboot_system(confirm=True, __user__=user_regular)

        # 3. Allowed if user is admin
        user_admin = {"id": "admin_1", "role": "admin"}
        with patch.object(self.tool, "_ubus_call") as mock_ubus:
            msg = self.tool.reboot_system(confirm=True, __user__=user_admin)
            self.assertIn("rebooting", msg)
            mock_ubus.assert_called_with("system", "reboot", {}, __user__=user_admin)

    def test_call_ubus_security_checks(self):
        # 1. file.exec is blocked unconditionally
        with self.assertRaises(PermissionError):
            self.tool.call_ubus("file", "exec", {"command": "ls"})

        with self.assertRaises(PermissionError):
            self.tool.call_ubus("file", "write", {"path": "/etc/rc.local"})

        # 2. Non-allowlist procedure blocked for regular user
        user_regular = {"id": "user_1", "role": "user"}
        with self.assertRaises(PermissionError):
            self.tool.call_ubus("custom_service", "do_something", {}, __user__=user_regular)

        # 3. Safe allowlist procedure allowed for regular user
        with patch.object(self.tool, "_ubus_call") as mock_ubus:
            mock_ubus.return_value = {"uptime": 120}
            res = self.tool.call_ubus("system", "info", {}, __user__=user_regular)
            self.assertEqual(res, {"uptime": 120})

    def test_uci_get_sensitive_redaction(self):
        raw_config = {
            "default_radio0": {
                "ssid": "MyHomeWifi",
                "key": "SuperSecretWifiPassword!",
                "encryption": "psk2",
            },
            "vpn": {
                "private_key": "my_wireguard_key",
                "endpoint": "vpn.example.com",
            },
        }

        with patch.object(self.tool, "_ubus_call", return_value=raw_config):
            cleaned = self.tool.uci_get("wireless")
            self.assertEqual(cleaned["default_radio0"]["key"], "******")
            self.assertEqual(cleaned["default_radio0"]["ssid"], "MyHomeWifi")
            self.assertEqual(cleaned["vpn"]["private_key"], "******")

    def test_timeout_and_context_manager(self):
        self.tool.valves.REQUEST_TIMEOUT = 20
        self.assertEqual(self.tool._timeout, (5.0, 20.0))

        with Tools() as t:
            self.assertIsNotNone(t.session)


if __name__ == "__main__":
    unittest.main()
