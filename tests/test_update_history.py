"""Unit tests for ``src.api.update.history`` (Updates-page history)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.api.update.history import (
    MAX_ENTRIES,
    append_history_entry,
    read_history,
    resolve_history_path,
)


class TestUpdateHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "update_history.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file_reads_empty(self) -> None:
        self.assertEqual(read_history(self.path), [])

    def test_append_then_read_roundtrip(self) -> None:
        ok = append_history_entry(
            {"kind": "apply", "branch": "main", "success": True},
            path=self.path,
        )
        self.assertTrue(ok)
        entries = read_history(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "apply")
        self.assertTrue(entries[0]["at"])  # timestamp stamped

    def test_newest_first(self) -> None:
        append_history_entry({"kind": "apply", "n": 1}, path=self.path)
        append_history_entry({"kind": "rollback", "n": 2}, path=self.path)
        entries = read_history(self.path)
        self.assertEqual([e["n"] for e in entries], [2, 1])

    def test_capped_at_max_entries(self) -> None:
        for i in range(MAX_ENTRIES + 5):
            append_history_entry({"n": i}, path=self.path)
        entries = read_history(self.path)
        self.assertEqual(len(entries), MAX_ENTRIES)
        self.assertEqual(entries[0]["n"], MAX_ENTRIES + 4)

    def test_limit_parameter(self) -> None:
        for i in range(8):
            append_history_entry({"n": i}, path=self.path)
        self.assertEqual(len(read_history(self.path, limit=5)), 5)

    def test_corrupt_file_reads_empty(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(read_history(self.path), [])

    def test_non_list_payload_reads_empty(self) -> None:
        self.path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(read_history(self.path), [])

    def test_append_survives_corrupt_file(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertTrue(append_history_entry({"n": 1}, path=self.path))
        self.assertEqual(len(read_history(self.path)), 1)

    def test_resolve_path_is_sibling_of_rollback_state(self) -> None:
        rb = Path("/opt/meshpoint/data/update_rollback.json")
        self.assertEqual(
            resolve_history_path(rb),
            Path("/opt/meshpoint/data/update_history.json"),
        )


if __name__ == "__main__":
    unittest.main()
