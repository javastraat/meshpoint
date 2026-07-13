/**
 * Sidebar telemetry rail.
 *
 * Pinned between the nav and the role/sign-out footer. Always-on
 * status surface so the sidebar reads like a piece of lab equipment
 * with status LEDs, not a passive nav drawer.
 *
 * Three rows:
 *   - Uptime          (slow polled from /api/device/status, 5s)
 *   - Active sessions (same poll, websocket_clients count)
 *   - Noise floor     (live from `noise_floor` WS frame; sparkline
 *                      drawn by NoiseFloorSparkline)
 *   - RF Environment  (link to full RF tab, below noise floor)
 *
 * Hidden when the sidebar is in icon-only "rail" mode.
 *
 * Mini radio player: when the Radio/RTL-SDR FM listener is actively
 * tuned, the noise-floor block swaps out for a compact player (station
 * name or frequency, mute, stop) so you can control playback from any
 * page without navigating back to the Listener tab. Swaps back to the
 * noise floor the moment playback stops. Scoped to the Radio tab only
 * -- P2000/Pagers/POCSAG/RTL433 have no audio to control, and already
 * get their own sidebar "in use" badge (listener_badge.js). Polls
 * /api/listener/status independently (own 5s interval, same convention
 * as every other sidebar module) rather than sharing ListenerBadge's
 * poll -- decoupled, at the cost of one redundant request every 5s.
 * Mute toggles the actual <audio id="lsn-audio"> element's own client-
 * side volume directly (instant, no server round-trip) -- a different
 * knob from the Radio page's own Level slider, which is a server-side
 * pre-encode gain that requires a full retune to change.
 */
class SidebarTelemetryRail {
    constructor(rootEl, dashboardWs) {
        this._root = rootEl;
        this._ws = dashboardWs;
        this._uptimeEl = rootEl.querySelector('#telemetry-uptime');
        this._sessionsEl = rootEl.querySelector('#telemetry-sessions');
        this._noiseEl = rootEl.querySelector('#telemetry-noise-value');
        this._noiseBwEl = rootEl.querySelector('#telemetry-noise-bw');
        this._noiseChip = rootEl.querySelector('.telemetry-rail__noise');
        const canvas = rootEl.querySelector('#telemetry-noise-canvas');
        this._sparkline = canvas ? new NoiseFloorSparkline(canvas) : null;
        this._statusTimer = null;
        this._playerEl = rootEl.querySelector('#telemetry-player');
        this._playerTextEl = rootEl.querySelector('#telemetry-player-text');
        this._muteBtn = rootEl.querySelector('#telemetry-player-mute');
        this._stopBtn = rootEl.querySelector('#telemetry-player-stop');
        this._playerTimer = null;
    }

    init() {
        this._refreshStatus();
        this._statusTimer = setInterval(() => this._refreshStatus(), 5_000);
        if (this._ws) {
            this._ws.on('noise_floor', (data) => this._onNoiseFloor(data));
        }
        this._refreshPlayer();
        this._playerTimer = setInterval(() => this._refreshPlayer(), 5_000);
        if (this._muteBtn) this._muteBtn.addEventListener('click', () => this._toggleMute());
        if (this._stopBtn) this._stopBtn.addEventListener('click', () => this._stopRadio());
    }

    destroy() {
        if (this._statusTimer) clearInterval(this._statusTimer);
        if (this._playerTimer) clearInterval(this._playerTimer);
    }

    async _refreshStatus() {
        try {
            const res = await fetch('/api/device/status', {
                credentials: 'same-origin',
            });
            if (!res.ok) return;
            const data = await res.json();
            this._uptimeEl.textContent = _formatUptime(data.uptime_seconds || 0);
            const sessions = data.websocket_clients;
            if (typeof sessions === 'number') {
                this._sessionsEl.textContent = String(sessions);
            }
        } catch (_e) { /* swallow; next tick will retry */ }
    }

