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
        this._plugins = [];
        this._modal = null;
    }

    bind() {
        if (this.restartBtn) {
            this.restartBtn.addEventListener('click', () => this._restartService());
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
                this.restartBtn.disabled = false;
                return;
            }
            const body = await response.json();
            this._setRestartStatus(
                body.success ? 'success' : 'error',
                body.success
                    ? 'Restarting… the dashboard will reconnect in a few seconds.'
                    : (body.message || 'Restart failed.'),
            );
        } catch (_e) {
            this._setRestartStatus('error', 'Network error.');
            this.restartBtn.disabled = false;
        }
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

    _render() {
        if (!this.listEl) return;
        if (!this._plugins.length) {
            this.listEl.innerHTML = '';
            return;
        }
        this.listEl.innerHTML = `<table class="plugins-table">
            <thead><tr><th>Plugin</th><th>Source</th><th>Provides</th><th></th></tr></thead>
            <tbody></tbody>
        </table>`;
        const tbody = this.listEl.querySelector('tbody');
        this._plugins.forEach((plugin) => {
            tbody.appendChild(this._renderRow(plugin));
        });
    }

    _renderRow(plugin) {
        const row = document.createElement('tr');
        const badgeMod = plugin.source === 'builtin' ? 'builtin' : 'community';
        const badgeLabel = plugin.source === 'builtin' ? 'Built-in' : 'Community';
        const provides = (plugin.provides || []).join(', ') || '-';
        const depsNote = (plugin.apt_deps || []).length
            ? `<p class="plugin-row__deps">Requires: <code>${this._escape(plugin.apt_deps.join(', '))}</code>${plugin.setup_script ? ` — run <code>sudo bash plugins/apps/${this._escape(plugin.id)}/${this._escape(plugin.setup_script)}</code> on the device` : ''}</p>`
            : '';
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
            </td>
            <td class="plugin-row__act">
                <label class="r-switch">
                    <input type="checkbox" data-toggle ${plugin.enabled ? 'checked' : ''}>
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
            if (!response.ok) {
                toggle.checked = !enabled;
                resultEl.dataset.kind = 'error';
                resultEl.textContent = response.status === 403
                    ? 'Admin role required.'
                    : `Failed (HTTP ${response.status}).`;
                return;
            }
            const body = await response.json();
            plugin.enabled = body.plugin.enabled;
            plugin.restart_required = body.plugin.restart_required;
            resultEl.dataset.kind = 'success';
            resultEl.textContent = 'Saved. Restart to apply.';
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
