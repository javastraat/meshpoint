/**
 * Configuration → Repeater Poll card.
 *
 * Single responsibility: edit the `repeater_poll` roster (enable/
 * interval + which repeaters to poll) so adding/removing a repeater
 * doesn't need hand-editing local.yaml. Mirrors SerialConfigCard's
 * add/remove-row shape, plus a per-row password field that follows the
 * MQTT broker password's dirty-tracking convention -- the API never
 * sends the real password back (only `password_set`), so leaving the
 * field blank on save means "keep the current password."
 */

class RepeaterPollConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    _MAX_REPEATERS = 8;

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-repeater-poll-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Repeater polling</h3>
                        <p class="cfg-card__hint">
                            Actively queries MeshCore repeaters you operate for status,
                            telemetry, and neighbours (Radio → Repeaters page).
                            Requires a service restart after changes.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-rp-enable>
                        <span class="cfg-field__label">Enable repeater polling</span>
                    </label>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Poll interval (minutes)</span>
                        <input class="cfg-field__input" type="number" min="5" max="1440"
                               data-rp-interval>
                    </label>
                    <div class="cfg-companions" data-rp-repeaters></div>
                    <div class="cfg-companions__add-row">
                        <button class="terminal-button" type="button" data-rp-add>
                            + Add repeater
                        </button>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-rp-save>
                            Save repeater polling
                        </button>
                    </div>
                    <p class="cfg-status" data-rp-status aria-live="polite"></p>
                </article>
            </div>
        `;
        this._listEl = this._root.querySelector('[data-rp-repeaters]');

        this._root.querySelector('[data-rp-add]')
            .addEventListener('click', () => this._addRow());
        this._root.querySelector('[data-rp-save]')
            .addEventListener('click', () => this._save());
    }

    render(config) {
        const rp = config.repeater_poll || {};
        const repeaters = Array.isArray(rp.repeaters) ? rp.repeaters : [];

        const enableEl = this._root.querySelector('[data-rp-enable]');
        if (enableEl) enableEl.checked = !!rp.enabled;
        const intervalEl = this._root.querySelector('[data-rp-interval]');
        if (intervalEl) intervalEl.value = rp.interval_minutes != null ? rp.interval_minutes : 30;

        this._listEl.innerHTML = '';
        const list = repeaters.length > 0 ? repeaters : [{ key: '', name: '', password_set: false }];
        list.forEach((r) => this._addRow(r));
        this._syncAddBtn();
    }

    _addRow(data = {}) {
        const idx = this._listEl.children.length;
        if (idx >= this._MAX_REPEATERS) return;

        const key = this._esc(data.key || '');
        const name = this._esc(data.name || '');
        const passwordSet = !!data.password_set;

        const div = document.createElement('div');
        div.className = 'cfg-companion';
        div.dataset.repeaterIdx = idx;
        div.dataset.passwordDirty = 'false';
        div.innerHTML = `
            <div class="cfg-companion__header">
                <span class="cfg-companion__num">Repeater ${idx + 1}</span>
                <label class="cfg-companion__label-wrap">
                    <span class="cfg-field__label">Name</span>
                    <input class="cfg-field__input cfg-companion__label-input"
                           type="text" maxlength="32"
                           placeholder="e.g. NL-AMS-R-PD2EMC"
                           value="${name}" data-rp-name>
                </label>
                <button class="cfg-companion__remove terminal-button terminal-button--danger"
                        type="button" title="Remove repeater">✕</button>
            </div>
            <label class="cfg-field">
                <span class="cfg-field__label">Public key prefix</span>
                <input class="cfg-field__input" type="text" maxlength="32"
                       placeholder="12 hex chars, e.g. da0b77f13bc7" value="${key}"
                       data-rp-key>
            </label>
            <label class="cfg-field">
                <span class="cfg-field__label">Login password</span>
                <input class="cfg-field__input" type="password" data-rp-password
                       autocomplete="new-password">
            </label>
        `;

        const passwordEl = div.querySelector('[data-rp-password]');
        passwordEl.placeholder = passwordSet
            ? 'Leave blank to keep current password'
            : 'Repeater login password';
        passwordEl.addEventListener('input', () => {
            div.dataset.passwordDirty = 'true';
        });

        div.querySelector('.cfg-companion__remove').addEventListener('click', () => {
            div.remove();
            this._reindexRows();
            this._syncAddBtn();
        });

        this._listEl.appendChild(div);
        this._syncAddBtn();
    }

    _reindexRows() {
        this._listEl.querySelectorAll('.cfg-companion').forEach((el, i) => {
            el.dataset.repeaterIdx = i;
            const num = el.querySelector('.cfg-companion__num');
            if (num) num.textContent = `Repeater ${i + 1}`;
        });
    }

    _syncAddBtn() {
        const btn = this._root.querySelector('[data-rp-add]');
        if (!btn) return;
        const count = this._listEl.children.length;
        btn.disabled = count >= this._MAX_REPEATERS;
        btn.title = count >= this._MAX_REPEATERS
            ? `Maximum ${this._MAX_REPEATERS} repeaters`
            : '';
    }

    async _save() {
        const status = this._root.querySelector('[data-rp-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const repeaters = [];
        this._listEl.querySelectorAll('.cfg-companion').forEach((div) => {
            const key = (div.querySelector('[data-rp-key]')?.value || '').trim();
            if (!key) return;
            const dirty = div.dataset.passwordDirty === 'true';
            repeaters.push({
                key,
                name: (div.querySelector('[data-rp-name]')?.value || '').trim(),
                password: dirty ? (div.querySelector('[data-rp-password]')?.value || '') : null,
                password_unchanged: !dirty,
            });
        });

        const result = await this._api.put('/api/config/repeater-poll', {
            enabled: this._root.querySelector('[data-rp-enable]').checked,
            interval_minutes: Number(this._root.querySelector('[data-rp-interval]').value) || 30,
            repeaters,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            this._api.signalRestart('Repeater polling updated.');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.RepeaterPollConfigCard = RepeaterPollConfigCard;
