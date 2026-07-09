"""Tests for backup archive construction."""

from __future__ import annotations

import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from src.backup.archive_builder import BackupArchiveBuilder


class TestBackupArchiveBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_dir = self.root / "config"
        self.data_dir = self.root / "data"
        self.config_dir.mkdir()
        self.data_dir.mkdir()
        (self.config_dir / "local.yaml").write_text(
            "device:\n  device_id: test-device-001\n",
            encoding="utf-8",
        )
        db_path = self.data_dir / "concentrator.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO nodes(name) VALUES ('alpha')")
            conn.commit()
        finally:
            conn.close()
        (self.data_dir / "keys.yaml").write_text("private_key: deadbeef\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_builds_tar_with_manifest_and_files(self) -> None:
        builder = BackupArchiveBuilder(
            meshpoint_root=self.root,
            local_config_path=self.config_dir / "local.yaml",
            data_dir=self.data_dir,
            database_path="data/concentrator.db",
            device_id="test-device-001",
            device_name="Lab Meshpoint",
        )
        result = builder.build()
        try:
            with tarfile.open(result.archive_path, "r:gz") as tar:
                names = tar.getnames()
                bundle_dirs = {n.split("/")[0] for n in names if "/" in n}
                self.assertEqual(len(bundle_dirs), 1)
                prefix = next(iter(bundle_dirs))
                manifest_member = f"{prefix}/manifest.json"
                self.assertIn(manifest_member, names)
                manifest = json.loads(
                    tar.extractfile(manifest_member).read().decode("utf-8"),
                )
                self.assertEqual(manifest["device_id"], "test-device-001")
                paths = {entry["path"] for entry in manifest["entries"]}
                self.assertIn("config/local.yaml", paths)
                self.assertIn("data/concentrator.db", paths)
                self.assertIn("data/keys.yaml", paths)
        finally:
            try:
                result.archive_path.unlink(missing_ok=True)
            except PermissionError:
                pass


if __name__ == "__main__":
    unittest.main()
