/**
 * DAB/DAB+ tab content -- pick a channel/ensemble, wait for welle-cli to
 * lock and decode its station list, then play one. Two-level model
 * (channel -> station) unlike Radio/P2000/Pagers/POCSAG/RTL433's flat
 * preset list, since a DAB+ multiplex carries several stations at once --
 * see src/audio/dab_listener.py.
 */
const _DAB_DONGLE_OWNER_LABELS = {
    radio: 'Radio', p2000: 'P2000', pagers: 'Pagers', pocsag: 'POCSAG', rtl433: 'RTL433', dab: 'DAB+',
};

// Amsterdam-area DAB+ ensembles (NL national/regional multiplexes).
const DAB_CHANNEL_PRESETS = [
    { channel: '12C', label: '12C · NPO (national)' },
    { channel: '11C', label: '11C · Commercial nationals' },
    { channel: '7D', label: '7D · MTVNL' },
    { channel: '9C', label: '9C · Amsterdam/regional' },
    { channel: '11A', label: '11A · Regional' },
];

class DabPanel {
    constructor() {
        this._root = null;
        this._statusTimer = null;
        this._playingSid = null;
        this._lastStatus = null;
        // A favorite tune-and-play jumps to a channel that may not be the
        // one currently running, then has to wait for that specific
        // station's sid to show up in the progressively-decoded services
        // list before it can actually play -- these track that wait.
        this._pendingPlay = null;      // { channel, sid }
        this._pendingPlayAt = 0;
    }

    mount(root) {
        this._root = root;
        root.innerHTML = `
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header">
                        <span>DAB+</span>
                        <div class="pager-status" data-dab-status>
                            <span class="pager-status__dot" data-dab-dot></span>
                            <span data-dab-status-text>idle</span>
                        </div>
                    </div>
                    <div class="panel__body">
                        <div class="dab-favbar" data-dab-favbar>${this._renderFavBar()}</div>
                        <div class="dab-channels" data-dab-channels>
                            ${DAB_CHANNEL_PRESETS.map((c) => `
                                <button type="button" class="terminal-button" data-dab-channel="${c.channel}">${c.label}</button>
                            `).join('')}
                        </div>
                        <div class="dab-ensemble" data-dab-ensemble style="display:none">
                            <span data-dab-ensemble-label></span>
                            <span class="dab-snr" data-dab-snr></span>
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
            <audio id="dab-audio" style="display:none"></audio>
        `;
        root.querySelector('[data-dab-channels]').addEventListener('click', (ev) => {
            const btn = ev.target.closest('[data-dab-channel]');
            if (btn && !btn.disabled) { this._pendingPlay = null; this._tune(btn.dataset.dabChannel); }
        });
        root.querySelector('[data-dab-stop]').addEventListener('click', () => this._stopEnsemble());
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

    async _tune(channel) {
        this._setStatus(false, `tuning ${channel}…`);
        try {
            const r = await fetch('/api/dab/tune', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel }),
            });
            if (!r.ok) {
                const detail = (await r.json().catch(() => ({}))).detail;
                this._setStatus(false, detail || `tune failed (${r.status})`);
                return;
            }
            this._render(await r.json());
        } catch (err) {
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
            audio.pause();
            audio.removeAttribute('src');
            this._playingSid = null;
        } else {
            audio.src = `/api/dab/stream/${encodeURIComponent(sid)}?t=${Date.now()}`;
            audio.play().catch(() => { /* user gesture (click) already present */ });
            this._playingSid = sid;
        }
        this._repaintStationButtons();
    }

    _stopAudio() {
        const audio = document.getElementById('dab-audio');
        if (audio) { audio.pause(); audio.removeAttribute('src'); }
        this._playingSid = null;
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

        const ensembleEl = root.querySelector('[data-dab-ensemble]');
        if (ensembleEl) ensembleEl.style.display = status.running ? '' : 'none';
        const labelEl = root.querySelector('[data-dab-ensemble-label]');
        if (labelEl) {
            labelEl.textContent = status.ensemble_label
                ? `${status.ensemble_label} (${status.channel})`
                : `${status.channel || ''} — scanning…`;
        }
        const snrEl = root.querySelector('[data-dab-snr]');
        if (snrEl) snrEl.textContent = status.running ? `SNR ${Number(status.snr).toFixed(1)} dB` : '';

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

        this._renderStations(status.services || [], status.running, status.channel);
        this._resolvePendingPlay(status);
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
            dot.classList.toggle('pager-status__dot--on', !!running);
            dot.classList.toggle('pager-status__dot--busy', !!busy);
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
