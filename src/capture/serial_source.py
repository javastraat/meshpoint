from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from src.capture.base import CaptureSource
from src.models.packet import RawCapture
from src.models.signal import SignalMetrics
from src.radio.channel_frequency import resolve_frequency_mhz
from src.radio.presets import get_preset

logger = logging.getLogger(__name__)

# A busy/wrong port at startup used to raise straight out of start(),
# permanently -- CaptureCoordinator.start() (see capture_coordinator.py)
# now stops that from aborting every OTHER source too, but this source
# itself still needed its own way to actually recover once the port
# frees up or the real issue gets fixed, instead of sitting dead until
# a manual service restart. Same base/max backoff values as
# meshcore_usb_source.py's own proven reconnect loop, for consistency --
# not the same DTR-reset-pulse mechanism, though: that's a documented
# ESP32-S3-companion-specific USB-CDC wedge recovery, confirmed live on
# that hardware, not something to blindly assume applies to a Meshtastic
# USB stick's own separate serial stack.
_RECONNECT_BASE_DELAY_SECONDS = 5
_RECONNECT_MAX_DELAY_SECONDS = 60
# After a config write the node reboots; the first retry waits longer so
# it isn't spent on a board that is still booting (upstream 459c4d7c).
_REBOOT_INITIAL_DELAY_SECONDS = 15


