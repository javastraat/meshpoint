/**
 * Configuration → Metrics card.
 *
 * Single responsibility: edit the `metrics` section (Prometheus-
 * compatible /metrics scrape endpoint). Unlike most config pages, this
 * one applies live -- metrics_routes.py reads config.metrics fresh on
 * every request, so toggling either field takes effect immediately,
 * no service restart needed.
 *
 * Also manages named, revocable API keys scoped to /metrics,
 * /api/device/metrics, and /api/stats/summary -- a small fixed
 * allowlist, not general dashboard access -- letting an unattended
 * scraper (Home Assistant, Prometheus) authenticate with a static
 * `Authorization: Bearer <key>` header instead of a short-lived
 * dashboard session. Each key's raw value is shown exactly once at
 * creation time; only its hash is ever stored or returned afterward.
 */

class MetricsConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._revealedKey = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-metrics-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Prometheus metrics</h3>
                        <p class="cfg-card__hint">
                            Exposes a <code>/metrics</code> endpoint in Prometheus text
                            format (uptime, packet counts, RSSI/SNR averages, node
                            counts). Passive -- Meshpoint never sends this anywhere;
                            a Prometheus server you run elsewhere would scrape
                            (periodically fetch) this URL on its own schedule.
                            Changes apply immediately, no restart needed.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-metrics-enable>
                        <span class="cfg-field__label">Enable /metrics endpoint</span>
                    </label>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-metrics-auth>
                        <span class="cfg-field__label">Require authentication</span>
                    </label>
                    <p class="cfg-card__hint" data-metrics-auth-hint>
                        When on, a scraper needs a valid dashboard session (browser
                        cookie or session Bearer token) <strong>or</strong> one of the
                        API keys below. When off, the endpoint is fully open to
                        anyone who can reach it on the network; it exposes only
                        aggregate stats (packet/node counts, signal averages),
                        never credentials or channel keys.
                    </p>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-metrics-save>
                            Save
                        </button>
                    </div>
                    <p class="cfg-status" data-metrics-status aria-live="polite"></p>
                </article>

                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">API keys</h3>
                        <p class="cfg-card__hint">
                            Named, revocable bearer keys scoped to <code>/metrics</code>,
                            <code>/api/device/metrics</code>, and
                            <code>/api/stats/summary</code> -- read-only status data,
                            never config, control, messages, or node content. Use one
                            per consumer (e.g. "Home Assistant", "Prometheus") so you
                            can revoke individually. Send as
                            <code>Authorization: Bearer &lt;key&gt;</code>.
                        </p>
                    </header>
                    <div class="cfg-companions" data-metrics-keys></div>
                    <div class="cfg-metrics-key-add">
                        <input class="cfg-field__input" type="text" maxlength="64"
                               placeholder="Label, e.g. Home Assistant"
                               data-metrics-key-label>
                        <button class="terminal-button" type="button"
                                data-metrics-key-generate>
                            + Generate key
                        </button>
                    </div>
                    <div class="cfg-reveal" data-metrics-key-reveal hidden></div>
                    <p class="cfg-status" data-metrics-keys-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._root.querySelector('[data-metrics-save]')
            .addEventListener('click', () => this._save());
        this._root.querySelector('[data-metrics-key-generate]')
            .addEventListener('click', () => this._generateKey());
    }

    render(config) {
        const metrics = config.metrics || {};
        const enableEl = this._root.querySelector('[data-metrics-enable]');
        if (enableEl) enableEl.checked = !!metrics.enabled;
        const authEl = this._root.querySelector('[data-metrics-auth]');
        if (authEl) authEl.checked = metrics.require_auth !== false;

        const keys = Array.isArray(metrics.api_keys) ? metrics.api_keys : [];
        this._renderKeyList(keys);
        this._renderReveal();
    }

    async _save() {
        const status = this._root.querySelector('[data-metrics-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const result = await this._api.put('/api/config/metrics', {
            enabled: this._root.querySelector('[data-metrics-enable]').checked,
            require_auth: this._root.querySelector('[data-metrics-auth]').checked,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved — applied immediately.';
            this._api.toast('Metrics settings saved');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _renderKeyList(keys) {
        const listEl = this._root.querySelector('[data-metrics-keys]');
        if (!listEl) return;

        if (keys.length === 0) {
            listEl.innerHTML = '<p class="cfg-card__hint">No API keys yet.</p>';
            return;
        }

        listEl.innerHTML = '';
        keys.forEach((k) => {
            const row = document.createElement('div');
            row.className = 'cfg-companion';
            row.innerHTML = `
                <div class="cfg-companion__header">
                    <span class="cfg-companion__num">${this._esc(k.label)}</span>
                    <button class="cfg-companion__remove terminal-button terminal-button--danger"
                            type="button" title="Revoke key">✕</button>
                </div>
                <p class="cfg-companion__offline-hint">
                    Created ${this._formatDate(k.created_at)} ·
                    Last used ${k.last_used_at ? this._formatDate(k.last_used_at) : 'never'}
                </p>
            `;
            row.querySelector('.cfg-companion__remove')
                .addEventListener('click', () => this._revokeKey(k.id, k.label));
            listEl.appendChild(row);
        });
    }

    async _generateKey() {
        const input = this._root.querySelector('[data-metrics-key-label]');
        const label = (input.value || '').trim();
        const status = this._root.querySelector('[data-metrics-keys-status]');

        if (!label) {
            status.dataset.kind = 'error';
            status.textContent = 'Give the key a label first.';
            return;
        }

        status.dataset.kind = 'pending';
        status.textContent = 'Generating…';

        const result = await this._api.post('/api/config/metrics/api-keys', { label });

        if (result) {
            input.value = '';
            status.dataset.kind = 'success';
            status.textContent = 'Key created.';
            this._revealedKey = result;
            this._renderReveal();
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Generate failed.';
        }
    }

    async _revokeKey(id, label) {
        const confirmed = await this._confirm({
            label: `Revoke "${label}"`,
            description: 'Anything using this key (a Home Assistant sensor, a Prometheus scrape config, etc.) will stop working immediately.',
        });
        if (!confirmed) return;

        const status = this._root.querySelector('[data-metrics-keys-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Revoking…';

        const result = await this._api.delete(`/api/config/metrics/api-keys/${id}`);

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Key revoked.';
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Revoke failed.';
        }
    }

    _renderReveal() {
        const box = this._root.querySelector('[data-metrics-key-reveal]');
        if (!box) return;

        if (!this._revealedKey) {
            box.hidden = true;
            box.innerHTML = '';
            return;
        }

        const { label, key } = this._revealedKey;
        box.hidden = false;
        box.innerHTML = `
            <p class="cfg-card__hint">
                <strong>${this._esc(label)}</strong> — copy this key now, it will
                not be shown again:
            </p>
            <div class="cfg-reveal__row">
                <input class="cfg-field__input" type="text" readonly
                       value="${this._esc(key)}" data-metrics-key-reveal-input>
                <button class="terminal-button" type="button"
                        data-metrics-key-copy>Copy</button>
                <button class="terminal-button" type="button"
                        data-metrics-key-dismiss>Done</button>
            </div>
        `;

        box.querySelector('[data-metrics-key-copy]').addEventListener('click', async () => {
            const inputEl = box.querySelector('[data-metrics-key-reveal-input]');
            inputEl.select();
            try {
                await navigator.clipboard.writeText(key);
                this._api.toast('Copied to clipboard');
            } catch (e) {
                // Clipboard API may be unavailable (e.g. non-HTTPS LAN access);
                // the selected text still lets the user Ctrl/Cmd+C manually.
            }
        });
        box.querySelector('[data-metrics-key-dismiss]').addEventListener('click', () => {
            this._revealedKey = null;
            this._renderReveal();
        });
    }

    _formatDate(iso) {
        if (!iso) return 'never';
        try {
            return new Date(iso).toLocaleString(undefined, { hour12: false });
        } catch (e) {
            return iso;
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }

    /**
     * In-app confirmation dialog (replaces the browser's native
     * ``window.confirm`` popup). Uses the shared confirmModal helper;
     * falls back to native confirm if that script failed to load.
     */
    _confirm({ label, description }) {
        if (window.confirmModal) {
            return window.confirmModal({ label, description });
        }
        return Promise.resolve(window.confirm(`${label}\n\n${description}`));
    }
}

window.MetricsConfigCard = MetricsConfigCard;
