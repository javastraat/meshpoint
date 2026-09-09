"""_ensure_secrets_header(): the sketch's `#include "secrets.h"` is
gitignored, so a fresh checkout (the Pi) has only secrets.h.example --
the compile route must seed secrets.h from it or arduino-cli dies with
"secrets.h: No such file or directory". FastAPI-gated like the other
dapnet backend tests (the module imports fastapi at top)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from plugins.apps.dapnet.backend import firmware_routes as fw
    _HAS_FASTAPI = True
except ImportError:  # no fastapi on the dev Mac -- runs on CI / the Pi
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "firmware_routes imports fastapi (CI / Pi only)")
class EnsureSecretsHeader(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self._patch = mock.patch.object(fw, "_SKETCH_DIR", self.dir)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_seeds_from_example_when_missing(self) -> None:
        (self.dir / "secrets.h.example").write_text('#define WIFI_SSID "x"\n')
        fw._ensure_secrets_header()
        self.assertTrue((self.dir / "secrets.h").is_file())
        self.assertEqual(
            (self.dir / "secrets.h").read_text(), '#define WIFI_SSID "x"\n',
        )

    def test_never_overwrites_an_existing_secrets_h(self) -> None:
        (self.dir / "secrets.h.example").write_text("placeholder\n")
        (self.dir / "secrets.h").write_text("REAL CREDS\n")
        fw._ensure_secrets_header()
        self.assertEqual((self.dir / "secrets.h").read_text(), "REAL CREDS\n")

    def test_no_example_is_a_noop_not_a_crash(self) -> None:
        fw._ensure_secrets_header()  # empty dir
        self.assertFalse((self.dir / "secrets.h").exists())


if __name__ == "__main__":
    unittest.main()
