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

// NL DAB+ ensembles for an Amsterdam-area antenna. All 5 confirmed live
// via scripts/dab_channel_scan.py's real full-channel scan on this exact
// antenna (2026-07-13) -- labels reflect the actual decoded station
// rosters, not guesses from another city's scanner data. 6C (Radio
// SALTO/FunX Amsterdam) was tried and dropped after decoding nothing
// here; use the manual channel dropdown below for anything else.
const DAB_CHANNEL_PRESETS = [
    { channel: '12C', name: 'NPO', label: '12C · NPO (Radio 1/2/3FM/Klassiek/FunX…)' },
    { channel: '11C', name: 'Commercial', label: '11C · Commercial (SLAM!, 538, Qmusic, Sky, Radio 10…)' },
    { channel: '9C', name: 'Throwback', label: '9C · Throwback/hits (Sublime, KINK, Qmusic Foute Uur…)' },
    { channel: '7D', name: 'MTVNL', label: '7D · MTVNL (KINK Distortion, ArrowClassicRock, Veronica 90s…)' },
    { channel: '8B', name: 'NH/Flevo', label: '8B · Noord-Holland/Flevo (NH, Omroep Flevoland, SLAM!…)' },
];

// Full Band III DAB channel raster (5A-13F, 38 channels; ETSI EN 300 401)
// for the manual channel dropdown, alongside the curated presets above --
// L-Band (LA-LW) isn't offered since the Netherlands doesn't use it.
const DAB_ALL_CHANNELS = (() => {
    const channels = [];
    for (let n = 5; n <= 12; n++) {
        for (const letter of ['A', 'B', 'C', 'D']) channels.push(`${n}${letter}`);
    }
    for (const letter of ['A', 'B', 'C', 'D', 'E', 'F']) channels.push(`13${letter}`);
    return channels;
})();

