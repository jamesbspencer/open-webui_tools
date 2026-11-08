from __future__ import annotations

import itertools
import threading
from typing import Any, Optional

try:
    import requests
    import urllib3
except ImportError:
    raise ImportError(
        "The 'requests' package is required to run this tool. Install it with: pip install requests"
    )

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
        # In CLI mode without pydantic, resolve to default value directly.
        return default


def _as_dict(val: Any) -> dict:
    return val if isinstance(val, dict) else {}


def _as_list(val: Any) -> list:
    return val if isinstance(val, list) else []


class Tools:
    """OpenWrt router management client for Open WebUI via ubus JSON-RPC.

    Provides secure access to router status, network interfaces, wireless associations,
    DHCP leases, and UCI configuration with multi-tenant credential isolation.
    """

    class Valves(BaseModel):
        """Admin/Tool-level connection settings (configured in Workspace > Tools)."""

        OPENWRT_URL: str = Field(
            default="http://192.168.1.1",
            description="Base URL of the OpenWrt router (e.g., http://192.168.1.1 or https://router.lan).",
        )
        OPENWRT_RPC_PATH: str = Field(
            default="/ubus",
            description="Path to the ubus JSON-RPC endpoint (default: /ubus).",
        )
        OPENWRT_SKIP_TLS_VERIFY: bool = Field(
            default=False,
            description="Disable TLS verification for self-signed router certificates.",
        )
        REQUEST_TIMEOUT: int = Field(
            default=10,
            description="HTTP connection and read timeout in seconds.",
        )
        OPENWRT_USERNAME: str = Field(
            default="root",
            description="(Optional) Default username for tool-level fallback / CLI.",
        )
        OPENWRT_PASSWORD: str = Field(
            default="",
            description="(Optional) Default password.",
            json_schema_extra={"input": {"type": "password"}},
        )

    class UserValves(BaseModel):
        """Per-user credentials (persisted in the user's Open WebUI profile)."""

        OPENWRT_USERNAME: str = Field(
            default="",
            description="Personal OpenWrt username.",
        )
        OPENWRT_PASSWORD: str = Field(
            default="",
            description="Personal OpenWrt password (never printed).",
            json_schema_extra={"input": {"type": "password"}},
        )

    # Allowlist of safe read-only ubus procedures accessible to all users
    SAFE_UBUS_ALLOWLIST: dict[str, set[str]] = {
        "system": {"info", "board"},
        "network.interface": {"dump", "status"},
        "network.wireless": {"status"},
        "dhcp": {"ipv4leases"},
        "luci-rpc": {"getDHCPLeases"},
    }

    # Keys automatically redacted in UCI configuration queries to prevent credential exfiltration
    REDACTED_UCI_KEYS: set[str] = {
        "key",
        "password",
        "secret",
        "private_key",
        "auth_key",
        "preshared_key",
        "token",
    }

    def __init__(self):
        self.valves = self.Valves()
        self.tokens: dict[str, str] = {}
        self._tokens_lock = threading.Lock()
        self._request_counter = itertools.count(1)
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def close(self) -> None:
        """Close the underlying HTTP session connection pool."""
        if hasattr(self, "session") and self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def token(self) -> Optional[str]:
        """Backward-compatible access to the latest cached session token."""
        with self._tokens_lock:
            return next(iter(self.tokens.values()), None)

    @property
    def _timeout(self) -> tuple[float, float]:
        t = float(getattr(self.valves, "REQUEST_TIMEOUT", 10))
        return (5.0, t)

    def _get_verify(self) -> bool:
        skip_verify = getattr(self.valves, "OPENWRT_SKIP_TLS_VERIFY", False)
        if skip_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            return False
        return True

    def _get_user_key(self, __user__: Optional[dict], username: Optional[str]) -> str:
        user_id = "cli"
        if isinstance(__user__, dict):
            user_id = str(__user__.get("id") or __user__.get("email") or "anonymous")
        elif hasattr(__user__, "id"):
            user_id = str(getattr(__user__, "id", "anonymous"))
        return f"{user_id}:{username or 'default'}"

    def _resolve_credentials(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        user_valves = None
        if isinstance(__user__, dict):
            user_valves = __user__.get("valves")

        u = (
            username
            or getattr(user_valves, "OPENWRT_USERNAME", None)
            or (user_valves.get("OPENWRT_USERNAME") if isinstance(user_valves, dict) else None)
            or self.valves.OPENWRT_USERNAME
        )
        p = (
            password
            or getattr(user_valves, "OPENWRT_PASSWORD", None)
            or (user_valves.get("OPENWRT_PASSWORD") if isinstance(user_valves, dict) else None)
            or self.valves.OPENWRT_PASSWORD
        )
        return (u.strip() if u else None), (p if p else None)

    def _endpoint(self) -> str:
        base = self.valves.OPENWRT_URL.rstrip("/")
        path = self.valves.OPENWRT_RPC_PATH.strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"

    def _login(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """Authenticate with OpenWrt ubus JSON-RPC and cache the session token per user."""
        u, p = self._resolve_credentials(username, password, __user__)
        if not u or not p:
            raise ValueError(
                "Missing credentials. Set OPENWRT_USERNAME / OPENWRT_PASSWORD in UserValves or Valves."
            )

        req_id = next(self._request_counter)
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": u, "password": p},
            ],
        }

        self.session.cookies.clear()
        resp = self.session.post(
            self._endpoint(),
            json=payload,
            verify=self._get_verify(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}

        result = data.get("result")
        if not result or not isinstance(result, list):
            error = data.get("error") or "Unknown RPC response format"
            raise RuntimeError(f"OpenWrt login failed: {error}")

        status_code = result[0]
        if status_code != 0:
            raise PermissionError(
                f"OpenWrt authentication rejected (error code {status_code}). Check username/password."
            )

        session_info = _as_dict(result[1] if len(result) > 1 else {})
        session_id = session_info.get("ubus_rpc_session")
        if not session_id:
            raise RuntimeError("Login succeeded but no ubus_rpc_session token was returned.")

        cache_key = self._get_user_key(__user__, u)
        with self._tokens_lock:
            self.tokens[cache_key] = session_id
        return session_id

    def _ensure_token(self, __user__: Optional[dict] = None) -> str:
        u, p = self._resolve_credentials(__user__=__user__)
        if not u or not p:
            raise ValueError(
                "Missing credentials. Set OPENWRT_USERNAME / OPENWRT_PASSWORD in UserValves or Valves."
            )
        cache_key = self._get_user_key(__user__, u)
        with self._tokens_lock:
            cached = self.tokens.get(cache_key)
        if cached:
            return cached
        return self._login(username=u, password=p, __user__=__user__)

    def _ubus_call(
        self,
        object_name: str,
        method: str,
        params: Optional[dict] = None,
        __user__: Optional[dict] = None,
        retry: bool = True,
    ) -> Any:
        """Execute a ubus call over JSON-RPC with automatic re-authentication."""
        session_id = self._ensure_token(__user__=__user__)
        req_id = next(self._request_counter)

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "call",
            "params": [
                session_id,
                object_name,
                method,
                params or {},
            ],
        }

        self.session.cookies.clear()
        resp = self.session.post(
            self._endpoint(),
            json=payload,
            verify=self._get_verify(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}

        result = data.get("result")
        if not result or not isinstance(result, list):
            error = data.get("error", "Unknown error")
            raise RuntimeError(f"ubus call failed ({object_name}.{method}): {error}")

        code = result[0]
        # ubus code 6 = Permission denied / session expired
        if code == 6 and retry:
            u, _ = self._resolve_credentials(__user__=__user__)
            cache_key = self._get_user_key(__user__, u)
            with self._tokens_lock:
                self.tokens.pop(cache_key, None)
            return self._ubus_call(object_name, method, params, __user__=__user__, retry=False)

        if code != 0:
            msg = f"ubus error code {code} calling {object_name}.{method}"
            if code == 4:
                msg += " (Not found / procedure or object not available)"
            elif code == 5:
                msg += " (Invalid argument)"
            elif code == 6:
                msg += " (Permission denied / session expired)"
            raise RuntimeError(msg)

        return result[1] if len(result) > 1 else None

    def _redact_sensitive_data(self, data: Any) -> Any:
        """Recursively redact known passwords, secrets, and private keys from UCI outputs."""
        if isinstance(data, dict):
            return {
                k: "******" if k.lower() in self.REDACTED_UCI_KEYS else self._redact_sensitive_data(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._redact_sensitive_data(item) for item in data]
        return data

    # -------------------------------------------------------------------------
    # Public Tool Functions (Exposed to Open WebUI / LLM)
    # -------------------------------------------------------------------------

    def get_system_info(self, __user__: Optional[dict] = None) -> dict:
        """
        Get system health information from OpenWrt including model, release, uptime, CPU load, and memory usage.

        :return: Dictionary containing system model, release, uptime, load averages, memory, and swap status.
        """
        try:
            info = _as_dict(self._ubus_call("system", "info", {}, __user__=__user__))
            board = {}
            try:
                board = _as_dict(self._ubus_call("system", "board", {}, __user__=__user__))
            except Exception:
                pass

            mem = _as_dict(info.get("memory"))
            return {
                "model": board.get("model", "Unknown"),
                "board_name": board.get("board_name", "Unknown"),
                "release": _as_dict(board.get("release")),
                "uptime_seconds": info.get("uptime", 0),
                "load": _as_list(info.get("load")),
                "memory": {
                    "total": mem.get("total", 0),
                    "free": mem.get("free", 0),
                    "shared": mem.get("shared", 0),
                    "buffered": mem.get("buffered", 0),
                },
                "swap": _as_dict(info.get("swap")),
            }
        except Exception as e:
            return {"error": f"Failed to retrieve system info: {e}"}

    def get_network_status(self, __user__: Optional[dict] = None) -> dict:
        """
        Get status of all active network interfaces on the router (e.g. LAN, WAN, WWAN), including IP addresses and DNS.

        :return: Dictionary mapping interface names to IP addresses, DNS servers, and status.
        """
        try:
            dump = _as_dict(self._ubus_call("network.interface", "dump", {}, __user__=__user__))
            interfaces = _as_list(dump.get("interface"))

            summary = {}
            for iface in interfaces:
                if not isinstance(iface, dict):
                    continue
                name = iface.get("interface", "unknown")
                summary[name] = {
                    "up": iface.get("up", False),
                    "device": iface.get("device") or iface.get("l3_device"),
                    "ipv4_addresses": [
                        f"{addr.get('address')}/{addr.get('mask')}"
                        for addr in _as_list(iface.get("ipv4-address"))
                        if isinstance(addr, dict) and addr.get("address")
                    ],
                    "ipv6_addresses": [
                        f"{addr.get('address')}/{addr.get('mask')}"
                        for addr in _as_list(iface.get("ipv6-address"))
                        if isinstance(addr, dict) and addr.get("address")
                    ],
                    "dns_servers": _as_list(iface.get("dns-server")),
                    "uptime": iface.get("uptime", 0),
                }
            return summary
        except Exception as e:
            return {"error": f"Failed to retrieve network status: {e}"}

    def get_dhcp_leases(self, __user__: Optional[dict] = None) -> list[dict]:
        """
        Get active DHCP client leases (connected devices, assigned IP addresses, MAC addresses, and hostnames).

        :return: List of connected DHCP clients with hostname, IP, MAC address, and lease expiration.
        """
        leases = []
        # 1. Try luci-rpc first
        try:
            res = self._ubus_call("luci-rpc", "getDHCPLeases", {}, __user__=__user__)
            if isinstance(res, dict) and "dhcp_leases" in res:
                return _as_list(res["dhcp_leases"])
        except Exception:
            pass

        # 2. Try dhcp.ipv4leases
        try:
            res = self._ubus_call("dhcp", "ipv4leases", {}, __user__=__user__)
            if isinstance(res, dict):
                device_list = _as_dict(res.get("device"))
                for dev, dev_leases in device_list.items():
                    leases_list = _as_list(_as_dict(dev_leases).get("leases"))
                    for item in leases_list:
                        if isinstance(item, dict):
                            leases.append(item)
                if leases:
                    return leases
        except Exception:
            pass

        # 3. Fallback: query /tmp/dhcp.leases via file.read if available
        try:
            file_res = _as_dict(
                self._ubus_call("file", "read", {"path": "/tmp/dhcp.leases"}, __user__=__user__)
            )
            data = file_res.get("data")
            if isinstance(data, str) and data.strip():
                for line in data.strip().split("\n"):
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        leases.append({
                            "expires": parts[0],
                            "mac": parts[1],
                            "ip": parts[2],
                            "hostname": parts[3] if parts[3] != "*" else "Unknown",
                        })
        except Exception:
            pass

        return leases

    def get_wireless_status(self, __user__: Optional[dict] = None) -> dict:
        """
        Get status of wireless radios, configured SSIDs, operating channels, and connected Wi-Fi clients.

        :return: Dictionary summarizing Wi-Fi devices, active SSIDs, and client status.
        """
        try:
            status = _as_dict(
                self._ubus_call("network.wireless", "status", {}, __user__=__user__)
            )
            result = {}
            for radio, data in status.items():
                data_dict = _as_dict(data)
                ifaces = _as_list(data_dict.get("interfaces"))
                iface_list = []
                for iface in ifaces:
                    if not isinstance(iface, dict):
                        continue
                    config = _as_dict(iface.get("config"))
                    iface_list.append({
                        "ssid": config.get("ssid"),
                        "mode": config.get("mode"),
                        "network": config.get("network"),
                        "ifname": iface.get("ifname"),
                    })
                result[radio] = {
                    "disabled": data_dict.get("disabled", False),
                    "channel": _as_dict(data_dict.get("config")).get("channel"),
                    "interfaces": iface_list,
                }
            return result
        except Exception as e:
            return {"error": f"Failed to retrieve wireless status: {e}"}

    def uci_get(
        self,
        config: str,
        section: Optional[str] = None,
        option: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> Any:
        """
        Query OpenWrt Unified Configuration Interface (UCI) settings (e.g. 'network', 'wireless', 'firewall', 'dhcp').
        Sensitive credentials (keys, passwords) are automatically redacted.

        :param config: The UCI configuration file name (e.g. 'network', 'firewall', 'wireless', 'system').
        :param section: Optional specific section name or type to inspect.
        :param option: Optional specific option name within the section.
        :return: Dictionary or string containing the redacted configuration values.
        """
        if config.lower() in {"shadow", "passwords", "dropbear"}:
            role = __user__.get("role") if isinstance(__user__, dict) else None
            if role != "admin":
                raise PermissionError("Access to this configuration is restricted to administrators.")

        params: dict[str, Any] = {"config": config}
        if section:
            params["section"] = section
        if option:
            params["option"] = option

        try:
            res = self._ubus_call("uci", "get", params, __user__=__user__)
            if isinstance(res, dict) and "values" in res:
                return self._redact_sensitive_data(res["values"])
            if isinstance(res, dict) and "value" in res:
                return self._redact_sensitive_data(res["value"])
            return self._redact_sensitive_data(res)
        except Exception as e:
            return {"error": f"Failed to query UCI configuration '{config}': {e}"}

    def call_ubus(
        self,
        object_name: str,
        method: str,
        params: Optional[dict] = None,
        __user__: Optional[dict] = None,
    ) -> Any:
        """
        Execute an allowlisted or administrative ubus procedure on the router.

        :param object_name: The ubus object name (e.g. 'system', 'network.interface').
        :param method: The method to execute on the object (e.g. 'info', 'dump').
        :param params: Optional parameters dictionary to pass to the method.
        :return: Result object returned by OpenWrt ubus.
        """
        # Block dangerous shell execution and arbitrary file writes unconditionally
        if object_name == "file" and method in {"exec", "write"}:
            raise PermissionError("Execution of arbitrary system commands or file writes is prohibited.")

        # Non-admins are confined to safe read-only allowlist
        allowed_methods = self.SAFE_UBUS_ALLOWLIST.get(object_name)
        is_safe = allowed_methods and method in allowed_methods

        if not is_safe:
            role = __user__.get("role") if isinstance(__user__, dict) else None
            if role != "admin":
                raise PermissionError(
                    f"Calling '{object_name}.{method}' requires Open WebUI administrator role."
                )

        try:
            return self._ubus_call(object_name, method, params or {}, __user__=__user__)
        except Exception as e:
            return {"error": f"ubus procedure '{object_name}.{method}' failed: {e}"}

    def reboot_system(self, confirm: bool = False, __user__: Optional[dict] = None) -> str:
        """
        Reboot the OpenWrt router. Requires setting confirm=True and administrative privileges.

        :param confirm: Explicit confirmation flag. Must be set to True to initiate reboot.
        :return: Confirmation message or cancellation notice.
        """
        if not confirm:
            return "Reboot aborted: 'confirm' must be explicitly set to True to reboot the router."

        role = __user__.get("role") if isinstance(__user__, dict) else None
        if role != "admin":
            raise PermissionError("Router reboot requires Open WebUI administrator role.")

        try:
            self._ubus_call("system", "reboot", {}, __user__=__user__)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # Router closes network sockets abruptly upon receiving reboot command
            pass
        except Exception as e:
            return f"Failed to send reboot command: {e}"

        return "Reboot command sent to OpenWrt. The router is now rebooting."


def main():
    """CLI test entrypoint for OpenWrt client."""
    tool = Tools()
    print(f"Connecting to OpenWrt router at {tool.valves.OPENWRT_URL}...")
    try:
        sysinfo = tool.get_system_info()
        print(f"Connected successfully! Model: {sysinfo.get('model')}")
        print(f"Uptime: {sysinfo.get('uptime_seconds')} seconds")
        print("\nNetwork interfaces:")
        net = tool.get_network_status()
        for name, details in net.items():
            if isinstance(details, dict):
                print(f"  - {name}: up={details.get('up')}, IPv4={details.get('ipv4_addresses')}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        tool.close()


if __name__ == "__main__":
    main()
