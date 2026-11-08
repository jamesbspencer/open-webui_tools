#!/usr/bin/env python3
"""
Install / Update tools and skills on an Open WebUI instance (e.g. https://ai.jamesspencer.me).
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
        "description": "Operational runbook and guidance for managing and interacting with OpenBao / Vault KV v2 secrets via Open WebUI Tools.",
    },
    {
        "id": "openwrt_client",
        "name": "OpenWrt Router Client",
        "file": "skills/openwrt_client/SKILL.md",
        "description": "Operational runbook and guidance for querying, inspecting, and managing OpenWrt routers via ubus JSON-RPC.",
    },
    {
        "id": "ubuntu_ssh_client",
        "name": "Ubuntu SSH Client",
        "file": "skills/ubuntu_ssh_client/SKILL.md",
        "description": "Operational runbook and troubleshooting guidance for managing Ubuntu Linux systems via SSH.",
    },
]


def install_tool(base_url: str, api_key: str, tool_info: dict) -> bool:
    tool_id = tool_info["id"]
    name = tool_info["name"]
    file_path = REPO_ROOT / tool_info["file"]

    if not file_path.is_file():
        print(f"[-] Error: tool file not found: {file_path}")
        return False

    content = file_path.read_text(encoding="utf-8")
    payload = {
        "id": tool_id,
        "name": name,
        "content": content,
        "meta": {
            "description": tool_info["description"],
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    base = base_url.rstrip("/")

    # Check if tool already exists
    check_url = f"{base}/api/v1/tools/id/{tool_id}"
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
            return False
        else:
            exists = False
    except Exception:
        exists = False

    data_bytes = json.dumps(payload).encode("utf-8")

    if exists:
        url = f"{base}/api/v1/tools/id/{tool_id}/update"
        action = "Updating"
    else:
        url = f"{base}/api/v1/tools/create"
        action = "Creating"

    print(f"[*] {action} tool '{name}' (id: {tool_id}) on {base}...")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[+] Successfully installed tool '{name}'!")
                return True
            else:
                body = resp.read().decode("utf-8", errors="replace")
                print(f"[-] Server returned unexpected status {resp.status}: {body}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[-] HTTP Error {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        return False


def install_skill(base_url: str, api_key: str, skill_info: dict) -> bool:
    skill_id = skill_info["id"]
    name = skill_info["name"]
    file_path = REPO_ROOT / skill_info["file"]

    if not file_path.is_file():
        print(f"[-] Error: skill file not found: {file_path}")
        return False

    content = file_path.read_text(encoding="utf-8")
    payload = {
        "id": skill_id,
        "name": name,
        "description": skill_info["description"],
        "content": content,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    base = base_url.rstrip("/")

    # Check if skill already exists
    check_url = f"{base}/api/v1/skills/id/{skill_id}"
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
            return False
        else:
            exists = False
    except Exception:
        exists = False

    data_bytes = json.dumps(payload).encode("utf-8")

    if exists:
        url = f"{base}/api/v1/skills/id/{skill_id}/update"
        action = "Updating"
    else:
        url = f"{base}/api/v1/skills/create"
        action = "Creating"

    print(f"[*] {action} skill '{name}' (id: {skill_id}) on {base}...")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[+] Successfully installed skill '{name}'!")
                return True
            else:
                body = resp.read().decode("utf-8", errors="replace")
                print(f"[-] Server returned unexpected status {resp.status}: {body}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[-] HTTP Error {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        return False


def load_dotenv():
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


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Deploy tools and skills to an Open WebUI instance."
    )
    parser.add_argument(
        "--url",
        default="https://ai.jamesspencer.me",
        help="Base URL of Open WebUI (default: https://ai.jamesspencer.me)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENWEBUI_API_KEY"),
        help="Open WebUI API Key (or set OPENWEBUI_API_KEY env var)",
    )
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="Deploy only tools",
    )
    parser.add_argument(
        "--skills-only",
        action="store_true",
        help="Deploy only skills",
    )
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
        print("\n[+] All tools and skills deployed successfully to Open WebUI!")
    else:
        print("\n[-] Some items failed to deploy. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
