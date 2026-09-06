"""Run ``sudo systemctl <args>`` for the narrowly-scoped subcommands
granted passwordless in ``config/sudoers-meshpoint``.

Shared by two callers: the RNode firmware flasher
(``src/api/routes/rnode_firmware_routes.py``), which stops/starts ``rnsd``
around a flash so it releases the serial port, and the Reticulum plugin's
config routes, which restart ``rnsd`` so it re-runs
``plugins/apps/reticulum/write_rnsd_config.py`` after an RNode/backbone
settings change.

Anything outside the exact ``rnsd`` subcommands listed in
``config/sudoers-meshpoint`` will prompt for a password rather than run.
Kept FastAPI-free so both callers (and their tests) can import it anywhere.
"""

from __future__ import annotations

import asyncio


async def run_systemctl(*args: str) -> tuple[int, str]:
    """Run ``sudo systemctl <args>``; return ``(returncode, combined
    stdout+stderr)``."""
    process = await asyncio.create_subprocess_exec(
        "sudo", "systemctl", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output = await process.stdout.read() if process.stdout else b""
    returncode = await process.wait()
    return returncode, output.decode("utf-8", errors="replace").strip()
