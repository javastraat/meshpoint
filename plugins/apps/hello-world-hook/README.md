# Hello World Hook plugin

The minimal reference plugin for the **hook** seam: content injected into
*another* plugin's already-rendered page, instead of owning a page/tab of
its own (that's what `panel`/`sidebar` are for — see the ACARS and Hello
World plugins for those).

Targets the [Hello World](../hello-world/) plugin's sidebar page. With both
enabled, opening Networks → Hello World shows the usual "Hello, World."
content plus a second box below it, rendered by this plugin — proof that a
plugin can attach into a page it doesn't own.

## Enable it

Needs the [`hello-world`](../hello-world/) plugin enabled too (its page is
what this one hooks into — with only `hello-world-hook` enabled, there's no
host page for it to render into, so nothing shows up anywhere):

```yaml
plugins:
  hello-world:
    enabled: true
  hello-world-hook:
    enabled: true
```

Restart, then Networks → Hello World in the sidebar.

## How the hook works

`plugin.toml`'s `[hook]` table names the target host by its `[sidebar].route`:

```toml
provides = ["hook"]

[hook]
host = "hello-world"      # must match hello-world's plugin.toml [sidebar].route
```

The frontend script registers content for that host:

```js
// frontend/hello_world_hook.js
window.registerPageHook({
    host: 'hello-world',
    make: () => ({
        mount(rootEl) { rootEl.innerHTML = '<p>Hello from a hook.</p>'; },
        show() {},
        hide() {},
    }),
});
```

`frontend/sidebar/page_hook_registry.js` is the seam itself: every plugin's
frontend script runs before `app.js`, so every `registerPageHook()` call has
already landed by the time a host's own `mount()` runs and calls
`window.mountPageHooks(hostId, containerEl)` to render whatever's registered
for it. A host page has to opt in to being hookable — Hello World's own
`frontend/hello_world.js` does this, and only adds the extra container
element to its markup when at least one hook plugin actually targets it, so
the page renders identically to before for anyone who hasn't installed one.

Full write-up: [docs/PLUGINS.md](../../../docs/PLUGINS.md).

## Layout

```
plugin.toml                      manifest ([hook] table, [frontend])
backend/__init__.py              register(reg) -- a no-op; nothing to register
frontend/hello_world_hook.js     the injected content (registerPageHook)
frontend/hello_world_hook.css    demonstrates [frontend].styles for a hook plugin
```
