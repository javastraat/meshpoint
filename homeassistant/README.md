# Meshpoint for Home Assistant

A read-only Home Assistant integration for [Meshpoint](https://github.com/javastraat/meshpoint). Polls three of a Meshpoint gateway's status endpoints and exposes the result as sensors on one device — mesh stats (uptime, packet rates, node counts, RSSI/SNR averages, relay stats), host health (CPU/RAM/disk/temperature/fan), and richer stats-page data (best signal ever, farthest contact, node role/hardware-model distribution). No per-node or per-contact entities; this is a status integration, not a mesh client (see [meshcore-ha](https://github.com/meshcore-dev/meshcore-ha) if you want that).

Entities are created dynamically from whatever those endpoints return, so a metric Meshpoint adds in a future release shows up automatically — no integration update required, just possibly a generic name until `metric_meta.py` is updated for it. The two extra endpoints beyond `/metrics` are polled best-effort: an older Meshpoint (or a key minted before this was added) just won't produce those sensors, `/metrics` alone still works fully.

## 1. On the Meshpoint dashboard

**Configuration → Metrics:**

1. Enable "Enable /metrics endpoint"
2. If "Require authentication" is on, generate an API key (label it something like "Home Assistant") and copy it now — it's shown once, only its hash is stored afterward. The key grants read-only access to `/metrics`, `/api/device/metrics`, and `/api/stats/summary` — everything this integration polls, nothing else.

## 2. Install the integration files on Home Assistant

The integration needs to land at `<ha-config>/custom_components/meshpoint/` — `<ha-config>` is the folder containing your `configuration.yaml`, not this repo. How you get files there depends on your HA setup; pick whichever you have:

- **File editor / Studio Code Server add-on** (HA OS/Supervised) — open the add-on from the sidebar, create the folder `custom_components/meshpoint` at the root (same level as `configuration.yaml`), and upload or paste in every file from this repo's `homeassistant/custom_components/meshpoint/` (including the `translations/` subfolder)
- **Samba share add-on** — mount it from your Mac/PC, copy `homeassistant/custom_components/meshpoint` straight into `\\<ha-ip>\config\custom_components\`
- **scp / SSH** (Container or Core installs) — `scp -r homeassistant/custom_components/meshpoint user@ha-host:/path/to/config/custom_components/`

**Verify before restarting** — the folder should look like:
```
<ha-config>/custom_components/meshpoint/__init__.py
<ha-config>/custom_components/meshpoint/manifest.json
<ha-config>/custom_components/meshpoint/config_flow.py
<ha-config>/custom_components/meshpoint/coordinator.py
<ha-config>/custom_components/meshpoint/sensor.py
<ha-config>/custom_components/meshpoint/metric_meta.py
<ha-config>/custom_components/meshpoint/prometheus.py
<ha-config>/custom_components/meshpoint/json_flatten.py
<ha-config>/custom_components/meshpoint/const.py
<ha-config>/custom_components/meshpoint/strings.json
<ha-config>/custom_components/meshpoint/translations/en.json
```
A common mistake is copying the whole `homeassistant/` folder from this repo (preserving its own `custom_components/meshpoint/...` nesting) instead of just its *contents* — check the paths above match exactly, no extra nesting.

Then: **restart Home Assistant** (Settings → System → Restart).

## 3. Add the integration

**Settings → Devices & Services → + Add Integration → search "Meshpoint"**

- Host/IP of the Meshpoint gateway
- Port (default `8080`)
- The API key from step 1 (leave blank if "Require authentication" is off)

It validates by actually polling `/metrics` before saving — a wrong host or key is caught immediately with a clear error, not a silently-broken device.

Once added, **Settings → Devices & Services → Meshpoint** shows every sensor on one device page.

### HACS instead of manual?

This integration lives in a subdirectory of the main Meshpoint repo rather than its own repo. Adding `https://github.com/javastraat/meshpoint` as a HACS custom repository (category "Integration") may not pick up the subdirectory correctly — manual installation above is the reliable path for now.

## 4. Install the Lovelace cards (optional)

`www/meshpoint-card.js` is one self-contained file (no build step, no framework) that registers **four** card types — with ~140 entities across the three polled endpoints, one card became an unreadable wall of tiles, so it's split by concern instead:

| Card type | Shows |
|---|---|
| `custom:meshpoint-card` | Status — online, node count, uptime, packet rate, protocol split, signal, relay. The at-a-glance one. |
| `custom:meshpoint-health-card` | Host health, plain tiles — CPU, memory, disk, temperature, fan. |
| `custom:meshpoint-host-gauges-card` | Host health, same data as above but as color-coded SVG gauges (green/amber/red by severity) with icons — CPU/Memory/Temperature as rings, Disk as a filled used/free pie. The fancy one. |
| `custom:meshpoint-insights-card` | Insights — best signal ever, farthest contact, node role distribution. |

Each pulls in only the entities that belong to it; anything not yet in its lookup table still shows up in a "More" grid on the right card, grouped by source — so a metric the integration surfaces later never gets silently dropped (the gauges card doesn't have a "More" grid — it's a fixed set of gauges by design, uncurated host metrics still show up on the plain health card). Raw hardware-model codes and the packet-type breakdown are deliberately left out of all four (not meaningful as tiles; still available as plain entities if you want to build your own).

1. Copy `www/meshpoint-card.js` into `<ha-config>/www/meshpoint-card.js` — same methods as step 2 above (File editor, Samba, scp). It must land directly in `www/`, not a subfolder — `/local/` maps to that exact directory.
2. **Verify it's actually being served** before touching Lovelace at all:
   ```
   curl http://<ha-ip>:8123/local/meshpoint-card.js
   ```
   You should see the real JS source. A 404 here means the file isn't where HA expects it — fix that first, nothing downstream will work otherwise.
3. **Settings → Dashboards → ⋮ → Resources → + Add Resource**
   - URL: `/local/meshpoint-card.js`
   - Resource type: **JavaScript Module**
4. Edit any dashboard → Add Card → search "Meshpoint" (all four show up), or add manually as YAML — swap `type` for whichever of the four you want:
   ```yaml
   type: custom:meshpoint-card
   entity: sensor.meshpoint_<...>_uptime
   ```
   Any one Meshpoint sensor works for `entity`, on any of the four card types — find one via **Developer Tools → States**, filter "meshpoint", copy any entity ID. Each card looks up its sibling entities from the same device automatically. (Or use `device_id: <id>` instead — that ID is the last segment of the device page's URL.) Add multiple as separate cards if you want everything (pick either health card, not usually both).

No visual card editor yet — YAML config only for this first version. Updating an already-installed `meshpoint-card.js` to a newer version needs a Python-style restart-free refresh from the browser (it's just a static file), but the JS resource can be cached hard by the browser — if a change doesn't seem to take effect, see the cache troubleshooting below before assuming something's broken.

## Troubleshooting

### "icon not available" in the Add Integration picker

Cosmetic only, not a bug. Home Assistant's brand icons come from the centralized [home-assistant/brands](https://github.com/home-assistant/brands) repo, looked up by domain name — a custom integration can't bundle its own icon for that specific screen. Assets are staged at `homeassistant/brands/meshpoint/` in this repo, ready for submission whenever someone gets around to the PR; until then it's just a gray placeholder, everything still works.

### Config flow fails immediately

The error tells you which:
- **"Could not reach Meshpoint at that address"** — wrong host/port, or `/metrics` isn't reachable from HA over the network (firewall, wrong subnet)
- **"Meshpoint rejected the API key"** — key was revoked, mistyped, or belongs to a different Meshpoint
- **"/metrics endpoint is disabled"** — reachable, but Configuration → Metrics → "Enable /metrics endpoint" is off on the Meshpoint side

### Card shows "Custom element doesn't exist: meshpoint-card" / "Custom element not found"

Work through these in order — each rules out a layer:

1. **Confirm the file is actually served**: `curl http://<ha-ip>:8123/local/meshpoint-card.js` from any machine. A 404 means the file isn't at `<ha-config>/www/meshpoint-card.js` — go back to step 4.1 above and check for extra nesting (`www/homeassistant/www/...` is a common mistake if the whole repo folder got copied instead of just its contents).
2. **If curl returns 200 but the browser still fails** — this is a browser caching problem, not a real error. Confirmed on Chrome specifically taking real effort to shake loose:
   - A plain hard-refresh (Cmd/Ctrl+Shift+R) is usually **not enough** — Home Assistant's frontend is a PWA with a service worker that can keep serving a cached 404 independently of normal browser cache.
   - Clearing all site data (`chrome://settings/content/all` → find the HA host → Delete) is **also sometimes not enough**.
   - What reliably works: DevTools (F12) → **Network** tab → check **"Disable cache"** → also check Application → Service Workers → **"Bypass for network"** if present → then hard-reload with DevTools still open.
3. **Works in Incognito/Private browsing but not your normal profile, even after the above?** That's the signature of a browser extension (ad blocker, privacy/script blocker) interfering — incognito runs with extensions off by default. Try `chrome://extensions` → disable all → reload; re-enable one at a time to find the culprit.
4. Confirmed working across Chrome, Safari, and iOS Safari using this integration in practice — if none of the above resolves it, check the Console tab (F12) for the actual failed request and paste the error.

## What it does not do

- No per-node or per-contact sensors (Meshpoint can track thousands of mesh nodes; this integration reports counts and rates, not one entity per node)
- No control of Meshpoint or the mesh (read-only, matches the API key's scope — it can reach three status routes, `/metrics` + `/api/device/metrics` + `/api/stats/summary`, and nothing that mutates config, controls the mesh, or reads message/node content)
- No messaging, map upload, or radio configuration — that's Meshpoint's own dashboard

## Development

Pure-Python parsing logic (`prometheus.py` for `/metrics`, `json_flatten.py` for the two JSON endpoints) has no Home Assistant imports and can be unit tested standalone:

```bash
python3 -m pytest homeassistant/tests/
```
