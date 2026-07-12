/**
 * Configuration → Metrics card.
 *
 * Single responsibility: edit the `metrics` section (Prometheus-
 * compatible /metrics scrape endpoint). Unlike most config pages, this
 * one applies live -- metrics_routes.py reads config.metrics fresh on
 * every request, so toggling either field takes effect immediately,
 * no service restart needed.
 */

class MetricsConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
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
                        When on, a scraper needs a valid dashboard session -- either the
                        browser session cookie, or an <code>Authorization: Bearer &lt;token&gt;</code>
                        header. These are short-lived login session tokens, not a
                        long-lived API key, so this is awkward for an unattended
                        Prometheus scrape config. When off, the endpoint is fully
                        open to anyone who can reach it on the network; it exposes
                        only aggregate stats (packet/node counts, signal averages),
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
            </div>
        `;

        this._root.querySelector('[data-metrics-save]')
            .addEventListener('click', () => this._save());
    }

    render(config) {
        const metrics = config.metrics || {};
        const enableEl = this._root.querySelector('[data-metrics-enable]');
        if (enableEl) enableEl.checked = !!metrics.enabled;
        const authEl = this._root.querySelector('[data-metrics-auth]');
        if (authEl) authEl.checked = metrics.require_auth !== false;
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
}

window.MetricsConfigCard = MetricsConfigCard;
