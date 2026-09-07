#!c=1
# TechInc Mesh BBS -- About Meshpoint (meshpoint.mu)
# Generic -- nothing to [EDIT] here unless you want to.

`F38f`!TechInc Mesh BBS`!`f  `F888//`f  `!About Meshpoint`!
========================================================

>What it is

`*Meshpoint`* is an edge radio + mesh gateway with a web
dashboard. It runs on a Raspberry Pi, listens on real hardware
-- an 868 MHz LoRa concentrator, an RNode, and a cheap RTL-SDR
dongle -- decodes what it hears, stores it, and serves it up
locally. No cloud, no account, no phone-home. One install
script, then it just sits there and listens.

>LoRa mesh

`F888Meshtastic `f: node roster, positions on a map, telemetry,
             DM + channel messaging
`F888MeshCore   `f: node roster, messaging, live radio view
`F888LoRaWAN    `f: uplink frames, decrypted with your own keys,
             device roster

>RTL-SDR -- one $30 dongle, a lot of bands

`F888FM / AM radio `f: browser tuner with RDS (station name,
                RadioText, signal meter)
`F888DAB+         `f: digital radio -- channel scan + playback
`F888POCSAG pagers `f: 512 / 1200 / 2400 baud pager decode
`F888DAPNET       `f: amateur-radio paging network
`F888P2000        `f: NL emergency services (FLEX, 169 MHz)
`F888RTL433       `f: 433 MHz ISM -- weather stations, sensors,
                TPMS, doorbells, whatever is chirping
`F888ADS-B        `f: aircraft table + live map (1090 MHz)
`F888ACARS        `f: aircraft VHF datalink messages

Only one RTL-SDR mode runs at a time -- they share the dongle.

>RF environment

A spectrum sweep across the RTL-SDR's range -- a quick "what is
loud right now" view, and a noise-floor trace on the dashboard.

>Reticulum / LXMF

`*Meshpoint`* attaches to a local `rnsd` as a client: an LXMF
inbox, a peer roster built from announces, a NomadNet browser,
and -- when node hosting is on -- this very BBS. All on one
identity: browse it and message it on the same hash.

>The dashboard

Per-protocol pages, a live map, packet stats + traffic graphs,
a real terminal, firmware flashing for Meshtastic / MeshCore /
RNode / pager companions, and a plugin system (every radio mode
above is a plugin you enable per node).

>Open source

`*Meshpoint`* is a fork, developed in the open, Raspberry Pi OS.

`F888Source `f: `[github.com/KMX415/meshpoint`https://github.com/KMX415/meshpoint]
`F888Stats  `f: `[this node's live numbers`:/page/info.mu]

-
`[<< Main menu`:/page/index.mu]     `[Get on the mesh >>`:/page/mesh.mu]
