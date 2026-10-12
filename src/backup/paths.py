"""Path resolution helpers for backup and restore."""

from __future__ import annotations

import os
import re
from pathlib import Path

from src.config import _get_local_yaml_path

_EXCLUDED_DATA_DIR_PATTERN = re.compile(
    r"^(restore-incoming|backup-staging|pre-restore-stash-)"
)

MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def resolve_meshpoint_root() -> Path:
    """Return the Meshpoint install root (``MESHPOINT_DIR`` or cwd)."""
    return Path(os.environ.get("MESHPOINT_DIR", ".")).resolve()


def resolve_local_config_path() -> Path:
    """Resolved ``local.yaml`` path (honours ``CONCENTRATOR_CONFIG``)."""
    return _get_local_yaml_path()


def resolve_data_dir(database_path: str) -> Path:
    """Parent directory of the SQLite database file."""
    return Path(database_path).resolve().parent


def iter_included_data_files(data_dir: Path):
    """Yield every file under ``data_dir`` that belongs in a backup,
    skipping excluded top-level subtrees (``restore-incoming``,
    ``backup-staging``, ``pre-restore-stash-*``) WITHOUT walking into
    them first.

    Both callers of this (``BackupArchiveBuilder._add_data_tree`` and
    the backup-status size estimate) used to do ``Path.rglob("*")``
    then check each result's relative path against
    ``_EXCLUDED_DATA_DIR_PATTERN`` one file at a time -- ``rglob`` has no
    pruning API, so it always recurses into an excluded directory
    before that per-file check throws its contents away. A
    ``pre-restore-stash-*`` dir is a full copy of the data tree at
    restore time (made by ``scripts/restore_finish.sh``, never cleaned
    up automatically) -- after even one or two real restores, that
    silently multiplies the real file count several times over for
    every size estimate and every real backup build, with nothing to
    show for the extra I/O. ``os.walk`` lets a caller prune `dirnames`
    in place before it descends, so an excluded top-level directory is
    never opened at all. The exclusion pattern only ever matches a
    name at ``relative_parts[0]`` (it never excluded anything nested
    deeper), so pruning only ever needs to happen at the top level.

    Only yields entries that pass ``is_file()`` -- a broken symlink, a
    socket, or a device/FIFO node all land in ``os.walk``'s
    ``filenames`` list (it only tests ``is_dir()`` to sort entries into
    ``dirnames`` vs ``filenames``, nothing stronger), and ``Path.stat()``
    follows symlinks by default and raises ``FileNotFoundError`` on a
    dangling one. The old ``rglob()``-based version filtered exactly
    this way too (``if not path.is_file(): continue``) -- ``is_file()``
    itself never raises, it just returns ``False`` for any of these, so
    this preserves that same silent-skip behavior instead of ever
    5xx-ing a caller over a stray broken symlink somewhere in `data/`.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return
    top = True
    for dirpath, dirnames, filenames in os.walk(data_dir):
        if top:
            dirnames[:] = [d for d in dirnames if not _EXCLUDED_DATA_DIR_PATTERN.match(d)]
            top = False
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if path.is_file():
                yield path


def restore_finish_script(meshpoint_root: Path | None = None) -> Path:
    root = meshpoint_root or resolve_meshpoint_root()
    return root / "scripts" / "restore_finish.sh"


def launch_restore_finish_script(meshpoint_root: Path | None = None) -> Path:
    root = meshpoint_root or resolve_meshpoint_root()
    return root / "scripts" / "launch_restore_finish.sh"


def restore_incoming_dir(data_dir: Path) -> Path:
    return data_dir / "restore-incoming"
