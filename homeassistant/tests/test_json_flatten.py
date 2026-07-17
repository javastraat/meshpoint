"""Unit tests for the standalone JSON flattener.

No Home Assistant imports -- pure Python, runs with a plain ``pytest``.
"""

from custom_components.meshpoint.json_flatten import flatten_json

DEVICE_METRICS_SAMPLE = {
    "cpu_percent": 24.6,
    "memory_percent": 16.5,
    "memory_used_mb": 207,
    "memory_total_mb": 1783,
    "disk_percent": 41.4,
    "disk_used_gb": 12.3,
    "disk_total_gb": 29.7,
    "cpu_temp_c": 41.4,
    "load_avg": [0.12, 0.08, 0.05],
    "system_uptime_seconds": 543120,
    "fan_duty_percent": None,
    "fan_previous_duty_percent": None,
}

STATS_SUMMARY_SAMPLE = {
    "device": {"name": "PD2EMC Meshpoint", "region": "EU_868", "firmware": "0.7.7"},
    "first_packet_time": "2026-05-01T12:00:00+00:00",
    "signal": {"best_rssi": -34.0, "best_snr": 12.3},
    "rssi_distribution": {"-100_to_-90": 12, "-90_to_-80": 40},
    "farthest_mesh": {"miles": 42.1, "node_id": "!abcd1234", "node_name": "Repeater X"},
    "farthest_meshcore": None,
    "network": {"roles": {"CLIENT": 40, "ROUTER": 2}, "total_nodes": 1936},
}


def test_flat_numeric_fields_pass_through():
    flat = flatten_json(DEVICE_METRICS_SAMPLE)
    assert flat["cpu_percent"] == 24.6
    assert flat["memory_used_mb"] == 207


def test_none_values_are_skipped():
    flat = flatten_json(DEVICE_METRICS_SAMPLE)
    assert "fan_duty_percent" not in flat
    assert "fan_previous_duty_percent" not in flat


def test_lists_are_skipped_entirely():
    flat = flatten_json(DEVICE_METRICS_SAMPLE)
    assert "load_avg" not in flat
    assert not any(k.startswith("load_avg") for k in flat)


def test_nested_dict_flattens_with_underscore_join():
    flat = flatten_json(STATS_SUMMARY_SAMPLE)
    assert flat["device_name"] == "PD2EMC Meshpoint"
    assert flat["device_region"] == "EU_868"
    assert flat["signal_best_rssi"] == -34.0
    assert flat["signal_best_snr"] == 12.3


def test_skip_keys_excluded_even_when_nested():
    flat = flatten_json(STATS_SUMMARY_SAMPLE)
    assert not any(k.startswith("rssi_distribution") for k in flat)


def test_none_branch_produces_no_keys_not_a_crash():
    flat = flatten_json(STATS_SUMMARY_SAMPLE)
    assert not any(k.startswith("farthest_meshcore") for k in flat)


def test_deeply_nested_dict_with_dynamic_keys():
    flat = flatten_json(STATS_SUMMARY_SAMPLE)
    assert flat["network_roles_client"] == 40
    assert flat["network_roles_router"] == 2
    assert flat["network_total_nodes"] == 1936


def test_farthest_contact_present_flattens_cleanly():
    flat = flatten_json(STATS_SUMMARY_SAMPLE)
    assert flat["farthest_mesh_miles"] == 42.1
    assert flat["farthest_mesh_node_name"] == "Repeater X"


def test_bool_becomes_zero_or_one():
    flat = flatten_json({"relay_enabled": True, "noise_floor_stale": False})
    assert flat["relay_enabled"] == 1
    assert flat["noise_floor_stale"] == 0


def test_empty_string_skipped():
    flat = flatten_json({"name": "", "region": "EU_868"})
    assert "name" not in flat
    assert flat["region"] == "EU_868"


def test_non_dict_input_returns_empty():
    assert flatten_json([1, 2, 3]) == {}
    assert flatten_json(None) == {}


def test_prefix_argument_applied():
    flat = flatten_json({"cpu_percent": 5.0}, prefix="device")
    assert flat == {"device_cpu_percent": 5.0}
