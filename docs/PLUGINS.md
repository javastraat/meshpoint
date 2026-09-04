# Writing a Meshpoint Plugin

A how-to for building a new app plugin from scratch. For *using* an
already-written plugin (enabling it, setting its config, the Settings →
Plugins page, the `meshpoint plugin` CLI), see
[docs/CONFIGURATION.md § Plugins](CONFIGURATION.md#plugins) instead — this
doc is for the plugin author.

The canonical worked example is the shipped **ACARS** plugin —
[`plugins/apps/acars/`](../plugins/apps/acars/) — for routes/listener/panel,
the minimal **Hello World** plugin —
[`plugins/apps/hello-world/`](../plugins/apps/hello-world/) — for the
sidebar seam specifically, and **Hello World Hook** —
[`plugins/apps/hello-world-hook/`](../plugins/apps/hello-world-hook/) — for
the hook seam, injecting content into Hello World's own page. Every section
below points at the real file that does the thing being described. When in
doubt, go read that file; it's real, tested, shipped code, not a toy
example.

---

## What a plugin can do today

An app plugin is out-of-core code that hooks five seams:

- **Routes** — mount a FastAPI `APIRouter` under `/api/<whatever>`.
- **Listener** — register an RTL-SDR subprocess listener (built idle at
  startup, started on demand by its own `/start` route, sharing the one
  physical dongle with every other listener — see
  `src/audio/sdr_registry.py`).
- **Panel** — add a sub-tab to the dashboard's *Listener* page specifically.
- **Sidebar** — add a whole new top-level page of your own, placed under an
  existing sidebar section (Networks, Radio, Ops, Configuration, Settings).
- **Hook** — inject content into *another* plugin's already-rendered page,
  instead of owning a page/tab of your own. The other plugin has to opt in
  as a host (see [Injecting into another page](#injecting-into-another-page-hook)).

That's it. A plugin **cannot** (yet) add a packet *decoder* hooked into an
existing capture source, a new *capture source* of its own (non-RTL-SDR), or
a *plugin-contributed settings sub-page* (something more structured than raw
`plugins.<id>` YAML) — see [Current limitations](#current-limitations) at
the bottom before you start, in case what you want to build needs one of
those.

## Directory layout

```
plugins/apps/<your-id>/
    plugin.toml              # the manifest -- required
    setup.sh                 # optional: installs system deps (apt + build)
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
provides = ["listener", "routes", "panel"]
locked = false                            # optional, default false -- see below

[deps]                                    # optional
apt = ["cmake", "pkg-config"]
setup = "setup.sh"                        # relative path, must exist

[frontend]                                # required when "panel" or "sidebar" in provides
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
| `provides` | yes | Non-empty subset of `listener`, `routes`, `panel`, `sidebar`, `hook`. Calling a `PluginRegistry` method for a capability you didn't declare raises at register time — see [The `register(reg)` entry point](#the-registerreg-entry-point). |
| `locked` | no, default `false` | Only meaningful for **community** plugins. `true` marks a shipped/bundled community plugin (git-tracked, not a real user drop-in) so Settings → Plugins refuses to offer a Delete button for it — the same protection `plugins/themes/*/theme.json`'s `"locked": true` already gives the bundled theme pack. ACARS sets this. If you're writing a plugin someone else will `git clone` into their own `plugins/apps/`, leave it `false` (default) so they can delete it if they want to. |
| `[deps].apt` / `.setup` | no | System packages + a build script. **Never installed automatically** — the operator runs it themselves (`sudo bash plugins/apps/<id>/setup.sh` or `sudo meshpoint plugin setup <id>`, which just wraps the same script after showing what it does). |
| `[frontend].scripts` / `.styles` | scripts required iff `panel`, `sidebar` or `hook` in `provides` | Served at `/plugins/apps/<id>/<path>` — **only** the exact files listed here, from either tier, nothing else in the folder is reachable (`src/plugins/assets.py:resolve_plugin_asset`). |
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

Calling `add_router`/`add_listener` for a capability not in `provides`
raises `PluginRegistryError` — caught by the loader, logged, and the whole
plugin is skipped (one bad plugin never aborts the others or the app). See
`src/plugins/loader.py::load_plugins`.

## Adding a dashboard tab (`"panel"`)

1. List your id in `provides` and your JS (and optionally CSS) under
   `[frontend]`.
2. Your script runs at a fixed point in `index.html` — after
   `listener_panel_registry.js` (which defines the hook below) and before
   `app.js` builds `ListenerPanel` — so call this at your script's top
   level, not inside a DOMContentLoaded handler:

   ```js
   // plugins/apps/acars/frontend/acars_panel.js
   window.registerListenerPanel({
       tab: 'acars',                 // unique slug; becomes #lsn-tab-acars
       label: 'ACARS',               // tab button text
       make: () => new window.PagerPanel('acars', '/api/acars', 'ACARS', renderRow),
   });
   ```

   `make` is called once when `ListenerPanel` is constructed; it must
   return an object with `mount(rootEl)` / `show()` / `hide()`. ACARS reuses
   the core `PagerPanel` (start/stop/clear + a live message list) since its
   shape already fit; you can hand it any object satisfying that trio.
3. Your assets are served from `/plugins/apps/<id>/<path>` — exactly the
   paths you listed in `[frontend]`, nothing else. No manual wiring needed
   beyond step 2; `src/plugins/assets.py:inject_plugin_assets` injects the
   `<script>`/`<link>` tags automatically for every *loaded* panel plugin.

## Adding a top-level sidebar page (`"sidebar"`)

Unlike `"panel"` (a sub-tab inside the existing Listener page), `"sidebar"`
gives your plugin its own top-level nav entry, placed in an existing
sidebar section. There's no `reg.add_sidebar(...)` call — it's entirely
declarative, driven by `[sidebar]` in `plugin.toml` plus your own frontend
script:

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
   `lorawan`, `gear` (exact copies of Meshpoint's own existing sidebar
   icons for those pages — reuse one that already fits your plugin's
   domain). Deliberately a name, not raw SVG from the manifest — that would
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

`"panel"` and `"sidebar"` both give your plugin its own space — a Listener
sub-tab, or a whole top-level page. `"hook"` is different: it lets your
plugin inject content into a page **another plugin owns**, instead of
having a page of your own. The other plugin has to opt in as a *host* first
— see [Making your own page hookable](#making-your-own-page-hookable) below
if you're the one writing the host, not just the hook.

The reference pair is **Hello World** (the host —
[`plugins/apps/hello-world/`](../plugins/apps/hello-world/)) and **Hello
World Hook** (the hook —
[`plugins/apps/hello-world-hook/`](../plugins/apps/hello-world-hook/)).
With both enabled, opening the Hello World page shows its usual content
plus a second box below it, rendered by the hook plugin.

A second, less toy example: **RTL-SDR** (`plugins/apps/rtlsdr/`) is meant
to eventually replace the built-in Listener page entirely, one plugin at a
time. The shipped **DAB+** plugin is the first to move — it dropped
`"panel"` from `provides` and no longer appears on the Listener page at
all; both its player and its Config panel now hook into the RTL-SDR page
instead (`plugins/apps/dab/frontend/dab_panel.js` /
`dab_config_panel.js`). Moving wholesale rather than duplicating mattered
here for a concrete reason, not just tidiness: DAB+'s player looks up its
`<audio>` element by a hardcoded id, not scoped to its own mounted root,
so two live instances at once would have fought over it.

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

   Not validated against real plugins at parse time — if the host doesn't
   exist, or isn't enabled, or never calls `mountPageHooks()` (see below),
   your hook just never renders anywhere. No error, same "silently skipped"
   philosophy `registerSidebarPage()` already uses for a dangling
   descriptor.

2. Your frontend script registers content for that host — same
   `mount(rootEl)`/`show()`/`hide()` shape `"panel"`/`"sidebar"` both use:

   ```js
   // plugins/apps/hello-world-hook/frontend/hello_world_hook.js
   window.registerPageHook({
       host: 'hello-world',        // must match plugin.toml's [hook].host
       make: () => ({
           mount(rootEl) {
               rootEl.innerHTML = '<p>Hello from a hook.</p>';
           },
           show() {},
           hide() {},
       }),
   });
   ```

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
directly).

**If your page has its own `show()`/`hide()`** (called by the router on
navigation, unlike `mount()` which runs once at boot regardless of
visibility) **and a hook you host depends on that lifecycle** — e.g. its
own `show()` is what kicks off a data fetch or starts status polling, the
same way `panel`-seam tabs already work — you need to propagate it
yourself. `mountPageHooks()` returns the mounted panel objects for exactly
this:

```js
make: () => {
    let hookPanels = [];   // closure-scoped so show()/hide() below can reach it
    return {
        mount(rootEl) {
            // ...render your own content...
            hookPanels = window.mountPageHooks('your-host-id', hookContainerEl);
        },
        show() { hookPanels.forEach((p) => p.show && p.show()); },
        hide() { hookPanels.forEach((p) => p.hide && p.hide()); },
    };
},
```

Easy to miss — a hook that never receives `show()` will render its initial
markup fine but silently never load any data, with no error anywhere. Not
needed if your own page has no meaningful `show()`/`hide()` of its own
(Hello World's are no-ops, so the simpler example above skips this).

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

Make your script idempotent — `setup.sh` should check whether it already
did its job (ACARS checks `shutil.which`-equivalent for `acarsdec` on
`PATH`) and exit cleanly instead of reinstalling every time it's re-run.

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
  toggles `plugins.<id>.enabled`, shows apt-deps + the setup-script hint,
  and (for a community, non-`locked` plugin) offers a Delete button that
  removes `plugins/apps/<id>/` outright.
- `meshpoint plugin list` / `sudo meshpoint plugin setup <id>` — the CLI
  equivalents, usable from SSH or the dashboard's own web Terminal (it's a
  real shell on the device).

Both are read from `discover_plugins()` fresh each time, so nothing needs
telling about a new plugin beyond it existing on disk with a valid
`plugin.toml`.

## Current limitations

Don't build around these — if you need one, that's a signal to extend the
core seam (`src/plugins/registry.py`, `src/plugins/manifest.py`'s
`KNOWN_PROVIDES`), not to work around it inside a plugin:

- **No decoder seam.** A plugin can't hook into an *existing* capture
  source's packet stream (the way, say, a LoRaWAN-style decoder would) —
  only a new listener it owns entirely.
- **No non-RTL-SDR capture source seam.** `add_listener` is RTL-SDR-shaped
  specifically (shares `src/audio/sdr_registry.py`'s one-dongle-at-a-time
  claim). A plugin reading from a different physical source (another
  serial protocol, say) has no seam yet.
- **No plugin-contributed settings sub-page seam.** Beyond raw
  `plugins.<id>` YAML (see above), a plugin can't render its own
  Configuration-style settings UI. (The `"sidebar"` seam above gets a
  plugin its own top-level *page* — this is specifically about a
  Configuration/Settings-style *form* wired to `plugins.<id>`.)

These are anticipated, not hypothetical — the current best guess is
they'll matter when protocols like LoRaWAN or Pager eventually get
extracted into plugins the same way ACARS was (the top-level sidebar page
seam that used to be listed here was built for exactly that reason, proven
out with the Hello World reference plugin). Until a real plugin needs one
of the two above, though, building the seam speculatively risks guessing
the wrong shape. Full background: `memory/plugin-architecture-review.md`.
