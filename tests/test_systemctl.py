"""src.api.systemctl.run_systemctl shells out to `sudo systemctl <args>`.

Pure Python, no FastAPI. The subprocess call is patched -- we only check
argv construction and the (returncode, text) shape, not that sudo/systemctl
actually run.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from src.api import systemctl


class _FakeProc:
    def __init__(self, out: bytes, rc: int) -> None:
        self.stdout = mock.AsyncMock()
        self.stdout.read.return_value = out
        self._rc = rc

    async def wait(self) -> int:
        return self._rc


class TestRunSystemctl(unittest.TestCase):
    def test_builds_sudo_systemctl_argv_and_returns_rc_and_text(self) -> None:
        with mock.patch.object(
            systemctl.asyncio, "create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProc(b"  restarted\n", 0)),
        ) as spawn:
            rc, out = asyncio.run(systemctl.run_systemctl("restart", "rnsd"))
        self.assertEqual((rc, out), (0, "restarted"))
        args, _kwargs = spawn.call_args
        self.assertEqual(args[:4], ("sudo", "systemctl", "restart", "rnsd"))

    def test_nonzero_exit_is_passed_through(self) -> None:
        with mock.patch.object(
            systemctl.asyncio, "create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProc(b"Unit rnsd.service not found.", 5)),
        ):
            rc, out = asyncio.run(systemctl.run_systemctl("restart", "rnsd"))
        self.assertEqual(rc, 5)
        self.assertIn("not found", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
