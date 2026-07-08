/**
 * Configuration → Transmit card.
 *
 * Single responsibility: edit the ``transmit`` block in ``local.yaml``
 * (TX power, max duty cycle, relay enable, relay rate limits). Shares
 * the ``api`` helper shape used by the existing Radio cards so the
 * surrounding orchestrator can reuse the same plumbing.
 */

class TransmitConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <article class="cfg-card">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">Transmit</h3>
                    <p class="cfg-card__hint">Native TX and onboard SX1302 relay. Enable relay here; burst and RSSI filters apply to concentrator rebroadcasts.</p>
                </header>
                <form class="cfg-form" data-tx-form>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-tx-enabled>
                        <span class="cfg-field__label">Native TX enabled</span>
                    </label>
                    <p class="cfg-card__hint cfg-card__hint--nested">
                        Required for MeshCore companion status, dashboard messaging,
                        and Send Advert. USB packet capture works independently when
                        the MeshCore USB source is enabled.
                    </p>
                    <label class="cfg-field">
                        <span class="cfg-field__label">TX power (dBm)</span>
                        <input class="cfg-field__input" type="number" min="0" max="30" step="1" data-tx-power>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Max duty cycle (%)</span>
                        <input class="cfg-field__input" type="number" min="0" max="100" step="0.1" data-tx-duty>
                    </label>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-tx-relay-enable>
                        <span class="cfg-field__label">Relay enabled</span>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Relay max / minute</span>
                        <input class="cfg-field__input" type="number" min="0" max="600" step="1" data-tx-relay-rate>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Relay burst size</span>
                        <input class="cfg-field__input" type="number" min="1" max="50" step="1" data-tx-relay-burst>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Relay min RSSI (dBm)</span>
                        <input class="cfg-field__input" type="number" min="-150" max="0" step="1" data-tx-relay-rssi-min>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Relay max RSSI (dBm)</span>
                        <input class="cfg-field__input" type="number" min="-150" max="0" step="1" data-tx-relay-rssi-max>
                    </label>
                    <p class="cfg-card__hint cfg-card__hint--nested">
                        Only packets heard between min and max RSSI are
                        rebroadcast: skips signals too weak to be real and
                        strong ones every node already hears. Burst caps
                        back-to-back relays inside the per-minute budget.
                    </p>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary" type="submit">Save</button>
                    </div>
                    <p class="cfg-status" data-tx-status aria-live="polite"></p>
                </form>
            </article>
        `;
        this._form = this._root.querySelector('[data-tx-form]');
        this._enabledEl = this._root.querySelector('[data-tx-enabled]');
        this._powerEl = this._root.querySelector('[data-tx-power]');
        this._dutyEl = this._root.querySelector('[data-tx-duty]');
        this._relayEnable = this._root.querySelector('[data-tx-relay-enable]');
        this._relayRate = this._root.querySelector('[data-tx-relay-rate]');
        this._relayBurst = this._root.querySelector('[data-tx-relay-burst]');
        this._relayRssiMin = this._root.querySelector('[data-tx-relay-rssi-min]');
        this._relayRssiMax = this._root.querySelector('[data-tx-relay-rssi-max]');
        this._statusEl = this._root.querySelector('[data-tx-status]');
        this._form.addEventListener('submit', (e) => this._onSubmit(e));
    }

    render(config) {
        const tx = (config && config.transmit) || {};
        if (this._enabledEl) this._enabledEl.checked = !!tx.enabled;
        if (this._powerEl && tx.tx_power_dbm != null) this._powerEl.value = tx.tx_power_dbm;
        if (this._dutyEl && tx.max_duty_cycle_percent != null) this._dutyEl.value = tx.max_duty_cycle_percent;
        if (this._relayEnable) this._relayEnable.checked = !!(tx.relay && tx.relay.enabled);
        if (this._relayRate && tx.relay && tx.relay.max_relay_per_minute != null) {
            this._relayRate.value = tx.relay.max_relay_per_minute;
        }
        if (this._relayBurst && tx.relay && tx.relay.burst_size != null) {
            this._relayBurst.value = tx.relay.burst_size;
        }
        if (this._relayRssiMin && tx.relay && tx.relay.min_relay_rssi != null) {
            this._relayRssiMin.value = tx.relay.min_relay_rssi;
        }
        if (this._relayRssiMax && tx.relay && tx.relay.max_relay_rssi != null) {
            this._relayRssiMax.value = tx.relay.max_relay_rssi;
        }
    }

    async _onSubmit(event) {
        event.preventDefault();
        const relay = { enabled: this._relayEnable.checked };
        const rateRaw = this._relayRate.value.trim();
        if (rateRaw !== '') {
            const rate = Number(rateRaw);
            if (!Number.isFinite(rate)) {
                this._setStatus('error', 'Relay rate must be a number.');
                return;
            }
            relay.max_relay_per_minute = rate;
        }

        const filters = this._collectRelayFilters();
        if (filters === null) return; // _collectRelayFilters set the status

        const payload = {
            enabled: this._enabledEl.checked,
            tx_power_dbm: Number(this._powerEl.value),
            max_duty_cycle_percent: Number(this._dutyEl.value),
            relay,
        };
        this._setStatus('pending', 'Saving…');
        const txResult = await this._api.put('/api/config/transmit', payload);
        if (!txResult) {
            this._setStatus('error', 'Transmit save failed.');
            return;
        }

        if (Object.keys(filters).length) {
            const relayResult = await this._api.put('/api/config/relay', filters);
            if (!relayResult) {
                this._setStatus('error', 'Relay filter save failed.');
                return;
            }
        }

        this._setStatus('success', 'Saved.');
        this._api.signalRestart('Transmit settings updated.');
    }

    /**
     * Burst + RSSI window go to PUT /api/config/relay (the transmit
     * endpoint only carries enable/rate). Returns {} when all three are
     * blank, or null after flagging invalid input in the status line.
     */
    _collectRelayFilters() {
        const filters = {};
        const fields = [
            [this._relayBurst, 'burst_size', 'Relay burst size'],
            [this._relayRssiMin, 'min_relay_rssi', 'Relay min RSSI'],
            [this._relayRssiMax, 'max_relay_rssi', 'Relay max RSSI'],
        ];
        for (const [el, key, label] of fields) {
            const raw = el ? el.value.trim() : '';
            if (raw === '') continue;
            const num = Number(raw);
            if (!Number.isFinite(num)) {
                this._setStatus('error', `${label} must be a number.`);
                return null;
            }
            filters[key] = num;
        }
        if (
            filters.min_relay_rssi != null
            && filters.max_relay_rssi != null
            && filters.max_relay_rssi <= filters.min_relay_rssi
        ) {
            this._setStatus('error', 'Relay max RSSI must be above min RSSI.');
            return null;
        }
        return filters;
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }
}

window.TransmitConfigCard = TransmitConfigCard;
