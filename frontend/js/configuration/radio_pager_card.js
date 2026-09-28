/**
 * Configuration → Concentrator → Radio (pager) card.
 *
 * Emergency pager project: lets the concentrator's dedicated FSK channel
 * (ch9 -- independent hardware from every LoRa channel, its own sync
 * word) be tuned without hand-editing local.yaml. Still internal/
 * experimental, but confirmed working end-to-end on real hardware
 * (extra/pager_client.ino, a Heltec V3) as of 2026-08 -- see
 * src/api/routes/emergency_pager_routes.py. Always requires a restart;
 * nothing here is hot-reloadable. Lives under Configuration →
 * Concentrator (Hardware sidebar group), not Meshtastic -- ch9 is
 * independent of the Meshtastic protocol entirely.
 */

class RadioPagerConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <article class="cfg-card">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">Radio (pager)</h3>
                    <p class="cfg-card__hint">
                        Emergency pager project, ch9 (FSK) -- internal/experimental,
                        but confirmed working end-to-end on real hardware
                        (extra/pager_client, a Heltec V3) as of 2026-08. Frequency
                        must stay close enough to RF1's anchor in your configured
                        region for this hardware to actually tune to it (validated
                        on save) -- the default (869.4625 MHz) sits in ETSI EU868's
                        "sub-band P" high-power window; a US915 (or other region)
                        setup validates against that region's own anchor instead.
                    </p>
                </header>
                <form class="cfg-form" data-radio-pager-form>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-radio-pager-enabled>
                        <span class="cfg-field__label">Enable pager channel (ch9)</span>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">My pager capcode</span>
                        <input class="cfg-field__input" type="number" min="0"
                               placeholder="e.g. 123456" data-radio-pager-capcode>
                        <span class="cfg-field__hint">
                            This device's own POCSAG-style address -- the "from" on every
                            message it sends, and required before it will transmit at all.
                            Also lets it recognize (and hide) its own transmission leaking
                            back into its own receiver.
                        </span>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Frequency (MHz)</span>
                        <input class="cfg-field__input" type="number" min="869.40" max="869.65"
                               step="0.0001" data-radio-pager-freq>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Sync word (hex)</span>
                        <input class="cfg-field__input" type="text"
                               placeholder="e.g. 946437" data-radio-pager-syncword>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Sync word size (bytes)</span>
                        <input class="cfg-field__input" type="number" min="1" max="8"
                               step="1" data-radio-pager-syncword-size>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="submit">Save radio pager</button>
                    </div>
                    <p class="cfg-status" data-radio-pager-status aria-live="polite"></p>
                </form>
            </article>
        `;
        this._form = this._root.querySelector('[data-radio-pager-form]');
        this._form.addEventListener('submit', (e) => this._save(e));
    }

    render(config) {
        const pager = config.radio_pager || {};
        const enabled = this._root.querySelector('[data-radio-pager-enabled]');
        if (enabled) enabled.checked = !!pager.pager_enabled;
        this._setVal('[data-radio-pager-capcode]', pager.pager_capcode);
        this._setVal('[data-radio-pager-freq]', pager.pager_frequency_mhz);
        this._setVal('[data-radio-pager-syncword]', pager.pager_sync_word_hex);
        this._setVal('[data-radio-pager-syncword-size]', pager.pager_sync_word_size);
    }

    _setVal(sel, v) {
        const el = this._root.querySelector(sel);
        if (el && v != null) el.value = v;
    }

    async _save(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-radio-pager-status]');
        const syncwordRaw = this._root.querySelector('[data-radio-pager-syncword]').value.trim();
        const syncword = parseInt(syncwordRaw, 16);
        if (syncwordRaw && Number.isNaN(syncword)) {
            status.dataset.kind = 'error';
            status.textContent = 'Sync word must be a valid hex value.';
            return;
        }
        const capcodeRaw = this._root.querySelector('[data-radio-pager-capcode]').value.trim();
        if (capcodeRaw) {
            const capcodeNum = Number(capcodeRaw);
            if (!Number.isInteger(capcodeNum) || capcodeNum < 0 || capcodeNum > 0xFFFFFFFF) {
                status.dataset.kind = 'error';
                status.textContent = 'Capcode must be a whole number from 0 to 4294967295.';
                return;
            }
        }
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/radio/pager', {
            pager_enabled: this._root.querySelector('[data-radio-pager-enabled]').checked,
            pager_capcode: capcodeRaw ? Number(capcodeRaw) : 0,
            pager_frequency_mhz: Number(
                this._root.querySelector('[data-radio-pager-freq]').value,
            ),
            pager_sync_word: syncword,
            pager_sync_word_size: Number(
                this._root.querySelector('[data-radio-pager-syncword-size]').value,
            ),
        });
        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            if (result.restart_required) {
                this._api.signalRestart('Radio pager updated.');
            } else {
                this._api.toast('Radio pager updated.');
            }
            this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }
}

window.RadioPagerConfigCard = RadioPagerConfigCard;
