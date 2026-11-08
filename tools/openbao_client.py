from __future__ import annotations

import posixpath
import threading
from typing import Any, Optional
from urllib.parse import quote

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


class Tools:
    """OpenBao / HashiCorp Vault (KV v2) client tool for Open WebUI.

    Provides secure access to secrets via Key-Value v2 engine with per-user
    credential isolation and automatic token renewal.
    """

    class Valves(BaseModel):
        """Admin/Tool-level connection settings (configured in Workspace > Tools)."""

        OPENBAO_ADDR: str = Field(
            default="https://vault.spencer.lan",
            description="Base URL of the vault (proxied HTTPS/443).",
        )
        SECRETS_MOUNT: str = Field(
            default="kv",
            description="KV v2 mount path (default: kv).",
        )
        OPENBAO_SKIP_TLS_VERIFY: bool = Field(
            default=False,
            description="Disable TLS verification for self-signed certs (testing only).",
        )
        REQUEST_TIMEOUT: int = Field(
            default=10,
            description="HTTP connection and read timeout in seconds.",
        )
        OPENBAO_USERNAME: str = Field(
            default="",
            description="(Optional) Default userpass username for tool-level fallback / CLI.",
        )
        OPENBAO_PASSWORD: str = Field(
            default="",
            description="(Optional) Default userpass password.",
            json_schema_extra={"input": {"type": "password"}},
        )

    class UserValves(BaseModel):
        """Per-user connection credentials (saved to each user's Open WebUI profile)."""

        OPENBAO_USERNAME: str = Field(
            default="",
            description="Personal userpass username.",
        )
        OPENBAO_PASSWORD: str = Field(
            default="",
            description="Personal userpass password (never printed).",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()
        self.tokens: dict[str, str] = {}
        self._tokens_lock = threading.Lock()
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
        """Backward-compatible access to the latest cached token."""
        with self._tokens_lock:
            return next(iter(self.tokens.values()), None)

    @token.setter
    def token(self, value: Optional[str]) -> None:
        with self._tokens_lock:
            if value is None:
                self.tokens.clear()
            else:
                self.tokens["cli:default"] = value

    @property
    def _base_url(self) -> str:
        addr = self.valves.OPENBAO_ADDR.strip().rstrip("/")
        if not addr:
            raise ValueError("OPENBAO_ADDR is not configured in Valves.")
        return addr

    @property
    def _timeout(self) -> tuple[float, float]:
        t = float(getattr(self.valves, "REQUEST_TIMEOUT", 10))
        return (5.0, t)

    def _get_verify(self) -> bool:
        skip_verify = getattr(self.valves, "OPENBAO_SKIP_TLS_VERIFY", False)
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

    def _sanitize_path(self, path: str) -> str:
        """Sanitize secret path to prevent directory traversal and double slashes."""
        clean = posixpath.normpath(path.strip().lstrip("/"))
        if clean.startswith("..") or "/../" in clean or clean == ".":
            raise ValueError(f"Invalid secret path (path traversal detected): {path}")
        return "/".join(quote(part, safe="") for part in clean.split("/"))

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
            or getattr(user_valves, "OPENBAO_USERNAME", None)
            or (user_valves.get("OPENBAO_USERNAME") if isinstance(user_valves, dict) else None)
            or self.valves.OPENBAO_USERNAME
        )
        p = (
            password
            or getattr(user_valves, "OPENBAO_PASSWORD", None)
            or (user_valves.get("OPENBAO_PASSWORD") if isinstance(user_valves, dict) else None)
            or self.valves.OPENBAO_PASSWORD
        )
        return (u.strip() if u else None), (p if p else None)

    def _login(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """Internal authentication: logs in via userpass and caches token per user identity."""
        u, p = self._resolve_credentials(username, password, __user__)
        if not u or not p:
            raise ValueError(
                "Missing credentials. Set OPENBAO_USERNAME / OPENBAO_PASSWORD in UserValves or Valves."
            )

        url = f"{self._base_url}/v1/auth/userpass/login/{quote(u, safe='')}"
        self.session.cookies.clear()
        resp = self.session.post(
            url,
            json={"password": p},
            verify=self._get_verify(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        token = payload.get("auth", {}).get("client_token")
        if not token:
            raise RuntimeError("Login succeeded but no client_token was returned.")

        cache_key = self._get_user_key(__user__, u)
        with self._tokens_lock:
            self.tokens[cache_key] = token
        return token

    def _ensure_token(self, __user__: Optional[dict] = None) -> str:
        u, p = self._resolve_credentials(__user__=__user__)
        if not u or not p:
            raise ValueError(
                "Missing credentials. Set OPENBAO_USERNAME / OPENBAO_PASSWORD in UserValves or Valves."
            )
        cache_key = self._get_user_key(__user__, u)
        with self._tokens_lock:
            cached = self.tokens.get(cache_key)
        if cached:
            return cached
        return self._login(username=u, password=p, __user__=__user__)

    def _request_with_auth(
        self,
        method: str,
        url: str,
        __user__: Optional[dict] = None,
        retry: bool = True,
        **kwargs,
    ) -> requests.Response:
        """Execute HTTP request with authentication and automatic retry on token expiration."""
        token = self._ensure_token(__user__=__user__)
        headers = kwargs.pop("headers", {})
        headers["X-Vault-Token"] = token

        self.session.cookies.clear()
        resp = self.session.request(
            method,
            url,
            headers=headers,
            verify=self._get_verify(),
            timeout=self._timeout,
            **kwargs,
        )

        # Handle token expiration (HTTP 401 or 403 Forbidden)
        if resp.status_code in (401, 403) and retry:
            u, _ = self._resolve_credentials(__user__=__user__)
            cache_key = self._get_user_key(__user__, u)
            with self._tokens_lock:
                self.tokens.pop(cache_key, None)
            return self._request_with_auth(
                method, url, __user__=__user__, retry=False, **kwargs
            )

        resp.raise_for_status()
        return resp

    # -------------------------------------------------------------------------
    # Public Tool Functions (Exposed to Open WebUI / LLM)
    # -------------------------------------------------------------------------

    def list_secrets(
        self, path: Optional[str] = None, __user__: Optional[dict] = None
    ) -> list[str]:
        """
        List the names of secrets or subfolders stored under the OpenBao/Vault KV v2 mount.

        :param path: Optional subpath/folder within the KV mount to list (leave empty to list root).
        :return: List of secret keys and subfolder names.
        """
        mount = self.valves.SECRETS_MOUNT.strip("/")
        if path and path.strip("/"):
            clean_sub = self._sanitize_path(path)
            url = f"{self._base_url}/v1/{mount}/metadata/{clean_sub}?list=true"
        else:
            url = f"{self._base_url}/v1/{mount}/metadata?list=true"

        resp = self._request_with_auth("GET", url, __user__=__user__)
        payload = resp.json() or {}
        data = payload.get("data") or {}
        return data.get("keys") or []

    def read_secret(self, path: str, __user__: Optional[dict] = None) -> dict:
        """
        Read key/value secret data from OpenBao/Vault KV v2 at the specified path.

        :param path: The path to the secret to read under the KV mount (e.g. 'database/credentials').
        :return: Dictionary containing the secret key/value data.
        """
        clean_path = self._sanitize_path(path)
        mount = self.valves.SECRETS_MOUNT.strip("/")
        url = f"{self._base_url}/v1/{mount}/data/{clean_path}"

        resp = self._request_with_auth("GET", url, __user__=__user__)
        payload = resp.json() or {}
        data = payload.get("data") or {}
        return data.get("data") or {}

    def write_secret(
        self, path: str, data: dict, __user__: Optional[dict] = None
    ) -> dict:
        """
        Create or update a secret in OpenBao/Vault KV v2 with key/value pairs.

        :param path: The path where the secret should be stored under the KV mount (e.g. 'database/credentials').
        :param data: Dictionary containing the key/value pairs to store.
        :return: Dictionary containing version and metadata from OpenBao.
        """
        if not isinstance(data, dict):
            raise ValueError("'data' parameter must be a JSON dictionary of key/value pairs.")

        clean_path = self._sanitize_path(path)
        mount = self.valves.SECRETS_MOUNT.strip("/")
        url = f"{self._base_url}/v1/{mount}/data/{clean_path}"

        resp = self._request_with_auth(
            "POST", url, __user__=__user__, json={"data": data}
        )
        return resp.json() or {}

    def logout(self, __user__: Optional[dict] = None) -> str:
        """
        Log out the current user by evicting and revoking their cached session token.

        :return: Confirmation message indicating the session was terminated.
        """
        u, _ = self._resolve_credentials(__user__=__user__)
        cache_key = self._get_user_key(__user__, u)
        with self._tokens_lock:
            token = self.tokens.pop(cache_key, None)

        if token:
            try:
                url = f"{self._base_url}/v1/auth/token/revoke-self"
                self.session.post(
                    url,
                    headers={"X-Vault-Token": token},
                    verify=self._get_verify(),
                    timeout=(3.0, 5.0),
                )
            except Exception:
                pass
            return "Session successfully terminated and token revoked."
        return "No active session found to log out."


def main():
    """CLI entrypoint: test connection and list secrets under the kv mount."""
    tool = Tools()
    print(f"Connecting to OpenBao vault at {tool.valves.OPENBAO_ADDR}...")
    try:
        tool._login()
        names = tool.list_secrets()
        print(f"Authenticated as {tool.valves.OPENBAO_USERNAME}")
        print(f"Found {len(names)} secret(s) under '{tool.valves.SECRETS_MOUNT}':")
        for name in names:
            print(f"  - {name}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        tool.close()


if __name__ == "__main__":
    main()
