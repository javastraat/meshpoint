# Upstream sync with KMX415/meshpoint

Keeps track of what KMX (upstream, `KMX415/meshpoint`) has that our fork (`javastraat/meshpoint`) doesn't.
Earlier rounds (up to 2026-08-13): [memory/upstream_sync_todo.md](memory/upstream_sync_todo.md).

Checked: **2026-11-26** against `upstream/main` at `4e78804d` (v0.8.0 release prep).

## Why GitHub says "100+ behind"

- `merge.sh` / `rebase.sh` run `git merge -s ours upstream/main`. That marks upstream as merged but takes **none** of its
  code. It hides the gap: after such a merge GitHub shows 0 behind while nothing was ported.
  **Don't run `merge.sh` again until the items below are handled**, or this list loses its reference point.
- Since the last such merge (2026-09-13, `918e3fc9`) upstream has **85 commits + 17 merges**. The WisMesh branch
  (May-June) was merged into their main only now, so it appears here too.
- Also 3 commits from 2026-08-14 to 09-13 that the `-s ours` merges skipped: 2 we have, 1 is the MQTT privacy commit,
  which we also have.
- The forks differ too much for cherry-picks (only 6 of 88 apply cleanly). Port by hand, the way the earlier round
  did: read the full diff, compare with our code, write it in our style, add a test.

How each item was checked: does the patch apply (or apply in reverse); how many of its added lines are already in our
files; does the feature exist under a different name in our code or history. A "❓" still needs a full-diff look.

Legend: ⬜ to do · ❓ check first · ✅ have it (theirs or our own version) · ⏭️ skip

## Work list (in order, one at a time)

Per item: read `git show <hash>`, compare with our file(s), port in our style, adapt their test, a line in
`docs/CHANGELOG.md`, tick it here, commit. **Pi** = needs a check on the real device after the commit.
Size = lines upstream changed (code + tests). Work on a branch `upstream-sync`.

### A. Warm-up: small, no radio risk

- [x] **1. `536a9149` Received coding rate** (S, 4 + test 77). Received packets show the wrong coding rate: the
      concentrator source never fills `coding_rate`. Add a map of the HAL's `pkt.coderate` (1-4 → 4/5-4/8).
      `src/capture/concentrator_source.py`. Pi: packet modal shows 4/5 etc.
      Follow-up `51710121`: packets loaded from the database showed the "4/8" default; now no CR (not stored).
  - [ ] **Recheck later (26-11):** with both commits on the COTX and meshpoint restarted, a **live** LongFast packet
        must show `CR 4/5`. On 26-11 nearby Meshpoints (-18 to -36 dBm, relay `0xfb`) still showed `CR 4/8`, probably
        database packets before `51710121`. The chain checks out (Meshtastic LongFast 4/5, our TX 4/5, HAL 1→4/5,
        ctypes struct = `lgw_pkt_rx_s`). Still 4/8 live? Log the raw `pkt.coderate` and look in `journalctl`.
  - [ ] Idea: store the coding rate in the packets table (new column), so reloaded packets and the Meshtastic page
        show it too.
- [x] **2. `06af14ba` MQTT reception time** (S, 2 + test 46). Meshtastic MQTT packets get the time we received them
      (`rx_time`), not "now". `src/relay/mqtt_formatter.py`. Applies cleanly.
- [x] **3. `d870125f` MQTT signal test** (S, test 80 only). Test for partial RSSI/SNR in MQTT. Applies cleanly.
      → Skipped 26-11: our RSSI/SNR are never None, so the test guards nothing here.
- [x] **4. `1b2c8ff5` Web terminal cleanup** (S-M, 81 + test 118). After `exit` in the web terminal the shell process
      is cleaned up properly. `src/api/terminal/pty_session.py`. Applies cleanly. Pi: open terminal, `exit`, no leftovers.
- [x] **5. `bc5b810c` python-multipart** (S, 1 line). Firmware upload (FormData) needs `python-multipart>=0.0.9`;
      it's missing from our `requirements.txt`.
      → Not needed yet (26-11): nothing of ours uses `UploadFile`/`Form` (backup restore reads the raw body). Add it
        together with item 31 (nRF DFU flash), whose firmware upload is what needs it.
