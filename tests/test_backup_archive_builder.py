"""Tests for backup archive construction."""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from src.backup.archive_builder import BackupArchiveBuilder
from src.backup.encryption import decrypt_archive, is_encrypted


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

    def test_build_with_password_produces_encrypted_mpenc(self) -> None:
        builder = BackupArchiveBuilder(
            meshpoint_root=self.root,
            local_config_path=self.config_dir / "local.yaml",
            data_dir=self.data_dir,
            database_path="data/concentrator.db",
            device_id="test-device-001",
            device_name="Lab Meshpoint",
        )
        result = builder.build(password="correct horse battery staple")
        try:
            self.assertTrue(result.download_filename.endswith(".tar.gz.mpenc"))
            payload = result.archive_path.read_bytes()
            self.assertTrue(is_encrypted(payload))

            plaintext = decrypt_archive(payload, "correct horse battery staple")
            with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as tar:
                names = tar.getnames()
                self.assertTrue(any(n.endswith("manifest.json") for n in names))
        finally:
            try:
                result.archive_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_build_without_password_is_unchanged(self) -> None:
        builder = BackupArchiveBuilder(
            meshpoint_root=self.root,
            local_config_path=self.config_dir / "local.yaml",
            data_dir=self.data_dir,
            database_path="data/concentrator.db",
            device_id="test-device-001",
            device_name="Lab Meshpoint",
        )
        result = builder.build(password=None)
        try:
            self.assertTrue(result.download_filename.endswith(".tar.gz"))
            self.assertFalse(result.download_filename.endswith(".mpenc"))
            self.assertFalse(is_encrypted(result.archive_path.read_bytes()))
        finally:
            try:
                result.archive_path.unlink(missing_ok=True)
            except PermissionError:
                pass


if __name__ == "__main__":
    unittest.main()
