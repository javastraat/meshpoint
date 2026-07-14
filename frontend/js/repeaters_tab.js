/**
 * Repeaters page — health dashboard for polled MeshCore repeaters.
 *
 * MeshCore nodes advertise identity only, so their stats have to be
 * asked for; the backend polls req_status/req_telemetry periodically
 * (see repeater_poller.py) and this renders the latest: a summary row
 * plus one health card per repeater (battery, uptime, sensors, airtime,
 * packet counters, noise floor). Only mounted when polling is enabled.
 */
class RepeatersTab {
    constructor() {
        this._mounted = false;
        this._timer = null;
    }

    async checkAvailable() {
        try {
            const r = await fetch('/api/meshcore/repeaters');
            if (!r.ok) return false;
            const d = await r.json();
            return !!d.available;
        } catch (_) {
            return false;
        }
    }

    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        // Repeaters are polled every ~20 min, so a slow refresh is
        // plenty -- no point re-fetching the full history every 30s.
        this._timer = setInterval(() => this._load(), 300_000);
    }

    hide() {
        clearInterval(this._timer);
        this._timer = null;
        Object.values(this._charts || {}).forEach((c) => c.destroy());
        this._charts = {};
    }

    _mount() {
        const root = document.getElementById('repeaters-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Repeaters</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="rp-refresh-btn">Refresh</button>
                </div>
            </header>
            <section class="lw-stats" id="rp-summary"></section>
            <div class="rp-grid" id="rp-grid"></div>
            <p class="lw-empty" id="rp-empty" style="display:none">
                No repeater data yet — the first poll runs shortly after start.
            </p>
        `;
        document.getElementById('rp-refresh-btn')
            ?.addEventListener('click', () => this._load());
        // Delegated so it survives the grid's innerHTML re-render on
        // every poll refresh, instead of re-binding per card each time.
        document.getElementById('rp-grid')
            ?.addEventListener('click', (e) => {
                const trigger = e.target.closest('[data-rp-neighbours]');
                if (trigger) this._openNeighbours(trigger.dataset.rpNeighbours);
            });
    }

    _openNeighbours(key) {
        const r = (this._lastReps || []).find((x) => x.key === key);
        if (!r || !window.NeighboursModal) return;
        const nbList = r.neighbours && Array.isArray(r.neighbours.neighbours)
            ? r.neighbours.neighbours
            : [];
        window.NeighboursModal.show(r.mesh_name || r.name || r.key, nbList);
    }

    async _load() {
        try {
            const r = await fetch('/api/meshcore/repeaters');
            if (!r.ok) return;
            const data = await r.json();
            this._render(data.repeaters || []);
        } catch (_) {}
    }

    _render(reps) {
        const grid = document.getElementById('rp-grid');
        const empty = document.getElementById('rp-empty');
        const summary = document.getElementById('rp-summary');
        if (!grid) return;
        this._lastReps = reps;

        const polled = reps.filter((r) => r.status);
        const healthy = reps.filter((r) => r.ok).length;
        if (summary) {
            summary.innerHTML = `
                ${this._statCard('Repeaters', reps.length)}
                ${this._statCard('Reporting', `${healthy} / ${reps.length}`)}
                ${this._statCard('Oldest poll', this._oldest(reps))}
            `;
        }

        if (!polled.length) {
            grid.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        grid.innerHTML = reps.map((r) => this._card(r)).join('');
        // Render the per-repeater trend charts after the DOM is in place.
        reps.forEach((r) => this._renderTrends(r));
    }

    /** Fetch this repeater's telemetry history and draw it with the
     * shared NodeMetricsChart (same component the node drawer uses). */
    async _renderTrends(r) {
        const canvas = document.querySelector(`canvas[data-rp-chart="${r.key}"]`);
        if (!canvas || !window.NodeMetricsChart) return;
        this._charts = this._charts || {};
        if (this._charts[r.key]) this._charts[r.key].destroy();
        try {
            // Wide window to cover the full history -- the backend now
            // buckets/averages into `limit` evenly-sized time windows
            // server-side (see TelemetryRepository.get_history()), so
            // this stays a sane chart-point target instead of the old
            // "raw row cap high enough it never truncates" hack.
            const res = await fetch(
                `/api/nodes/${encodeURIComponent(r.key)}/metrics_history`
                + '?hours=100000&limit=1000',
            );
            if (!res.ok) return;
            const history = await res.json();
            const chart = new window.NodeMetricsChart(canvas);
            const drawn = chart.render(history);
            const wrap = canvas.closest('.rp-card--trends');
            const emptyEl = wrap && wrap.querySelector('.rp-trends-empty');
            if (emptyEl) emptyEl.style.display = drawn ? 'none' : '';
            if (drawn) this._charts[r.key] = chart;
        } catch (_) {}
    }

    _statCard(label, value) {
        return `<div class="stat-card">
            <div class="stat-card__label">${this._esc(label)}</div>
            <div class="stat-card__value">${this._esc(value)}</div>
        </div>`;
    }

    _card(r) {
        const s = r.status || {};
        const stale = !r.ok;

        // Radio / router health from req_status.
        const health = [];
        health.push(['Battery', s.bat != null ? `${(s.bat / 1000).toFixed(2)} V` : '--']);
        health.push(['Uptime', this._uptime(s.uptime)]);
        health.push(['Airtime (tx/rx)', this._airtime(s)]);
        health.push(['Packets recv', this._num(s.nb_recv)]);
        health.push(['Packets sent', this._num(s.nb_sent)]);
        health.push(['Noise floor', s.noise_floor != null ? `${s.noise_floor} dBm` : '--']);
        health.push(['Last SNR', s.last_snr != null ? `${s.last_snr} dB` : '--']);
        if (s.recv_errors != null) health.push(['Recv errors', this._num(s.recv_errors)]);
        const nbData = r.neighbours;
        const nbList = nbData && Array.isArray(nbData.neighbours) ? nbData.neighbours : null;
        const nbCount = nbData
            ? (nbData.neighbours_count != null ? nbData.neighbours_count : (nbList ? nbList.length : null))
            : null;

        // Every LPP sensor reading (any channel / any sensor).
        const sensors = this._sensorRows(r.telemetry);

        // Historical telemetry stats (min/max/avg from imported data + live polls).
        const history = r.history || {};
        const historyRows = this._historyRows(history);

        // Prefer the repeater's real advertised name, then a config
        // label, then the raw key.
        const title = r.mesh_name || r.name || r.key;
        const rowsHtml = (rows) => rows.map(([k, v]) => `
            <div class="rp-row"><span class="rp-row__k">${this._esc(k)}</span>
            <span class="rp-row__v">${this._esc(v)}</span></div>
        `).join('');
        const sensorChannels = new Set(
            sensors
                .map(([k]) => {
                    const m = String(k).match(/^Ch\d+/);
                    return m ? m[0] : null;
                })
                .filter(Boolean)
        ).size;
        const sensorMeta = sensors.length
            ? `${sensorChannels} ch · ${sensors.length} vals`
            : 'No data';
        const sensorRows = sensors.length
            ? rowsHtml(sensors)
            : '<div class="rp-row"><span class="rp-row__k">No sensor telemetry</span><span class="rp-row__v">--</span></div>';

        const historyMeta = history.total_samples
            ? `${history.total_samples} samples`
            : 'No data';
        const historyRowsHtml = historyRows.length
            ? rowsHtml(historyRows)
            : '<div class="rp-row"><span class="rp-row__k">No history</span><span class="rp-row__v">--</span></div>';

        const neighboursRowHtml = nbCount != null
            ? `<div class="rp-row rp-row--clickable" data-rp-neighbours="${this._esc(r.key)}">
                 <span class="rp-row__k">Neighbours</span>
                 <span class="rp-row__v rp-row__v--link">${this._num(nbCount)}</span>
               </div>`
            : '';

        // Farthest node THIS repeater has reported (distance measured
        // from the repeater's own position, not Meshpoint's -- a
        // repeater can be a remote site with its own local RF picture).
        const fn = r.farthest_neighbour;
        const farthestRowHtml = fn
            ? (() => {
                const km = fn.miles * 1.60934;
                const dist = window.MeshpointDisplayUnits
                    ? window.MeshpointDisplayUnits.formatDistanceKm(km)
                    : `${km.toFixed(1)} km`;
                const detail = [fn.snr != null ? `SNR ${fn.snr} dB` : null, fn.node_name]
                    .filter(Boolean).join(' · ');
                return `<div class="rp-row">
                     <span class="rp-row__k">Farthest neighbour</span>
                     <span class="rp-row__v">${this._esc(dist)} · ${this._esc(detail)}</span>
                   </div>`;
            })()
            : '';

        return `
            <div class="rp-repeater">
                <div class="rp-card ${stale ? 'rp-card--stale' : ''}">
                    <div class="rp-card__head">
                        <span class="rp-card__name">${this._esc(title)}</span>
                        <span class="rp-card__lamp ${r.ok ? 'rp-ok' : 'rp-stale'}"
                              title="${r.ok ? 'Reporting' : this._esc(r.error || 'stale')}"></span>
                    </div>
                    <div class="rp-card__id">!${this._esc(r.key)}</div>
                    <div class="rp-card__rows">${rowsHtml(health)}${neighboursRowHtml}${farthestRowHtml}</div>
                </div>
                <div class="rp-card rp-card--sensors ${stale ? 'rp-card--stale' : ''}">
                    <div class="rp-card__head">
                        <span class="rp-card__name">Sensors</span>
                        <span class="rp-card__meta">${this._esc(sensorMeta)}</span>
                    </div>
                    <div class="rp-card__rows">${sensorRows}</div>
                </div>
                <div class="rp-card rp-card--history ${stale ? 'rp-card--stale' : ''}">
                    <div class="rp-card__head">
                        <span class="rp-card__name">History</span>
                        <span class="rp-card__meta">${this._esc(historyMeta)}</span>
                    </div>
                    <div class="rp-card__rows">${historyRowsHtml}</div>
                </div>
                <div class="rp-card rp-card--trends">
                    <div class="rp-card__head">
                        <span class="rp-card__name">Trends</span>
                        <span class="rp-card__meta">tap legend to toggle</span>
                    </div>
                    <div class="rp-trends-wrap">
                        <canvas data-rp-chart="${this._esc(r.key)}"></canvas>
                    </div>
                    <div class="rp-trends-empty" style="display:none">
                        No telemetry history yet.
                    </div>
                </div>
            </div>
        `;
    }

    _historyRows(h) {
        const rows = [];
        if (h.min_ts && h.max_ts) {
            rows.push(['Period', `${this._shortDate(h.min_ts)} to ${this._shortDate(h.max_ts)}`]);
        }
        if (h.voltage && (h.voltage.min != null || h.voltage.max != null)) {
            const v = h.voltage;
            rows.push(['Voltage (min/avg/max)', 
                `${this._fmt(v.min, 2)} / ${this._fmt(v.avg, 2)} / ${this._fmt(v.max, 2)} V`]);
        }
        if (h.temperature && (h.temperature.min != null || h.temperature.max != null)) {
            const t = h.temperature;
            rows.push(['Temperature (min/avg/max)', 
                `${this._fmt(t.min, 1)} / ${this._fmt(t.avg, 1)} / ${this._fmt(t.max, 1)} °C`]);
        }
        if (h.humidity && (h.humidity.min != null || h.humidity.max != null)) {
            const hm = h.humidity;
            rows.push(['Humidity (min/avg/max)', 
                `${this._fmt(hm.min, 1)} / ${this._fmt(hm.avg, 1)} / ${this._fmt(hm.max, 1)} %`]);
        }
        return rows;
    }

    static UNITS = {
        voltage: 'V', temperature: '°C', barometer: 'hPa', altitude: 'm',
        current: 'A', power: 'W', humidity: '%', relative_humidity: '%',
    };

    static TYPE_LABELS = { barometer: 'pressure' };

    /** One row per LPP reading, in channel order. Labels are
     * ``Ch{n} {type}`` -- universal, no per-repeater sensor assumptions;
     * the channel disambiguates the multiple temperature sensors. */
    _sensorRows(t) {
        const lpp = t && Array.isArray(t.lpp) ? t.lpp : [];
        const rows = lpp
            .slice()
            .sort((a, b) => (a.channel - b.channel)
                || String(a.type).localeCompare(String(b.type)))
            .map((rd) => {
                const type = RepeatersTab.TYPE_LABELS[rd.type] || rd.type;
                const unit = RepeatersTab.UNITS[rd.type] || '';
                // Up to 2 decimals, trailing zeros trimmed (4.11, 37.7, 0, 52).
                const num = parseFloat(Number(rd.value).toFixed(2));
                return {
                    channel: rd.channel,
                    label: `Ch${rd.channel} ${type}`,
                    value: `${num}${unit ? ' ' + unit : ''}`,
                    isZero: Number.isFinite(num) && num === 0,
                };
            });

        const channelHasNonZero = new Map();
        for (const row of rows) {
            const current = channelHasNonZero.get(row.channel) || false;
            channelHasNonZero.set(row.channel, current || !row.isZero);
        }

        return rows
            .filter((row) => channelHasNonZero.get(row.channel))
            .map((row) => [row.label, row.value]);
    }

    _airtime(s) {
        const fmt = (v) => (v != null ? `${Math.round(v / 60)}m` : '--');
        return `${fmt(s.airtime)} / ${fmt(s.rx_airtime)}`;
    }

    _uptime(secs) {
        if (secs == null) return '--';
        const d = Math.floor(secs / 86400);
        const h = Math.floor((secs % 86400) / 3600);
        if (d > 0) return `${d}d ${h}h`;
        const m = Math.floor((secs % 3600) / 60);
        return `${h}h ${m}m`;
    }

    _num(n) {
        return n != null ? Number(n).toLocaleString() : '--';
    }

    _oldest(reps) {
        const times = reps.map((r) => r.updated_at).filter(Boolean).sort();
        return times.length ? this._ago(times[0]) : '--';
    }

    _ago(iso) {
        if (!iso) return 'never';
        const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
        if (secs < 90) return 'just now';
        if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
        if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
        return `${Math.floor(secs / 86400)}d ago`;
    }

    _esc(s) {
        const el = document.createElement('span');
        el.textContent = s == null ? '' : String(s);
        return el.innerHTML;
    }

    _fmt(n, decimals = 2) {
        if (n == null) return '--';
        return Number(n).toFixed(decimals);
    }

    _shortDate(iso) {
        if (!iso) return '--';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch (_) {
            return '--';
        }
    }
}

window.RepeatersTab = RepeatersTab;
