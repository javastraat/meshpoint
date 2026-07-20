/**
 * ADS-B (air traffic) tab -- Start/Stop dump1090 and show the live
 * aircraft table. Unlike PagerPanel's append-only decoded message log
 * (P2000/Pagers/POCSAG/RTL433, each a stream of discrete events),
 * dump1090 hands back a full snapshot of currently-tracked aircraft on
 * every poll of its own `/data.json` (see src/audio/adsb_listener.py),
 * so this renders as a table keyed by ICAO hex that updates in place --
 * the same shape every other ADS-B web UI (dump1090's own bundled
 * gmap.html, tar1090, etc) uses.
 *
 * Reuses the same panel/status-header markup and CSS classes as
 * PagerPanel (`.pager-status`, `.pager-actions`, `.pager-count`) for a
 * consistent look with the RTL433 tab right before it in the tabbar,
 * plus dedicated `.adsb-*` table styles.
 *
 * Only one of Radio/P2000/Pagers/POCSAG/RTL433/DAB+/ADS-B can hold the
 * RTL-SDR dongle at a time -- see src/audio/sdr_registry.py.
 */

class AdsbPanel {
    constructor() {
        this._apiPrefix = '/api/adsb';
        this._root = null;
        this._statusTimer = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">ADS-B</div>
                    <div class="panel__body pager-controls">
                        <div class="pager-status" data-adsb-status>
                            <span class="pager-status__dot" data-adsb-dot></span>
                            <span data-adsb-status-text>idle</span>
                        </div>
                        <div class="pager-actions">
                            <label class="adsb-metric-toggle">
                                <input type="checkbox" data-adsb-metric checked>
                                Metric units
                            </label>
                            <button class="terminal-button" type="button" data-adsb-start>Start listening</button>
                            <button class="terminal-button" type="button" data-adsb-stop>Stop</button>
                        </div>
                    </div>
                </div>
            </section>
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">Aircraft <span class="pager-count" data-adsb-count></span></div>
                    <div class="panel__body">
                        <div class="adsb-table-wrap">
                            <table class="adsb-table">
                                <thead>
                                    <tr>
                                        <th>ICAO</th>
                                        <th>Flight</th>
                                        <th>Squawk</th>
                                        <th>Altitude</th>
                                        <th>Speed</th>
                                        <th>Track</th>
                                        <th>Position</th>
                                        <th>Msgs</th>
                                        <th>Seen</th>
                                    </tr>
                                </thead>
                                <tbody data-adsb-body>
                                    <tr class="adsb-table__empty"><td colspan="9">No aircraft yet.</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </section>
        `;
        this._root.querySelector('[data-adsb-start]').addEventListener('click', () => this._start());
        this._root.querySelector('[data-adsb-stop]').addEventListener('click', () => this._stop());
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
        const btn = this._root.querySelector('[data-adsb-start]');
        const metric = this._root.querySelector('[data-adsb-metric]').checked;
        btn.disabled = true;
        try {
            const res = await fetch(`${this._apiPrefix}/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ metric }),
            });
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
        const dot = this._root.querySelector('[data-adsb-dot]');
        const text = this._root.querySelector('[data-adsb-status-text]');
        const startBtn = this._root.querySelector('[data-adsb-start]');
        // Only the RTL-SDR dongle's ACTUAL owner can be "busy" from this
        // tab's point of view -- if dongle_owner === 'adsb', that's just
        // us running, not something else in the way.
        const busyOwner = (status.dongle_owner && status.dongle_owner !== 'adsb')
            ? status.dongle_owner : null;

        if (dot) {
            dot.classList.toggle('pager-status__dot--on', !!status.running);
            dot.classList.toggle('pager-status__dot--busy', !!busyOwner);
        }
        if (text) {
            if (status.running) {
                text.textContent = 'tracking 1090 MHz';
            } else if (busyOwner) {
                const labels = { p2000: 'P2000', pagers: 'Pagers', pocsag: 'POCSAG', rtl433: 'RTL433', dab: 'DAB+', radio: 'Radio' };
                text.textContent = `busy -- in use by ${labels[busyOwner] || busyOwner}`;
            } else if (status.last_error) {
                text.textContent = `stopped -- ${status.last_error}`;
            } else {
                text.textContent = 'idle';
            }
        }
        if (startBtn) startBtn.disabled = !!busyOwner;
        const metricCb = this._root.querySelector('[data-adsb-metric]');
        if (metricCb) {
            // Only meaningful before Start -- dump1090's units are fixed
            // for the life of the process, so don't let the checkbox
            // imply toggling it live would do anything.
            metricCb.disabled = !!status.running || !!busyOwner;
            if (status.running) metricCb.checked = !!status.metric;
        }

        const countEl = this._root.querySelector('[data-adsb-count]');
        if (countEl) countEl.textContent = status.aircraft_count ? `(${status.aircraft_count})` : '';

        const body = this._root.querySelector('[data-adsb-body]');
        if (!body) return;
        const aircraft = status.aircraft || [];
        if (aircraft.length === 0) {
            body.innerHTML = '<tr class="adsb-table__empty"><td colspan="9">No aircraft yet.</td></tr>';
            return;
        }
        body.innerHTML = aircraft.map((a) => this._rowHtml(a, !!status.metric)).join('');
    }

    _rowHtml(a, metric) {
        const pos = (a.lat != null && a.lon != null)
            ? `${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}` : '';
        const alt = a.altitude != null ? `${a.altitude} ${metric ? 'm' : 'ft'}` : '';
        const speed = a.speed != null ? `${a.speed} ${metric ? 'km/h' : 'kt'}` : '';
        const track = a.track != null ? `${a.track}°` : '';
        return `
            <tr>
                <td class="adsb-table__hex">${this._esc(a.hex || '')}</td>
                <td>${this._esc(a.flight || '')}</td>
                <td>${this._esc(a.squawk || '')}</td>
                <td>${this._esc(alt)}</td>
                <td>${this._esc(speed)}</td>
                <td>${this._esc(track)}</td>
                <td>${this._esc(pos)}</td>
                <td>${this._esc(a.messages != null ? a.messages : '')}</td>
                <td>${this._esc(a.seen != null ? `${a.seen}s` : '')}</td>
            </tr>
        `;
    }

    _showError(msg) {
        const text = this._root.querySelector('[data-adsb-status-text]');
        if (text) text.textContent = msg;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.AdsbPanel = AdsbPanel;