- [x] **6. `5ff1ec6a` Espressif USB rule on old installs** (S, 15 + test 94). We already install the tight rule
      (`0660`, `dialout`), but an old install keeps the world-writable `0666` rule. Port their `post_update.sh` part:
      replace the old rule only if it's exactly the old one, and add `meshpoint` to `dialout`.
      → Done 26-11: we had our own migration (`273ffdee`); now as upstream: only the exact old rule is replaced
        (an operator's own rule stays), and `meshpoint` is put in `dialout` first. `install.sh` + `post_update.sh`.
- [x] **7. `d0074db3` Short reconnect log lines** (S, 9 + test 105). Expected Meshradar reconnect failures get one
      short line instead of a traceback. `src/api/upstream_client.py`. 70% already in: finish it.
      → Already have it (26-11): same handler in `upstream_client.py:140`.
- [x] **8. `d8db1301` Bound plugin source revision lookups** (S, 4 + test 20). Large imports don't hang on revision
      lookups. `src/plugins/sources.py`: check that ours has the same weak spot first.
      → Already have it (26-11): ours uses `commits?sha=…&per_page=1`.

### B. Radio and concentrator (our COTX gateway): one per session, Pi test after each

- [x] **9. `fcacc92b` RX preamble on every start** (M, 54 + test 96). Set the service modem's RX preamble at every
      start and read it back. New `src/hal/sx1302_preamble.py`, hook in `sx1302_wrapper.py`. Pi: log shows the
      preamble verified after restart.
      → Done 26-11, with one change: a failed set/read-back logs an error and keeps RX on the HAL default (8)
        instead of stopping the concentrator. Test as unittest (`tests/test_service_preamble.py`).
        COTX 26-11 19:20: `RX preamble verified: 16 symbols` after start; 46 HAL tests OK on the Pi.
  - [ ] **Recheck later:** Meshtastic packets per hour before (until 26-11 19:20) vs after, on the COTX:
        `journalctl -u meshpoint --since … --until … | grep -c 'Meshtastic packet'`. About equal or more = good.
- [x] **10. `027899ed` Receive iterator survives a restart** (M, 29 + test 95). After a concentrator restart the
      receive loop keeps running instead of silently stopping. `src/capture/concentrator_source.py`. Pi: restart
      the radio from the dashboard, packets keep coming.
      → Done 26-11: confirmed bug here too (only caller: Dashboard "Restart concentrator"). Upstream's full test file.
- [ ] **11. `e9286d84` HAL access and TX completion** (M-L, 145 + test 182). All HAL calls go through one lock,
      and a transmit waits until the radio is done before RX resumes. New `src/hal/sx1302_access.py`, changes in
      `sx1302_wrapper.py` and `src/transmit/tx_service.py`. We have a `_hal_lock` already: compare carefully.
      Pi: send messages while traffic comes in, no lost packets or hangs.
- [x] **12. `f4d19492` Own Meshtastic packets and relay identity** (S-M, 23 + test 40). The relay doesn't relay what
      it sent itself, and relayed packets carry our node ID as relay node. `src/relay/relay_manager.py`,
      `tx_service.py`. Applies cleanly. Pi: relay on, no echoes of our own packets.
      → Done 26-11: applied as-is (our files matched upstream's pre-change versions).
  - [ ] **Live check later:** unit tests OK on the COTX (26-11), but it only hears packets of -19 to -46 dBm, all
        above `max_relay_rssi` (-50), so nothing is relayed there. Where a Meshpoint hears distant nodes: `RELAY [`
        lines in the log, none with its own ID, and other nodes show its last ID byte as relay byte.
- [x] **13. `ebbf6eb3` Gateway detection on a fresh install** (M, 93 + tests 179). The setup wizard probes the HAL
      version with a time limit instead of hanging. `src/cli/hardware_detect.py`, `hardware_probe.py`,
      `setup_wizard.py`. Pi: only testable on a fresh SD card; otherwise unit tests.
      → Skipped 26-11 (Einstein's choice): it fixes upstream's chip probe from `de78139d` (WisMesh work), which we
        don't have; our wizard only checks SPI + libloragw. Taking the probe would be a new feature.
- [x] **14. `553bdd83` Transmit settings save** (S, 30 + test 62). Saving Configuration → Transmit finishes properly
      (button state, message). `frontend/js/configuration/transmit_card.js`.
      → Already have it, closed 26-11 (Einstein's OK): upstream's fix was a try/catch around the save request. Our
        shared `_request()` (`configuration_panel.js`) catches network and HTTP errors for every card and returns
        null, and the card then shows "Transmit save failed.". We keep our relay fields (upstream removed theirs).

### C. Messages and channels

- [ ] **15. `121c2d3a` Keep received channel numbers** (S, 7 + test 37). A received message keeps its channel
      index. `src/api/server.py`.
- [ ] **16. `ffea55fd` Native channel routing and acknowledgements** (M, 41 + test 92). Replies go out on the right
      channel; Meshtastic ACKs aren't lost. `src/api/routes/messages.py`, `server.py`, `src/decode/meshtastic_decoder.py`
      (skip their `PIMESH.md`).
- [ ] **17. `8ba70630` MQTT topic preview and LongTurbo** (M, 59 + tests 106). The MQTT settings preview shows the
      right topic; the LongTurbo preset resolves to the right channel. `mqtt_card.js`, `mqtt_config_routes.py`,
      `channel_resolver.py`, `mqtt_formatter.py`, `mqtt_publisher.py`.
- [ ] **18. `4439c2a8` MeshCore contact positions to Meshradar** (M, 120 + tests 155). Positions of MeshCore contacts
      are stored on the node and sent upstream. New `src/models/meshcore_position.py`, `node_repository.py`,
      `upstream_client.py`, `coordinator.py`, `meshcore_event_adapter.py`.
- [ ] **19. `5a9383d2` Registered-pin position privacy** (M, 35 + tests 123). With "registered pin" chosen, the
      broadcaster sends the pin, never the live GPS. We have the option in `mesh_position_resolver.py` and
      `gps_card.js`: check where ours still leaks. Also `broadcast_interval.py`, `position_broadcaster.py`.

### D. Dashboard and status

- [x] **20. `4d4b22df` CPU sampled in the background** (M, 70 + test 94). Ours calls `psutil.cpu_percent(interval=0.5)`
      per request, which blocks 0.5 s each time. New `src/system_metrics.py` sampler, used by `system_metrics.py`,
      `server.py`, `src/remote/executors.py`.
      → Done 26-11: as upstream, plus a guard in `meshpoint report` (None while warming up crashed its health check).
- [x] **21. `a16253be` Status before data on load** (S, 34 + test 62). The dashboard connects the websocket first, so
      it doesn't hang on "connecting…" while data loads. `frontend/js/app.js`, `websocket_client.js`.
      → Already have it, closed 26-11 (Einstein's OK): upstream adapted it from our commit 93c4d4f (WS connects first).
- [x] **22. `3fbfa9fa` Meshtastic chip only when configured** (S, 8 + tests 50). The top bar shows the Meshtastic
      chip only if a Meshtastic source is configured. `topbar_meshtastic_chip.js`, `topbar_controller.js`.
      → Already have it, closed 26-11 (Einstein's OK): upstream adapted it from our commits 7986b18e + f9dda48d.
- [x] **23. `23a5fe7e` MeshCore capture status apart from TX** (S, 23 + tests 66). MeshCore USB shows "capturing"
      even when TX is off. `meshcore_card.js`, `radio_companion_card.js`, `topbar_meshcore_chip.js`, `config_routes.py`.
      → Done 26-11: our top bar already used per-companion capture status; the two cards now use the same
        (`mc.companions`), so no new server field. Node test `tests/frontend_meshcore_capture_status.test.js`.

### E. Meshtastic USB recovery

- [ ] **24. `93866842` Reconnect after Set Preset reboot** (M-L, 215 + test 75). After Set Preset the node reboots;
      Meshpoint now waits and reconnects. New `src/capture/serial_link_watch.py`, `serial_source.py`. Pi: Set
      Preset on a USB Meshtastic node.
- [ ] **25. `459c4d7c` REBOOTING vs RECONNECTING** (M, 210 + tests 30). Shows which of the two is happening, in
      Configuration → Serial and the top bar. Needs 24.

### F. MeshCore features

- [ ] **26. `6ea8de00` Shared MeshCore TCP and verified radio commands** (M, 78 + test 38). MeshCore over TCP shared
      between capture and TX; radio commands serialized and checked. `meshcore_usb_source.py`, `meshcore_tx_client.py`,
      new `meshcore_channel_sync.py`.
- [ ] **27. `fc15bc36` + `cad3c4a1` MeshCore RF metadata and hops** (M, 137 + tests 690). MeshCore packets get RSSI,
      SNR, SF/BW and hop count in the feed and packet modal. `meshcore_usb_source.py`, `meshcore_event_adapter.py`,
      `packet_repository.py`, `packet_detail_modal.js`, `simple_packet_feed.js`.
- [ ] **28. `e8c4c6e1` MeshCore send feedback** (L, 387 + tests 208). A sent message shows "heard repeated by N",
      kept in the database. New `src/transmit/meshcore_repeats.py`, `message_repository.py` (+ DB column),
      `messaging_chat.js`.
- [ ] **29. `a451d1e2` MeshCore heard-path popover** (M-L, 301 + tests 88). Click the feedback to see which
      repeaters heard it. Needs 28.

### G. Dashboard presets

- [ ] **30. `829a17e4` + `45adf5c5` Preset chips and filter** (L, 450 + tests). LF/MF/LT/MC chips on nodes and
      packets, and a "show only" preset filter, pills appear once a preset is heard. New `modem_preset_label.js`,
      `radio_view_filter.js`, `packet_feed.css`; `node_map.js`, `node_cards.js`, `simple_packet_feed.js`.

### H. Big one

- [ ] **31. `6011f846` nRF DFU flash** (XL, ~1900 + test 160). Flash nRF52 MeshCore/Meshtastic companions from the
      dashboard (serial DFU, or UF2 volume), with firmware catalogs and upload. New `src/api/firmware/*` (8 files),
      `firmware_nrf_panel.js`, big rewrite of both firmware routes and cards. Ours: drag-and-drop note only.
      Plan it as a project of its own.

### I. Docs

- [ ] **32. `486a2d2e` + `44262226` + `ba50853f` Heltec HT-M2808 guide** (applies cleanly) and links in README,
      HARDWARE-MATRIX.
- [ ] **33. `c7bf59f4` Bobcat G285 community setup** in our `BOBCAT-300.md` and HARDWARE-MATRIX.
- [ ] **34. `d476e296` Hardware and accessory links** in README.
- [ ] **35. `72a9c2cd` RAK6421 HAT store URL**.

### J. Decide first (not in the queue)

- [ ] **36. Reticulum interface discovery** `a890b318`: idea for our Reticulum plugin.
- [ ] **37. Their plugin repo and dashboard access controls** `622ce563`, `b91d994b`.
- [ ] **38. WisMesh Node / meshtasticd** (15 commits, section 5): only with that hardware.
- [ ] **39. PiMesh** (4 commits, section 5): only with that hardware.

The tables below are the full inventory (incl. what we already have and what we skip).

## 1. Radio, concentrator and relay fixes (high: our COTX gateway runs on this)

| | Commit | What | Notes |
|---|---|---|---|
| ⬜ | `536a9149` | Show the real received coding rate (#163) | Tiny. `concentrator_source.py` doesn't set `coding_rate` from `pkt.coderate` |
| ❓ | `e9286d84` | Serialize native HAL access and wait for TX completion (#181) | We have a `_hal_lock` in `sx1302_wrapper.py`; they add `sx1302_access.py` + TX wait in `tx_service.py` |
| ⬜ | `fcacc92b` | Set and verify the service-modem RX preamble on every start (#179) | New `sx1302_preamble.py` |
| ❓ | `027899ed` | Keep the concentrator receive iterator alive during a restart (#176) | 24% already similar |
| ⬜ | `f4d19492` | Skip our own Meshtastic packets, stamp the native relay identity (#175, #182) | Applies cleanly |
| ⬜ | `ebbf6eb3` | Fresh gateway detection with a bounded HAL version probe (#178) | Setup wizard / `hardware_probe.py` |
| ⬜ | `553bdd83` | Transmit settings save completion (#177) | `transmit_card.js` |
| ⬜ | `ffea55fd` | Native channel routing, keep Meshtastic acknowledgements | |
| ⬜ | `121c2d3a` | Keep received message channel numbers | |
| ⬜ | `8ba70630` | MQTT previews and LongTurbo channel resolution (#146/#147) | |
| ⬜ | `06af14ba` | Keep reception timestamps in Meshtastic MQTT packets | Applies cleanly |
| ⬜ | `d870125f` | Test only: MQTT partial signal metric | Applies cleanly |
| ⬜ | `4439c2a8` | MeshCore contact positions reaching Meshradar (#136) | |
| ❓ | `5a9383d2` | Honor registered-pin mesh position privacy | We have `registered pin` in `mesh_position_resolver.py`; compare |
| ⏭️ | `408f9ea2` | Privacy validation notes (docs to the above) | |

## 2. System and security (high, mostly small)

| | Commit | What | Notes |
|---|---|---|---|
| ⬜ | `4d4b22df` | Sample host CPU in the background (#149/#150) | Ours calls `psutil.cpu_percent(interval=0.5)` per request: 0.5 s blocked each time |
| ⬜ | `5ff1ec6a` | Restrict Espressif USB access to the dialout group | We install the tight rule; missing: upgrading the old `0666` rule in `post_update.sh` |
| ⬜ | `bc5b810c` | Pin `python-multipart` for firmware upload | Missing from our `requirements.txt` |
| ⬜ | `1b2c8ff5` | Web terminal cleanup after shell EOF (#166) | Applies cleanly |
| ❓ | `d0074db3` | Keep expected upstream reconnect failures short in the log | 70% already in |
| ❓ | `3ca92469` | Harden `install.sh` for dashboard Apply on upgrade | 46% in |

## 3. Features: MeshCore and Meshtastic USB (medium)

| | Commit | What | Notes |
|---|---|---|---|
| ⬜ | `6011f846` | nRF DFU flash for MeshCore and Meshtastic companions | Big (2000 lines). Ours only says "drag-and-drop the .uf2" for nRF52 |
| ⬜ | `93866842` + `459c4d7c` | Reconnect Meshtastic USB after Set Preset reboots it; show REBOOTING vs RECONNECTING | |
| ⬜ | `829a17e4` + `45adf5c5` | LF/MF/LT/MC preset chips and a show-only preset filter on the dashboard | |
| ⬜ | `e8c4c6e1` | Persistent MeshCore send feedback (#151) | |
| ⬜ | `a451d1e2` | MeshCore heard-path popover (#152) | |
| ⬜ | `fc15bc36` + `cad3c4a1` | MeshCore packet RF metadata and received hops | |
| ⬜ | `6ea8de00` | Shared MeshCore TCP transport, verified serialized radio commands | |
| ⬜ | `23a5fe7e` | MeshCore USB capture status independent of TX | |
| ⬜ | `3fbfa9fa` | Show Meshtastic status only for configured capture sources | |
| ⬜ | `a16253be` | Connect dashboard status before the initial data load | |
| ❓ | `a890b318` / `8e349c91` | Opt-in Reticulum interface discovery and operator contacts | Our Reticulum is a plugin; take the idea if wanted |
| ⏭️ | `58e4e9b1`, `4ad2903f` | Docs/wording: USB radios are "nodes", not "sticks" | Optional |

## 4. Plugin system (compare, don't port)

We built our own plugin system (manifest, dependencies with cascading disable, sources, batch updates, `meshpoint-plugins`
repo). Theirs is a different implementation. Only worth looking at for ideas and compatibility.

| | Commit | What | Notes |
|---|---|---|---|
| ❓ | `b91d994b` | Optional apps, themes and dashboard access controls (34 000 lines) | Look at "dashboard access controls"; the rest we have our own way |
| ✅ | `ede788c8`, `6b06ec5d` | Plugin source picker, dependencies + cascading disable | Our own (`5ec7fa52`, `6e9f7dfe`, `49a370b6`) |
| ❓ | `622ce563` | Their official plugin repository | Do we want their repo as a source next to ours? |
| ❓ | `d8db1301` | Bound plugin source revision lookups for big imports | Possibly useful for our sources |
| ⏭️ | `471a81da`, `dfe6bcf5` | Their plugin docs and release plan | |
| ✅ | `06730b06` | Map tile sources from the dashboard | Ours: `map_tile_source.js`, `dashboard.map_tile_url` (`7d9b3434`) |

## 5. Hardware we may not have (decide first)

| | Commit(s) | What | Notes |
|---|---|---|---|
| ❓ | `de78139d` `cb5495e1` `43cd37aa` `f82898ef` `95247426` `349c56da` `74305f1d` `e043fb4a` `5bca93d2` `387f08be` `cb38865f` `9124ab55` `90d159c8` `9f9da27f` `c44642ea` | **WisMesh Node / RAK6421 HAT** via meshtasticd (bridge, install, dashboard control) | ~5000 lines. Only if we use that hardware. We do have `docs/WISMESH-NODE.md`; check what it covers |
| ❓ | `cdb2d235` `48942ef2` `529577dc` `841ff7a5` | **PiMesh** (device roles, forwarding, MeshCore config) | Only if we use PiMesh |

## 6. Docs (low, copy what's useful)

| | Commit | What |
|---|---|---|
| ⬜ | `486a2d2e` + `44262226` | Heltec HT-M2808 installation guide (applies cleanly) |
| ⬜ | `c7bf59f4` | Bobcat G285 community setup (we have `BOBCAT-300.md`) |
| ⬜ | `d476e296` | Hardware and accessory links |
| ⬜ | `ba50853f` | GPIO reference SX1301 → SX1302 |
| ⬜ | `72a9c2cd` | RAK6421 HAT store URL |
| ⏭️ | `e311f407` | README: installation leads with concentrator gateways (our README differs) |

## 7. Already have (no action)

| Commit | What | How |
|---|---|---|
| `e29ba96d` / `3049d109` | MQTT broadcast and location privacy | Identical |
| `9d47ffc5` | Public channel messages showing sender "Broadcast" | 95% same |
| `65346b36`, `f1d96a24` | Dashboard Apply / `apply_finish` fixes (v0.7.5.1) | ~90% same |
| `211ea1c1` | Reject special archive members on backup restore | `_reject_non_regular_members` |
| `635a4884` | Map tiles off watermarked CARTO | `bd1cec4c`, `59c01da1` |
| `cea01429` | Bobcat capture YAML SPI settings | 100% |
| `b03692b4` | Honor configured concentrator reset GPIO | Our own `85d5b175` |
| `34a3a6f2`, `e943a22d` | COTX X3 and Pisces P100 docs | Our own (`2f7c8013`, `6bfcda48`) |
| `7465c113` | meshtasticd IPC spike doc | 75% |

## 8. Skip

Release and CI housekeeping: `78082ba2` (v0.8.0 metadata), `3907348a` (changelog), `4f62d644` (RC checks),
`cfda01d8` (session drafts), and all merge commits.

## Next round

1. `git fetch upstream`
2. `git log --no-merges --reverse --format='%h %ad %s' --date=short 4e78804d..upstream/main`: only what's new since this check.
3. Add the new commits here, update "Checked" at the top.
