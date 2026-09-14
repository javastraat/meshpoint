# Reticulum Dashboard plugin

A live, standalone companion page to the [reticulum](../reticulum) plugin's
own Peers/Messages/Settings page: five stat cards (Status / Known Peers /
People / Infrastructure / Conversations) plus a flashing real-time announce
ticker, newest first.

## Why a separate plugin, not a tab on the reticulum page

The manifest only supports one `[sidebar]` table per plugin, so a second
top-level nav item needs a second plugin — same minimal, backend-free
`provides = ["sidebar"]` shape as [hello-world](../hello-world), just reading
someone else's API instead of saying hello.

## Why it exists

A box with only Reticulum configured (no concentrator/serial/MeshCore) shows
a completely empty core Dashboard — the RF capture pipeline's map/packet
table/stat cards have nothing to show, because Reticulum deliberately
produces zero packets into that pipeline (see
`memory/plugin-reticulum.md`). This page gives Reticulum its own equivalent
of that live, glanceable feel, in its own data shape instead of a faked fit
into RF-only fields (RSSI/SNR/hop-count) Reticulum peers don't have.

## No backend of its own

`provides = ["sidebar"]` only. It reads the reticulum plugin's already-public
`GET /api/reticulum/{status,peers,announces}` and
`GET /api/messages/conversations`, and listens on the shared dashboard
WebSocket (`window.concentratorWS`) for the `reticulum_announce` /
`reticulum_peer` broadcasts the reticulum plugin's own page already
consumes. If the reticulum plugin isn't enabled, those fetches just fail and
the page sits in its empty state — no crash, no dependency mechanism needed.

## Enable it

```yaml
plugins:
  reticulum-dashboard:
    enabled: true
```

Restart, then Networks → Reticulum Dashboard in the sidebar. Needs
`plugins.reticulum.enabled: true` too, or there's nothing to show.

## Layout

```
plugin.toml                          manifest ([sidebar] table, [frontend])
backend/__init__.py                  register(reg) -- a no-op; nothing to register
frontend/reticulum_dashboard.js      the page content (registerSidebarPage)
```
