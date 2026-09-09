"""``meshpoint plugin list`` / ``meshpoint plugin setup <id>``.

``list`` queries the running service's ``GET /api/plugins`` (same
login-fallback flow as ``meshpoint report``) since only the live process
knows whether a plugin is actually *loaded*, not just configured to load.
``setup`` is pure local filesystem + subprocess -- no running service
required, since installing a plugin's system deps (apt packages + its own
``setup.sh``) is independent of whether Meshpoint itself is up.
"""

from __future__ import annotations

import json
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
    if any(p.get("has_deps_check") for p in plugins):
        print(
            f"  {_DIM}dep state is the boot-time snapshot -- "
            f"'meshpoint plugin check' re-runs the probes live.{_RESET}"
        )
    print()


def run_plugin_check(plugin_id: str | None = None) -> int:
    """Re-run one plugin's (or every checkable plugin's) ``[deps] check``
    probe *inside the running service* and print the fresh verdict.

    This is the authoritative check: the probe runs server-side as the
    ``meshpoint`` service account -- exactly the context the loader uses at
    boot -- so it doesn't matter which shell (SSH, web Terminal) invokes
    the CLI. ``meshpoint plugin list`` by contrast only echoes the
    boot-time snapshot, which goes stale if deps change on the device
    afterwards.
    """
    client = CliApiClient()
    plugins = _fetch_plugins(client)  # also establishes the admin session
    if plugins is None:
        return 1

    if plugin_id is not None:
        targets = [plugin_id]
    else:
        targets = [p["id"] for p in plugins if p.get("has_deps_check")]
        if not targets:
            print("\n  No plugin declares a [deps] check script.\n")
            return 0

    print()
    exit_code = 0
    for pid in targets:
        try:
            body = client.post(f"/api/plugins/{pid}/check")
        except AuthRequired:
            print("  Re-check needs a dashboard admin login.\n")
            return 1
        except (ServiceDown, ApiError) as exc:
            print(f"  {pid:<20} {_YELLOW}re-check failed: {exc}{_RESET}")
            exit_code = 1
            continue
        p = body.get("plugin", {})
        deps_ok = p.get("deps_ok")
        if deps_ok is True:
            print(f"  {pid:<20} {_GREEN}dependencies installed{_RESET}")
        elif deps_ok is False:
            first = (p.get("deps_detail") or "").splitlines()
            print(f"  {pid:<20} {_YELLOW}setup needed{_RESET}"
                  + (f" -- {first[0]}" if first else ""))
            exit_code = 1
        else:
            print(f"  {pid:<20} {_DIM}no verdict{_RESET}")
    print()
    return exit_code


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
    # A plugin can need setup.sh with no apt packages at all (e.g. a
    # from-source build like ADS-B's dump1090 -- its build tools are
    # already covered by scripts/install.sh's base system packages), so
    # this must show whenever EITHER is present, not just apt_deps being
    # non-empty -- same bug/fix as plugins_panel_controller.js's web
    # equivalent of this row.
    apt_deps = p.get("apt_deps") or []
    deps_ok = p.get("deps_ok")
    if deps_ok is False:
        why = (p.get("deps_detail") or "").splitlines()
        print(
            f"      {_YELLOW}deps: setup needed"
            f"{f' -- {why[0]}' if why else ''} "
            f"-- run: meshpoint plugin setup {p['id']}{_RESET}"
        )
    elif deps_ok is True:
        print(f"      {_DIM}deps: installed{_RESET}")
    elif apt_deps or p.get("setup_script"):
        deps_label = ', '.join(apt_deps) if apt_deps else "a build step"
        print(
            f"      {_DIM}deps: {deps_label} "
            f"-- run: meshpoint plugin setup {p['id']}{_RESET}"
        )


def run_plugin_setup(plugin_id: str, *, skip_confirm: bool = False) -> int:
    """Show a plugin's [deps] and, after confirmation, run its setup.sh
    (apt + build). Returns a process exit code."""
    from src.config import load_config
    from src.plugins.manifest import discover_plugins

    config = load_config()
    builtin_dir = Path(__file__).resolve().parents[1] / "plugins" / "apps"
    # .resolve() (not just Path(...)) -- config.dashboard.plugins_dir is
    # CWD-relative by convention ("plugins", same as static_dir), and a
    # relative setup_path here would get passed to `sudo bash` as a
    # relative argv, which config/sudoers-meshpoint's NOPASSWD rule (an
    # absolute path pattern, matching this file's own path-discipline
    # convention) would never match -- silently falling back to a
    # password prompt in a non-interactive context.
    community_dir = Path(config.dashboard.plugins_dir).resolve() / "apps"

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


def run_plugin_index(repo_dir: str, *, write: bool = False) -> int:
    """Generate a plugin repo's ``repo.json`` from the ``plugin.toml``
    / ``theme.json`` files under its ``apps/`` and ``themes/`` dirs.

    Run this *in the plugin repo* (not on a device). It's the tool a repo
    author uses to keep the browse catalog in sync -- Meshpoint re-reads
    the real manifests on install anyway, so this file is only metadata.
    """
    from src.plugins.manifest import PluginManifestError, parse_manifest

    root = Path(repo_dir).expanduser().resolve()
    if not root.is_dir():
        print(f"  {root} is not a directory.\n")
        return 1

    plugins: list[dict] = []
    for child in sorted((root / "apps").glob("*/")):
        if not (child / "plugin.toml").is_file():
            continue
        try:
            m = parse_manifest(child)
        except PluginManifestError as exc:
            print(f"  {_YELLOW}skip apps/{child.name}: {exc}{_RESET}")
            continue
        plugins.append({
            "id": m.name,
            "kind": "app",
            "path": f"apps/{m.name}",
            "version": m.version,
            "meshpoint_api": m.api_version,
            "provides": list(m.provides),
            "description": m.description,
            "author": m.author,
            "homepage": m.homepage,
            "has_setup": m.setup is not None,
        })

    themes: list[dict] = []
    for child in sorted((root / "themes").glob("*/")):
        manifest = child / "theme.json"
        if not manifest.is_file():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"  {_YELLOW}skip themes/{child.name}: {exc}{_RESET}")
            continue
        tid = str(raw.get("id") or child.name).strip()
        themes.append({
            "id": tid,
            "kind": "theme",
            "path": f"themes/{tid}",
            "version": str(raw.get("version") or "1.0.0"),
            "description": str(raw.get("description") or ""),
            "author": str(raw.get("author") or ""),
            "homepage": str(raw.get("homepage") or ""),
        })

    doc: dict = {
        "meshpoint_repo": 1,
        "name": root.name,
        "plugins": plugins,
    }
    if themes:
        doc["themes"] = themes

    rendered = json.dumps(doc, indent=2) + "\n"
    if write:
        (root / "repo.json").write_text(rendered, encoding="utf-8")
        print(f"  Wrote {root / 'repo.json'} "
              f"({len(plugins)} plugin(s), {len(themes)} theme(s)).\n")
    else:
        print(rendered)
    return 0


def _confirm(message: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = input(f"  {message} {suffix} ").strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes")
