# Meshpoint for Home Assistant

A read-only Home Assistant integration for [Meshpoint](https://github.com/javastraat/meshpoint). Polls a Meshpoint gateway's `/metrics` endpoint and exposes its aggregate stats as sensors — uptime, packet rates, node counts, RSSI/SNR averages, relay stats. No per-node or per-contact entities; this is a status integration, not a mesh client (see [meshcore-ha](https://github.com/meshcore-dev/meshcore-ha) if you want that).

Entities are created dynamically from whatever `/metrics` returns, so a metric Meshpoint adds in a future release shows up automatically — no integration update required, just possibly a generic name until `metric_meta.py` is updated for it.

## Setup

1. On the Meshpoint dashboard: **Configuration → Metrics**
   - Enable "Enable /metrics endpoint"
   - If "Require authentication" is on, generate an API key (give it a label like "Home Assistant") and copy it — it's shown once
2. In Home Assistant: **Settings → Devices & Services → + Add Integration → Meshpoint**
3. Enter the Meshpoint gateway's host/IP, port (default `8080`), and the API key from step 1 (leave blank if authentication is off)

## Installation

### Manual

Copy `custom_components/meshpoint` into your Home Assistant config's `custom_components/` directory, then restart Home Assistant.

### HACS (custom repository)

This integration lives in a subdirectory of the main Meshpoint repo rather than its own repo. Add `https://github.com/javastraat/meshpoint` as a HACS custom repository, category "Integration" — if HACS doesn't pick up the subdirectory automatically, manual installation above is the reliable path for now.

## What it does not do

- No per-node or per-contact sensors (Meshpoint can track thousands of mesh nodes; this integration reports counts and rates, not one entity per node)
- No control of Meshpoint or the mesh (read-only, matches the `/metrics` API key's scope — it cannot reach any other Meshpoint API route)
- No messaging, map upload, or radio configuration — that's Meshpoint's own dashboard

## Development

Pure-Python parsing logic (`prometheus.py`) has no Home Assistant imports and can be unit tested standalone:

```bash
python3 -m pytest homeassistant/tests/
```
