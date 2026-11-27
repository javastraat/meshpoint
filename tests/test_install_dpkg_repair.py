"""install.sh / install-debian.sh repair an interrupted dpkg before any apt call (TODO 40).

Upstream KMX415/meshpoint 3ca92469: a run cut short (power cut, Ctrl+C, a
dropped SSH session) leaves dpkg half-configured, and every following
apt-get then refuses with "dpkg was interrupted". On an upgrade the scripts
now run ``dpkg --configure -a`` first. Unlike upstream we keep
``apt-get upgrade`` (our dashboard Apply never runs install.sh, so a manual
run may as well update the system) and keep ``python3 -m venv`` on the
existing venv (reusing it as-is breaks after a Python version change).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
SCRIPTS = ("install.sh", "install-debian.sh")
MARKER = "# ── Repair an interrupted dpkg"


def _source(script: str) -> str:
    return (ROOT / "scripts" / script).read_text(encoding="utf-8")


class TestRepairComesFirst(unittest.TestCase):
    def test_repair_before_the_first_apt_call(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                text = _source(script)
                self.assertIn("dpkg --configure -a", text)
                repair = text.index("dpkg --configure -a")
                # The upgrade fast path's apt-get install and section 1's apt-get update.
                self.assertLess(repair, text.index("    _upgrade_refresh_python_deps\nfi"))
                self.assertLess(repair, text.index("\napt-get update -qq"))

    def test_full_upgrade_and_venv_stay(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertIn("\napt-get upgrade -y -qq", _source(script))
        self.assertIn('\npython3 -m venv "${MESHPOINT_DIR}/venv"', _source("install.sh"))


@unittest.skipUnless(BASH, "bash is needed to run the installer block")
class TestRepairBlock(unittest.TestCase):
    def _run(self, script: str, is_upgrade: str) -> list[str]:
        text = _source(script)
        start = text.index(MARKER)
        block = text[start:text.index("# ── Upgrade fast path", start)]
        stub = (
            "set -e\ninfo() { :; }\n"
            'dpkg() { echo "dpkg $*" >> calls; }\n'
            'apt-get() { echo "apt-get $*" >> calls; }\n'
            f"IS_UPGRADE={is_upgrade}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([BASH, "-c", stub + block], cwd=tmp, check=True)
            calls = Path(tmp) / "calls"
            return calls.read_text().splitlines() if calls.exists() else []

    def test_upgrade_runs_the_repair(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(self._run(script, "1"), ["dpkg --configure -a"])

    def test_fresh_install_skips_it(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(self._run(script, "0"), [])


if __name__ == "__main__":
    unittest.main()