class DabPanel {
    constructor() {
        this._root = null;
        this._statusTimer = null;
        this._playingSid = null;
        this._lastStatus = null;
        this._tuning = false;
        this._nowPlayingTextCache = null;
        // Sub-tabs within the DAB+ tab: 'favorites', 'manual', or a
        // channel code. Starts on Favorites so there's something useful
        // to see immediately rather than an empty tab needing a click.
        this._activeChannelTab = 'favorites';
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
                            <div class="lsn-freq dab-nowplaying-big">
                                <span class="lsn-station__scroll">
                                    <span class="lsn-station__text lsn-station__text--big" data-dab-nowplayingtext>— — —</span>
                                </span>
                            </div>
                            <div class="lsn-station" data-dab-nowplaying>
                                <span class="lsn-tag lsn-tag--qual" data-dab-snrtag
                                      title="Signal-to-noise ratio"></span>
                                <span class="lsn-tag lsn-tag--pty" data-dab-ptytag
                                      title="Programme type"></span>
                                <span class="lsn-freq__unit dab-chan-tag" data-dab-chantag
                                      title="Channel"></span>
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
                    <div class="panel__header">
                        <span>Channel</span>
                        <button type="button" class="terminal-button" data-dab-stop>Stop</button>
                    </div>
                    <div class="panel__body">
                        <div class="lsn-tabbar dab-chantabs" data-dab-chantabs>
                            <button type="button" class="lsn-tabbar__btn lsn-tabbar__btn--active" data-chantab="favorites">★ Favorites</button>
                            ${DAB_CHANNEL_PRESETS.map((c) => `
                                <button type="button" class="lsn-tabbar__btn" data-chantab="${c.channel}" title="${c.channel} — ${c.label}">${c.name}</button>
                            `).join('')}
                            <button type="button" class="lsn-tabbar__btn" data-chantab="manual">Manual…</button>
                        </div>
                        <div class="dab-chantab-content" data-dab-chantab-content></div>
                    </div>
                </div>
            </section>
        `;
        this._buildVuSegments();
        root.querySelector('[data-dab-stop]').addEventListener('click', () => this._stopEnsemble());
        root.querySelector('[data-dab-chantabs]').addEventListener('click', (ev) => {
            const btn = ev.target.closest('[data-chantab]');
            if (btn && !btn.disabled) this._switchChannelTab(btn.dataset.chantab);
        });
        root.querySelector('[data-dab-chantab-content]').addEventListener('click', (ev) => {
            const scanBtn = ev.target.closest('[data-dab-scan-channel]');
            if (scanBtn) {
                this._pendingPlay = null;
                this._tune(scanBtn.dataset.dabScanChannel);
                return;
            }
            const favRemoveBtn = ev.target.closest('[data-dab-fav-remove]');
            if (favRemoveBtn) {
                const fav = this._loadFavs()[parseInt(favRemoveBtn.dataset.dabFavRemove, 10)];
                if (fav) this._toggleFav(fav); // already a favorite -> this removes it
                return;
            }
            const favPlayBtn = ev.target.closest('[data-dab-fav-play]');
            if (favPlayBtn) {
                const fav = this._loadFavs()[parseInt(favPlayBtn.dataset.dabFavPlay, 10)];
                if (fav) {
                    if (this._playingSid === fav.sid) this._playOrStop(fav.sid);
                    else this._playFavorite(fav);
                }
                return;
            }
            const manualTuneBtn = ev.target.closest('[data-dab-manual-tune]');
            if (manualTuneBtn) {
                const sel = root.querySelector('[data-dab-manual-select]');
                const channel = sel && sel.value;
                if (channel) { this._pendingPlay = null; this._tune(channel); }
                return;
            }
            const favToggle = ev.target.closest('[data-dab-favtoggle]');
            if (favToggle) {
                this._toggleFav({
                    channel: favToggle.dataset.dabChannel,
                    sid: favToggle.dataset.dabSid,
                    label: favToggle.dataset.dabLabel,
                });
                return;
            }
            const playBtn = ev.target.closest('[data-dab-play]');
            if (playBtn) { this._pendingPlay = null; this._playOrStop(playBtn.dataset.dabPlay); }
        });
        this._renderChanTabContent();
    }

    /** Switch which sub-tab is shown -- a pure view switch, no tuning side
     * effect. Browsing a channel tab that isn't the one actually running
     * shows a Scan prompt instead of silently interrupting whatever's
     * currently playing; only pressing Scan/Rescan retunes. */
    _switchChannelTab(tab) {
        this._activeChannelTab = tab;
        const root = this._root;
        if (root) {
            root.querySelectorAll('[data-chantab]').forEach((btn) => {
                btn.classList.toggle('lsn-tabbar__btn--active', btn.dataset.chantab === tab);
            });
        }
        this._renderChanTabContent();
    }

    // Renders whichever sub-tab is active into the shared content
    // container -- favorites chips, the manual channel picker, or a
    // channel's station list (only ever one truly "live" at a time,
    // since the dongle can only be tuned to one channel).
    _renderChanTabContent() {
        const el = this._root && this._root.querySelector('[data-dab-chantab-content]');
        if (!el) return;
        const tab = this._activeChannelTab;
        const status = this._lastStatus;
        const busyOwner = status && status.dongle_owner && status.dongle_owner !== 'dab'
            ? status.dongle_owner : null;

        if (tab === 'favorites') {
            el.innerHTML = `<div data-dab-favbar>${this._renderFavBar()}</div>`;
            this._afterStationsRender(el);
            return;
        }

        if (tab === 'manual') {
            // Build the select/button shell only once per tab-switch;
            // poll-driven re-renders (every 2s) only touch the stations
            // sub-container below it, so an open dropdown or in-progress
            // pick survives a status refresh instead of getting wiped by
            // a full innerHTML rebuild.
            let manualEl = el.querySelector('[data-dab-manual]');
            if (!manualEl) {
                el.innerHTML = `
                    <div class="dab-manual" data-dab-manual>
                        <select class="dab-manual__select" data-dab-manual-select title="Manual channel entry">
                            <option value="">Manual channel…</option>
                            ${DAB_ALL_CHANNELS.map((ch) => `<option value="${ch}">${ch}</option>`).join('')}
                        </select>
                        <button type="button" class="terminal-button" data-dab-manual-tune>Tune</button>
                    </div>
                    <div data-dab-manual-stations></div>
                `;
            }
            const sel = el.querySelector('[data-dab-manual-select]');
            const tuneBtn = el.querySelector('[data-dab-manual-tune]');
            if (sel) {
                sel.disabled = !!busyOwner;
                if (document.activeElement !== sel && status && status.running) {
                    sel.value = status.channel || '';
                }
            }
            if (tuneBtn) tuneBtn.disabled = !!busyOwner;
            const stationsEl = el.querySelector('[data-dab-manual-stations]');
            if (stationsEl) {
                stationsEl.innerHTML = this._stationsSectionHtml(status, null);
                this._afterStationsRender(stationsEl);
            }
            return;
        }

        // tab is a channel code
        el.innerHTML = this._stationsSectionHtml(status, tab);
        this._afterStationsRender(el);
    }

    // forChannel: null means "show whatever is currently tuned" (the
    // Manual tab, which has no single channel identity of its own); a
    // channel code means "only show if that's the one actually tuned" --
    // otherwise browsing this tab is safe (no side effect) and shows a
    // Scan prompt instead of silently interrupting the current station.
    _stationsSectionHtml(status, forChannel) {
        const isActiveChannel = !forChannel || (status && status.running && status.channel === forChannel);

        if (forChannel && !isActiveChannel) {
            return `
                <div class="dab-scan-prompt">
                    <div class="pager-log__empty">Not currently tuned to ${this._esc(forChannel)}.</div>
                    <button type="button" class="terminal-button" data-dab-scan-channel="${this._esc(forChannel)}">Scan ${this._esc(forChannel)}</button>
                    <div class="dab-scan-note">Stops the current station and retunes to this channel.</div>
                </div>
            `;
        }

        if (!status || !status.running) {
            return '<div class="pager-log__empty">Not tuned. Pick a channel above to scan for stations.</div>';
        }

        const rescan = forChannel
            ? `<div class="dab-chan-actions"><button type="button" class="terminal-button" data-dab-scan-channel="${this._esc(forChannel)}">Rescan</button></div>`
            : '';
        const services = status.services || [];
        if (!services.length) {
            return rescan + '<div class="pager-log__empty">Scanning… stations appear as they decode.</div>';
        }
        return rescan + `<div class="dab-stations" data-dab-stations>${services.map((s) => this._stationRowHtml(s, status.channel)).join('')}</div>`;
    }

    // Marquee for any label/DLS text that overflows -- mirrors the Radio
    // tab's RDS scroll logic (lsn-station__scroll/.scroll).
    _afterStationsRender(container) {
        container.querySelectorAll('[data-dab-scrolltext]').forEach((textEl) => {
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
            return '<div class="pager-log__empty">No favorites yet — click the ☆ on any station to pin it here.</div>';
        }
        return `<div class="dab-stations">${favs.map((f, i) => this._favRowHtml(f, i)).join('')}</div>`;
    }

    // Same row shape as a channel tab's station list (star, scrolling
    // text, Play/Stop) so Favorites reads as just another station list
    // instead of a different-looking chip grid. A favorite only stores
    // {channel, sid, label} in localStorage -- no RadioText/DLS, since
    // that changes constantly and can't be saved statically -- but if
    // this favorite happens to be on the channel currently tuned, its
    // live label+DLS is already sitting in status.services, same data
    // a channel tab's own station row uses.
    _favRowHtml(f, i) {
        const esc = this._esc.bind(this);
        const playing = this._playingSid === f.sid;
        const status = this._lastStatus;
        const live = (status && status.running && status.channel === f.channel)
            ? (status.services || []).find((s) => s.sid === f.sid)
            : null;
        const label = live ? live.label : f.label;
        const dls = live ? live.dls : '';
        const text = (dls && dls !== label) ? `${f.channel} · ${label} — ${dls}` : `${f.channel} · ${label}`;
        return `
            <div class="dab-station-row">
                <span class="lsn-fav on" data-dab-fav-remove="${i}" title="Remove favorite">★</span>
                <span class="lsn-station__scroll dab-station-row__text">
                    <span class="lsn-station__text" data-dab-scrolltext>${esc(text)}</span>
                </span>
                <button type="button" class="terminal-button${playing ? ' dab-station-row__playing' : ''}"
                        data-dab-fav-play="${i}">${playing ? 'Stop' : 'Play'}</button>
            </div>
        `;
    }

    /** Jump straight to a favorite: tune its channel if not already there
     * (or the station isn't decoded yet), then auto-play the moment its
     * sid shows up in the progressively-filled station list. */
    async _playFavorite(fav) {
        // Switch the view to this favorite's channel tab so its station
        // list (and the played station's Stop state) is actually visible,
        // rather than leaving the user looking at the Favorites tab while
        // a different channel tunes in the background.
        this._activeChannelTab = fav.channel;
        const root = this._root;
        if (root) {
            root.querySelectorAll('[data-chantab]').forEach((btn) => {
                btn.classList.toggle('lsn-tabbar__btn--active', btn.dataset.chantab === fav.channel);
            });
        }
        const st = this._lastStatus;
        if (st && st.running && st.channel === fav.channel) {
            const found = (st.services || []).find((s) => s.sid === fav.sid);
            if (found) { this._playOrStop(fav.sid); return; }
            this._renderChanTabContent();
            return;
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

        root.querySelectorAll('[data-chantab]').forEach((btn) => {
            const isChannelCode = DAB_CHANNEL_PRESETS.some((c) => c.channel === btn.dataset.chantab);
            if (isChannelCode) btn.disabled = !!busyOwner;
        });

        this._setLeds({ onair: status.running, tuning: this._tuning });

        // Small tag shows channel + a friendly name -- our own curated
        // name if this is a known preset, else whatever real ensemble
        // label welle-cli decoded (some, like 11C's literal "DAB+" or
        // 9C's literal "9C", aren't descriptive at all, so the curated
        // name is preferred whenever we have one). The big VFD slot is
        // reserved for the now-playing station/RadioText instead -- that
        // space was originally sized for the Radio tab's frequency
        // digits, but a station name matters more to a listener here
        // than which channel it happens to be on.
        const chanTagEl = root.querySelector('[data-dab-chantag]');
        if (chanTagEl) {
            if (!status.running) {
                chanTagEl.textContent = '';
            } else {
                const preset = DAB_CHANNEL_PRESETS.find((c) => c.channel === status.channel);
                const name = preset ? preset.name : status.ensemble_label;
                chanTagEl.textContent = name ? `${status.channel} · ${name}` : (status.channel || '');
            }
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
        this._renderChanTabContent();
        this._resolvePendingPlay(status);
    }

    // Drives the big VFD "now playing" headline + SNR/PTY pills from
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
        if (el) {
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
        // Favorites tab's own Play/Stop buttons -- same playingSid check,
        // different markup/attributes (data-dab-fav-play, not
        // data-dab-play), so it needs its own pass.
        const favBar = this._root && this._root.querySelector('[data-dab-favbar]');
        if (favBar) {
            favBar.querySelectorAll('[data-dab-fav-play]').forEach((btn) => {
                const fav = this._loadFavs()[parseInt(btn.dataset.dabFavPlay, 10)];
                const playing = !!fav && this._playingSid === fav.sid;
                btn.textContent = playing ? 'Stop' : 'Play';
                btn.classList.toggle('dab-station-row__playing', playing);
            });
        }
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
