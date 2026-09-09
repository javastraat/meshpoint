/**
 * Settings -> Plugins panel controller.
 *
 * Loads the discovered app-plugin catalog from ``GET /api/plugins`` (built-in
 * + community, each with its configured `enabled` state and whether it's
 * actually `loaded` in the running process), renders one row per plugin in a
 * table (same shape as Settings > Themes' "Installed themes" list) with a
 * toggle switch, and persists flips through ``PUT /api/plugins/{id}``.
 * Enabling/disabling only takes effect on the next restart -- the panel says
 * so inline rather than pretending the change is live. A plugin that declares
 * a `[deps] check` script shows a live verdict from the loader (⚠ setup needed
 * with the reason, or ✓ installed) instead of the always-on "Requires:" hint,
 * with a Re-check button (``POST /api/plugins/{id}/check``) so running setup on
 * the device clears the warning without a restart. When a setup is genuinely
 * needed, a **Run setup** button streams ``sudo bash setup.sh``
 * (``POST /api/plugins/{id}/setup/stream``, NDJSON via ``UpdateStreamClient``)
 * into a modal, then offers Enable + Restart once it succeeds. A `deletable` plugin
 * (community tier, not `locked`) also gets a Delete button that removes its
 * folder via ``DELETE /api/plugins/{id}`` -- same confirm-to-delete modal as
 * Settings > Themes' "Installed themes" list. A page-level "Restart service"
 * button reuses the existing `restart_service` dangerous action
 * (``POST /api/dangerous/invoke``, same one Settings > System's "Restart
 * service" card triggers) so a pending enable/disable/delete change can be
 * applied without leaving this page.
 */

class PluginsPanelController {
    constructor(rootEl) {
        this.root = rootEl;
        this.listEl = rootEl.querySelector('[data-plugins-list]');
        this.statusEl = rootEl.querySelector('[data-plugins-status]');
        this.restartBtn = rootEl.querySelector('[data-restart-service]');
        this.restartStatusEl = rootEl.querySelector('[data-restart-status]');
        this.searchEl = rootEl.querySelector('[data-plugins-search]');
        this._plugins = [];
        this._filterText = '';
        // Which group-root ids are folded shut -- persists across
        // _render() calls (a toggle/delete/search re-renders the whole
        // table) since it's UI-only state, not re-derived from the API.
        // Ignored entirely while a filter is active (see _render()) so
        // typing a search term can never hide a real match behind a
        // collapsed group.
        this._collapsedGroups = new Set();
        // A group starts collapsed the first time we ever see it (e.g.
        // "rtlsdr" alone accounts for 8 of 11 plugins today -- showing
        // all of them by default defeats the point of grouping), then
        // respects whatever the admin does with it after that for the
        // rest of this page session. Tracked separately from
        // _collapsedGroups so a later refresh() (every toggle/delete
        // re-fetches and re-renders) doesn't stomp back over a group the
        // admin just expanded a moment ago.
        this._seenGroupRoots = new Set();
        this._modal = null;
        // Lazily-built "Run setup" output modal + a guard so its backdrop /
        // Close can't dismiss it mid-run (setup.sh is minutes long).
        this._setupModal = null;
        this._setupRunning = false;
        this.recheckAllBtn = rootEl.querySelector('[data-recheck-all]');
    }

    bind() {
        if (this.restartBtn) {
            this.restartBtn.addEventListener('click', () => this._restartService());
        }
        if (this.recheckAllBtn) {
            this.recheckAllBtn.addEventListener('click', () => this._recheckAll());
        }
        if (this.searchEl) {
            this.searchEl.addEventListener('input', () => {
                this._filterText = this.searchEl.value.trim().toLowerCase();
                this._render();
            });
        }
    }

