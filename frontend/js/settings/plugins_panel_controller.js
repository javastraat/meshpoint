/**
 * Settings -> Plugins panel controller.
 *
 * Loads the discovered app-plugin catalog from ``GET /api/plugins`` (built-in
 * + community, each with its configured `enabled` state and whether it's
 * actually `loaded` in the running process), renders one card per plugin
 * with a toggle switch, and persists flips through ``PUT /api/plugins/{id}``.
 * Enabling/disabling only takes effect on the next restart -- the panel says
 * so inline rather than pretending the change is live.
 */

class PluginsPanelController {
    constructor(rootEl) {
        this.root = rootEl;
        this.listEl = rootEl.querySelector('[data-plugins-list]');
        this.statusEl = rootEl.querySelector('[data-plugins-status]');
        this._plugins = [];
    }

    bind() {}

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
        this.listEl.innerHTML = '';
        this._plugins.forEach((plugin) => {
            this.listEl.appendChild(this._renderCard(plugin));
        });
    }

    _renderCard(plugin) {
        const card = document.createElement('article');
        card.className = 'plugin-card';
        const sourceLabel = plugin.source === 'builtin' ? 'built-in' : 'community';
        const provides = (plugin.provides || []).join(', ');
        const restartNote = plugin.restart_required
            ? `<p class="plugin-card__restart" data-restart>Restart required to ${plugin.enabled ? 'load' : 'unload'} this plugin.</p>`
            : '';
        const depsNote = (plugin.apt_deps || []).length
            ? `<p class="plugin-card__deps">Requires: <code>${this._escape(plugin.apt_deps.join(', '))}</code>${plugin.setup_script ? ` -- run <code>sudo bash plugins/apps/${this._escape(plugin.id)}/${this._escape(plugin.setup_script)}</code> on the device` : ''}</p>`
            : '';
        card.innerHTML = `
            <header class="plugin-card__head">
                <h3 class="plugin-card__title">${this._escape(plugin.id)}</h3>
                <span class="plugin-card__pill" data-pill="${plugin.source}">${sourceLabel}</span>
                <span class="plugin-card__version">v${this._escape(plugin.version)}</span>
                <label class="r-switch plugin-card__switch">
                    <input type="checkbox" data-toggle ${plugin.enabled ? 'checked' : ''}>
                    <span class="r-switch__track"></span>
                </label>
            </header>
            <p class="plugin-card__description">${this._escape(plugin.description) || 'No description provided.'}</p>
            <p class="plugin-card__meta">Provides: ${this._escape(provides) || '-'}${plugin.author ? ` &middot; by ${this._escape(plugin.author)}` : ''}</p>
            ${depsNote}
            ${restartNote}
            <p class="plugin-card__result" data-result aria-live="polite"></p>
        `;
        const toggle = card.querySelector('[data-toggle]');
        const resultEl = card.querySelector('[data-result]');
        toggle.addEventListener('change', () => this._setEnabled(plugin, toggle, resultEl));
        return card;
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
            resultEl.textContent = 'Saved. Restart the service to apply.';
        } catch (_e) {
            toggle.checked = !enabled;
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
        } finally {
            toggle.disabled = false;
        }
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
