# Open WebUI Tools

A collection of custom tools and extensions for [Open WebUI](https://github.com/open-webui/open-webui).

---

## Available Tools

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

## Installation in Open WebUI

1. Log into your Open WebUI instance with administrator or workspace permissions.
2. Navigate to **Workspace > Tools**.
3. Click the **+** (Add Tool) button.
4. Copy and paste the contents of the desired tool script (`tools/openbao_client.py` or `tools/openwrt_client.py`) into the code editor.
5. Click **Save**.

---

## Configuration & Valves

Open WebUI uses Pydantic-based **Valves** to generate interactive configuration forms.

### 1. Global / Tool-Level Valves (`Valves`)
Configured by administrators in **Workspace > Tools > [Tool] > Settings (Gear Icon)**:
- Sets default server URLs, ports, TLS verification options, timeouts, and optional shared credentials.

### 2. User-Specific Valves (`UserValves`)
Configured by individual users directly inside chat sessions:
1. Open any chat where the tool is enabled.
2. Click **Model Controls** (sliders icon next to the chat prompt).
3. Under the **Controls** tab, click **Valves** next to the tool name.
4. Enter your personal credentials.
5. Click **Save**.

> [!NOTE]
> **Persistence & Security**: `UserValves` are stored in Open WebUI's database linked to the user's ID and persist across sessions. Session tokens are cached strictly per user, preventing multi-user credential collisions.

---

## Standalone CLI Testing

You can test any tool script directly from the terminal outside of Open WebUI:

```bash
# Test OpenBao KV client
python3 tools/openbao_client.py

# Test OpenWrt router client
python3 tools/openwrt_client.py
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
├── README.md                      # Project documentation
├── tools/
│   ├── openbao_client.py          # OpenBao KV v2 client tool
│   └── openwrt_client.py          # OpenWrt ubus JSON-RPC router client tool
├── skills/
│   ├── openbao_client/
│   │   └── SKILL.md               # OpenBao operational runbook and skill
│   └── openwrt_client/
│       └── SKILL.md               # OpenWrt operational runbook and skill
└── tests/
    ├── test_openbao_client.py     # Unit and integration tests for OpenBao client
    └── test_openwrt_client.py     # Unit and integration tests for OpenWrt client
```
