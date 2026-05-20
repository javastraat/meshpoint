"""Read the live install tree branch and compare to upstream."""

from __future__ import annotations

import logging
import re
import subprocess
import urllib.request
from typing import Callable, Optional

from src.api.update.channels import ReleaseChannelRegistry, TIER_CUSTOM
from src.version import __version__

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')
GitRunner = Callable[[list[str], Optional[str], float], tuple[int, str, str]]


def default_git_runner(
    args: list[str], cwd: Optional[str], timeout_seconds: float,
) -> tuple[int, str, str]:
    completed = subprocess.run(  # noqa: S603
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def read_install_git_ref(
    repo_path: str,
    *,
    runner: GitRunner = default_git_runner,
    use_sudo: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(branch_name, short_sha)`` for HEAD in the install tree."""
    prefix = ["sudo"] if use_sudo else []
    base = [*prefix, "git", "-C", repo_path]

    rc, branch_out, _ = runner([*base, "rev-parse", "--abbrev-ref", "HEAD"], None, 10.0)
    branch = branch_out.strip() if rc == 0 else None
    if branch == "HEAD":
        branch = _read_detached_branch_name(base, runner)

    rc, sha_out, _ = runner([*base, "rev-parse", "--short=8", "HEAD"], None, 10.0)
    sha = sha_out.strip() if rc == 0 else None
    return branch or None, sha or None


def _read_detached_branch_name(
    base: list[str], runner: GitRunner,
) -> Optional[str]:
    """Best-effort branch name when HEAD is detached at a remote tip."""
    rc, out, _ = runner(
        [*base, "rev-parse", "--abbrev-ref", "HEAD@{upstream}"],
        None,
        10.0,
    )
    if rc != 0:
        return None
    ref = out.strip()
    if ref.startswith("origin/"):
        return ref[len("origin/"):]
    return ref or None


def match_channel_for_branch(
    registry: ReleaseChannelRegistry, branch: str,
) -> dict[str, str]:
    """Map an install branch name back to a picker channel (or custom)."""
    for channel in registry.channels():
        if channel.branch and channel.branch == branch:
            return {
                "active_channel_id": channel.id,
                "active_channel_label": channel.label,
                "channel_tier": channel.tier,
            }
    if branch == "main":
        stable = registry.find("stable")
        if stable is not None:
            return {
                "active_channel_id": stable.id,
                "active_channel_label": stable.label,
                "channel_tier": stable.tier,
            }
    return {
        "active_channel_id": "custom",
        "active_channel_label": f"Custom ({branch})" if branch else "Custom branch",
        "channel_tier": TIER_CUSTOM,
    }


def fetch_remote_version_sync(branch: str) -> Optional[str]:
    url = (
        "https://raw.githubusercontent.com/KMX415/meshpoint/"
        f"{branch}/src/version.py"
    )
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode()
            match = _VERSION_RE.search(text)
            return match.group(1) if match else None
    except Exception:
        logger.debug(
            "Could not fetch remote version for branch %s", branch, exc_info=True,
        )
        return None


def _parse_version(version_str: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version_str.split("."))


def build_install_status_payload(
    *,
    registry: ReleaseChannelRegistry,
    repo_path: str = "/opt/meshpoint",
    runner: GitRunner = default_git_runner,
    use_sudo: bool = True,
) -> dict:
    """Assemble the JSON body for ``GET /api/update/install_status``."""
    branch, sha = read_install_git_ref(
        repo_path, runner=runner, use_sudo=use_sudo,
    )
    channel_info = match_channel_for_branch(registry, branch or "main")
    remote_version = None
    update_available = False
    if branch:
        remote_version = fetch_remote_version_sync(branch)
        if remote_version:
            try:
                update_available = (
                    _parse_version(remote_version) > _parse_version(__version__)
                )
            except ValueError:
                update_available = False
    return {
        "local_version": __version__,
        "install_branch": branch,
        "install_sha_short": sha,
        "remote_version": remote_version,
        "remote_branch": branch,
        "update_available": update_available,
        **channel_info,
    }
