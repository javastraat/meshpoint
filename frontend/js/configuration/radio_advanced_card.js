/**
 * Configuration → Concentrator → Radio (advanced) card.
 *
 * Spectral scan interval and optional SX1261 SPI path, feeding the
 * hardware noise-floor readout (Band spectrum card, RF Environment tab).
 * Split out of the old Configuration → Advanced page (which also held
 * an unrelated Storage card) so it sits with the rest of the radio
 * settings instead of under Settings. Moved again, alongside Radio
 * (pager), out of Configuration → Radio (Meshtastic-specific: modem
 * presets, hop limit) into its own Concentrator page under the
 * Hardware sidebar group -- this card configures the concentrator's
 * shared RF hardware itself, not anything Meshtastic-protocol-specific.
 */

class RadioAdvancedConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <article class="cfg-card">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">Radio (advanced)</h3>
                    <p class="cfg-card__hint">Spectral scan and optional SX1261 SPI path for noise-floor readout.</p>
                </header>
                <form class="cfg-form" data-radio-adv-form>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Spectral scan interval (s)</span>
                        <input class="cfg-field__input" type="number" min="0" max="3600"
                               step="1" data-radio-scan-interval>
                        <span class="cfg-field__hint">0 disables hardware noise-floor scan.</span>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">SX1261 SPI path (optional)</span>
                        <input class="cfg-field__input" type="text"
                               placeholder="/dev/spidev0.1 or empty" data-radio-sx1261>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="submit">Save radio advanced</button>
                    </div>
                    <p class="cfg-status" data-radio-adv-status aria-live="polite"></p>
                </form>
            </article>
        `;
        this._radioAdvForm = this._root.querySelector('[data-radio-adv-form]');
        this._radioAdvForm.addEventListener('submit', (e) => this._saveRadioAdv(e));
    }

    render(config) {
        const radioAdv = config.radio_advanced || {};
        this._setVal('[data-radio-scan-interval]', radioAdv.spectral_scan_interval_seconds);
        this._setVal('[data-radio-sx1261]', radioAdv.sx1261_spi_path || '');
    }

    _setVal(sel, v) {
        const el = this._root.querySelector(sel);
        if (el && v != null) el.value = v;
    }

    async _saveRadioAdv(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-radio-adv-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/radio/advanced', {
            spectral_scan_interval_seconds: Number(
                this._root.querySelector('[data-radio-scan-interval]').value,
            ),
            sx1261_spi_path: this._root.querySelector('[data-radio-sx1261]').value.trim(),
        });
        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            if (result.restart_required) {
                this._api.signalRestart('Radio advanced updated.');
            } else {
                this._api.toast('Radio advanced updated.');
            }
            this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }
}

window.RadioAdvancedConfigCard = RadioAdvancedConfigCard;
