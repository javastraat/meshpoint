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
        this._timer = setInterval(() => this._load(), 30_000);
    }

    hide() {
        clearInterval(this._timer);
        this._timer = null;
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

        // Every LPP sensor reading (any channel / any sensor).
        const sensors = this._sensorRows(r.telemetry);

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

        return `
            <div class="rp-repeater">
                <div class="rp-card ${stale ? 'rp-card--stale' : ''}">
                    <div class="rp-card__head">
                        <span class="rp-card__name">${this._esc(title)}</span>
                        <span class="rp-card__lamp ${r.ok ? 'rp-ok' : 'rp-stale'}"
                              title="${r.ok ? 'Reporting' : this._esc(r.error || 'stale')}"></span>
                    </div>
                    <div class="rp-card__id">!${this._esc(r.key)}</div>
                    <div class="rp-card__rows">${rowsHtml(health)}</div>
                    <div class="rp-card__foot">${stale ? 'stale · ' : ''}polled ${this._ago(r.updated_at)}</div>
                </div>
                <div class="rp-card rp-card--sensors ${stale ? 'rp-card--stale' : ''}">
                    <div class="rp-card__head">
                        <span class="rp-card__name">Sensors</span>
                        <span class="rp-card__meta">${this._esc(sensorMeta)}</span>
                    </div>
                    <div class="rp-card__rows">${sensorRows}</div>
                </div>
            </div>
        `;
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
}

window.RepeatersTab = RepeatersTab;
