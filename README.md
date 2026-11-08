# Open WebUI Tools

A collection of custom tools and extensions for [Open WebUI](https://github.com/open-webui/open-webui).

---

## Available Tools & Skills

### 1. OpenBao / Vault KV Client ([`tools/openbao_client.py`](file:///Users/jspencer/projects/open-webui_tools/tools/openbao_client.py))

An integration tool allowing Open WebUI and connected LLMs to interact with an [OpenBao](https://openbao.org/) (or HashiCorp Vault) Key-Value (KV v2) secrets engine.

- **Capabilities**: Discover secret keys (`list_secrets`), retrieve key/value data (`read_secret`), and create or update secrets (`write_secret`).
- **Valves**:
  - `OPENBAO_ADDR`: Base URL of the vault instance (e.g. `https://vault.example.com`).
  - `SECRETS_MOUNT`: KV v2 mount point (default: `kv`).
  - `OPENBAO_SKIP_TLS_VERIFY`: Boolean flag for self-signed certificates.
  - `REQUEST_TIMEOUT`: HTTP connection and read timeout in seconds (default: `10`).
  - `OPENBAO_USERNAME` / `OPENBAO_PASSWORD`: Optional fallback credentials.
- **UserValves**: Personal userpass username and password saved to the user's chat profile.
- **Security Features**: Per-user token isolation (`__user__["id"]:username`), automatic token renewal on HTTP 401/403, path sanitization against directory traversal, and server-side token revocation on `logout()`.
- **Skill**: [`skills/openbao_client/SKILL.md`](file:///Users/jspencer/projects/open-webui_tools/skills/openbao_client/SKILL.md)

---

### 2. OpenWrt Router Client ([`tools/openwrt_client.py`](file:///Users/jspencer/projects/open-webui_tools/tools/openwrt_client.py))

A router management and network diagnostics tool interfacing with OpenWrt's `ubus` JSON-RPC interface (`/ubus`).

- **Capabilities**:
  - `get_system_info`: Inspect router model, OpenWrt release, uptime, CPU load, and memory usage.
  - `get_network_status`: Query active interfaces (LAN, WAN, WWAN), assigned IPv4/IPv6 addresses, DNS, and uptime.
  - `get_dhcp_leases`: Discover connected devices, hostnames, assigned IPs, MAC addresses, and lease timers.
  - `get_wireless_status`: Inspect Wi-Fi physical devices, active SSIDs, channels, and client associations.
  - `uci_get`: Query OpenWrt's Unified Configuration Interface (`network`, `wireless`, `firewall`, `dhcp`, etc.) with automatic credential masking.
  - `call_ubus`: Execute allowlisted or administrative ubus procedures.
  - `reboot_system`: Safeguarded reboot with mandatory `confirm=True` flag and administrator role verification.
- **Valves**:
  - `OPENWRT_URL`: Base URL of the OpenWrt router (e.g., `http://192.168.1.1` or `https://router.lan`).
  - `OPENWRT_RPC_PATH`: ubus endpoint path (default: `/ubus`).
  - `OPENWRT_SKIP_TLS_VERIFY`: Boolean flag to bypass self-signed router certificate verification.
  - `REQUEST_TIMEOUT`: HTTP connection and read timeout in seconds (default: `10`).
  - `OPENWRT_USERNAME` / `OPENWRT_PASSWORD`: Optional fallback credentials.
- **UserValves**: Personal OpenWrt username (e.g., `root`) and password persisted in chat session controls.
- **Security Features**: Multi-tenant token isolation, blocking of dangerous shell execution (`file.exec`), automatic redaction of Wi-Fi PSK and VPN keys in UCI queries, and admin-only enforcement on router reboots.
- **Skill**: [`skills/openwrt_client/SKILL.md`](file:///Users/jspencer/projects/open-webui_tools/skills/openwrt_client/SKILL.md)

---

### 3. Ubuntu SSH Client ([`tools/ubuntu_ssh_client.py`](file:///Users/jspencer/projects/open-webui_tools/tools/ubuntu_ssh_client.py))

A remote command execution, service management, and diagnostic tool for Ubuntu Linux servers via SSH.

- **Capabilities**:
  - `execute_command`: Run arbitrary shell commands on remote Ubuntu machines with timeout and output truncation.
  - `get_system_status`: Retrieve structured OS version, uptime, load averages, memory, and root disk usage.
  - `read_file`: Inspect remote configuration and log files.
  - `write_file`: Safely write or update remote files using Base64 encoding.
  - `manage_service`: Inspect or control systemd service units (`nginx`, `docker`, `ufw`, etc.).
- **Valves**:
  - `SSH_HOST`: Default server hostname or IP address.
  - `SSH_PORT`: SSH port number (default: `22`).
  - `SSH_TIMEOUT`: Command and connection timeout in seconds (default: `15`).
  - `MAX_OUTPUT_CHARS`: Output truncation limit (default: `8000`).
  - `SSH_USERNAME` / `SSH_PASSWORD` / `SSH_KEY`: Optional fallback credentials.
- **UserValves**: Personal host, port, username, password, or SSH private key (PEM/OpenSSH) saved per user.
- **Security Features**: Per-user credential isolation, masked secrets in UI, output bounds preventing LLM token exhaustion, and safe execution timeouts.
- **Skill**: [`skills/ubuntu_ssh_client/SKILL.md`](file:///Users/jspencer/projects/open-webui_tools/skills/ubuntu_ssh_client/SKILL.md)

---

### 4. Gitea CLI & Open Terminal ([`skills/gitea_cli/SKILL.md`](file:///Users/jspencer/projects/open-webui_tools/skills/gitea_cli/SKILL.md))

An operational runbook for managing Gitea repositories, issues, pull requests, and releases directly from Open WebUI's **Open Terminal** environment.

- **Capabilities**:
  - Automated non-root installation of the official `tea` CLI binary into `~/.local/bin`.
  - Profile authentication with personal access tokens (`tea login add`).
  - Repository operations: list, clone, create, and inspect repositories.
  - Issue tracking: non-interactive creation, listing, commenting, and closing.
  - Pull requests: non-interactive PR creation, checkout, review/approval, and merging (squash, merge, rebase).
  - Releases: create and manage release tags and assets.
  - Fallback REST API: complete `curl` + `jq` recipes for headless or minimal Open Terminal environments.
- **Skill**: [`skills/gitea_cli/SKILL.md`](file:///Users/jspencer/projects/open-webui_tools/skills/gitea_cli/SKILL.md)

---

## Installation in Open WebUI

### Automated Deployment (`install.py`)
Deploy all tools and skills directly to Open WebUI with your API key:

```bash
# Deploy all tools and skills
python3 install.py --api-key "sk-your-openwebui-api-key"

# Or deploy selectively
python3 install.py --tools-only
python3 install.py --skills-only
```

### Manual UI Installation
- **Tools**: In Open WebUI, navigate to **Workspace > Tools**, click **+**, paste the tool file from `tools/`, and save.
- **Skills**: In Open WebUI, navigate to **Workspace > Skills**, click **+**, paste the skill markdown from `skills/<tool>/SKILL.md`, and save.

---

## Configuration & Valves

Open WebUI uses Pydantic-based **Valves** to generate interactive configuration forms.

### 1. Global / Tool-Level Valves (`Valves`)
Configured by administrators in **Workspace > Tools > [Tool] > Settings (Gear Icon)**:
- Sets default server URLs, ports, timeouts, and optional shared credentials.

### 2. User-Specific Valves (`UserValves`)
Configured by individual users directly inside chat sessions:
1. Open any chat where the tool is enabled.
2. Click **Model Controls** (sliders icon next to the chat prompt).
3. Under the **Controls** tab, click **Valves** next to the tool name.
4. Enter your personal credentials.
5. Click **Save**.

> [!NOTE]
> **Persistence & Security**: `UserValves` are stored in Open WebUI's database linked to the user's ID and persist across sessions. Session tokens and SSH credentials are strictly isolated per user.

---

## Standalone CLI Testing

You can test any tool script directly from the terminal outside of Open WebUI:

```bash
# Test OpenBao KV client
python3 tools/openbao_client.py

# Test OpenWrt router client
python3 tools/openwrt_client.py

# Test Ubuntu SSH client
python3 tools/ubuntu_ssh_client.py
```

---

## Running Automated Tests

A comprehensive test suite verifying dual-tier authentication, KV v2 URL routing, multi-user token isolation, redaction, and error recovery is provided under `tests/`:

```bash
python3 -m unittest discover tests/
```

---

## Project Structure

```text
open-webui_tools/
├── .agents/
│   └── skills/                    # Antigravity workspace skill discovery mirrors
│       ├── gitea_cli/SKILL.md
│       ├── openbao_client/SKILL.md
│       ├── openwrt_client/SKILL.md
│       └── ubuntu_ssh_client/SKILL.md
├── .github/
│   └── workflows/
│       └── test.yml               # GitHub Actions CI matrix (Python 3.10–3.13)
├── README.md                      # Project documentation
├── install.py                     # Automated Open WebUI deployment script
├── tools/
│   ├── openbao_client.py          # OpenBao KV v2 client tool
│   ├── openwrt_client.py          # OpenWrt ubus JSON-RPC router client tool
│   └── ubuntu_ssh_client.py       # Ubuntu Linux SSH management client tool
├── skills/
│   ├── gitea_cli/
│   │   └── SKILL.md               # Gitea CLI (tea) operational runbook and skill
│   ├── openbao_client/
│   │   └── SKILL.md               # OpenBao operational runbook and skill
│   ├── openwrt_client/
│   │   └── SKILL.md               # OpenWrt operational runbook and skill
│   └── ubuntu_ssh_client/
│       └── SKILL.md               # Ubuntu SSH operational runbook and skill
└── tests/
    ├── test_install.py            # Unit tests for install.py and skills parity
    ├── test_openbao_client.py     # Unit and integration tests for OpenBao client
    ├── test_openwrt_client.py     # Unit and integration tests for OpenWrt client
    └── test_ubuntu_ssh_client.py  # Unit and integration tests for Ubuntu SSH client
```
