#!/usr/bin/env python3
"""
Install / Update tools on an Open WebUI instance (e.g. https://ai.jamesspencer.me).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


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


def install_tool(base_url: str, api_key: str, tool_info: dict) -> bool:
    tool_id = tool_info["id"]
    name = tool_info["name"]
    file_path = Path(tool_info["file"])

    if not file_path.is_file():
        print(f"[-] Error: file not found: {file_path}")
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
                print(f"[+] Successfully installed '{name}'!")
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
    env_path = Path(".env")
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
        description="Deploy tools to an Open WebUI instance."
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
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        print("[!] No API key provided.")
        print("To deploy automatically, obtain an API key from:")
        print(f"    {args.url} -> Settings > Account > API Keys > Create New Key")
        print()
        try:
            api_key = input("Enter your Open WebUI API key: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not api_key:
        print("[-] API key is required.")
        sys.exit(1)

    all_success = True
    for tool_info in TOOLS_METADATA:
        ok = install_tool(args.url, api_key, tool_info)
        if not ok:
            all_success = False

    if all_success:
        print("\n[+] All tools deployed successfully to Open WebUI!")
    else:
        print("\n[-] Some tools failed to deploy. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

