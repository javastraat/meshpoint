/**
 * Lightweight broadcast status strip (countdown + lamp).
 *
 * Observational only: interval edits happen on the Configuration cards.
 */

class BroadcastStatusCard {
    constructor(api, options) {
        this._api = api;
        this._title = options.title;
        this._configKey = options.configKey;
        this._editRoute = options.editRoute || '#/configuration/radio';
        this._scrollTarget = options.scrollTarget || '';
        this._root = null;
        this._timer = null;
        this._zeroSince = null;
        this._saved = {
            interval_minutes: 0,
            running: false,
            last_sent_at: null,
            next_due_at: null,
        };
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        const scrollAttr = this._scrollTarget
            ? ` data-cfg-scroll-target="${this._esc(this._scrollTarget)}"`
            : '';
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">${this._esc(this._title)}</h3>
                <span class="status-lamp" data-bi-lamp>
                    <span class="status-lamp__dot"></span>
                    <span class="status-lamp__label">--</span>
                </span>
            </div>
            <div class="r-countdown">
                <div class="r-countdown__label">Next broadcast in</div>
                <div class="r-countdown__value" data-bi-countdown>--</div>
                <div class="r-countdown__sub">
                    <span class="r-countdown__sub-item" data-bi-last>
                        Last sent <span>--</span>
                    </span>
                    <span class="r-countdown__sub-sep">|</span>
                    <span class="r-countdown__sub-item">
                        Interval <span data-bi-interval-label>--</span>
                    </span>
                </div>
            </div>
            <a class="r-config-link" href="${this._esc(this._editRoute)}"${scrollAttr}>
                <span>Edit broadcast interval</span>
                <span aria-hidden="true">→</span>
            </a>
        `;
        const editLink = this._root.querySelector('[data-cfg-scroll-target]');
        if (editLink) {
            editLink.addEventListener('click', () => {
                const id = editLink.getAttribute('data-cfg-scroll-target');
                if (id) sessionStorage.setItem('cfg-scroll-target', id);
            });
        }
    }

    render(config) {
        const block = config[this._configKey] || {};
        this._saved.interval_minutes = block.interval_minutes || 0;
        this._saved.running = !!block.running;
        this._saved.last_sent_at = _biParseTimestamp(block.last_sent_at);
        this._saved.next_due_at = _biParseTimestamp(block.next_due_at);
        this._zeroSince = null;
        this._renderIntervalLabel();
        this._renderLamp();
        this._tick();
        this._startTimer();
    }

    destroy() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    _renderIntervalLabel() {
        const el = this._root.querySelector('[data-bi-interval-label]');
        const minutes = this._saved.interval_minutes;
        el.textContent = minutes === 0 ? 'paused' : _biFormatDuration(minutes * 60);
    }

    _renderLamp() {
        const lamp = this._root.querySelector('[data-bi-lamp]');
        const label = lamp.querySelector('.status-lamp__label');
        lamp.classList.remove(
            'status-lamp--ready',
            'status-lamp--warn',
            'status-lamp--off',
        );
        if (this._saved.interval_minutes === 0) {
            lamp.classList.add('status-lamp--off');
            label.textContent = 'PAUSED';
        } else if (this._saved.running) {
            lamp.classList.add('status-lamp--ready');
            label.textContent = 'ACTIVE';
        } else {
            lamp.classList.add('status-lamp--warn');
            label.textContent = 'IDLE';
        }
    }

    _startTimer() {
        if (this._timer) clearInterval(this._timer);
        this._timer = setInterval(() => this._tick(), 1000);
    }

    _tick() {
        const valueEl = this._root.querySelector('[data-bi-countdown]');
        const lastEl = this._root.querySelector('[data-bi-last] span');

        if (this._saved.interval_minutes === 0) {
            valueEl.textContent = 'PAUSED';
            valueEl.style.opacity = '0.45';
            lastEl.textContent = this._saved.last_sent_at
                ? _biFormatAgo(_biSecondsAgo(this._saved.last_sent_at))
                : 'never';
            return;
        }

        valueEl.style.opacity = '1';
        const next = this._saved.next_due_at;
        if (!next) {
            valueEl.textContent = 'awaiting first send';
        } else {
            const remaining = Math.max(
                0, Math.floor((next.getTime() - Date.now()) / 1000),
            );
            valueEl.textContent = remaining === 0
                ? 'broadcasting...'
                : _biFormatCountdown(remaining);
            if (remaining === 0) {
                this._scheduleRefresh();
            }
        }

        lastEl.textContent = this._saved.last_sent_at
            ? _biFormatAgo(_biSecondsAgo(this._saved.last_sent_at))
            : 'never';
    }

    _scheduleRefresh() {
        if (this._zeroSince !== null) return;
        this._zeroSince = Date.now();
        const refreshOnce = async () => {
            try {
                await this._api.refresh();
            } catch (_e) { /* swallow */ }
        };
        setTimeout(refreshOnce, 2500);
        setTimeout(() => {
            if (this._zeroSince !== null) refreshOnce();
        }, 5000);
    }

    _esc(str) {
        return this._api.escape ? this._api.escape(String(str)) : String(str);
    }
}

function _biParseTimestamp(value) {
    if (!value) return null;
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
}

function _biSecondsAgo(date) {
    return Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
}

function _biFormatCountdown(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
        return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
    }
    if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
    return `${s}s`;
}

function _biFormatAgo(seconds) {
    if (seconds < 60) return `${seconds} sec ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m > 0 ? `${h} hr ${m} min ago` : `${h} hr ago`;
}

function _biFormatDuration(seconds) {
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    const h = seconds / 3600;
    return Number.isInteger(h) ? `${h} hr` : `${h.toFixed(1)} hr`;
}

window.BroadcastStatusCard = BroadcastStatusCard;
