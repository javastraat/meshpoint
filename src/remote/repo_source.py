"""Resolve which GitHub repo this checkout's self-update machinery targets.

Reads the ``origin`` remote straight out of ``.git/config`` (no ``git``
subprocess, so it sidesteps the dubious-ownership/safe.directory check
entirely) and derives ``owner/repo`` from it. A fork's origin resolves
automatically with zero configuration; anything we can't parse (no repo,
no origin, a non-GitHub host) falls back to the upstream project rather
than any particular fork.
"""

from __future__ import annotations

import configparser
import re

from src.backup.paths import resolve_meshpoint_root

UPSTREAM_OWNER_REPO = "KMX415/meshpoint"

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?/?$")
_HTTPS_URL_RE = re.compile(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$")

_cache: str | None = None


def resolve_owner_repo() -> str:
    """Return ``owner/repo`` for this checkout's origin, cached for the process."""
    global _cache
    if _cache is None:
        _cache = _parse_origin_owner_repo() or UPSTREAM_OWNER_REPO
    return _cache


def _parse_origin_owner_repo() -> str | None:
    config_path = resolve_meshpoint_root() / ".git" / "config"
    parser = configparser.ConfigParser()
    try:
        if not parser.read(config_path):
            return None
        url = parser.get('remote "origin"', "url", fallback=None)
    except configparser.Error:
        return None
    if not url:
        return None

    for pattern in (_SSH_URL_RE, _HTTPS_URL_RE):
        match = pattern.match(url.strip())
        if match:
            host, owner_repo = match.group(1), match.group(2)
            return owner_repo if host.lower() == "github.com" else None
    return None


def github_raw_url(branch: str, path: str) -> str:
    """Build a raw.githubusercontent.com URL for ``path`` on ``branch``."""
    return f"https://raw.githubusercontent.com/{resolve_owner_repo()}/{branch}/{path}"
