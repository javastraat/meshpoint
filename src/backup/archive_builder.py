"""Build a timestamped Meshpoint backup ``.tar.gz`` archive."""

from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.backup.manifest import FORMAT_VERSION, BackupFileEntry, BackupManifest
from src.backup.paths import (
    is_excluded_data_relative,
    resolve_data_dir,
    resolve_local_config_path,
    resolve_meshpoint_root,
)
from src.version import __version__

logger = logging.getLogger(__name__)

_ARCHIVE_PREFIX = "meshpoint-backup"
_CONFIG_ARCHIVE_PATH = "config/local.yaml"


@dataclass(frozen=True)
class BackupBuildResult:
    """Paths produced by :class:`BackupArchiveBuilder`."""

    archive_path: Path
    manifest: BackupManifest
    download_filename: str


class BackupArchiveBuilder:
    """Assemble ``local.yaml``, ``data/``, and a signed manifest into ``.tar.gz``."""

    def __init__(
        self,
        *,
        meshpoint_root: Path | None = None,
        local_config_path: Path | None = None,
        data_dir: Path | None = None,
        database_path: str = "data/concentrator.db",
        device_id: str = "",
        device_name: str = "",
    ) -> None:
        self._root = meshpoint_root or resolve_meshpoint_root()
        self._local_config = local_config_path or resolve_local_config_path()
        self._data_dir = data_dir or resolve_data_dir(database_path)
        self._database_path = Path(database_path)
        self._device_id = device_id
        self._device_name = device_name

    def build(self) -> BackupBuildResult:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        short_id = (self._device_id or "unknown")[:8]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle_name = f"{_ARCHIVE_PREFIX}-{short_id}-{stamp}"
        download_filename = f"{bundle_name}.tar.gz"

        staging_root = Path(tempfile.mkdtemp(prefix="meshpoint-backup-"))
        bundle_dir = staging_root / bundle_name
        bundle_dir.mkdir(parents=True)

        entries: list[BackupFileEntry] = []
        total_bytes = 0

        try:
            total_bytes += self._add_local_config(bundle_dir, entries)
            total_bytes += self._add_data_tree(bundle_dir, entries)

            manifest = BackupManifest(
                format_version=FORMAT_VERSION,
                meshpoint_version=__version__,
                created_at=created_at,
                device_id=self._device_id,
                device_name=self._device_name,
                entries=list(entries),
                total_bytes=total_bytes,
            )
            manifest_path = bundle_dir / "manifest.json"
            manifest_path.write_text(manifest.to_json(), encoding="utf-8")

            archive_path = Path(
                tempfile.mkstemp(
                    prefix=f"{bundle_name}-",
                    suffix=".tar.gz",
                )[1],
            )
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(bundle_dir, arcname=bundle_name)

            return BackupBuildResult(
                archive_path=archive_path,
                manifest=manifest,
                download_filename=download_filename,
            )
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    def _add_local_config(
        self,
        bundle_dir: Path,
        entries: list[BackupFileEntry],
    ) -> int:
        if not self._local_config.is_file():
            raise FileNotFoundError(
                f"local config not found: {self._local_config}",
            )
        dest = bundle_dir / _CONFIG_ARCHIVE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._local_config, dest)
        entry = self._entry_from_file(dest, _CONFIG_ARCHIVE_PATH)
        entries.append(entry)
        return entry.size_bytes

    def _add_data_tree(
        self,
        bundle_dir: Path,
        entries: list[BackupFileEntry],
    ) -> int:
        if not self._data_dir.is_dir():
            return 0

        total = 0
        db_name = self._database_path.name
        db_path = self._data_dir / db_name

        for path in sorted(self._data_dir.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self._data_dir).parts
            if is_excluded_data_relative(rel_parts):
                continue
            if path.name in {f"{db_name}-wal", f"{db_name}-shm"}:
                continue

            archive_rel = Path("data").joinpath(*rel_parts).as_posix()
            dest = bundle_dir / archive_rel

            if path == db_path:
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._snapshot_database(path, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

            entry = self._entry_from_file(dest, archive_rel)
            entries.append(entry)
            total += entry.size_bytes

        return total

    @staticmethod
    def _snapshot_database(source: Path, dest: Path) -> None:
        if dest.exists():
            dest.unlink()
        source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            dest_conn = sqlite3.connect(dest)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()

    @staticmethod
    def _entry_from_file(path: Path, archive_path: str) -> BackupFileEntry:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
        return BackupFileEntry(path=archive_path, sha256=digest, size_bytes=size)
