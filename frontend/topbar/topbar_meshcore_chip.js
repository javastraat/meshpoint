/**
 * Topbar — MeshCore USB companion chip(s).
 *
 * One small purple badge per configured `capture.meshcore_usb` companion
 * (mirrors TopbarSerialChip's identical "one badge per configured device"
 * pattern -- up to 4 companions can be configured, each with its own
 * independent connection, so a single chip could only ever show
 * company[0]'s status). Reads `meshcore.companions` (per-companion
 * name/connected/radio), keyed by `meshcore_usb_<label>` names, same as
 * the Configuration page's MeshCore card. Channel names are still
 * mesh-wide config (`meshcore.channel_keys`, synced only through the
 * primary companion), so every badge shows the same channel slot --
 * that's a real shared value, not a per-badge stand-in.
 */
class TopbarMeshcoreChip {
    constructor(groupEl) {
        this._group = groupEl;
        this._lastMc = null;
        this._dashboardReachable = false;
    }

    setMeshcore(meshcore) {
        this._lastMc = meshcore || null;
        this._paint();
    }

    /** When false, every badge shows "reconnecting" (dashboard/API poll
     * unreachable) instead of its last-known per-companion status --
     * same treatment as the Serial chip on a websocket drop. */
    setDashboardReachable(reachable) {
        this._dashboardReachable = Boolean(reachable);
        this._paint();
    }

    _paint() {
        const mc = this._lastMc || {};
        const companions = Array.isArray(mc.companions) ? mc.companions : [];
        this._group.hidden = companions.length === 0;
        this._group.textContent = '';
        companions.forEach((companion) => {
            this._group.appendChild(this._buildBadge(companion, mc.channel_keys));
        });
    }

    _buildBadge(companion, channelKeys) {
        const reachable = this._dashboardReachable;
        const connected = reachable && Boolean(companion.connected);
        const radio = companion.radio || {};
        const label = this._companionLabel(companion.name);

        const root = document.createElement('span');
        root.className = 'topbar-meshcore';
        root.setAttribute(
            'aria-label',
            `MeshCore companion ${label ? `${label} ` : ''}`
                + `${!reachable ? 'reconnecting' : (connected ? 'connected' : 'offline')}`,
        );

        const brand = document.createElement('span');
        brand.className = 'topbar-meshcore__brand';
        brand.textContent = 'MeshCore';
        root.appendChild(brand);

        const lampState = !reachable ? 'reconnecting' : (connected ? 'online' : 'offline');
        const lamp = document.createElement('span');
        lamp.className = 'topbar-meshcore__lamp';
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const lampLabels = {
            online: 'MeshCore companion connected',
            offline: 'MeshCore companion offline',
            reconnecting: 'MeshCore status unknown (dashboard reconnecting)',
        };
        lamp.setAttribute('aria-label', lampLabels[lampState]);
        const dot = document.createElement('span');
        dot.className = 'topbar-meshcore__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        const nameEl = document.createElement('span');
        nameEl.className = 'topbar-meshcore__name';
        nameEl.textContent = !reachable
            ? 'Reconnecting…'
            : this._formatName(radio.name, connected, label);
        root.appendChild(nameEl);

        root.appendChild(this._sep());
        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-meshcore__freq';
        freqEl.textContent = !reachable ? '--' : this._formatFreq(radio.frequency_mhz);
        root.appendChild(freqEl);

        root.appendChild(this._sep(true));
        const channelEl = document.createElement('span');
        channelEl.className = 'topbar-meshcore__channel';
        channelEl.textContent = !reachable ? '--' : this._formatChannel(channelKeys);
        root.appendChild(channelEl);

        root.classList.toggle('topbar-meshcore--online', reachable && connected);
        root.classList.toggle('topbar-meshcore--offline', reachable && !connected);
        root.classList.toggle('topbar-meshcore--reconnecting', !reachable);
        return root;
    }

    _sep(bar = false) {
        const sep = document.createElement('span');
        sep.className = bar ? 'topbar-meshcore__sep topbar-meshcore__sep--bar' : 'topbar-meshcore__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = bar ? '|' : '·';
        return sep;
    }

    /** "meshcore_usb_868" -> "868", bare "meshcore_usb" -> "". */
    _companionLabel(name) {
        const prefix = 'meshcore_usb_';
        return typeof name === 'string' && name.startsWith(prefix)
            ? name.slice(prefix.length)
            : '';
    }

    _formatName(radioName, connected, label) {
        const raw = (radioName || '').trim();
        if (raw) return label ? `${raw} (${label})` : raw;
        if (connected) return label ? `Companion ${label}` : 'Companion';
        return 'No companion';
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(3)} MHz`;
    }

    _formatChannel(channelKeys) {
        const keys = Array.isArray(channelKeys) ? channelKeys : [];
        const names = keys
            .map((ch) => (ch && ch.name ? String(ch.name).trim() : ''))
            .filter(Boolean);
        if (names.length === 0) return 'Public';
        if (names.length === 1) return names[0];
        return `${names[0]} +${names.length - 1}`;
    }
}

window.TopbarMeshcoreChip = TopbarMeshcoreChip;
