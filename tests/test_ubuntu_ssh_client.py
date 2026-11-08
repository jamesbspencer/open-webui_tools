import subprocess
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

    def test_host_override_security_check(self):
        # 1. Non-admin without personal credentials blocked from overriding host
        user_regular = {"id": "user_reg", "role": "user"}
        with self.assertRaises(PermissionError):
            self.tool._resolve_connection_params(override_host="attacker.com", __user__=user_regular)

        # 2. Admin allowed to override host
        user_admin = {"id": "admin_1", "role": "admin"}
        params = self.tool._resolve_connection_params(override_host="target.lan", __user__=user_admin)
        self.assertEqual(params["host"], "target.lan")

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
    def test_get_system_status_parsing(self, mock_run):
        probe_stdout = (
            "<<<SECTION:OS>>>\n"
            "PRETTY_NAME=\"Ubuntu 22.04.4 LTS\"\n"
            "NAME=\"Ubuntu\"\n"
            "VERSION_ID=\"22.04\"\n"
            "<<<SECTION:UPTIME>>>\n"
            " 14:22:01 up 12 days,  3:40,  1 user,  load average: 0.12, 0.08, 0.05\n"
            "<<<SECTION:MEM>>>\n"
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:           15891        4201        8102         120        3587       11280\n"
            "<<<SECTION:DISK>>>\n"
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1        98G   32G   62G  35% /\n"
        )
        mock_run.return_value = (0, probe_stdout, "")
        status = self.tool.get_system_status()
        self.assertIn("os", status)
        self.assertEqual(status["os"], "Ubuntu 22.04.4 LTS")
        self.assertIn("uptime_raw", status)
        self.assertIn("12 days", status["uptime_raw"])
        self.assertIn("memory_mb", status)
        self.assertIn("disk_root", status)

    @patch.object(Tools, "_run_remote_command")
    def test_read_file_quoting(self, mock_run):
        mock_run.return_value = (0, "server { listen 80; }", "")
        res = self.tool.read_file("/etc/nginx/sites available/default.conf", max_lines=50)
        self.assertEqual(res, "server { listen 80; }")
        called_cmd = mock_run.call_args[0][0]
        # Verify path with spaces is properly shell-quoted
        self.assertIn("'/etc/nginx/sites available/default.conf'", called_cmd)

    @patch.object(Tools, "_run_remote_command")
    def test_manage_service(self, mock_run):
        # 1. Invalid action rejected
        err = self.tool.manage_service("nginx", "destroy")
        self.assertIn("Invalid action", err)

        # 2. Invalid service name with injection attempt rejected
        err_inj = self.tool.manage_service("nginx; reboot", "status")
        self.assertIn("Invalid service name", err_inj)

        # 3. Valid action executes systemctl with quoting
        mock_run.return_value = (0, "Active: active (running)", "")
        res = self.tool.manage_service("nginx", "status")
        self.assertIn("SUCCESS", res)
        self.assertIn("active (running)", res)
        mock_run.assert_called_with("systemctl status nginx", override_host=None, __user__=None)

    @patch.object(Tools, "_run_remote_command")
    def test_write_file_base64_transport(self, mock_run):
        mock_run.return_value = (0, "", "")
        res = self.tool.write_file("/tmp/app config.txt", "Hello World\nLine 2")
        self.assertIn("Successfully wrote", res)
        called_cmd = mock_run.call_args[0][0]
        # Verify base64 transport and shlex quoting on path with spaces
        self.assertIn("base64 -d > '/tmp/app config.txt'", called_cmd)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_execute_subprocess_with_temp_key(self, mock_subproc, mock_which):
        mock_which.return_value = "/usr/bin/ssh"
        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/ssh"], returncode=0, stdout=b"Linux Ubuntu\n", stderr=b""
        )
        params = {
            "host": "192.168.1.50",
            "port": 22,
            "username": "ubuntu",
            "password": "",
            "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
            "timeout": 10,
            "max_output": 5000,
        }
        ret, out, err = self.tool._execute_subprocess("uptime", params)
        self.assertEqual(ret, 0)
        self.assertIn("Linux Ubuntu", out)
        # Verify subprocess was called with -i flag for temp key
        called_cmd = mock_subproc.call_args[0][0]
        self.assertIn("-i", called_cmd)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_execute_subprocess_with_sshpass_password(self, mock_subproc, mock_which):
        def fake_which(cmd):
            if cmd in ("ssh", "sshpass"):
                return f"/usr/bin/{cmd}"
            return None

        mock_which.side_effect = fake_which
        mock_subproc.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/sshpass"], returncode=0, stdout=b"Linux Ubuntu\n", stderr=b""
        )
        params = {
            "host": "192.168.1.50",
            "port": 22,
            "username": "ubuntu",
            "password": "secretpassword",
            "key": "",
            "timeout": 10,
            "max_output": 5000,
        }
        ret, out, err = self.tool._execute_subprocess("uptime", params)
        self.assertEqual(ret, 0)
        called_cmd = mock_subproc.call_args[0][0]
        called_kwargs = mock_subproc.call_args[1]
        self.assertEqual(called_cmd[:2], ["/usr/bin/sshpass", "-e"])
        self.assertEqual(called_kwargs["env"]["SSHPASS"], "secretpassword")
        self.assertNotIn("BatchMode=yes", " ".join(called_cmd))

    @patch("shutil.which")
    def test_execute_subprocess_password_missing_sshpass(self, mock_which):
        mock_which.side_effect = lambda cmd: "/usr/bin/ssh" if cmd == "ssh" else None
        params = {
            "host": "192.168.1.50",
            "port": 22,
            "username": "ubuntu",
            "password": "secretpassword",
            "key": "",
            "timeout": 10,
            "max_output": 5000,
        }
        with self.assertRaises(RuntimeError) as ctx:
            self.tool._execute_subprocess("uptime", params)
        self.assertIn("sshpass", str(ctx.exception))

    def test_execute_paramiko_stream_reading(self):
        import sys
        fake_paramiko = MagicMock()
        mock_client = MagicMock()
        fake_paramiko.SSHClient.return_value = mock_client
        fake_paramiko.AutoAddPolicy = MagicMock

        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_stdout.read.return_value = b"Linux 6.8.0-generic x86_64\n"
        mock_stderr.read.return_value = b"warning: non-fatal warning\n"
        mock_channel = MagicMock()
        mock_channel.recv_exit_status.return_value = 0
        mock_stdout.channel = mock_channel

        mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)

        with patch.dict(sys.modules, {"paramiko": fake_paramiko}):
            # Temporarily set module-level paramiko
            import tools.ubuntu_ssh_client as usc_mod
            orig_paramiko = usc_mod.paramiko
            usc_mod.paramiko = fake_paramiko
            try:
                params = {
                    "host": "192.168.1.50",
                    "port": 22,
                    "username": "ubuntu",
                    "password": "pwd",
                    "key": "",
                    "timeout": 10,
                    "max_output": 5000,
                }
                code, out, err = self.tool._execute_paramiko("uname -a", params)
                self.assertEqual(code, 0)
                self.assertEqual(out, "Linux 6.8.0-generic x86_64\n")
                self.assertEqual(err, "warning: non-fatal warning\n")
                mock_stdout.read.assert_called_once()
                mock_stderr.read.assert_called_once()
                mock_stdin.close.assert_called_once()
            finally:
                usc_mod.paramiko = orig_paramiko


if __name__ == "__main__":
    unittest.main()
