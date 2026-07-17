"""Unit tests for the standalone Prometheus text parser.

No Home Assistant imports here on purpose -- prometheus.py is pure
Python so this suite can run with a plain ``pytest``, no HA test
harness required.
"""

from custom_components.meshpoint.prometheus import parse_prometheus_text

SAMPLE = """
# HELP meshpoint_uptime_seconds Seconds since the metrics collector started
# TYPE meshpoint_uptime_seconds gauge
meshpoint_uptime_seconds 54773
# HELP meshpoint_info Meshpoint build info (always 1)
# TYPE meshpoint_info gauge
meshpoint_info{region="EU_868",version="0.7.7"} 1
# HELP meshpoint_protocol_packets_session_total Session packets by protocol
# TYPE meshpoint_protocol_packets_session_total counter
meshpoint_protocol_packets_session_total{protocol="meshtastic"} 460
meshpoint_protocol_packets_session_total{protocol="meshcore"} 202
# HELP meshpoint_rssi_average_dbm Average RSSI over session samples
# TYPE meshpoint_rssi_average_dbm gauge
meshpoint_rssi_average_dbm -83.43
# HELP meshpoint_relay_rejected_total Packets rejected by relay filters
# TYPE meshpoint_relay_rejected_total counter
meshpoint_relay_rejected_total 494
meshpoint_relay_rejected_total{reason="no_hops_remaining"} 323
meshpoint_relay_rejected_total{reason="duplicate"} 39
"""


def test_unlabeled_gauge_parses():
    metrics, _info = parse_prometheus_text(SAMPLE)
    assert metrics["meshpoint_uptime_seconds"] == 54773.0


def test_negative_float_parses():
    metrics, _info = parse_prometheus_text(SAMPLE)
    assert metrics["meshpoint_rssi_average_dbm"] == -83.43


def test_labeled_series_get_suffixed_keys():
    metrics, _info = parse_prometheus_text(SAMPLE)
    assert metrics["meshpoint_protocol_packets_session_total_meshtastic"] == 460.0
    assert metrics["meshpoint_protocol_packets_session_total_meshcore"] == 202.0


def test_bare_and_labeled_variants_of_same_metric_coexist():
    metrics, _info = parse_prometheus_text(SAMPLE)
    assert metrics["meshpoint_relay_rejected_total"] == 494.0
    assert metrics["meshpoint_relay_rejected_total_no_hops_remaining"] == 323.0
    assert metrics["meshpoint_relay_rejected_total_duplicate"] == 39.0


def test_info_series_extracted_separately_not_as_a_metric():
    metrics, info = parse_prometheus_text(SAMPLE)
    assert "meshpoint_info" not in metrics
    assert info == {"region": "EU_868", "version": "0.7.7"}


def test_comments_and_blank_lines_ignored():
    metrics, _info = parse_prometheus_text("\n\n# just a comment\n\n")
    assert metrics == {}


def test_malformed_line_is_skipped_not_fatal():
    text = "not a valid metric line at all\nmeshpoint_uptime_seconds 42\n"
    metrics, _info = parse_prometheus_text(text)
    assert metrics == {"meshpoint_uptime_seconds": 42.0}


def test_non_numeric_value_is_skipped():
    text = 'meshpoint_weird{label="x"} not-a-number\nmeshpoint_uptime_seconds 5\n'
    metrics, _info = parse_prometheus_text(text)
    assert metrics == {"meshpoint_uptime_seconds": 5.0}
