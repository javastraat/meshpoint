"""Extra fields for ``GET /api/config`` beyond the original radio/transmit summary."""

from __future__ import annotations

from src.config import AppConfig


def enrich_config_payload(cfg: AppConfig, base: dict) -> dict:
    """Merge device, upstream, storage, capture, location, and extended relay/radio into *base*."""
    device = cfg.device
    upstream = cfg.upstream
    storage = cfg.storage
    capture = cfg.capture
    relay = cfg.relay
    radio = cfg.radio
    location = cfg.location
    companions = capture.meshcore_usb  # list[MeshcoreUsbConfig]
    mc_usb = companions[0] if companions else None

    token = (upstream.auth_token or "").strip()
    base["device"] = {
        "device_name": device.device_name,
        "latitude": device.latitude,
        "longitude": device.longitude,
        "altitude": device.altitude,
        "hardware_description": device.hardware_description,
    }
    base["upstream"] = {
        "url": upstream.url,
        "reconnect_interval_seconds": upstream.reconnect_interval_seconds,
        "buffer_max_size": upstream.buffer_max_size,
        "auth_token_set": bool(token),
    }
    base["storage"] = {
        "database_path": storage.database_path,
        "max_packets_retained": storage.max_packets_retained,
        "cleanup_interval_seconds": storage.cleanup_interval_seconds,
    }
    base["capture"] = {
        "sources": list(capture.sources or []),
        "concentrator_spi_device": capture.concentrator_spi_device,
        "meshcore_usb": [
            {
                "serial_port": c.serial_port,
                "baud_rate": c.baud_rate,
                "auto_detect": c.auto_detect,
                "label": c.label,
            }
            for c in companions
        ],
        "meshcore_usb_primary": {
            "serial_port": mc_usb.serial_port if mc_usb else None,
            "baud_rate": mc_usb.baud_rate if mc_usb else 115200,
            "auto_detect": mc_usb.auto_detect if mc_usb else True,
            "label": mc_usb.label if mc_usb else "",
        },
        "serial": [
            {
                "serial_port": d.serial_port,
                "serial_baud": d.serial_baud,
                "label": d.label,
            }
            for d in capture.serial
        ],
    }
    base["relay"] = {
        "enabled": relay.enabled,
        "serial_port": relay.serial_port,
        "serial_baud": relay.serial_baud,
        "max_relay_per_minute": relay.max_relay_per_minute,
        "burst_size": relay.burst_size,
        "min_relay_rssi": relay.min_relay_rssi,
        "max_relay_rssi": relay.max_relay_rssi,
    }
    base["radio_advanced"] = {
        "spectral_scan_interval_seconds": radio.spectral_scan_interval_seconds,
        "sx1261_spi_path": radio.sx1261_spi_path or "",
    }
    base["location"] = {
        "source": location.source,
        "gpsd_host": location.gpsd_host,
        "gpsd_port": location.gpsd_port,
        "update_interval_seconds": location.update_interval_seconds,
        "min_fix_quality": location.min_fix_quality,
    }
    fan = cfg.fan
    led = cfg.led
    button = cfg.button
    base["hardware"] = {
        "fan": {
            "enabled": fan.enabled,
            "gpio_pin": fan.gpio_pin,
            "min_temp_c": fan.min_temp_c,
            "max_temp_c": fan.max_temp_c,
            "min_duty": fan.min_duty,
            "hysteresis_c": fan.hysteresis_c,
            "poll_interval_s": fan.poll_interval_s,
        },
        "led": {
            "enabled": led.enabled,
            "gpio_pin": led.gpio_pin,
            "activity_blink": led.activity_blink,
        },
        "button": {
            "enabled": button.enabled,
            "gpio_pin": button.gpio_pin,
            "hold_time_s": button.hold_time_s,
            "advert_cooldown_s": button.advert_cooldown_s,
        },
    }
    update_check = cfg.update_check
    base["update_check"] = {
        "enabled": update_check.enabled,
        "interval_minutes": update_check.interval_minutes,
    }
    pos = cfg.transmit.position
    telem = cfg.transmit.telemetry
    if "transmit" in base:
        base["transmit"]["position"] = {
            "interval_minutes": pos.interval_minutes,
            "startup_delay_seconds": pos.startup_delay_seconds,
            "coordinate_source": pos.coordinate_source,
            "location_precision": pos.location_precision,
        }
        base["transmit"]["telemetry"] = {
            "interval_minutes": telem.interval_minutes,
            "startup_delay_seconds": telem.startup_delay_seconds,
        }
    return base
