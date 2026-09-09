# Writing a Meshpoint Plugin

A how-to for building a new app plugin from scratch. For *using* an
already-written plugin (enabling it, setting its config, the Settings →
Plugins page, the `meshpoint plugin` CLI), see
[docs/CONFIGURATION.md § Plugins](CONFIGURATION.md#plugins) instead — this
doc is for the plugin author.

The canonical worked example is the shipped **ACARS** plugin —
[`plugins/apps/acars/`](../plugins/apps/acars/) — for routes/listener/hook,
the minimal **Hello World** / **Hello World Hook** /
**Hello Service** plugins —
[`plugins/apps/hello-world/`](../plugins/apps/hello-world/) (sidebar),
[`plugins/apps/hello-world-hook/`](../plugins/apps/hello-world-hook/) (hook),
[`plugins/apps/hello-service/`](../plugins/apps/hello-service/) (service) —
each isolating one seam, and **DAPNET**
([`plugins/apps/dapnet/`](../plugins/apps/dapnet/)) and **Reticulum**
([`plugins/apps/reticulum/`](../plugins/apps/reticulum/)) as full
multi-seam plugins extracted out of core. Every section below points at
the real file that does the thing being described. When in doubt, go read
that file; it's real, tested, shipped code, not a toy example.

---

## What a plugin can do today

An app plugin is out-of-core code that hooks nine seams:

- **Routes** — mount a FastAPI `APIRouter` under `/api/<whatever>`.
- **Listener** — register an RTL-SDR subprocess listener (built idle at
  startup, started on demand by its own `/start` route, sharing the one
  physical dongle with every other listener — see
  `src/audio/sdr_registry.py`).
- **Panel** — add a sub-tab to another plugin's dashboard page. Technically
  still supported (`"panel"` in `provides`, see
  [`src/plugins/manifest.py`](../src/plugins/manifest.py)) but no shipped
  plugin uses it anymore — the built-in *Listener* page it originally
  targeted is gone, and every former panel (DAB+, Pagers, POCSAG, P2000,
  RTL433, ACARS, ADS-B, Radio) now uses **Hook** below instead, which does
  the same job without requiring a specific page to exist in core.
- **Sidebar** — add a whole new top-level page of your own, placed under an
  existing sidebar section (Networks, Radio, Ops, Configuration, Settings).
- **Hook** — inject content into *another* plugin's already-rendered page,
  instead of owning a page/tab of your own. The other plugin has to opt in
  as a host (see [Injecting into another page](#injecting-into-another-page-hook)).
- **Capture** — register a `CaptureSource` that isn't RTL-SDR-shaped (a
  serial-connected device, say), joining the core packet pipeline
  unconditionally at boot rather than on-demand via a `/start` route.
- **Protocol** — own decode and post-decode classification for a protocol
  identity your plugin introduces, one that isn't a member of the closed
  `Protocol` enum. Kept separate from Capture since a plugin might need
  only one of the two (see
  [Adding a non-RTL-SDR capture source + protocol](#adding-a-non-rtl-sdr-capture-source--protocol-captureprotocol)).
- **Topbar** — add your own persistent status chip to the topbar, the same
  visual language as the built-in Meshtastic/MeshCore/Serial/Pager chips
  (see [Adding a topbar chip](#adding-a-topbar-chip-topbar)).
- **Service** — register a lifespan-managed async background service (an
  object with `async start()` / `async stop()`), for a plugin that just
  needs to *run something* for the life of the app — not a subprocess
  listener, not a packet-pipeline source. See [Adding a background
  service](#adding-a-background-service-service).

That's it. A plugin **cannot** (yet) add a *plugin-contributed settings
sub-page* inside core's own Configuration section — see [Current
limitations](#current-limitations) at the bottom before you start, in
case what you want to build needs one.

## Directory layout

```
plugins/apps/<your-id>/
    plugin.toml              # the manifest -- required
    setup.sh                 # optional: installs system deps (apt + build)
    check.sh                 # optional: "are deps installed?" probe (exit 0 = yes)
    README.md                # recommended: install/config/layout, like this
    backend/
        __init__.py          # required: register(reg) entry point
        <whatever>.py         # your listener/routes/decode logic
        tests/
            __init__.py
            test_<whatever>.py
    frontend/
        <your-id>_panel.js    # required if you add a "panel"
        <your-id>_panel.css   # optional
```

`<your-id>` is both the folder name and `plugin.toml`'s `name` — they must
match exactly (`src/plugins/manifest.py` rejects a mismatch), lowercase
`[a-z0-9-]`, 2–39 chars.

**Where it lives** decides its tier:

- `src/plugins/apps/<id>/` — **built-in**. Ships in the repo, loads
  automatically unless `plugins.<id>.enabled: false`. Use this for
  first-party plugins bundled with a fork.
- `plugins/apps/<id>/` — **community**. A drop-in folder (yours or
  someone else's), loads only when `plugins.<id>.enabled: true`. This is
  where you'll put a new plugin while developing it, and where ACARS lives
  (it's the reference *community* plugin on purpose, to prove that tier
  actually works end to end).

A built-in id always wins an id collision with a community folder of the
same name.

## `plugin.toml`

```toml
name = "acars"
version = "1.0.0"
meshpoint_api = 1
provides = ["listener", "routes", "hook"]
locked = false                            # optional, default false -- see below

[deps]                                    # optional
apt = ["cmake", "pkg-config"]
setup = "setup.sh"                        # relative path, must exist
check = "check.sh"                        # optional, relative path, must exist

[frontend]                                # required when "panel", "sidebar" or "hook" in provides
scripts = ["frontend/acars_panel.js"]     # relative paths, must exist
styles  = ["frontend/acars_panel.css"]    # optional

[sidebar]                                 # required when "sidebar" in provides
route = "hello-world"                     # url route id, bare slug [a-z0-9-]
label = "Hello World"                     # sidebar link text
category = "networks"                     # networks | radio | ops | configuration | settings
icon = "plug"                             # optional, default "plug" -- see KNOWN_SIDEBAR_ICONS

[hook]                                    # required when "hook" in provides
host = "hello-world"                      # another plugin's [sidebar].route -- this
                                           # plugin's content is injected into that
                                           # page instead of owning one of its own

[meta]                                    # optional, all strings
description = "Aircraft VHF datalink (ACARS) decoding via acarsdec + libacars"
homepage = "https://github.com/f00b4r0/acarsdec"
author = "Your Name"
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Must equal the folder name. |
| `version` | yes | Free-form string, shown on Settings → Plugins. |
| `meshpoint_api` | yes | Integer. Currently `1` (`PLUGIN_API_VERSION` in `src/plugins/manifest.py`). A manifest targeting a higher number than this build supports is refused, not crashed. |
| `provides` | yes | Non-empty subset of `listener`, `routes`, `panel`, `sidebar`, `hook`, `capture`, `protocol`, `topbar`, `service`. Calling a `PluginRegistry` method for a capability you didn't declare raises at register time — see [The `register(reg)` entry point](#the-registerreg-entry-point). |
| `locked` | no, default `false` | Only meaningful for **community** plugins. `true` marks a shipped/bundled community plugin (git-tracked, not a real user drop-in) so Settings → Plugins refuses to offer a Delete button for it — the same protection `plugins/themes/*/theme.json`'s `"locked": true` already gives the bundled theme pack. ACARS sets this. If you're writing a plugin someone else will `git clone` into their own `plugins/apps/`, leave it `false` (default) so they can delete it if they want to. |
| `[deps].apt` / `.setup` | no | System packages + a build script. **Never installed automatically** — the operator runs it themselves (`sudo bash plugins/apps/<id>/setup.sh` or `sudo meshpoint plugin setup <id>`, which just wraps the same script after showing what it does). |
| `[deps].check` | no | Path to an **unprivileged** "are my deps installed?" probe. Exit `0` = satisfied, non-zero = setup needed (stdout/stderr is shown to the admin as the reason). Run at boot by the loader and on demand from Settings → Plugins (`POST /api/plugins/{id}/check`). Must not use `sudo` — the service account has to be able to answer it. See [System dependencies](#system-dependencies). |
| `[frontend].scripts` / `.styles` | scripts required iff `panel`, `sidebar`, `hook` or `topbar` in `provides` | Served at `/plugins/apps/<id>/<path>` — **only** the exact files listed here, from either tier, nothing else in the folder is reachable (`src/plugins/assets.py:resolve_plugin_asset`). |
| `[sidebar].route` / `.label` / `.category` | required iff `sidebar` in `provides` | See [Adding a top-level sidebar page](#adding-a-top-level-sidebar-page-sidebar) below. `category` must be one of `KNOWN_SIDEBAR_CATEGORIES` in `src/plugins/manifest.py`. |
| `[sidebar].icon` | no, default `"plug"` | One of `KNOWN_SIDEBAR_ICONS` (`src/plugins/manifest.py`) — a curated key, not raw SVG. See [Adding a top-level sidebar page](#adding-a-top-level-sidebar-page-sidebar). |
| `[hook].host` | required iff `hook` in `provides` | Another plugin's `[sidebar].route` — not validated against real plugins at parse time (resolved at runtime in the browser). See [Injecting into another page](#injecting-into-another-page-hook). |
| `[meta].*` | no | Shown on Settings → Plugins: description, a clickable homepage link, author. |

## The `register(reg)` entry point

`backend/__init__.py` must define a module-level `register(reg)`, called
once at startup (`src/plugins/loader.py`) if the plugin is enabled. Keep
imports of anything heavy (FastAPI, your listener class) *inside*
`register()`, not at module top level — this is what lets
`backend/<whatever>.py` unit-test on a machine with no FastAPI installed
(see [Testing](#testing)):

```python
# plugins/apps/acars/backend/__init__.py
from __future__ import annotations


def register(reg) -> None:
    from .listener import AcarsListener
    from .routes import init_routes, router

    reg.add_router(router)

    def build() -> AcarsListener:
        return AcarsListener(
            frequencies=reg.config.get("freqs"),
            gain=reg.config.get("gain"),
            device=reg.config.get("device"),
        )

    reg.add_listener("acars", build, init_routes)
```

`reg` is a `PluginRegistry` (`src/plugins/registry.py`):

- `reg.manifest` — the parsed `PluginManifest`.
- `reg.name` — the plugin id.
- `reg.config` — a plain `dict`, a copy of `config.plugins["<id>"]` from
  `local.yaml`. **Opaque and unconditional** — every plugin gets this
  regardless of what it declared in `provides`, it's never checked against
  the core config schema, and Meshpoint hands it to you verbatim. This is
  how ACARS reads its own `freqs`/`gain`/`device` keys (see
  [Your plugin's own config](#your-plugins-own-config) below).
- `reg.add_router(router, *, public=False)` — requires `"routes"` in
  `provides`. Mounts a FastAPI `APIRouter` the same way every core route
  gets mounted, behind `Depends(require_auth)` unless `public=True`.
- `reg.add_listener(name, build, wire=None)` — requires `"listener"` in
  `provides`. `build` is a zero-arg callable returning your listener
  instance (or a tuple of several — see the built-in pager listener in
  `src/api/server.py`'s `_BUILTIN_LISTENERS` for that shape). It's called
  once at startup; the listener stays idle until its own `/start` route is
  hit. `wire`, if given, is called with whatever `build()` returned, so you
  can inject it into your routes module's module-level state (that's what
  `init_routes(listener)` does above).
- `reg.add_capture_source(name, build, wire=None)` — requires `"capture"`
  in `provides`. For a capture source that isn't RTL-SDR-shaped and
  doesn't share the one-dongle-at-a-time listener lifecycle — a serial
  device, say. `build` is a zero-arg callable returning your `CaptureSource`
  (or a tuple of several, one per configured device); unlike a listener it
  joins the pipeline **unconditionally at boot**, no `/start` route. `wire`,
  if given, is called once `pipeline.start()` has completed (so
  `pipeline.packet_repo` is safe to read) with whatever `build()` returned
  plus the live `pipeline` — this is how a plugin's own routes get a
  `PacketRepository` handle. See [Adding a non-RTL-SDR capture
  source + protocol](#adding-a-non-rtl-sdr-capture-source--protocol-captureprotocol)
  below.
- `reg.add_protocol(protocol, *, capture_prefix, adapt, tier=None)` —
  requires `"protocol"` in `provides`. Lets your plugin own decode and
  post-decode classification for a protocol identity it introduces (not
  one of the closed `Protocol` enum's members) — `protocol` is a plain
  string, matched against `packet.protocol` after decode; `capture_prefix`
  is matched against `raw.capture_source.startswith(...)` to decide when
  your `adapt(raw) -> Packet | None` runs instead of the core decoder.
  `tier(packet) -> "ignore" | "blacklist" | None`, if given, is checked
  right after decode — `"ignore"` drops the packet entirely (not even
  shown live), `"blacklist"` shows it live but never persists it, `None`
  is normal handling. See the same section below.
- `reg.add_service(name, build, wire=None)` — requires `"service"` in
  `provides`. For a plugin that runs a lifespan-managed async service (an
  object with `async start()` / `async stop()`) rather than a subprocess
  listener or a pipeline source. `build(context)` returns the service (or
  `None` to opt out); `context` is a `ServiceContext` exposing the live
  `pipeline`, the shared `ws_manager` and the full `AppConfig`. Started
  right after `pipeline.start()`, stopped on shutdown. A service whose
  `start()` raises is logged and skipped — it never aborts meshpoint. See
  [Adding a background service](#adding-a-background-service-service) below.

Calling `add_router`/`add_listener`/`add_capture_source`/`add_protocol`/
`add_service` for a capability not in `provides` raises
`PluginRegistryError` — caught by the loader, logged, and the whole plugin
is skipped (one bad plugin never aborts the others or the app). See
`src/plugins/loader.py::load_plugins`.

## Adding a dashboard tab (`"panel"`, unused — use `"hook"` instead)

`"panel"` (`window.registerListenerPanel`) added a sub-tab to one specific
built-in page — the dashboard's *Listener* page. That page is gone (its last
tab, Radio, moved to a plugin like everything else RTL-SDR), and
`window.registerListenerPanel` was deleted along with it, so `"panel"` has
no working frontend counterpart left even though `PluginRegistry` and the
manifest schema still technically accept it. Every plugin that used to be a
panel (ACARS, RTL433, ADS-B, Pagers, POCSAG, P2000, DAB+, Radio) now uses
**Hook** instead (see [Injecting into another page](#injecting-into-another-page-hook)
below) — it does the same job (a tab inside someone else's already-rendered
page) without needing that page to be a specific built-in one, since any
plugin can opt in as a host. Write a new dashboard-tab plugin against `hook`,
not `panel`.

## Adding a top-level sidebar page (`"sidebar"`)

Unlike `"hook"` (a tab injected into another plugin's already-rendered
page), `"sidebar"` gives your plugin its own top-level nav entry, placed in
an existing sidebar section. There's no `reg.add_sidebar(...)` call — it's
entirely declarative, driven by `[sidebar]` in `plugin.toml` plus your own
frontend script:

1. List `"sidebar"` in `provides` and fill in `[sidebar]`:

   ```toml
   # plugins/apps/hello-world/plugin.toml
   provides = ["sidebar"]

   [frontend]
   scripts = ["frontend/hello_world.js"]
   styles = ["frontend/hello_world.css"]   # optional -- omit if you have no CSS

   [sidebar]
   route = "hello-world"     # -> #/hello-world
   label = "Hello World"     # sidebar link text
   category = "networks"     # networks | radio | ops | configuration | settings
   icon = "message"          # optional, default "plug" -- see below
   ```

   `category` must be an *existing* sidebar section — you're placing your
   page into one, not creating a new section. `networks`/`radio`/`ops` are
   flat item runs (your page becomes a sibling of LoRaWAN, Radio, Terminal,
   ...); `configuration`/`settings` are the two collapsible submenus, and
   your route gets nested as `<category>/<route>` the same way the built-in
   subitems are (e.g. `settings/plugins`) — so `category = "settings"` with
   `route = "hello-world"` ends up at `#/settings/hello-world`.

   `icon` picks from a small curated set in `frontend/sidebar/
   sidebar_plugin_registry.js`'s `_ICON_PATHS` (kept in sync with
   `KNOWN_SIDEBAR_ICONS` in `src/plugins/manifest.py`) — currently `plug`
   (default), `antenna`, `map`, `list` (generic), plus `chart`, `message`,
   `terminal`, `grid`, `topology`, `rf`, `pager`, `dapnet`, `reticulum`,
   `lorawan`, `gear`, `usb` (exact copies of Meshpoint's own existing sidebar
   icons for those pages — reuse one that already fits your plugin's
   domain; `usb` is a single fill-path glyph in its own larger viewBox
   rather than the standard 24x24 stroke style every other entry shares,
   handled via `_ICON_VIEWBOX` if you're adding something similarly
   unusual). Deliberately a name, not raw SVG from the manifest — that would
   let a plugin's `plugin.toml` inject arbitrary markup into every viewer's
   sidebar. An unrecognized key falls back to `plug` rather than breaking
   the page.

2. Your frontend script supplies the page content — same
   `mount(rootEl)`/`show()`/`hide()` shape `"panel"` uses:

   ```js
   // plugins/apps/hello-world/frontend/hello_world.js
   window.registerSidebarPage({
       route: 'hello-world',       // must match plugin.toml's sidebar.route
       make: () => ({
           mount(rootEl) {
               rootEl.innerHTML = '<div class="plugin-page"><h2>Hello, World.</h2></div>';
           },
           show() {},
           hide() {},
       }),
   });
   ```

   `.plugin-page` (`frontend/css/dashboard.css`) gives you sane padding and
   base typography for free — optional, use your own markup/CSS if you'd
   rather.

3. That's it — no manual route registration. `src/plugins/assets.py`'s
   `sidebar_descriptor_tags()` pushes your `{route, label, category, icon}`
   onto `window.MESHPOINT_SIDEBAR_PLUGINS` at serve time; `frontend/sidebar/
   sidebar_plugin_registry.js`'s `mountPluginSidebarPages()` (called from
   `app.js`, *before* the Router/sidebar are built) reads that plus your
   `registerSidebarPage()` call and builds the actual `<li>` + `<section>`.
   A page declared in `plugin.toml` whose script never calls
   `registerSidebarPage()` logs a console warning and is silently skipped
   (never blocks the rest of the app).

## Injecting into another page (`"hook"`)

`"sidebar"` gives your plugin its own space — a whole top-level page.
`"hook"` is different: it lets your plugin inject content into a page
**another plugin owns**, instead of having a page of your own. The other
plugin has to opt in as a *host* first
— see [Making your own page hookable](#making-your-own-page-hookable) below
if you're the one writing the host, not just the hook.

The reference pair is **Hello World** (the host —
[`plugins/apps/hello-world/`](../plugins/apps/hello-world/)) and **Hello
World Hook** (the hook —
[`plugins/apps/hello-world-hook/`](../plugins/apps/hello-world-hook/)).
With both enabled, opening the Hello World page shows its usual content
plus a second box below it, rendered by the hook plugin.

A second, less toy example: **RTL-SDR** (`plugins/apps/rtlsdr/`) is the
shared host page every RTL-SDR decoder plugin hooks a tab into — the
built-in Listener page these all used to live on directly (via `"panel"`)
is gone entirely now. **DAB+** moved first — it dropped `"panel"` from
`provides`; both its player and its Config panel hook into the RTL-SDR page
instead (`plugins/apps/dab/frontend/dab_panel.js` / `dab_config_panel.js`),
each with its own `label` (see below) so they show up as two switchable
tabs rather than one long stacked page. Moving wholesale rather than
duplicating mattered here for a concrete reason, not just tidiness: DAB+'s
player looks up its `<audio>` element by a hardcoded id, not scoped to its
own mounted root, so two live instances at once would have fought over it.
**P2000, Pagers, POCSAG, RTL433, ACARS, ADS-B and finally Radio itself
followed** once the mechanism was proven on DAB+ — each a mechanical
single-hook migration (drop `"panel"`, add `"hook"` with `host = "rtlsdr"`,
swap `registerListenerPanel` for `registerPageHook`, and — Radio only —
convert every DOM lookup from `document.getElementById` to
`this._root.querySelector` since a hooked panel no longer owns the whole
page). Radio moving off it was the last piece; nothing RTL-SDR-related is
built into core anymore.

1. List `"hook"` in `provides` and fill in `[hook]` with the target host's
   id — another plugin's `[sidebar].route`:

   ```toml
   # plugins/apps/hello-world-hook/plugin.toml
   provides = ["hook"]

   [frontend]
   scripts = ["frontend/hello_world_hook.js"]
   styles = ["frontend/hello_world_hook.css"]   # optional

   [hook]
   host = "hello-world"      # must match the host's own [sidebar].route
   ```

   Not validated against real plugins at manifest *parse* time — `plugin.toml`
   alone can't know what other plugins exist. It IS enforced at *enable*
   time though: `PUT /api/plugins/{id}` (Settings → Plugins) refuses to
   enable a hook plugin whose host isn't currently enabled, and disabling
   a host cascades to disable every plugin hooking into it, reported back
   so it's never a silent side effect (`src/api/routes/plugin_routes.py`).
   The Settings → Plugins page greys out a hook's toggle with a tooltip
   until its host is on. A host that exists but never calls
   `mountPageHooks()` (see below), or a `host` string matching no
   installed plugin's route at all, still isn't caught until then — the
   plugin loads fine, it just renders nowhere, same "silently skipped"
   philosophy `registerSidebarPage()` already uses for a dangling
   descriptor.

2. Your frontend script registers content for that host — same
   `mount(rootEl)`/`show()`/`hide()` shape `"panel"`/`"sidebar"` both use:

   ```js
   // plugins/apps/hello-world-hook/frontend/hello_world_hook.js
   window.registerPageHook({
       host: 'hello-world',        // must match plugin.toml's [hook].host
       label: 'My Plugin',         // optional -- see below
       make: () => ({
           mount(rootEl) {
               rootEl.innerHTML = '<p>Hello from a hook.</p>';
           },
           show() {},
           hide() {},
       }),
   });
   ```

   `label` only matters if the host ends up with more than one hook
   registered against it — with just yours, it renders directly, no tab
   chrome at all. Two or more get an automatic small tabbar (built by
   `mountPageHooks()` itself, nothing the host has to do), `label` as the
   button text — falls back to `"Plugin N"` if you skip it, so still
   worth setting once you know you might share a host with something
   else.

3. That's it on the hook side — no manual wiring. `frontend/sidebar/
   page_hook_registry.js` is the seam: every plugin's frontend script runs
   before `app.js` (same guarantee `"panel"`/`"sidebar"` already rely on),
   so your `registerPageHook()` call has always landed before any host
   looks up what's registered for it.

### Making your own page hookable

If you're writing the **host** — a `"sidebar"` (or, later, another kind of)
page you want other plugins to be able to attach into — call
`window.mountPageHooks(hostId, containerEl)` once from inside your own
`mount(rootEl)`, after rendering your own content, passing an element for
hook content to render into:

```js
// plugins/apps/hello-world/frontend/hello_world.js
mount(rootEl) {
    const hasHooks = (window.MESHPOINT_PAGE_HOOKS || [])
        .some((h) => h.host === 'hello-world');
    rootEl.innerHTML = `
        <div class="plugin-page">
            <h2>Hello, World.</h2>
            ${hasHooks ? '<div data-hooks></div>' : ''}
        </div>
    `;
    if (hasHooks) {
        window.mountPageHooks('hello-world', rootEl.querySelector('[data-hooks]'));
    }
},
```

`hostId` is whatever your page is known by — for a `"sidebar"` plugin,
that's your own `[sidebar].route`. Checking `window.MESHPOINT_PAGE_HOOKS`
first and only adding the extra container when something's actually
registered means your page renders identically to before for anyone who
hasn't installed a hook plugin targeting it — a host plugin costs nothing
extra when nobody hooks into it. `mountPageHooks()` itself is a no-op if
you pass it `null`/no hooks are registered, so skipping that check and
always calling it is also safe, just leaves a stray empty container element
in your markup.

`mountPageHooks()` gives each hook its own wrapper `<div>` under your
container automatically — you never need to worry about two hooks' `mount()`
calls colliding (a panel's `mount(el)` typically does `el.innerHTML = ...`,
which would wipe out a sibling's content if two hooks shared one element
directly). With two or more hooks it also builds the small tabbar
mentioned above, keeping only the active one's panel visible and "live".

**If your page has its own `show()`/`hide()`** (called by the router on
navigation, unlike `mount()` which runs once at boot regardless of
visibility) **and a hook you host depends on that lifecycle** — e.g. its
own `show()` is what kicks off a data fetch or starts status polling, the
same way `panel`-seam tabs already work — you need to propagate it
yourself. `mountPageHooks()` returns `{show(), hide()}` for exactly this
(with multiple hooks, these forward to whichever tab is currently active;
switching tabs handles hide()-the-old/show()-the-new on its own):

```js
make: () => {
    let hookGroup = null;   // closure-scoped so show()/hide() below can reach it
    return {
        mount(rootEl) {
            // ...render your own content...
            hookGroup = window.mountPageHooks('your-host-id', hookContainerEl);
        },
        show() { if (hookGroup) hookGroup.show(); },
        hide() { if (hookGroup) hookGroup.hide(); },
    };
},
```

Easy to miss — a hook that never receives `show()` will render its initial
markup fine but silently never load any data, with no error anywhere. Not
needed if your own page has no meaningful `show()`/`hide()` of its own
(Hello World's are no-ops, so the simpler example above skips this).

## Adding a topbar chip (`"topbar"`)

A persistent status badge in the topbar, the same visual language as the
built-in Meshtastic/MeshCore/Serial/Pager/Reticulum chips — unlike those,
which are fed by `TopbarController`'s own shared `GET /api/config` poll,
a plugin chip has no core-config-driven data source or enabled flag to
gate on. It's mounted unconditionally the moment your plugin registers it
(the plugin being loaded at all already means it's enabled), and owns its
own data fetching and visibility from there — hide yourself (`el.hidden`)
whenever you have nothing worth showing.

No `[topbar]` TOML table exists — a chip is fully custom-rendered, there's
no route/label/icon to declare upfront the way `"sidebar"` has. You do
still need at least one `[frontend].scripts` entry (enforced the same way
as `panel`/`sidebar`/`hook`), since the chip itself is registered from
JS, not Python — nothing on the backend needs touching for this seam at
all.

`plugins/apps/dapnet/frontend/dapnet_topbar_chip.js` is the real, shipped
example, reusing DAPNET's own `GET /api/dapnet/status` (the same endpoint
its page-level status card already polls) rather than any new endpoint:

```js
class MyPluginTopbarChip {
    mount(rootEl) {
        this._el = rootEl;
        this._el.hidden = true;   // nothing to show yet
    }

    init() {
        this._refresh();
        this._timer = setInterval(() => this._refresh(), 10_000);
    }

    destroy() {
        clearInterval(this._timer);
    }

    async _refresh() {
        const res = await fetch('/api/my-plugin/status', { credentials: 'same-origin' });
        const data = res.ok ? await res.json() : null;
        this._el.hidden = !data;
        if (data) this._el.textContent = data.summary;
    }
}

window.registerTopbarChip({ id: 'my-plugin', make: () => new MyPluginTopbarChip() });
```

`window.registerTopbarChip({ id, make })` — `make()` returns an object
shaped like every existing chip:

- `mount(rootEl)` — required. `rootEl` is an already-appended, empty
  wrapper `<span>` — build your initial DOM into it. Reuse the shared
  `.topbar-serial` classes (brand/lamp/call/sep/freq spans — see
  `plugins/apps/reticulum/frontend/reticulum_topbar_chip.js` or
  `plugins/apps/dapnet/frontend/dapnet_topbar_chip.js` for shipped
  self-polling examples) if you want the same visual language as the
  built-in chips, or render whatever you want — nothing enforces the shape.
- `init()` — optional, called once, immediately after `mount()`. Start
  your own polling/timers here, not in `mount()` — this ordering
  guarantee is why `DapnetTopbarChip` above splits the two.
- `destroy()` — optional, called on teardown. No real teardown path
  exists in the app today (the dashboard never tears down its own
  `TopbarController`); kept for symmetry and any future one.

Registration order matches every other frontend seam in this doc — your
plugin's `<script>` tag runs before `app.js` ever constructs
`TopbarController`, so `window.registerTopbarChip` calls from any number
of plugins are all recorded before anything tries to mount them. No
capability-declaration enforcement happens at runtime the way
`add_router`/`add_listener` enforce theirs (there's no backend call to
gate) — declaring `"topbar"` in `provides` is what makes the manifest
loader require your `[frontend].scripts` entry, which is the real,
useful check.

## Adding a background service (`"service"`)

`"listener"` is an RTL-SDR subprocess. `"capture"` is a source feeding the
packet pipeline. `"service"` is neither — it's for a plugin that just
needs to **run something async for the life of the app**: attach to an
external daemon, hold a connection open, poll a device, run a router. The
shipped example is **Reticulum** (`plugins/apps/reticulum/`), whose
`LxmfService` attaches to a local `rnsd` shared instance as an RNS/LXMF
client; **Hello Service** (`plugins/apps/hello-service/`) is the minimal
one — a no-op that just logs when it starts and stops.

Backend-only: no `[service]` TOML table, no frontend script required.
`backend/__init__.py`:

```python
def register(reg) -> None:
    from .my_service import MyService

    def build(context):
        # context is a src.api.service_registry.ServiceContext:
        #   .pipeline    -- the live packet pipeline (.database, .packet_repo)
        #   .ws_manager  -- the shared WebSocketManager
        #   .config      -- the full AppConfig
        return MyService(
            db=context.pipeline.database,
            ws_manager=context.ws_manager,
            # ... your own plugins.<id>.* config from reg.config ...
        )

    def wire(service, context):
        # optional -- runs between build() and start(), e.g. to hand the
        # built service to your routes module's module-level state
        routes.init_routes(service)

    reg.add_service("my-plugin", build, wire)
```

Your service object needs `async start()` and `async stop()`:

- **`build(context)` is called once**, right after `pipeline.start()` — so
  `context.pipeline.packet_repo` is safe to read (it raises before then).
  Return `None` to opt out (e.g. an optional dependency isn't installed).
- **`start()` runs immediately** after `wire()`. **`stop()` runs on
  shutdown**, newest-registered service first.
- **A failure is isolated.** If `build`/`wire`/`start` raises, it's logged
  (`plugin service <name> failed to start -- skipping it`) and meshpoint
  starts normally — the same guarantee the loader gives `register()`. A
  `stop()` that raises doesn't hold up the rest of shutdown either.
- **This runs in-process**, on the server's event loop — an async
  `start()` that blocks blocks startup. A one-time synchronous init
  (Reticulum's `RNS.Reticulum()`, which must run on the main thread) is
  acceptable to block on briefly; anything ongoing belongs in a task the
  service spawns and cancels in `stop()`.

Keep the service class importable without FastAPI (defer heavy imports
into `register()`) so `backend/tests/` can exercise it on a dev machine —
see [Testing](#testing).

## Adding a non-RTL-SDR capture source + protocol (`"capture"`/`"protocol"`)

`"listener"` assumes RTL-SDR: a subprocess sharing one dongle, idle until
its own `/start` route fires. A capture source that's genuinely different
hardware (a serial-connected device, say) and introduces a protocol
identity that isn't one of the closed `Protocol` enum's members needs two
separate capabilities instead — kept separate, not combined, since a
plugin might only need one (a new protocol classifying packets that arrive
over an *existing* capture source, or a new capture source producing
packets in an *existing* protocol shape). `plugins/apps/dapnet/` is the
real, shipped example both are built from — DAPNET/POCSAG paging over a
serial-connected companion board, the first plugin to use either seam:

```python
# plugins/apps/dapnet/backend/__init__.py
from __future__ import annotations


def register(reg) -> None:
    from . import config_routes, decode, firmware_routes, routes, settings_routes, state
    from .listener import DapnetSerialSource

    state.init(reg.config)
    reg.add_router(routes.router)
    reg.add_router(config_routes.router)
    reg.add_router(firmware_routes.router)
    reg.add_router(settings_routes.router)

    def build() -> tuple[DapnetSerialSource, ...]:
        return tuple(
            DapnetSerialSource(
                serial_port=dev.get("serial_port"), serial_baud=dev.get("serial_baud", 115200),
                label=dev.get("label", ""), status_poll_interval_s=state.status_poll_interval_s(),
            )
            for dev in state.devices()
        )

    def wire(sources, pipeline) -> None:
        routes.init_routes(pipeline.packet_repo)
        config_routes.init_routes(dapnet_sources=list(sources))
        firmware_routes.init_routes(dapnet_sources=list(sources))
        settings_routes.init_routes(
            dapnet_sources=list(sources), packet_repo=pipeline.packet_repo,
        )

    reg.add_capture_source("dapnet", build, wire)
    reg.add_protocol(
        "dapnet", capture_prefix="dapnet",
        adapt=lambda raw: decode.adapt_event(raw.payload, signal=raw.signal),
        tier=state.tier,
    )
```

A few things that only matter for this pair:

- **`build()` runs before `wire()`, and before the pipeline starts.**
  `add_capture_source`'s sources are drained into the pipeline's capture
  coordinator *before* `pipeline.start()` is called (a source added after
  that point never gets a reader task); `wire()` only runs once
  `pipeline.start()` has completed, since `pipeline.packet_repo` raises
  until then. You never need to sequence this yourself — the core wiring
  (`src/api/server.py`'s `_build_pipeline`/`lifespan`) already calls
  `build_all()`/`wire_all()` at the right points.
- **Your `Packet`s need an identity that isn't a real `Protocol`/`PacketType`
  member.** Construct them with `OpenProtocol("dapnet")` /
  `OpenPacketType("dapnet_alpha")` (`src/models/packet.py`) instead —
  plain-string subclasses that expose `.value` and behave identically to a
  real enum member (`==`, hashing, f-strings, DB storage) at every one of
  the ~20 existing `packet.protocol.value`-style call sites across the
  codebase, with zero changes needed at any of them. `Protocol.parse(value)`
  / `PacketType.parse(value)` (used when reconstructing a `Packet` from
  storage) already fall back to these for a value the closed enum doesn't
  recognize — you don't call them yourself, `PacketRepository` does.
- **`capture_prefix` is a `str.startswith()` match, checked in registration
  order.** `raw.capture_source` for a capture-source-owning plugin's own
  sources is that source's `.name` (e.g. `"dapnet"`, or `"dapnet_ttgo"` for
  a labeled second device) — `capture_prefix="dapnet"` matches both.
- **`tier`'s two outcomes are for noise, not errors.** `"ignore"` is for
  traffic nobody ever wants to see (return early, nothing stored, nothing
  shown); `"blacklist"` is for traffic worth confirming is still arriving
  live (shown over the WebSocket feed) but not worth keeping in the
  packets table forever (DAPNET's own network housekeeping/time-sync
  beacons, in its case). Anything else — the normal case — return `None`
  and the packet is stored and broadcast exactly like any other protocol's.

## Your plugin's own config

`plugins.<id>` in `local.yaml` is entirely yours — Meshpoint only ever
reads `plugins.<id>.enabled` (the loader's enable gate); everything else is
opaque and handed to `reg.config` verbatim, never validated against the
core schema:

```yaml
plugins:
  acars:
    enabled: true
    freqs: [131.525, 131.725, 131.800, 131.825]   # your own keys
    gain: 34
    device: 0
```

Validate what you read from `reg.config` yourself and fall back sanely —
config is user-edited YAML, a typo shouldn't crash your plugin. ACARS's
`_normalize_frequencies()` (`plugins/apps/acars/backend/listener.py`) is a
small worked example: anything that isn't a non-empty list of stringifiable
entries falls back to a sane default instead of starting `acarsdec` with no
channels.

There's no plugin-contributed settings *UI* yet (see
[Current limitations](#current-limitations)) — for now, document your keys
in your plugin's `README.md` and expect the operator to hand-edit
`local.yaml` or use `docs/CONFIGURATION.md`'s pattern as a model.

## System dependencies

If your plugin needs anything beyond Python (`acarsdec`/`libacars` for
ACARS), write a `setup.sh` and list its apt packages in `[deps]`. It's
**never** run automatically. The operator runs it once, either directly:

```sh
sudo bash /opt/meshpoint/plugins/apps/<id>/setup.sh
```

or through the friendlier CLI wrapper, which shows the apt list + script
path and confirms first:

```sh
sudo meshpoint plugin setup <id>
```

Either is passwordless: `config/sudoers-meshpoint` grants NOPASSWD for
`/opt/meshpoint/plugins/apps/*/setup.sh` and `/opt/meshpoint/src/plugins/
apps/*/setup.sh` (both tiers) -- **but only for the absolute path**, since
sudo matches argv literally and can't resolve a relative one against an
unknown cwd. `sudo bash plugins/apps/<id>/setup.sh` (relative, even from
`/opt/meshpoint`) still works, just prompts for a password.
`meshpoint plugin setup` always passes the resolved absolute path.

A plugin that also declares `[deps] check` (next section) gets a **Run
setup** button on its Settings → Plugins row when the check says setup is
needed: it runs that same `sudo bash setup.sh` server-side and streams the
output into a modal (`POST /api/plugins/{id}/setup/stream`, admin-only,
audited as `config.plugin_setup`), then re-probes `check` and offers Enable
+ Restart on success. Same script, same sudoers grant — just no SSH needed.
Only one setup runs at a time; there's a 30-minute cap.

Make your script idempotent — `setup.sh` should check whether it already
did its job (ACARS checks `shutil.which`-equivalent for `acarsdec` on
`PATH`) and exit cleanly instead of reinstalling every time it's re-run.

### Letting the dashboard show "setup needed"

Optionally add a `check.sh` and point `[deps] check` at it. It's a probe,
not an installer: exit `0` when every dependency is in place, non-zero
otherwise, and print what's missing to stdout. The loader runs it
(unprivileged, ~15s cap) for each enabled plugin at boot, and Settings →
Plugins shows the verdict on that plugin's row — **"⚠ Setup needed"** with
your message, or **"✓ Dependencies installed"** — instead of the always-on
"Requires: … run setup" hint. A **Re-check** button re-runs it
(`POST /api/plugins/{id}/check`) so running setup on the device clears the
warning without a restart. `meshpoint plugin check [<id>]` does the same from
the CLI — and unlike `meshpoint plugin list` (which just echoes the boot-time
snapshot), it re-runs the probe live. Both run it **inside the service
process**, as the `meshpoint` service account — the exact context the loader
uses at boot — so it doesn't matter which shell (SSH, the dashboard's web
Terminal) you call the CLI from.

The script itself must run as the unprivileged `meshpoint` service account —
**no `sudo`**.
Checking a file under `/etc/systemd/system` or `systemctl is-enabled <unit>`
both work without root; installing anything does not (that's `setup.sh`'s
job). Every shipped plugin has one to copy from — the from-source builds
(`acars`, `adsb`, `radio`, the `multimon-ng` trio) just do `command -v
<binary>`; `rtlsdr` also greps its DVB-T blacklist file; `reticulum` does
`venv/bin/python3 -c "import LXMF"` plus an installed, enabled
`rnsd.service`; `dapnet` (no build step of its own) checks `pyserial`
imports and exits 0 with an `arduino-cli` note rather than nagging.
`tests/test_plugin_manifest.py` fails if a plugin ships a `setup.sh`
without a matching `check.sh`.

## Testing

Keep your listener/decode logic importable without FastAPI, so it unit-tests
on a machine that doesn't have the full dependency stack installed (this
project's own dev Mac included) — that's the entire reason `register()`
defers its imports (see above). `backend/tests/test_<whatever>.py` should
import straight from `backend.<whatever>`, not through `backend/__init__.py`:

```python
# plugins/apps/acars/backend/tests/test_listener.py
from plugins.apps.acars.backend.listener import AcarsListener
```

If you do need to test something that touches FastAPI (a routes module),
gate the test class behind a `fastapi` import check — mirrors
`tests/test_plugin_loader.py::TestShippedAcarsPlugin`:

```python
try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "needs fastapi (CI / Pi only)")
class TestSomethingThatNeedsFastapi(unittest.TestCase):
    ...
```

CI runs `ruff check src/ tests/ plugins/` and `pytest tests/ plugins/` —
your plugin's tests are part of the same run, so `plugins/apps/<id>/`,
`backend/`, and `backend/tests/` all need an `__init__.py` to be importable.

## Managing your plugin once it's installed

An operator doesn't need to touch YAML by hand for the common cases:

- **Settings → Plugins** in the dashboard lists every discovered plugin,
  toggles `plugins.<id>.enabled`, shows apt-deps + a live dependency
  verdict (for a plugin with a `[deps] check` script) or the setup-script
  hint, a **Re-check** button, a **Run setup** button that streams
  `setup.sh` output into a modal when setup is needed, and (for a
  community, non-`locked` plugin) a Delete button that removes
  `plugins/apps/<id>/` outright.
- `meshpoint plugin list` / `meshpoint plugin check [<id>]` /
  `sudo meshpoint plugin setup <id>` — the CLI equivalents, usable from SSH
  or the dashboard's own web Terminal (it's a real shell on the device).
  `check` re-runs the `[deps]` probes live (the `list` verdict is a
  boot-time snapshot).

Both are read from `discover_plugins()` fresh each time, so nothing needs
telling about a new plugin beyond it existing on disk with a valid
`plugin.toml`.

## Publishing a plugin repository

You can keep your plugins in your own GitHub repo and let operators add it
as a **plugin source** (Settings → Plugins → *Add source*).

### Repo layout

Mirror Meshpoint's own dirs — one folder per plugin/theme, folder name ==
manifest `name`:

```
your-repo/
  repo.json               # the browse catalog (generated, see below)
  apps/
    my-thing/
      plugin.toml
      backend/__init__.py
      frontend/...
  themes/
    my-palette/
      theme.json
      theme.css
```

### `repo.json`

A catalog at the repo root, one entry per plugin/theme:

```json
{
  "meshpoint_repo": 1,
  "name": "your repo's display name",
  "plugins": [
    { "id": "my-thing", "kind": "app", "path": "apps/my-thing",
      "version": "0.2.0", "meshpoint_api": 1, "provides": ["sidebar"],
      "description": "...", "author": "...", "homepage": "...",
      "has_setup": false }
  ],
  "themes": [
    { "id": "my-palette", "kind": "theme", "path": "themes/my-palette",
      "version": "1.0.0", "description": "...", "author": "..." }
  ]
}
```

Every field but `id`/`kind`/`path` mirrors the plugin's own `plugin.toml` /
`theme.json`. **Generate it — don't hand-write it.** Two ways:

- A standalone `make-repo-json.py` in your repo (Python 3.11+, no
  Meshpoint checkout needed) — the template repo ships one; it scans
  `apps/*/plugin.toml` + `themes/*/theme.json` and writes `repo.json`,
  warning about folder/name mismatches, unknown `provides`, duplicate ids.
- `meshpoint plugin index /path/to/your-repo --write` from a Meshpoint
  checkout — same output, using Meshpoint's own manifest validator.

Re-run whenever you bump a version. Meshpoint re-reads and re-validates the
real manifest on install, so the catalog is metadata only — a stale or
tampered `repo.json` can't smuggle anything in.

### How an operator uses it

1. **Add source** → paste the repo URL → an explicit trust confirmation
   (a source can install code that runs with the service's privileges, and
   its `setup.sh` runs as root).
2. **Browse** → Meshpoint fetches `repo.json` and shows what the repo
   offers, flagging what's already installed / has an update / needs a
   newer Meshpoint.
3. **Install** → downloads just that plugin's subtree from GitHub
   (`api.github.com/…/tarball/<ref>`, no `git` needed), rejects any unsafe
   archive member, re-validates the real `plugin.toml` with Meshpoint's own
   parser, and drops it in `plugins/apps/<id>/`. From there it's a normal
   drop-in — enable it, run setup if it needs it, restart. **Update** does
   the same in place and keeps the enabled state; uninstall is the list's
   existing Delete button. Provenance (source URL, ref, version) is
   recorded under `plugins.<id>.source` in `local.yaml`.

The source list lives in `local.yaml` (`plugin_sources:`), so it survives
restarts and self-updates.

## Current limitations

Don't build around these — if you need one, that's a signal to extend the
core seam (`src/plugins/registry.py`, `src/plugins/manifest.py`'s
`KNOWN_PROVIDES`), not to work around it inside a plugin:

- **No plugin-contributed settings sub-page seam.** Beyond raw
  `plugins.<id>` YAML (see above), a plugin can't render its own
  Configuration-style settings UI *inside the core Configuration page*.
  (The `"sidebar"` seam gets a plugin its own top-level *page*, and DAPNET's
  own "Settings" tab on that page is one way around this for a plugin
  that already has a page of its own — this is specifically about a
  Configuration/Settings-*style form living in core's own Configuration
  section*, for a plugin with no page to hang a tab off of.)

The non-RTL-SDR capture source + decoder-ownership gaps that used to be
listed here are solved — see [Adding a non-RTL-SDR capture source +
protocol](#adding-a-non-rtl-sdr-capture-source--protocol-captureprotocol)
above, proven out by DAPNET actually moving out of core onto it. The
generic topbar-chip gap that used to be listed here is solved too — see
[Adding a topbar chip](#adding-a-topbar-chip-topbar), also proven out by
DAPNET. And the "no seam for a plain background service" gap is solved —
see [Adding a background service](#adding-a-background-service-service),
proven out by **Reticulum** moving out of core onto it (its whole
`LxmfService` — RNS/LXMF client, announce handlers, peer roster — is now a
`"service"` plugin). Don't build around the one above either — if
you need it, that's a signal to extend the core seam
(`src/plugins/registry.py`, `src/plugins/manifest.py`'s
`KNOWN_PROVIDES`), not to work around it inside a plugin. Full
background: `memory/plugin-architecture-review.md`.

===========

A plugin author installs a pip dependency by writing a setup.sh that installs into meshpoint's venv (venv/bin/pip), not system Python. Here's the whole pattern.

1. plugin.toml

[deps]
setup = "setup.sh"
check = "check.sh"   # required whenever setup.sh exists — a test enforces this
2. setup.sh — installs into the venv, idempotently

#!/usr/bin/env bash
set -euo pipefail

# plugins/apps/<id>/setup.sh  ->  repo root is three levels up
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
VENV_PY="${REPO}/venv/bin/python3"
VENV_PIP="${REPO}/venv/bin/pip"

if "${VENV_PY}" -c "import somepackage" &>/dev/null; then
    echo "somepackage already installed -- skipping"
else
    echo "Installing somepackage into the venv ..."
    "${VENV_PIP}" install --quiet 'somepackage>=1.2'
fi
3. check.sh — unprivileged probe, mirrors setup.sh minus the installing

#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"

if "${REPO}/venv/bin/python3" -c "import somepackage" &>/dev/null; then
    echo "somepackage installed"
    exit 0
fi
echo "somepackage is not installed in the venv"
echo "run: sudo meshpoint plugin setup <id>"
exit 1
How it runs
Not automatic. The operator runs it once: sudo meshpoint plugin setup <id>, or the "Run setup" button in Settings → Plugins (streams the output into a modal, no SSH needed), or sudo bash /opt/meshpoint/plugins/apps/<id>/setup.sh.
All three are passwordless — config/sudoers-meshpoint grants NOPASSWD for /opt/meshpoint/plugins/apps/*/setup.sh (absolute path only).
The check.sh probe runs at boot and on demand; when it fails, Settings → Plugins shows "⚠ Setup needed" with the reason instead of letting the plugin load half-broken.
Reference implementation: plugins/apps/reticulum/setup.sh + check.sh do exactly this for lxmf.