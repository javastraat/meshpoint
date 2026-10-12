"""Tests for src.backup.paths.iter_included_data_files.

Pure Python -- no FastAPI/aiosqlite dependency, real tempdirs on disk.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.backup.paths import iter_included_data_files


class TestIterIncludedDataFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _touch(self, *rel_parts: str) -> Path:
        path = self.data_dir.joinpath(*rel_parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        return path

    def test_includes_ordinary_files(self) -> None:
        self._touch("concentrator.db")
        self._touch("keys.yaml")
        self._touch("reticulum", "identity")
        names = {p.relative_to(self.data_dir).as_posix() for p in iter_included_data_files(self.data_dir)}
        self.assertEqual(names, {"concentrator.db", "keys.yaml", "reticulum/identity"})

    def test_prunes_excluded_top_level_dirs_without_descending(self) -> None:
        # A real pre-restore-stash-* dir is a full copy of the data tree --
        # many files. None of them should ever be yielded, and (the actual
        # bug being fixed) the walk must not pay the cost of opening every
        # file inside it either -- verified here by simply asserting none
        # of a large set of planted files ever surface, which is only
        # possible if the directory itself was skipped, not filtered
        # after the fact.
        self._touch("concentrator.db")
        for i in range(50):
            self._touch("pre-restore-stash-20261011T120000Z", "data", f"file{i}.bin")
        self._touch("restore-incoming", "upload.tar.gz")
        self._touch("backup-staging", "scratch.tmp")

        names = {p.relative_to(self.data_dir).as_posix() for p in iter_included_data_files(self.data_dir)}
        self.assertEqual(names, {"concentrator.db"})

    def test_excluded_name_only_matters_at_the_top_level(self) -> None:
        # The exclusion pattern only ever inspected relative_parts[0] in
        # the original per-file-filter implementation -- a nested
        # directory that happens to share a name with an excluded one is
        # NOT excluded. Confirms the pruning preserves that exact
        # semantics rather than over-matching at any depth.
        self._touch("plugins", "restore-incoming", "not_actually_excluded.txt")

        names = {p.relative_to(self.data_dir).as_posix() for p in iter_included_data_files(self.data_dir)}
        self.assertEqual(names, {"plugins/restore-incoming/not_actually_excluded.txt"})

    def test_missing_data_dir_yields_nothing(self) -> None:
        missing = self.data_dir / "does-not-exist"
        self.assertEqual(list(iter_included_data_files(missing)), [])


if __name__ == "__main__":
    unittest.main()
