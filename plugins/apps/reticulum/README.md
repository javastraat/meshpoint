# Reticulum plugin

Native **Reticulum / LXMF** messaging — meshpoint's own LXMF delivery
destination on the local `rnsd` shared instance, plus the peer roster built
from received announces.

> **Status: Phase 1 scaffold.** This plugin is being extracted from core
> (`src/reticulum/`, `src/api/routes/reticulum_routes.py`, …). Core's own
> Reticulum service and routes are still authoritative and still what a
> normal install runs. Do **not** enable this plugin on a device that has
> `reticulum.enabled: true` in `local.yaml` — you'd get two RNS client
> attachments fighting over the same identity. The migration (disable
> core, enable plugin, move config) is Phase 4. See
> [`memory/plugin-reticulum.md`](../../../memory/plugin-reticulum.md).

## What it provides (Phase 1)

| Seam | What |
|---|---|
| `service` | `LxmfService` — RNS/LXMF client attach, started right after the packet pipeline is up (`src.api.service_registry`), stopped on shutdown |
| `routes` | `/api/reticulum/{status,peers,messages,send,announce}` |

Coming in Phase 2: the Reticulum **page** (`sidebar`) and the **topbar
pill** (`topbar`), plus the RNode/backbone settings tab (`config_routes`).

## Config

`plugins.reticulum.*` — the same shape core's `AppConfig.reticulum` has
today (`backend/state.py` documents every key and its default). Nothing is
read from core's `reticulum:` section by this plugin.

```yaml
plugins:
  reticulum:
    enabled: true
    display_name: "Meshpoint"
    reticulum_config_dir: data/reticulum/rns_config
    identity_path: data/reticulum/identity
    lxmf_storage_dir: data/reticulum/lxmf
```

The `rnode_*` / `backbone_*` keys are held in `state.py` for Phase 2's
settings tab; they're consumed by `scripts/write_rnsd_config.py` (rnsd's
own interfaces), which still reads core's `reticulum:` section until
Phase 5.

## Layout

```
plugin.toml                 manifest (provides = ["service", "routes"])
backend/
  __init__.py               register(reg) -- add_router + add_service
  state.py                  plugins.reticulum.* config (defaults mirror core)
  lxmf_service.py           the RNS/LXMF client (moved from src/reticulum/)
  peer_repo.py              reticulum_peers table access (moved from src/storage/)
  routes.py                 /api/reticulum/* (moved from src/api/routes/)
  tests/
```

Full write-up: [docs/PLUGINS.md](../../../docs/PLUGINS.md).
