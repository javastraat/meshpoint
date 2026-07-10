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
        const rows = [];
        const bat = s.bat != null ? `${(s.bat / 1000).toFixed(2)} V` : '--';
        rows.push(['Battery', bat]);
        rows.push(['Uptime', this._uptime(s.uptime)]);
        const temp = this._lppTemp(r.telemetry);
        if (temp != null) rows.push(['Temperature', `${temp.toFixed(1)} °C`]);
        const hum = this._lpp(r.telemetry, 4, 'humidity');
        if (hum != null) rows.push(['Humidity', `${hum.toFixed(0)} %`]);
        rows.push(['Airtime (tx/rx)', this._airtime(s)]);
        rows.push(['Packets recv', this._num(s.nb_recv)]);
        rows.push(['Packets sent', this._num(s.nb_sent)]);
        rows.push(['Noise floor', s.noise_floor != null ? `${s.noise_floor} dBm` : '--']);
        rows.push(['Last SNR', s.last_snr != null ? `${s.last_snr} dB` : '--']);
        if (s.recv_errors != null) rows.push(['Recv errors', this._num(s.recv_errors)]);

        // Prefer the repeater's real advertised name, then a config
        // label, then the raw key.
        const title = r.mesh_name || r.name || r.key;
        return `
            <div class="rp-card ${stale ? 'rp-card--stale' : ''}">
                <div class="rp-card__head">
                    <span class="rp-card__name">${this._esc(title)}</span>
                    <span class="rp-card__lamp ${r.ok ? 'rp-ok' : 'rp-stale'}"
                          title="${r.ok ? 'Reporting' : this._esc(r.error || 'stale')}"></span>
                </div>
                <div class="rp-card__id">!${this._esc(r.key)}</div>
                <div class="rp-card__rows">
                    ${rows.map(([k, v]) => `
                        <div class="rp-row"><span class="rp-row__k">${this._esc(k)}</span>
                        <span class="rp-row__v">${this._esc(v)}</span></div>
                    `).join('')}
                </div>
                <div class="rp-card__foot">${stale ? 'stale · ' : ''}polled ${this._ago(r.updated_at)}</div>
            </div>
        `;
    }

    _lppTemp(t) {
        // Prefer the ambient BMP280/SHT3X sensor over MCU die temp.
        return this._lpp(t, 3, 'temperature')
            ?? this._lpp(t, 4, 'temperature')
            ?? this._lpp(t, 1, 'temperature');
    }

    _lpp(t, channel, type) {
        const lpp = t && Array.isArray(t.lpp) ? t.lpp : [];
        const hit = lpp.find((r) => r.channel === channel && r.type === type);
        return hit ? Number(hit.value) : null;
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
