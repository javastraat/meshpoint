/**
 * Settings → Meshpoint panel controller (service actions).
 *
 * Single responsibility: load the action catalog from
 * ``GET /api/dangerous/actions``, render one card per action, and
 * route every press through ``DangerousModal`` for a click-to-confirm
 * dialog before invoking ``POST /api/dangerous/invoke``. Live result
 * is surfaced inline next to the action so the operator sees the
 * outcome without leaving the panel.
 */

class DangerousPanelController {
    constructor(rootEl) {
        this.root = rootEl;
        this.listEl = rootEl.querySelector('[data-dangerous-list]');
        this.statusEl = rootEl.querySelector('[data-dangerous-status]');
        this.modal = new window.DangerousModal();
        this._actions = [];
        this.wtCardEl = rootEl.querySelector('[data-web-terminal-card]');
        this.wtToggle = rootEl.querySelector('[data-web-terminal-toggle]');
        this.wtStatusEl = rootEl.querySelector('[data-web-terminal-status]');
        this.lpSelect = rootEl.querySelector('[data-landing-page-select]');
        this.lpStatusEl = rootEl.querySelector('[data-landing-page-status]');
    }

    bind() {
        if (this.wtToggle) {
            this.wtToggle.addEventListener('change', () => this._onWebTerminalToggle());
        }
        if (this.lpSelect) {
            this.lpSelect.addEventListener('change', () => this._onLandingPageChange());
        }
    }

    async refresh() {
        this._loadWebTerminalState();
        this._loadLandingPageState();
        try {
            const response = await fetch('/api/dangerous/actions', {
                credentials: 'same-origin',
            });
            if (!response.ok) {
                this._setStatus('error', `Could not load actions (HTTP ${response.status}).`);
                return;
            }
            const body = await response.json();
            this._actions = body.actions || [];
            this._render();
        } catch (_e) {
            this._setStatus('error', 'Network error loading actions.');
        }
    }

    // ── Web terminal enable/disable ─────────────────────────────────────

    /** The whole card starts `hidden` in the markup (index.html) -- it
     * only appears once ``dashboard.web_terminal_toggle`` confirms true.
     * That flag has no API/UI of its own to set it (filesystem-only, see
     * src/config.py and update_dashboard()'s 403 in config_routes.py), so
     * unlike the plugin-sources disabled state, there's deliberately no
     * "this is disabled, here's how to enable it" note either -- an
     * operator who never opted in shouldn't see any hint the web terminal
     * exists at all. Leaving it hidden is also the safe default on a
     * failed fetch, same reasoning as _renderSourcesGate() in
     * plugins_panel_controller.js. */
    async _loadWebTerminalState() {
        if (!this.wtToggle) return;
        try {
            const r = await fetch('/api/config', { credentials: 'same-origin' });
            if (!r.ok) { this._setWtStatus('error', `Could not load (HTTP ${r.status}).`); return; }
            const cfg = await r.json();
            if (!(cfg.dashboard && cfg.dashboard.web_terminal_toggle)) return;
            if (this.wtCardEl) this.wtCardEl.hidden = false;
            const on = !!(cfg.dashboard && cfg.dashboard.web_terminal_enabled);
            this.wtToggle.checked = on;
            this.wtToggle.disabled = false;
            this._setWtStatus('', on ? 'On.' : 'Off — the Terminal page is hidden and its API is disabled.');
        } catch (_e) {
            this._setWtStatus('error', 'Network error.');
        }
    }

    async _onWebTerminalToggle() {
        const want = this.wtToggle.checked;
        if (want) {
            const ok = await this.modal.confirm({
                label: 'Enable the web terminal?',
                command: 'Enable web terminal',
                description:
                    'This exposes a full shell on the device at Ops → Terminal. It can run ' +
                    'sudo (package installs, plugin setup, service control), so anyone with ' +
                    'an admin session — or anything that hijacks one — effectively has root ' +
                    'on this host. Only enable it if you actively use it. Restart required.',
            });
            if (!ok) { this.wtToggle.checked = false; return; }
        }
        this.wtToggle.disabled = true;
        this._setWtStatus('pending', 'Saving…');
        try {
            const r = await fetch('/api/config/dashboard', {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ web_terminal_enabled: want }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) {
                this.wtToggle.checked = !want;
                this._setWtStatus('error', body.detail || `Failed (HTTP ${r.status}).`);
                return;
            }
            this._setWtStatus('success',
                `${want ? 'Enabled' : 'Disabled'}. Restart the service to apply — `
                + 'use "Restart service" in Plugins, or reboot.');
        } catch (_e) {
            this.wtToggle.checked = !want;
            this._setWtStatus('error', 'Network error.');
        } finally {
            this.wtToggle.disabled = false;
        }
    }

