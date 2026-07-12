/**
 * P2000/Pagers tab content -- a live-scrolling decoded message log with
 * Start/Stop controls. Reused for both kinds (parameterized) since the
 * pipeline/UI shape is identical, just a different backend endpoint
 * prefix and page title -- see src/audio/pager_listener.py.
 *
 * Only one of Radio/P2000/Pagers can hold the RTL-SDR dongle at a time
 * (manual-stop-required design, 2026-07-12): starting this while
 * another is active returns an error from the backend, shown inline
 * rather than silently stopping the other one.
 */
class PagerPanel {
    constructor(apiPrefix, title) {
        this._apiPrefix = apiPrefix;  // '/api/p2000' or '/api/pagers'
        this._title = title;
        this._root = null;
        this._statusTimer = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">${this._esc(this._title)}</div>
                    <div class="panel__body pager-controls">
                        <div class="pager-status" data-pager-status>
                            <span class="pager-status__dot" data-pager-dot></span>
                            <span data-pager-status-text>idle</span>
                        </div>
                        <div class="pager-actions">
                            <button class="terminal-button" type="button" data-pager-start>Start listening</button>
                            <button class="terminal-button" type="button" data-pager-stop>Stop</button>
                        </div>
                    </div>
                </div>
            </section>
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">Messages <span class="pager-count" data-pager-count></span></div>
                    <div class="panel__body">
                        <div class="pager-log" data-pager-log>
                            <div class="pager-log__empty">No messages yet.</div>
                        </div>
                    </div>
                </div>
            </section>
        `;
        this._root.querySelector('[data-pager-start]').addEventListener('click', () => this._start());
        this._root.querySelector('[data-pager-stop]').addEventListener('click', () => this._stop());
    }

    show() {
        this._refresh();
        this._statusTimer = setInterval(() => this._refresh(), 2000);
    }

    hide() {
        clearInterval(this._statusTimer);
        this._statusTimer = null;
    }

    async _start() {
        const btn = this._root.querySelector('[data-pager-start]');
        btn.disabled = true;
        try {
            const res = await fetch(`${this._apiPrefix}/start`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this._showError(err.detail || `HTTP ${res.status}`);
            }
        } catch (e) {
            this._showError(e.message);
        } finally {
            btn.disabled = false;
            this._refresh();
        }
    }

    async _stop() {
        try {
            await fetch(`${this._apiPrefix}/stop`, { method: 'POST' });
        } catch (_e) { /* ignore -- status poll will reflect reality */ }
        this._refresh();
    }

    async _refresh() {
        try {
            const res = await fetch(`${this._apiPrefix}/status`);
            if (!res.ok) return;
            const status = await res.json();
            this._render(status);
        } catch (_e) { /* transient network hiccup -- next poll retries */ }
    }

    _render(status) {
        const dot = this._root.querySelector('[data-pager-dot]');
        const text = this._root.querySelector('[data-pager-status-text]');
        if (dot) dot.classList.toggle('pager-status__dot--on', !!status.running);
        if (text) {
            text.textContent = status.running
                ? `listening on ${status.frequency_mhz} MHz`
                : (status.last_error ? `stopped -- ${status.last_error}` : 'idle');
        }
        const countEl = this._root.querySelector('[data-pager-count]');
        if (countEl) countEl.textContent = status.message_count ? `(${status.message_count})` : '';

        const log = this._root.querySelector('[data-pager-log]');
        if (!log) return;
        const messages = status.messages || [];
        if (messages.length === 0) {
            log.innerHTML = '<div class="pager-log__empty">No messages yet.</div>';
            return;
        }
        // Newest first for a live feed.
        log.innerHTML = messages.slice().reverse().map((m) => this._rowHtml(m)).join('');
    }

    _rowHtml(m) {
        const time = m.received_at
            ? new Date(m.received_at * 1000).toLocaleTimeString([], {
                hour: '2-digit', minute: '2-digit', second: '2-digit',
            })
            : '';
        return `
            <div class="pager-row">
                <span class="pager-row__time">${this._esc(time)}</span>
                <span class="pager-row__proto">${this._esc(m.protocol || '')}</span>
                <span class="pager-row__capcode">${this._esc(m.capcode || '')}</span>
                <span class="pager-row__msg">${this._esc(m.message || m.raw || '')}</span>
            </div>
        `;
    }

    _showError(msg) {
        const text = this._root.querySelector('[data-pager-status-text]');
        if (text) text.textContent = msg;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.PagerPanel = PagerPanel;