    async _restartService() {
        const ok = await this._confirm(
            'Restart the Meshpoint service now? This applies any pending plugin ' +
            'enable/disable changes above. The dashboard will briefly disconnect ' +
            'and reload while it comes back up.',
            { label: 'Restart service?', command: 'Restart service' },
        );
        if (!ok) return;
        this.restartBtn.disabled = true;
        this._setRestartStatus('pending', 'Restarting…');
        try {
            const response = await fetch('/api/dangerous/invoke', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action_id: 'restart_service' }),
            });
            if (!response.ok) {
                this._setRestartStatus('error', response.status === 403
                    ? 'Admin role required.'
                    : `Failed (HTTP ${response.status}).`);
                return;
            }
            const body = await response.json();
            if (!body.success) {
                this._setRestartStatus('error', body.message || 'Restart failed.');
                return;
            }
            this._setRestartStatus('success', 'Restarting… the dashboard will reconnect in a few seconds.');
            // Fire-and-forget: the service process fully exits and restarts
            // (systemd), so this page's own plugin list -- and every row's
            // "Saved. Restart to apply." pending state -- otherwise stays
            // frozen forever with no code anywhere re-fetching it, which
            // reads as a stuck/greyed-out page even once the service is
            // long back up and everything else (WS, uptime, sessions) has
            // already reconnected on its own.
            this._reconnectAfterRestart();
        } catch (_e) {
            this._setRestartStatus('error', 'Network error.');
        } finally {
            this.restartBtn.disabled = false;
        }
    }

    /** Polls until the restarted service answers again, then refreshes the
     * plugin list so enabled/loaded/restart_required reflect the new
     * process instead of the stale pre-restart snapshot. */
    async _reconnectAfterRestart() {
        const RETRY_DELAY_MS = 3000;
        const MAX_ATTEMPTS = 6; // ~18s -- generous for a concentrator reinit
        for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
            try {
                const response = await fetch('/api/plugins', { credentials: 'same-origin' });
                if (response.ok) {
                    await this.refresh();
                    this._setRestartStatus('success', 'Reconnected — plugin list refreshed.');
                    return;
                }
            } catch (_e) { /* still restarting -- keep retrying */ }
        }
        this._setRestartStatus('error', 'Still unreachable after the restart — reload the page to check.');
    }

    _setRestartStatus(kind, message) {
        if (!this.restartStatusEl) return;
        this.restartStatusEl.dataset.kind = kind;
        this.restartStatusEl.textContent = message;
    }

    /** Re-run every plugin's [deps] check probe in one shot (server-side,
     * concurrent) and re-render, so an admin can see what's missing across
     * all plugins without clicking each row's Re-check. */
    async _recheckAll() {
        if (!this.recheckAllBtn) return;
        this.recheckAllBtn.disabled = true;
        const label = this.recheckAllBtn.textContent;
        this.recheckAllBtn.textContent = 'Re-checking…';
        this._setRestartStatus('pending', 'Re-checking every plugin’s dependencies…');
        try {
            const response = await fetch('/api/plugins/check-all', {
                method: 'POST', credentials: 'same-origin',
            });
            if (!response.ok) {
                this._setRestartStatus('error', response.status === 403
                    ? 'Admin role required.'
                    : `Re-check failed (HTTP ${response.status}).`);
                return;
            }
            const body = await response.json();
            this._plugins = body.plugins || this._plugins;
            this._render();
            const bad = this._plugins.filter((p) => p.deps_ok === false).map((p) => p.id);
            this._setRestartStatus(bad.length ? 'error' : 'success', bad.length
                ? `Setup needed: ${bad.join(', ')}.`
                : `All ${body.checked} checked plugins have their dependencies installed.`);
        } catch (_e) {
            this._setRestartStatus('error', 'Network error re-checking dependencies.');
        } finally {
            this.recheckAllBtn.disabled = false;
            this.recheckAllBtn.textContent = label;
        }
    }

    async refresh() {
        try {
            const response = await fetch('/api/plugins', { credentials: 'same-origin' });
            if (!response.ok) {
                this._setStatus('error', `Could not load plugins (HTTP ${response.status}).`);
                return;
            }
            const body = await response.json();
            this._plugins = body.plugins || [];
            this._setStatus('', this._plugins.length ? '' : 'No plugins found under plugins/apps/.');
            this._render();
        } catch (_e) {
            this._setStatus('error', 'Network error loading plugins.');
        }
    }

    /** Case-insensitive substring match against id/description/provides --
     * enough to find a plugin by name, what it does, or which seam it uses
     * (e.g. typing "hook" surfaces every hook plugin at once). */
    _matchesFilter(plugin) {
        if (!this._filterText) return true;
        const haystack = [
            plugin.id, plugin.description, (plugin.provides || []).join(' '),
        ].join(' ').toLowerCase();
        return haystack.includes(this._filterText);
    }

    /**
     * Groups every plugin under the host it (transitively) hooks into,
     * host first within its own group -- a "hook" plugin listed right
     * after (and visually under) the page it actually depends on reads
     * far more clearly than the plain alphabetical order the API returns,
     * which scatters a host and its hooks wherever their names happen to
     * fall (e.g. "rtlsdr" sorts dead last, after all 8 plugins that hook
     * into it). Standalone plugins (no [hook], or a [hook] whose host
     * route resolves to nothing installed) are their own one-plugin
     * group. Group order itself is stable -- whichever group's first
     * member appears first in the API's own (alphabetical) order -- so
     * the overall page doesn't reshuffle unpredictably as plugins are
     * added. Returns [{root, members}], not a flat list -- _render()
     * decides what to actually show based on fold/filter state.
     */
    _groupedPlugins() {
        const byId = new Map(this._plugins.map((p) => [p.id, p]));
        const rootId = (plugin) => {
            const seen = new Set();
            let current = plugin;
            while (current.dependency && current.dependency.host_id && !seen.has(current.id)) {
                seen.add(current.id);
                const host = byId.get(current.dependency.host_id);
                if (!host) break;
                current = host;
            }
            return current.id;
        };

        const groups = new Map(); // rootId -> { root, members: [] }
        const groupOrder = [];
        this._plugins.forEach((plugin) => {
            const root = rootId(plugin);
            if (!groups.has(root)) {
                groups.set(root, { root: byId.get(root) || plugin, members: [] });
                groupOrder.push(root);
            }
            if (plugin.id !== root) groups.get(root).members.push(plugin);
        });

        return groupOrder.map((root) => groups.get(root));
    }

    _render() {
        if (!this.listEl) return;
        if (!this._plugins.length) {
            this.listEl.innerHTML = '';
            return;
        }

        // While actively searching, fold state is ignored entirely (a
        // collapsed group must never hide a real match) and a host whose
        // OWN text doesn't match is still shown as context above any of
        // its members that do -- a bare "p2000" row floating with no
        // visible host reads as confusing as the un-grouped list this
        // whole feature replaced.
        const searching = !!this._filterText;
        const rows = []; // {plugin, grouped, hostMeta}
        this._groupedPlugins().forEach(({ root, members }) => {
            const hasMembers = members.length > 0;
            if (searching) {
                const matchingMembers = members.filter((m) => this._matchesFilter(m));
                if (!this._matchesFilter(root) && !matchingMembers.length) return;
                rows.push({ plugin: root, grouped: hasMembers, hostMeta: null });
                matchingMembers.forEach((m) => rows.push({ plugin: m, grouped: true, hostMeta: null }));
                return;
            }
            if (hasMembers && !this._seenGroupRoots.has(root.id)) {
                this._seenGroupRoots.add(root.id);
                this._collapsedGroups.add(root.id); // collapsed by default on first sight
            }
            const collapsed = hasMembers && this._collapsedGroups.has(root.id);
            rows.push({
                plugin: root, grouped: hasMembers,
                hostMeta: hasMembers ? { collapsed, memberCount: members.length } : null,
            });
            if (!collapsed) members.forEach((m) => rows.push({ plugin: m, grouped: true, hostMeta: null }));
        });

        if (!rows.length) {
            this.listEl.innerHTML = '';
            this._setStatus('', `No plugins match "${this.searchEl ? this.searchEl.value.trim() : ''}".`);
            return;
        }
        this._setStatus('', '');
        this.listEl.innerHTML = `<table class="plugins-table">
            <thead><tr><th>Plugin</th><th>Source</th><th>Provides</th><th></th></tr></thead>
            <tbody></tbody>
        </table>`;
        const tbody = this.listEl.querySelector('tbody');
        rows.forEach(({ plugin, grouped, hostMeta }) => {
            tbody.appendChild(this._renderRow(plugin, grouped, hostMeta));
        });
        // A message queued by _setEnabled() just before its own
        // refresh()-triggered re-render -- applied once here, then
        // cleared, so it doesn't reappear on some later unrelated render.
        if (this._pendingMessage) {
            const { id, kind, text } = this._pendingMessage;
            this._pendingMessage = null;
            const row = Array.from(tbody.querySelectorAll('tr')).find(
                (tr) => tr.querySelector('.plugin-row__name')?.textContent === id,
            );
            const resultEl = row && row.querySelector('[data-result]');
            if (resultEl) {
                resultEl.dataset.kind = kind;
                resultEl.textContent = text;
            }
        }
    }

    _renderRow(plugin, grouped = false, hostMeta = null) {
        const row = document.createElement('tr');
        // Visual cue for _groupedPlugins()'s reordering: a hook plugin
        // (has its own dependency) sits indented under its host; the host
        // row itself (grouped=true but no dependency of its own) gets a
        // subtle top rule marking where a new group starts, so a run of
        // hooks reads as "belonging to" the host above rather than just
        // some other row order.
        if (plugin.dependency) row.classList.add('plugin-row--dependent');
        else if (grouped) row.classList.add('plugin-row--host');
        // hostMeta is only set (by _render(), never while a search filter
        // is active) on a group-root row that actually has members --
        // a clickable chevron toggles its group folded/open, remembered
        // in this._collapsedGroups across re-renders.
        const toggleHtml = hostMeta
            ? `<button type="button" class="plugin-row__toggle" data-group-toggle ` +
              `aria-expanded="${!hostMeta.collapsed}" title="${hostMeta.collapsed ? 'Show' : 'Hide'} ${hostMeta.memberCount} dependent plugin${hostMeta.memberCount === 1 ? '' : 's'}">` +
              `${hostMeta.collapsed ? '▸' : '▾'}</button>`
            : '';
        const badgeMod = plugin.source === 'builtin' ? 'builtin' : 'community';
        const badgeLabel = plugin.source === 'builtin' ? 'Built-in' : 'Community';
        const provides = (plugin.provides || []).join(', ') || '-';
        // A plugin can need setup.sh with no apt packages at all (e.g. a
        // from-source build like dump1090 -- its build tools are already
        // covered by scripts/install.sh's base system packages), so this
        // must show whenever EITHER is present, not just apt_deps being
        // non-empty -- otherwise the hint silently vanishes for exactly the
        // plugins that most need one run before enabling.
        const aptDeps = plugin.apt_deps || [];
        const runHint = plugin.setup_script
            ? ` — run <code>sudo meshpoint plugin setup ${this._escape(plugin.id)}</code> on the device`
            : '';
        const staticHint = (aptDeps.length || plugin.setup_script)
            ? `Requires: ${aptDeps.length ? `<code>${this._escape(aptDeps.join(', '))}</code>` : 'a build step'}${runHint}`
            : '';
        // A plugin with a [deps] check script (has_deps_check) gets a live
        // verdict from the loader instead of the always-on static hint:
        // deps_ok === false -> "setup needed" + why; === true -> a quiet
        // "installed" line; null (no check / not loaded) -> the static hint.
        // Either verdict carries a Re-check button -- the boot-time verdict
        // goes stale if rnsd/a package is changed on the device afterwards,
        // so re-running the probe is the way to refresh it without a restart.
        const recheckBtnHtml = plugin.has_deps_check
            ? ` <button type="button" class="plugin-row__recheck" data-recheck>Re-check</button>`
            : '';
        // "Run setup" streams `sudo bash setup.sh` output into a modal --
        // offered only where a live verdict says it's actually needed, so a
        // healthy row (or one with no check) doesn't invite a re-run.
        const runSetupBtnHtml = (plugin.deps_ok === false && plugin.setup_script)
            ? ` <button type="button" class="plugin-row__runsetup" data-run-setup>Run setup</button>`
            : '';
        let depsNote = '';
        if (plugin.deps_ok === false) {
            const why = (plugin.deps_detail || '').split('\n').filter(Boolean)[0]
                || 'dependencies missing';
            depsNote = `<p class="plugin-row__deps plugin-row__deps--bad" title="${this._escape(plugin.deps_detail || '')}">`
                + `⚠ Setup needed — ${this._escape(why)}${runSetupBtnHtml}${recheckBtnHtml}</p>`;
        } else if (plugin.deps_ok === true) {
            depsNote = `<p class="plugin-row__deps plugin-row__deps--ok">✓ Dependencies installed${recheckBtnHtml}</p>`;
        } else if (plugin.has_deps_check) {
            depsNote = `<p class="plugin-row__deps">Dependency state unknown${recheckBtnHtml}</p>`;
        } else if (staticHint) {
            depsNote = `<p class="plugin-row__deps">${staticHint}</p>`;
        }
        // A "hook" plugin (dependency != null) has nowhere to render
        // without its host enabled -- shown here regardless of current
        // state, and the toggle itself is disabled below when the host
        // isn't on, so the reason is visible before anyone tries.
        const dep = plugin.dependency;
        const depNote = dep
            ? `<p class="plugin-row__dep${dep.host_enabled ? '' : ' plugin-row__dep--unmet'}">Depends on: <code>${this._escape(dep.host_id || dep.host_route)}</code>${dep.host_id ? (dep.host_enabled ? ' (enabled)' : ' (not enabled)') : ' — not installed'}</p>`
            : '';
        const depBlocksEnable = !!dep && !dep.host_enabled && !plugin.enabled;
        const byLine = [
            plugin.author ? this._escape(plugin.author) : '',
            plugin.homepage ? `<a href="${this._escape(plugin.homepage)}" target="_blank" rel="noopener noreferrer">homepage</a>` : '',
        ].filter(Boolean).join(' &middot; ');
        row.innerHTML = `
            <td>
                <span${hostMeta ? ' class="plugin-row__namewrap--foldable" data-group-toggle-cell' : ''}>
                    ${toggleHtml}<span class="plugin-row__name">${this._escape(plugin.id)}</span>
                    ${hostMeta && hostMeta.collapsed ? `<span class="plugin-row__count">+${hostMeta.memberCount} plugin${hostMeta.memberCount === 1 ? '' : 's'}</span>` : ''}
                </span>
                <span class="plugin-row__version">v${this._escape(plugin.version)}${byLine ? ` &middot; ${byLine}` : ''}</span>
            </td>
            <td><span class="plugin-row__badge plugin-row__badge--${badgeMod}">${badgeLabel}</span></td>
            <td class="plugin-row__meta">
                ${this._escape(plugin.description) || 'No description provided.'}
                <p class="plugin-row__provides">${this._escape(provides)}</p>
                ${depsNote}
                ${depNote}
            </td>
            <td class="plugin-row__act">
                <label class="r-switch" title="${depBlocksEnable ? `Enable ${this._escape(dep.host_id || dep.host_route)} first` : ''}">
                    <input type="checkbox" data-toggle ${plugin.enabled ? 'checked' : ''} ${depBlocksEnable ? 'disabled' : ''}>
                    <span class="r-switch__track"></span>
                </label>
                ${plugin.deletable ? `<button type="button" class="plugin-row__del" data-delete>Delete</button>` : ''}
                ${plugin.restart_required ? `<span class="plugin-row__restart" data-restart>Restart to ${plugin.enabled ? 'load' : 'unload'}</span>` : ''}
                <span class="plugin-row__result" data-result aria-live="polite"></span>
            </td>
        `;
        const toggle = row.querySelector('[data-toggle]');
        const resultEl = row.querySelector('[data-result]');
        toggle.addEventListener('change', () => this._setEnabled(plugin, toggle, resultEl));
        const delBtn = row.querySelector('[data-delete]');
        if (delBtn) {
            delBtn.addEventListener('click', () => this._deletePlugin(plugin, delBtn, resultEl));
        }
        const recheckBtn = row.querySelector('[data-recheck]');
        if (recheckBtn) {
            recheckBtn.addEventListener('click', () => this._recheckDeps(plugin, recheckBtn, resultEl));
        }
        const runSetupBtn = row.querySelector('[data-run-setup]');
        if (runSetupBtn) {
            runSetupBtn.addEventListener('click', () => this._runSetup(plugin));
        }
        // Wired on the name+chevron wrapper, not the whole row or the
        // whole first cell -- the version/byline span right below it
        // holds the homepage link, which must stay independently
        // clickable (navigate) instead of also toggling the fold.
        const groupToggleArea = row.querySelector('[data-group-toggle-cell]');
        if (groupToggleArea) {
            groupToggleArea.addEventListener('click', () => {
                if (this._collapsedGroups.has(plugin.id)) this._collapsedGroups.delete(plugin.id);
                else this._collapsedGroups.add(plugin.id);
                this._render();
            });
        }
        return row;
    }

    async _setEnabled(plugin, toggle, resultEl) {
        const enabled = toggle.checked;
        toggle.disabled = true;
        resultEl.dataset.kind = 'pending';
        resultEl.textContent = 'Saving…';
        try {
            const response = await fetch(`/api/plugins/${encodeURIComponent(plugin.id)}`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            const body = await response.json().catch(() => ({}));
            if (!response.ok) {
                toggle.checked = !enabled;
                resultEl.dataset.kind = 'error';
                // A dependency rejection (missing/disabled host) comes back
                // as a 400 with a specific, already-user-facing `detail` --
                // show that instead of a bare status code.
                resultEl.textContent = response.status === 403
                    ? 'Admin role required.'
                    : (body.detail || `Failed (HTTP ${response.status}).`);
                return;
            }
            const alsoDisabled = body.also_disabled || [];
            // Enabling/disabling a plugin can change OTHER rows' dependency
            // state too -- a host coming on un-greys its dependents'
            // toggles, disabling one cascades to every enabled dependent
            // (see also_disabled). Re-fetching the whole list rather than
            // patching this one row's local state keeps every row's
            // greyed-out/enabled reality correct with no separate
            // client-side dependency-graph bookkeeping to keep in sync.
            this._pendingMessage = {
                id: plugin.id,
                kind: 'success',
                text: alsoDisabled.length
                    ? `Saved. Also disabled: ${alsoDisabled.join(', ')} (they hook into this page). Restart to apply.`
                    : 'Saved. Restart to apply.',
            };
            await this.refresh();
        } catch (_e) {
            toggle.checked = !enabled;
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
        } finally {
            toggle.disabled = false;
        }
    }

    async _recheckDeps(plugin, button, resultEl) {
        button.disabled = true;
        resultEl.dataset.kind = 'pending';
        resultEl.textContent = 'Re-checking dependencies…';
        try {
            const response = await fetch(
                `/api/plugins/${encodeURIComponent(plugin.id)}/check`,
                { method: 'POST', credentials: 'same-origin' },
            );
            const body = await response.json().catch(() => ({}));
            if (!response.ok) {
                resultEl.dataset.kind = 'error';
                resultEl.textContent = response.status === 403
                    ? 'Admin role required.'
                    : (body.detail || `Failed (HTTP ${response.status}).`);
                button.disabled = false;
                return;
            }
            const ok = body.plugin && body.plugin.deps_ok === true;
            // refresh() re-renders every row from the new /api/plugins state,
            // so the ⚠/✓ line updates itself -- this message just narrates
            // the outcome in the row's result slot.
            this._pendingMessage = {
                id: plugin.id,
                kind: ok ? 'success' : 'error',
                text: ok
                    ? 'Dependencies OK.'
                    : 'Still missing dependencies — run setup on the device.',
            };
            await this.refresh();
        } catch (_e) {
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
            button.disabled = false;
        }
    }

    // ── Run setup (stream sudo bash setup.sh into a modal) ───────────────

    _ensureSetupModal() {
        if (this._setupModal) return this._setupModal;
        const root = document.createElement('div');
        root.className = 'plugin-setup-modal';
        root.setAttribute('aria-hidden', 'true');
        root.innerHTML = `
            <div class="plugin-setup-modal__backdrop" data-ps-backdrop></div>
            <div class="plugin-setup-modal__sheet" role="dialog" aria-modal="true">
                <h3 class="plugin-setup-modal__title" data-ps-title>Run setup</h3>
                <p class="plugin-setup-modal__status" data-ps-status aria-live="polite"></p>
                <pre class="plugin-setup-modal__output" data-ps-output></pre>
                <div class="plugin-setup-modal__actions" data-ps-actions>
                    <button type="button" class="plugin-setup-modal__btn" data-ps-enable hidden>Enable it</button>
                    <button type="button" class="plugin-setup-modal__btn" data-ps-restart hidden>Restart service</button>
                    <button type="button" class="plugin-setup-modal__btn plugin-setup-modal__btn--ghost" data-ps-close>Close</button>
                </div>
            </div>
        `;
        document.body.appendChild(root);
        root.querySelector('[data-ps-backdrop]').addEventListener('click', () => {
            if (!this._setupRunning) this._closeSetupModal();
        });
        root.querySelector('[data-ps-close]').addEventListener('click', () => {
            if (!this._setupRunning) this._closeSetupModal();
        });
        this._setupModal = {
            root,
            title: root.querySelector('[data-ps-title]'),
            status: root.querySelector('[data-ps-status]'),
            output: root.querySelector('[data-ps-output]'),
            enableBtn: root.querySelector('[data-ps-enable]'),
            restartBtn: root.querySelector('[data-ps-restart]'),
            closeBtn: root.querySelector('[data-ps-close]'),
        };
        return this._setupModal;
    }

    _closeSetupModal() {
        if (!this._setupModal) return;
        this._setupModal.root.setAttribute('aria-hidden', 'true');
        this._setupModal.root.classList.remove('plugin-setup-modal--open');
        // The dep verdict / enabled state may have changed while it was open.
        this.refresh();
    }

    async _runSetup(plugin) {
        const ok = await this._confirm(
            `Run "${plugin.id}"'s setup.sh on the device now? This executes ` +
            `sudo bash plugins/apps/${plugin.id}/setup.sh — the same thing ` +
            `\`sudo meshpoint plugin setup ${plugin.id}\` does — installing apt ` +
            `packages and/or building from source. Can take several minutes.`,
            { label: 'Run plugin setup?', command: `sudo bash setup.sh (${plugin.id})` },
        );
        if (!ok) return;

        const m = this._ensureSetupModal();
        m.title.textContent = `Setup — ${plugin.id}`;
        m.status.dataset.kind = 'pending';
        m.status.textContent = 'Running setup.sh…';
        m.output.textContent = '';
        m.enableBtn.hidden = true;
        m.restartBtn.hidden = true;
        m.closeBtn.disabled = true;
        m.root.setAttribute('aria-hidden', 'false');
        m.root.classList.add('plugin-setup-modal--open');
        this._setupRunning = true;

        const append = (text) => {
            const atBottom = m.output.scrollTop + m.output.clientHeight >= m.output.scrollHeight - 4;
            m.output.textContent += (m.output.textContent ? '\n' : '') + text;
            if (atBottom) m.output.scrollTop = m.output.scrollHeight;
        };

        let result = null;
        try {
            result = await window.UpdateStreamClient.postNdjson(
                `/api/plugins/${encodeURIComponent(plugin.id)}/setup/stream`,
                {},
                (event) => {
                    if (event.type === 'started' && Array.isArray(event.cmd)) {
                        append(`$ ${event.cmd.join(' ')}`);
                    } else if (event.type === 'line') {
                        append(event.text);
                    }
                },
            );
        } catch (err) {
            this._setupRunning = false;
            m.closeBtn.disabled = false;
            m.status.dataset.kind = 'error';
            m.status.textContent = err && err.status === 403
                ? 'Admin role required.'
                : `Request failed: ${(err && err.message) || err}`;
            return;
        }

        this._setupRunning = false;
        m.closeBtn.disabled = false;
        const success = !!(result && result.success);
        m.status.dataset.kind = success ? 'success' : 'error';
        if (success) {
            m.status.textContent = result.deps_ok === false
                ? 'setup.sh finished, but the dependency check still fails — see output above.'
                : 'setup.sh finished. Enable the plugin and restart to load it.';
            if (result.deps_ok !== false) {
                m.enableBtn.hidden = plugin.enabled;
                m.restartBtn.hidden = false;
            }
        } else {
            m.status.textContent = `setup.sh exited with code ${result ? result.returncode : '?'} — see output above.`;
        }

        m.enableBtn.onclick = async () => {
            m.enableBtn.disabled = true;
            try {
                const r = await fetch(`/api/plugins/${encodeURIComponent(plugin.id)}`, {
                    method: 'PUT',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: true }),
                });
                if (!r.ok) {
                    const b = await r.json().catch(() => ({}));
                    m.status.dataset.kind = 'error';
                    m.status.textContent = b.detail || `Enable failed (HTTP ${r.status}).`;
                    m.enableBtn.disabled = false;
                    return;
                }
                m.status.dataset.kind = 'success';
                m.status.textContent = 'Enabled. Restart the service to load it.';
                m.enableBtn.hidden = true;
            } catch (_e) {
                m.status.dataset.kind = 'error';
                m.status.textContent = 'Enable failed (network error).';
                m.enableBtn.disabled = false;
            }
        };
        m.restartBtn.onclick = () => {
            this._closeSetupModal();
            this._restartService();
        };
    }

    async _deletePlugin(plugin, button, resultEl) {
        const ok = await this._confirm(
            `Delete the "${plugin.id}" plugin from plugins/apps/? This removes ` +
            `the folder on the device and its plugins.${plugin.id} config. Takes ` +
            `effect on the next restart.`,
        );
        if (!ok) return;
        button.disabled = true;
        resultEl.dataset.kind = 'pending';
        resultEl.textContent = 'Deleting…';
        try {
            const response = await fetch(`/api/plugins/${encodeURIComponent(plugin.id)}`, {
                method: 'DELETE',
                credentials: 'same-origin',
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                resultEl.dataset.kind = 'error';
                resultEl.textContent = body.detail || (response.status === 403
                    ? 'Admin role required.'
                    : `Failed (HTTP ${response.status}).`);
                button.disabled = false;
                return;
            }
            this._plugins = this._plugins.filter((p) => p.id !== plugin.id);
            this._render();
            this._setStatus('', this._plugins.length ? '' : 'No plugins found under plugins/apps/.');
        } catch (_e) {
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
            button.disabled = false;
        }
    }

    async _confirm(message, { label = 'Delete plugin?', command = 'Delete' } = {}) {
        if (window.DangerousModal) {
            this._modal = this._modal || new window.DangerousModal();
            return this._modal.confirm({ label, command, description: message });
        }
        return window.confirm(message);
    }

    _setStatus(kind, message) {
        if (!this.statusEl) return;
        this.statusEl.dataset.kind = kind;
        this.statusEl.textContent = message;
    }

    _escape(value) {
        return String(value || '').replace(/[&<>"']/g, (c) => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }
}

window.PluginsPanelController = PluginsPanelController;
