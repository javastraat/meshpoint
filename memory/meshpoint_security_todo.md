# Meshpoint security — todo & findings log

Running list of security issues, hardening items, and fixes for Meshpoint.
A friend is auditing the codebase — new findings go under **Incoming findings**
with a date and reporter, then move to **Fixed** once patched (with commit +
verification evidence).

See `memory/project_m1_meshpoint.md` for wider session context and
`memory/reticulum_todo.md` for the Reticulum plugin backlog.

Last updated 2026-09-11 — **#6 and #7 (plugin-sources / web-terminal
filesystem-only gates) done AND Pi-verified by the user** — the
`local.yaml` edit + restart + UI round trip confirmed working for both
(disabled state hides the right UI with no hint, re-appears once opted
in). Reticulum Browse auth-gating (2026-09-09 fix) now has real regression
tests (`TestBrowseAuthGating`, 6 cases). #4 (udev `0666`→`0660`)
fixed+verified; #5 (plugin-source SHA/pin) done; #3 phase 1 (web terminal
opt-in) done; **#2 phase 2 (drop the `sudo git` / `sudo pip`-as-root
grants) done AND Pi-verified 2026-09-09** — real self-update ran on the
new plain-git path, `sudo -l -U meshpoint` shows no git grants + pip is
`(meshpoint)`, venv has no root-owned files, service healthy. #1 (TLS)
cert SAN verified on the SenseCap — every live address in the cert.
**Only real work left: #2/#3 phase 3** — move the sudoers-invoked scripts
(`apply_finish.sh`, `post_update.sh`, `install.sh`) out of the
service-user-writable tree. Small owed follow-up: #4's udev fix has never
been confirmed with an actual Heltec V3 (`303a`) device plugged in.

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
- **The `confirm:true` consent gate only proves the *current* admin
  session consents — it says nothing about whether that session is the
  real admin.** A compromised/phished admin session could tick the same
  box. As of #6, adding a source / installing from one is also gated by
  `plugin_sources_enabled` (default `false`), which has **no API route or
  dashboard toggle** — filesystem-only, `local.yaml` + restart. That's the
  actual defense-in-depth: a session that's fully compromised still
  cannot turn this one on. Backlog #6 (done).
- **`dashboard.web_terminal_enabled` itself is still toggleable over the
  API** (`PUT /api/config/dashboard`) — same shape of gap as the one above,
  and a shorter chain to root: enable it, then `POST
  /api/dangerous/invoke {id:"restart_service"}` (also just admin +
  a static confirm string) applies it. Backlog #7 closes this **for anyone
  who's never opted in**: `dashboard.web_terminal_toggle` (default
  `false`, filesystem-only, same as `plugin_sources_enabled`) gates both
  the `PUT` route (403 until true) and whether the Settings → System card
  renders at all. Deliberately a *second* flag rather than making
  `web_terminal_enabled` itself filesystem-only — once opted in, the
  existing checkbox keeps working for convenience, which means a
  compromised session can still flip it + restart *after that point*,
  same as before #7. The population this protects is whoever leaves the
  master switch off, i.e. anyone who doesn't actually use the terminal.
  Backlog #7 (done).

---

## Security hardening backlog

