"""
title: Ubuntu SSH Client
author: Open WebUI Community
version: 0.1.0
description: Remote command execution, system diagnostics, and file management on Ubuntu Linux via SSH.
requirements: paramiko
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
from typing import Any, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    # Fallback for local/CLI runs where pydantic is not installed.
    class BaseModel:
        def __init__(self, **kwargs):
            for key in dir(self.__class__):
                if not key.startswith("_"):
                    setattr(self, key, getattr(self.__class__, key))
            for k, v in kwargs.items():
                setattr(self, k, v)

    def Field(default=None, **kwargs):
        return default

try:
    import paramiko
except ImportError:
    paramiko = None  # Handled via subprocess ssh fallback or informative error


class Tools:
    """Ubuntu Linux management and diagnostics tool for Open WebUI via SSH.

    Provides secure command execution, system status monitoring, service control,
    and file access on Ubuntu servers with per-user credential isolation.
    """

    class Valves(BaseModel):
        """Admin/Tool-level connection settings (configured in Workspace > Tools)."""

        SSH_HOST: str = Field(
            default="",
            description="Default Ubuntu server hostname or IP address.",
        )
        SSH_PORT: int = Field(
            default=22,
            description="SSH port number (default: 22).",
        )
        SSH_TIMEOUT: int = Field(
            default=15,
            description="Connection and command execution timeout in seconds.",
        )
        MAX_OUTPUT_CHARS: int = Field(
            default=8000,
            description="Maximum characters of command output to return to the LLM (truncation limit).",
        )
        SSH_USERNAME: str = Field(
            default="ubuntu",
            description="(Optional) Default SSH username for tool-level fallback.",
        )
        SSH_PASSWORD: str = Field(
            default="",
            description="(Optional) Default SSH password.",
            json_schema_extra={"input": {"type": "password"}},
        )
        SSH_KEY: str = Field(
            default="",
            description="(Optional) Default SSH private key (PEM/OpenSSH format).",
            json_schema_extra={"input": {"type": "password"}},
        )

    class UserValves(BaseModel):
        """Per-user connection credentials (saved to the user's Open WebUI profile)."""

        SSH_HOST: str = Field(
            default="",
            description="Personal Ubuntu server hostname or IP address (overrides default if set).",
        )
        SSH_PORT: int = Field(
            default=22,
            description="Personal SSH port number.",
        )
        SSH_USERNAME: str = Field(
            default="",
            description="Personal SSH username (e.g. 'ubuntu').",
        )
        SSH_PASSWORD: str = Field(
            default="",
            description="Personal SSH password.",
            json_schema_extra={"input": {"type": "password"}},
        )
        SSH_KEY: str = Field(
            default="",
            description="Personal SSH private key (OpenSSH/PEM string).",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()
        self._lock = threading.Lock()

    def _resolve_connection_params(
        self,
        override_host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Resolve host, port, username, password, and private key prioritizing UserValves."""
        user_valves = None
        if isinstance(__user__, dict):
            user_valves = __user__.get("valves")

        host = (
            override_host
            or getattr(user_valves, "SSH_HOST", None)
            or (user_valves.get("SSH_HOST") if isinstance(user_valves, dict) else None)
            or self.valves.SSH_HOST
        )
        port = (
            getattr(user_valves, "SSH_PORT", None)
            or (user_valves.get("SSH_PORT") if isinstance(user_valves, dict) else None)
            or self.valves.SSH_PORT
            or 22
        )
        username = (
            getattr(user_valves, "SSH_USERNAME", None)
            or (user_valves.get("SSH_USERNAME") if isinstance(user_valves, dict) else None)
            or self.valves.SSH_USERNAME
        )
        password = (
            getattr(user_valves, "SSH_PASSWORD", None)
            or (user_valves.get("SSH_PASSWORD") if isinstance(user_valves, dict) else None)
            or self.valves.SSH_PASSWORD
        )
        key = (
            getattr(user_valves, "SSH_KEY", None)
            or (user_valves.get("SSH_KEY") if isinstance(user_valves, dict) else None)
            or self.valves.SSH_KEY
        )

        host = host.strip() if host else ""
        username = username.strip() if username else ""
        password = password if password else ""
        key = key.strip() if key else ""

        if not host:
            raise ValueError(
                "SSH host is not configured. Set SSH_HOST in UserValves (chat controls) or tool Valves."
            )
        if not username:
            raise ValueError(
                "SSH username is not configured. Set SSH_USERNAME in UserValves or tool Valves."
            )
        if not password and not key:
            raise ValueError(
                "No SSH credentials provided. Set SSH_PASSWORD or SSH_KEY in UserValves or tool Valves."
            )

        timeout = int(getattr(self.valves, "SSH_TIMEOUT", 15) or 15)
        max_output = int(getattr(self.valves, "MAX_OUTPUT_CHARS", 8000) or 8000)

        return {
            "host": host,
            "port": int(port),
            "username": username,
            "password": password,
            "key": key,
            "timeout": timeout,
            "max_output": max_output,
        }

    def _truncate_output(self, output: str, max_chars: int) -> str:
        """Truncate command output to avoid exhausting LLM token context."""
        if len(output) <= max_chars:
            return output
        truncated_count = len(output) - max_chars
        return (
            output[:max_chars]
            + f"\n\n[... Output truncated: {truncated_count} additional characters omitted. Filter command or use head/tail ...]"
        )

    def _execute_paramiko(
        self,
        command: str,
        params: dict[str, Any],
    ) -> tuple[int, str, str]:
        """Execute command using the paramiko library."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pkey = None
        if params["key"]:
            key_file = io.StringIO(params["key"])
            for key_cls in (
                paramiko.RSAKey,
                paramiko.Ed25519Key,
                paramiko.ECDSAKey,
                paramiko.DSSKey,
            ):
                key_file.seek(0)
                try:
                    pkey = key_cls.from_private_key(key_file, password=params["password"] or None)
                    break
                except Exception:
                    continue
            if not pkey and not params["password"]:
                raise ValueError("Could not parse SSH_KEY. Verify it is a valid PEM/OpenSSH private key.")

        try:
            client.connect(
                hostname=params["host"],
                port=params["port"],
                username=params["username"],
                password=params["password"] or None,
                pkey=pkey,
                timeout=params["timeout"],
                banner_timeout=params["timeout"],
                auth_timeout=params["timeout"],
            )
            stdin, stdout, stderr = client.exec_command(
                command, timeout=params["timeout"]
            )
            out_str = stdout.read().decode("utf-8", errors="replace")
            err_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            return exit_code, out_str, err_str
        finally:
            client.close()

    def _execute_subprocess(
        self,
        command: str,
        params: dict[str, Any],
    ) -> tuple[int, str, str]:
        """Fallback command execution using system ssh CLI if paramiko is unavailable."""
        ssh_bin = shutil.which("ssh")
        if not ssh_bin:
            raise RuntimeError(
                "Neither the 'paramiko' Python library nor the system 'ssh' command is available. "
                "Install paramiko: pip install paramiko"
            )

        cmd = [
            ssh_bin,
            "-p", str(params["port"]),
            "-o", f"ConnectTimeout={params['timeout']}",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",
            f"{params['username']}@{params['host']}",
            command,
        ]

        # Note: subprocess fallback with passwords requires sshpass; private keys work natively
        env = os.environ.copy()
        if params["key"]:
            # If an in-memory key is provided in fallback mode, write to a temp secure file
            import tempfile
            with tempfile.NamedTemporaryFile("w", delete=False, mode="w", encoding="utf-8") as f:
                f.write(params["key"])
                temp_key = f.name
            os.chmod(temp_key, 0o600)
            cmd.insert(1, "-i")
            cmd.insert(2, temp_key)
            try:
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=params["timeout"]
                )
                return (
                    proc.returncode,
                    proc.stdout.decode("utf-8", errors="replace"),
                    proc.stderr.decode("utf-8", errors="replace"),
                )
            finally:
                if os.path.exists(temp_key):
                    os.remove(temp_key)

        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=params["timeout"], env=env
        )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    def _run_remote_command(
        self,
        command: str,
        override_host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> tuple[int, str, str]:
        """Dispatch remote execution with timeout and credential validation."""
        params = self._resolve_connection_params(override_host=override_host, __user__=__user__)

        if paramiko is not None:
            return self._execute_paramiko(command, params)
        return self._execute_subprocess(command, params)

    # -------------------------------------------------------------------------
    # Public Tool Functions (Exposed to Open WebUI / LLM)
    # -------------------------------------------------------------------------

    def execute_command(
        self,
        command: str,
        host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Execute a shell command on the remote Ubuntu server via SSH and return stdout/stderr.

        :param command: The shell command to run on the Ubuntu server (e.g., 'uname -a', 'systemctl status nginx').
        :param host: Optional target host/IP override if different from configured default.
        :return: Formatted string containing the exit code, standard output, and standard error.
        """
        params = self._resolve_connection_params(override_host=host, __user__=__user__)
        try:
            exit_code, stdout, stderr = self._run_remote_command(
                command, override_host=host, __user__=__user__
            )
            result = []
            if exit_code != 0:
                result.append(f"[Exit Status: {exit_code}]")
            if stdout:
                result.append(self._truncate_output(stdout.strip(), params["max_output"]))
            if stderr:
                result.append(f"[stderr]\n{self._truncate_output(stderr.strip(), params['max_output'])}")
            if not stdout and not stderr:
                result.append("(Command produced no output)")
            return "\n".join(result)
        except Exception as e:
            return f"Error executing SSH command: {e}"

    def get_system_status(
        self,
        host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> dict:
        """
        Get an overview of the Ubuntu server status, including OS release, uptime, CPU load, memory, and root disk usage.

        :param host: Optional target host/IP override if different from configured default.
        :return: Dictionary containing parsed system health metrics.
        """
        probe_cmd = (
            "echo '===OS==='; cat /etc/os-release 2>/dev/null; "
            "echo '===UPTIME==='; uptime; "
            "echo '===MEM==='; free -m; "
            "echo '===DISK==='; df -h /"
        )
        try:
            exit_code, stdout, stderr = self._run_remote_command(
                probe_cmd, override_host=host, __user__=__user__
            )
            if exit_code != 0:
                return {"error": f"Status probe failed (exit code {exit_code}): {stderr.strip()}"}

            sections = stdout.split("===")
            status: dict[str, Any] = {}

            for sec in sections:
                if sec.startswith("OS==="):
                    content = sec.replace("OS===", "").strip()
                    for line in content.splitlines():
                        if "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() in ("PRETTY_NAME", "VERSION"):
                                status["os"] = v.strip().strip('"')
                                break
                elif sec.startswith("UPTIME==="):
                    status["uptime_raw"] = sec.replace("UPTIME===", "").strip()
                elif sec.startswith("MEM==="):
                    status["memory_mb"] = sec.replace("MEM===", "").strip().splitlines()
                elif sec.startswith("DISK==="):
                    status["disk_root"] = sec.replace("DISK===", "").strip().splitlines()

            return status if status else {"raw_output": stdout.strip()}
        except Exception as e:
            return {"error": f"Failed to retrieve system status: {e}"}

    def read_file(
        self,
        remote_path: str,
        host: Optional[str] = None,
        max_lines: int = 200,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Read the contents of a text file from the remote Ubuntu server.

        :param remote_path: Absolute path to the file on the remote server (e.g., '/etc/netplan/01-netcfg.yaml').
        :param host: Optional target host/IP override.
        :param max_lines: Maximum number of lines to read (default: 200).
        :return: File contents as string or error message.
        """
        safe_path = remote_path.strip()
        cmd = f"head -n {int(max_lines)} {safe_path}"
        try:
            exit_code, stdout, stderr = self._run_remote_command(
                cmd, override_host=host, __user__=__user__
            )
            if exit_code != 0:
                return f"Error reading file '{safe_path}': {stderr.strip()}"
            params = self._resolve_connection_params(override_host=host, __user__=__user__)
            return self._truncate_output(stdout, params["max_output"])
        except Exception as e:
            return f"Failed to read remote file: {e}"

    def write_file(
        self,
        remote_path: str,
        content: str,
        host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Write or overwrite a file on the remote Ubuntu server with specified text content.

        :param remote_path: Absolute destination path on the remote server (e.g., '/home/ubuntu/script.sh').
        :param content: Text content to write to the file.
        :param host: Optional target host/IP override.
        :return: Status confirmation message.
        """
        safe_path = remote_path.strip()
        # Use base64 encoding to transport arbitrary content without escaping issues
        import base64
        b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f"echo '{b64_content}' | base64 -d > {safe_path}"

        try:
            exit_code, stdout, stderr = self._run_remote_command(
                cmd, override_host=host, __user__=__user__
            )
            if exit_code != 0:
                return f"Error writing file '{safe_path}': {stderr.strip()}"
            return f"Successfully wrote {len(content)} characters to '{safe_path}'."
        except Exception as e:
            return f"Failed to write remote file: {e}"

    def manage_service(
        self,
        service_name: str,
        action: str,
        host: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Control or inspect systemd services on the Ubuntu server (e.g. nginx, docker, ssh).

        :param service_name: Name of the systemd service unit (e.g., 'nginx', 'docker', 'ufw').
        :param action: Action to perform: 'status', 'start', 'stop', 'restart', 'reload', or 'is-active'.
        :param host: Optional target host/IP override.
        :return: Service status or execution result.
        """
        allowed_actions = {"status", "start", "stop", "restart", "reload", "is-active", "enable", "disable"}
        act = action.strip().lower()
        if act not in allowed_actions:
            return f"Invalid action '{action}'. Allowed actions: {', '.join(sorted(allowed_actions))}"

        srv = service_name.strip()
        cmd = f"systemctl {act} {srv}"

        try:
            exit_code, stdout, stderr = self._run_remote_command(
                cmd, override_host=host, __user__=__user__
            )
            output = stdout.strip() or stderr.strip()
            if exit_code == 0:
                return f"[systemctl {act} {srv}: SUCCESS]\n{output}" if output else f"[systemctl {act} {srv}: SUCCESS]"
            return f"[systemctl {act} {srv}: EXIT {exit_code}]\n{output}"
        except Exception as e:
            return f"Failed to manage service '{srv}': {e}"


def main():
    """CLI test entrypoint: verify SSH connectivity to Ubuntu host."""
    tool = Tools()
    print(f"Connecting to Ubuntu host at {tool.valves.SSH_HOST or 'Not configured'}...")
    try:
        res = tool.execute_command("uname -a && uptime")
        print("Output:\n", res)
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    main()
