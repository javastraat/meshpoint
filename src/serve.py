"""Launcher for the meshpoint web server.

Reads the bind address from ``dashboard.host`` / ``dashboard.port`` in the
layered YAML config, then starts uvicorn against the app factory. This is
the single place the port is decided — the systemd unit runs
``python -m src.serve`` with no ``--host``/``--port`` args.
"""

from __future__ import annotations

import logging

FALLBACK_HOST = "0.0.0.0"  # nosec B104 -- intentional for local device dashboard
FALLBACK_PORT = 8080

logger = logging.getLogger(__name__)


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


def main() -> None:
    import uvicorn

    host, port = _bind_address()
    uvicorn.run("src.api.server:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    main()