    _onNoiseFloor(data) {
        if (!data) return;
        const value = data.value_dbm;
        const stale = !!data.stale;
        const calibrating = !!data.calibrating;
        const bw = data.bandwidth_khz;
        const samples = Array.isArray(data.samples_dbm) ? data.samples_dbm : [];
        const floor = data.theoretical_floor_dbm;
        const source = data.source;

        if (calibrating || value == null) {
            this._noiseEl.textContent = value == null ? 'calibrating' : `${value.toFixed(0)} dBm`;
        } else {
            this._noiseEl.textContent = `${value.toFixed(0)} dBm`;
        }
        this._noiseEl.title = _buildNoiseTooltip({
            source, value, calibrating, stale, samples_count: data.samples_count,
            theoretical_floor_dbm: floor,
        });

        if (bw) {
            this._noiseBwEl.textContent = `${bw.toFixed(0)} kHz`;
        } else {
            this._noiseBwEl.textContent = '--';
        }

        this._noiseChip.classList.toggle(
            'telemetry-rail__noise--stale', stale,
        );
        this._noiseChip.classList.toggle(
            'telemetry-rail__noise--calibrating', calibrating,
        );

        if (this._sparkline) this._sparkline.setSamples(samples, floor);
    }

    async _refreshPlayer() {
        try {
            const res = await fetch('/api/listener/status', { credentials: 'same-origin' });
            if (!res.ok) return;
            this._applyPlayer(await res.json());
        } catch (_e) { /* swallow; next poll retries */ }
    }

    _applyPlayer(status) {
        const active = !!status.running;
        if (this._noiseChip) this._noiseChip.style.display = active ? 'none' : '';
        if (this._playerEl) this._playerEl.style.display = active ? '' : 'none';
        if (!active) return;

        const ps = (status.rds_ps || '').trim();
        const text = ps || `${_fmtFreq(status.frequency_mhz)} MHz ${(status.mode || '').toUpperCase()}`;
        if (this._playerTextEl) this._playerTextEl.textContent = text;

        const audio = document.getElementById('lsn-audio');
        this._applyMuteIcon(!!(audio && audio.muted));
    }

    _toggleMute() {
        const audio = document.getElementById('lsn-audio');
        if (!audio) return;
        audio.muted = !audio.muted;
        this._applyMuteIcon(audio.muted);
    }

    _applyMuteIcon(muted) {
        if (!this._muteBtn) return;
        this._muteBtn.setAttribute('aria-pressed', muted ? 'true' : 'false');
        this._muteBtn.title = muted ? 'Unmute' : 'Mute';
        this._muteBtn.setAttribute('aria-label', muted ? 'Unmute' : 'Mute');
        const unmutedIcon = this._muteBtn.querySelector('[data-icon="unmuted"]');
        const mutedIcon = this._muteBtn.querySelector('[data-icon="muted"]');
        if (unmutedIcon) unmutedIcon.style.display = muted ? 'none' : '';
        if (mutedIcon) mutedIcon.style.display = muted ? '' : 'none';
    }

    async _stopRadio() {
        try {
            await fetch('/api/listener/stop', { method: 'POST', credentials: 'same-origin' });
        } catch (_e) { /* swallow; next poll reflects reality */ }
        this._refreshPlayer();
    }
}

// Matches listener_panel.js's own fmtFreq4 -- duplicated per this repo's
// small-helper convention rather than importing across sidebar/js modules.
function _fmtFreq(mhz) {
    return Number.isFinite(mhz) ? mhz.toFixed(4) : '--.----';
}

function _buildNoiseTooltip({ source, value, calibrating, stale, samples_count, theoretical_floor_dbm }) {
    if (calibrating) {
        return (
            'Waiting for the first spectral scan or a few packets '
            + 'before reporting a number.'
        );
    }
    if (value == null) {
        return 'No noise floor data yet.';
    }
    if (source === 'spectral_scan') {
        const margin = (theoretical_floor_dbm != null && value != null)
            ? `${(value - theoretical_floor_dbm).toFixed(1)} dB above theoretical thermal floor`
            : '';
        const fresh = stale ? ' (last scan stale)' : '';
        return (
            `Direct ambient channel power from SX1302 spectral scan${fresh}. `
            + 'Sampled on the same frequency the radio is tuned to. '
            + (margin ? `${margin}.` : '')
        );
    }
    const fresh = stale ? ' (no recent packets)' : '';
    return (
        `Packet-derived upper bound (rolling minimum of rssi - snr)${fresh}. `
        + 'This is a fallback estimate: the true noise floor is at or below this value. '
        + 'Spectral scan was not available on this device.'
    );
}

function _formatUptime(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

window.SidebarTelemetryRail = SidebarTelemetryRail;