Priority order is the user's own (set 2026-09-08).

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | **HTTPS/TLS option** | 🟢 Built + verified 2026-09-09 | `dashboard.tls_enabled` / `tls_cert_path` / `tls_key_path` / `tls_port` (default 8443). Self-signed cert via bundled `cryptography`, `src/tls_cert.py`. SAN covers every `hostname -I` address + hostname + `<hostname>.local` + `127.0.0.1`/`localhost`; auto-regenerates at startup if the address set drifted. `:8080` → 308-redirect-only listener when TLS on. 28 tests. **Verified on the SenseCap 2026-09-09:** `openssl x509 -checkip/-checkhost` against every live address — `192.168.2.189` ✓, `192.168.4.2` ✓, `sensecap.local` ✓, `sensecap` ✓, `localhost` ✓ all in the cert SAN. So a browser shows only the self-signed warning, never a hostname mismatch. Nothing owed (no Tailscale on this box; it'd auto-add on next restart if added). |
| 2 | **Move services off root onto `meshpoint` user** | 🟢 Phase 2 done + Pi-verified 2026-09-09 | **Phase 2 done + verified:** `/opt/meshpoint` + venv are `meshpoint`-owned, so the `NOPASSWD: git …` (~16 lines incl. `git reset --hard *`) and `NOPASSWD: venv/bin/pip install *` grants were dead weight *and* arbitrary-code-as-root. **Removed.** `apply.py` runs plain `git` (`_git()`) + `_precheck_tree_ownership()` (fails with a "chown the tree" message if ownership drifts); `install_status.py::_git_argv` plain-only (reads work on a mis-owned tree via `safe.directory`). `apply_finish.sh` runs pip via `runuser -u meshpoint`. venv-pip grant kept but `Runas=(meshpoint)` (never root) so `sudo -u meshpoint …/pip install <pkg>` still works from the terminal/SSH — the form the fan/mqtt hints + docs now use. `post_update.sh`/`install.sh` `visudo -c` before installing. Tests: `test_update_apply` (no-sudo + preflight ×2). **Pi-verified 2026-09-09:** real dashboard self-update ran on the new path — journal shows `runuser` dropping uid 0→999 for pip, no `sudo git`; `sudo -l -U meshpoint` shows zero git grants + only `(meshpoint) NOPASSWD: …/pip install *`; `find /opt/meshpoint/venv -not -user meshpoint` empty; service `active` after restart. **Phase 3 (the real de-root, still open):** the remaining sudoers lines point at scripts *in the meshpoint-writable tree* (`apply_finish.sh`, `post_update.sh`, `install.sh`) → the service user can rewrite-then-`sudo`-run them → still root-equivalent. Fix = move those to a root-owned dir (`/usr/local/lib/meshpoint/`) only a root process updates; needs a root-side update component. Same work as #3 phase 3. |
| 3 | **Web terminal → opt-in** | 🟢 Phase 1 done 2026-09-09 | **Kept in core (not a plugin) + config-gated.** `dashboard.web_terminal_enabled`, default `false`. Off = `terminal_routes` (HTTP + ws) 403, `identity_routes` drops `"terminal"` from `available_sections` so the sidebar hides it. Toggle: **Web terminal** card in Settings → System (`PUT /api/config/dashboard`, audited `config.dashboard_update`) with a `DangerousModal` ack spelling out the root implication. **No grandfather migration** (5 testers, they re-enable; CHANGELOG says so). Tests: `test_config_loader` (default off + yaml load), `test_identity_route` (section hidden), `test_terminal_routes` (403 + ws refused). Phase 2/3 = the sudoers/de-root work above (#2). |
| 4 | **USB companion udev rules too permissive** | 🟢 Fixed 2026-09-09 | `99-meshpoint-esp.rules` shipped `MODE="0666"` for `idVendor 303a` (Espressif native-USB: Heltec V3/V4, T-Beam S3). Now `MODE="0660", GROUP="dialout"` in `install.sh` + a `post_update.sh` migration that rewrites the stale rule. **Verified on the SenseCap 2026-09-09:** the box's current radios are `ttyUSB0/1` (CP210x/CH340, *not* `303a`) and already showed the safe OS default `crw-rw---- root:dialout` — the `0666` rule only ever bit a plugged-in `303a` board (none attached), so live blast radius was nil; latent until a Heltec V3 is connected for firmware-flash/relay. See Fixed below. |
| 5 | Plugin source: record + surface the resolved commit SHA | 🟢 Done 2026-09-09 | `plugins.<id>.source.commit` records the resolved short SHA at install. Plugin row shows `from owner/repo @ ref · <sha>`. `GET /api/plugin-sources/resolve` resolves a ref to its current commit; the Update confirm shows `installed <sha> → incoming <sha> "msg"` and flags a moving branch. `PATCH /api/plugin-sources` + **Pin/Unpin** buttons on the source row freeze a branch to the commit it points at now (`pinned_from` remembers the branch for Unpin). See Fixed. |
| 6 | Plugin sources: filesystem-only enable gate | 🟢 Done + Pi-verified 2026-09-11 | `plugin_sources_enabled: bool = False` (`src/config.py`, top-level, popped in `_apply_yaml` before the section loop so it's not flagged as an unknown key). **No API route sets it** — hand-edit `local.yaml` + restart, by design (see threat-model note above). `add_source`/`install_from_source_route` in `plugin_source_routes.py` 403 via `_require_sources_enabled()` while off; list/remove/catalog/resolve/repoint stay open. `GET /api/plugin-sources` now also returns `sources_enabled`. Frontend splits **show** (the already-configured sources list — always renders, since those routes were never gated) from **add** (form + subtitle hidden with no note while off, matching #7's silent treatment — follow-up 2026-09-11, see Fixed). |
| 7 | Web terminal: filesystem-only toggle gate | 🟢 Done + Pi-verified 2026-09-11 | `dashboard.web_terminal_toggle: bool = False` (`src/config.py`, nested — regular `dashboard:` section field, no special popping needed). **No API route sets it.** `PUT /api/config/dashboard` in `config_routes.py` 403s on any `web_terminal_enabled` change while it's off; `GET /api/config`'s `dashboard` block now also returns `web_terminal_toggle`. Settings → System's whole "Web terminal" card starts `hidden` in `index.html` and only un-hides once the fetched value is true — no explanatory note when it's off, unlike plugin sources, by explicit design (asked by auditor: don't hint the feature exists at all). See Fixed. |

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

### 2026-09-11 — web terminal: filesystem-only toggle gate  (asked by auditor)
- **Not a vuln in isolation** — same shape as the plugin-sources fix right
  below, closing the gap between "admin session compromised" and "root
  shell obtained," which the existing mitigations (confirm dialog, audit
  log) leave open since both only require *an* admin session.
- **Issue:** `PUT /api/config/dashboard {web_terminal_enabled: true}` is a
  plain admin-gated route. `POST /api/dangerous/invoke {id:
  "restart_service", confirmation: "restart"}` is too. Both just need an
  admin session and a static, publicly-known confirm string — no
  filesystem access anywhere. So a compromised/phished admin session could
  enable the terminal, trigger its own restart, and have a root-capable
  shell within seconds. Worse than the plugin-sources gap: the payoff here
  is immediate and total, not "a plugin sitting disabled on disk."
- **Design conversation:** two options considered — (A) make
  `web_terminal_enabled` itself filesystem-only, full stop, matching
  `plugin_sources_enabled` exactly (strongest, but every future on/off
  needs an SSH round-trip, not just the first); (B) a second, purely
  filesystem-only master flag that gates whether the *existing* checkbox
  is reachable at all — once opted in, the convenient web toggle keeps
  working. Presented both with the tradeoff spelled out
  (`AskUserQuestion`); **user picked (B)**, their original proposal.
- **Fix:** `dashboard.web_terminal_toggle: bool = False` (`src/config.py`).
  No route sets it. `update_dashboard()` in `config_routes.py` 403s any
  `web_terminal_enabled` change (either direction) while it's off, with a
  message pointing at the config key. `get_config()`'s `dashboard` block
  now also returns `web_terminal_toggle`. Frontend: the whole "Web
  terminal" `<article>` in `index.html` starts `hidden` (plus a
  `.web-terminal-card[hidden] { display: none }` CSS rule -- `.auth-card`'s
  `display: flex` otherwise beats the bare `[hidden]` UA rule, same gotcha
  as the plugin-sources fix two commits earlier); `dangerous_panel_controller.js`'s
  `_loadWebTerminalState()` only un-hides it once `GET /api/config`
  confirms `web_terminal_toggle: true` — **no explanatory note when it's
  off**, unlike plugin sources' disabled note, by explicit ask: don't hint
  the feature exists at all to a session that hasn't earned it.
  `config/default.yaml` documents both flags at their `false` default.
- **Known, accepted limitation:** once an operator opts in
  (`web_terminal_toggle: true`), the underlying `web_terminal_enabled`
  flip is reachable via the API exactly as before — a compromised session
  at that point can still enable + restart. This only fully protects
  operators who never opt in. Full closure would need option (A); revisit
  if that tradeoff ever stops being acceptable.
- **Tests:** `tests/test_config_routes.py` (new file, 6 cases — default
  off, `GET /api/config` reports both flags, enable refused / disable
  refused while off, enable succeeds once on, confirms no field on
  `DashboardUpdate` can set the toggle itself), `tests/test_config_loader.py`
  +1 (`web_terminal_toggle` default off + loads from yaml, no unknown-key
  warning). All CI/Pi-gated (`_HAS_FASTAPI`) except the loader test, which
  ran green on the Mac (32 passed). **Pi-verified 2026-09-11 by the user**:
  the `local.yaml` edit + restart + Settings → System round trip confirmed
  working (card hidden while off, appears with the checkbox working once
  `web_terminal_toggle: true` is set).
- **Docs:** `docs/CONFIGURATION.md` (new `web_terminal_toggle` writeup next
  to `web_terminal_enabled`'s existing one), `docs/CHANGELOG.md` under
  `### Unreleased` → Dashboard, `README.md`'s "Web terminal" bullet extended.

### 2026-09-11 — plugin sources: filesystem-only enable gate  (asked by auditor)
- **Not a vuln in isolation** — closes the gap between "admin session
  compromised" and "arbitrary privileged code runs," which every prior
  plugin-source mitigation (confirm dialog, audit log, SHA pin) leaves
  open: all of them only require *an* admin session, not a trustworthy one.
- **Issue:** `POST /api/plugin-sources` (add) and `POST
  /api/plugin-sources/install` were reachable by any admin session with
  just a client-side `confirm:true` — no server-side switch existed, so a
  phished/stolen session (or XSS, or a reused/leaked JWT) could add an
  attacker-controlled source and drop code into `plugins/apps/<id>/`
  in one round trip. (Enabling that plugin, and thus executing it, is a
  separate step — `PUT /api/plugins/{id}` — but that route is *also* just
  admin-gated, so the same compromised session clears it too.)
- **Fix:** `plugin_sources_enabled: bool = False` (`src/config.py`,
  top-level field, popped in `_apply_yaml` before the section loop —
  otherwise it's silently dropped as an "unknown key"). Deliberately
  **no PUT/PATCH route touches it** — the only way to set it is hand-
  editing `plugin_sources_enabled: true` into `local.yaml` and restarting,
  same trust tier as filesystem/SSH access to the device. `add_source` and
  `install_from_source_route` in `plugin_source_routes.py` now call
  `_require_sources_enabled()` first and 403 with an explanatory message
  when off. Left ungated: `GET` (list/catalog/resolve — read-only) and
  `DELETE` (remove — only ever narrows what's trusted) and `PATCH`
  (repoint/pin — moves within an already-consented repo, adds no new
  trust). `GET /api/plugin-sources` now also returns `sources_enabled`;
  `frontend/js/settings/plugins_panel_controller.js`'s `_renderSourcesGate()`
  hides the Add-source form (`data-src-add-form`) and shows a
  `data-src-disabled-note` pointing at the config key when it's false —
  purely cosmetic, the backend enforces regardless of what the UI shows.
- **Tests:** `tests/test_plugin_source_routes.py` —
  `TestPluginSourcesDisabledByDefault` (5: config default, add 403,
  install 403, list reports `sources_enabled: false`, confirms no other
  verb on the router can flip it), plus `test_list_reports_sources_enabled`
  added to the existing enabled-by-default suite (whose `setUp` now sets
  `plugin_sources_enabled = True` so its pre-existing add/install tests
  keep passing). `tests/test_config_loader.py` —
  `test_plugin_sources_enabled_defaults_off_and_loads_from_yaml` (default
  False, loads from a bare top-level YAML key, no unknown-key warning).
  All CI/Pi-gated (`_HAS_FASTAPI`) except the config-loader test, which
  ran green on the Mac. **Pi-verified 2026-09-11 by the user**: the
  `local.yaml` edit + restart + Settings → Plugins page round trip
  confirmed working (form hidden while off, reappears once
  `plugin_sources_enabled: true` is set).
- **Docs:** `docs/CONFIGURATION.md` new "### Plugin sources" subsection
  (previously undocumented entirely — `plugin_sources` itself wasn't
  written up before this pass either); `docs/CHANGELOG.md` under
  `### Unreleased` → Plugins; `README.md`'s existing "Plugin sources"
  bullet extended in place.
- **Follow-up 2026-09-11 (asked by auditor, after #7 landed):** split
  "show" from "add" instead of showing a disabled note. The already-
  configured sources list (`data-src-list` — Browse/Pin/Unpin/Remove)
  was never actually gated by `sources_enabled` (those routes stay open
  regardless, see Issue above), so it renders unconditionally in
  `_loadSources()` same as before. What changed: `data-src-disabled-note`
  is **gone** — removed from `index.html` entirely, along with
  `srcDisabledNoteEl` in the controller. The Add-source form + its
  subtitle now get exactly the same silent treatment as #7's Web terminal
  card: both start `hidden` in the markup, `_renderSourcesGate()` only
  un-hides them once `sources_enabled: true` is confirmed, nothing
  indicates the capability exists while it's off. Considered and
  rejected: hiding the *whole* card (list included) while disabled — would
  have hidden a still-fully-functional Browse/Pin/Remove UI for a source
  already added, for no security benefit (those verbs were never gated).

### 2026-09-09 — Reticulum "Browse" (NomadNet page fetch) wrongly required admin  (reported by auditor)
- **Severity:** low (over-restrictive, not over-permissive — a usability/parity
  gap, not exposure) — **plus one real finding surfaced while fixing it**,
  see below.
- **Where:** `plugins/apps/reticulum/backend/nomad_routes.py`,
  `plugins/apps/reticulum/frontend/reticulum_panel.js`
- **Issue:** fetching another `nomadnetwork.node`'s hosted `.mu` page/file
  over a Link is a read-only action, the same risk class as reading LXMF
  messages (already viewer-accessible) — but `POST /page` and `POST /file`
  required `require_admin`, and the frontend hid the whole "Browse" tab +
  every inline "Browse" button for a viewer session. A viewer could see
  peers/announces but never actually browse a hosted node.
- **Also found while auditing the same file:** `GET /nodes` (list recently-
  seen `nomadnetwork.node` peers) had **no auth dependency at all** — not
  even `require_auth` — so it was reachable unauthenticated. Not the
  auditor's report, but the same file, same pass.
- **Fix:** `nomad_routes.py` — `/nodes`, `/page`, `/file` now
  `Depends(require_auth)` (any logged-in session) instead of
  `require_admin`/nothing. `/pages*` (reading/editing *this node's own*
  hosted content) stays `require_admin` — that's a config/write concern,
  not browsing. Frontend: the Browse tab button, its tab-switch guard, and
  the inline "Browse" buttons on the Peers/Activity tables no longer check
  `_isAdmin`; the Contacts-tab Browse button stays admin-gated since
  Contacts itself is still an admin-only tab.
- **Tests (added 2026-09-11):** `plugins/apps/reticulum/backend/tests/test_nomad_routes.py`
  gains `TestBrowseAuthGating` (6 cases) — explicit `dependency_overrides`
  for both `require_auth` and `require_admin` per test (not a real JWT
  service, not leaving one unoverridden -- FastAPI only rewires the exact
  `Depends(...)` callable a route declares, so `require_admin`'s own
  internal `await require_auth(...)` call is untouched by overriding
  `require_auth` alone). Viewer session: `GET /nodes` 200 (empty roster),
  `POST /page`/`POST /file` 200 (both stub `nomad.fetch_page`/`fetch_file`
  to skip a real Reticulum Link), all five `/pages*` routes 403. Separate
  case: no session at all -> `GET /nodes` 401, covering the second bug
  above. `nomad.fetch_page`/`fetch_file` monkeypatches are snapshotted +
  restored in `tearDown` (see the plugin-sources test-isolation fix same
  day for the leak this guards against).

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
