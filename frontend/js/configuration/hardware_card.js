/**
 * Configuration → Hardware card.
 *
 * SenseCap M1 onboard fan/LED/button -- opt-in, this hardware doesn't
 * exist on RAK V2/Chameleon/DIY builds. Three independent forms (each
 * peripheral saves on its own), same multi-card-in-one-page layout as
 * AdvancedConfigCard.
 */

class HardwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-hw-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Fan</h3>
                        <p class="cfg-card__hint">PWM speed ramps with CPU temperature. Requires a restart; needs gpiozero + lgpio installed (see Troubleshooting).</p>
                    </header>
                    <form class="cfg-form" data-fan-form>
                        <label class="cfg-field cfg-field--toggle">
                            <input type="checkbox" data-fan-enabled>
                            <span class="cfg-field__label">Enabled</span>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">GPIO pin</span>
                            <input class="cfg-field__input" type="number" min="0" max="27" data-fan-pin>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Ramp start (°C)</span>
                            <input class="cfg-field__input" type="number" step="0.5" data-fan-min-temp>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Full speed at (°C)</span>
                            <input class="cfg-field__input" type="number" step="0.5" data-fan-max-temp>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Minimum duty (0-1)</span>
                            <input class="cfg-field__input" type="number" step="0.05" min="0" max="1" data-fan-min-duty>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Hysteresis (°C)</span>
                            <input class="cfg-field__input" type="number" step="0.5" min="0" data-fan-hysteresis>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Poll interval (s)</span>
                            <input class="cfg-field__input" type="number" step="1" min="1" data-fan-poll>
                        </label>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary" type="submit">Save fan</button>
                        </div>
                        <p class="cfg-status" data-fan-status aria-live="polite"></p>
                    </form>
                </article>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Status LED</h3>
                        <p class="cfg-card__hint">Steady = healthy, brief flicker = packet captured, 1&nbsp;Hz blink = a capture source is down.</p>
                    </header>
                    <form class="cfg-form" data-led-form>
                        <label class="cfg-field cfg-field--toggle">
                            <input type="checkbox" data-led-enabled>
                            <span class="cfg-field__label">Enabled</span>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">GPIO pin</span>
                            <input class="cfg-field__input" type="number" min="0" max="27" data-led-pin>
                        </label>
                        <label class="cfg-field cfg-field--toggle">
                            <input type="checkbox" data-led-blink>
                            <span class="cfg-field__label">Flicker on packet activity</span>
                        </label>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary" type="submit">Save LED</button>
                        </div>
                        <p class="cfg-status" data-led-status aria-live="polite"></p>
                    </form>
                </article>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">User Button</h3>
                        <p class="cfg-card__hint">Short press: advert on every TX-capable radio. Long press: restart the service.</p>
                    </header>
                    <form class="cfg-form" data-button-form>
                        <label class="cfg-field cfg-field--toggle">
                            <input type="checkbox" data-button-enabled>
                            <span class="cfg-field__label">Enabled</span>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">GPIO pin</span>
                            <input class="cfg-field__input" type="number" min="0" max="27" data-button-pin>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Hold time for restart (s)</span>
                            <input class="cfg-field__input" type="number" step="0.5" min="0.5" data-button-hold>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">Advert cooldown (s)</span>
                            <input class="cfg-field__input" type="number" step="1" min="0" data-button-cooldown>
                        </label>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary" type="submit">Save button</button>
                        </div>
                        <p class="cfg-status" data-button-status aria-live="polite"></p>
                    </form>
                </article>
            </div>
        `;
        this._root.querySelector('[data-fan-form]')
            .addEventListener('submit', (e) => this._saveFan(e));
        this._root.querySelector('[data-led-form]')
            .addEventListener('submit', (e) => this._saveLed(e));
        this._root.querySelector('[data-button-form]')
            .addEventListener('submit', (e) => this._saveButton(e));
    }

    render(config) {
        const hw = (config && config.hardware) || {};
        const fan = hw.fan || {};
        const led = hw.led || {};
        const button = hw.button || {};

        this._setChecked('[data-fan-enabled]', fan.enabled);
        this._setVal('[data-fan-pin]', fan.gpio_pin);
        this._setVal('[data-fan-min-temp]', fan.min_temp_c);
        this._setVal('[data-fan-max-temp]', fan.max_temp_c);
        this._setVal('[data-fan-min-duty]', fan.min_duty);
        this._setVal('[data-fan-hysteresis]', fan.hysteresis_c);
        this._setVal('[data-fan-poll]', fan.poll_interval_s);

        this._setChecked('[data-led-enabled]', led.enabled);
        this._setVal('[data-led-pin]', led.gpio_pin);
        this._setChecked('[data-led-blink]', led.activity_blink);

        this._setChecked('[data-button-enabled]', button.enabled);
        this._setVal('[data-button-pin]', button.gpio_pin);
        this._setVal('[data-button-hold]', button.hold_time_s);
        this._setVal('[data-button-cooldown]', button.advert_cooldown_s);
    }

    _setVal(sel, v) {
        const el = this._root.querySelector(sel);
        if (el && v != null) el.value = v;
    }

    _setChecked(sel, v) {
        const el = this._root.querySelector(sel);
        if (el) el.checked = Boolean(v);
    }

    async _saveFan(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-fan-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/hardware/fan', {
            enabled: this._root.querySelector('[data-fan-enabled]').checked,
            gpio_pin: Number(this._root.querySelector('[data-fan-pin]').value),
            min_temp_c: Number(this._root.querySelector('[data-fan-min-temp]').value),
            max_temp_c: Number(this._root.querySelector('[data-fan-max-temp]').value),
            min_duty: Number(this._root.querySelector('[data-fan-min-duty]').value),
            hysteresis_c: Number(this._root.querySelector('[data-fan-hysteresis]').value),
            poll_interval_s: Number(this._root.querySelector('[data-fan-poll]').value),
        });
        this._finish(status, result, 'Fan settings updated.');
    }

    async _saveLed(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-led-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/hardware/led', {
            enabled: this._root.querySelector('[data-led-enabled]').checked,
            gpio_pin: Number(this._root.querySelector('[data-led-pin]').value),
            activity_blink: this._root.querySelector('[data-led-blink]').checked,
        });
        this._finish(status, result, 'LED settings updated.');
    }

    async _saveButton(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-button-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/hardware/button', {
            enabled: this._root.querySelector('[data-button-enabled]').checked,
            gpio_pin: Number(this._root.querySelector('[data-button-pin]').value),
            hold_time_s: Number(this._root.querySelector('[data-button-hold]').value),
            advert_cooldown_s: Number(this._root.querySelector('[data-button-cooldown]').value),
        });
        this._finish(status, result, 'Button settings updated.');
    }

    _finish(statusEl, result, restartMsg) {
        if (result) {
            statusEl.dataset.kind = 'success';
            statusEl.textContent = 'Saved.';
            if (result.restart_required) {
                this._api.signalRestart(restartMsg);
            } else {
                this._api.toast(restartMsg);
            }
            this._api.refresh();
        } else {
            statusEl.dataset.kind = 'error';
            statusEl.textContent = 'Save failed.';
        }
    }
}

window.HardwareConfigCard = HardwareConfigCard;
