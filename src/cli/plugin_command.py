"""``meshpoint plugin list`` / ``meshpoint plugin setup <id>``.

``list`` queries the running service's ``GET /api/plugins`` (same
login-fallback flow as ``meshpoint report``) since only the live process
knows whether a plugin is actually *loaded*, not just configured to load.
``setup`` is pure local filesystem + subprocess -- no running service
required, since installing a plugin's system deps (apt packages + its own
``setup.sh``) is independent of whether Meshpoint itself is up.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.cli.api_client import ApiError, AuthRequired, CliApiClient, ServiceDown

_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def run_plugin_list() -> None:
    """Print every discovered plugin with its enabled/loaded state."""
    client = CliApiClient()
    plugins = _fetch_plugins(client)
    if plugins is None:
        return

    print()
    print("  Plugins")
    print("  " + "=" * 60)
    if not plugins:
        print("  No plugins found under plugins/apps/.")
        print()
        return
    for p in plugins:
        _print_plugin_row(p)
    print()


def _fetch_plugins(client: CliApiClient) -> list | None:
    """The plugin list, or None (after printing why) if it can't be fetched."""
    try:
        return client.get("/api/plugins").get("plugins", [])
    except ServiceDown:
        print("\n  Meshpoint service is not running or unreachable.")
        print("  Start it with: sudo systemctl start meshpoint\n")
        return None
    except AuthRequired:
        pass  # fall through to the login flow below

    if client.login_local_root():
        try:
            return client.get("/api/plugins").get("plugins", [])
        except ApiError:
            pass

    print("\n  Service is running; listing plugins needs a dashboard admin login.")
    try:
        client.login_interactive()
        return client.get("/api/plugins").get("plugins", [])
    except AuthRequired:
        print("\n  Login failed (wrong credentials?).\n")
        return None
    except (ServiceDown, ApiError) as exc:
        print(f"\n  Login failed: {exc}\n")
        return None


def _print_plugin_row(p: dict) -> None:
    name = f"{p['id']} (v{p['version']})"
    source = p["source"]
    if p["enabled"] and p["loaded"]:
        state = f"{_GREEN}enabled, loaded{_RESET}"
    elif p["restart_required"]:
        state = f"{_YELLOW}{'enabled' if p['enabled'] else 'disabled'}, restart required{_RESET}"
    else:
        state = f"{_DIM}disabled{_RESET}"
    print(f"  {name:<28} {source:<10} {state}")
    if p.get("apt_deps"):
        print(
            f"      {_DIM}deps: {', '.join(p['apt_deps'])} "
            f"-- run: meshpoint plugin setup {p['id']}{_RESET}"
        )


def run_plugin_setup(plugin_id: str, *, skip_confirm: bool = False) -> int:
    """Show a plugin's [deps] and, after confirmation, run its setup.sh
    (apt + build). Returns a process exit code."""
    from src.config import load_config
    from src.plugins.manifest import discover_plugins

    config = load_config()
    builtin_dir = Path(__file__).resolve().parents[1] / "plugins" / "apps"
    community_dir = Path(config.dashboard.plugins_dir) / "apps"

    manifest = next(
        (m for m in discover_plugins(builtin_dir, community_dir) if m.name == plugin_id),
        None,
    )
    if manifest is None:
        print(
            f"\n  No plugin {plugin_id!r} found under {community_dir}/ or "
            f"{builtin_dir}/.\n"
        )
        return 1

    if manifest.setup is None:
        print(f"\n  {plugin_id!r} (v{manifest.version}) has no setup step -- nothing to install.\n")
        return 0

    print()
    print(f"  {plugin_id} v{manifest.version} ({manifest.source})")
    if manifest.apt:
        print(f"  System packages: {', '.join(manifest.apt)}")
    print(f"  Setup script:    {manifest.setup_path}")
    print()

    if not skip_confirm and not _confirm("Run this setup script now?"):
        print("  Cancelled.\n")
        return 1

    print()
    result = subprocess.run(["sudo", "bash", str(manifest.setup_path)], check=False)
    print()
    if result.returncode == 0:
        print(
            f"  Done. Enable it with plugins.{plugin_id}.enabled: true in "
            f"local.yaml (or Settings -> Plugins) and restart.\n"
        )
    else:
        print(f"  Setup script exited with code {result.returncode}.\n")
    return result.returncode


def _confirm(message: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = input(f"  {message} {suffix} ").strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes")
