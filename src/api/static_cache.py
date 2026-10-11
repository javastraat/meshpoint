"""Cache-Control policy for the dashboard's static assets.

Companion to ``html_assets.bust_asset_urls``: every local ``.js``/``.css``
URL in the served HTML carries ``?v=<BOOT_TOKEN>``, and the token is
re-minted on every service start (which is what every dashboard apply
ends in). A versioned URL is therefore *content-addressed in practice* —
the browser can keep it for a year and will simply be handed a different
URL after the next upgrade. That is exactly what this middleware sets,
and it removes the per-asset revalidation round-trips that used to
dominate a dashboard reload on a lossy meshlink / loaded LAN.

Policy (response-side, applied to 200s that have no explicit header
already set by the handler):

- ``.js`` / ``.css`` **with** ``?v=``  -> ``public, max-age=31536000,
  immutable`` (the URL is boot-token-versioned; can never go stale)
- ``.js`` / ``.css`` **without** ``v=`` -> ``public, max-age=0,
  must-revalidate`` (runtime-assembled URLs, e.g. from a plugin manifest
  or a dynamic import — keep them honest with the ETag StaticFiles sends)
- images / fonts / json / map / txt -> ``public, max-age=0,
  must-revalidate`` (not stamped by the bust regex; 304s are one cheap
  LAN round-trip and correctness survives upgrades)
- ``.html`` -> ``no-cache`` (a fresh document must revalidate even when
  fetched outside the ``/`` route, e.g. ``/index.html`` direct)
- everything else (API, 302s, 404s) -> untouched

Pure ASGI (no BaseHTTPMiddleware) so it stays transparent to
streaming responses and does not add another thread hop per request.
"""

from __future__ import annotations

from typing import Awaitable, Callable

ASGIApp = Callable[..., Awaitable[None]]

_VERSIONED = "public, max-age=31536000, immutable"
_REVALIDATE = "public, max-age=0, must-revalidate"
_NO_CACHE = "no-cache"

_JS_SUFFIXES = (".js", ".mjs", ".css")
_MEDIA_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
    ".map", ".json", ".txt", ".wasm",
)
_HTML_SUFFIXES = (".html", ".htm")


class StaticCacheHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = (scope.get("path") or "").lower()
        query = (scope.get("query_string") or b"").decode("latin-1")
        header = _header_for(path, query)
        if header is None:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message) -> None:
            if (
                message["type"] == "http.response.start"
                and message.get("status", 200) == 200
                and not _has_header(message, "cache-control")
            ):
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", header.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _header_for(path: str, query: str) -> str | None:
    if path.endswith(_JS_SUFFIXES):
        return _VERSIONED if "v=" in query else _REVALIDATE
    if path.endswith(_MEDIA_SUFFIXES):
        return _REVALIDATE
    if path.endswith(_HTML_SUFFIXES):
        return _NO_CACHE
    return None


def _has_header(message, name: str) -> bool:
    name_b = name.lower().encode("latin-1")
    return any(k.lower() == name_b for k, _v in message.get("headers", []))
