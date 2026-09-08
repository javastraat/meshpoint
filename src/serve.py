"""Launcher for the meshpoint web server.

Reads the bind address from ``dashboard.host`` / ``dashboard.port`` in the
layered YAML config, then starts uvicorn against the app factory. This is
the single place the port is decided — the systemd unit runs
``python -m src.serve`` with no ``--host``/``--port`` args.
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


def _tls_files() -> tuple[str, str] | None:
    """(keyfile, certfile) if ``dashboard.tls_enabled`` and the cert is
    ready, else ``None`` (plain HTTP). Cert generation/regeneration
    failures fall back to HTTP rather than crash-loop the service --
    same reasoning as ``_bind_address``'s own fallback: this dashboard
    is also the tool an operator would use to fix whatever's wrong."""
    try:
        from src.config import load_config

        dashboard = load_config().dashboard
        if not dashboard.tls_enabled:
            return None

        from src.tls_cert import ensure_cert

        ensure_cert(dashboard.tls_cert_path, dashboard.tls_key_path)
        return dashboard.tls_key_path, dashboard.tls_cert_path
    except Exception:
        logger.exception(
            "dashboard.tls_enabled is set but the TLS cert could not be "
            "prepared; falling back to plain HTTP",
        )
        return None


def main() -> None:
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
    ssl_kwargs = {}
    if tls is not None:
        keyfile, certfile = tls
        ssl_kwargs = {"ssl_keyfile": keyfile, "ssl_certfile": certfile}
        logger.info("HTTPS enabled -- serving with self-signed cert %s", certfile)

    uvicorn.run(
        "src.api.server:create_app", factory=True, host=host, port=port, **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
