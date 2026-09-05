/**
 * DAPNET status card -- device connected/board/callsign/freq/hostname/wifi,
 * shown prominently at the top of the plugin's own page.
 *
 * Replaces the old core topbar chip (frontend/topbar/topbar_dapnet_chip.js,
 * deleted along with the rest of core's DAPNET surface) -- this plugin
 * deliberately doesn't get an equivalent, since no generic "plugin owns a
 * topbar chip" seam exists yet and building one for a single plugin risked
 * guessing its shape wrong (see plugins/apps/dapnet/README.md for the full
 * reasoning). Losing the at-a-glance-from-anywhere status is a real,
 * acknowledged trade-off; showing it prominently here instead of behind a
 * click is the mitigation.
 *
 * Polls GET /api/dapnet/status (settings_routes.py) directly rather than
 * the old core GET /api/config's dapnet_status key, which no longer exists.
 */
class DapnetStatusCard {
    constructor(el) {
        this._el = el;
        this._timer = null;
    }

    show() {
        this._refresh();
        this._timer = setInterval(() => this._refresh(), 10_000);
    }

    hide() {
        clearInterval(this._timer);
        this._timer = null;
    }

    async _refresh() {
        let devices = [];
        try {
            const res = await fetch('/api/dapnet/status', { credentials: 'same-origin' });
            if (res.ok) devices = await res.json();
        } catch (_e) { /* keep last known render */ }
        this._render(devices);
    }

    _render(devices) {
        if (!this._el) return;
        if (!devices.length) {
            this._el.innerHTML = `
                <div class="lw-stats" style="margin-bottom: 12px">
                    <div class="stat-card">
                        <div class="stat-card__label">Companion</div>
                        <div class="stat-card__value">Not configured</div>
                    </div>
                </div>
            `;
            return;
        }
        this._el.innerHTML = `
            <div class="lw-stats" style="margin-bottom: 12px">
                ${devices.map((d) => this._deviceCard(d)).join('')}
            </div>
        `;
    }

    _deviceCard(d) {
        const title = this._esc(d.name || d.callsign || d.board || 'Companion');
        const dot = d.connected ? '🟢' : '⚪';
        const bits = [];
        if (d.board) bits.push(this._esc(d.board));
        if (d.callsign) bits.push(this._esc(d.callsign));
        if (d.frequency_mhz) bits.push(`${d.frequency_mhz} MHz`);
        if (d.wifi_ip) bits.push(this._esc(d.wifi_ip));
        return `
            <div class="stat-card">
                <div class="stat-card__label">${dot} ${title}</div>
                <div class="stat-card__value" style="font-size: 0.95rem">
                    ${bits.length ? bits.join(' · ') : (d.connected ? 'Connected' : 'Disconnected')}
                </div>
            </div>
        `;
    }

    _esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
}

window.DapnetStatusCard = DapnetStatusCard;