class SerialCaptureSource(CaptureSource):
    """Captures packets from a Meshtastic radio connected via USB serial.

    Uses the meshtastic-python pub/sub API to receive decoded packets.
    Packets arrive already decoded, so they are re-serialized as raw
    capture events for the pipeline to process uniformly.
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = 115200,
        label: str = "",
        long_name: Optional[str] = None,
        short_name: Optional[str] = None,
    ):
        self._port = port
        self._baud = baud
        self._label = label
        self._desired_long_name = long_name
        self._desired_short_name = short_name
        self._interface = None
        self._running = False
        self._connected = False
        self._radio_info: dict = {}
        self._queue: asyncio.Queue[RawCapture] = asyncio.Queue(maxsize=500)
        self._reconnect_task: Optional[asyncio.Task] = None
        # Live-drop recovery (upstream 93866842): meshtastic-python publishes
        # "meshtastic.connection.lost" from its reader thread, and a LoRa/
        # Bluetooth config write reboots the node. Either way the old
        # interface is dead, but _connected stayed True and the reconnect
        # loop (armed only when the first connect failed) never ran:
        # green on the dashboard, no packets until a service restart.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lost_subscribed = False
        # Dashboard status while recovering: "rebooting" (after a config
        # write) or "reconnecting" (link lost / first connect failed), and
        # when the next attempt is due (time.monotonic()).
        self._link_phase: Optional[str] = None
        self._retry_at: Optional[float] = None

    @property
    def name(self) -> str:
        return f"serial_{self._label}" if self._label else "serial"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    def link_status(self) -> dict:
        """Recovery state for the dashboard: reconnecting, link_phase, retry_in_s."""
        task = self._reconnect_task
        busy = task is not None and not task.done() and not self._connected
        retry_in = 0
        if busy and self._retry_at is not None:
            retry_in = max(0, int(round(self._retry_at - time.monotonic())))
        return {
            "reconnecting": busy,
            "link_phase": (self._link_phase or "reconnecting") if busy else None,
            "retry_in_s": retry_in,
        }

    def get_radio_info(self) -> dict:
        """Region/channel/name from the connect-time handshake.

        Empty dict before the first successful connect. Same role as
        MeshCore's ``self_info`` readout, exposed for the topbar chip
        and for stamping real signal metadata instead of a hardcoded
        placeholder.
        """
        return dict(self._radio_info)

    def send_nodeinfo(self) -> bool:
        """Broadcast this stick's own NodeInfo on its band.

        The stick is a full Meshtastic node with its own identity (not
        the Meshpoint's node_id) -- this asks it to introduce itself,
        which is what the physical advert button wants: "this box is
        here" on the stick's band. Sync and cheap: meshtastic-python
        queues the frame to the radio's stream.

        long_name/short_name come from self._radio_info (this source's
        own cache, kept current by set_owner() immediately after a
        successful rename) rather than re-querying
        iface.getMyNodeInfo() -- so an advert sent right after a rename
        announces the NEW name, not whatever the library's own node
        cache happens to still hold.
        """
        iface = self._interface
        if iface is None or not self._running:
            return False
        try:
            from meshtastic.protobuf import mesh_pb2, portnums_pb2

            my = iface.getMyNodeInfo() or {}
            user_info = my.get("user") or {}
            node_id = user_info.get("id") or ""
            long_name = self._radio_info.get("long_name") or user_info.get("longName") or ""
            short_name = self._radio_info.get("short_name") or user_info.get("shortName") or ""
            user = mesh_pb2.User()
            user.id = node_id
            user.long_name = long_name
            user.short_name = short_name
            iface.sendData(
                user.SerializeToString(),
                portNum=portnums_pb2.PortNum.NODEINFO_APP,
            )
            logger.info(
                "%s: NodeInfo broadcast sent (%s)",
                self.name, node_id or "unknown id",
            )
            return True
        except Exception:
            logger.exception("%s: NodeInfo broadcast failed", self.name)
            return False

    def send_text(
        self,
        text: str,
        destination: int | str,
        channel_index: int = 0,
        want_ack: bool = False,
    ) -> dict:
        """Send a text message via THIS stick's own connection.

        Lets a reply go out through whichever Meshtastic USB stick
        actually has RF reach to the recipient, instead of always the
        onboard concentrator -- a contact heard only via a 433 MHz USB
        stick physically cannot receive a reply sent out on 868 MHz.
        meshtastic-python's own sendText()/sendData() queue the packet
        and return immediately (confirmed this session, same call
        already used non-blocking by send_nodeinfo()/set_owner() above)
        -- no executor wrapper needed.

        Returns a plain dict, not TxService's SendResult dataclass:
        that type lives a layer above capture sources, which shouldn't
        depend on it.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected", "packet_id": ""}
        try:
            sent = iface.sendText(
                text,
                destinationId=destination,
                wantAck=want_ack,
                channelIndex=channel_index,
            )
            packet_id = f"{sent.id:08x}" if sent is not None and hasattr(sent, "id") else ""
            logger.info(
                "%s: text message sent (dest=%s, id=%s)",
                self.name, destination, packet_id or "unknown",
            )
            return {"success": True, "error": "", "packet_id": packet_id}
        except Exception as exc:
            logger.exception("%s: send_text failed", self.name)
            return {"success": False, "error": str(exc), "packet_id": ""}

    def set_owner(self, long_name: Optional[str], short_name: Optional[str]) -> dict:
        """Rename this stick's own Meshtastic identity (long/short name).

        Uses meshtastic-python's Node.setOwner() -- an ADMIN_APP
        AdminMessage, the same TX mechanism send_nodeinfo() rides on.
        Pass None for a name to leave it unchanged (matches setOwner()'s
        own None-means-skip convention).

        CAUTION: meshtastic-python's setOwner() calls its own
        our_exit() helper (print + sys.exit(1)) on an empty or
        whitespace-only name -- a CLI-oriented escape hatch that would
        kill this entire long-running server process if ever reached.
        Both names are therefore validated and stripped BEFORE the
        call (same 36/4-char ceilings as the dashboard's own concentrator
        Identity route, config_routes.py's update_identity), and
        SystemExit is caught defensively in case some other internal
        path still raises it.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected"}

        long_clean = (long_name or "").strip() if long_name is not None else None
        short_clean = (short_name or "").strip() if short_name is not None else None

        if long_clean is not None:
            if not long_clean:
                return {"success": False, "error": "Long name must not be empty"}
            if len(long_clean) > 36:
                return {"success": False, "error": "Long name max 36 characters"}
        if short_clean is not None:
            if not short_clean:
                return {"success": False, "error": "Short name must not be empty"}
            if len(short_clean) > 4:
                return {"success": False, "error": "Short name max 4 characters"}

        try:
            # No waitForAckNak() here, unlike get_device_metadata's
            # request/response round trip: Node.setOwner()'s own source
            # sets onResponse=None for the local node case (self ==
            # self.iface.localNode) -- the library's own authors chose
            # not to wait for an ack when renaming the directly-attached
            # device, since sendData() already queues the write and
            # nothing ever sets receivedAck/receivedNak for this path.
            # An earlier version of this method DID call waitForAckNak()
            # here, which -- since nothing was ever going to satisfy
            # it -- blocked for its full 20s default timeout on every
            # single rename, synchronously freezing the whole dashboard's
            # asyncio event loop (this method has no executor wrapper)
            # for that entire duration. Confirmed by reading the real
            # meshtastic-python Timeout/waitForAckNak source before
            # removing this, not guessed.
            iface.localNode.setOwner(long_name=long_clean, short_name=short_clean)
        except SystemExit:
            logger.error(
                "%s: setOwner unexpectedly hit sys.exit (should be unreachable "
                "after validation above)", self.name,
            )
            return {"success": False, "error": "Internal error setting owner"}
        except Exception as exc:
            logger.exception("%s: setOwner failed", self.name)
            return {"success": False, "error": str(exc)}

        # Update our own cache immediately -- meshtastic-python's
        # getMyNodeInfo()/nodesByNum isn't guaranteed to reflect a local
        # rename until the device's own NodeInfo happens to round-trip
        # back through the receive stream. Config-page readouts and any
        # advert sent right after this call should show the new name
        # right away, not lag behind.
        if long_clean is not None:
            self._radio_info["long_name"] = long_clean
        if short_clean is not None:
            self._radio_info["short_name"] = short_clean

        logger.info(
            "%s: renamed (long=%r short=%r)", self.name, long_clean, short_clean,
        )
        return {"success": True, "long_name": long_clean, "short_name": short_clean}

    def set_region(self, region: str) -> dict:
        """Set this stick's LoRa region over the already-open serial
        connection -- e.g. for a freshly-flashed board with region
        UNSET (Meshtastic's factory default; it will not transmit at
        all until this is set).

        Same ``Node.writeConfig()`` AdminMessage mechanism as
        ``set_owner()``'s ``setOwner()`` call, and the same reasoning
        applies for why this doesn't block the event loop: writeConfig
        only sets ``onResponse=self.onAckNak`` (which DOES wait) when
        ``self != self.iface.localNode`` -- for the directly-attached
        device (always true here) it's unconditionally ``None``,
        confirmed by reading meshtastic-python's own node.py source
        before relying on it, not guessed.

        ``region`` is a ``Config.LoRaConfig.RegionCode`` enum NAME
        (e.g. ``"EU_433"``), not its int value -- validated against the
        real enum so a typo fails cleanly instead of silently writing 0
        (UNSET) or raising deep inside protobuf.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected"}

        try:
            from meshtastic.protobuf import config_pb2
            region_value = config_pb2.Config.LoRaConfig.RegionCode.Value(region)
        except ValueError:
            return {"success": False, "error": f"Unknown region: {region}"}

        try:
            node = iface.localNode
            node.localConfig.lora.region = region_value
            node.writeConfig("lora")
        except SystemExit:
            logger.error(
                "%s: writeConfig(lora) unexpectedly hit sys.exit (should be "
                "unreachable -- 'lora' is always a valid config_name)", self.name,
            )
            return {"success": False, "error": "Internal error setting region"}
        except Exception as exc:
            logger.exception("%s: set_region failed", self.name)
            return {"success": False, "error": str(exc)}

        # Same immediate-cache-update reasoning as set_owner() above --
        # don't wait for the region to round-trip back through the
        # receive stream before the readout tile reflects it.
        self._radio_info["region"] = region
        logger.info("%s: region set to %s", self.name, region)
        self.handle_link_drop("lora config write: node reboots")
        return {"success": True, "region": region}

    def set_bluetooth(
        self, enabled: bool, mode: Optional[str] = None, fixed_pin: Optional[int] = None,
    ) -> dict:
        """Set this stick's Bluetooth config over its already-open
        serial connection -- same ``Node.writeConfig()`` mechanism (and
        the same non-blocking guarantee) as ``set_region()``/
        ``set_owner()``.

        Deliberately leaves the choice to the user rather than picking
        one on their behalf: a USB-only capture stick arguably has no
        need for Bluetooth at all, but someone who still wants
        occasional phone-app access can pick a fixed PIN instead of
        disabling it outright.

        ``mode`` is a ``Config.BluetoothConfig.PairingMode`` enum NAME
        (``"RANDOM_PIN"``/``"FIXED_PIN"``/``"NO_PIN"``) -- optional,
        left unchanged if not given. ``fixed_pin`` only means anything
        when mode is (or already is) ``"FIXED_PIN"``.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected"}

        mode_value = None
        if mode is not None:
            try:
                from meshtastic.protobuf import config_pb2
                mode_value = config_pb2.Config.BluetoothConfig.PairingMode.Value(mode)
            except ValueError:
                return {"success": False, "error": f"Unknown pairing mode: {mode}"}

        if fixed_pin is not None and not (0 <= fixed_pin <= 999999):
            return {"success": False, "error": "PIN must be a 6-digit number (0-999999)"}

        try:
            node = iface.localNode
            node.localConfig.bluetooth.enabled = enabled
            if mode_value is not None:
                node.localConfig.bluetooth.mode = mode_value
            if fixed_pin is not None:
                node.localConfig.bluetooth.fixed_pin = fixed_pin
            node.writeConfig("bluetooth")
        except SystemExit:
            logger.error(
                "%s: writeConfig(bluetooth) unexpectedly hit sys.exit (should be "
                "unreachable -- 'bluetooth' is always a valid config_name)", self.name,
            )
            return {"success": False, "error": "Internal error setting Bluetooth config"}
        except Exception as exc:
            logger.exception("%s: set_bluetooth failed", self.name)
            return {"success": False, "error": str(exc)}

        self._radio_info["bluetooth_enabled"] = enabled
        if mode is not None:
            self._radio_info["bluetooth_mode"] = mode
        logger.info(
            "%s: bluetooth set (enabled=%s mode=%s)", self.name, enabled, mode,
        )
        self.handle_link_drop("bluetooth config write: node reboots")
        return {"success": True, "enabled": enabled, "mode": mode, "fixed_pin": fixed_pin}

    def set_modem_preset(self, preset: str) -> dict:
        """Set this stick's LoRa modem preset over its already-open
        serial connection -- same ``Node.writeConfig("lora")`` mechanism
        as ``set_region()`` (both live on ``localConfig.lora``, so this
        writes the same config section, just a different field).

        ``preset`` is a ``Config.LoRaConfig.ModemPreset`` enum NAME
        (e.g. ``"LONG_FAST"``), not its int value. Always sets
        ``use_preset = True`` -- this method only supports the named
        presets, not a fully custom spread-factor/bandwidth/coding-rate
        config (Meshtastic's own "Custom" option), which would need its
        own dedicated fields and isn't exposed from the dashboard.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected"}

        try:
            from meshtastic.protobuf import config_pb2
            preset_value = config_pb2.Config.LoRaConfig.ModemPreset.Value(preset)
        except ValueError:
            return {"success": False, "error": f"Unknown modem preset: {preset}"}

        try:
            node = iface.localNode
            node.localConfig.lora.use_preset = True
            node.localConfig.lora.modem_preset = preset_value
            node.writeConfig("lora")
        except SystemExit:
            logger.error(
                "%s: writeConfig(lora) unexpectedly hit sys.exit (should be "
                "unreachable -- 'lora' is always a valid config_name)", self.name,
            )
            return {"success": False, "error": "Internal error setting modem preset"}
        except Exception as exc:
            logger.exception("%s: set_modem_preset failed", self.name)
            return {"success": False, "error": str(exc)}

        self._radio_info["modem_preset"] = preset
        self._radio_info["use_preset"] = True
        logger.info("%s: modem preset set to %s", self.name, preset)
        self.handle_link_drop("lora config write: node reboots")
        return {"success": True, "modem_preset": preset}

    def set_broadcast_intervals(
        self,
        node_info_secs: Optional[int] = None,
        telemetry_secs: Optional[int] = None,
    ) -> dict:
        """Set how often this stick announces its own NodeInfo
        (``device.node_info_broadcast_secs``) and/or reports its own
        device telemetry (``telemetry.device_update_interval``, a
        MODULE config, not a top-level one -- hence the separate
        ``writeConfig("telemetry")`` call) to the mesh.

        NOT the same subsystem as Meshpoint's own concentrator
        NodeInfo/telemetry broadcast interval settings (a separate
        Meshpoint-side scheduler for its own directly-driven radio) --
        this is the attached Meshtastic stick's own firmware-internal
        broadcast timing, independent of anything Meshpoint's concentrator
        does. Either argument can be omitted to leave that one setting
        unchanged; at least one should be given or this is a no-op.
        """
        iface = self._interface
        if iface is None or not self._connected:
            return {"success": False, "error": "Not connected"}

        for label, value in (("NodeInfo", node_info_secs), ("telemetry", telemetry_secs)):
            if value is not None and not (0 <= value <= 86400):
                return {
                    "success": False,
                    "error": f"{label} interval must be between 0 and 86400 seconds",
                }

        try:
            node = iface.localNode
            if node_info_secs is not None:
                node.localConfig.device.node_info_broadcast_secs = node_info_secs
                node.writeConfig("device")
            if telemetry_secs is not None:
                node.moduleConfig.telemetry.device_update_interval = telemetry_secs
                node.writeConfig("telemetry")
        except SystemExit:
            logger.error(
                "%s: writeConfig unexpectedly hit sys.exit (should be "
                "unreachable -- 'device'/'telemetry' are always valid "
                "config_names)", self.name,
            )
            return {"success": False, "error": "Internal error setting broadcast intervals"}
        except Exception as exc:
            logger.exception("%s: set_broadcast_intervals failed", self.name)
            return {"success": False, "error": str(exc)}

        logger.info(
            "%s: broadcast intervals set (node_info_secs=%s telemetry_secs=%s)",
            self.name, node_info_secs, telemetry_secs,
        )
        return {
            "success": True,
            "node_info_broadcast_secs": node_info_secs,
            "telemetry_device_update_interval": telemetry_secs,
        }

    async def start(self) -> None:
        self._running = True
        self._loop = asyncio.get_running_loop()
        if await self._attempt_connect():
            return
        logger.warning(
            "%s: initial connect failed -- retrying in the background "
            "instead of staying dead until a service restart",
            self.name,
        )
        self._link_phase = "reconnecting"
        self._reconnect_task = asyncio.create_task(
            self._reconnect_until_connected(), name=f"{self.name}-reconnect",
        )

    def _blocking_connect(self):
        """The actual open-port + handshake + config read -- real
        blocking serial I/O (meshtastic-python's StreamInterface.__init__
        calls waitForConfig() synchronously before returning), run off
        the event loop via asyncio.to_thread by both the initial connect
        and every background retry so a wedged/busy port never freezes
        the whole server -- every other capture source, the dashboard
        API, all of it -- for however long that takes to time out.
        """
        import meshtastic.serial_interface

        if self._port:
            interface = meshtastic.serial_interface.SerialInterface(devPath=self._port)
        else:
            interface = meshtastic.serial_interface.SerialInterface()
        radio_info = self._read_radio_info(interface)
        return interface, radio_info

    async def _attempt_connect(self) -> bool:
        """One connection attempt. Returns True/False instead of raising,
        so a background retry loop can call this in a loop -- except for
        ImportError, which still needs to abort the whole app loudly (a
        missing dependency, not a hardware hiccup worth retrying)."""
        try:
            interface, radio_info = await asyncio.to_thread(self._blocking_connect)
        except ImportError:
            logger.error(
                "meshtastic package not installed. "
                "Install with: pip install meshtastic"
            )
            raise
        except Exception:
            logger.debug("%s: connect attempt failed", self.name, exc_info=True)
            return False

        from pubsub import pub

        self._interface = interface
        self._radio_info = radio_info
        self._connected = True
        pub.subscribe(self._on_receive, "meshtastic.receive")
        if not self._lost_subscribed:
            pub.subscribe(self._on_connection_lost, "meshtastic.connection.lost")
            self._lost_subscribed = True
        logger.info(
            "Serial capture started on %s (region=%s channel_num=%s)",
            self._port or "auto-detect",
            self._radio_info.get("region"),
            self._radio_info.get("channel_num"),
        )
        if self._desired_long_name or self._desired_short_name:
            result = self.set_owner(self._desired_long_name, self._desired_short_name)
            if result["success"]:
                logger.info("%s: applied configured identity on connect", self.name)
            else:
                logger.warning(
                    "%s: failed to apply configured identity on connect: %s",
                    self.name, result["error"],
                )
        return True

    async def _reconnect_until_connected(self, first_delay: Optional[float] = None) -> None:
        delay = _RECONNECT_BASE_DELAY_SECONDS if first_delay is None else first_delay
        try:
            while self._running:
                logger.info("%s: reconnecting in %ds...", self.name, delay)
                self._retry_at = time.monotonic() + delay
                await asyncio.sleep(delay)
                if not self._running:
                    return
                self._retry_at = None  # attempt (handshake) in progress
                if await self._attempt_connect():
                    logger.info("%s: reconnected successfully", self.name)
                    return
                delay = min(max(delay, _RECONNECT_BASE_DELAY_SECONDS) * 2,
                            _RECONNECT_MAX_DELAY_SECONDS)
        finally:
            self._link_phase = None
            self._retry_at = None

    @staticmethod
    def _read_radio_info(interface) -> dict:
        """Region/channel/modem/name from the interface's own config.

        meshtastic-python's StreamInterface.__init__ already calls
        waitForConfig() synchronously before SerialInterface(...)
        returns, so localNode.localConfig.lora and the node identity
        are populated by the time this runs -- no extra wait needed.
        Best-effort: any read failure leaves that field None rather
        than raising, since this must never block a successful capture
        start.

        SF/bandwidth/coding rate depend on whether the node uses a
        named modem preset (the common case -- looked up in
        src.radio.presets, the same table the dashboard's preset
        picker uses) or a fully custom config (use_preset=False,
        reading the raw spread_factor/bandwidth/coding_rate fields
        directly; coding_rate is stored as just the denominator, e.g.
        5 means "4/5").
        """
        info: dict = {
            "region": None, "channel_num": None,
            "short_name": None, "long_name": None,
            "modem_preset": None, "use_preset": True,
            "spreading_factor": None, "bandwidth_khz": None, "coding_rate": None,
            "channel_name": None, "frequency_offset": 0.0, "override_frequency": 0.0,
            "own_node_num": None,
            "firmware_version": None, "hw_model": None,
            "tx_power": None,
            "bluetooth_enabled": None, "bluetooth_mode": None,
            "node_info_broadcast_secs": None, "telemetry_device_update_interval": None,
        }
        try:
            from meshtastic.protobuf import config_pb2
            lora = interface.localNode.localConfig.lora
            info["channel_num"] = int(lora.channel_num)
            info["region"] = config_pb2.Config.LoRaConfig.RegionCode.Name(lora.region)
            info["use_preset"] = bool(lora.use_preset)
            info["frequency_offset"] = float(lora.frequency_offset)
            info["override_frequency"] = float(lora.override_frequency)
            if lora.tx_power:
                info["tx_power"] = int(lora.tx_power)
            if lora.use_preset:
                preset_name = config_pb2.Config.LoRaConfig.ModemPreset.Name(
                    lora.modem_preset,
                )
                info["modem_preset"] = preset_name
                preset = get_preset(preset_name)
                if preset:
                    info["spreading_factor"] = preset.spreading_factor
                    info["bandwidth_khz"] = preset.bandwidth_khz
                    info["coding_rate"] = preset.coding_rate
            else:
                info["modem_preset"] = "CUSTOM"
                if lora.spread_factor:
                    info["spreading_factor"] = int(lora.spread_factor)
                if lora.bandwidth:
                    info["bandwidth_khz"] = float(lora.bandwidth)
                if lora.coding_rate:
                    info["coding_rate"] = f"4/{int(lora.coding_rate)}"
        except Exception:
            logger.debug("Could not read LoRa config from serial interface", exc_info=True)
        try:
            from meshtastic.protobuf import config_pb2 as _config_pb2
            bluetooth = interface.localNode.localConfig.bluetooth
            info["bluetooth_enabled"] = bool(bluetooth.enabled)
            info["bluetooth_mode"] = _config_pb2.Config.BluetoothConfig.PairingMode.Name(
                bluetooth.mode,
            )
        except Exception:
            logger.debug("Could not read Bluetooth config from serial interface", exc_info=True)
        try:
            info["node_info_broadcast_secs"] = int(
                interface.localNode.localConfig.device.node_info_broadcast_secs,
            )
        except Exception:
            logger.debug(
                "Could not read node_info_broadcast_secs from serial interface", exc_info=True,
            )
        try:
            info["telemetry_device_update_interval"] = int(
                interface.localNode.moduleConfig.telemetry.device_update_interval,
            )
        except Exception:
            logger.debug(
                "Could not read telemetry.device_update_interval from serial interface",
                exc_info=True,
            )
        try:
            info["short_name"] = interface.getShortName()
            info["long_name"] = interface.getLongName()
        except Exception:
            logger.debug("Could not read node identity from serial interface", exc_info=True)
        try:
            info["channel_name"] = SerialCaptureSource._read_primary_channel_name(interface)
        except Exception:
            logger.debug("Could not read primary channel name from serial interface", exc_info=True)
        try:
            info["channel_table"] = SerialCaptureSource._read_channel_table(
                interface, info.get("modem_preset")
            )
        except Exception:
            logger.debug("Could not read channel table from serial interface", exc_info=True)
            info["channel_table"] = {}
        try:
            info["own_node_num"] = int(interface.myInfo.my_node_num)
        except Exception:
            logger.debug("Could not read own node number from serial interface", exc_info=True)
        try:
            # Unlike the fields above (all read from state the interface
            # already caches from the initial connect handshake),
            # firmware/hw model need an explicit admin-message round trip
            # -- getMetadata() sends the request and blocks on its own
            # ack/nak wait, then the response lands in interface.metadata
            # as a side effect (same mechanism as MeshCore's
            # send_device_query() in meshcore_tx_client.py, just
            # meshtastic-python's synchronous equivalent). Called once
            # here at connect time only, never repeated on every status
            # poll. UNVERIFIED against a real serial stick as of writing
            # (no Meshtastic hardware on the Mac dev machine) -- the
            # field names (firmware_version, hw_model) are confirmed
            # against the real meshtastic/protobufs DeviceMetadata
            # message, but the exact getMetadata()/interface.metadata
            # interaction hasn't been exercised live.
            interface.localNode.getMetadata()
            metadata = getattr(interface, "metadata", None)
            if metadata:
                info["firmware_version"] = metadata.firmware_version or None
                from meshtastic.protobuf import mesh_pb2
                info["hw_model"] = mesh_pb2.HardwareModel.Name(metadata.hw_model)
        except Exception:
            logger.debug("Could not read device metadata from serial interface", exc_info=True)
        return info

    @staticmethod
    def _read_primary_channel_name(interface) -> Optional[str]:
        """The primary channel's own name, for frequency-slot hashing.

        meshtastic/firmware's Channels::getName() hashes this string
        (falling back to the modem preset's display name when it's
        blank -- the common case for a stock setup) to pick a default
        frequency slot. Returns None (not "") when there's no primary
        channel, so callers can tell "blank name" from "no data".
        """
        from meshtastic.protobuf import channel_pb2
        channels = getattr(interface.localNode, "channels", None) or []
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.PRIMARY:
                return ch.settings.name
        return None

    @staticmethod
    def _read_channel_table(
        interface, modem_preset_name: Optional[str] = None
    ) -> dict:
        """This stick's own channel-table index -> name mapping.

        Needed because a received MeshPacket's ``.channel`` field is
        THIS STICK'S local channel-table index when it decoded the
        packet locally (mesh_interface.py sets ``meshPacket.channel =
        channelIndex`` symmetrically on send) -- it has no relationship
        to Meshpoint's own channel numbering or to the real over-the-air
        channel_hash byte. Resolving it to a NAME here is what lets
        ``_build_pre_decoded`` route by something actually meaningful
        instead of a index that only makes sense on this one stick (see
        F1 in the worklist).

        Blank primary-channel names fall back to the modem preset's
        display name, mirroring firmware's own Channels::getName()
        convention (same reasoning as ``_read_primary_channel_name``).
        Blank secondary-channel names are skipped entirely -- there's
        no equivalent fallback for those, and guessing risks silently
        routing traffic to the wrong bucket, the exact failure mode
        this fix exists to eliminate.
        """
        from meshtastic.protobuf import channel_pb2
        table: dict[int, str] = {}
        channels = getattr(interface.localNode, "channels", None) or []
        for ch in channels:
            if ch.role == channel_pb2.Channel.Role.DISABLED:
                continue
            name = ch.settings.name
            if not name and ch.role == channel_pb2.Channel.Role.PRIMARY:
                name = modem_preset_name
            if name:
                table[ch.index] = name
        return table

    def resolve_channel_index(self, name: str) -> Optional[int]:
        """This stick's own channel-table index for ``name``, or None
        if it has no channel configured under that exact name.

        Used when sending a reply through this stick: the dashboard's
        own channel index has no relationship to this stick's channel
        table (a separate physical node with its own, independently
        ordered channel list) -- translating by name, and refusing to
        send at all when there's no match, replaces the previous
        behavior of passing Meshpoint's index straight through as if
        the two numberings were interchangeable (see F3 in the
        worklist).
        """
        table = self._radio_info.get("channel_table") or {}
        for idx, ch_name in table.items():
            if ch_name == name:
                return idx
        return None

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reconnect_task = None
        if self._interface:
            try:
                self._interface.close()
            except Exception:
                pass
            self._interface = None
        self._link_phase = None
        self._retry_at = None
        if self._lost_subscribed:
            try:
                from pubsub import pub
                pub.unsubscribe(self._on_connection_lost, "meshtastic.connection.lost")
            except Exception:
                logger.debug("%s: pubsub unsubscribe failed", self.name, exc_info=True)
            self._lost_subscribed = False
        logger.info("Serial capture stopped")

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            try:
                raw = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                yield raw
            except asyncio.TimeoutError:
                continue

    def _on_connection_lost(self, interface=None, **_kwargs) -> None:
        """pypubsub callback (meshtastic reader thread) for a dropped link."""
        self.handle_link_drop("connection lost", interface)

    def handle_link_drop(self, reason: str, interface=None) -> None:
        """Treat the current interface as dead and reconnect with backoff.

        Thread-safe: called from meshtastic's reader thread, from a worker
        thread running a config write, or from the event loop itself. An
        event for another stick's interface (multi-stick setups share the
        process-wide topic) is ignored.
        """
        if not self._running:
            return
        if interface is not None and interface is not self._interface:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._begin_reconnect, reason)
        except RuntimeError:
            pass  # loop shutting down

    def _begin_reconnect(self, reason: str) -> None:
        """On the event loop: mark disconnected and start the retry task once."""
        if not self._running:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        dead = self._interface
        self._interface = None
        self._connected = False
        rebooting = "config write" in reason
        self._link_phase = "rebooting" if rebooting else "reconnecting"
        first_delay = _REBOOT_INITIAL_DELAY_SECONDS if rebooting else _RECONNECT_BASE_DELAY_SECONDS
        self._retry_at = time.monotonic() + first_delay
        logger.warning("%s: serial link dropped (%s); %s", self.name, reason, self._link_phase)
        self._reconnect_task = asyncio.create_task(
            self._close_then_reconnect(dead, first_delay), name=f"{self.name}-reconnect",
        )

    async def _close_then_reconnect(self, dead, first_delay: Optional[float] = None) -> None:
        if dead is not None:
            try:
                # close() joins meshtastic's reader thread: off the loop.
                await asyncio.to_thread(dead.close)
            except Exception:
                logger.debug("%s: closing the dead interface failed", self.name, exc_info=True)
        await self._reconnect_until_connected(first_delay)

    def _on_receive(self, packet, interface) -> None:
        """Callback invoked by meshtastic-python on packet reception.

        meshtastic-python publishes every open interface's packets on one
        process-wide pypubsub topic ("meshtastic.receive"), so with more
        than one SerialCaptureSource running (multiple USB sticks), each
        instance's callback fires for every stick's packets, not just its
        own. Compare identity against our own interface so a multi-stick
        setup doesn't duplicate/misattribute packets across devices.
        """
        if not self._running or interface is not self._interface:
            return

        try:
            raw_capture = self._packet_to_raw_capture(packet)
            if raw_capture:
                try:
                    self._queue.put_nowait(raw_capture)
                except asyncio.QueueFull:
                    logger.warning("Serial capture queue full")
        except Exception:
            logger.debug("Failed to convert serial packet", exc_info=True)

    def _packet_to_raw_capture(self, packet: dict) -> Optional[RawCapture]:
        """Convert a meshtastic-python packet dict to a RawCapture."""
        own_node_num = self._radio_info.get("own_node_num")
        is_self = own_node_num is not None and packet.get("from") == own_node_num
        is_text = (
            isinstance(packet.get("decoded"), dict)
            and packet["decoded"].get("portnum") == "TEXT_MESSAGE_APP"
        )
        if is_self and not is_text:
            # The connected stick's own periodic self-telemetry/nodeinfo
            # (and anything else it locally originates) passes through
            # the same "meshtastic.receive" event stream as genuinely
            # received packets -- meshtastic-python doesn't distinguish
            # them. Firmware's own convention (rx_rssi == rx_snr == 0)
            # confirms these were never actually received over the air,
            # so there's no real signal to report; dropped here rather
            # than flowing through decode/storage/the packet feed/node
            # counters as a confusing, spammy "-100 dBm" reading of the
            # stick reporting on itself.
            #
            # Text messages are exempt: a message the user typed via a
            # BLE/WiFi-connected app on this same physical stick is
            # genuine chat content, not a beacon -- it should still reach
            # decode/storage so it shows up in the Messages panel, even
            # though this stick is also its own "from" node here.
            logger.debug(
                "Dropping self-originated packet from own node %08x", own_node_num,
            )
            return None

        raw_bytes = packet.get("raw", b"")
        if isinstance(raw_bytes, str):
            raw_bytes = bytes.fromhex(raw_bytes)
        elif not isinstance(raw_bytes, (bytes, bytearray)):
            # meshtastic-python always sets packet["raw"] to the decoded
            # MeshPacket protobuf object (mesh_interface.py explicitly
            # does `asDict["raw"] = meshPacket`), never actual bytes.
            # Treat anything that isn't bytes as absent so the
            # reconstruction fallback below actually runs instead of
            # passing a protobuf object downstream as if it were bytes.
            raw_bytes = b""

        if not raw_bytes:
            # Reconstruct regardless of whether "decoded" is present.
            # "decoded" and "encrypted" share one protobuf oneof: a
            # packet the connected radio's own key COULDN'T decrypt
            # (e.g. traffic on a channel it isn't configured for) has
            # "encrypted" set and NO "decoded" key at all -- gating on
            # "decoded" here silently dropped exactly that case, the
            # one a passive multi-channel sniffer most needs (its own
            # channel_keys config may decrypt what the stick couldn't).
            raw_bytes = self._reconstruct_raw(packet)

        if not raw_bytes:
            return None

        radio = self._radio_info
        signal = SignalMetrics(
            rssi=float(packet.get("rxRssi", packet.get("rssi", -100))),
            snr=float(packet.get("rxSnr", packet.get("snr", 0))),
            frequency_mhz=resolve_frequency_mhz(
                region=radio.get("region"),
                channel_num=radio.get("channel_num"),
                bandwidth_khz=radio.get("bandwidth_khz") or 250.0,
                channel_name=radio.get("channel_name"),
                modem_preset=radio.get("modem_preset"),
                use_preset=radio.get("use_preset", True),
                frequency_offset=radio.get("frequency_offset") or 0.0,
                override_frequency=radio.get("override_frequency") or 0.0,
            ),
            # Fall back to LongFast (the de facto default preset almost
            # every Meshtastic node runs) only when the handshake
            # hasn't populated these yet -- better than the previous
            # unconditional 11/250.0 which never reflected non-LongFast
            # presets either.
            spreading_factor=radio.get("spreading_factor") or 11,
            bandwidth_khz=radio.get("bandwidth_khz") or 250.0,
            coding_rate=radio.get("coding_rate") or "4/5",
        )

        return RawCapture(
            payload=raw_bytes,
            signal=signal,
            capture_source=self.name,
            timestamp=datetime.now(timezone.utc),
            pre_decoded=self._build_pre_decoded(packet),
        )

    def _build_pre_decoded(self, packet: dict) -> Optional[dict]:
        """Portnum + inner payload when meshtastic-python decrypted this
        packet locally with the connected radio's own key.

        "decoded" and "encrypted" share one protobuf oneof (see
        _packet_to_raw_capture's comment above), so when "decoded" is
        present there is no ciphertext left for Meshpoint's own
        crypto_service to attempt -- without this, such packets always
        showed as "Unknown" even though the actual decoded content
        (position, telemetry, nodeinfo, ...) was sitting right there in
        the dict the whole time. Portnum names/encoding verified against
        the installed meshtastic.protobuf.portnums_pb2 (MessageToDict
        emits the enum NAME string and base64-encodes payload bytes).

        Also resolves ``packet["channel"]`` (this stick's own local
        channel-table index for locally-decoded packets, see F1 in the
        worklist) to a channel NAME via the connect-time channel table,
        so the caller can route by name instead of misreading a local
        index as if it were the real over-the-air channel_hash.
        """
        decoded = packet.get("decoded")
        if not isinstance(decoded, dict):
            return None
        portnum_name = decoded.get("portnum")
        if not portnum_name:
            return None
        try:
            from meshtastic.protobuf import portnums_pb2
            portnum = portnums_pb2.PortNum.Value(portnum_name)
        except (ImportError, ValueError):
            logger.debug("Unrecognized portnum name %r", portnum_name)
            return None

        payload_b64 = decoded.get("payload", "")
        try:
            payload = base64.b64decode(payload_b64) if payload_b64 else b""
        except Exception:
            logger.debug("Could not base64-decode decoded.payload", exc_info=True)
            payload = b""

        result = {
            "portnum": portnum,
            "payload": payload,
            "request_id": decoded.get("requestId", 0),
        }
        channel_idx = packet.get("channel")
        if channel_idx is not None:
            channel_name = self._radio_info.get("channel_table", {}).get(channel_idx)
            if channel_name:
                result["channel_name"] = channel_name
        return result

    @staticmethod
    def _reconstruct_raw(packet: dict) -> bytes:
        """Build a minimal raw frame from a decoded meshtastic packet.

        When the meshtastic library provides already-decoded data
        without raw bytes, we reconstruct the header so the pipeline
        can process it. The payload portion will be empty/encrypted.

        ``packet["channel"]`` means two different things depending on
        whether this stick decrypted the packet locally: for a
        genuinely undecryptable packet (only "encrypted" set) it's the
        real on-air channel_hash byte; for a locally-decoded one
        (mesh_interface.py sets ``meshPacket.channel = channelIndex``
        symmetrically on send) it's this stick's own local channel
        INDEX, unrelated to any real hash. Stuffed into the header's
        hash-byte position either way for a structurally valid frame,
        but callers must not trust it for the locally-decoded case --
        ``_build_pre_decoded`` resolves the real channel NAME instead
        (see F1 in the worklist), which routing should prefer whenever
        it's present.
        """
        import struct

        dest = packet.get("to", 0xFFFFFFFF)
        source = packet.get("from", 0)
        pkt_id = packet.get("id", 0)

        hop_limit = packet.get("hopLimit", 3)
        hop_start = packet.get("hopStart", 3)
        want_ack = packet.get("wantAck", False)

        flags = (hop_limit & 0x07)
        if want_ack:
            flags |= 0x08
        flags |= (hop_start & 0x07) << 5

        channel = packet.get("channel", 0)

        header = struct.pack("<III", dest, source, pkt_id)
        header += bytes([flags, channel, 0, 0])

        # google.protobuf.json_format.MessageToDict base64-encodes bytes
        # fields, and the MeshPacket field is named "encrypted" (verified
        # against the installed meshtastic.protobuf.mesh_pb2.MeshPacket
        # descriptor) -- not "encoded"/hex, which never matched any real
        # key from this library. "encrypted" and "decoded" share one
        # protobuf oneof, so it's empty whenever the connected radio's
        # own key already decrypted the packet locally -- that's the
        # "payload portion will be empty" case above, not a bug here.
        encoded = packet.get("encrypted", b"")
        if isinstance(encoded, str):
            encoded = base64.b64decode(encoded)

        return header + encoded
