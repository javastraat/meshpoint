/**
 * Topbar — Meshtastic USB serial device chip(s).
 *
 * One small cyan badge per configured `capture.serial` device (T5
 * multi-stick support). Unlike MeshCore's single TX-bound "primary"
 * companion, every serial device is a passive capture-only source
 * (Meshtastic TX from the dashboard goes through the concentrator,
 * not a USB stick) -- there's no single "the" device, so this renders
 * one badge per configured stick and hides the whole group when none
 * are configured.
 */
class TopbarSerialChip {
    constructor(groupEl) {
        this._group = groupEl;
        this._lastDevices = [];
        this._dashboardReachable = false;
    }

    setSerial(devices) {
        this._lastDevices = Array.isArray(devices) ? devices : [];
        this._paint();
    }

    /** When false, every badge shows "reconnecting" (dashboard/API poll
     * unreachable) instead of its last-known per-device status -- same
     * treatment as the Meshtastic/MeshCore chips on a websocket drop
     * (e.g. a dashboard restart), so this chip doesn't keep silently
     * showing stale data while the others visibly react. */
    setDashboardReachable(reachable) {
        this._dashboardReachable = Boolean(reachable);
        this._paint();
    }

    _paint() {
        const list = this._lastDevices;
        this._group.hidden = list.length === 0;
        this._group.textContent = '';
        list.forEach((dev) => this._group.appendChild(this._buildBadge(dev)));
    }

    _buildBadge(dev) {
        const reachable = this._dashboardReachable;
        const connected = reachable && Boolean(dev.connected);
        const label = this._labelFromName(dev.name);
        const ownId = this._shortNodeId(dev.own_node_id_hex);

        const root = document.createElement('span');
        root.className = 'topbar-serial';
        root.setAttribute(
            'aria-label',
            `Meshtastic USB${label ? ` ${label}` : ''} `
                + `${!reachable ? 'reconnecting' : (connected ? 'connected' : 'offline')}`,
        );
        root.title = !reachable
            ? 'Reconnecting to the dashboard…'
            : (ownId
                ? `This stick's own node ID: ${ownId} (its self-telemetry/nodeinfo is filtered from the packet feed)`
                : "This stick's own node ID is not known yet");

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'USB';
        root.appendChild(brand);

        const lampState = !reachable ? 'reconnecting' : (connected ? 'online' : 'offline');
        const lamp = document.createElement('span');
        lamp.className = `topbar-serial__lamp topbar-serial__lamp--${lampState}`;
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        if (label) {
            const labelEl = document.createElement('span');
            labelEl.className = 'topbar-serial__label';
            labelEl.textContent = label;
            root.appendChild(labelEl);
        }

        const region = !reachable
            ? '--'
            : ((dev.region && dev.region !== 'UNSET') ? dev.region : '--');
        const regionEl = document.createElement('span');
        regionEl.className = 'topbar-serial__region';
        regionEl.textContent = region;
        root.appendChild(this._sep());
        root.appendChild(regionEl);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = !reachable ? '--' : this._formatFreq(dev.frequency_mhz);
        root.appendChild(this._sep());
        root.appendChild(freqEl);

        root.classList.toggle('topbar-serial--offline', reachable && !connected);
        root.classList.toggle('topbar-serial--reconnecting', !reachable);
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
        return `${n.toFixed(3)} MHz`;
    }

    /** "serial_433" -> "433"; bare "serial" -> null (no useful label). */
    _labelFromName(name) {
        const raw = String(name || '');
        const idx = raw.indexOf('_');
        if (idx === -1) return null;
        return raw.slice(idx + 1) || null;
    }

    /** "09d406f4" -> "!06f4", matching the packet feed's node ID style. */
    _shortNodeId(hex) {
        if (!hex) return null;
        return `!${String(hex).slice(-4)}`;
    }
}

window.TopbarSerialChip = TopbarSerialChip;
