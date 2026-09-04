# Radio plugin

Browser FM/AM/SSB broadcast & utility radio listener off the shared
RTL-SDR dongle, via `rtl_fm` + `ffmpeg`, with RDS on FM via
[`redsea`](https://github.com/windytan/redsea). Coverage: ~24–1766 MHz —
FM broadcast (WFM), airband and AM, marine VHF/UHF, PMR446, 2 m / 70 cm ham
(NFM), and SSB (USB/LSB). The last RTL-SDR decoder to move off the old
built-in Listener page — its UI renders on the [RTL-SDR](../rtlsdr/) page
instead, via the `"hook"` seam (`plugin.toml`'s `[hook] host = "rtlsdr"`),
same as every other RTL-SDR plugin (see
[`plugins/apps/rtlsdr/README.md`](../rtlsdr/README.md) for the full
migration story). With Radio gone, the built-in Listener page had nothing
left on it and was deleted outright.

Everything that made Radio the biggest tab on the old page came along:

- **Tuner** — frequency, mode (WFM/NFM/AM/USB/LSB), squelch, gain, and
  pre-encoder level.
- **Two switchable skins** — **Digital** (VFD-style readout, segmented VU
  meter, LEDs) and **Analogue** (slide-rule dial, swinging-needle VU gauge
  under glass), persisted per browser.
- **Real-time Web Audio VU meter** that follows the actual decoded audio,
  not just a server-reported level.
- **RDS on FM** (via `redsea`): station name, scrolling RadioText /
  now-playing, program type (PTY), and a block-error-rate signal-quality
  meter.
- **Preset stations picker** — category tabs, search, ★ favorites, and
  green "now playing" dots on the tuned channel and its category.

⚠️ **Behaviour change:** Radio used to be always-on, no config gate. It now
ships `locked = true` in its `plugin.toml` (git-tracked, so it won't offer
a Delete button on Settings → Plugins — deleting it wouldn't stick past the
next `Update` anyway), but like every other plugin here it is **off by
default**. `/api/listener/*` — its API prefix from before this plugin
existed — is kept unchanged rather than renamed to `/api/radio/*`, to
avoid touching the sidebar mini-player, the telemetry rail, the `<audio>`
stream URL, and every doc mentioning it for a purely cosmetic rename.

## Install

1. Install `redsea` (once, needs sudo — builds from source via meson,
   a couple of minutes on a Pi 4; `rtl_fm`/`ffmpeg` come from the shared
   [`rtlsdr`](../rtlsdr/) plugin's own `setup.sh` + base packages):

   ```sh
   sudo bash /opt/meshpoint/plugins/apps/radio/setup.sh
   # or, for a confirmation prompt first:
   sudo meshpoint plugin setup radio
   ```

   The absolute path matters if you want this passwordless: `config/
   sudoers-meshpoint`'s NOPASSWD grant for plugin setup scripts matches
   the absolute path exactly. `meshpoint plugin setup` always resolves it
   for you. Idempotent — skips the build if `redsea` is already on `PATH`.
   Without `redsea`, everything else works; the RDS pills simply stay
   hidden.

2. Enable it (and [`rtlsdr`](../rtlsdr/), its host page) in `local.yaml`
   and restart Meshpoint:

   ```yaml
   plugins:
     rtlsdr:
       enabled: true
     radio:
       enabled: true
   ```

3. Open the dashboard → Radio → **RTL-SDR** and tune in a preset or a
   manual frequency.

Shares the one RTL-SDR dongle with the DAB+ / Pagers / POCSAG / P2000 /
RTL433 / ACARS / ADS-B listeners (only one active at a time; stop the
other one first).

## Layout

```
plugin.toml              manifest (name, deps, [frontend], [hook], meta)
setup.sh                 builds redsea from source via meson
backend/listener.py      rtl_fm | ffmpeg pipeline + redsea RDS tailer + fan-out (RtlListener)
backend/routes.py        /api/listener  status / tune / stop / stream
backend/__init__.py      register(reg)
frontend/radio_panel.js  the player (Digital/Analogue skins, VU meter, presets, RDS) -- hooks into rtlsdr
```