    _setWtStatus(kind, message) {
        if (!this.wtStatusEl) return;
        this.wtStatusEl.dataset.kind = kind;
        this.wtStatusEl.textContent = message;
    }

    // ── Landing page ─────────────────────────────────────────────────────

    /** Options are "Dashboard" (always) plus every currently-mounted
     * "top"-category plugin in `window.MESHPOINT_SIDEBAR_PLUGINS`
     * (server-injected by src/plugins/assets.py -- a disabled plugin
     * never gets a descriptor there, so it never shows up as a choice
     * here either, matching what the backend accepts). Current value
     * comes from GET /api/config's `dashboard.landing_page`. */
    async _loadLandingPageState() {
        if (!this.lpSelect) return;
        const topPages = (window.MESHPOINT_SIDEBAR_PLUGINS || [])
            .filter((p) => p.category === 'top');
        const options = [{ route: 'dashboard', label: 'Dashboard' }, ...topPages];
        this.lpSelect.innerHTML = options
            .map((p) => `<option value="${this._escape(p.route)}">${this._escape(p.label)}</option>`)
            .join('');
        try {
            const r = await fetch('/api/config', { credentials: 'same-origin' });
            if (!r.ok) { this._setLpStatus('error', `Could not load (HTTP ${r.status}).`); return; }
            const cfg = await r.json();
            const current = (cfg.dashboard && cfg.dashboard.landing_page) || 'dashboard';
            if (options.some((p) => p.route === current)) this.lpSelect.value = current;
            this.lpSelect.disabled = false;
        } catch (_e) {
            this._setLpStatus('error', 'Network error.');
        }
    }

    async _onLandingPageChange() {
        const landingPage = this.lpSelect.value;
        this.lpSelect.disabled = true;
        this._setLpStatus('pending', 'Saving…');
        try {
            const r = await fetch('/api/config/dashboard', {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ landing_page: landingPage }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) {
                this._setLpStatus('error', body.detail || `Failed (HTTP ${r.status}).`);
                return;
            }
            this._setLpStatus('success', 'Saved.');
        } catch (_e) {
            this._setLpStatus('error', 'Network error.');
        } finally {
            this.lpSelect.disabled = false;
        }
    }

    _setLpStatus(kind, message) {
        if (!this.lpStatusEl) return;
        this.lpStatusEl.dataset.kind = kind;
        this.lpStatusEl.textContent = message;
    }

    _render() {
        if (!this.listEl) return;
        this.listEl.innerHTML = '';
        this._actions.forEach((action) => {
            this.listEl.appendChild(this._renderCard(action));
        });
    }

    _renderCard(action) {
        const card = document.createElement('article');
        card.className = 'dangerous-card';
        card.innerHTML = `
            <header class="dangerous-card__head">
                <h3 class="dangerous-card__title">${this._escape(action.label)}</h3>
                <span class="dangerous-card__pill">irreversible</span>
            </header>
            <p class="dangerous-card__description">${this._escape(action.description)}</p>
            <div class="dangerous-card__actions">
                <button class="terminal-button terminal-button--danger" type="button" data-invoke>${this._escape(action.label)}</button>
            </div>
            <p class="dangerous-card__result" data-result aria-live="polite"></p>
        `;
        const button = card.querySelector('[data-invoke]');
        const resultEl = card.querySelector('[data-result]');
        button.addEventListener('click', () => this._invoke(action, button, resultEl));
        return card;
    }

    async _invoke(action, button, resultEl) {
        const ok = await this.modal.confirm({
            label: action.confirmation_text,
            command: action.label,
            description: action.description,
        });
        if (!ok) return;
        button.disabled = true;
        resultEl.dataset.kind = 'pending';
        resultEl.textContent = 'Invoking…';
        try {
            const response = await fetch('/api/dangerous/invoke', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action_id: action.id }),
            });
            if (!response.ok) {
                resultEl.dataset.kind = 'error';
                resultEl.textContent = `Failed (HTTP ${response.status}).`;
                return;
            }
            const body = await response.json();
            resultEl.dataset.kind = body.success ? 'success' : 'error';
            resultEl.textContent = body.message || (body.success ? 'Done.' : 'Failed.');
        } catch (_e) {
            resultEl.dataset.kind = 'error';
            resultEl.textContent = 'Network error.';
        } finally {
            button.disabled = false;
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

window.DangerousPanelController = DangerousPanelController;
