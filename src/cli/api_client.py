"""Cookie-session HTTP helper for CLI commands using the local API.

Most API routes sit behind the dashboard's session-cookie auth, so an
unauthenticated CLI request gets 401 — which is a different situation
from the service being down. This client keeps the two distinguishable
and offers an interactive login that stores the session cookie for
subsequent requests.
"""

from __future__ import annotations

import getpass
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8080"
_LOCAL_TOKEN_TTL_SECONDS = 600


class ApiError(Exception):
    """Request failed for a reason other than the two below."""


class ServiceDown(ApiError):
    """Nothing is listening (connection refused / timeout)."""


class AuthRequired(ApiError):
    """The service answered, but wants a valid admin session."""


class CliApiClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0):
        self._base = base_url
        self._timeout = timeout
        self._bearer: str | None = None
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def get(self, path: str) -> dict | list:
        headers = (
            {"Authorization": f"Bearer {self._bearer}"} if self._bearer else {}
        )
        try:
            request = urllib.request.Request(
                f"{self._base}{path}", headers=headers
            )
            with self._opener.open(request, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthRequired(path) from exc
            raise ApiError(f"{path}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ServiceDown(str(exc.reason)) from exc

    def login_local_root(self) -> bool:
        """Mint an admin session offline from the on-disk signing key.

        Trust model mirrors ``meshpoint reset-password``: whoever can
        read ``web_auth.jwt_secret`` in local.yaml (root / the service
        user) can already take over the dashboard, so a password prompt
        adds no protection for them. Signs a short-lived (10 min)
        admin bearer token with the same key + session_version the
        server verifies against — no server-side bypass involved.

        Returns False (never raises) when the config isn't readable,
        has no secret yet, or PyJWT isn't importable; callers fall
        back to the interactive login.
        """
        try:
            import jwt
            import yaml

            config_path = os.environ.get(
                "CONCENTRATOR_CONFIG", "config/local.yaml"
            )
            with open(config_path) as fh:
                raw = yaml.safe_load(fh) or {}
            web_auth = raw.get("web_auth") or {}
            secret = web_auth.get("jwt_secret")
            if not secret:
                return False
            now = int(time.time())
            self._bearer = jwt.encode(
                {
                    "sub": "cli-local-root",
                    "role": "admin",
                    "sv": int(web_auth.get("session_version", 1)),
                    "iat": now,
                    "exp": now + _LOCAL_TOKEN_TTL_SECONDS,
                },
                secret,
                algorithm="HS256",
            )
            return True
        except Exception:
            return False

    def login_interactive(self) -> None:
        """Prompt for dashboard admin credentials and open a session."""
        username = input("  Dashboard admin username [admin]: ").strip() or "admin"
        password = getpass.getpass("  Password: ")
        body = json.dumps({"username": username, "password": password}).encode()
        request = urllib.request.Request(
            f"{self._base}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            self._opener.open(request, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthRequired("login rejected") from exc
            raise ApiError(f"login: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ServiceDown(str(exc.reason)) from exc
