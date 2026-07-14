"""Tests for the on-USB-connect companion_name re-apply helper.

The helper (``_reapply_companion_name`` in ``src.api.server``) runs
right after ``sync_channels`` whenever a MeshCore USB capture source
successfully (re)connects. For the primary companion (``is_primary``),
it falls back to the legacy mesh-wide ``meshcore.companion_name`` field
when that companion has no per-entry name of its own configured in
``capture.meshcore_usb`` -- so a freshly-flashed companion or a
hot-swap lands on the configured name without a manual dashboard
re-save, the same shape as how ``sync_channels`` keeps user channel
keys consistent. These tests cover that legacy-fallback path
specifically (source has no matching ``capture.meshcore_usb`` entry of
its own, ``is_primary=True``); per-companion name resolution itself is
covered in ``test_meshcore_companion_name_route.py``/server.py's own
``_desired_companion_name`` callers.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.api.server import _reapply_companion_name


class _RenameResult:
    def __init__(self, success: bool, error: str | None = None):
        self.success = success
        self.error = error


def _config(companion_name: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        meshcore=SimpleNamespace(companion_name=companion_name),
        # Empty so _desired_companion_name() falls through to the
        # legacy meshcore.companion_name field above -- these tests
        # are specifically about that fallback, not a per-companion
        # capture.meshcore_usb[i].companion_name match.
        capture=SimpleNamespace(meshcore_usb=[]),
    )


def _source() -> MagicMock:
    # .name must be a real string (not an unconfigured MagicMock
    # attribute) -- _reapply_companion_name resolves this source's own
    # label via source.name.startswith(...)/slicing.
    mc_tx = MagicMock()
    mc_tx.name = "meshcore_usb"
    return mc_tx


class TestReapplyCompanionNameOnConnect(unittest.IsolatedAsyncioTestCase):

    async def test_skip_when_desired_empty(self):
        mc_tx = _source()
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock()
        await _reapply_companion_name(mc_tx, _config(None), True)
        mc_tx.set_companion_name.assert_not_called()

    async def test_skip_when_desired_whitespace_only(self):
        mc_tx = _source()
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock()
        await _reapply_companion_name(mc_tx, _config("   \t  "), True)
        mc_tx.set_companion_name.assert_not_called()

    async def test_skip_when_not_connected(self):
        # Edge case: callback fires after a connect that was rolled back
        # before the callback ran. set_companion_name would 503 anyway,
        # but skipping locally avoids polluting logs and saves a round
        # trip to the device.
        mc_tx = _source()
        mc_tx.connected = False
        mc_tx.set_companion_name = AsyncMock()
        await _reapply_companion_name(mc_tx, _config("Mesh Lab East"), True)
        mc_tx.set_companion_name.assert_not_called()

    async def test_applies_stripped_name_on_success(self):
        mc_tx = _source()
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock(
            return_value=_RenameResult(success=True)
        )
        await _reapply_companion_name(mc_tx, _config("  Mesh Lab East  "), True)
        mc_tx.set_companion_name.assert_awaited_once_with("Mesh Lab East")

    async def test_logs_warning_on_failure_but_does_not_raise(self):
        # Channel sync ran first and is the more important call; a
        # failed rename re-apply must not bubble up and break the
        # subsequent connect callbacks (or the source's connect
        # bookkeeping).
        mc_tx = _source()
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock(
            return_value=_RenameResult(success=False, error="Companion ERROR")
        )
        await _reapply_companion_name(mc_tx, _config("Mesh Lab East"), True)
        mc_tx.set_companion_name.assert_awaited_once()

    async def test_swallows_unexpected_exceptions(self):
        mc_tx = _source()
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock(side_effect=RuntimeError("boom"))
        # Should not raise.
        await _reapply_companion_name(mc_tx, _config("Mesh Lab East"), True)

    async def test_non_primary_does_not_fall_back_to_legacy_field(self):
        # A non-primary companion with no per-entry companion_name of
        # its own must NOT inherit the legacy mesh-wide field -- that
        # fallback is primary-only (server.py's _desired_companion_name
        # docstring/reasoning).
        mc_tx = _source()
        mc_tx.name = "meshcore_usb_433"
        mc_tx.connected = True
        mc_tx.set_companion_name = AsyncMock()
        await _reapply_companion_name(mc_tx, _config("Mesh Lab East"), False)
        mc_tx.set_companion_name.assert_not_called()


if __name__ == "__main__":
    unittest.main()
