# Meshpoint security — todo & findings log

Running list of security issues, hardening items, and fixes for Meshpoint.
A friend is auditing the codebase — new findings go under **Incoming findings**
with a date and reporter, then move to **Fixed** once patched (with commit +
verification evidence).

See `memory/project_m1_meshpoint.md` for wider session context and
`memory/reticulum_todo.md` for the Reticulum plugin backlog.

Last updated 2026-09-09 (file created, seeded from the security-hardening
backlog in `project_m1_meshpoint.md`).

---

## Threat model / known-and-accepted tradeoffs

Read this before filing a finding — some of these are deliberate.

- **The web terminal is root-equivalent by design.** `config/sudoers-meshpoint`
  grants `NOPASSWD` for `pip install *` and `plugins/apps/*/setup.sh`, so an
  authenticated admin can trivially get root from Ops → Terminal. This is
  documented in `command_catalog.py`'s docstring and the sudoers file's own
  comments. The real security boundary is `require_admin` auth, **not**
  root-vs-non-root once authenticated. Items 2–3 below aim to shrink this
  surface anyway.
- **Viewer vs admin** is the primary authz boundary. Viewer-role lockdown was
  done 2026-07-06 (`0c1cd41`) — viewers get 403 + toast on write routes
  (`config_routes.py`, `messages.py`, `nodeinfo_routes.py`,
  `position_broadcast_routes.py`, `telemetry_broadcast_routes.py` all gated).
- **Hosted `.mu` pages are served non-executable on purpose** (Reticulum
  plugin) — dynamic content only via generated pages or token substitution.
- Passwords live only in `local.yaml`, never returned in GET responses.

---

## Security hardening backlog

Priority order is the user's own (set 2026-09-08).

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | **HTTPS/TLS option** | 🟢 Built, partially live-verified | `dashboard.tls_enabled` / `tls_cert_path` / `tls_key_path` / `tls_port` (default 8443). Self-signed cert via bundled `cryptography` (no new dep), `src/tls_cert.py`. SAN covers every `hostname -I` address + hostname + `<hostname>.local` + `127.0.0.1`/`localhost`; auto-regenerates at startup if the address set drifted. `:8080` becomes a 308-redirect-only listener when TLS is on (two `uvicorn.Server`s via `asyncio.gather`). 28 tests (`test_tls_cert.py` ×12, `test_serve.py` ×13, `test_banner_sources.py` ×3). Boot log verified on ti-meshpoint. **Still owed:** real browser round-trip against all 3 addresses (LAN IP / Tailscale IP / `sensecap.local`) — confirm only the self-signed warning appears, not also a hostname-mismatch warning. |
| 2 | **Move services off root onto `meshpoint` user** | 🔴 Not started | Explicitly longer-term ("to limit attack surface"). Self-update chain's `pip install` runs as root via `config/sudoers-meshpoint` NOPASSWD. |
| 3 | **Web terminal → opt-in plugin** | 🔴 Not started, needs design | Currently core, admin-gated but root-equivalent. Move to an explicitly opt-in plugin like every other powerful/risky capability. "The root thing needs some thought" — not yet scoped/greenlit. |
| 4 | **USB companion udev rules too permissive** | 🔴 Not started, unprioritized | Every user on the box currently gets full serial-device access. Should be `0660` with a `dialout`-or-`meshpoint` group. |

---

## Incoming findings (from the audit)

_None yet. Template:_

```
### YYYY-MM-DD — <short title>  (reported by <name>)
- **Severity:** low / med / high / critical
- **Where:** file:line / route / component
- **Issue:** what's wrong and why it matters
- **Repro / PoC:** concrete steps or crafted input
- **Proposed fix:**
- **Status:** triaging / accepted / wontfix (reason) / fixed → see below
```

---

## Fixed

### 2026-09-08 — backup/restore tar-symlink extraction  (found by the user)
- **Severity:** high (arbitrary root-owned file write from a crafted upload)
- **Where:** `src/backup/restore_service.py`, `validate_archive_path()`
- **Issue:** the path/manifest allowlist check only ran for members where
  `.isfile()` was true, silently `continue`-ing past symlink / hardlink /
  device / FIFO members. That function is the only gate before
  `restore_finish.sh` (run as root via `sudo` from `launch_restore()`) does
  `tar -xzf ... -C "${EXTRACT_DIR}"`. Classic tar symlink attack: archive
  contains a symlink `data/x` → `/etc/cron.d` followed by a "regular" member
  `data/x/payload`; extraction writes the payload straight through the link to
  an arbitrary root-owned path. Upload route (`backup_routes.py:185`) always
  validates before restore, so fixing this one function closes the real flow.
- **Fix:** new `_reject_non_regular_members()` static method, called first
  inside `validate_archive_path`'s `tarfile.open` block — raises
  `RestoreValidationError` on any member that's neither `isdir()` nor
  `isfile()` (covers `issym()`/`islnk()`/`ischr()`/`isblk()`/`isfifo()`),
  rejecting the whole archive rather than skipping the member.
- **Tests:** 3 new cases in `tests/test_backup_restore_validate.py` (symlink,
  hardlink, FIFO — each alongside an otherwise-valid manifest+archive). Full
  backup suite: 13 passed, zero regressions.

### 2026-07-13 — `javascript:` URI in MeshCore firmware-update link  (caught during dev)
- **Severity:** low–med (stored/reflected XSS via a crafted release URL)
- **Where:** `frontend/js/configuration/meshcore_card.js` firmware-check render
- **Issue:** `latest_version` was HTML-escaped but `release_url` was not
  scheme-validated — entity-escaping text does nothing to stop a
  `javascript:` URI executing on click.
- **Fix:** `/^https?:\/\//i` allowlist check before rendering the link;
  `javascript:` / `data:` URIs silently dropped. Verified a legit GitHub URL
  still renders.

### 2026-07-06 — viewer role could hit write routes  (`0c1cd41`)
- Viewer-role lockdown: write routes now return 403 + toast for viewers.
  Verified route-by-route across `config_routes.py`, `messages.py`,
  `nodeinfo_routes.py`, `position_broadcast_routes.py`,
  `telemetry_broadcast_routes.py`.

---

## Notes for the auditor

- Dev is on the Mac; the live device is a Raspberry Pi (SenseCap M1 / RAK V2).
  Mac has no `fastapi` / `rns` / `lxmf` venv — route tests are gated behind
  `_HAS_FASTAPI` and run on CI / the Pi only.
- Tests: `python3.11 -m pytest tests/` (python3.14 has no pytest).
- Auth model: session cookie + JWT, `require_admin` / logged-in-required
  dependencies wired at the router level in `src/server.py`.
- Plugin asset resolution: `resolve_plugin_asset(manifests, id, path)` — has
  its own path-traversal guard, worth a look.
