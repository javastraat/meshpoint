/**
 * DAB/DAB+ tab content -- styled like the Radio tab's Digital skin (LEDs,
 * VFD-style readout, scrolling station tag, VU meter, native <audio>
 * controls) so it reads as the same instrument family, then a channel
 * picker and station list below since DAB+ needs a genuinely different
 * model: pick a channel/ensemble first (it carries several stations at
 * once), wait for welle-cli to decode the station list, then pick one --
 * see src/audio/dab_listener.py.
 */
const _DAB_DONGLE_OWNER_LABELS = {
    radio: 'Radio', p2000: 'P2000', pagers: 'Pagers', pocsag: 'POCSAG', rtl433: 'RTL433', dab: 'DAB+',
};

// NL DAB+ ensembles for an Amsterdam-area antenna. 12C/11C/9C/7D are
// confirmed nationwide (identical frequency + Ensemble ID across every
// NL DAB scanner region, not just Amsterdam); 6C/8B are the genuinely
// local/provincial ones for this specific area (Radio SALTO and FunX
// Amsterdam only show up on 6C; NH/Omroep Flevoland only on 8B).
const DAB_CHANNEL_PRESETS = [
    { channel: '12C', label: '12C · NPO (national)' },
    { channel: '11C', label: '11C · Commercial (SLAM!, 538, Qmusic, Sky…)' },
    { channel: '9C', label: '9C · Sublime/KINK/Qmusic (national)' },
    { channel: '7D', label: '7D · MTVNL' },
    { channel: '6C', label: '6C · Amsterdam (SALTO, FunX A\'dam)' },
    { channel: '8B', label: '8B · Noord-Holland/Flevo' },
];

class DabPanel {
    constructor() {
        this._root = null;
        this._statusTimer = null;
        this._playingSid = null;
        this._lastStatus = null;
        this._tuning = false;
        this._nowPlayingTextCache = null;
        // A favorite tune-and-play jumps to a channel that may not be the
        // one currently running, then has to wait for that specific
        // station's sid to show up in the progressively-decoded services
        // list before it can actually play -- these track that wait.
        this._pendingPlay = null;      // { channel, sid }
        this._pendingPlayAt = 0;
        // Web Audio VU (mirrors ListenerPanel's own graph, duplicated per
        // this repo's small-helper convention rather than importing
        // across js modules -- see telemetry_rail.js's identical note).
        this._audioCtx = null;
        this._analyser = null;
        this._srcNode = null;
        this._vuData = null;
        this._vuRaf = null;
        this._vuLevel = 0;
    }

