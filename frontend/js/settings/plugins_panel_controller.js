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
 *
 * The "Plugin sources" card below the list adds/browses/installs from
 * operator-added GitHub repos (``/api/plugin-sources``). On load it scans
 * each source's catalog once -- that fills the per-source plugin count and
 * records which installed plugins have a newer version upstream, so a
 * plugin with an available update shows an **Update vX → vY** button right
 * on its own row in the main list (not only inside that source's Browse
 * panel), calling the same ``POST /api/plugin-sources/install``.
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
        this.srcAddForm = rootEl.querySelector('[data-src-add-form]');
        this.srcUrlEl = rootEl.querySelector('[data-src-url]');
        this.srcRefEl = rootEl.querySelector('[data-src-ref]');
        this.srcStatusEl = rootEl.querySelector('[data-src-status]');
        this.srcListEl = rootEl.querySelector('[data-src-list]');
        this._sources = [];
        // {pluginId: {url, ref, installed_version, version}} -- built from
        // each source's catalog on load, so a plugin whose source offers a
        // newer version shows an "Update" button on its own row in the
        // main list, not only inside that source's Browse panel.
        this._updates = {};
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
        if (this.srcAddForm) {
            this.srcAddForm.addEventListener('submit', (e) => { e.preventDefault(); this._addSource(); });
            this.srcListEl.addEventListener('click', (e) => this._onSourceClick(e));
            this._loadSources();
        }
    }

    // --- Plugin sources (Settings -> Plugins -> "Add source") -----------

    async _loadSources() {
        try {
            const r = await fetch('/api/plugin-sources', { credentials: 'same-origin' });
            if (r.ok) this._sources = (await r.json()).sources || [];
        } catch (_) {}
        this._renderSources();
    }

    _renderSources() {
        if (!this.srcListEl) return;
        if (!this._sources.length) {
            this.srcListEl.innerHTML = '<p class="plugins-sources__empty">No sources added.</p>';
            return;
        }
        this.srcListEl.innerHTML = this._sources.map((s) => `
            <div class="plugins-source" data-src-row="${this._escape(s.url)}">
                <div class="plugins-source__head">
                    <a href="${this._escape(s.url)}" target="_blank" rel="noopener" class="plugins-source__url">${this._escape(s.url)}</a>
                    <span class="plugins-source__ref">@ ${this._escape(s.ref || 'main')}</span>
                    <span class="plugins-source__count" data-src-count></span>
                    <span class="plugins-source__spacer"></span>
                    <button type="button" class="terminal-button" data-src-browse>Browse</button>
                    <button type="button" class="plugin-row__toggle" data-src-remove title="Remove source">&times;</button>
                </div>
                <div class="plugins-source__catalog" data-src-catalog hidden></div>
            </div>
        `).join('');
        // Scan each source's catalog on load (one lightweight fetch per
        // source): fills the row's "— N plugins" count AND records which
        // installed plugins have a newer version available, so the main
        // list can show an Update button per row. Failures degrade to a
        // quiet "— unreachable".
        this._updates = {};
        this._sources.forEach((s) => this._scanSource(s.url, s.ref || 'main'));
    }

    async _scanSource(url, ref) {
        const row = this.srcListEl.querySelector(`[data-src-row="${(window.CSS && CSS.escape) ? CSS.escape(url) : url}"]`);
        const el = row && row.querySelector('[data-src-count]');
        if (el) el.textContent = '— checking…';
        let cat = null;
        try {
            const qs = `url=${encodeURIComponent(url)}${ref ? `&ref=${encodeURIComponent(ref)}` : ''}`;
            const r = await fetch(`/api/plugin-sources/catalog?${qs}`, { credentials: 'same-origin' });
            if (!r.ok) { if (el) el.textContent = '— unreachable'; return; }
            cat = await r.json();
        } catch (_) {
            if (el) el.textContent = '';
            return;
        }
        const entries = [...(cat.plugins || []), ...(cat.themes || [])];
        if (el) {
            const np = (cat.plugins || []).length;
            const nt = (cat.themes || []).length;
            const parts = [];
            if (np) parts.push(`${np} plugin${np === 1 ? '' : 's'}`);
            if (nt) parts.push(`${nt} theme${nt === 1 ? '' : 's'}`);
            el.textContent = parts.length ? `— ${parts.join(', ')}` : '— empty';
        }
        entries.forEach((p) => {
            if (p.update_available) {
                this._updates[p.id] = {
                    url: cat.url || url, ref: cat.ref || ref,
                    installed_version: p.installed_version, version: p.version,
                    downgrade: this._cmpVersions(p.version, p.installed_version) < 0,
                };
            } else if (this._updates[p.id]) {
                delete this._updates[p.id];
            }
        });
        if (this._plugins.length) this._render();
    }

    /** Rough semver-ish compare -> -1 / 0 / 1. Splits on . - + and
     * compares numeric segments as numbers, the rest as strings; a
     * missing segment sorts lower (so 0.1 < 0.1.0). Good enough to tell
     * an update from a downgrade -- not a full semver implementation. */
    _cmpVersions(a, b) {
        const seg = (v) => String(v == null ? '' : v).split(/[.\-+]/)
            .map((x) => (/^\d+$/.test(x) ? parseInt(x, 10) : x));
        const pa = seg(a);
        const pb = seg(b);
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
            const x = pa[i];
            const y = pb[i];
            if (x === undefined) return -1;
            if (y === undefined) return 1;
            if (x === y) continue;
            if (typeof x === 'number' && typeof y === 'number') return x < y ? -1 : 1;
            return String(x) < String(y) ? -1 : 1;
        }
        return 0;
    }

    _onSourceClick(e) {
        const row = e.target.closest('[data-src-row]');
        if (!row) return;
        const url = row.dataset.srcRow;
        if (e.target.closest('[data-src-remove]')) { this._removeSource(url); return; }
        const installBtn = e.target.closest('[data-src-install]');
        if (installBtn) {
            const cat = row.querySelector('[data-src-catalog]');
            this._installFromSource(url, installBtn.dataset.id, cat.dataset.ref, {
                action: installBtn.dataset.action || 'install',
                from: installBtn.dataset.from || '',
                to: installBtn.dataset.to || '',
            }, cat);
            return;
        }
        if (e.target.closest('[data-src-browse]')) {
            const cat = row.querySelector('[data-src-catalog]');
            if (!cat.hidden) { cat.hidden = true; return; }
            this._browseSource(url, row.querySelector('.plugins-source__ref')?.textContent.replace('@ ', '').trim(), cat);
        }
        if (e.target.closest('[data-src-catalog-refresh]')) {
            const cat = row.querySelector('[data-src-catalog]');
            this._browseSource(url, cat.dataset.ref, cat);
        }
    }

    async _addSource() {
        const url = (this.srcUrlEl.value || '').trim();
        const ref = (this.srcRefEl.value || '').trim();
        if (!url) return;
        const ok = await this._confirm(
            `Add "${url}" as a plugin source?\n\nA source repository can install plugins that run in-process ` +
            `with the Meshpoint service's privileges, and their setup scripts run as root. ` +
            `Only add repositories whose author you trust.`,
            { label: 'Add plugin source?', command: `add source ${url}` },
        );
        if (!ok) return;
        this._setSrcStatus('pending', 'Adding…');
        try {
            const r = await fetch('/api/plugin-sources', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, ref: ref || 'main', confirm: true }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) { this._setSrcStatus('error', body.detail || `Failed (HTTP ${r.status}).`); return; }
            this.srcUrlEl.value = ''; this.srcRefEl.value = '';
            this._setSrcStatus('success', 'Source added.');
            this._loadSources();
        } catch (e) {
            this._setSrcStatus('error', e.message || 'Failed.');
        }
    }

    async _removeSource(url) {
        const ok = await this._confirm(
            `Forget "${url}"? Plugins already installed from it are not removed.`,
            { label: 'Remove plugin source?', command: `remove source ${url}` },
        );
        if (!ok) return;
        try {
            const r = await fetch(`/api/plugin-sources?url=${encodeURIComponent(url)}`, {
                method: 'DELETE', credentials: 'same-origin',
            });
            if (r.ok) { this._setSrcStatus('success', 'Source removed.'); this._loadSources(); }
            else this._setSrcStatus('error', `Failed (HTTP ${r.status}).`);
        } catch (e) { this._setSrcStatus('error', e.message || 'Failed.'); }
    }

    async _browseSource(url, ref, catEl) {
        catEl.hidden = false;
        catEl.innerHTML = '<p class="plugins-sources__empty">Loading catalog…</p>';
        let cat = null;
        try {
            const qs = `url=${encodeURIComponent(url)}${ref ? `&ref=${encodeURIComponent(ref)}` : ''}`;
            const r = await fetch(`/api/plugin-sources/catalog?${qs}`, { credentials: 'same-origin' });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) { catEl.innerHTML = `<p class="plugins-panel__status" data-kind="error">${this._escape(body.detail || `HTTP ${r.status}`)}</p>`; return; }
            cat = body;
        } catch (e) {
            catEl.innerHTML = `<p class="plugins-panel__status" data-kind="error">${this._escape(e.message || 'Failed')}</p>`;
            return;
        }
        catEl.dataset.ref = cat.ref || 'main';
        const rows = [...(cat.plugins || []), ...(cat.themes || [])];
        if (!rows.length) {
            catEl.innerHTML = '<p class="plugins-sources__empty">This source lists no plugins or themes.</p>';
            return;
        }
        catEl.innerHTML = `
            <p class="plugins-sources__catmeta">${this._escape(cat.name || url)} — <code>@ ${this._escape(cat.ref)}</code></p>
            <table class="plugins-table"><tbody>
            ${rows.map((p) => {
                const down = p.update_available
                    && this._cmpVersions(p.version, p.installed_version) < 0;
                const badge = !p.compatible
                    ? '<span class="plugin-row__badge plugin-row__badge--community">needs newer Meshpoint</span>'
                    : p.update_available
                        ? `<span class="plugin-row__count">${down ? 'downgrade' : 'update'} ${this._escape(p.installed_version)} → ${this._escape(p.version)}</span>`
                        : p.installed
                            ? '<span class="plugin-row__badge plugin-row__badge--builtin">installed</span>'
                            : '';
                const attrs = (action) => `data-src-install data-id="${this._escape(p.id)}" `
                    + `data-action="${action}" data-from="${this._escape(p.installed_version || '')}" `
                    + `data-to="${this._escape(p.version)}"`;
                let btn;
                if (!p.compatible) {
                    btn = '<button type="button" class="terminal-button" disabled title="Update Meshpoint first">Install</button>';
                } else if (p.update_available) {
                    btn = `<button type="button" class="terminal-button" ${attrs(down ? 'downgrade' : 'update')}>${down ? 'Downgrade' : 'Update'}</button>`;
                } else if (p.installed) {
                    btn = `<button type="button" class="terminal-button" ${attrs('reinstall')} title="Replace with a fresh copy from the source">Reinstall</button>`;
                } else {
                    btn = `<button type="button" class="terminal-button" ${attrs('install')}>Install</button>`;
                }
                return `<tr>
                    <td><span class="plugin-row__name">${this._escape(p.id)}</span>
                        <span class="plugin-row__version">v${this._escape(p.version)} · ${this._escape(p.kind)}${p.author ? ` · ${this._escape(p.author)}` : ''}</span>
                        ${p.description ? `<span class="plugin-row__version">${this._escape(p.description)}</span>` : ''}</td>
                    <td class="plugins-source__catright">${badge}${btn}</td>
                </tr>`;
            }).join('')}
            </tbody></table>`;
    }

    async _installFromSource(url, id, ref, opts, catEl) {
        const { action = 'install', from = '', to = '' } = opts || {};
        const VERB = { install: 'Install', update: 'Update', downgrade: 'Downgrade', reinstall: 'Reinstall' };
        const PROG = { install: 'Installing', update: 'Updating', downgrade: 'Downgrading', reinstall: 'Reinstalling' };
        const DONE = { install: 'Installed', update: 'Updated', downgrade: 'Downgraded', reinstall: 'Reinstalled' };
        const verb = VERB[action] || 'Install';

        let extra = '';
        if (action === 'downgrade') {
            extra = `\n\n⚠ This is a DOWNGRADE (v${from} → v${to}). Older plugin code may not read data or config written by the newer version — only go back if you know the older version works for you.`;
        } else if (action === 'reinstall') {
            extra = `\n\nThis replaces the plugin's files with a fresh v${to} copy from the source — any changes you made to it on the device are lost. Its enabled state is kept.`;
        }
        const ok = await this._confirm(
            `${verb} "${id}" from ${url}${ref ? ` @ ${ref}` : ''}?${extra}\n\n` +
            `Meshpoint downloads just this plugin's files, re-validates its plugin.toml, ` +
            `and places it in plugins/apps/.${action === 'install' ? ' It stays disabled until you enable it.' : ''} ` +
            `Any setup.sh is a separate step.`,
            { label: `${verb} plugin?`, command: `${verb.toLowerCase()} ${id}` },
        );
        if (!ok) return;
        this._setSrcStatus('pending', `${PROG[action]} ${id}…`);
        try {
            const r = await fetch('/api/plugin-sources/install', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, id, ref: ref || null }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) { this._setSrcStatus('error', body.detail || `Failed (HTTP ${r.status}).`); return; }
            this._setSrcStatus('success',
                `${DONE[action]} ${id} v${body.version}. ` +
                `${body.has_setup ? 'It needs setup — enable it and run setup below, then restart.'
                    : 'Enable it in the list above and restart to load it.'}`);
            delete this._updates[id];
            this.refresh();
            this._loadSources();
            if (catEl) this._browseSource(url, ref, catEl);
        } catch (e) {
            this._setSrcStatus('error', e.message || 'Failed.');
        }
    }

    async _updatePluginFromRow(plugin, button, resultEl) {
        const upd = this._updates[plugin.id];
        if (!upd) return;
        const down = upd.downgrade;
        const verb = down ? 'Downgrade' : 'Update';
        const warn = down
            ? `\n\n⚠ This is a DOWNGRADE (v${upd.installed_version} → v${upd.version}). Older plugin code may not read data or config written by the newer version — only go back if you know the older version works for you.`
            : '';
        const ok = await this._confirm(
            `${verb} "${plugin.id}" from v${upd.installed_version} to v${upd.version}?${warn}\n\n` +
            `Downloaded from ${upd.url}${upd.ref ? ` @ ${upd.ref}` : ''}, re-validated, and ` +
            `installed in place. Its enabled state is kept — restart to load the new version.`,
            { label: `${verb} plugin?`, command: `${verb.toLowerCase()} ${plugin.id}` },
        );
        if (!ok) return;
        button.disabled = true;
        resultEl.dataset.kind = 'pending';
        resultEl.textContent = `${down ? 'Downgrading' : 'Updating'}…`;
        try {
            const r = await fetch('/api/plugin-sources/install', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: upd.url, id: plugin.id, ref: upd.ref || null }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) {
                resultEl.dataset.kind = 'error';
                resultEl.textContent = body.detail || `Failed (HTTP ${r.status}).`;
                button.disabled = false;
                return;
            }
            delete this._updates[plugin.id];
            this._pendingMessage = {
                id: plugin.id, kind: 'success',
                text: `${down ? 'Downgraded' : 'Updated'} to v${body.version}. Restart to load it.`,
            };
            await this.refresh();
            this._loadSources();
        } catch (_e) {
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
            button.disabled = false;
        }
    }

    _setSrcStatus(kind, message) {
        if (!this.srcStatusEl) return;
        this.srcStatusEl.dataset.kind = kind;
        this.srcStatusEl.textContent = message;
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
        // A source offers a different version than what's installed -- one
        // button on the row (Update, or Downgrade + a caution colour when
        // the offered version is older), so the operator doesn't have to
        // open Browse to find it. See _scanSource()/_updatePluginFromRow().
        const upd = this._updates[plugin.id];
        const updateBtnHtml = upd
            ? `<button type="button" class="plugin-row__update${upd.downgrade ? ' plugin-row__update--down' : ''}" data-plugin-update title="From ${this._escape(upd.url)}">`
              + `${upd.downgrade ? 'Downgrade' : 'Update'} v${this._escape(upd.installed_version)} &rarr; v${this._escape(upd.version)}</button>`
            : '';
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
                ${updateBtnHtml}
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
        const updBtn = row.querySelector('[data-plugin-update]');
        if (updBtn) {
            updBtn.addEventListener('click', () => this._updatePluginFromRow(plugin, updBtn, resultEl));
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
