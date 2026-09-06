# Hello Service plugin

The minimal reference plugin for the **service** seam: a lifespan-managed
background service — an object with async `start()` / `stop()`, started
right after the packet pipeline is up and stopped on shutdown, the same
shape as core's own `LxmfService` (Reticulum).

Use this seam for a plugin that just needs to *run something* for the life
of the app — attach to an external daemon, poll a device, keep a
connection open — rather than a subprocess listener (`listener`) or a
packet-pipeline source (`capture`).

This plugin does nothing but log on start and stop. It exists to prove the
seam works and to give a copy-paste starting point — and because it logs,
it's a handy probe for confirming the wiring fires on a real device.

## Enable it

```yaml
plugins:
  hello-service:
    enabled: true
```

Restart, then:

```sh
journalctl -u meshpoint --no-pager | grep hello_service
#   → hello-service started (context: pipeline=True ws_manager=True)

sudo systemctl stop meshpoint
journalctl -u meshpoint --no-pager | grep hello_service | tail -2
#   → hello-service started ...
#   → hello-service stopped          ← stop_all() ran on shutdown
```

There is nothing to see in the dashboard — a `service` plugin has no UI.
`GET /api/plugins` shows it as `loaded: true`.

## How it works

`plugin.toml` just declares the capability — no dedicated table, no
frontend script (unlike `sidebar`/`hook`/`topbar`):

```toml
provides = ["service"]
```

`backend/__init__.py`'s `register(reg)` registers the service:

```python
def register(reg) -> None:
    reg.add_service("hello-service", lambda context: HelloService(context))
```

- `build(context)` is called once, right after `pipeline.start()`. Return
  the service, or `None` to opt out (e.g. an optional dependency isn't
  installed).
- `context` is a `src.api.service_registry.ServiceContext`: `.pipeline`
  (the live packet pipeline — `.database`, `.packet_repo`), `.ws_manager`
  (the shared `WebSocketManager`), `.config` (the full `AppConfig`).
- `reg.add_service(name, build, wire=None)` — `wire(service, context)`, if
  given, runs between `build` and `start()`.
- The service's `async start()` runs immediately; its `async stop()` runs
  on shutdown, newest-registered first. A `stop()` that raises is logged
  and doesn't hold up the rest of shutdown.

Full write-up: [docs/PLUGINS.md](../../../docs/PLUGINS.md).

## Layout

```
plugin.toml                 manifest (provides = ["service"], no tables)
backend/__init__.py         register(reg) + the HelloService class
```
