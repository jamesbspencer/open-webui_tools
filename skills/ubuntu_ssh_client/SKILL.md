---
name: ubuntu-ssh-client
description: >-
  Operational runbook and guidance for executing remote commands, inspecting system health,
  managing systemd services, and editing files on Ubuntu Linux servers via SSH using the Open WebUI Tools client.
---

# Ubuntu SSH Client Skill

This skill guides the operation, diagnostic runbooks, and troubleshooting procedures for managing remote Ubuntu Linux servers using the Open WebUI SSH client ([`tools/ubuntu_ssh_client.py`](file:///Users/jspencer/projects/open-webui_tools/tools/ubuntu_ssh_client.py)).

---

## 1. Architecture & Security Model

The client enables Open WebUI LLMs to interact with remote Ubuntu machines over standard SSH (port 22) using either `paramiko` or system `ssh`:

```mermaid
flowchart TD
    UserChat["User in Open WebUI Chat"] -->|"Asks to inspect server / run command"| CheckCreds{"UserValves or Valves credentials"}
    CheckCreds --> Resolve["Resolve Host, Port, User, Key / Password"]
    Resolve --> Connect["SSH Handshake & Authentication"]
    Connect --> Exec["Execute remote command with timeout"]
    Exec --> Truncate["Enforce MAX_OUTPUT_CHARS truncation limit"]
    Truncate --> Return["Return formatted stdout/stderr to LLM"]
```

### Security Controls & Multi-Tenant Isolation
- **Per-User Credentials (`UserValves`)**: Each chat user can supply their own personal SSH username, password, or private key (stored in their Open WebUI profile). One user cannot access another user's server credentials.
- **Masked Secrets**: `SSH_PASSWORD` and `SSH_KEY` are marked with `json_schema_extra={"input": {"type": "password"}}` to ensure they are masked in the UI and never printed in logs or LLM context.
- **Context-Safe Output Limits**: Output is truncated at `MAX_OUTPUT_CHARS` (default: 8,000 chars) to prevent unbounded terminal output from exhausting LLM context windows.
- **Timeouts**: All connections and commands enforce `SSH_TIMEOUT` (default: 15 seconds) to prevent frozen worker threads.

---

## 2. Configuration Tiers

### Tool-Level Valves (`Valves`)
Configured in Open WebUI under **Workspace > Tools > Settings**:
- `SSH_HOST`: Default server hostname or IP address.
- `SSH_PORT`: SSH port (default: 22).
- `SSH_TIMEOUT`: Command and connection timeout in seconds (default: 15).
- `MAX_OUTPUT_CHARS`: Maximum characters returned per command (default: 8000).
- `SSH_USERNAME` / `SSH_PASSWORD` / `SSH_KEY`: Optional fallback credentials.

### User-Specific Valves (`UserValves`)
Configured by each user under chat session **Controls > Valves**:
- `SSH_HOST`: Personal server hostname or IP (overrides tool default if set).
- `SSH_PORT`: Personal SSH port.
- `SSH_USERNAME`: Personal SSH username (e.g. `ubuntu`).
- `SSH_PASSWORD`: Personal password (if password auth is used).
- `SSH_KEY`: Personal SSH private key in PEM or OpenSSH format (e.g. `-----BEGIN OPENSSH PRIVATE KEY-----`).

---

## 3. Tool Methods & Common Operational Workflows

### 1. Remote Shell Commands
- **Method**: `execute_command(command, host=None)`
- **Common Tasks**:
  - Check disk space: `execute_command("df -h")`
  - Check process list: `execute_command("ps aux --sort=-%mem | head -n 15")`
  - Review network sockets: `execute_command("ss -tulpn")`
  - Check Docker containers: `execute_command("docker ps")`

### 2. System Status Overview
- **Method**: `get_system_status(host=None)`
- **Behavior**: Executes a low-overhead composite probe inspecting `/etc/os-release`, `uptime`, `free -m`, and root disk usage `df -h /`.
- **Output**: Structured dictionary containing OS version, uptime, memory, and disk health.

### 3. File Operations
- **Method**: `read_file(remote_path, host=None, max_lines=200)`
  - Reads configuration files (e.g. `/etc/nginx/nginx.conf`, `/etc/netplan/01-netcfg.yaml`).
- **Method**: `write_file(remote_path, content, host=None)`
  - Safely writes remote files using Base64 encoding to prevent escaping issues with quotes or special characters.

### 4. Systemd Service Management
- **Method**: `manage_service(service_name, action, host=None)`
- **Allowed Actions**: `status`, `start`, `stop`, `restart`, `reload`, `is-active`, `enable`, `disable`.
- **Examples**:
  - `manage_service(service_name="nginx", action="status")`
  - `manage_service(service_name="docker", action="restart")`

---

## 4. Standalone CLI Runbook

To test SSH connectivity outside of Open WebUI:

```bash
python3 tools/ubuntu_ssh_client.py
```

### Interactive Python Test
```python
from tools.ubuntu_ssh_client import Tools

tool = Tools()
tool.valves.SSH_HOST = "192.168.1.50"
tool.valves.SSH_USERNAME = "ubuntu"
tool.valves.SSH_KEY = open("/Users/jspencer/.ssh/id_rsa").read()

status = tool.get_system_status()
print("System Status:", status)

res = tool.execute_command("uptime")
print("Uptime:", res)
```

---

## 5. Troubleshooting Common Issues

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **`Authentication failed`** | Incorrect username, password, or key mismatch. | Re-check `SSH_USERNAME`, `SSH_PASSWORD`, or verify the public key is in `~/.ssh/authorized_keys` on Ubuntu. |
| **`Could not parse SSH_KEY`** | Key format not recognized or encrypted without passphrase. | Supply unencrypted OpenSSH or RSA PEM private key string. |
| **`Connection timed out`** | Firewall blocking port 22 or incorrect IP. | Verify target host IP and security group / `ufw status` allowing port 22. |
| **`Command output truncated`** | Command produced more characters than `MAX_OUTPUT_CHARS`. | Use `grep`, `head`, or `tail` in the command to filter output, or increase `MAX_OUTPUT_CHARS` in Valves. |
| **`Permission denied (sudo)`** | Command requires root privileges. | Configure passwordless sudo in `/etc/sudoers` (`ubuntu ALL=(ALL) NOPASSWD:ALL`) for maintenance scripts. |
