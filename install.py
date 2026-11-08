#!/usr/bin/env python3
"""
Install / Update tools and skills on an Open WebUI instance.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


TOOLS_METADATA = [
    {
        "id": "openbao_client",
        "name": "OpenBao KV Client",
        "file": "tools/openbao_client.py",
        "description": "OpenBao / HashiCorp Vault KV v2 secrets management tool with per-user credential isolation.",
    },
    {
        "id": "openwrt_client",
        "name": "OpenWrt Router Client",
        "file": "tools/openwrt_client.py",
        "description": "OpenWrt router management, network diagnostics, DHCP leases, and UCI configuration via ubus JSON-RPC.",
    },
    {
        "id": "ubuntu_ssh_client",
        "name": "Ubuntu SSH Client",
        "file": "tools/ubuntu_ssh_client.py",
        "description": "Remote command execution, system diagnostics, and file management on Ubuntu Linux via SSH.",
    },
]

SKILLS_METADATA = [
    {
        "id": "openbao_client",
        "name": "OpenBao KV Client",
        "file": "skills/openbao_client/SKILL.md",
        "description": "Operational runbook and guidance for managing OpenBao / Vault KV v2 secrets via Open WebUI Tools OR directly via bash/curl in Open Terminal.",
    },
    {
        "id": "openwrt_client",
        "name": "OpenWrt Router Client",
        "file": "skills/openwrt_client/SKILL.md",
        "description": "Operational runbook for querying and managing OpenWrt routers via ubus JSON-RPC OR directly via bash/curl/ssh in Open Terminal.",
    },
    {
        "id": "ubuntu_ssh_client",
        "name": "Ubuntu SSH Client",
        "file": "skills/ubuntu_ssh_client/SKILL.md",
        "description": "Operational runbook and troubleshooting guidance for managing Ubuntu Linux via SSH using Tools OR native OpenSSH in Open Terminal.",
    },
    {
        "id": "gitea_cli",
        "name": "Gitea CLI (tea)",
        "file": "skills/gitea_cli/SKILL.md",
        "description": "Operational runbook and guidance for interacting with Gitea repositories, issues, PRs, and releases via tea CLI or REST API in Open Terminal.",
    },
]


def _deploy_item(endpoint_prefix: str, item_info: dict, base_url: str, api_key: str) -> bool:
    """Deploy or update a tool or skill in Open WebUI."""
    item_id = item_info["id"]
    name = item_info["name"]
    description = item_info["description"]
    file_path = REPO_ROOT / item_info["file"]
    singular_label = endpoint_prefix.rstrip("s")

    if not file_path.is_file():
        print(f"[-] Error: {singular_label} file not found: {file_path}")
        return False

    content = file_path.read_text(encoding="utf-8")
    payload = {
        "id": item_id,
        "name": name,
        "description": description,
        "content": content,
        "meta": {
            "description": description,
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    base = base_url.rstrip("/")

    # Check if item already exists
    check_url = f"{base}/api/v1/{endpoint_prefix}/id/{item_id}"
    exists = False
    try:
        check_req = urllib.request.Request(check_url, headers=headers, method="GET")
        with urllib.request.urlopen(check_req, timeout=15) as resp:
            if resp.status == 200:
                exists = True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            exists = False
        elif e.code in (401, 403):
            print(f"[-] Authentication failed (HTTP {e.code}). Please verify your Open WebUI API key.")
            e.close()
            return False
        else:
            body = e.read(4096).decode("utf-8", errors="replace")
            print(f"[-] Error checking {singular_label} '{item_id}' (HTTP {e.code}): {body}")
            e.close()
            return False
    except Exception as e:
        print(f"[-] Connection failed during existence check for {singular_label} '{item_id}': {e}")
        return False

    data_bytes = json.dumps(payload).encode("utf-8")

    if exists:
        url = f"{base}/api/v1/{endpoint_prefix}/id/{item_id}/update"
        action = "Updating"
    else:
        url = f"{base}/api/v1/{endpoint_prefix}/create"
        action = "Creating"

    print(f"[*] {action} {singular_label} '{name}' (id: {item_id}) on {base}...")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[+] Successfully installed {singular_label} '{name}'!")
                return True
            else:
                body = resp.read(4096).decode("utf-8", errors="replace")
                print(f"[-] Server returned unexpected status {resp.status}: {body}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read(4096).decode("utf-8", errors="replace")
        print(f"[-] HTTP Error {e.code}: {body}")
        e.close()
        return False
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        return False


def install_tool(base_url: str, api_key: str, tool_info: dict) -> bool:
    """Install or update a tool."""
    return _deploy_item("tools", tool_info, base_url, api_key)


def install_skill(base_url: str, api_key: str, skill_info: dict) -> bool:
    """Install or update a skill."""
    return _deploy_item("skills", skill_info, base_url, api_key)


def load_dotenv():
    """Load configuration from local .env file."""
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip().strip("'\"")
                if k in ("open_webui_api", "openwebui_api_key", "open_webui_api_key", "api_key"):
                    os.environ.setdefault("OPENWEBUI_API_KEY", v)
                elif k in ("open_webui_url", "openwebui_url"):
                    os.environ.setdefault("OPENWEBUI_URL", v)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for install.py."""
    parser = argparse.ArgumentParser(
        description="Deploy tools and skills to an Open WebUI instance."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("OPENWEBUI_URL", "http://localhost:3000"),
        help="Base URL of Open WebUI (default: $OPENWEBUI_URL or http://localhost:3000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENWEBUI_API_KEY"),
        help="Open WebUI API Key (or set OPENWEBUI_API_KEY env var)",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--tools-only",
        action="store_true",
        help="Deploy only tools",
    )
    mode_group.add_argument(
        "--skills-only",
        action="store_true",
        help="Deploy only skills",
    )
    return parser


def main():
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        print("[!] No API key provided.")
        print("To deploy automatically, obtain an API key from:")
        print(f"    {args.url} -> Settings > Account > API Keys > Create New Key")
        print()
        try:
            api_key = getpass.getpass("Enter your Open WebUI API key: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not api_key:
        print("[-] API key is required.")
        sys.exit(1)

    all_success = True

    if not args.skills_only:
        print("=== Deploying Tools ===")
        for tool_info in TOOLS_METADATA:
            ok = install_tool(args.url, api_key, tool_info)
            if not ok:
                all_success = False

    if not args.tools_only:
        print("\n=== Deploying Skills ===")
        for skill_info in SKILLS_METADATA:
            ok = install_skill(args.url, api_key, skill_info)
            if not ok:
                all_success = False

    if all_success:
        print("\n[+] All requested tools and skills deployed successfully to Open WebUI!")
    else:
        print("\n[-] Some items failed to deploy. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
