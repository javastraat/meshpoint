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
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8080"


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
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def get(self, path: str) -> dict | list:
        try:
            with self._opener.open(
                f"{self._base}{path}", timeout=self._timeout
            ) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthRequired(path) from exc
            raise ApiError(f"{path}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ServiceDown(str(exc.reason)) from exc

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