    mount(root) {
        this._root = root;
        root.innerHTML = `
            <section class="lsn-section">
                <div class="panel lsn-radio">
                    <div class="panel__header">
                        <span>DAB+</span>
                        <div class="lsn-status" id="dab-lsn-status">
                            <span class="lsn-status__dot" data-dab-dot></span>
                            <span data-dab-status-text>idle</span>
                        </div>
                    </div>
                    <div class="panel__body lsn-radio__body">
                        <div class="lsn-display">
                            <div class="lsn-leds">
                                <span class="lsn-badge" title="DAB+ digital radio">DAB+</span>
                                <span class="lsn-led lsn-led--onair" data-dab-onair
                                      title="On air — the receiver is running and streaming"><i></i>ON AIR</span>
                                <span class="lsn-led lsn-led--tune" data-dab-tuning
                                      title="Tuning — switching channel and restarting the receiver"><i></i>TUNING</span>
                            </div>
                            <div class="lsn-freq">
                                <span class="lsn-freq__num" data-dab-channelnum>--</span>
                                <span class="lsn-freq__unit" data-dab-ensemble></span>
                            </div>
                            <div class="lsn-station" data-dab-nowplaying>
                                <span class="lsn-tag lsn-tag--qual" data-dab-snrtag
                                      title="Signal-to-noise ratio"></span>
                                <span class="lsn-tag lsn-tag--pty" data-dab-ptytag
                                      title="Programme type"></span>
                                <span class="lsn-station__scroll">
                                    <span class="lsn-station__text" data-dab-nowplayingtext>— — —</span>
                                </span>
                            </div>
                            <div class="lsn-vu" title="Audio level (real-time)">
                                <span class="lsn-vu__label">VU</span>
                                <div class="lsn-vu__bar" data-dab-vubar></div>
                            </div>
                        </div>
                        <audio id="dab-audio" controls preload="none"></audio>
                    </div>
                </div>
            </section>
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">Channel</div>
                    <div class="panel__body">
                        <div class="dab-favbar" data-dab-favbar>${this._renderFavBar()}</div>
                        <div class="dab-channels" data-dab-channels>
                            ${DAB_CHANNEL_PRESETS.map((c) => `
                                <button type="button" class="terminal-button" data-dab-channel="${c.channel}">${c.label}</button>
                            `).join('')}
                            <button type="button" class="terminal-button" data-dab-stop>Stop</button>
                        </div>
                    </div>
                </div>
            </section>
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">Stations</div>
                    <div class="panel__body">
                        <div class="dab-stations" data-dab-stations>
                            <div class="pager-log__empty">Pick a channel above to scan for stations.</div>
                        </div>
                    </div>
                </div>
            </section>
        `;
        this._buildVuSegments();
        root.querySelector('[data-dab-channels]').addEventListener('click', (ev) => {
            const stopBtn = ev.target.closest('[data-dab-stop]');
            if (stopBtn) { this._stopEnsemble(); return; }
            const btn = ev.target.closest('[data-dab-channel]');
            if (btn && !btn.disabled) { this._pendingPlay = null; this._tune(btn.dataset.dabChannel); }
        });
        root.querySelector('[data-dab-favbar]').addEventListener('click', (ev) => {
            const btn = ev.target.closest('[data-dab-fav-play]');
            if (!btn) return;
            const fav = this._loadFavs()[parseInt(btn.dataset.dabFavPlay, 10)];
            if (fav) this._playFavorite(fav);
        });
        root.querySelector('[data-dab-stations]').addEventListener('click', (ev) => {
            const favBtn = ev.target.closest('[data-dab-favtoggle]');
            if (favBtn) {
                this._toggleFav({
                    channel: favBtn.dataset.dabChannel,
                    sid: favBtn.dataset.dabSid,
                    label: favBtn.dataset.dabLabel,
                });
                return;
            }
            const btn = ev.target.closest('[data-dab-play]');
            if (btn) { this._pendingPlay = null; this._playOrStop(btn.dataset.dabPlay); }
        });
    }

    // 32-segment VU bar (green/amber/red zones), same construction as
    // ListenerPanel's DigitalSkin.
    _buildVuSegments() {
        const bar = this._root && this._root.querySelector('[data-dab-vubar]');
        if (!bar) return;
        const n = 32;
        let html = '';
        for (let i = 0; i < n; i++) {
            const zone = i < n * 0.66 ? 'g' : i < n * 0.88 ? 'a' : 'r';
            html += `<span class="lsn-vu__seg" data-zone="${zone}"></span>`;
        }
        bar.innerHTML = html;
    }

    /* ── favorites (channel + station sid, so switching channel and
       playing the right station is one click) ────────────────────── */

    _loadFavs() {
        try { return JSON.parse(localStorage.getItem('meshpoint.dabFavs') || '[]'); }
        catch (_e) { return []; }
    }

    _saveFavs(favs) {
        try { localStorage.setItem('meshpoint.dabFavs', JSON.stringify(favs)); }
        catch (_e) { /* ignore */ }
    }

    _isFav(channel, sid) {
        return this._loadFavs().some((f) => f.channel === channel && f.sid === sid);
    }

    _toggleFav({ channel, sid, label }) {
        const favs = this._loadFavs();
        const idx = favs.findIndex((f) => f.channel === channel && f.sid === sid);
        if (idx >= 0) favs.splice(idx, 1);
        else favs.push({ channel, sid, label });
        this._saveFavs(favs);
        const bar = this._root && this._root.querySelector('[data-dab-favbar]');
        if (bar) bar.innerHTML = this._renderFavBar();
        this._repaintStationButtons();
    }

    _renderFavBar() {
        const favs = this._loadFavs();
        if (!favs.length) {
            return '<div class="dab-favbar__empty">No favorites yet — click the ☆ on any station to pin it here.</div>';
        }
        return favs.map((f, i) => `
            <button type="button" class="terminal-button dab-fav-chip" data-dab-fav-play="${i}">
                ★ ${this._esc(f.channel)} · ${this._esc(f.label)}
            </button>
        `).join('');
    }

    /** Jump straight to a favorite: tune its channel if not already there
     * (or the station isn't decoded yet), then auto-play the moment its
     * sid shows up in the progressively-filled station list. */
    async _playFavorite(fav) {
        const st = this._lastStatus;
        if (st && st.running && st.channel === fav.channel) {
            const found = (st.services || []).find((s) => s.sid === fav.sid);
            if (found) { this._playOrStop(fav.sid); return; }
        }
        this._pendingPlay = { channel: fav.channel, sid: fav.sid };
        this._pendingPlayAt = Date.now();
        await this._tune(fav.channel);
    }

