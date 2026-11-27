# Upstream sync with KMX415/meshpoint

Keeps track of what KMX (upstream, `KMX415/meshpoint`) has that our fork (`javastraat/meshpoint`) doesn't.
Earlier rounds (up to 2026-08-13): [memory/upstream_sync_todo.md](memory/upstream_sync_todo.md).

Checked: **2026-11-26** against `upstream/main` at `4e78804d` (v0.8.0 release prep) and their other branches
(`feat/v0.8.1` is one commit ahead of main: item 48).

**Status 27-11:** done 1-10, 12-15, 17-29, 32-36, 40-47, 49-51 (42 of the 50, plus 51). Open: 11, 16, 30, 31, 37c/e/g,
38, 39, 41a (Pi test waits for an RTL-SDR dongle), 48 (someone else's), the rechecks marked "Recheck later", then the
0.8.2 bump.

**Decision 26-11 (Einstein): we want everything they have.** Nothing is "skip" or "decide first" any more, unless it
is only upstream's own housekeeping (release metadata, CI, merge commits) or code that is already ours. That
includes WisMesh Node / meshtasticd, PiMesh, the public view, p25 and their plugin repo. Items we closed earlier as
"skipped" because they only made sense with that hardware (13, and the tests in 3) are open again: see section K.

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

Test note (26-11): `rakv21-meshpoint` has a newer starlette whose `TestClient` needs `httpx2` (not installed), so tests
using `fastapi.testclient` (e.g. `test_gps_routes`) fail to import there; run those on the COTX, or install `httpx2`
in the venv. Meshpoint itself doesn't need it.

Per item: read `git show <hash>`, compare with our file(s), port in our style, adapt their test, a line in
`docs/CHANGELOG.md`, tick it here (only after Einstein's OK, once the Pi test passed), Einstein commits.
**Pi** = needs a check on the real device after the commit.
Size = lines upstream changed (code + tests). Work on a branch `upstream-sync`.

### A. Warm-up: small, no radio risk

- [x] **1. `536a9149` Received coding rate** (S, 4 + test 77). Received packets show the wrong coding rate: the
      concentrator source never fills `coding_rate`. Add a map of the HAL's `pkt.coderate` (1-4 → 4/5-4/8).
      `src/capture/concentrator_source.py`. Pi: packet modal shows 4/5 etc.
      Follow-up `51710121`: packets loaded from the database showed the "4/8" default; now no CR (not stored).
  - [x] **Recheck done 26-11 21:12:** live LongFast packet (amsterdamgw1, relay 0x8f) shows `CR 4/5` on the dashboard.
        Earlier: a **live** LongFast packet
        must show `CR 4/5`. On 26-11 nearby Meshpoints (-18 to -36 dBm, relay `0xfb`) still showed `CR 4/8`, probably
        database packets before `51710121`. The chain checks out (Meshtastic LongFast 4/5, our TX 4/5, HAL 1→4/5,
        ctypes struct = `lgw_pkt_rx_s`). Still 4/8 live? Log the raw `pkt.coderate` and look in `journalctl`.
  - [ ] Idea: store the coding rate in the packets table (new column), so reloaded packets and the Meshtastic page
        show it too.
- [x] **2. `06af14ba` MQTT reception time** (S, 2 + test 46). Meshtastic MQTT packets get the time we received them
      (`rx_time`), not "now". `src/relay/mqtt_formatter.py`. Applies cleanly.
- [x] **3. `d870125f` MQTT signal test** (S, test 80 only). Test for partial RSSI/SNR in MQTT. Applies cleanly.
      → Skipped 26-11: our RSSI/SNR are never None, so the test guards nothing here.
        **Reopened 26-11:** take it with `95247426` (unknown RSSI/SNR) in item 38.
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
        **Reopened 26-11 (everything is wanted): do it together with item 38** (`de78139d` brings the probe).
- [x] **14. `553bdd83` Transmit settings save** (S, 30 + test 62). Saving Configuration → Transmit finishes properly
      (button state, message). `frontend/js/configuration/transmit_card.js`.
      → Already have it, closed 26-11 (Einstein's OK): upstream's fix was a try/catch around the save request. Our
        shared `_request()` (`configuration_panel.js`) catches network and HTTP errors for every card and returns
        null, and the card then shows "Transmit save failed.". We keep our relay fields (upstream removed theirs).

### C. Messages and channels

- [x] **15. `121c2d3a` Keep received channel numbers** (S, 7 + test 37). A received message keeps its channel
      index. `src/api/server.py`.
      → Done 26-11: `message_channel` in `_setup_message_interception`, passed to `save_received`. Test
        `tests/test_received_message_channel.py` (unittest, not upstream's pytest).
  - [ ] **Recheck later:** a new channel message received on the COTX is stored with its channel number (DB rows
        from before 26-11 still show 0; `grep` showed the fix is on the Pi).
- [ ] **16. `ffea55fd` Native channel routing and acknowledgements** (M, 41 + test 92). Replies go out on the right
      channel; Meshtastic ACKs aren't lost. `src/api/routes/messages.py`, `server.py`, `src/decode/meshtastic_decoder.py`
      (skip their `PIMESH.md`).
      → Checked 26-11: everything except the `channel=` fix (done in 15) is meshtasticd/PiMesh (API decode of
        `requestId`/routing, `channel_index` from the Phone API, PiMesh channel list). Do it with 38/39.
- [x] **17. `8ba70630` MQTT topic preview and LongTurbo** (M, 59 + tests 106). The MQTT settings preview shows the
      right topic; the LongTurbo preset resolves to the right channel. `mqtt_card.js`, `mqtt_config_routes.py`,
      `channel_resolver.py`, `mqtt_formatter.py`, `mqtt_publisher.py`.
      → Done 26-11: patch applied (resolver, formatter, publisher, config route, MQTT card, tests); CSS by hand;
        frontend test ported to `tests/frontend_mqtt_topic_preview.test.js`.
- [x] **18. `4439c2a8` MeshCore contact positions to Meshradar** (M, 120 + tests 155). Positions of MeshCore contacts
      are stored on the node and sent upstream. New `src/models/meshcore_position.py`, `node_repository.py`,
      `upstream_client.py`, `coordinator.py`, `meshcore_event_adapter.py`.
      → Done 26-11: patch applied for the model, node repository, adapter, coordinator, upstream heartbeat and USB tests;
        contact parser (ours lives in `meshcore_tx_client.get_contacts`, still requires a name) and contact sync by hand.
        Tests ported into `tests/test_meshcore_contact_enrichment.py`.
  - [ ] **Recheck later:** more MeshCore contacts with a position show up on the map / reach Meshradar (few nodes
        with a position so far).
- [x] **19. `5a9383d2` Registered-pin position privacy** (M, 35 + tests 123). With "registered pin" chosen, the
      broadcaster sends the pin, never the live GPS. We have the option in `mesh_position_resolver.py` and
      `gps_card.js`: check where ours still leaks. Also `broadcast_interval.py`, `position_broadcaster.py`.
      → Done 26-11: patch applied (resolver, schedule `mark_attempt`, GPS card, CONFIGURATION.md, tests); default.yaml
        comment by hand; frontend test ported. rakv21 has no `position:` section: on the defaults it now sends
        approximate instead of exact (told Einstein; `location_precision: exact` keeps the old behaviour).

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

- [x] **24. `93866842` Reconnect after Set Preset reboot** (M-L, 215 + test 75). After Set Preset the node reboots;
      Meshpoint now waits and reconnects. New `src/capture/serial_link_watch.py`, `serial_source.py`. Pi: Set
      Preset on a USB Meshtastic node.
      → Done 26-11 in our own `serial_source.py` (upstream split theirs into modules): `connection.lost` + after
        region/preset/bluetooth writes. Test `tests/test_serial_link_drop.py`. COTX has no USB Meshtastic node.
- [x] **25. `459c4d7c` REBOOTING vs RECONNECTING** (M, 210 + tests 30). Shows which of the two is happening, in
      Configuration → Serial and the top bar. Needs 24.
      → Done 26-11 in our own files (patch didn't apply): `link_status()` on the source, 3 fields in the serial status,
        top-bar chip + 1 s polling while busy, live status line in Configuration → Serial (form not re-rendered;
        radio controls of a device that was offline at page load appear after a reload). Node + Python tests.

### F. MeshCore features

- [x] **26. `6ea8de00` Shared MeshCore TCP and verified radio commands** (M, 78 + test 38). MeshCore over TCP shared
      between capture and TX; radio commands serialized and checked. `meshcore_usb_source.py`, `meshcore_tx_client.py`,
      new `meshcore_channel_sync.py`.
      → Done 26-11, all three parts: TCP per companion (local.yaml only, like upstream; preserved by the dashboard save),
        live TX switch for MeshCore (client, every companion, TxService), channel save waits and reads all slots back
        (502 with the reason if not confirmed). Test `tests/test_meshcore_tcp_and_tx_gate.py`.
- [x] **27. `fc15bc36` + `cad3c4a1` MeshCore RF metadata and hops** (M, 137 + tests 690). MeshCore packets get RSSI,
      SNR, SF/BW and hop count in the feed and packet modal. `meshcore_usb_source.py`, `meshcore_event_adapter.py`,
      `packet_repository.py`, `packet_detail_modal.js`, `simple_packet_feed.js`.
      → Done 26-11 in our files: receiver snapshot (incl. CR) at capture, exact-key advert matching (RSSI/SNR + hops in
        `hop_start`, like our MeshCore messages), CR restored from the database. Unmatched adverts still fall back to
        the last RF frame, as upstream. No frontend change needed. Test `tests/test_meshcore_rf_metadata.py`.
- [x] **28. `e8c4c6e1` MeshCore send feedback** (L, 387 + tests 208). A sent message shows "heard repeated by N",
      kept in the database. New `src/transmit/meshcore_repeats.py`, `message_repository.py` (+ DB column),
      `messaging_chat.js`.
      → Done 26-11, adapted to our multi-companion sending: copies of one send share a packet_id and add up
        (`src/transmit/meshcore_repeats.py`), observed in each companion's own event loop (RX log + ACK). Only wired
        when MeshCore capture sources exist. Test `tests/test_meshcore_send_feedback.py` (real AES/HMAC frames).
- [x] **29. `a451d1e2` MeshCore heard-path popover** (M-L, 301 + tests 88). Click the feedback to see which
      repeaters heard it. Needs 28.
      → Done 26-11: paths per copy in the tracker (all companions' copies, first 32), `heard_paths` column,
        `GET /api/messages/{id}/heard-paths`, popover from upstream in our chat. Python + Node tests.

### G. Dashboard presets

- [ ] **30. `829a17e4` + `45adf5c5` Preset chips and filter** (L, 450 + tests). LF/MF/LT/MC chips on nodes and
      packets, and a "show only" preset filter, pills appear once a preset is heard. New `modem_preset_label.js`,
      `radio_view_filter.js`, `packet_feed.css`; `node_map.js`, `node_cards.js`, `simple_packet_feed.js`.
      → 27-11, **30a built** (Einstein: LongMod = "LMd", "LM" stays LocalMesh): `modem_preset_label.js` +
        `radio_view_filter.js` from upstream (plus LMd, an LM entry for protocol localmesh, no chip for pager/LoRaWAN);
        `packet_feed.css` (chips, pills, orange LM); node repository sends `latest_spreading_factor/bandwidth_khz`
        (test); packet table gets a Preset column and `data-preset` per row, the filter hides rows instead of rebuilding
        them (upstream re-renders 200 rows per packet); node cards and map follow the filter, map popup names the
        preset. Test `tests/frontend_preset_chips.test.js`. Pi 27-11 on the COTX: LF and LM filters OK.
      → 27-11, **30b built:** map markers as upstream: one divIcon per node (dot = Meshtastic, diamond = others) with
        the preset chip next to it, green pulse when recent, amber when favourite (`markerMarkup`, `_stampNodeModem`;
        circleMarker/setStyle code gone); marker CSS in `packet_feed.css`. Also upstream's `responsive.css` fix missed
        in 30a: narrow screens hide columns 9-12 (Freq, SF, Hops, Details) so Preset (8) stays. Tests added. Still to
        do: map screenshot.

### H. Big one

- [ ] **31. `6011f846` nRF DFU flash** (XL, ~1900 + test 160). Flash nRF52 MeshCore/Meshtastic companions from the
      dashboard (serial DFU, or UF2 volume), with firmware catalogs and upload. New `src/api/firmware/*` (8 files),
      `firmware_nrf_panel.js`, big rewrite of both firmware routes and cards. Ours: drag-and-drop note only.
      Plan it as a project of its own.
      **When done, also update `docs/USB-NODES.md`** ("Add a Meshtastic USB node", step 1): it now says ESP32 via
      esptool and nRF52 by dragging the `.uf2`; put back upstream's wording "Configuration → Firmware can do that for
      catalog boards (ESP32 family via esptool, nRF via DFU)".

### I. Docs

- [x] **32. `486a2d2e` + `44262226` + `ba50853f` Heltec HT-M2808 guide** (applies cleanly) and links in README,
      HARDWARE-MATRIX.
      → Done 26-11: guide + `ba50853f` fix (SX1302), linked in README and HARDWARE-MATRIX (we have no docs/README.md index).
- [x] **33. `c7bf59f4` Bobcat G285 community setup** in our `BOBCAT-300.md` and HARDWARE-MATRIX.
      → Done 26-11: G285 recipe in BOBCAT-300.md (patch applied), HARDWARE-MATRIX entry rewritten by hand.
- [x] **34. `d476e296` Hardware and accessory links** in README.
      → Done 26-11, option b (Einstein's choice): own table in README, plain manufacturer links checked 26-11 (Heltec
        V3/V4, Seeed kit, Waveshare CM4-IO-BASE-A; RAK store front page because its product page wasn't reachable),
        EU868 variants, no affiliate links; generic accessories without links.
- [x] **35. `72a9c2cd` RAK6421 HAT store URL**.
      → Done 26-11: README link updated; HARDWARE-MATRIX already had the new URL.

### J. Plugins, Reticulum and access (decided 26-11: take it all)

- [x] **36. Reticulum interface discovery** `a890b318` (= `8e349c91`): checked 26-11, we have about 80% of it. Open
      work is in our plugin repo (`meshpoint-plugins/apps/reticulum`), not here.
  - Have: listening (`discover_interfaces`, autoconnect 0), publishing our RNode (`rnode_discoverable`, name, interval,
    lat/lon), reading the heard interfaces (`backend/discovered.py`, `GET /api/reticulum/discovered`, admin-only host).
  - Missing: **operator contact**. A setting `rnode_discovery_lxmf_address` (32 hex, validated, written as
    `discovery_lxmf_address` only when `rnode_discoverable` is on), the address read from the stored interface files, and a
    **Contact operator** button that opens a draft in Messages (sends nothing).
  - Missing: `discovered.py` `_entry()` drops interfaces without a location; theirs lists all (TCP/backbone without
    coordinates).
  - Don't copy: their forced `mode = access_point` for publishing (blocks announce forwarding; we coerce to `gateway`)
    and their "no location" rule (we publish lat/lon on purpose).
  - First check: does our RNS version read and write `discovery_lxmf_address`? (Upstream pinned RNS 1.5.3.)
  → 27-11 (plugin repo): RNS 1.5.4 (COTX) and 1.6.1 both support it. `rnode_discovery_lxmf_address` (settings field +
    "Use this Meshpoint's address", validated to 32 hex, written as `discovery_lxmf_address` only when discoverable;
    `_discoverable_block()` in `write_rnsd_config.py`); `discovered.py` lists entries without a location (lat/lon null,
    map skips them) and carries `operator_lxmf_address`; map popup (reticulum-dashboard) shows the operator and, for
    admins, **Contact operator** (draft in Messages via `composeMessageTo`); detail panel: Operator row, no 0,0 location.
    Tests in `test_config_routes.py`, `test_discovered.py`, `test_write_rnsd_config.py` (fail on the old code).
    reticulum 1.1.5, reticulum-dashboard 1.0.2. Pi test 27-11 on the COTX: block with `discovery_lxmf_address`
    (dry run), nothing published with rmap off, address saved in local.yaml (after a Meshpoint restart).
  - [ ] **Recheck later:** "Contact operator" in the map popup, once a heard interface publishes an operator address.
- [ ] **37. Their plugin repo and dashboard access controls** `622ce563`, `b91d994b`: checked 26-11. Most of it is ours
      already (their commit says it adapts `javastraat/meshpoint`).
  - [x] **37a. Fix: viewer marks a conversation read for everyone.** `POST /api/conversation/{node_id}/read` in
        `src/api/routes/messages.py` has no `require_admin`. It is the only write route without it. Add the dependency
        and a test (a viewer gets 403).
        → Done 26-11: `require_admin` on the read route; test checks every write route in messages.py.
  - [x] **37b. Hardening:** make `require_auth` reject non-GET/HEAD/OPTIONS for the viewer role and add
        `require_session` for `change_password` (`src/api/auth/dependencies.py`, `auth_routes.py`). Then a new write route
        (also in a plugin) is admin-only by default. Reticulum's `/page`, `/disconnect`, `/file` POSTs
        (`nomad_routes.py`) are read-like and handled separately: check them first.
        → Done 26-11 (Einstein chose option b): `require_session` + strict `require_auth`; `change_password` on
          `require_session`. Core already had every protected write on admin (scan). meshpoint-plugins: reticulum
          1.1.4 GET `/page` + `/file` for plain reads (POST stays for forms/identify), `/disconnect` admin;
          reticulum-browser 0.1.1 and reticulum-dashboard 1.0.1 use GET. Plugins first, then core.
  - [ ] **37c. Public view** (decided 26-11: yes). Admin picks pages that anonymous visitors see: dashboard counts,
        stats averages, radio parameters. We have none; `public_radar_routes.py` only feeds the login-page radar. About
        600 lines (`public_view_routes.py`, `public.html`, `public_view.js`, settings form, `update_public_view` in
        `auth_service.py`, `stats_routes.public_snapshot`, tests `test_public_view.py`). Off by default, aggregate
        numbers only (no IDs, positions, payloads), no session issued, no WebSocket access. Review it as an
        unauthenticated surface (rate limit, cache) before enabling.
  - [x] **37d. Viewer UI in Messages:** no `meshpointReadOnly` flag in our frontend, so a viewer still sees compose and
        Send and opening a chat posts "read". Hide compose, delete and Send Now for viewers; skip the read POST
        (`messaging_chat.js`, `messaging_contacts.js`, `viewer_access.js`). Goes with 37a.
        → Done 26-11: `window.meshpointReadOnly` from the identity role (app.js); Messages hides New and delete,
          disables compose, skips the read POST. Config pages needed nothing: our route guard keeps viewers out.
          Node test `tests/frontend_viewer_messages.test.js`.
  - Have, no action: viewer role, terminal off by default (we keep our API toggle + restart), `plugin_sources_enabled`.
  - **Their plugin repo** (`KMX415/meshpoint-plugins`): the catalogs diverged. It is one snapshot of their `apps/`
    (11 plugins); ours has 188 commits and 26 plugins (versions 1.2.0 vs 1.0.0 for most shared ones, reticulum 1.1.3 vs
    1.0.0). Their manifests parse on our core, but their Reticulum imports `src.plugins.runtime` and
    `src.plugins.python_dependencies`, which we don't have, and their plugins drop `setup.sh`/`check.sh`. Don't take
    their updates to shared plugins (ours are newer and have the setup scripts). Take **p25** (0.1.0, experimental) and
    add `KMX415/meshpoint-plugins` as a source preset (37e, 37f).
  - [ ] **37e. p25 plugin** (their `apps/p25`: OP25 adapter, needs `meshpoint-op25` + ffmpeg). Their manifest parses on
        our core, but it may need their runtime (`src.plugins.runtime`, `python_dependencies`). Port it into
        `meshpoint-plugins` with our `setup.sh`/`check.sh`, run it on our core.
  - [x] **37f. Source preset for `KMX415/meshpoint-plugins`** next to ours (`src/plugins/sources.py`,
        `frontend/js/settings/plugin_catalog.js`, `docs/PLUGINS.md`). One line plus docs. Say in the UI which catalog is
        which; their shared plugins are older than ours.
        → Done 26-11: preset in `frontend/data/plugin_sources.json` (ours keeps presets there, not in JS) + PLUGINS.md.
  - [ ] **37g. Take what is better in their versions of the shared plugins.** Per plugin (acars, adsb, dab, p2000,
        pagers, pocsag, radio, rtl433, rtlsdr, reticulum): diff theirs against ours and port real fixes, keep our
        manifest and setup scripts. `reticulum` differs most (~4200 lines): their `managed_service.py`,
        `worker_proxy.py`, `worker_runner.py` (separate worker process), regions (item 41) and discovery (item 36).
- [ ] **38. WisMesh Node / meshtasticd** (15 commits, ~5000 lines, section 5): decided 26-11, we take it. Plan it as a
      project of its own, like item 31, in the order of the commits (platform detection, install, bridge capture, decode,
      region and channel sync, TX, control plane and WisBlock module picker, platform guards). Includes the pieces the
      earlier sections skipped: `ebbf6eb3` (item 13), `9f9da27f` (decoder), `95247426` (unknown RSSI/SNR), `90d159c8`
      (`platform_guards.py`), `3ca92469` (install.sh, item 40). Compare with our `docs/WISMESH-NODE.md` first.
- [ ] **39. PiMesh** (4 commits, section 5): decided 26-11, we take it (`cdb2d235`, `48942ef2`, `529577dc`, `841ff7a5`:
      device roles and forwarding, MeshCore config, docs, upstream credits). Needs `pimesh_*` modules, `openhop_control`
      and the `config/meshtasticd/` presets. Plan after 38; they share the meshtasticd parts.

### K. Found on 26-11 in the full compare (not covered by items 1-39)

- [x] **40. `3ca92469` install.sh hardening** (S). On an upgrade: `dpkg --configure -a` before apt and skip
      `apt-get upgrade`; reuse the existing venv instead of recreating it (ours does `python3 -m venv` every time, line
      ~876, and `apt-get upgrade` runs always, line ~243). Check the venv reuse against a Python version change.
      → 27-11 (Einstein: a, keep `apt-get upgrade`): `dpkg --configure -a` on upgrades in `install.sh` and
        `install-debian.sh`, before the first apt call (also before the upgrade fast path's `apt-get install`, which
        upstream's placement missed). Not taken: skipping `apt-get upgrade` (our Apply doesn't run install.sh), venv
        reuse (breaks on a Python version change). Test `tests/test_install_dpkg_repair.py` (fails on the old scripts).
        Pi test 27-11 on the COTX: unit tests OK; full `install.sh` run: repair before "Updating system packages",
        finished (incl. a new kernel), Meshpoint active, no errors.
- [x] **41. Reticulum regional starting profiles** (M). Upstream's Reticulum fills missing RNode settings from
      `radio.region` (US, EU_868, ANZ, IN, KR, SG_923), has a "Use region starting profile" button, and
      `src/audio/sdr_registry.py` gives the SDR receivers (ACARS, ADS-B, ...) region defaults. Docs: `RETICULUM-REGIONS.md`.
      Tests: `test_reticulum_regions.py`, `test_receiver_regions.py`. Our plugin has no region logic. Adjust EU to our
      band plan (869,4-869,65 MHz) before copying their numbers.
      → 27-11 (Einstein: b + c, with an own NL profile): plugin repo `backend/regional.py`, profiles NL / our network
        (= the plugin defaults, preselected for EU_868 and unknown regions), EU (upstream), US, ANZ, IN, KR, SG;
        `GET /api/config/reticulum/radio-profiles` (admin; region read live via `state.set_region_provider`); Settings:
        **Starting profile** + **Apply** (fills the five radio fields, saves nothing). Optional airtime caps
        `rnode_airtime_limit_short/long` (percent, blank = none) → RNS `airtime_limit_short/long`; upstream's 1 %/hour
        default not copied. README section. Tests `test_regional.py`, `test_config_routes.py`,
        `test_write_rnsd_config.py`. reticulum 1.1.6. Pi test 27-11 on the COTX: NL preselected (EU_868), US Apply fills
        the fields without saving, `airtime_limit_long = 10.0` in rnsd's config.
  - [ ] **41a. SDR receiver region defaults** (S, the third part of 41): upstream's receiver plugins (pagers, POCSAG,
        rtl433, ACARS, FM radio) refuse to start without a valid frequency and take FM de-emphasis from the region
        (EU 50 µs, US 75 µs); `src/audio/sdr_registry.py`, `tests/test_receiver_regions.py`. Compare with our versions
        in the plugin repo first; probably mostly fine for EU.
        → 27-11: frequencies: nothing to do (ours are fixed NL/EU frequencies on purpose: pagers 172.45, POCSAG 439.9875,
          P2000 169.65, rtl433 433.92, ACARS EU channels). FM radio: without RDS it used `rtl_fm -E deemp` (fixed 75 µs,
          US); now ffmpeg `aemphasis` on both wfm paths (method after upstream). Einstein 27-11: not upstream's chooser
          but automatic from the region: 75 µs for US/KR, 50 µs for everything else (unknown too, no refusing to
          start), `plugins.radio.deemphasis_us` (50/75) overrides; status shows `deemphasis_us`/`region`. Core: plugins
          get `reg.radio_region` (`load_plugins(..., radio_region=config.radio.region)`, as upstream's runtime.py),
          test in `tests/test_plugin_loader.py`. Plugin tests in `apps/radio/backend/tests/test_listener.py` (fail on the
          old code). NFM/AM/SSB get none. radio 1.0.2.
    - [ ] **Pi test, waits for an RTL-SDR dongle** (none in a Meshpoint now, 27-11). Needs the core pull + radio 1.0.2,
          then `sudo systemctl restart meshpoint`.
          1. `cd /opt/meshpoint && sudo venv/bin/python -m unittest -v tests.test_plugin_loader` (all OK).
          2. Radio page: tune a broadcast station in WFM (e.g. 100.7 MHz); it plays.
          3. `ps -eo args | grep -E '[f]fmpeg' | grep -o 'aemphasis[^,]*'` → `aemphasis=mode=reproduction:type=50fm`
             (region EU_868); logged in, `/api/listener/status` shows `"deemphasis_us": 50, "region": "EU_868"`.
          4. Without `redsea` (`which redsea` empty): `ps -eo args | grep '[r]tl_fm'` has no `-E deemp`; by ear a bit
             more treble than before. With `redsea` the RDS path was already 50 µs, so nothing changes by ear.
- [x] **42. MeshCore USB robustness** (M, `b91d994b`; item 26 did not cover it). In `meshcore_usb_source.py`:
  - `restart_auto_fetching()` must call `stop_auto_message_fetching()` first: `start_auto_message_fetching()` in
    `meshcore_py` is not idempotent (each call adds a subscription).
  - Release DTR after opening on CP210x USB bridges (it can hold BOOT and start the firmware rescue console):
    their `src/capture/meshcore_serial.py`. Keep native-USB CDC as is.
  - On idle timeouts check that the port path still exists and trigger a reconnect if it vanished.
  - Keep the `MeshCore` instance before `connect()` and clean up when it fails (`create_serial()` can raise after its
    dispatcher started); on `OSError` log one short warning. Test: `tests/test_meshcore_reconnect.py`.
      **When done, also update `docs/USB-NODES.md`** ("Add a MeshCore companion", first paragraph): it now says
      "this fork does not do that yet (planned, TODO.md item 42)"; put back upstream's wording "Meshpoint releases DTR
      on identified CP210x bridges; native USB devices retain their existing behavior. This uses USB hardware
      identifiers, so it does not depend on the node label or a particular USB port number."
      → Done 26-11: all four points; keeps the library's "retry with DTR inverted" (upstream dropped it); also acts on
        the DISCONNECTED event we already subscribed to. USB-NODES.md CP210x paragraph put back to upstream's wording.
        Tests `tests/test_meshcore_usb_robustness.py` (meshcore 2.3.14 and 2.3.19); exclusive-apply tests now fake
        `_open_meshcore`.
- [x] **43. Node list: sort by packet count** (S). `packets` key in `NodeCards.SORT_KEYS` and
      `node_cards_sort.js` (`packet_count` descending, missing/zero last, tie-break last heard). Credit: PR #128 by
      yourasmit15-web. Test: `tests/frontend/node_sort_stats_units.test.cjs`.
      → Done 26-11: comparator from upstream (our file was identical otherwise), option + SORT_KEYS. Node test.
- [x] **44. Docs wording and `USB-NODES.md`** (S, `58e4e9b1`, `4ad2903f`): USB radios are "nodes", not "sticks"; add
      `docs/USB-NODES.md`; touch HARDWARE-MATRIX, ONBOARDING, RADIO-CONFIG-EXPLAINED, `serial_card.js`,
      `meshtastic_firmware_card.js`. Upstream's new docs to compare: `COMMON-ERRORS`, `FAQ`, `TROUBLESHOOTING`,
      `ONBOARDING`, `DASHBOARD-ACCESS` (with 37c/37d), `docs/README.md` index.
      → Done 26-11: `docs/USB-NODES.md` adapted to this fork (no nRF DFU / CP210x DTR yet, list YAML, TCP), linked from
        README + CONFIGURATION; 45 lines "stick" → "node" (README, API-ENDPOINTS, CONFIGURATION, WHATS-DIFFERENT,
        BANDPLAN, Serial + firmware cards); GPS sticks kept. Their other new docs (COMMON-ERRORS, FAQ, TROUBLESHOOTING,
        ONBOARDING, DASHBOARD-ACCESS, docs/README.md index) not compared yet: still open, see item 50.
- [x] **45. Stats reporter test timing** (S, `4f62d644`): make `tests/test_stats_reporter.py` deterministic like theirs;
      only if our test is flaky.
      → 27-11: `test_positive_after_packets` with a fixed `time.monotonic` (100 → 110 s, 10 packets = exactly 60.0/min);
        our docstrings kept. `stats_reporter.py` itself is the same as upstream's.
        Pi test 27-11 on the COTX: OK.
- [x] **46. Check the rest of their `tests/frontend/*.test.cjs` and plugin docs** (`471a81da`, `dfe6bcf5`): port the tests
      that cover code we already have (gps privacy, mqtt topic preview, transmit save, topbar, bootstrap, map tiles).
      → 27-11: transmit save (`tests/frontend_transmit_save.test.js` + try/catch in `transmit_card.js`; ours keeps the
        relay filters), top-bar MeshCore (`frontend_meshcore_topbar.test.js`, our badge-per-companion chip, passed as-is),
        messaging feedback (`frontend_messaging_feedback.test.js`, upstream's unchanged, passes), stats units
        (`frontend_stats_range_units.test.js` + live redraw in `stats_tab.js`, also our MeshCore card), packet metadata
        (`frontend_packet_modal_rf.test.js`: 0 MHz/SF0/BW0 → n/a in the modal; their meshcore_hops shape isn't ours, 27),
        route audit (`tests/test_write_route_audit.py`, with their newer-FastAPI fix from 471a81da). Skipped:
        `configuration_navigation` (PiMesh, with 39). Plugin docs: 471a81da's PLUGINS.md text is about their plugin
        store ("How to enable downloads", RC catalog) → with 47; dfe6bcf5 is their release plan, nothing for us.
        Bootstrap and map tiles: no upstream test files for those.
- [x] **47. Plugin pages and plugin store layout** (M-L, `b91d994b`, `ede788c8`, `471a81da`, `622ce563`). They redesigned
      both. Checked 26-11 against `upstream/main`:
  - **Store view** (`css/plugin_store.css`, `js/settings/plugin_catalog.js`, `plugin_store_data.js`, markup in
    `index.html` `#settings-plugins-panel`): a hero banner ("optional modules", art squares), a search box, category
    filter chips (Aviation, Radio, Sensors, Paging, ...) and a card grid. Each card has an icon, category colour,
    installed/available badge, description, "details" fold-out, source picker and Install / Enable actions. Setup
    instructions for a source show as an amber notice. Ours (`plugins_panel_controller.js`, 1830 lines) is a list with
    **Installed** and **Sources** tabs and a Browse button per source. Take the grid look as a new browse view; keep
    our logic (updates, dependencies with cascading disable, pinning to a commit, batch updates, provenance), which
    theirs (129-line controller) does not have.
  - **Plugin page shell** (`css/plugin_pages.css`, `js/settings/plugin_pages.js`): one scoped stylesheet
    `.section[data-plugin-page]` that maps plugin pages onto the active theme (cards, tabs, buttons, tables, fieldsets,
    inputs, focus rings), a mobile layout under 640 px (2-column stat grid, full-width actions), and compatibility
    tokens for imported plugin UI. Ours only has a small opt-in `.plugin-page` block in `dashboard.css`, so plugin pages
    look different per plugin. Port the shell; check every one of our 26 plugin pages afterwards, and our light theme
    (`themes/light/theme.css`).
  - **Plugin page loader:** theirs fetches `/api/plugin-ui` and loads each plugin's styles and scripts before the
    sidebar snapshot (10 s script timeout, admin only). Ours mounts via `mountPluginSidebarPages()`; compare, no change
    needed unless a plugin page fails to load.
  - Check with screenshots (dark, light, mobile) before and after. The theme editor page uses the same shell
    (`.theme-editor`).
  → 27-11, **47a (store) built:** Browse renders cards (`_catalogCardHtml`, same data-src-* hooks as the rows, so
    install/update/batch/dependencies unchanged) with a search box and category chips (`_applyStoreFilter`, per source
    in `_storeFilters`). New `frontend/css/plugin_store.css` (upstream's grid/card/chips, no hero banner, our Sources
    form kept) and `frontend/js/settings/plugin_store_meta.js` (category, tagline, icon for our 26 plugins + themes;
    fallback: rtlsdr hook → Radio, reticulum/localmesh → Networks, else Other). Third-party homepage only as http(s)
    link. Test `tests/frontend_plugin_store.test.js`. Plus upstream's "Optional modules" banner on the Sources tab and
    "(n of total)" counts. Screenshots 27-11: dark and light OK (phone not yet).
  → 27-11, **47b (plugin page shell) built:** `frontend/css/plugin_pages.css` = upstream's file as-is (our plugins use
    the same class names: lw-panel, panel, lsn-, cfg-, stat-card ...); `sidebar_plugin_registry.js` marks each plugin
    section `data-plugin-page="<id>"` like upstream; `.plugin-page` in `dashboard.css` lost its padding/scroll (the
    section has them now, as upstream). Also styles Settings → Themes (`.theme-editor`). Test
    `tests/frontend_plugin_page_shell.test.js` (marker; every selector scoped). First after-screenshots 27-11: the
    LocalMesh and Reticulum Dashboard maps collapsed (upstream's `.panel { height: auto }`) and the stat row overflowed;
    fixed with an "ours" block at the end of plugin_pages.css: plugin pages using the core `.dashboard` layout keep
    the core Dashboard's values (no section padding, panels 100 % high, compact stat cards). Test added. Also in the
    "ours" block: yellow primary buttons kept, the theme editor's active tab marked, the installed-themes table full
    width (scrolls only under 640 px), thin theme-coloured scrollbars on plugin pages. bluetooth-scanner 0.2.3: stat
    cards line up with the title. Screenshots 27-11 on the COTX (dark, light, phone): OK.
- [ ] **48. `c2e6c495` Malformed Meshtastic channel key at startup** (M, 9 files + test 85). **In progress 26-11.**
      A real bug here too, only on their `feat/v0.8.1` branch (not in their main yet). Ours:
      `CryptoService.add_channel_key()` does `base64.b64decode(key_b64)` without checking, so a wrong Base64 PSK in
      `local.yaml` raises at startup; the Channels editor (`PUT /api/config/channels`) saves the bad key to disk first
      and then fails, so the next restart crashes too. Theirs: `decode_channel_psk()` (strict, whitespace-tolerant);
      an unusable channel keeps its slot (`None`) so the other channel indices don't shift, `get_all_keys()` returns
      slots with `None`; MeshCore keys go to their own list (`add_meshcore_channel_key`) instead of being re-encoded as
      Base64 (so a MeshCore key with the same name can't overwrite a broken slot); TX on a dead slot is refused
      (`tx_service.py`: `_resolve_channel` raises for an unknown or dead channel, no silent fallback to the primary key);
      the editor rejects a bad key with 400 before saving; the card shows "Channel unavailable. Enter its Base64 PSK."
      (`config_routes.py`, `channel_hash_resolver.py`, `meshtastic_decoder.py`, `coordinator.py`, `channels_card.js`).
      Test first: `tests/test_channel_key_startup.py` is written (10 tests, all fail on current code); then port.
      Their patch does not apply cleanly (3-way conflicts in `config_routes.py`, `coordinator.py`, `tx_service.py`).
      Because KMX keeps working on `feat/v0.8.1`, look at that branch every round.
      Note 27-11: `tests/test_channel_key_startup.py` is committed (in 264d3430) and fails on purpose until this item
      is ported, so CI (`.github/workflows/ci.yml`, pytest step) stays red until then.
      → 27-11 ported (Einstein: not someone else's after all): `CryptoService.decode_channel_psk()` (strict,
        whitespace-tolerant), `add_channel_key` keeps a None slot, `get_channel_key`, `add_meshcore_channel_key` (own
        list), `get_all_keys` with None slots; coordinator/config routes load MeshCore keys separately; decoder and hash
        resolver skip None; `tx_service`: `_secondary_channel` raises for unknown/unavailable, send refuses early,
        replies on an unknown hash get no key when a slot is unavailable; Channels editor validates before saving (400)
        and saves once, list flags `key_unavailable`, card shows "Channel unavailable. Enter its Base64 PSK."; MQTT only
        gets usable keys. Also fixed: a Meshtastic channel save dropped the MeshCore keys until restart (upstream does
        it too). `test_channel_key_startup.py` 10/10 (CI green), `test_meshcore_channels.py` and the echo-hash fixture in
        `test_tx_service.py` adjusted. Still to do: Pi test.
- [x] **49. Bobcat G285 docs branch** (S, `fd5b4d1d` + `dd834718`, branch `upstream/fix/bobcat-g285-docs-reconciliation`,
      not merged into their main). New `docs/BOBCAT-G285.md` (417 lines), reworked `BOBCAT-300.md`, README and
      HARDWARE-MATRIX. Merge with item 33 (`c7bf59f4`) so we do the G285 docs once.
      → Done 26-11 on top of item 33: `BOBCAT-G285.md` added, BOBCAT-300 points there (both patches applied), README and
        HARDWARE-MATRIX by hand. Clone URL in BOBCAT-300, BOBCAT-G285 and HELTEC-M2808 set to javastraat/meshpoint.
- [x] **50. Smaller things inside `b91d994b` and README** (S): `.github/SECURITY.md` (+20 lines: what the Viewer and
      the terminal opt-in mean), README (+57 lines: optional apps, themes, dashboard access, USB nodes), and
      `src/transmit/meshcore_tx_client.py` (+3: takes the shared command lock, check against our item 26 version).
      Also `.github/` CI files of the release candidate: read once, take what fits our CI.
      → 26-11, part done: `SECURITY.md` got a section on Viewer, web terminal and plugins, written for this fork (theirs
        describes public view, DASHBOARD-ACCESS.md and Reticulum isolation, which we don't have yet). README: nothing to
        add, ours already covers viewer, terminal, plugins and sources in more detail (theirs would add wrong claims).
        Still open: the MeshCore command lock (+3 lines, check against item 26), their CI files, and comparing their new
        docs (COMMON-ERRORS, FAQ, TROUBLESHOOTING, ONBOARDING, DASHBOARD-ACCESS, docs/README.md). `SECURITY.md`
        (Einstein 26-11: 1a, 2a): reports now go through GitHub private vulnerability reporting on javastraat/meshpoint,
        supported 0.8.x. Einstein must switch that reporting on in the repo settings.
      → 27-11: CI done (`httpx2`, Node frontend-test step, ruff stays 0.15.1; 5 lint errors of ours fixed). Docs done:
        own `DASHBOARD-ACCESS.md` (admin/Viewer only) and `docs/README.md` index; COMMON-ERRORS +5 entries (Viewer 403,
        restore non-regular member, USB permission after the dialout rule, serial retry, REBOOTING after Set Preset;
        their GPS entry we already had); FAQ (USB radios, USB preset workaround, plugins optional, Viewer, TCP now yes);
        ONBOARDING (Meshtastic USB radio, optional extras). Left out: public view, esptool-in-venv, nRF DFU touch,
        P25/DAPNET/Flock, Reticulum radio test, their "v0.8.0 development checks", PiMesh/WisMesh notes. Open: 50a.
  - [x] **50a. MeshCore command serialization** (M, found 27-11; do after the rest of 50 and 46). Upstream's "+3 lines"
        in `set_source()` bind a `_cmd_lock` they built earlier; we have none. Upstream: every TX-client command
        (send, contacts, repeater poll, channel sync, name/radio) runs under one `asyncio.Lock`, shared with each
        companion's `set_command_lock()`, and the companion's health probe takes it too. Ours: those can overlap on the
        serial line, the library can pick up the other command's response or time out, and a timeout triggers a
        reconnect. Port: lock on the client, shared per companion, around every command and the probe; tests for
        "two commands wait for each other" and "no deadlock when one command calls another". Pi test on rakv21.
        → 27-11: `_cmd_lock` on `MeshCoreTxClient`, shared via `set_source()` → `set_command_lock()`; around sends, advert,
          rename, device info, contacts, add_contact, the whole repeater poll and channel sync (read/write/verify). The
          source takes it for the health probe (as upstream) and, unlike upstream, also for its own per-companion
          sends/advert/rename/device info, the whole exclusive radio change, and `restart_auto_fetching` (stop/start
          talk to the companion too; post-command callbacks run after release, so no deadlock). Test
          `tests/test_meshcore_command_lock.py` (4 of 6 fail on the old code). Pi test 27-11 on rakv21: unit tests OK,
          channel messages and a DM ("Delivered") OK, startup advert + 2 contact fetches at once without timeouts, Set Radio
          OK (after 51). COTX: write-route audit OK, km/mi and n/a OK.
    - [ ] **Recheck later:** a message sent during a repeater poll waits for the poll instead of timing out (rakv21
          polls no repeaters; do it on a Meshpoint that does).

- [x] **51. Set Radio from the dashboard fails on rakv21** (S, found 27-11 while testing 50a; not from 50a: the code from
      before the lock fails the same way; Einstein: never set through the web before, so unknown whether it ever worked).
      Configuration → MeshCore → Set Radio on the Heltec V4.3 always ends in "MeshCore handshake failed during exclusive
      radio set": DTR pulse right after detaching, open 2 s later, no answer to the library's fixed 2 s handshake, DTR-
      inverted retry at once, also no answer. The normal reconnect (5 s after closing, pulse, 2 s, open) works.
      → 27-11: 3 s after detaching before the pulse (`_RADIO_EXCLUSIVE_DETACH_SETTLE_SECONDS`), 3 s instead of 2 after
        the pulse (`_RADIO_EXCLUSIVE_DTR_SETTLE_SECONDS`), 1 s before `_open_meshcore`'s DTR-inverted retry, as the
        library's `create_serial()` does. Test `tests/test_meshcore_radio_set_timing.py` (3 fail on the old code; only
        order and pauses, the board itself is the Pi test). Pi test 27-11 on rakv21: SF7/CR5 verified, back to SF8/CR8
        verified, companion reconnected both times.

### Last step (when everything above is done)

- [ ] **Bump to 0.8.2** (Einstein, 26-11: "we will bump when all is done"). `src/version.py` `__version__ = "0.8.2"`, and
      rename `### Unreleased` in `docs/CHANGELOG.md` to `### v0.8.2 (<month> 2026)`: the dashboard's "What's new"
      (`select_preview_section` in `src/api/update/release_notes.py`) shows the section matching the installed version,
      so bullets left under "Unreleased" wouldn't show. Earlier bump for reference: `28169a85`.

The tables below are the full inventory (incl. what we already have and what we skip). Status column synced with
the work list on 27-11: ✅ done, ⬜ still open.

## 1. Radio, concentrator and relay fixes (high: our COTX gateway runs on this)

| | Commit | What | Notes |
|---|---|---|---|
| ✅ | `536a9149` | Show the real received coding rate (#163) | Tiny. `concentrator_source.py` doesn't set `coding_rate` from `pkt.coderate` |
| ⬜ | `e9286d84` | Serialize native HAL access and wait for TX completion (#181) | We have a `_hal_lock` in `sx1302_wrapper.py`; they add `sx1302_access.py` + TX wait in `tx_service.py` |
| ✅ | `fcacc92b` | Set and verify the service-modem RX preamble on every start (#179) | New `sx1302_preamble.py` |
| ✅ | `027899ed` | Keep the concentrator receive iterator alive during a restart (#176) | 24% already similar |
| ✅ | `f4d19492` | Skip our own Meshtastic packets, stamp the native relay identity (#175, #182) | Applies cleanly |
| ✅ | `ebbf6eb3` | Fresh gateway detection with a bounded HAL version probe (#178) | Setup wizard / `hardware_probe.py` |
| ✅ | `553bdd83` | Transmit settings save completion (#177) | `transmit_card.js` |
| ⬜ | `ffea55fd` | Native channel routing, keep Meshtastic acknowledgements | |
| ✅ | `121c2d3a` | Keep received message channel numbers | |
| ✅ | `8ba70630` | MQTT previews and LongTurbo channel resolution (#146/#147) | |
| ✅ | `06af14ba` | Keep reception timestamps in Meshtastic MQTT packets | Applies cleanly |
| ✅ | `d870125f` | Test only: MQTT partial signal metric | Applies cleanly |
| ✅ | `4439c2a8` | MeshCore contact positions reaching Meshradar (#136) | |
| ✅ | `5a9383d2` | Honor registered-pin mesh position privacy | We have `registered pin` in `mesh_position_resolver.py`; compare |
| ⏭️ | `408f9ea2` | Privacy validation notes (docs to the above) | |

## 2. System and security (high, mostly small)

| | Commit | What | Notes |
|---|---|---|---|
| ✅ | `4d4b22df` | Sample host CPU in the background (#149/#150) | Ours calls `psutil.cpu_percent(interval=0.5)` per request: 0.5 s blocked each time |
| ✅ | `5ff1ec6a` | Restrict Espressif USB access to the dialout group | We install the tight rule; missing: upgrading the old `0666` rule in `post_update.sh` |
| ✅ | `bc5b810c` | Pin `python-multipart` for firmware upload | Missing from our `requirements.txt` |
| ✅ | `1b2c8ff5` | Web terminal cleanup after shell EOF (#166) | Applies cleanly |
| ✅ | `d0074db3` | Keep expected upstream reconnect failures short in the log | 70% already in |
| ✅ | `3ca92469` | Harden `install.sh` for dashboard Apply on upgrade | 46% in |

## 3. Features: MeshCore and Meshtastic USB (medium)

| | Commit | What | Notes |
|---|---|---|---|
| ⬜ | `6011f846` | nRF DFU flash for MeshCore and Meshtastic companions | Big (2000 lines). Ours only says "drag-and-drop the .uf2" for nRF52 |
| ✅ | `93866842` + `459c4d7c` | Reconnect Meshtastic USB after Set Preset reboots it; show REBOOTING vs RECONNECTING | |
| ⬜ | `829a17e4` + `45adf5c5` | LF/MF/LT/MC preset chips and a show-only preset filter on the dashboard | |
| ✅ | `e8c4c6e1` | Persistent MeshCore send feedback (#151) | |
| ✅ | `a451d1e2` | MeshCore heard-path popover (#152) | |
| ✅ | `fc15bc36` + `cad3c4a1` | MeshCore packet RF metadata and received hops | |
| ✅ | `6ea8de00` | Shared MeshCore TCP transport, verified serialized radio commands | |
| ✅ | `23a5fe7e` | MeshCore USB capture status independent of TX | |
| ✅ | `3fbfa9fa` | Show Meshtastic status only for configured capture sources | |
| ✅ | `a16253be` | Connect dashboard status before the initial data load | |
| ✅ | `a890b318` / `8e349c91` | Opt-in Reticulum interface discovery and operator contacts | Mostly have it in our plugin; operator contact is missing (item 36) |
| ⏭️ | `58e4e9b1`, `4ad2903f` | Docs/wording: USB radios are "nodes", not "sticks" | Optional |

## 4. Plugin system (compare, don't port)

We built our own plugin system (manifest, dependencies with cascading disable, sources, batch updates, `meshpoint-plugins`
repo). Theirs is a different implementation. Only worth looking at for ideas and compatibility.

| | Commit | What | Notes |
|---|---|---|---|
| ⬜ | `b91d994b` | Optional apps, themes and dashboard access controls (34 000 lines) | Checked 26-11: mostly ours already; one viewer fix + optional hardening (item 37a/b), public view is optional (37c) |
| ✅ | `ede788c8`, `6b06ec5d` | Plugin source picker, dependencies + cascading disable | Our own (`5ec7fa52`, `6e9f7dfe`, `49a370b6`) |
| ⬜ | `622ce563` | Their official plugin repository | Catalogs diverged (item 37); only p25 is new, check it runs on our core first |
| ✅ | `d8db1301` | Bound plugin source revision lookups for big imports | Possibly useful for our sources |
| ⏭️ | `471a81da`, `dfe6bcf5` | Their plugin docs and release plan | |
| ✅ | `06730b06` | Map tile sources from the dashboard | Ours: `map_tile_source.js`, `dashboard.map_tile_url` (`7d9b3434`) |

## 5. Hardware we may not have (decided 26-11: take it, items 38 and 39)

| | Commit(s) | What | Notes |
|---|---|---|---|
| ⬜ | `de78139d` `cb5495e1` `43cd37aa` `f82898ef` `95247426` `349c56da` `74305f1d` `e043fb4a` `5bca93d2` `387f08be` `cb38865f` `9124ab55` `90d159c8` `9f9da27f` `c44642ea` | **WisMesh Node / RAK6421 HAT** via meshtasticd (bridge, install, dashboard control) | ~5000 lines. Only if we use that hardware. We do have `docs/WISMESH-NODE.md`; check what it covers |
| ⬜ | `cdb2d235` `48942ef2` `529577dc` `841ff7a5` | **PiMesh** (device roles, forwarding, MeshCore config) | Only if we use PiMesh |

## 6. Docs (low, copy what's useful)

| | Commit | What |
|---|---|---|
| ✅ | `486a2d2e` + `44262226` | Heltec HT-M2808 installation guide (applies cleanly) |
| ✅ | `c7bf59f4` | Bobcat G285 community setup (we have `BOBCAT-300.md`) |
| ✅ | `d476e296` | Hardware and accessory links |
| ✅ | `ba50853f` | GPIO reference SX1301 → SX1302 |
| ✅ | `72a9c2cd` | RAK6421 HAT store URL |
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

Only upstream's own release and CI housekeeping: `78082ba2` (v0.8.0 metadata), `3907348a` (changelog),
`cfda01d8` (session drafts), and all merge commits. (`4f62d644` is item 45 and `e311f407` README wording:
read it once, our README differs.)

## Next round

1. `git fetch upstream`
2. `git log --no-merges --reverse --format='%h %ad %s' --date=short 4e78804d..upstream/main`: only what's new since this check.
3. **Also look at their other branches**, not only main. `feat/v0.8.1` already has a commit main doesn't (`c2e6c495`, item 48):
   `git log --no-merges --remotes=upstream --not upstream/main origin/upstream-sync --format='%h %ad %s' --date=short | head`
   (older entries there are rebased duplicates; compare subjects with main before adding them).
4. Add the new commits here, update "Checked" at the top.
