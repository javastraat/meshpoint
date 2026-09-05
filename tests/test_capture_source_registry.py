"""Tests for the plugin capture-source-registry seam.

Pure Python -- src/api/capture_source_registry.py has no FastAPI import.
Fake CaptureSource-shaped objects stand in for real ones (DapnetSerialSource
et al); the registry doesn't care what a "source" actually is, only that
build() returns one (or a tuple of them). The create_app side (that
_build_pipeline actually drains build_all() into the coordinator before
pipeline.start(), and wire_all() runs after) is integration-level and needs
fastapi, so it isn't covered here.
"""

from __future__ import annotations

import unittest

from src.api import capture_source_registry
from src.api.capture_source_registry import CaptureSourceSpec


class _FakeSource:
    def __init__(self, name: str) -> None:
        self.name = name


class TestCaptureSourceRegistry(unittest.TestCase):
    def setUp(self) -> None:
        capture_source_registry.reset()

    def tearDown(self) -> None:
        capture_source_registry.reset()

    def test_register_and_read_back(self) -> None:
        spec = CaptureSourceSpec("x", lambda: _FakeSource("x"))
        capture_source_registry.register_capture_source(spec)
        self.assertEqual(capture_source_registry.plugin_specs(), [spec])

    def test_plugin_specs_returns_a_copy(self) -> None:
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("x", lambda: _FakeSource("x")),
        )
        capture_source_registry.plugin_specs().clear()
        self.assertEqual(len(capture_source_registry.plugin_specs()), 1)

    def test_build_all_returns_a_flat_list_across_specs(self) -> None:
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("single", lambda: _FakeSource("a")),
        )
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("multi", lambda: (_FakeSource("b"), _FakeSource("c"))),
        )
        built = capture_source_registry.build_all()
        self.assertEqual([s.name for s in built], ["a", "b", "c"])

    def test_build_all_is_idempotent_per_call(self) -> None:
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("x", lambda: _FakeSource("x")),
        )
        first = capture_source_registry.build_all()
        second = capture_source_registry.build_all()
        # Two independent calls -- e.g. two create_app() calls in tests
        # without a reset() between them -- must not accumulate duplicate
        # entries in the internal _built bookkeeping used by wire_all().
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)

    def test_wire_all_hands_each_spec_its_own_built_sources_and_the_pipeline(self) -> None:
        seen = []
        pipeline = object()
        capture_source_registry.register_capture_source(
            CaptureSourceSpec(
                "single", lambda: _FakeSource("a"),
                wire=lambda sources, pl: seen.append((sources, pl)),
            ),
        )
        capture_source_registry.register_capture_source(
            CaptureSourceSpec(
                "multi", lambda: (_FakeSource("b"), _FakeSource("c")),
                wire=lambda sources, pl: seen.append((sources, pl)),
            ),
        )
        capture_source_registry.build_all()
        capture_source_registry.wire_all(pipeline)

        self.assertEqual(len(seen), 2)
        (single_sources, single_pipeline), (multi_sources, multi_pipeline) = seen
        self.assertEqual([s.name for s in single_sources], ["a"])
        self.assertEqual([s.name for s in multi_sources], ["b", "c"])
        self.assertIs(single_pipeline, pipeline)
        self.assertIs(multi_pipeline, pipeline)

    def test_wire_all_skips_specs_with_no_wire_callback(self) -> None:
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("x", lambda: _FakeSource("x")),  # no wire=
        )
        capture_source_registry.build_all()
        capture_source_registry.wire_all(object())  # must not raise

    def test_reset_clears_specs_and_built(self) -> None:
        capture_source_registry.register_capture_source(
            CaptureSourceSpec("x", lambda: _FakeSource("x")),
        )
        capture_source_registry.build_all()
        capture_source_registry.reset()
        self.assertEqual(capture_source_registry.plugin_specs(), [])
        # wire_all() after a reset() with no specs registered is a no-op,
        # not a crash from stale _built state.
        capture_source_registry.wire_all(object())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
