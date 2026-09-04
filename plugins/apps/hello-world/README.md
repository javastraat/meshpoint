# Hello World plugin

The minimal reference plugin for the **sidebar** seam: a whole new top-level
sidebar page, not just a Listener sub-tab (that's the older `panel` seam --
see the ACARS plugin for that one).

Adds "Hello World" under the **Networks** section of the sidebar. Clicking
it just shows a static "Hello, World." page. That's the whole plugin -- it
exists to prove the seam works and to give a copy-paste starting point for
a real one.

## Enable it

```yaml
plugins:
  hello-world:
    enabled: true
```

Restart, then Networks → Hello World in the sidebar.

## How the sidebar placement works

`plugin.toml`'s `[sidebar]` table is the source of truth:

```toml
provides = ["sidebar"]

[sidebar]
route = "hello-world"     # URL route id
label = "Hello World"     # sidebar link text
category = "networks"     # networks | radio | ops | configuration | settings
```

`src/plugins/manifest.py` parses and validates this; `src/plugins/assets.py`
pushes it to the browser as a small descriptor; `frontend/sidebar/
sidebar_plugin_registry.js`'s `mountPluginSidebarPages()` (called from
`app.js` before the sidebar/router are built) turns that descriptor into an
actual `<li>` in the right sidebar section and a `<section>` to render into.

The plugin's own frontend script only supplies the content, by calling
`window.registerSidebarPage({ route, make })` — `make()` returns a
`{mount(rootEl), show(), hide()}` object, same shape the Listener-tab seam
already uses. See `frontend/hello_world.js`.

Full write-up: [docs/PLUGINS.md](../../../docs/PLUGINS.md).

## Layout

```
plugin.toml                 manifest ([sidebar] table, [frontend])
backend/__init__.py         register(reg) -- a no-op; nothing to register
frontend/hello_world.js     the page content (registerSidebarPage)
```