    show() {
        this._refresh();
        this._statusTimer = setInterval(() => this._refresh(), 2000);
    }

    hide() {
        clearInterval(this._statusTimer);
        this._statusTimer = null;
    }

    /** Public: what THIS browser tab is currently playing, if anything --
     * for SidebarTelemetryRail's mini-player, which has no reason to
     * duplicate DAB's own on-demand station-selection state (unlike FM,
     * "tuned" and "what's playing" aren't the same thing here). */
    getNowPlaying() {
        if (!this._playingSid || !this._lastStatus) return null;
        const svc = (this._lastStatus.services || []).find((s) => s.sid === this._playingSid);
        if (!svc) return null;
        return { label: svc.label, dls: svc.dls || '' };
    }

    /** Public: stop from outside this tab (e.g. the sidebar mini-player's
     * Stop button) -- tears down the ensemble and clears local playback
     * state exactly like the tab's own Stop button. */
    stopFromSidebar() {
        this._stopEnsemble();
    }

    async _tune(channel) {
        this._tuning = true;
        this._setLeds({ onair: false, tuning: true });
        this._setStatus(false, `tuning ${channel}…`);
        try {
            const r = await fetch('/api/dab/tune', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel }),
            });
            if (!r.ok) {
                const detail = (await r.json().catch(() => ({}))).detail;
                this._tuning = false;
                this._setLeds({ onair: false, tuning: false });
                this._setStatus(false, detail || `tune failed (${r.status})`);
                return;
            }
            this._tuning = false;
            this._render(await r.json());
        } catch (err) {
            this._tuning = false;
            this._setLeds({ onair: false, tuning: false });
            this._setStatus(false, 'tune request failed');
        }
    }

    async _stopEnsemble() {
        this._stopAudio();
        try {
            const r = await fetch('/api/dab/stop', { method: 'POST' });
            if (r.ok) this._render(await r.json());
        } catch (_e) { /* poll catches up */ }
    }

    _playOrStop(sid) {
        const audio = document.getElementById('dab-audio');
        if (!audio) return;
        if (this._playingSid === sid) {
            this._stopAudio();
        } else {
            audio.src = `/api/dab/stream/${encodeURIComponent(sid)}?t=${Date.now()}`;
            audio.play().catch(() => { /* user gesture (click) already present */ });
            this._playingSid = sid;
            if (this._ensureAudioGraph()) this._startVuLoop();
        }
        this._repaintStationButtons();
        this._renderNowPlaying(this._lastStatus);
    }

    _stopAudio() {
        const audio = document.getElementById('dab-audio');
        if (audio) { audio.pause(); audio.removeAttribute('src'); }
        this._playingSid = null;
        this._stopVuLoop();
    }

    _ensureAudioGraph() {
        const audio = document.getElementById('dab-audio');
        if (!audio) return false;
        try {
            if (!this._audioCtx) {
                const AC = window.AudioContext || window.webkitAudioContext;
                if (!AC) return false;
                this._audioCtx = new AC();
            }
            if (!this._srcNode) {
                this._srcNode = this._audioCtx.createMediaElementSource(audio);
                this._analyser = this._audioCtx.createAnalyser();
                this._analyser.fftSize = 1024;
                this._vuData = new Uint8Array(this._analyser.fftSize);
                this._srcNode.connect(this._analyser);
                this._analyser.connect(this._audioCtx.destination);
            }
            if (this._audioCtx.state === 'suspended') this._audioCtx.resume();
            return true;
        } catch (_e) {
            return false;
        }
    }

    _startVuLoop() {
        if (this._vuRaf || !this._analyser) return;
        const tick = () => {
            this._analyser.getByteTimeDomainData(this._vuData);
            let sum = 0;
            for (let i = 0; i < this._vuData.length; i++) {
                const x = (this._vuData[i] - 128) / 128;
                sum += x * x;
            }
            const rms = Math.sqrt(sum / this._vuData.length);
            const db = 20 * Math.log10(rms + 1e-6);
            const lvl = Math.max(0, Math.min(100, (db + 50) / 47 * 100));
            this._vuLevel = this._vuLevel * 0.4 + lvl * 0.6;
            this._setVu(this._vuLevel);
            this._vuRaf = requestAnimationFrame(tick);
        };
        this._vuRaf = requestAnimationFrame(tick);
    }

    _stopVuLoop() {
        if (this._vuRaf) cancelAnimationFrame(this._vuRaf);
        this._vuRaf = null;
        this._vuLevel = 0;
        this._setVu(0);
    }

    _setVu(level) {
        const bar = this._root && this._root.querySelector('[data-dab-vubar]');
        if (!bar) return;
        const segs = bar.children;
        const n = segs.length;
        const lit = Math.max(0, Math.min(n, Math.round((level / 100) * n)));
        for (let i = 0; i < n; i++) segs[i].classList.toggle('on', i < lit);
    }

    async _refresh() {
        try {
            const r = await fetch('/api/dab/status');
            if (!r.ok) return;
            this._render(await r.json());
        } catch (_e) { /* transient network hiccup -- next poll retries */ }
    }

    _render(status) {
        const root = this._root;
        if (!root) return;
        this._lastStatus = status;
        const busyOwner = (status.dongle_owner && status.dongle_owner !== 'dab') ? status.dongle_owner : null;

        root.querySelectorAll('[data-dab-channel]').forEach((btn) => {
            btn.disabled = !!busyOwner;
            btn.classList.toggle('dab-channel--active', status.running && status.channel === btn.dataset.dabChannel);
        });

        this._setLeds({ onair: status.running, tuning: this._tuning });

        const numEl = root.querySelector('[data-dab-channelnum]');
        if (numEl) numEl.textContent = status.channel || '--';
        const ensembleEl = root.querySelector('[data-dab-ensemble]');
        if (ensembleEl) {
            ensembleEl.textContent = status.running
                ? (status.ensemble_label || 'scanning…')
                : '';
        }

        if (status.running) {
            this._setStatus(true, `tuned to ${status.channel}`);
        } else if (busyOwner) {
            this._setStatus(false, `busy — in use by ${_DAB_DONGLE_OWNER_LABELS[busyOwner] || busyOwner}`, true);
            this._stopAudio();
        } else if (status.last_error) {
            this._setStatus(false, `idle — ${status.last_error}`);
            this._stopAudio();
        } else {
            this._setStatus(false, 'idle');
            this._stopAudio();
        }

        this._renderNowPlaying(status);
        this._renderStations(status.services || [], status.running, status.channel);
        this._resolvePendingPlay(status);
    }

    // Drives the VFD-style "now playing" tag row + SNR/PTY pills from
    // whichever station this browser session picked (this._playingSid) --
    // a purely client-side concept, since welle-cli can serve several
    // browser clients different stations from the same tuned ensemble at
    // once (unlike FM, where "tuned" and "what's playing" are the same
    // thing server-side).
    _renderNowPlaying(status) {
        const root = this._root;
        if (!root || !status) return;
        const snrEl = root.querySelector('[data-dab-snrtag]');
        const ptyEl = root.querySelector('[data-dab-ptytag]');
        const textEl = root.querySelector('[data-dab-nowplayingtext]');
        if (!textEl) return;

        const playing = this._playingSid
            && (status.services || []).find((s) => s.sid === this._playingSid);

        if (snrEl) {
            if (status.running && typeof status.snr === 'number') {
                snrEl.style.display = '';
                snrEl.textContent = `${status.snr.toFixed(1)} dB`;
                snrEl.classList.remove('q-good', 'q-mid', 'q-bad');
                snrEl.classList.add(status.snr >= 12 ? 'q-good' : status.snr >= 6 ? 'q-mid' : 'q-bad');
            } else {
                snrEl.style.display = 'none';
            }
        }
        if (ptyEl) {
            const pty = playing ? (playing.pty || '').trim() : '';
            ptyEl.style.display = pty ? '' : 'none';
            ptyEl.textContent = pty;
        }

        let text;
        if (playing) {
            text = (playing.dls && playing.dls !== playing.label)
                ? `${playing.label} — ${playing.dls}` : playing.label;
        } else if (status.running) {
            text = 'select a station below';
        } else {
            text = '— — —';
        }
        this._setNowPlayingText(text);
    }

    // Marquee for now-playing text, same measure/toggle approach as
    // ListenerPanel's setStation().
    _setNowPlayingText(text) {
        const textEl = this._root && this._root.querySelector('[data-dab-nowplayingtext]');
        if (!textEl || this._nowPlayingTextCache === text) return;
        this._nowPlayingTextCache = text;
        textEl.textContent = text;
        const scroll = textEl.parentElement;
        const overflow = scroll.scrollWidth - scroll.clientWidth;
        textEl.classList.remove('scroll');
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

    _setLeds({ onair, tuning }) {
        const root = this._root;
        if (!root) return;
        const onairEl = root.querySelector('[data-dab-onair]');
        const tuneEl = root.querySelector('[data-dab-tuning]');
        if (onairEl) onairEl.classList.toggle('on', !!onair);
        if (tuneEl) tuneEl.classList.toggle('on', !!tuning);
    }

    /** If a favorite jump is waiting on a channel switch, check whether its
     * sid has shown up in the (progressively-decoded) station list yet;
     * give up after 30 s (channel might genuinely not carry that station
     * anymore) rather than waiting forever. */
    _resolvePendingPlay(status) {
        const pending = this._pendingPlay;
        if (!pending) return;
        if (!status.running || status.channel !== pending.channel) {
            if (Date.now() - this._pendingPlayAt > 30000) this._pendingPlay = null;
            return;
        }
        const found = (status.services || []).find((s) => s.sid === pending.sid);
        if (found) {
            this._pendingPlay = null;
            this._playOrStop(pending.sid);
        } else if (Date.now() - this._pendingPlayAt > 30000) {
            this._pendingPlay = null;
            this._setStatus(true, `tuned to ${status.channel} — favorite station not found`);
        }
    }

    _renderStations(services, running, channel) {
        const el = this._root && this._root.querySelector('[data-dab-stations]');
        if (!el) return;
        if (!running) {
            el.innerHTML = '<div class="pager-log__empty">Pick a channel above to scan for stations.</div>';
            return;
        }
        if (!services.length) {
            el.innerHTML = '<div class="pager-log__empty">Scanning… stations appear as they decode.</div>';
            return;
        }
        el.innerHTML = services.map((s) => this._stationRowHtml(s, channel)).join('');
        // Marquee for any label/DLS text that overflows -- mirrors the
        // Radio tab's RDS scroll logic (lsn-station__scroll/.scroll).
        el.querySelectorAll('[data-dab-scrolltext]').forEach((textEl) => {
            const scroll = textEl.parentElement;
            const overflow = scroll.scrollWidth - scroll.clientWidth;
            textEl.classList.remove('scroll');
            if (overflow > 8) {
                textEl.style.setProperty('--scroll-dist', `-${overflow + 16}px`);
                textEl.style.setProperty('--scroll-dur', `${Math.min(24, Math.max(6, (overflow + 16) / 22))}s`);
                void textEl.offsetWidth;
                textEl.classList.add('scroll');
            }
        });
    }

    _stationRowHtml(s, channel) {
        const esc = this._esc.bind(this);
        const playing = this._playingSid === s.sid;
        const isFav = this._isFav(channel, s.sid);
        const text = (s.dls && s.dls !== s.label) ? `${s.label} — ${s.dls}` : s.label;
        return `
            <div class="dab-station-row">
                <span class="lsn-fav${isFav ? ' on' : ''}" data-dab-favtoggle title="Favorite"
                      data-dab-channel="${esc(channel)}" data-dab-sid="${esc(s.sid)}" data-dab-label="${esc(s.label)}">
                    ${isFav ? '★' : '☆'}
                </span>
                <span class="lsn-station__scroll dab-station-row__text">
                    <span class="lsn-station__text" data-dab-scrolltext>${esc(text)}</span>
                </span>
                <button type="button" class="terminal-button${playing ? ' dab-station-row__playing' : ''}"
                        data-dab-play="${esc(s.sid)}">${playing ? 'Stop' : 'Play'}</button>
            </div>
        `;
    }

    _repaintStationButtons() {
        const el = this._root && this._root.querySelector('[data-dab-stations]');
        if (!el) return;
        el.querySelectorAll('[data-dab-play]').forEach((btn) => {
            const playing = this._playingSid === btn.dataset.dabPlay;
            btn.textContent = playing ? 'Stop' : 'Play';
            btn.classList.toggle('dab-station-row__playing', playing);
        });
        el.querySelectorAll('[data-dab-favtoggle]').forEach((star) => {
            const isFav = this._isFav(star.dataset.dabChannel, star.dataset.dabSid);
            star.textContent = isFav ? '★' : '☆';
            star.classList.toggle('on', isFav);
        });
    }

    _setStatus(running, text, busy = false) {
        const dot = this._root && this._root.querySelector('[data-dab-dot]');
        const label = this._root && this._root.querySelector('[data-dab-status-text]');
        if (dot) {
            dot.classList.toggle('lsn-status__dot--on', !!running);
            dot.classList.toggle('lsn-status__dot--busy', !!busy);
        }
        if (label) label.textContent = text;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.DabPanel = DabPanel;
