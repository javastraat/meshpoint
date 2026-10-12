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
  short-streak "digital rain" with per-column speed variation. `matrix` is the one style that doesn't react to activity level (the
  three pet styles all do) -- tried it (speed/density scaling by level)
  and reverted the same day: multiplying the monotonic frame counter by
  a value that itself changes made the streak's position snap/teleport
  whenever the speed changed, instead of smoothly accelerating -- looked
  like the rain randomly jumping to a different screen. Left alone,
  plain constant-speed rain, matching what the user explicitly asked to
  go back to. A real fix later would need an accumulated position
  (add a variable increment per frame) instead of recomputing `head`
  from scratch each tick -- not attempted.

  **`pet: dinosaur` upgraded to real sprite art, 2026-10-12.** User
  pointed at [AlexIII/t-rex-duino](https://github.com/AlexIII/t-rex-duino)
  (MIT, a full Chrome-Dino-game port for Arduino+OLED) and asked for
  real dino/cactus art instead of procedural ellipses. That repo ships
  actual source PNGs (not just packed Arduino bitmap arrays), so no
  format reverse-engineering needed -- vendored 5 of them
  (`trex-up-1/2/3s.png` for the run cycle, `cacti-small-small-small.png`,
  `ground-1.png`) into `apps/oled-display/backend/assets/dino/` with a
  `CREDITS.md`. `_draw_dino_frame` now composites these (thresholded to
  1-bit, pasted using the PNG's own alpha channel as the mask, cached
  per-instance after first load so the disk read only happens once) in
  place of the old drawn-shape dino; same `_dino_x`/`_dino_dir`
  walk-and-bounce mechanism as before, now sized off the real sprite's
  actual width instead of a guessed constant. One real bug caught and
  fixed via an actual rendered-frame screenshot (saved to a scratch PNG,
  viewed directly) before calling it done: the cactus's first version
  sat at a fixed screen-center position, which the dino -- pacing the
  *entire* width continuously -- regularly walked straight through,
  overlapping/merging the two shapes together. Fixed by positioning the
  cactus a fixed gap ahead of the dino's current travel direction
  instead of a fixed screen spot, clamped to stay on-screen; re-rendered
  and visually confirmed clean separation at multiple dino positions
  including both edges. 500-frame mixed-activity smoke test (walk,
  bounce both directions, cactus on/off) ran clean with real Pillow
  compositing, not mocks.

  **Same day, same conversation, taken further: cactus is now a planted
  landmark + the dino actually jumps it + a score.** User noticed the
  dino-relative cactus from the fix above still looked like an
  accessory tagging along rather than an obstacle, and asked for
  jump-over-it + a score on top too -- explicitly asked "tell me first"
  both times before building, confirmed each time before continuing.
  Cactus now spawns once (a fixed gap ahead of wherever the dino is the
  moment activity starts) and stays PLANTED at that exact spot --
  doesn't track the dino anymore -- until either the dino clears it
  (scores) or bounces off a wall first (scrapped, no score); this also
  incidentally fixed the flicker the old recompute-every-frame version
  had, free. Jump physics ported verbatim from the same reference
  repo's `TrexPlayer.motionStep()` (a classic integer-decay symmetric
  arc) rather than invented from scratch -- verified numerically in
  isolation first (peak height exactly 36px at momentum 8, matching the
  source's own documented comment, lands cleanly at 0 with no
  oscillation) before ever wiring it in. Score ("jumps cleared") drawn
  with the SAME reference repo's own tiny 5x8 pixel digit font
  (ported as plain byte data, not an asset file -- it's only 10 short
  tuples) instead of Pillow's default font, for a more authentic
  Chrome-Dino look.

  **Real bug caught from an actual rendered filmstrip, not assumed
  away:** the first "clear the cactus" definition required the dino's
  FULL body past the cactus's FAR edge -- but horizontal speed is fixed
  and jump height can't be increased to compensate (momentum high
  enough to cover the needed extra ground would peak well above the
  64px panel's own height, confirmed by simulating several momentum
  values before picking one). Net effect: the dino reliably landed
  back down with its body overlapping the cactus before ever
  "clearing" it by that definition -- visible in a saved, directly-
  viewed filmstrip render, not something a unit test alone would have
  caught. Fixed by redefining "cleared" as the dino's leading edge
  reaching the cactus's near edge (the same reference point the jump
  trigger already used) instead of requiring full-body clearance --
  removes the cactus while the dino is still well up in the air, so no
  overlap is ever rendered. Re-verified with a fresh filmstrip after
  the fix: clean rise, cactus vanishes mid-climb, smooth landing on
  open ground, score tick appears the instant it clears. 500-frame
  regression re-run after this change too -- still clean bounds/bounces,
  score accumulates correctly across repeated bursts.

  **Regression caught live on the real Pi, same day: "a plant spawns
  right on the dino and vanishes."** Root cause: cactus spawn position
  was clamped to stay on-screen (`max(0, min(spawn_x, width - c_w))`)
  whenever the dino happened to be near a wall when activity hit --
  that clamp could squeeze the cactus in only a few px ahead of (or
  even overlapping) the dino's CURRENT position instead of the intended
  45px gap, which skips the jump-trigger window entirely (the gap is
  already <= 0 the moment it appears) and satisfies the lenient
  "cleared" check on the very next frame with no jump ever firing --
  an instant appear-then-vanish right on the dino, scoring a phantom
  point with nothing visible happening. Reproduced deterministically
  first (dino pinned near the right wall, activity triggered -- cactus
  spawned 4px ahead, overlapping the dino's own sprite box, cleared one
  frame later with `vy` never leaving 0) before touching any code.
  Fixed by not clamping at all: skip spawning entirely on any tick
  where the full, unclamped 45px-ahead position wouldn't fit on-screen,
  and just try again next tick once the dino has moved on or bounced
  back with the full width ahead of it. Verified with the same
  deterministic repro (confirms the phantom spawn is gone) plus an
  exhaustive sweep over every possible dino position (0-106) in both
  directions asserting zero overlapping spawns -- not just the one
  position that happened to be reported.

  **Same day: dino's walking speed is now activity-reactive too.** User
  asked for the dino to actually speed up on incoming RF ("rf +1 cactus
  -x min speed as set now ... eventually slows back down after jumping
  a few cactuses"), explicitly asking for advice first -- flagged the
  one real risk up front before building: the earlier matrix
  speed-reactivity revert happened because matrix recomputed its scroll
  position from `frame * speed` each tick, so a changing speed made it
  snap/teleport. The dino doesn't have that problem since its position
  is already a running accumulator (`self._dino_x += dir * speed`), so
  a smoothly varying speed is safe there in a way it wasn't for matrix.
  Built as: `self._dino_speed` ramps up a little each tick activity
  (`level > 0`) is seen, capped at `_DINO_SPEED_MAX = 5` -- deliberately
  kept well under `_DINO_JUMP_TRIGGER_GAP` (12px) so a single tick's
  movement can never skip clean over the jump-trigger window and
  faceplant into a cactus with no jump firing, confirmed by a dedicated
  simulation forcing max speed with sustained activity for 5000 frames:
  227 cacti cleared, zero without an actual jump preceding the clear.
  Decays back down a step each time a cactus is actually cleared (the
  satisfying "slows down after jumping a few" the user described), plus
  a slower passive per-tick decay regardless of jumps -- **this second
  decay path was added after a first version's own simulation caught
  it missing**: without it, a burst that ramped speed up and then went
  quiet with no cactus left in flight to clear left the dino stuck
  at its ramped-up speed forever, since nothing could trigger a decay.
  Re-simulated after adding the passive decay: a sustained-busy run
  reliably reaches max speed, and once quiet, speed returns fully to
  its floor within ~20 ticks (~7s at 3fps) regardless of whether any
  more cacti ever clear.

## Not written up in detail, mentioned only in passing

Trunked digital voice (P25/DMR) and GNSS jamming/spoofing detection came up
as "cooler but probably too complex for a single shared-antenna Pi setup" --
not ruled out forever, just not a quick build like everything above.
