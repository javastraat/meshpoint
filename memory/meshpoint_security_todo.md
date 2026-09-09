# Meshpoint security — todo & findings log

Running list of security issues, hardening items, and fixes for Meshpoint.
A friend is auditing the codebase — new findings go under **Incoming findings**
with a date and reporter, then move to **Fixed** once patched (with commit +
verification evidence).

See `memory/project_m1_meshpoint.md` for wider session context and
`memory/reticulum_todo.md` for the Reticulum plugin backlog.

Last updated 2026-09-09 — session: installer size caps + `ref` traversal;
#4 (udev `0666`→`0660`) fixed+verified; #5 (plugin-source SHA/pin) done;
#3 phase 1 (web terminal opt-in) done; **#2 phase 2 (drop the `sudo git` /
`sudo pip`-as-root grants) done AND Pi-verified 2026-09-09** — real
self-update ran on the new plain-git path, `sudo -l -U meshpoint` shows no
git grants + pip is `(meshpoint)`, venv has no root-owned files, service
healthy. **Only real work left: #2/#3 phase 3** — move the sudoers-invoked
scripts (`apply_finish.sh`, `post_update.sh`, `install.sh`) out of the
service-user-writable tree. Plus 1 device check (#1 TLS browser round-trip).

---

## Threat model / known-and-accepted tradeoffs

Read this before filing a finding — some of these are deliberate.

- **An enabled web terminal is still effectively root** — but it's now
  **off by default** (`dashboard.web_terminal_enabled`, #3 phase 1). While
  on: `config/sudoers-meshpoint` still grants `NOPASSWD: /bin/bash
  <plugins>/setup.sh` and `NOPASSWD: /bin/bash scripts/{apply_finish,
  post_update,install}.sh` — and those scripts live in a tree the
  `meshpoint` user can rewrite, so a shell can rewrite-then-`sudo`-run
  them → root. The `git` and root-`pip` wildcards are **gone** as of
  2026-09-09 (#2 phase 2). #2/#3 phase 3 (move those scripts to a
  root-owned dir) is what finally makes "admin session ≠ root" true. The
  real security boundary is `require_admin` auth.
- **Viewer vs admin** is the primary authz boundary. Viewer-role lockdown was
  done 2026-07-06 (`0c1cd41`) — viewers get 403 + toast on write routes
  (`config_routes.py`, `messages.py`, `nodeinfo_routes.py`,
  `position_broadcast_routes.py`, `telemetry_broadcast_routes.py` all gated).
- **Hosted `.mu` pages are served non-executable on purpose** (Reticulum
  plugin) — dynamic content only via generated pages or token substitution.
- Passwords live only in `local.yaml`, never returned in GET responses.
- **A plugin source is trusted code, at branch HEAD.** Adding a GitHub
  source (v0.8.1) is a consent gate (dangerous modal + `confirm:true`),
  but once added, Install/Update pull whatever that repo's `ref` points
  at *now* — a compromised repo account or a force-push lands on the next
  Update. Same class as `pip install` from the terminal. Mitigation
  available: **Pin** the source (Settings → Plugins → the source row) to
  freeze its `ref` to the commit it points at now. Downloaded files are
  re-validated (`parse_manifest`, path safety, size caps) but not
  signature-checked; `plugins.<id>.source.commit` records the resolved
  SHA as an audit anchor and the Update confirm shows old→new. Backlog #5
  (done).

---

## Security hardening backlog

Priority order is the user's own (set 2026-09-08).

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | **HTTPS/TLS option** | 🟢 Built, partially live-verified | `dashboard.tls_enabled` / `tls_cert_path` / `tls_key_path` / `tls_port` (default 8443). Self-signed cert via bundled `cryptography` (no new dep), `src/tls_cert.py`. SAN covers every `hostname -I` address + hostname + `<hostname>.local` + `127.0.0.1`/`localhost`; auto-regenerates at startup if the address set drifted. `:8080` becomes a 308-redirect-only listener when TLS is on (two `uvicorn.Server`s via `asyncio.gather`). 28 tests (`test_tls_cert.py` ×12, `test_serve.py` ×13, `test_banner_sources.py` ×3). Boot log verified on ti-meshpoint. **Still owed:** real browser round-trip against all 3 addresses (LAN IP / Tailscale IP / `sensecap.local`) — confirm only the self-signed warning appears, not also a hostname-mismatch warning. |
| 2 | **Move services off root onto `meshpoint` user** | 🟢 Phase 2 done + Pi-verified 2026-09-09 | **Phase 2 done + verified:** `/opt/meshpoint` + venv are `meshpoint`-owned, so the `NOPASSWD: git …` (~16 lines incl. `git reset --hard *`) and `NOPASSWD: venv/bin/pip install *` grants were dead weight *and* arbitrary-code-as-root. **Removed.** `apply.py` runs plain `git` (`_git()`) + `_precheck_tree_ownership()` (fails with a "chown the tree" message if ownership drifts); `install_status.py::_git_argv` plain-only (reads work on a mis-owned tree via `safe.directory`). `apply_finish.sh` runs pip via `runuser -u meshpoint`. venv-pip grant kept but `Runas=(meshpoint)` (never root) so `sudo -u meshpoint …/pip install <pkg>` still works from the terminal/SSH — the form the fan/mqtt hints + docs now use. `post_update.sh`/`install.sh` `visudo -c` before installing. Tests: `test_update_apply` (no-sudo + preflight ×2). **Pi-verified 2026-09-09:** real dashboard self-update ran on the new path — journal shows `runuser` dropping uid 0→999 for pip, no `sudo git`; `sudo -l -U meshpoint` shows zero git grants + only `(meshpoint) NOPASSWD: …/pip install *`; `find /opt/meshpoint/venv -not -user meshpoint` empty; service `active` after restart. **Phase 3 (the real de-root, still open):** the remaining sudoers lines point at scripts *in the meshpoint-writable tree* (`apply_finish.sh`, `post_update.sh`, `install.sh`) → the service user can rewrite-then-`sudo`-run them → still root-equivalent. Fix = move those to a root-owned dir (`/usr/local/lib/meshpoint/`) only a root process updates; needs a root-side update component. Same work as #3 phase 3. |
| 3 | **Web terminal → opt-in** | 🟢 Phase 1 done 2026-09-09 | **Kept in core (not a plugin) + config-gated.** `dashboard.web_terminal_enabled`, default `false`. Off = `terminal_routes` (HTTP + ws) 403, `identity_routes` drops `"terminal"` from `available_sections` so the sidebar hides it. Toggle: **Web terminal** card in Settings → System (`PUT /api/config/dashboard`, audited `config.dashboard_update`) with a `DangerousModal` ack spelling out the root implication. **No grandfather migration** (5 testers, they re-enable; CHANGELOG says so). Tests: `test_config_loader` (default off + yaml load), `test_identity_route` (section hidden), `test_terminal_routes` (403 + ws refused). Phase 2/3 = the sudoers/de-root work above (#2). |
| 4 | **USB companion udev rules too permissive** | 🟢 Fixed 2026-09-09 | `99-meshpoint-esp.rules` shipped `MODE="0666"` for `idVendor 303a` (Espressif native-USB: Heltec V3/V4, T-Beam S3). Now `MODE="0660", GROUP="dialout"` in `install.sh` + a `post_update.sh` migration that rewrites the stale rule. **Verified on the SenseCap 2026-09-09:** the box's current radios are `ttyUSB0/1` (CP210x/CH340, *not* `303a`) and already showed the safe OS default `crw-rw---- root:dialout` — the `0666` rule only ever bit a plugged-in `303a` board (none attached), so live blast radius was nil; latent until a Heltec V3 is connected for firmware-flash/relay. See Fixed below. |
| 5 | Plugin source: record + surface the resolved commit SHA | 🟢 Done 2026-09-09 | `plugins.<id>.source.commit` records the resolved short SHA at install. Plugin row shows `from owner/repo @ ref · <sha>`. `GET /api/plugin-sources/resolve` resolves a ref to its current commit; the Update confirm shows `installed <sha> → incoming <sha> "msg"` and flags a moving branch. `PATCH /api/plugin-sources` + **Pin/Unpin** buttons on the source row freeze a branch to the commit it points at now (`pinned_from` remembers the branch for Unpin). See Fixed. |

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

### 2026-09-09 — self-update chain: no more `sudo git` / root `sudo pip`  (backlog #2 phase 2)
- **Severity:** high (arbitrary code as root for any admin session / anything hijacking one)
- **Where:** `config/sudoers-meshpoint`, `src/api/update/apply.py`, `install_status.py`, `scripts/apply_finish.sh`
- **Issue:** `NOPASSWD: /opt/meshpoint/venv/bin/pip install *` (as root) →
  `sudo …/pip install <malicious-pkg>` = root code exec. Plus ~16
  `NOPASSWD: git …` lines including `git reset --hard *` / `git checkout *`
  → reset the (root-owned, per the stale comment) tree to anything as
  root. But `/opt/meshpoint` + `.git` + venv are **already `meshpoint`-owned**
  (confirmed on the SenseCap), so none of it was needed.
- **Fix:** deleted every `git` line and the root `pip install *` line.
  `apply.py` runs plain `git` (`_git()`), with `_precheck_tree_ownership()`
  failing early + actionably if `.git` isn't ours. `install_status._git_argv`
  is plain-only. `apply_finish.sh` runs pip via `runuser -u meshpoint`.
  The venv-pip grant is kept but `Runas=(meshpoint)` — never root —
  purely so `sudo -u meshpoint …/pip install <pkg>` keeps working (the
  fan / mqtt "install this" hints + docs updated to that form).
  `post_update.sh`/`install.sh` now `visudo -c` before installing the file.
- **Tests:** `test_update_apply` — git steps carry no `sudo`; preflight
  fails (chain never starts) when `sudo_needed()` is True, for apply +
  rollback. 101 update-suite tests pass.
- **Pi-verified 2026-09-09:** real dashboard self-update ran on the new
  path. Journal: `runuser[…]: session opened for user meshpoint(uid=999)
  by (uid=0)` (pip drop-to-meshpoint), `apply_finish.sh` via sudo as root
  (kept grant), no `sudo git` failures. `sudo -l -U meshpoint` → zero
  git grants, only `(meshpoint) NOPASSWD: /opt/meshpoint/venv/bin/pip
  install *`. `find /opt/meshpoint/venv -not -user meshpoint` → empty.
  `systemctl is-active meshpoint` → active.

### 2026-09-09 — plugin source: commit SHA now recorded + pinnable  (backlog #5)
- **Not a vuln** — reduces the "trusted code at branch HEAD" tradeoff.
- **Done:**
  - `install_from_source` returns the short SHA (from the tarball root
    dir); `plugins.<id>.source.commit` records it -- an audit anchor for
    *what code* is installed, since `ref` moves and `version` is
    author-typed.
  - `GET /api/plugin-sources/resolve?url=&ref=` -> the commit a ref points
    at now (GitHub commits API): `{sha, short_sha, message, committed_at,
    html_url, ref_is_pinned}`. `sources.resolve_commit()`.
  - `PATCH /api/plugin-sources {url, ref}` re-points a configured source.
    Pin = branch -> that commit's SHA (stores `pinned_from`); Unpin = SHA
    -> `pinned_from`. Admin + audited (`config.plugin_source_repoint`).
  - Frontend: **Pin / Unpin** buttons on the source row (📌 shown when
    pinned); the plugin row shows `from owner/repo @ ref · <sha>`; the
    Update confirm shows `installed abc → incoming def "msg"` and warns
    when the ref is a moving branch.
- **Tests:** `TestResolveCommit` ×3 (`test_plugin_sources.py`, Mac);
  resolve + pin/unpin roundtrip + 404 in `test_plugin_source_routes.py`
  (CI/Pi).

### 2026-09-09 — Espressif udev rule world-writable (`0666`)  (backlog #4, review pass)
- **Severity:** low–medium, latent (any local account → raw serial access to the mesh radios; only live when a `303a` board is attached)
- **Where:** `scripts/install.sh` (the `UDEV_RULE` heredoc), file `/etc/udev/rules.d/99-meshpoint-esp.rules`
- **Issue:** the rule was `SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0666"`
  — world read+write on any Espressif native-USB serial device (Heltec
  V3/V4, T-Beam ESP32-S3), which Meshpoint uses for the relay companion
  and MeshCore. The `meshpoint` user is already in `dialout`, so `0666`
  bought nothing and exposed the radios to every other local user /
  process. Generic USB-serial adapters (CP210x/CH340, `ttyUSB*`) were
  never covered by this rule and already get the OS default
  `0660 root:dialout`.
- **Verified on the SenseCap (2026-09-09):** `cat` of the rule file
  confirmed `0666`; `ls -l /dev/ttyUSB*` showed `crw-rw---- root dialout`
  (the box's radios aren't `303a`, so unaffected); `groups meshpoint`
  includes `dialout`. No `303a` device attached → nothing world-writable
  right now, but it would be the moment a Heltec V3 is plugged in for
  firmware flashing.
- **Fix:** rule is now `MODE="0660", GROUP="dialout"`. `install.sh`'s
  guard changed from "create if missing" to "write if content differs"
  so a re-run replaces a stale rule. New `post_update.sh` block 3b does
  the same on self-update (rewrites + `udevadm control --reload-rules` +
  `trigger`), so existing boxes get patched without a manual `install.sh`.
- **Follow-up owed:** confirm on a box *with* a Heltec V3 connected that
  after the migration the device shows `crw-rw---- root:dialout` and
  Meshpoint can still open it for flashing/relay.

### 2026-09-09 — plugin installer: no uncompressed-size / member-count cap  (review pass)
- **Severity:** medium (disk-fill DoS from a trusted-but-hostile or compromised source repo)
- **Where:** `src/plugins/installer.py`, `_safe_members()` / `stage_from_tarball()`
- **Issue:** `_download_tarball` capped the *compressed* GitHub tarball at
  25 MB, but extraction had no bound on total uncompressed bytes or file
  count — a gzip-bomb `repo.json` source could unpack to gigabytes and
  fill `/` (the plugin runs as the `meshpoint` user, so it can fill the
  data partition). GitHub's own repo-size limits make this hard to weaponise
  in practice, but it's cheap defence in depth and matches the stance the
  backup/restore path already takes.
- **Fix:** `_MAX_UNCOMPRESSED_BYTES = 80 MB` + `_MAX_MEMBERS = 4000`,
  checked twice — once against each member's declared header size in
  `_safe_members`, and again against the real bytes written during the
  streamed copy in `stage_from_tarball` (covers a lying header / sparse
  member). Aborts the whole install.
- **Tests:** `test_uncompressed_size_cap`, `test_member_count_cap` in
  `tests/test_plugin_installer.py` (both patch the constant low and run
  the normal fixture).

### 2026-09-09 — plugin source `ref` allowed `..` path segments  (review pass)
- **Severity:** low (catalog fetch could resolve to a different repo than the source URL shown)
- **Where:** `src/plugins/sources.py`, `normalise_ref()`
- **Issue:** the ref regex allowed `.` and `/`, and only rejected a
  leading slash — so `ref="../../other-owner/other-repo/main"` passed and
  got interpolated straight into
  `raw.githubusercontent.com/<o>/<r>/<ref>/repo.json`, which GitHub
  resolves server-side to `other-owner/other-repo`. The operator sets
  their own ref, so this is self-inflicted rather than a privilege
  escalation — but a copy-pasted "add this source with this ref"
  instruction could make the browsed/installed catalog come from a repo
  other than the one the UI displays.
- **Fix:** `normalise_ref` now also rejects a trailing slash and any `..`
  path segment (`".." in ref.split("/")`). Real slashed branch names
  (`feature/x`) still pass.
- **Tests:** extended `test_ref_normalisation` in `tests/test_plugin_sources.py`.

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
