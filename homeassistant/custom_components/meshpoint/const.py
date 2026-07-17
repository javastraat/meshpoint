"""Constants for the Meshpoint integration."""

from __future__ import annotations

DOMAIN = "meshpoint"

CONF_API_KEY = "api_key"

DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 60

# Metric keys that describe the box itself rather than a sensor value --
# pulled out of the parsed metrics dict and attached as device info instead
# of becoming an entity.
INFO_METRIC = "meshpoint_info"

