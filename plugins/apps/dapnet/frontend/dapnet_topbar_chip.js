/**
 * Topbar — DAPNET/POCSAG companion chip(s).
 *
 * Registers with core's window.registerTopbarChip (frontend/topbar/
 * topbar_plugin_registry.js) -- one small badge per configured device,
 * same "no single primary" reasoning as the core Serial chip (each
 * companion is an independent passive capture source). Reuses the exact
 * `.topbar-serial`/`.topbar-dapnet` CSS wholesale (still core, untouched
 * since the old built-in chip used it) -- same lamp/brand/sep visual
 * language, just DAPNET's own fields: callsign instead of node ID, board
 * name (ttgo/heltec) instead of modem preset.
 *
 * Unlike the old core chip (fed by TopbarController's shared GET
 * /api/config poll), this one self-polls GET /api/dapnet/status directly
 * -- same endpoint and cadence as dapnet_status_card.js's page-level
 * status card. Both exist side by side on purpose: the topbar chip is
 * the at-a-glance-from-anywhere badge, the page's own status card shows
 * more detail (hostname, WiFi SSID, TX count, uptime) the same way
 * Meshtastic/MeshCore have both a topbar chip and a detailed page.
 * Hidden entirely when no device is configured yet.
 */
class DapnetTopbarChip {
    constructor() {
        this._group = null;
        this._timer = null;
    }

    mount(rootEl) {
        this._group = rootEl;
        this._group.hidden = true;
    }

    init() {
        this._refresh();
        this._timer = setInterval(() => this._refresh(), 10_000);
    }

    destroy() {
        clearInterval(this._timer);
        this._timer = null;
    }

    async _refresh() {
        let devices = [];
        try {
            const res = await fetch('/api/dapnet/status', { credentials: 'same-origin' });
            if (res.ok) devices = await res.json();
        } catch (_e) { /* keep last-known badges showing */ }
        this._paint(Array.isArray(devices) ? devices : []);
    }

    _paint(devices) {
        this._group.hidden = devices.length === 0;
        this._group.textContent = '';
        devices.forEach((dev) => this._group.appendChild(this._buildBadge(dev)));
    }

    _buildBadge(dev) {
        const connected = Boolean(dev.connected);
        const callsign = (dev.callsign || '').trim();

        const root = document.createElement('a');
        root.className = 'topbar-serial topbar-dapnet';
        root.href = '#/dapnet';
        root.setAttribute(
            'aria-label',
            `DAPNET ${callsign || 'companion'} ${connected ? 'connected' : 'offline'} -- go to DAPNET page`,
        );
        root.title = 'DAPNET/POCSAG companion';

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'DAPNET';
        root.appendChild(brand);

        const lamp = document.createElement('span');
        lamp.className = `topbar-serial__lamp topbar-serial__lamp--${connected ? 'online' : 'offline'}`;
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        const callEl = document.createElement('span');
        callEl.className = 'topbar-serial__call';
        callEl.textContent = callsign || '----';
        root.appendChild(callEl);

        root.appendChild(this._sep());

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = this._formatFreq(dev.frequency_mhz);
        root.appendChild(freqEl);

        root.classList.toggle('topbar-serial--offline', !connected);
        return root;
    }

    _sep() {
        const sep = document.createElement('span');
        sep.className = 'topbar-serial__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = '·';
        return sep;
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(4)} MHz`;
    }
}

window.registerTopbarChip({ id: 'dapnet', make: () => new DapnetTopbarChip() });
