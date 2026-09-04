/**
 * Settings -> Plugins panel controller.
 *
 * Loads the discovered app-plugin catalog from ``GET /api/plugins`` (built-in
 * + community, each with its configured `enabled` state and whether it's
 * actually `loaded` in the running process), renders one row per plugin in a
 * table (same shape as Settings > Themes' "Installed themes" list) with a
 * toggle switch, and persists flips through ``PUT /api/plugins/{id}``.
 * Enabling/disabling only takes effect on the next restart -- the panel says
 * so inline rather than pretending the change is live. A `deletable` plugin
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
        this._modal = null;
    }

    bind() {
        if (this.restartBtn) {
            this.restartBtn.addEventListener('click', () => this._restartService());
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
     * added.
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

        const ordered = [];
        groupOrder.forEach((root) => {
            const group = groups.get(root);
            ordered.push({ plugin: group.root, grouped: group.members.length > 0 });
            group.members.forEach((m) => ordered.push({ plugin: m, grouped: true }));
        });
        return ordered;
    }

    _render() {
        if (!this.listEl) return;
        if (!this._plugins.length) {
            this.listEl.innerHTML = '';
            return;
        }
        const rows = this._groupedPlugins().filter(({ plugin }) => this._matchesFilter(plugin));
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
        rows.forEach(({ plugin, grouped }) => {
            tbody.appendChild(this._renderRow(plugin, grouped));
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

    _renderRow(plugin, grouped = false) {
        const row = document.createElement('tr');
        // Visual cue for _groupedPlugins()'s reordering: a hook plugin
        // (has its own dependency) sits indented under its host; the host
        // row itself (grouped=true but no dependency of its own) gets a
        // subtle top rule marking where a new group starts, so a run of
        // hooks reads as "belonging to" the host above rather than just
        // some other row order.
        if (plugin.dependency) row.classList.add('plugin-row--dependent');
        else if (grouped) row.classList.add('plugin-row--host');
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
        const depsNote = (aptDeps.length || plugin.setup_script)
            ? `<p class="plugin-row__deps">Requires: ${aptDeps.length ? `<code>${this._escape(aptDeps.join(', '))}</code>` : 'a build step'}${plugin.setup_script ? ` — run <code>sudo meshpoint plugin setup ${this._escape(plugin.id)}</code> on the device` : ''}</p>`
            : '';
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
                <span class="plugin-row__name">${this._escape(plugin.id)}</span>
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
