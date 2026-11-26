"""Capture source for MeshCore USB nodes.

Connects to a MeshCore companion radio via USB serial using the
``meshcore`` Python library, subscribes to incoming events, and
yields them as RawCapture objects for the pipeline.

Includes auto-reconnect with exponential backoff and a periodic
health check so the source self-heals after serial disconnects.

Events are JSON-serialised and decoded downstream by
``meshcore_event_adapter.adapt_event``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import Protocol, RawCapture
from src.models.signal import SignalMetrics
from src.transmit.meshcore_tx_client import (
    SendResult,
    read_device_info,
    read_radio_status,
    send_companion_advert,
    send_mc_channel_message,
    send_mc_direct_message,
    send_set_companion_name,
    send_set_radio_params,
)

logger = logging.getLogger(__name__)

_HEALTH_CHECK_INTERVAL_SECONDS = 180
_HEALTH_CHECK_RETRY_DELAY_SECONDS = 20
_HEALTH_CHECK_MAX_FAILURES = 2
_RECENT_EVENT_HEALTHY_WINDOW_SECONDS = 120
_MESHCORE_COMMAND_TIMEOUT_SECONDS = 12.0
_HEALTH_CHECK_TIMEOUT_SECONDS = 15.0
_RECONNECT_BASE_DELAY_SECONDS = 5
_RECONNECT_MAX_DELAY_SECONDS = 60
# set_radio_params() applies over an exclusive, temporary connection
# instead of the source's own shared/live one (see its docstring) --
# real-hardware testing (matching upstream KMX415/meshpoint's own
# a49ef60, "Live shared-handle set_radio failed for USA/Canada with
# no_event_received while cold exclusive access worked") found the
# shared-handle approach this used to be (send over self._meshcore,
# verify via the source's own reconnect) could still silently fail on a
# cross-band change even with a verify-and-retry-once path -- a
# genuinely separate, exclusive connection for the whole
# set+reboot+verify sequence is what's actually reliable. A longer
# handshake timeout than steady-state commands get (_MESHCORE_COMMAND_
# TIMEOUT_SECONDS): this connection is always cold, right after a DTR
# reset, so it needs the same slack a fresh boot-up handshake needs.
_RADIO_EXCLUSIVE_HANDSHAKE_TIMEOUT_SECONDS = 15.0
# How long to wait after sending reboot() before attempting the
# post-apply reconnect -- matches the real observed ESP32-S3 boot time
# this whole recovery path was built around.
_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS = 8.0
# Settle time after a DTR pulse, before the next connect attempt --
# same value the main reconnect loop already uses for the same reason.
_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS = 2.0
# Tolerance for comparing a requested preset against what the radio
# reports back post-reconnect -- SELF_INFO values round-trip through the
# firmware's own fixed-point representation, so an exact `==` would
# false-negative on harmless rounding. Frequency tighter than bandwidth
# since a frequency this far off would be a genuinely different channel,
# not rounding noise.
_RADIO_FREQ_MATCH_TOLERANCE_MHZ = 0.002
_RADIO_BW_MATCH_TOLERANCE_KHZ = 0.1


class MeshcoreUsbCaptureSource(CaptureSource):
    """Receives packets from a MeshCore device connected via USB serial."""

    def __init__(
        self,
        serial_port: Optional[str] = None,
        baud_rate: int = 115200,
        auto_detect: bool = True,
        label: str = "",
    ):
        self._configured_port = serial_port
        self._baud_rate = baud_rate
        self._auto_detect = auto_detect
        self._label = label
        self._meshcore = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._running = False
        self._connected = False
        self._subscriptions: list = []
        self._resolved_port: Optional[str] = None
        self._health_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        # Guards against two reconnect attempts running concurrently --
        # e.g. the health-check loop's own inline _reconnect() call
        # racing with a dashboard-command timeout's _trigger_reconnect()
        # firing moments later. Both would otherwise call _disconnect()/
        # _connect() on the same serial port at once, risking an
        # orphaned MeshCore object and redundant DTR reset pulses on
        # what may be an already-marginal DTR line. See _reconnect().
        self._reconnect_in_progress: bool = False
        self._last_rf_signal: Optional[SignalMetrics] = None
        # Raw advert frames (RX log) by full public key, kept ~2 s so the
        # decoded ADVERTISEMENT event can take the RSSI/SNR/hops of *its own*
        # frame instead of whatever RF frame came last (upstream fc15bc36).
        self._recent_raw_adverts: dict = {}
        # MeshCore send feedback (src/transmit/meshcore_repeats.py), shared
        # by all companions; set by the server.
        self._send_feedback = None
        self._last_event_at: float = 0.0
        self._on_connected_callback = None
        # Cached DEVICE_INFO round-trip result -- firmware doesn't change
        # at runtime, mirrors MeshCoreTxClient's identical per-connection
        # cache (see get_device_info() below).
        self._device_info_cache = None

    @property
    def name(self) -> str:
        return f"meshcore_usb_{self._label}" if self._label else "meshcore_usb"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        # Mirrors serial_source.py's identical public accessor -- without
        # this, config_routes.py's getattr(src, "connected", False) found
        # no such attribute (only the private self._connected existed) and
        # silently defaulted to False for every companion, regardless of
        # its real live state.
        return self._connected

    async def start(self) -> None:
        port = await self._resolve_port()
        if port is None:
            # Expected when meshcore_usb is enabled in config but no
            # companion is currently plugged in. Not an error condition,
            # just a state. Plug in a device and restart the service to
            # activate this source.
            logger.info(
                "No MeshCore USB device detected -- source idle "
                "(plug in a companion and restart to activate)"
            )
            return

        self._resolved_port = port
        self._running = True
        await self._connect(port)

        if self._connected:
            self._health_task = asyncio.create_task(
                self._health_check_loop(), name="meshcore-health"
            )
            return

        # Initial handshake failed. The device may still be coming up
        # (ESP32-S3 needs ~6-10s to be USB-ready after a reboot, longer
        # than the meshcore library's 5s handshake timeout). Schedule a
        # background reconnect with exponential backoff so the source
        # recovers on its own without blocking service startup.
        logger.info(
            "MeshCore USB initial connect failed -- scheduling background "
            "reconnect"
        )
        self._reconnect_task = asyncio.create_task(
            self._reconnect_until_connected(),
            name="meshcore-initial-reconnect",
        )

    async def stop(self) -> None:
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
        await self._disconnect()
        logger.info("MeshCore USB source stopped")

    async def _reconnect_until_connected(self) -> None:
        """Background reconnect after a failed initial handshake.

        Promotes itself to the standard health-check loop once connected
        so subsequent disconnects are handled normally.
        """
        try:
            await self._reconnect()
            if self._connected:
                self._health_task = asyncio.create_task(
                    self._health_check_loop(), name="meshcore-health"
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MeshCore USB initial reconnect loop error")

    async def packets(self) -> AsyncIterator[RawCapture]:
        if not self._running:
            return
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                etype = getattr(getattr(event, "type", None), "value", None)
                if self._send_feedback is not None and isinstance(getattr(event, "payload", None), dict):
                    try:
                        if etype == "rx_log_data":
                            await self._send_feedback.observe(event.payload)
                        elif etype == "acknowledgement":
                            await self._send_feedback.acknowledge(event.payload)
                    except Exception:
                        logger.exception("MeshCore send feedback observation failed")
                if etype == "acknowledgement":
                    continue  # a delivery receipt, not a packet
                raw = self._wrap_event(event)
                if raw is not None:
                    yield raw
            except asyncio.TimeoutError:
                continue

    async def _connect(self, port: str) -> None:
        try:
            from meshcore import MeshCore, EventType

            self._meshcore = await MeshCore.create_serial(
                port,
                self._baud_rate,
                default_timeout=_MESHCORE_COMMAND_TIMEOUT_SECONDS,
            )
            if self._meshcore is None:
                logger.error(
                    "MeshCore companion handshake failed on %s. "
                    "Verify the device is running Companion USB firmware "
                    "and that no other process is holding the port.",
                    port,
                )
                self._connected = False
                return

            self._connected = True

            for event_type in (
                EventType.RX_LOG_DATA,
                EventType.ACK,
                EventType.RAW_DATA,
                EventType.CONTACT_MSG_RECV,
                EventType.CHANNEL_MSG_RECV,
                EventType.ADVERTISEMENT,                
                EventType.NEW_CONTACT,
                EventType.DISCONNECTED,
            ):
                sub = self._meshcore.subscribe(event_type, self._on_event)
                self._subscriptions.append(sub)

            await self._meshcore.start_auto_message_fetching()
            logger.info(
                "MeshCore USB source started on %s @ %d baud",
                port, self._baud_rate,
            )
            if self._on_connected_callback:
                asyncio.create_task(
                    self._on_connected_callback(),
                    name="meshcore-on-connected",
                )
        except Exception:
            logger.exception(
                "Failed to start MeshCore USB source on %s", port
            )
            self._connected = False

    async def _disconnect(self) -> None:
        self._connected = False
        self._recent_raw_adverts.clear()
        if self._meshcore:
            for sub in self._subscriptions:
                self._meshcore.unsubscribe(sub)
            self._subscriptions.clear()
            try:
                await self._meshcore.stop_auto_message_fetching()
            except Exception:
                pass
            try:
                await self._meshcore.disconnect()
            except Exception:
                pass
            self._meshcore = None

    async def _reconnect(self) -> None:
        """Disconnect, wait with backoff, and reconnect.

        On retries (not the first attempt) we pulse DTR low briefly
        before opening the port. On most ESP32 dev boards (Heltec V3
        included) DTR is wired to the chip's RESET pin, so a short
        pulse triggers a hardware reset of the companion. This
        recovers from a stuck USB-CDC state that otherwise requires
        a manual unplug/replug. On boards where DTR is not wired
        to RESET the pulse is a harmless no-op.

        Guarded against re-entrancy (self._reconnect_in_progress): two
        different triggers can both decide a reconnect is needed within
        the same window -- the health-check loop's own inline call and
        a dashboard-command timeout's _trigger_reconnect(), for
        instance. Without this guard both would call _disconnect()/
        _connect() on the same port concurrently, risking an orphaned
        MeshCore object from whichever attempt loses the race, and
        doubling up DTR reset pulses on what confirmed live testing
        showed can be a marginal line on some ports (only MeshCore's
        capture source touches DTR at all -- the identical port/cable/
        board worked fine under both Meshtastic and DAPNET firmware,
        neither of which ever pulses it).
        """
        if self._reconnect_in_progress:
            logger.debug(
                "MeshCore USB reconnect already in progress, skipping duplicate trigger"
            )
            return
        self._reconnect_in_progress = True
        try:
            await self._disconnect()
            delay = _RECONNECT_BASE_DELAY_SECONDS
            attempt = 0

            while self._running:
                logger.info(
                    "MeshCore USB reconnecting in %ds...", delay
                )
                await asyncio.sleep(delay)
                if not self._running:
                    return

                attempt += 1
                # Confirmed live on a TTGO LoRa32: two plain retries (each
                # eating a full _MESHCORE_COMMAND_TIMEOUT_SECONDS=12s
                # handshake timeout) both failed with "No response from
                # meshcore node" -- recovery only happened once the pulse
                # fired on the 2nd retry (the old attempt >= 2 threshold).
                # That's strong evidence some boards' USB-CDC stack comes
                # up wedged and needs an actual reset, not just more
                # patience -- pulsing starting on the 1st retry instead
                # skips one whole wasted 12s timeout (~41s total recovery
                # down to ~21s). Still not on attempt 0 (the very first
                # try): a board that's simply mid-boot and would have
                # answered fine on its own shouldn't eat a reset (and the
                # ~15-20s of RX downtime a reset costs, see
                # _health_check_loop's docstring) before even one plain
                # attempt has been given a chance.
                if attempt >= 1 and self._resolved_port:
                    from src.capture.meshcore_dtr import pulse_dtr_reset

                    await asyncio.to_thread(
                        pulse_dtr_reset, self._resolved_port, self._baud_rate,
                    )
                    # Give the chip a moment to come back from reset.
                    await asyncio.sleep(2.0)

                await self._connect(self._resolved_port)
                if self._connected:
                    logger.info("MeshCore USB reconnected successfully")
                    return

                delay = min(delay * 2, _RECONNECT_MAX_DELAY_SECONDS)
        finally:
            self._reconnect_in_progress = False

    async def _health_check_loop(self) -> None:
        """Periodically verify the serial companion is still responding.

        Two defenses against false positives that used to trigger
        spurious reconnects (which themselves cost ~15-20s of RX
        downtime because they DTR-reboot the companion):

        1. Skip the active probe entirely if any event arrived from
           the device within the last RECENT_EVENT_HEALTHY_WINDOW
           seconds. Inbound events ARE proof of life: no point asking.
        2. Tolerate transient probe failures. A single missed response
           can happen when the device is busy processing an inbound
           RF frame or fetching queued messages. We retry once after
           a short delay and only reconnect if the second probe also
           fails.
        """
        consecutive_failures = 0
        try:
            while self._running and self._connected:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL_SECONDS)
                if not self._running:
                    return

                if self._has_recent_event_activity():
                    consecutive_failures = 0
                    continue

                if await self._check_health():
                    consecutive_failures = 0
                    continue

                consecutive_failures += 1
                logger.info(
                    "MeshCore USB health probe missed (%d/%d)",
                    consecutive_failures, _HEALTH_CHECK_MAX_FAILURES,
                )

                if consecutive_failures < _HEALTH_CHECK_MAX_FAILURES:
                    await asyncio.sleep(_HEALTH_CHECK_RETRY_DELAY_SECONDS)
                    continue

                logger.warning(
                    "MeshCore USB health check failed %d times -- "
                    "reconnecting",
                    _HEALTH_CHECK_MAX_FAILURES,
                )
                consecutive_failures = 0
                await self._reconnect()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MeshCore USB health check loop error")

    def _has_recent_event_activity(self) -> bool:
        if self._last_event_at == 0.0:
            return False
        now = asyncio.get_event_loop().time()
        return (now - self._last_event_at) < _RECENT_EVENT_HEALTHY_WINDOW_SECONDS

    async def _check_health(self) -> bool:
        """Send a device query and verify we get a response."""
        if not self._meshcore:
            return False
        try:
            from meshcore import EventType

            result = await asyncio.wait_for(
                self._meshcore.commands.send_device_query(),
                timeout=_HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            return result.type != EventType.ERROR
        except Exception:
            return False

    async def _on_event(self, event) -> None:
        if not self._running:
            return
        # Any event from the device is proof the connection is alive.
        # The health check loop uses this to skip its active probe.
        self._last_event_at = asyncio.get_event_loop().time()
        try:
            # Receiver settings as they were when the event came in, not
            # when the queued event is later decoded or displayed.
            event._meshpoint_receiver = _receiver_settings(
                getattr(self._meshcore, "self_info", {}) or {}
            )
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("MeshCore USB queue full, dropping event")

    def _wrap_event(self, event) -> Optional[RawCapture]:
        """Serialise a meshcore Event into a RawCapture envelope."""
        payload_dict = (
            event.payload if isinstance(event.payload, dict) else {}
        )
        etype = (
            event.type.value
            if hasattr(event.type, "value")
            else str(event.type)
        )

        radio_info = self._meshcore.self_info if self._meshcore else None
        # Snapshot taken in _on_event; a None snapshot (settings unknown then)
        # must not pick up settings that only arrived later.
        receiver = (event._meshpoint_receiver if hasattr(event, "_meshpoint_receiver")
                    else _receiver_settings(radio_info or {}))
        signal = _extract_signal(payload_dict, radio_info)
        now = time.monotonic()
        self._recent_raw_adverts = {
            key: entries for key, entries in self._recent_raw_adverts.items()
            if now - entries[-1][0] < 2
        }

        if etype == "rx_log_data":
            if signal.rssi > -119.0:
                self._last_rf_signal = signal
            advert = _raw_advertisement(payload_dict)
            if advert is not None:
                entries = self._recent_raw_adverts.setdefault(advert["public_key"], [])
                entries.append((now, advert, signal, receiver))
                # Two is enough to call it ambiguous (heard via two paths):
                # never guess which copy the decoded event came from.
                self._recent_raw_adverts[advert["public_key"]] = entries[-2:]
                if len(self._recent_raw_adverts) > 128:
                    self._recent_raw_adverts.pop(next(iter(self._recent_raw_adverts)))
            return None

        if etype == "advertisement":
            matches = [
                item for item in self._recent_raw_adverts.pop(payload_dict.get("public_key"), [])
                if now - item[0] < 2
            ]
            if len(matches) == 1:
                _, advert, signal, receiver = matches[0]
                payload_dict = {**payload_dict, **advert}

        safe_payload = _make_json_safe(payload_dict)

        if etype in ("channel_message", "contact_message", "advertisement"):
            if self._last_rf_signal and signal.rssi <= -119.0:
                safe_payload["RSSI"] = self._last_rf_signal.rssi
                safe_payload["SNR"] = self._last_rf_signal.snr
                signal = self._last_rf_signal
            self._last_rf_signal = None

        if receiver:
            signal = replace(
                signal,
                frequency_mhz=receiver["frequency_mhz"],
                spreading_factor=receiver["spreading_factor"],
                bandwidth_khz=receiver["bandwidth_khz"],
                coding_rate=receiver["coding_rate"],
            )
        envelope = {
            "receiver_settings": receiver,
            "event_type": etype,
            "payload": safe_payload,
        }
        return RawCapture(
            payload=json.dumps(envelope).encode("utf-8"),
            signal=signal,
            capture_source=self.name,
            protocol_hint=Protocol.MESHCORE,
        )

    def set_connected_callback(self, callback) -> None:
        """Register a coroutine called after every successful connection."""
        self._on_connected_callback = callback

    async def get_radio_info(self):
        """This companion's own radio parameters (frequency/bandwidth/SF/
        TX power/name/public key), read from its own connection -- unlike
        MeshCoreTxClient (wired to only one "primary" companion for
        sending), every configured companion has one of these capture
        source instances, so this is what makes per-companion status
        possible (see config_routes.py's meshcore_companions list)."""
        if not self._meshcore:
            return None
        return await read_radio_status(self._meshcore)

    async def get_device_info(self):
        """This companion's own firmware version/model/build date,
        cached per connection since firmware doesn't change at runtime
        (same reasoning as MeshCoreTxClient's identical cache)."""
        if self._device_info_cache is not None:
            return self._device_info_cache
        if not self._meshcore:
            return None
        info = await read_device_info(self._meshcore)
        if info is not None:
            self._device_info_cache = info
        return info

    def _trigger_reconnect(self, reason: str) -> None:
        """Mark this companion disconnected and kick off recovery NOW,
        via the same backoff+DTR-reset-pulse machinery that already
        handles unexpected drops (_reconnect()) -- instead of leaving a
        dead connection sitting there as "connected" until the
        health-check loop eventually notices (which can take minutes,
        and can be masked indefinitely by ongoing passive RX activity,
        see _has_recent_event_activity()). Confirmed live: a companion
        whose command channel silently died kept reporting connected
        while every subsequent command (rename, radio change, health
        probes) timed out, with nothing recovering it on its own.

        No-ops if a reconnect is already running (_reconnect_in_progress)
        -- e.g. the health-check loop's own inline reconnect already
        kicked in moments earlier. Avoids cancelling _health_task and
        spawning a second concurrent attempt for no benefit, since
        _reconnect() itself would just no-op the duplicate anyway.
        """
        if self._reconnect_in_progress:
            logger.debug(
                "MeshCore companion %r: %s -- reconnect already in progress, skipping",
                self.name, reason,
            )
            return
        logger.warning(
            "MeshCore companion %r: %s -- reconnecting now", self.name, reason,
        )
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None
        self._connected = False
        self._reconnect_task = asyncio.create_task(
            self._reconnect_until_connected(),
            name="meshcore-command-timeout-reconnect",
        )

    async def set_companion_name(self, name: str) -> SendResult:
        """Rename THIS companion via its own connection.

        Unlike MeshCoreTxClient.set_companion_name() (only ever the one
        "primary" companion), this lets every configured companion be
        renamed independently -- each already holds its own connection.
        """
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        result = await send_set_companion_name(self._meshcore, name)
        if result.timed_out:
            self._trigger_reconnect("set_name timed out")
            return result
        await self.restart_auto_fetching()
        if result.success:
            logger.info("MeshCore companion %r renamed to %r", self.name, (name or "").strip())
        return result

    async def set_radio_params(self, freq: float, bw: float, sf: int, cr: int) -> SendResult:
        """Set THIS companion's radio frequency/bandwidth/SF/CR and reboot
        it to apply, over a temporary EXCLUSIVE connection -- not the
        source's own shared/live one.

        This used to reuse the live connection (send over self._meshcore,
        verify-and-retry-once over the source's own reconnect on a
        timeout). That worked for same-band changes but real-hardware
        testing found it could still fail with `no_event_received` on a
        cross-band change (e.g. EU -> USA/Canada) even with that
        retry -- matching upstream KMX415/meshpoint's own independently-
        confirmed finding on the same bug ("Live shared-handle set_radio
        failed for USA/Canada... cold exclusive access worked on the
        test Pi"). A genuinely separate connection for the whole
        set+reboot+verify sequence, instead of contending with whatever
        else the shared connection is doing (auto-fetch polling, the
        health-check loop), is what's actually reliable.

        Trade-off worth knowing: unlike the old shared-handle path (which
        returned near-instantly on the common, same-band case), this
        ALWAYS pays the full detach -> cold-connect -> set -> reboot-wait
        -> cold-reconnect -> verify sequence, typically ~15-20s, since
        there's no way to know in advance whether a given change will
        hit the ambiguous no-response case or not. The dashboard's own
        save button already shows a pending state and its own copy
        already says "this can take up to a minute" (meshcore_card.js),
        so this fits the existing UI contract rather than needing any
        frontend change.
        """
        if not self.connected:
            return SendResult(success=False, error="Not connected")

        port = await self._detach_for_exclusive_radio_apply()
        if not port:
            await self._reattach_after_exclusive_radio_apply()
            return SendResult(success=False, error="MeshCore serial port not resolved")

        try:
            return await self._apply_radio_params_exclusive(port, freq, bw, sf, cr)
        finally:
            await self._reattach_after_exclusive_radio_apply()

    async def _detach_for_exclusive_radio_apply(self) -> Optional[str]:
        """Hand the serial port over from this source's own live
        connection to a cold, exclusive one for the duration of a
        set_radio_params() call -- see its docstring for why. Cancels
        the health-check and reconnect tasks (if either happens to be
        running) and closes self._meshcore, exactly the same shutdown
        _reconnect() already does before reopening, just without the
        backoff loop around it.
        """
        port = self._resolved_port
        if not port:
            return None
        logger.info(
            "MeshCore companion %r: detaching %s for exclusive radio config",
            self.name, port,
        )
        for attr in ("_health_task", "_reconnect_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, attr, None)
        self._reconnect_in_progress = False
        await self._disconnect()
        return port

    async def _reattach_after_exclusive_radio_apply(self) -> None:
        """Hand the port back to the source's own reconnect machinery --
        same fallback `start()` already uses for a failed initial
        connect, so a companion that came back up mid-config settles
        into the normal health-check loop exactly the same way."""
        if not self._running:
            return
        logger.info(
            "MeshCore companion %r: reattaching after exclusive radio config",
            self.name,
        )
        self._reconnect_task = asyncio.create_task(
            self._reconnect_until_connected(),
            name="meshcore-post-radio-config-reconnect",
        )

    async def _apply_radio_params_exclusive(
        self, port: str, freq: float, bw: float, sf: int, cr: int,
    ) -> SendResult:
        """The actual cold set+reboot+verify sequence, on its own
        exclusive connection to `port`. Caller must have already
        detached the source's own connection first (see
        set_radio_params()) and is responsible for reattaching after.
        """
        try:
            from meshcore import MeshCore
        except Exception:
            return SendResult(success=False, error="meshcore library unavailable")

        from src.capture.meshcore_dtr import pulse_dtr_reset

        await asyncio.to_thread(pulse_dtr_reset, port, self._baud_rate)
        await asyncio.sleep(_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS)

        mc = await MeshCore.create_serial(
            port, self._baud_rate,
            default_timeout=_RADIO_EXCLUSIVE_HANDSHAKE_TIMEOUT_SECONDS,
        )
        if mc is None:
            return SendResult(
                success=False,
                error="MeshCore handshake failed during exclusive radio set",
            )

        try:
            result = await send_set_radio_params(mc, freq, bw, sf, cr)
        finally:
            try:
                await mc.disconnect()
            except Exception:
                pass

        if result.success:
            logger.info(
                "MeshCore companion %r: exclusive set_radio acked "
                "(%.3f MHz / BW%.1f / SF%d / CR%d), verifying after reboot",
                self.name, freq, bw, sf, cr,
            )
        elif not result.timed_out:
            # A clean rejection (e.g. out-of-range params) -- nothing
            # rebooted, nothing to verify.
            return result

        await asyncio.sleep(_RADIO_EXCLUSIVE_REBOOT_SETTLE_SECONDS)
        await asyncio.to_thread(pulse_dtr_reset, port, self._baud_rate)
        await asyncio.sleep(_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS)

        mc2 = await MeshCore.create_serial(
            port, self._baud_rate,
            default_timeout=_RADIO_EXCLUSIVE_HANDSHAKE_TIMEOUT_SECONDS,
        )
        if mc2 is None:
            return SendResult(
                success=False,
                error="set_radio sent but the companion did not come back for verify",
                timed_out=True,
            )

        try:
            status = await read_radio_status(mc2)
        finally:
            try:
                await mc2.disconnect()
            except Exception:
                pass

        if status is None:
            return SendResult(
                success=False,
                error=(
                    "set_radio sent; companion reconnected but its radio "
                    "info is unavailable; check the preset and retry"
                ),
                timed_out=True,
            )
        if (
            abs(status.frequency_mhz - freq) <= _RADIO_FREQ_MATCH_TOLERANCE_MHZ
            and abs(status.bandwidth_khz - bw) <= _RADIO_BW_MATCH_TOLERANCE_KHZ
            and status.spreading_factor == sf
            and status.coding_rate == cr
        ):
            logger.info(
                "MeshCore companion %r: exclusive set_radio verified, radio "
                "matches %.3f MHz / BW%.1f / SF%d / CR%d",
                self.name, freq, bw, sf, cr,
            )
            return SendResult(success=True)
        return SendResult(
            success=False,
            error=(
                "set_radio sent; companion's radio is "
                f"{status.frequency_mhz:.3f} MHz / BW{status.bandwidth_khz:.1f} "
                f"/ SF{status.spreading_factor} / CR{status.coding_rate} "
                f"(wanted {freq:.3f} / BW{bw:.1f} / SF{sf} / CR{cr})"
            ),
            timed_out=True,
        )

    async def send_advert(self, flood: bool = False) -> SendResult:
        """Broadcast a node advertisement from THIS companion."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        result = await send_companion_advert(self._meshcore, flood=flood)
        if result.timed_out:
            self._trigger_reconnect("advert send timed out")
            return result
        await self.restart_auto_fetching()
        return result

    def set_send_feedback(self, feedback) -> None:
        """Share the MeshCore send-feedback tracker (repeats heard, DM ACKs)."""
        self._send_feedback = feedback

    async def send_direct_message(self, destination, text: str, packet_id: str = "") -> SendResult:
        """Send a direct message to a contact via THIS companion's own
        connection -- lets a reply go out through whichever companion
        actually has RF reach to the recipient, instead of always the
        one "primary" companion TxService is otherwise bound to."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        result = await send_mc_direct_message(
            self._meshcore, destination, text, self._send_feedback, packet_id,
        )
        if result.timed_out:
            self._trigger_reconnect("direct message send timed out")
            return result
        await self.restart_auto_fetching()
        return result

    async def send_channel_message(self, channel: int, text: str, packet_id: str = "") -> SendResult:
        """Broadcast a message on a MeshCore channel via THIS companion."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        result = await send_mc_channel_message(
            self._meshcore, channel, text, self._send_feedback, packet_id,
        )
        if result.timed_out:
            self._trigger_reconnect("channel message send timed out")
            return result
        await self.restart_auto_fetching()
        return result

    async def restart_auto_fetching(self) -> None:
        """Re-enable auto message fetching after TX operations."""
        if self._meshcore and self._connected:
            try:
                await self._meshcore.start_auto_message_fetching()
                logger.info("MeshCore auto message fetching restarted")
            except Exception:
                logger.debug("Failed to restart auto fetching", exc_info=True)

    async def _resolve_port(self) -> Optional[str]:
        if self._configured_port:
            return self._configured_port
        if not self._auto_detect:
            return None
        from src.capture.meshcore_usb_detect import detect_meshcore_port
        return await detect_meshcore_port(baud=self._baud_rate)


def _extract_signal(
    payload: dict, radio_info: Optional[dict] = None
) -> SignalMetrics:
    """Build signal metrics for a MeshCore event.

    RSSI/SNR come per-packet from the event payload. Frequency/bandwidth/SF
    are not part of the event stream (the companion firmware doesn't report
    them per-packet) but are static for the session, cached on the meshcore
    client's self_info from the connect-time handshake -- the same values
    the Configuration > MeshCore page displays.
    """
    rssi = payload.get("rssi", payload.get("RSSI"))
    snr = payload.get("snr", payload.get("SNR"))
    frequency_mhz = float(radio_info.get("radio_freq", 0.0)) if radio_info else 0.0
    bandwidth_khz = float(radio_info.get("radio_bw", 0.0)) if radio_info else 0.0
    spreading_factor = int(radio_info.get("radio_sf", 0)) if radio_info else 0
    if rssi is None and snr is None:
        return SignalMetrics(
            rssi=-120.0,
            snr=0.0,
            frequency_mhz=frequency_mhz,
            spreading_factor=spreading_factor,
            bandwidth_khz=bandwidth_khz,
            coding_rate="N/A",
        )
    return SignalMetrics(
        rssi=float(rssi) if rssi is not None else -120.0,
        snr=float(snr) if snr is not None else 0.0,
        frequency_mhz=frequency_mhz,
        spreading_factor=spreading_factor,
        bandwidth_khz=bandwidth_khz,
        coding_rate="N/A",
    )


def _make_json_safe(payload: dict) -> dict:
    """Convert bytes values to hex strings for JSON serialisation."""
    safe: dict = {}
    for key, val in payload.items():
        if isinstance(val, bytes):
            safe[key] = val.hex()
        elif isinstance(val, dict):
            safe[key] = _make_json_safe(val)
        else:
            safe[key] = val
    return safe


def _receiver_settings(info: dict) -> Optional[dict]:
    """This companion's radio settings from its cached SELF_INFO.

    Configuration, not a per-packet measurement: the companion doesn't
    report modem parameters per packet. None when anything is missing or
    out of range (upstream fc15bc36).
    """
    try:
        freq, bw = float(info["radio_freq"]), float(info["radio_bw"])
        sf, cr = int(info["radio_sf"]), int(info["radio_cr"])
        if not (0 < freq < 10000 and 0 < bw <= 2000 and 5 <= sf <= 12 and 5 <= cr <= 8):
            return None
        return {"frequency_mhz": freq, "bandwidth_khz": bw,
                "spreading_factor": sf, "coding_rate": f"4/{cr}",
                "source": "receiver_self_info_at_capture"}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _raw_advertisement(payload: dict) -> Optional[dict]:
    """RSSI/SNR/hops of a raw ADVERT frame from the RX log, keyed by its own
    public key (checked against the meshcore library's ``adv_key``), or None
    for anything that isn't a complete public advert (upstream fc15bc36)."""
    try:
        raw = bytes.fromhex(payload.get("payload", ""))
        if len(raw) < 2 or len(raw) > 512:
            return None
        header = raw[0]
        if (header >> 2) & 15 != 4 or header >> 6 != 0:  # ADVERT, version 0
            return None
        route = header & 3
        offset = 5 if route in (0, 3) else 1  # transport codes on 0 and 3
        path_byte = raw[offset]
        count, size = path_byte & 63, (path_byte >> 6) + 1
        body = raw[offset + 1 + count * size:]
        if len(body) < 101:  # public key, timestamp, signature, flags
            return None
        key = body[:32].hex()
        if payload.get("adv_key") != key:
            return None
        result = {"public_key": key, "rf_metadata_source": "raw_advertisement",
                  "rssi": payload.get("rssi"), "snr": payload.get("snr")}
        # A flood path lists the repeaters it passed; a direct route's path is
        # a routing instruction, not a received hop count.
        if route in (0, 1):
            result["path_len"] = count
        for field in ("adv_name", "adv_lat", "adv_lon"):
            if payload.get(field) is not None:
                result[field] = payload[field]
        return result
    except (TypeError, ValueError, IndexError):
        return None
