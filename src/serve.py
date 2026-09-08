"""Launcher for the meshpoint web server.

Reads the bind address from ``dashboard.host`` / ``dashboard.port`` in the
layered YAML config, then starts uvicorn against the app factory. This is
the single place the port is decided — the systemd unit runs
``python -m src.serve`` with no ``--host``/``--port`` args.

With ``dashboard.tls_enabled`` on, this runs *two* listeners concurrently:
the real dashboard over HTTPS on ``dashboard.tls_port``, and a minimal
redirect-only ASGI app on ``dashboard.port`` (plain HTTP) that 308s every
request to the HTTPS one. A single socket can't serve both HTTP and HTTPS
at once, so without this second listener, a browser hitting the old
``http://host:8080`` URL would just fail to connect instead of bouncing
to HTTPS.
"""

from __future__ import annotations

import logging
import socket

FALLBACK_HOST = "0.0.0.0"  # nosec B104 -- intentional for local device dashboard
FALLBACK_PORT = 8080

logger = logging.getLogger(__name__)


def _can_bind(host: str, port: int) -> bool:
    """Best-effort check that (host, port) is bindable by this process.

    SO_REUSEADDR matches uvicorn's own socket options, so a listener in
    TIME_WAIT from a service restart does not count as a conflict.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
        return True
    except OSError:
        return False


def _bind_address() -> tuple[str, int]:
    """Resolve host/port from config, falling back to defaults on any error.

    A broken local.yaml must not keep the server down: the dashboard is
    also the update/rollback UI, so a crash-loop here would lock the
    operator out of the tool that could fix the config.
    """
    try:
        from src.config import load_config

        dashboard = load_config().dashboard
        return dashboard.host, int(dashboard.port)
    except Exception:
        logger.exception(
            "Failed to read dashboard host/port from config; "
            "falling back to %s:%d",
            FALLBACK_HOST,
            FALLBACK_PORT,
        )
        return FALLBACK_HOST, FALLBACK_PORT


def _tls_files() -> tuple[str, str, int] | None:
    """(keyfile, certfile, tls_port) if ``dashboard.tls_enabled`` and the
    cert is ready, else ``None`` (plain HTTP only). Cert generation/
    regeneration failures fall back to HTTP rather than crash-loop the
    service -- same reasoning as ``_bind_address``'s own fallback: this
    dashboard is also the tool an operator would use to fix whatever's
    wrong."""
    try:
        from src.config import load_config

        dashboard = load_config().dashboard
        if not dashboard.tls_enabled:
            return None

        from src.tls_cert import ensure_cert

        ensure_cert(dashboard.tls_cert_path, dashboard.tls_key_path)
        return dashboard.tls_key_path, dashboard.tls_cert_path, int(dashboard.tls_port)
    except Exception:
        logger.exception(
            "dashboard.tls_enabled is set but the TLS cert could not be "
            "prepared; falling back to plain HTTP",
        )
        return None


def _make_https_redirect_app(tls_port: int):
    """A minimal ASGI app: 308-redirects every request to the same host
    and path, over HTTPS, on ``tls_port``. Uses the request's own Host
    header rather than a fixed address, so it works no matter which of
    the dashboard's several reachable addresses (LAN IP, VPN IP, ``.local``
    hostname -- see ``src/tls_cert.py``) someone actually hit :8080 on."""

    async def app(scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        headers = dict(scope["headers"])
        host = headers.get(b"host", b"").decode("latin-1").split(":")[0]
        if not host:
            host = scope.get("server", (FALLBACK_HOST, None))[0]
        target = f"https://{host}:{tls_port}{scope['path']}"
        query_string = scope.get("query_string")
        if query_string:
            target += f"?{query_string.decode('latin-1')}"
        await send({
            "type": "http.response.start",
            "status": 308,
            "headers": [(b"location", target.encode("latin-1"))],
        })
        await send({"type": "http.response.body", "body": b""})

    return app


def main() -> None:
    import asyncio

    import uvicorn

    host, port = _bind_address()
    # A config that loads but cannot bind (privileged port as non-root,
    # port already taken, bad host) would otherwise crash-loop the service
    # with no dashboard left to fix it from.
    if (host, port) != (FALLBACK_HOST, FALLBACK_PORT) and not _can_bind(host, port):
        logger.error(
            "Cannot bind configured dashboard address %s:%d; "
            "falling back to %s:%d (fix dashboard.host/port in local.yaml)",
            host,
            port,
            FALLBACK_HOST,
            FALLBACK_PORT,
        )
        host, port = FALLBACK_HOST, FALLBACK_PORT

    tls = _tls_files()
    if tls is not None:
        _, _, tls_port = tls
        if not _can_bind(host, tls_port):
            logger.error(
                "dashboard.tls_enabled is set but %s:%d can't be bound; "
                "disabling TLS for this run (fix dashboard.tls_port in local.yaml)",
                host,
                tls_port,
            )
            tls = None

    if tls is None:
        uvicorn.run("src.api.server:create_app", factory=True, host=host, port=port)
        return

    keyfile, certfile, tls_port = tls
    logger.info(
        "HTTPS enabled -- dashboard on %s:%d, plain HTTP on %s:%d now redirects to it",
        host, tls_port, host, port,
    )

    https_server = uvicorn.Server(uvicorn.Config(
        "src.api.server:create_app", factory=True, host=host, port=tls_port,
        ssl_keyfile=keyfile, ssl_certfile=certfile,
    ))
    redirect_server = uvicorn.Server(uvicorn.Config(
        _make_https_redirect_app(tls_port), host=host, port=port, log_level="warning",
    ))

    async def _serve_both() -> None:
        await asyncio.gather(https_server.serve(), redirect_server.serve())

    asyncio.run(_serve_both())


if __name__ == "__main__":
    main()
