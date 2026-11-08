import unittest
from unittest.mock import MagicMock, patch
from tools.ubuntu_ssh_client import Tools


class TestUbuntuSSHClient(unittest.TestCase):

    def setUp(self):
        self.tool = Tools()
        self.tool.valves.SSH_HOST = "192.168.1.100"
        self.tool.valves.SSH_PORT = 22
        self.tool.valves.SSH_USERNAME = "ubuntu"
        self.tool.valves.SSH_PASSWORD = "testpassword"
        self.tool.valves.SSH_TIMEOUT = 10
        self.tool.valves.MAX_OUTPUT_CHARS = 100

    def test_resolve_connection_params_precedence(self):
        # 1. Fallback to global valves
        params = self.tool._resolve_connection_params()
        self.assertEqual(params["host"], "192.168.1.100")
        self.assertEqual(params["username"], "ubuntu")
        self.assertEqual(params["password"], "testpassword")

        # 2. UserValves takes precedence
        class UserValvesMock:
            SSH_HOST = "10.0.0.50"
            SSH_PORT = 2222
            SSH_USERNAME = "customuser"
            SSH_PASSWORD = "userpass"
            SSH_KEY = ""

        user_ctx = {"id": "user_456", "valves": UserValvesMock()}
        params = self.tool._resolve_connection_params(__user__=user_ctx)
        self.assertEqual(params["host"], "10.0.0.50")
        self.assertEqual(params["port"], 2222)
        self.assertEqual(params["username"], "customuser")
        self.assertEqual(params["password"], "userpass")

    def test_resolve_missing_credentials(self):
        self.tool.valves.SSH_PASSWORD = ""
        self.tool.valves.SSH_KEY = ""
        with self.assertRaises(ValueError):
            self.tool._resolve_connection_params()

    def test_truncate_output(self):
        short_text = "Hello world"
        self.assertEqual(self.tool._truncate_output(short_text, 50), short_text)

        long_text = "A" * 200
        truncated = self.tool._truncate_output(long_text, 50)
        self.assertTrue(truncated.startswith("A" * 50))
        self.assertIn("truncated", truncated)

    @patch.object(Tools, "_run_remote_command")
    def test_execute_command_success(self, mock_run):
        mock_run.return_value = (0, "Linux ubuntu 5.15.0-generic", "")
        res = self.tool.execute_command("uname -r")
        self.assertEqual(res, "Linux ubuntu 5.15.0-generic")

    @patch.object(Tools, "_run_remote_command")
    def test_execute_command_nonzero_exit(self, mock_run):
        mock_run.return_value = (1, "", "command not found")
        res = self.tool.execute_command("foobar")
        self.assertIn("[Exit Status: 1]", res)
        self.assertIn("command not found", res)

    @patch.object(Tools, "_run_remote_command")
    def test_manage_service(self, mock_run):
        # 1. Invalid action rejected
        err = self.tool.manage_service("nginx", "destroy")
        self.assertIn("Invalid action", err)

        # 2. Valid action executes systemctl
        mock_run.return_value = (0, "Active: active (running)", "")
        res = self.tool.manage_service("nginx", "status")
        self.assertIn("SUCCESS", res)
        self.assertIn("active (running)", res)
        mock_run.assert_called_with("systemctl status nginx", override_host=None, __user__=None)

    @patch.object(Tools, "_run_remote_command")
    def test_write_file_base64_transport(self, mock_run):
        mock_run.return_value = (0, "", "")
        res = self.tool.write_file("/tmp/test.txt", "Hello World\nLine 2")
        self.assertIn("Successfully wrote", res)
        # Verify base64 transport is used
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("base64 -d > /tmp/test.txt", called_cmd)


if __name__ == "__main__":
    unittest.main()
