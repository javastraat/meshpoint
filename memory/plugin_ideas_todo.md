# Plugin ideas — fun/cool backlog

Loose brainstormed wishlist, not scoped or committed to. Pick one and ask to
scope it out properly when ready to build (same pattern as other backlog
files in this directory). Nothing here has had its feasibility checked
against actual hardware/antenna setup yet.

## From the first brainstorm (2026-10-11)

- **AIS (ship tracking).** Marine VHF (161.975/162.025 MHz) sibling to the
  existing ADS-B plugin — same "dot moving on the map" payoff, for ships
  instead of planes. `rtl_ais` is the standard decoder, would slot into the
  same RTL-SDR-listener + map pattern ADS-B already uses. Coastal NL
  (Amsterdam) should have good reception.
- **APRS.** Classic ham radio packet protocol (144.800 MHz EU). Likely the
  lowest-effort new-protocol addition on this list — P2000/POCSAG already
  decode AFSK via a multimon-ng-style pipeline, and APRS is the same shape
  (`rtl_fm | multimon-ng -a AFSK1200`). Stations/weather/telemetry pinned
  on the map, same infra the other map-based plugins already use.
- **NOAA weather satellite (APT) decode.** The "wow" one — a pass of a NOAA
  polar-orbit satellite at 137 MHz decodes into an actual photo of Earth.
  Needs `noaa-apt` or similar plus knowing pass timing (ties naturally to
  the satellite-pass-predictor idea below). More orchestration than the
  others, but the payoff is the most fun to actually show someone.
- **Satellite pass predictor.** TLE + basic orbital math off the device's
  already-configured static location — a sidebar/topbar "ISS pass in 12
  min, 45° max elevation" countdown. No new RF hardware at all, just a
  timer + a bit of math. Good standalone build, and a natural companion
  to the NOAA APT idea (know when to listen).

## New ones (second round, same session)

- **FM RDS decode.** The existing `radio` (FM) plugin could surface station
  name / now-playing text from the RDS subcarrier (`redsea` or similar) --
  simple, low-effort, directly extends something already built rather than
  a new listener.
- **rtl_433 weather-sensor dashboard card.** `rtl433` already decodes a
  pile of consumer weather sensors (Acurite, Oregon Scientific, etc.) --
  today that's just raw packet log entries. A small aggregation plugin/card
  that pulls the already-decoded sensor readings into a clean "outdoor
  conditions" widget (temp/humidity/wind, last-seen per sensor) would be a
  practical, likely-low-effort win since the hard decoding part already
  exists.
- **"Fun stats / records" plugin.** Pure software, zero new hardware:
  gamify the existing packet database -- farthest packet ever heard (great-
  circle distance from device location, when a position is known), busiest
  hour, rarest protocol seen, longest-running node, etc. Genuinely matches
  the "fun" brief directly and has no RF/antenna risk at all since it's
  just queries over data already being collected.
- ~~**OLED "idle mode" easter egg**~~ **BUILT 2026-10-11** (same session,
  `meshpoint-plugins` repo, `apps/oled-display/`). New `idle_animation`
  setting: `off` (default, unchanged) \| `blink` \| `matrix` \| `smile` \|
  `pet`. Three idle-pet styles plus a falling-character Matrix scroll,
  shown instead of a blank screen once `blank_after_minutes` elapses (or
  on an explicit Sleep -- both land on the same idle state now).
  Activity signal combines **RF packets** (`pipeline.on_packet`, a hook
  this plugin never used before) **and Reticulum announces** (the
  existing `service_registry.live()` lookup `_reticulum_status()` already
  used, but comparing timestamps rather than `announce_log()`'s length --
  that log is a capped `deque(maxlen=200)`, so a length-delta would have
  silently frozen at zero forever on any mesh busy enough to fill it,
  caught by a Plan-agent review before it ever shipped). This was
  specifically to avoid a Reticulum-only box (no RF capture busy) showing
  a permanently "dead" pet, the user's own concern raised before building.
  `idle_animation` is the one setting on this whole plugin that applies
  **live** (no restart) -- `DisplayService._current_idle_animation()`
  re-reads `state` fresh every tick instead of the startup-snapshot
  `self._cfg` every other setting here is stuck with; the Settings page
  got its own small "Screensaver" card + save button so this field's PUT
  never rides along with a field that *does* need a restart (the combined
  Hardware+Settings form always resubmits everything together, which
  would've made the honest "no restart needed" message a lie in
  practice -- found and fixed the same day). Went through two rounds of
  visual redesign from a live screenshot + user feedback: pet poses
  (blink's antenna-wiggle/flat-mouth kept as one of three styles, not
  replaced), then a genuine second bug (`matrix` filled each column
  solid then flashed back empty instead of a falling streak -- "01
  flashing" per the user's own description) fixed into a proper
  short-streak "digital rain" with per-column speed variation. **Next,
  not yet built**: `matrix` is the one style that still doesn't react to
  the activity level at all (the three pet styles all do) -- agreed
  design: rain falls faster / denser as activity rises, decaying back
  down smoothly since `_activity_level` already decays on its own.

## Not written up in detail, mentioned only in passing

Trunked digital voice (P25/DMR) and GNSS jamming/spoofing detection came up
as "cooler but probably too complex for a single shared-antenna Pi setup" --
not ruled out forever, just not a quick build like everything above.
