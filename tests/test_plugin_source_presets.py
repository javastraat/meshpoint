"""Settings -> Plugins -> Add source presets (frontend/data/plugin_sources.json)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.plugins.sources import parse_github_url

PRESETS = Path(__file__).resolve().parents[1] / "frontend" / "data" / "plugin_sources.json"


class PluginSourcePresetsTest(unittest.TestCase):
    def test_presets_are_valid_github_sources(self):
        presets = json.loads(PRESETS.read_text())["presets"]
        urls = {p["url"] for p in presets}
        self.assertIn("https://github.com/javastraat/meshpoint-plugins", urls)
        self.assertIn("https://github.com/KMX415/meshpoint-plugins", urls)  # TODO.md item 37f
        for preset in presets:
            with self.subTest(label=preset["label"]):
                self.assertTrue(preset["label"] and preset.get("description"))
                parse_github_url(preset["url"])  # raises on anything that isn't a repo URL


if __name__ == "__main__":
    unittest.main()
