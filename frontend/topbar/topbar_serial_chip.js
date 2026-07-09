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
 *
 * Layout mirrors the Meshtastic/MeshCore chips: brand, lamp, a "call
 * sign" slot (here: the stick's own node ID -- a config label would be
 * redundant), frequency (which already tells the band; the region enum
 * was dropped as noise), and the stick's own modem preset (same data
 * the Meshtastic chip's trailing segment shows, read at connect time).
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
        const ownId = this._shortNodeId(dev.own_node_id_hex);
        // Same wording as the MeshCore chip's name slot in this state.
        const callText = !reachable ? 'Reconnecting…' : (ownId || '----');

        const root = document.createElement('span');
        root.className = 'topbar-serial';
        root.setAttribute(
            'aria-label',
            `Meshtastic USB ${ownId || 'device'} `
                + `${!reachable ? 'reconnecting' : (connected ? 'connected' : 'offline')}`,
        );
        root.title = !reachable
            ? 'Reconnecting to the dashboard…'
            : (ownId
                ? 'Self-telemetry/nodeinfo from this ID is filtered from the packet feed'
                : "This stick's own node ID is not known yet");

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'Meshtastic';
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

        const callEl = document.createElement('span');
        callEl.className = 'topbar-serial__call'
            + (!reachable ? ' topbar-serial__call--status' : '');
        callEl.textContent = callText;
        root.appendChild(callEl);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = !reachable ? '--' : this._formatFreq(dev.frequency_mhz);
        root.appendChild(this._sep());
        root.appendChild(freqEl);

        const presetEl = document.createElement('span');
        presetEl.className = 'topbar-serial__preset';
        presetEl.textContent = !reachable ? '--' : this._formatPresetLabel(dev.modem_preset);
        root.appendChild(this._sep(true));
        root.appendChild(presetEl);

        root.classList.toggle('topbar-serial--offline', reachable && !connected);
        root.classList.toggle('topbar-serial--reconnecting', !reachable);
        return root;
    }

    _sep(bar = false) {
        const sep = document.createElement('span');
        sep.className = bar ? 'topbar-serial__sep topbar-serial__sep--bar' : 'topbar-serial__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = bar ? '|' : '·';
        return sep;
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(3)} MHz`;
    }

    /** Mirrors TopbarMeshtasticChip._formatPresetLabel -- same enum-name
     * strings (both read via meshtastic.protobuf ModemPreset.Name()). */
    _formatPresetLabel(presetName) {
        if (!presetName || presetName === 'CUSTOM') return 'Custom';
        const labels = {
            LONG_FAST: 'LongFast',
            LONG_TURBO: 'LongTurbo',
            LONG_MODERATE: 'LongModerate',
            LONG_SLOW: 'LongSlow',
            VERY_LONG_SLOW: 'VeryLongSlow',
            MEDIUM_FAST: 'MediumFast',
            MEDIUM_SLOW: 'MediumSlow',
            SHORT_FAST: 'ShortFast',
            SHORT_SLOW: 'ShortSlow',
            SHORT_TURBO: 'ShortTurbo',
        };
        return labels[String(presetName)] || String(presetName);
    }

    /** "09d406f4" -> "!06f4", matching the packet feed's node ID style. */
    _shortNodeId(hex) {
        if (!hex) return null;
        return `!${String(hex).slice(-4)}`;
    }
}

window.TopbarSerialChip = TopbarSerialChip;
