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
 * Mini radio player: when the Radio/RTL-SDR FM listener OR the DAB+
 * listener is actively running, the noise-floor block swaps out for a
 * compact player (station name/frequency, mute, stop) so you can control
 * playback from any page without navigating back to the Listener tab.
 * Swaps back to the noise floor the moment playback stops. Scoped to
 * Radio/DAB+ only -- P2000/Pagers/POCSAG/RTL433 have no audio to
 * control, and already get their own sidebar "in use" badge
 * (listener_badge.js). Radio and DAB+ share one RTL-SDR dongle
 * (src/audio/sdr_registry.py) so at most one is ever running -- polls
 * both /api/listener/status and /api/dab/status independently (own 5s
 * interval, same convention as every other sidebar module) and shows
 * whichever one is actually running. Mute toggles the active <audio>
 * element's own client-side volume directly (instant, no server round-
 * trip) -- a different knob from the Radio page's own Level slider,
 * which is a server-side pre-encode gain that requires a full retune to
 * change.
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
        this._playerTextCache = null;
        // Which listener the player is currently mirroring -- 'radio',
        // 'dab', or null (neither running). Drives which <audio> element
        // mute targets and which stop endpoint/panel the Stop button hits.
        this._activeKind = null;
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
        const [fmStatus, dabStatus] = await Promise.all([
            this._fetchJson('/api/listener/status'),
            this._fetchJson('/api/dab/status'),
        ]);
        // This poll runs regardless of which page is showing, unlike
        // ListenerPanel's own poll (only active while the Listener route
        // is actually mounted) -- so it's the one place that can catch
        // "backend still running, but this page's <audio> element was
        // never (re)connected" after a reload on some other page.
        if (fmStatus && window.listenerPanel) window.listenerPanel.syncAudioFromStatus(fmStatus);

        if (fmStatus && fmStatus.running) {
            this._applyPlayer('radio', fmStatus);
        } else if (dabStatus && dabStatus.running) {
            this._applyPlayer('dab', dabStatus);
        } else {
            this._applyPlayer(null, null);
        }
    }

    async _fetchJson(url) {
        try {
            const res = await fetch(url, { credentials: 'same-origin' });
            return res.ok ? await res.json() : null;
        } catch (_e) {
            return null; // transient network hiccup -- next poll retries
        }
    }

    _applyPlayer(kind, status) {
        this._activeKind = kind;
        const active = !!kind;
        if (this._noiseChip) this._noiseChip.style.display = active ? 'none' : '';
        if (this._playerEl) this._playerEl.style.display = active ? '' : 'none';
        if (!active) return;

        const text = kind === 'radio' ? this._fmPlayerText(status) : this._dabPlayerText(status);
        this._setPlayerText(text);

        const audio = document.getElementById(kind === 'radio' ? 'lsn-audio' : 'dab-audio');
        this._applyMuteIcon(!!(audio && audio.muted));
    }

    // Same priority order as listener_panel.js's own setStation()
    // fallback chain: RDS station (+ RadioText) first, then whichever
    // preset was tuned (persisted server-side as station_label -- see
    // src/audio/rtl_listener.py), then bare frequency + mode.
    _fmPlayerText(status) {
        const ps = (status.rds_ps || '').trim();
        if (ps) {
            const rt = (status.rds_rt || '').trim();
            return (rt && rt !== ps) ? `${ps} — ${rt}` : ps;
        }
        const preset = (status.station_label || '').trim();
        return preset || `${_fmtFreq(status.frequency_mhz)} MHz ${(status.mode || '').toUpperCase()}`;
    }

    // DAB+'s "tuned" and "what's playing" aren't the same thing server-
    // side (an ensemble carries several stations at once, and different
    // browser tabs could each be playing a different one) -- so the
    // specific now-playing station/DLS text can only come from THIS
    // browser's own DabPanel instance, not the shared /api/dab/status
    // payload. Falls back to ensemble+channel when tuned but nothing
    // picked yet (or DabPanel hasn't mounted, e.g. a reload on another
    // page before ever visiting the DAB+ tab).
    _dabPlayerText(status) {
        const playing = window.dabPanel && window.dabPanel.getNowPlaying();
        if (playing) {
            return (playing.dls && playing.dls !== playing.label)
                ? `${playing.label} — ${playing.dls}` : playing.label;
        }
        return `${status.ensemble_label || status.channel || 'DAB+'} (${status.channel || ''})`;
    }

    // Marquees the text when it's too long to fit -- same measure/toggle
    // approach as listener_panel.js's own setStation() (DigitalSkin/
    // AnalogueSkin), reusing its @keyframes lsn-marquee (listener.css,
    // loaded globally) via the shared "scroll" class trigger.
    _setPlayerText(text) {
        const textEl = this._playerTextEl;
        if (!textEl || this._playerTextCache === text) return;
        this._playerTextCache = text;
        textEl.textContent = text;
        textEl.title = text;
        textEl.classList.remove('scroll');
        const scroll = textEl.parentElement;
        if (!scroll) return;
        const overflow = scroll.scrollWidth - scroll.clientWidth;
        if (overflow > 8) {
            textEl.style.setProperty('--scroll-dist', `-${overflow + 16}px`);
            textEl.style.setProperty('--scroll-dur', `${Math.min(24, Math.max(6, (overflow + 16) / 22))}s`);
            void textEl.offsetWidth;
            textEl.classList.add('scroll');
        } else {
            textEl.style.removeProperty('--scroll-dist');
            textEl.style.removeProperty('--scroll-dur');
        }
    }

    _toggleMute() {
        const audio = document.getElementById(this._activeKind === 'dab' ? 'dab-audio' : 'lsn-audio');
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
            if (this._activeKind === 'dab') {
                // Goes through DabPanel's own stop path (not a bare POST)
                // so its local playing-station state and <audio> element
                // get cleared too, keeping the DAB+ tab in sync if visited
                // afterward -- FM's single-pipeline model doesn't need
                // this since there's no separate per-station client state.
                if (window.dabPanel) await window.dabPanel.stopFromSidebar();
                else await fetch('/api/dab/stop', { method: 'POST', credentials: 'same-origin' });
            } else {
                await fetch('/api/listener/stop', { method: 'POST', credentials: 'same-origin' });
            }
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
