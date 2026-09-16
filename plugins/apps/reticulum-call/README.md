# Reticulum Call plugin

Voice calls over Reticulum. Adds a **Call** tab to the Reticulum page
(hooked in via `window.registerPageHook`, not a sidebar page of its
own) — dial a destination hash, or answer an incoming call, and talk,
Codec2 encoded, browser to browser.

## Credit

This one genuinely is a port, not a clean-room reimplementation, for
the parts where that made sense:

- **`backend/audio_call.py`** (in the `reticulum` plugin itself, not
  this plugin — see below) is ported closely from
  [**reticulum-meshchat**](https://github.com/liamcottle/reticulum-meshchat)'s
  `src/backend/audio_call_manager.py` (MIT, Liam Cottle). The mechanism
  is unchanged: a call is an `RNS.Link` to a `"call"/"audio"`
  destination, and forwarding a packet is one line,
  `RNS.Packet(link, data).send()`.
- **The vendored Codec2 WASM** (`frontend/codec2/c2enc.{js,wasm}`,
  `c2dec.{js,wasm}`) is copied verbatim from reticulum-meshchat's own
  `assets/js/codec2-emscripten/` (same MIT license) — real-time Codec2
  encode/decode compiled to WebAssembly, not something to rebuild from
  scratch. `codec2/processor.js` (the AudioWorklet capture processor)
  is ported with the same logic, adjusted only to no-op safely if
  something ever loads it as a plain script instead of via
  `audioWorklet.addModule()`.

What's **not** a port — built fresh against Meshpoint's own patterns:

- The whole call UI (`frontend/reticulum_call_panel.js`) — dial/
  incoming-call/hangup, wired as a page hook rather than
  reticulum-meshchat's own Vue `CallPage.vue`.
- `frontend/reticulum_call_codec.js`, the Float32-PCM ↔ Codec2 bridge.
  reticulum-meshchat's own `Codec2Lib` round-trips every audio chunk
  through a WAV file and a second vendored WASM build (`sox.wasm`,
  ~650 KB) purely to get from Float32 samples to headerless 16-bit PCM
  and back — SOX's actual job there, resampling, is a no-op, since the
  AudioWorklet processor already delivers audio at Codec2's own
  required 8 kHz. Converting Float32 ↔ 16-bit PCM directly (the same
  arithmetic as the reference's own `WavEncoder.floatTo16BitPCM`, just
  without ever writing a WAV header) gets the same result without the
  extra WASM module or the extra module-boot on every audio chunk.
- The wire framing between two meshpoint nodes: one mode-index byte
  plus the raw Codec2-encoded bytes per WebSocket/RNS frame — not
  reticulum-meshchat's own protobuf-wrapped `AudioCallPayload`, which
  would mean vendoring a protobuf runtime for a format only that one
  other project uses. **Consequence: not guaranteed to interoperate
  with a real Sideband or reticulum-meshchat call** — this targets
  meshpoint-to-meshpoint. Real interop, if it's ever wanted, means
  matching their exact frame shape instead.

## What's here

- **Dial by destination hash**, pick a Codec2 mode (3200 down to
  450PWB — same set reticulum-meshchat's own call UI offers).
- **Incoming calls** show up as a banner (Join / Ignore) the moment a
  peer's call link connects — there's no separate ring/answer
  negotiation at the RNS layer itself (confirmed against
  reticulum-meshchat's own implementation: an `RNS.Link` reaches
  `ACTIVE` the instant the destination responds), so "incoming call"
  really means "a link is up, do you want to join the audio."
- Mic capture via `getUserMedia` + an `AudioWorkletNode`, playback via
  `AudioBuffer`/`AudioBufferSourceNode` scheduled back-to-back as
  chunks decode.

## What's not here

- **Real interop with Sideband / reticulum-meshchat** — see the wire
  framing note above. Untested either way; nobody's confirmed whether
  even matching the frame shape would be sufficient.
- **Mute, call history, multiple simultaneous calls, anything past the
  minimum to actually talk to someone.**
- **Live-verified on a real device.** Built and unit-tested (the
  backend half, in the `reticulum` plugin's own test suite) without a
  live two-node call ever having happened yet.

## Enable it

```yaml
plugins:
  reticulum:
    enabled: true
    audio_calls_enabled: true    # Settings tab -> "Voice calls"
  reticulum-call:
    enabled: true
```

Restart, then open the Reticulum page's **Call** tab. Needs
`plugins.reticulum.audio_calls_enabled: true` as well as this plugin
being enabled — that flag is what actually announces a `call.audio`
destination on the node's identity; without it there's nothing to call.

## Layout

```
plugin.toml                              manifest ([hook] table, host = "reticulum", requires = "reticulum")
backend/__init__.py                       register(reg) -- a no-op; every route this plugin uses lives in the reticulum plugin itself
frontend/reticulum_call_panel.js          the Call tab (dial/incoming/hangup, mic + playback wiring)
frontend/reticulum_call_panel.css         layout for the above
frontend/reticulum_call_codec.js          Float32 PCM <-> Codec2 bytes
frontend/codec2/c2enc.{js,wasm}           Codec2 encoder (vendored, MIT)
frontend/codec2/c2dec.{js,wasm}           Codec2 decoder (vendored, MIT)
frontend/codec2/processor.js              AudioWorklet mic-capture processor (ported, MIT)
```
