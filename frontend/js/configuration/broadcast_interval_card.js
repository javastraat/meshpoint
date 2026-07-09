/**
 * Shared broadcast interval editor for Configuration panels.
 *
 * Preset chips, numeric input (0 or 5-1440 min), and Save with hot-reload.
 */

class BroadcastIntervalCard {
    constructor(api, options) {
        this._api = api;
        this._title = options.title;
        this._hint = options.hint || '';
        this._saveLabel = options.saveLabel || 'Save interval';
        this._putUrl = options.putUrl;
        this._configKey = options.configKey;
        this._cardId = options.cardId || `cfg-${options.configKey}-interval`;
        this._presets = options.presets || BroadcastIntervalCard.DEFAULT_PRESETS;
        this._root = null;
        this._saved = { interval_minutes: 0 };
        this._draft = { interval_minutes: 0 };
    }

    static DEFAULT_PRESETS = [
        { minutes: 0, label: 'Off', off: true },
        { minutes: 5, label: '5m' },
        { minutes: 15, label: '15m' },
        { minutes: 30, label: '30m' },
        { minutes: 60, label: '1h' },
        { minutes: 180, label: '3h' },
        { minutes: 360, label: '6h' },
        { minutes: 720, label: '12h' },
        { minutes: 1440, label: '24h' },
    ];

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <article class="cfg-card" id="${this._esc(this._cardId)}">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">${this._esc(this._title)}</h3>
                    <p class="cfg-card__hint">${this._esc(this._hint)}</p>
                </header>
                <form class="cfg-form" data-bi-form>
                    <div class="cfg-field">
                        <span class="cfg-field__label">Preset</span>
                        <div class="cfg-chip-row" data-bi-chips></div>
                    </div>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Custom (minutes)</span>
                        <input class="cfg-field__input" type="number"
                               min="0" max="1440" step="1" data-bi-input>
                    </label>
                    <p class="cfg-card__hint">
                        Use 0 to pause, or 5-1440 for an active cadence.
                        Saved intervals take effect immediately without a restart.
                    </p>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="submit" data-bi-save>${this._esc(this._saveLabel)}</button>
                    </div>
                    <p class="cfg-status" data-bi-status aria-live="polite"></p>
                </form>
            </article>
        `;
        this._chipsEl = this._root.querySelector('[data-bi-chips]');
        this._inputEl = this._root.querySelector('[data-bi-input]');
        this._saveBtn = this._root.querySelector('[data-bi-save]');
        this._statusEl = this._root.querySelector('[data-bi-status]');
        this._form = this._root.querySelector('[data-bi-form]');
        this._renderChips();
        this._wire();
    }

    render(config) {
        const block = (config && config[this._configKey]) || {};
        this._saved.interval_minutes = block.interval_minutes || 0;
        this._draft.interval_minutes = this._saved.interval_minutes;
        this._inputEl.value = String(this._draft.interval_minutes);
        this._setActiveChip(this._draft.interval_minutes);
        this._renderPendingCue();
        this._setStatus('', '');
    }

    _renderChips() {
        this._chipsEl.innerHTML = this._presets.map((p) => {
            const offCls = p.off ? ' cfg-chip--off' : '';
            return `<button type="button" class="cfg-chip${offCls}"
                    data-minutes="${p.minutes}">${this._esc(p.label)}</button>`;
        }).join('');
        this._chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
            chip.addEventListener('click', (e) => {
                e.preventDefault();
                const minutes = parseInt(chip.dataset.minutes, 10);
                this._inputEl.value = String(minutes);
                this._draft.interval_minutes = minutes;
                this._setActiveChip(minutes);
                this._renderPendingCue();
            });
        });
    }

    _wire() {
        this._form.addEventListener('submit', (e) => this._onSubmit(e));
        this._inputEl.addEventListener('input', () => {
            const minutes = parseInt(this._inputEl.value, 10);
            if (isNaN(minutes)) return;
            this._setActiveChip(minutes);
            if (minutes === 0 || (minutes >= 5 && minutes <= 1440)) {
                this._draft.interval_minutes = minutes;
            }
            this._renderPendingCue();
        });
    }

    async _onSubmit(event) {
        event.preventDefault();
        const minutes = this._draft.interval_minutes;
        if (isNaN(minutes) || (minutes !== 0 && (minutes < 5 || minutes > 1440))) {
            this._setStatus('error', 'Interval must be 0 or 5-1440 minutes.');
            return;
        }
        this._setStatus('pending', 'Saving…');
        const result = await this._api.put(this._putUrl, {
            interval_minutes: minutes,
        });
        if (!result) {
            this._setStatus('error', 'Save failed.');
            return;
        }
        const paused = minutes === 0;
        this._setStatus('success', paused ? 'Broadcasts paused.' : 'Interval saved.');
        this._api.toast(paused ? `${this._title} paused` : `${this._title} saved`);
        await this._api.refresh();
    }

    _setActiveChip(minutes) {
        this._chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
            const m = parseInt(chip.dataset.minutes, 10);
            chip.classList.toggle('cfg-chip--selected', m === minutes);
        });
    }

    _isPending() {
        return this._draft.interval_minutes !== this._saved.interval_minutes;
    }

    _renderPendingCue() {
        if (this._saveBtn) {
            this._saveBtn.classList.toggle('cfg-btn--has-pending', this._isPending());
        }
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind || '';
        this._statusEl.textContent = message;
    }

    _esc(str) {
        return this._api.escape ? this._api.escape(String(str)) : String(str);
    }
}

window.BroadcastIntervalCard = BroadcastIntervalCard;
