"""Tests for backup manifest serialization."""

from __future__ import annotations

import unittest

from src.backup.manifest import (
    FORMAT_VERSION,
    BackupFileEntry,
    BackupManifest,
)


class TestBackupManifest(unittest.TestCase):
    def test_round_trip_json(self) -> None:
        manifest = BackupManifest(
            format_version=FORMAT_VERSION,
            meshpoint_version="0.7.7",
            created_at="2026-06-11T12:00:00Z",
            device_id="abcd-1234",
            device_name="Test Meshpoint",
            entries=[
                BackupFileEntry(
                    path="config/local.yaml",
                    sha256="a" * 64,
                    size_bytes=42,
                ),
            ],
            total_bytes=42,
        )
        restored = BackupManifest.from_json(manifest.to_json())
        self.assertEqual(restored.format_version, FORMAT_VERSION)
        self.assertEqual(restored.device_id, "abcd-1234")
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].path, "config/local.yaml")


if __name__ == "__main__":
    unittest.main()
