/**
 * Reticulum Dashboard -- a standalone, live-only companion page to the
 * reticulum plugin's own Peers/Messages/Settings page.
 *
 * Born from a real gap: a box with only Reticulum configured (no
 * concentrator/serial/MeshCore) shows a completely empty core Dashboard --
 * "NODES DISCOVERED 0/0", an empty map, an empty packet table -- even
 * though Reticulum is clearly alive (peers, live announces). The core
 * Dashboard's map/packet-table/stat-cards are built around the RF
 * capture pipeline's data shape (lat/lon nodes, RSSI/SNR/hop-count
 * packets); Reticulum deliberately produces zero packets in that
 * pipeline (see memory/plugin-reticulum.md), so piping its data into
 * those exact widgets would mean faking fields that don't exist. This
 * page instead reuses the core Dashboard's OWN markup/classes verbatim
 * (main.dashboard, .dashboard__stats/.dashboard__main/.dashboard__map/
 * .dashboard__side/.dashboard__feed, .panel/.panel__header/.panel__body --
 * see frontend/index.html's `data-section="dashboard"` section for the
 * original) -- fed from Reticulum's own shape instead of RF's:
 *   - map          -> located telemetry peers (Sideband-style LXMF
 *                     telemetry frames with lat/lon), not RF nodes
 *   - "nodes" list -> the peer roster (right column)
 *   - live table   -> the announce ticker (bottom, full width)
 *
 * An earlier version of this page used its own hand-rolled .rtd-grid/
 * .rtd-panel classes approximating the same look. That was the wrong
 * call -- two real, separate bugs came out of the gap between "looks
 * similar" and "is the real thing" (a `.panel{height:100%}` assumption
 * needing the exact fixed-height shell only .dashboard provides, and
 * a self-inflicted CSS comment bug that silently dropped the grid rule
 * entirely -- see memory/plugin-reticulum.md). Reusing the actual classes
 * removes that whole class of drift.
 *
 * Deliberately its own plugin (not a tab on the reticulum plugin's page):
 * the manifest only supports one [sidebar] entry per plugin, so a second
 * nav item needs a second plugin -- see plugins/apps/hello-world for the
 * same minimal "sidebar" pattern this one follows, and `requires =
 * "reticulum"` in plugin.toml for how the dependency on it is declared/
 * enforced. No new backend routes: reads the reticulum plugin's
 * already-public /api/reticulum/{status,peers,announces,telemetry/peers}
 * + /api/messages/conversations, and listens on the shared dashboard
 * WebSocket (window.concentratorWS) for the same "reticulum_announce"/
 * "reticulum_peer"/"reticulum_telemetry" broadcasts the reticulum
 * plugin's own page already uses. If reticulum isn't enabled, those
 * fetches just fail and the page sits in its empty state -- no crash, no
 * special-casing needed (same "fails open" shape used throughout this
 * app).
 *
 * The live ticker reuses the core dashboard's own new-row flash
 * (.packet-row--new / @keyframes packetFlash in frontend/css/dashboard.css,
 * loaded globally) rather than inventing a new animation -- same "cool,
 * data flowing through" effect the live PACKETS table gives RF users,
 * for Reticulum users instead. The telemetry map is a second, independent
 * Leaflet instance (own markers, not the core dashboard's NodeMap, which
 * is fed from the RF nodes table Reticulum peers aren't in) -- same
 * approach as reticulum_panel.js's own Telemetry tab map, whose CSS is
 * copied into reticulum_dashboard.css (see that file's header note on why
 * it can't just be linked from here).
 */

// Ring-buffer cap for the ticker's DOM rows. The reticulum plugin's own
// Activity tab keeps 200 (matches its backend ring buffer); this page is a
// glanceable live view, not a searchable log, so a much smaller cap keeps
// the DOM light while still feeling continuously "alive".
const RTD_TICKER_LIMIT = 60;

// Peers list (right column) cap -- a glanceable "who's around" readout,
// not the full sortable/searchable table the Reticulum page's Peers tab
// already is. The API returns last_seen DESC, so this keeps the most
// recently active peers visible without an unbounded DOM list.
const RTD_PEER_LIST_LIMIT = 150;

// Exact copy of reticulum_panel.js's own RT_ASPECT_BADGES -- kept local
// rather than shared, matching this codebase's existing pattern of small
// self-contained plugin frontend files (e.g. reticulum_settings_tab.js
// has its own toast helper rather than importing reticulum_panel.js's).
const RTD_ASPECT_BADGES = {
    'lxmf.delivery': 'mt-badge--text',
    'lxmf.propagation': 'mt-badge--routing',
    'nomadnetwork.node': 'mt-badge--nodeinfo',
    'call.audio': 'mt-badge--routing',
};

/**
 * A read-only "quick view" for a NomadNet node -- not the Reticulum
 * page's own Browse tab (node-picker dropdown, favourites, form-field
 * submission, file downloads). Deliberately smaller in that one way, but
 * still a real little browser: address bar, back/forward/reload, click a
 * link to navigate. Reuses `.pdm-overlay`/`.pdm-modal--wide`
 * (frontend/css/packet_detail_modal.css, core, already loaded globally --
 * the exact same chrome ReticulumAnnounceModal above uses),
 * `window.MicronParser`, and the same dark "BBS terminal" page styling
 * the Browse tab's own `.rt-nomad__page` uses (reticulum_dashboard.css's
 * `.rtd-browse-modal .pdm-modal__body` rules -- copied, not reused, same
 * cross-plugin-asset reason as the telemetry-map CSS above). Nav wiring
 * mirrors reticulum_nomad.js's own `_go`/`_history_go`/`_splitAddr`
 * almost exactly, just without its node-picker/favourites/form-field
 * pieces.
 *
 * Local to this page (not exposed on window) -- it isn't a shape the
 * Reticulum page itself has any use for.
 */
class ReticulumQuickBrowseModal {
    constructor() {
        this._overlay = null;
        this._currentHash = null;
        this._history = []; // [{hash, path}], newest at the end
        this._historyIdx = -1;
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    open(hash, label) {
        this.close();
        this._history = [];
        this._historyIdx = -1;

        const overlay = document.createElement('div');
        overlay.className = 'pdm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Browse node');
        overlay.addEventListener('click', () => this.close());

        const modal = document.createElement('div');
        modal.className = 'pdm-modal pdm-modal--wide rtd-browse-modal';
        modal.addEventListener('click', (e) => e.stopPropagation());
        modal.innerHTML = `
            <header class="pdm-modal__header">
                <div>
                    <h2 class="pdm-modal__title"></h2>
                </div>
                <button type="button" class="pdm-modal__close" aria-label="Close">&times;</button>
            </header>
            <div class="rtd-browse-toolbar">
                <button type="button" class="terminal-button" data-qb-back title="Back" disabled>&larr;</button>
                <button type="button" class="terminal-button" data-qb-forward title="Forward" disabled>&rarr;</button>
                <button type="button" class="terminal-button" data-qb-reload title="Reload" disabled>&#x21bb;</button>
                <input type="text" class="cfg-field__input rtd-browse-toolbar__addr" data-qb-addr
                       autocomplete="off" spellcheck="false" aria-label="Node address">
                <button type="button" class="terminal-button" data-qb-go>Go</button>
            </div>
            <div class="pdm-modal__body"></div>
        `;
        modal.querySelector('.pdm-modal__title').textContent = label || hash;
        modal.querySelector('.pdm-modal__close').addEventListener('click', () => this.close());
        modal.querySelector('.pdm-modal__body').addEventListener('click', (e) => {
            const a = e.target.closest('a[data-nomad-url]');
            if (!a) return;
            e.preventDefault();
            this._followLink(a);
        });

        this._addrEl = modal.querySelector('[data-qb-addr]');
        this._backBtn = modal.querySelector('[data-qb-back]');
        this._fwdBtn = modal.querySelector('[data-qb-forward]');
        this._reloadBtn = modal.querySelector('[data-qb-reload]');
        modal.querySelector('[data-qb-go]').addEventListener('click', () => this._goFromAddr());
        this._addrEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this._goFromAddr(); }
        });
        this._backBtn.addEventListener('click', () => this._historyGo(-1));
        this._fwdBtn.addEventListener('click', () => this._historyGo(1));
        this._reloadBtn.addEventListener('click', () => {
            const e = this._history[this._historyIdx];
            if (e) this._fetch(e.hash, e.path, false);
        });

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;
        this._currentHash = hash;
        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.pdm-modal__close').focus();
        this._go(hash, '/page/index.mu');
    }

    _goFromAddr() {
        const raw = (this._addrEl?.value || '').trim();
        if (!raw) return;
        const { hash, path } = this._splitAddr(raw, this._currentHash);
        if (!hash) return;
        this._go(hash, path);
    }

    _go(hash, path) {
        this._fetch(hash, path, true);
    }

    _historyGo(delta) {
        const next = this._historyIdx + delta;
        if (next < 0 || next >= this._history.length) return;
        this._historyIdx = next;
        const e = this._history[next];
        this._fetch(e.hash, e.path, false);
    }

    async _fetch(hash, path, pushHistory) {
        if (!this._overlay) return;
        if (this._addrEl) this._addrEl.value = `${hash}:${path}`;
        const bodyEl = this._overlay.querySelector('.pdm-modal__body');
        if (bodyEl) bodyEl.innerHTML = '<p class="lw-panel__limit">Loading…</p>';
        try {
            const r = await fetch('/api/reticulum/nomad/page', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ destination_hash: hash, path, field_data: null }),
            });
            const data = await r.json().catch(() => ({}));
            if (!this._overlay) return; // closed while the fetch was in flight
            if (!r.ok || !data.ok) {
                if (bodyEl) bodyEl.textContent = data.error || `Failed (HTTP ${r.status})`;
                return;
            }
            this._currentHash = hash;
            if (bodyEl) {
                bodyEl.textContent = '';
                if (window.MicronParser) {
                    bodyEl.appendChild(new window.MicronParser(true).parseToHtml(data.content || ''));
                } else {
                    bodyEl.textContent = data.content || ''; // parser missing -- show raw source
                }
            }
            if (pushHistory) {
                this._history = this._history.slice(0, this._historyIdx + 1);
                this._history.push({ hash, path });
                this._historyIdx = this._history.length - 1;
            }
            this._syncNav();
        } catch (e) {
            if (bodyEl) bodyEl.textContent = `Network error: ${e.message}`;
        }
    }

    _syncNav() {
        if (this._backBtn) this._backBtn.disabled = this._historyIdx <= 0;
        if (this._fwdBtn) this._fwdBtn.disabled = this._historyIdx >= this._history.length - 1;
        if (this._reloadBtn) this._reloadBtn.disabled = this._historyIdx < 0;
    }

    /** Simplified version of reticulum_nomad.js's own _followLink/
     * _splitAddr -- no form-field submission (this modal is read-only,
     * not the full Browse tab) and no `/file/` downloads; history
     * back/forward/reload and the address bar otherwise work the same
     * way. An external http(s) link still opens a normal browser tab
     * rather than erroring on a non-Reticulum address. */
    _followLink(a) {
        let addr = (a.dataset.nomadUrl || '').split('`')[0]; // drop backtick form-vars, unsupported here
        addr = addr.replace(/^nomadnetwork:\/\//, '');
        if (/^https?:\/\//i.test(addr)) {
            window.open(addr, '_blank', 'noopener');
            return;
        }
        const { hash, path } = this._splitAddr(addr, this._currentHash);
        if (!hash || path.startsWith('/file/')) return;
        this._go(hash, path);
    }

    /** "<hash>:/page/x.mu" -> {hash, path}. A bare "/page/x.mu" or
     * ":/page/x.mu" resolves against the current node -- same shortcuts
     * reticulum_nomad.js's own _splitAddr offers. */
    _splitAddr(raw, currentHash) {
        raw = raw.replace(/^nomadnetwork:\/\//, '');
        if (raw.startsWith(':')) return { hash: currentHash || '', path: raw.slice(1) || '/page/index.mu' };
        if (raw.startsWith('/')) return { hash: currentHash || '', path: raw };
        const idx = raw.indexOf(':');
        if (idx === -1) return { hash: raw, path: '/page/index.mu' };
        return { hash: raw.slice(0, idx), path: raw.slice(idx + 1) || '/page/index.mu' };
    }

    close() {
        if (this._overlay) {
            this._overlay.remove();
            this._overlay = null;
        }
        document.removeEventListener('keydown', this._onKeyDown);
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') this.close();
    }
}

class ReticulumDashboard {
    constructor() {
        this._root = null;
        this._refreshTimer = null;
        this._peers = [];
        this._telemetry = [];
        this._homeLat = null;
        this._homeLon = null;
        this._homeMarker = null;
        this._announces = []; // mirrors the ticker's DOM rows -- needed to
        // look up an entry on click (row click-through -> detail panels)
        this._peerSearchQuery = '';
        this._peerDrawer = null;
        this._announceModal = null;
        this._quickBrowse = new ReticulumQuickBrowseModal();
        // Same localStorage key node_map.js's own basemap toggle uses --
        // deliberately shared, not a separate preference: "I like a light
        // map" is one setting the user expects to carry across every map
        // in the app, not something to set twice.
        this._basemapLight = this._loadBasemapPref();
        this._onWsAnnounce = this._onWsAnnounce.bind(this);
        this._onWsPeer = this._onWsPeer.bind(this);
        this._onWsTelemetry = this._onWsTelemetry.bind(this);
    }

    mount(rootEl) {
        this._root = rootEl;
        // Literal core Dashboard markup (main.dashboard > .dashboard__stats
        // + .dashboard__main [.dashboard__map + .dashboard__side] +
        // .dashboard__feed, .panel/.panel__header/.panel__body throughout)
        // -- see this file's header comment for why: a hand-rolled
        // approximation (.rtd-grid/.rtd-panel, an earlier version of this
        // file) kept drifting from the real thing's sizing behaviour.
        // Using the actual classes means this page gets the exact same
        // fixed-height panel shell, internal scrolling, and column split
        // the core Dashboard already has proven, for free.
        rootEl.innerHTML = `
            <main class="dashboard">
                <section class="dashboard__stats">
                    <div class="stat-card">
                        <div class="stat-card__label">Status</div>
                        <div class="stat-card__value" id="rtd-stat-status">--</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-card__label">Known Peers</div>
                        <div class="stat-card__value" id="rtd-stat-peers">--</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-card__label">People</div>
                        <div class="stat-card__value" id="rtd-stat-people">--</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-card__label">Infrastructure</div>
                        <div class="stat-card__value" id="rtd-stat-infra">--</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-card__label">Conversations</div>
                        <div class="stat-card__value" id="rtd-stat-conversations">--</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-card__label">You</div>
                        <div class="stat-card__value" id="rtd-own-address" style="font-size:0.75rem">--</div>
                    </div>
                </section>

                <div class="dashboard__main">
                    <section class="dashboard__map">
                        <div class="panel">
                            <div class="panel__header">
                                Telemetry Map
                                <div class="panel__header-actions">
                                    <button id="rtd-map-basemap-btn" class="map-expand-btn" type="button" title="Darken the map"></button>
                                    <button id="rtd-map-home-btn" class="map-expand-btn" type="button" title="Center on home">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14" aria-hidden="true">
                                            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                                            <polyline points="9 22 9 12 15 12 15 22"/>
                                        </svg>
                                    </button>
                                    <button id="rtd-map-expand-btn" class="map-expand-btn" type="button" title="Expand map">⤢</button>
                                </div>
                            </div>
                            <div class="panel__body" style="position:relative">
                                <div id="rtd-telemetry-map" class="rt-telemetry-map map-container" hidden></div>
                                <p class="lw-empty" id="rtd-telemetry-empty">
                                    No located peers yet -- most Reticulum
                                    peers don't report one (Sideband-style
                                    LXMF telemetry).
                                </p>
                            </div>
                        </div>
                    </section>

                    <section class="dashboard__side">
                        <div class="panel panel--nodes">
                            <div class="panel__header">
                                <span>Peers</span>
                                <div class="node-search-wrap">
                                    <input type="search" id="rtd-peer-search" class="node-search"
                                           placeholder="Search..." autocomplete="off" spellcheck="false">
                                </div>
                            </div>
                            <div class="panel__body" id="rtd-peers-list"></div>
                            <p class="lw-empty" id="rtd-peers-empty" style="display:none">
                                No Reticulum peers heard yet.
                            </p>
                        </div>
                    </section>
                </div>

                <section class="dashboard__feed">
                    <div class="panel">
                        <div class="panel__header">
                            <span>Live Activity</span>
                        </div>
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--rt-announces">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-id">
                                    <col class="col-type">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Display name</th>
                                        <th>Destination</th>
                                        <th>Aspect</th>
                                    </tr>
                                </thead>
                                <tbody id="rtd-ticker-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rtd-ticker-empty">
                                Waiting for the first announce…
                            </p>
                        </div>
                    </div>
                </section>
            </main>
        `;

        this._q('#rtd-peer-search')?.addEventListener('input', (e) => {
            this._peerSearchQuery = e.target.value.trim().toLowerCase();
            this._renderPeersList();
        });

        this._syncBasemapBtn(this._basemapLight);
        this._q('#rtd-map-basemap-btn')?.addEventListener('click', () => this._toggleBasemap());
        this._q('#rtd-map-home-btn')?.addEventListener('click', () => this._centerOnHome());
        this._q('#rtd-map-expand-btn')?.addEventListener('click', () => this._toggleExpand());

        // Same detail drawer/modal the Reticulum page's own Peers/Activity
        // rows open (plugins/apps/reticulum/frontend/reticulum_detail_
        // panels.js, exposed as window.ReticulumPeerDrawer/
        // ReticulumAnnounceModal -- reticulum is a hard `requires` of this
        // plugin, so its scripts are always loaded alongside this page's
        // own). Constructed lazily here rather than referenced only at
        // click time so a missing script (reticulum somehow not loaded)
        // fails visibly once at mount instead of silently on every click.
        if (window.ReticulumPeerDrawer) this._peerDrawer = new window.ReticulumPeerDrawer();
        if (window.ReticulumAnnounceModal) this._announceModal = new window.ReticulumAnnounceModal();

        this._q('#rtd-peers-list')?.addEventListener('click', (e) => {
            const browseBtn = e.target.closest('[data-browse]');
            if (browseBtn) {
                const peer = this._peers.find((p) => p.destination_hash === browseBtn.dataset.browse);
                if (peer) this._quickBrowse.open(peer.destination_hash, peer.display_name);
                return;
            }
            const row = e.target.closest('[data-hash]');
            if (!row) return;
            const peer = this._peers.find((p) => p.destination_hash === row.dataset.hash);
            if (peer) this._openPeerDrawer(peer);
        });
        this._q('#rtd-ticker-tbody')?.addEventListener('click', (e) => {
            const tr = e.target.closest('tr[data-rt-ts]');
            if (!tr) return;
            const entry = this._announces.find(
                (a) => a.ts === tr.dataset.rtTs && a.destination_hash === tr.dataset.rtHash,
            );
            if (entry) this._openAnnounceModal(entry);
        });
    }

    /** Peer-row click -> the same right-side drawer the Reticulum page's
     * own Peers tab opens. Read-only here -- no contact editing / send-
     * message actions, this page is a glanceable companion, not the full
     * management page -- but "view announce" and, for a nomadnetwork.node
     * peer, "Browse" both still work, matching the real thing's
     * cross-links (Browse opens this page's own quick-view modal, not
     * the Reticulum page's full Browse tab). */
    _openPeerDrawer(peer) {
        if (!this._peerDrawer) return;
        const recent = this._announces.filter((a) => a.destination_hash === peer.destination_hash);
        this._peerDrawer.open(peer, recent, {
            onViewAnnounce: (entry) => this._openAnnounceModal(entry),
            onBrowse: peer.aspect === 'nomadnetwork.node'
                ? (hash) => this._quickBrowse.open(hash, peer.display_name)
                : undefined,
        });
    }

    /** Activity-row click -> the same center modal the Reticulum page's
     * own Activity tab opens. */
    _openAnnounceModal(entry) {
        if (!this._announceModal) return;
        const peer = this._peers.find((p) => p.destination_hash === entry.destination_hash);
        this._announceModal.show(entry, {
            knownPeer: !!peer,
            onViewPeer: () => { if (peer) this._openPeerDrawer(peer); },
        });
    }

    /** Called by the router (via registerSidebarPage) when the page becomes active. */
    show() {
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 20_000);
        if (window.concentratorWS) {
            window.concentratorWS.on('reticulum_announce', this._onWsAnnounce);
            window.concentratorWS.on('reticulum_peer', this._onWsPeer);
            window.concentratorWS.on('reticulum_telemetry', this._onWsTelemetry);
        }
    }

    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
        // ConcentratorWebSocket has no unsubscribe primitive -- re-adding
        // the same bound callback on the next show() just means a brief
        // doubled-up refresh, not a real leak (same note as
        // reticulum_panel.js's own show()/hide()).
    }

    async _load() {
        await Promise.all([
            this._loadStatus(), this._loadPeers(), this._loadConversationCount(),
            this._loadTickerSeed(), this._loadTelemetry(), this._loadHomeLocation(),
        ]);
    }

    /** The device's own configured location (Configuration -> Identity),
     * same field node_map.js's centerOnHome() reads -- device-level, not
     * RF-specific, so it applies here too even though Reticulum peers
     * have no relation to it. Loaded once; a mid-session location change
     * needs a page reload to pick up, same as every other page here. */
    async _loadHomeLocation() {
        if (this._homeLat != null) return;
        try {
            const r = await fetch('/api/device', { credentials: 'same-origin' });
            if (!r.ok) return;
            const device = await r.json();
            if (device.latitude == null || device.longitude == null) return;
            this._homeLat = device.latitude;
            this._homeLon = device.longitude;
            this._renderHomeMarker();
        } catch (_) {}
    }

    async _loadStatus() {
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (!r.ok) return;
            const s = await r.json();
            this._setText('rtd-stat-status', s.running ? 'Running' : (s.available ? 'Stopped' : 'Unavailable'));
            this._setText('rtd-own-address', s.own_address || '--');
        } catch (_) {}
    }

    async _loadPeers() {
        try {
            const r = await fetch('/api/reticulum/peers', { credentials: 'same-origin' });
            if (!r.ok) return;
            this._peers = await r.json();
            this._setText('rtd-stat-peers', this._peers.length);
            // "People" = actual message recipients (lxmf.delivery);
            // everything else is network infrastructure -- same split
            // the reticulum plugin's own page applies.
            const peopleCount = this._peers.filter((p) => p.aspect === 'lxmf.delivery').length;
            this._setText('rtd-stat-people', peopleCount);
            this._setText('rtd-stat-infra', this._peers.length - peopleCount);
            this._renderPeersList();
        } catch (_) {}
    }

    async _loadConversationCount() {
        try {
            const r = await fetch('/api/messages/conversations', { credentials: 'same-origin' });
            if (!r.ok) return;
            const conversations = (await r.json()).filter((c) => c.protocol === 'reticulum');
            this._setText('rtd-stat-conversations', conversations.length);
        } catch (_) {}
    }

    /** Seed the ticker with recent history on first load only -- live
     * updates after that come from WS announces, prepended one row at a
     * time so the flash animation actually plays per-row. */
    async _loadTickerSeed() {
        if (this._seeded) return;
        try {
            const r = await fetch('/api/reticulum/announces', { credentials: 'same-origin' });
            if (!r.ok) return;
            const announces = await r.json();
            this._seeded = true;
            const tbody = this._q('#rtd-ticker-tbody');
            const empty = this._q('#rtd-ticker-empty');
            if (!tbody) return;
            const rows = announces.slice(0, RTD_TICKER_LIMIT);
            this._announces = rows;
            if (!rows.length) {
                if (empty) empty.style.display = '';
                return;
            }
            if (empty) empty.style.display = 'none';
            tbody.innerHTML = rows.map((a) => this._rowHtml(a)).join('');
        } catch (_) {}
    }

    async _loadTelemetry() {
        try {
            const r = await fetch('/api/reticulum/telemetry/peers', { credentials: 'same-origin' });
            if (!r.ok) return;
            this._telemetry = await r.json();
            this._renderTelemetryMap();
        } catch (_) {}
    }

    // --- Peers list (right column) ----------------------------------------

    _renderPeersList() {
        const list = this._q('#rtd-peers-list');
        const empty = this._q('#rtd-peers-empty');
        if (!list) return;
        if (!this._peers.length) {
            list.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        const q = this._peerSearchQuery;
        const filtered = q
            ? this._peers.filter((p) =>
                (p.display_name || '').toLowerCase().includes(q)
                || p.destination_hash.toLowerCase().includes(q))
            : this._peers;
        if (!filtered.length) {
            list.innerHTML = '';
            if (empty) { empty.style.display = ''; empty.textContent = 'No peers match that search.'; }
            return;
        }
        if (empty) empty.style.display = 'none';
        // Already last_seen DESC from the API -- same assumption
        // reticulum_panel.js's own Peers tab relies on.
        list.innerHTML = filtered.slice(0, RTD_PEER_LIST_LIMIT).map((p) => `
            <div class="rtd-peer-row" data-hash="${this._esc(p.destination_hash)}" title="${this._esc(p.destination_hash)}">
                <span class="rtd-peer-row__name">${this._esc(p.display_name || p.destination_hash.slice(0, 12) + '…')}</span>
                ${this._fmtAspect(p.aspect)}${
                    p.aspect === 'nomadnetwork.node'
                        ? ` <button type="button" class="lw-link-btn" data-browse="${this._esc(p.destination_hash)}">Browse</button>`
                        : ''
                }
                <span class="rtd-peer-row__time">${this._fmtTime(p.last_seen)}</span>
            </div>
        `).join('');
    }

    // --- Telemetry map -----------------------------------------------------

    /** Lightweight Leaflet map of telemetry peers that reported a location,
     * plus the device's own home location (see _renderHomeMarker). Own
     * markers only -- not the core dashboard's NodeMap (that's fed from
     * the RF nodes table, which Reticulum telemetry peers aren't in).
     * Ported from reticulum_panel.js's own Telemetry tab map. */
    _renderTelemetryMap() {
        const el = this._q('#rtd-telemetry-map');
        const empty = this._q('#rtd-telemetry-empty');
        if (!el || typeof L === 'undefined') return;
        const located = this._telemetry.filter((t) => t.latitude != null && t.longitude != null);
        const hasHome = this._homeLat != null && this._homeLon != null;
        // Show the map whenever there's ANYTHING to put on it -- located
        // peers or just home -- not only when peers exist like before
        // home was added; otherwise a box with no located peers yet never
        // shows its own home pin at all.
        if (!located.length && !hasHome) {
            el.hidden = true;
            if (empty) empty.style.display = '';
            return;
        }
        const wasHidden = el.hidden;
        el.hidden = false;
        if (empty) empty.style.display = 'none';

        if (!this._teleMap) {
            // Leaflet reads the container's real size when the map is
            // constructed. Measuring in the same synchronous tick as
            // unhiding it can catch a stale (zero-size) layout -- the
            // browser hasn't necessarily reflowed yet -- and Leaflet's
            // absolutely-positioned panes then lay out against that bogus
            // size, which visually reads as the map ballooning to cover
            // the whole page instead of staying inside the map panel.
            // requestAnimationFrame guarantees a real layout pass has
            // happened for the just-unhidden container first.
            requestAnimationFrame(() => this._initTelemetryMap(el, located));
            return;
        }
        this._updateTelemetryMarkers(located);
        // Also true the first time an already-built map's container goes
        // from hidden -> visible again (e.g. telemetry emptied out and
        // came back) -- same stale-size risk as above.
        if (wasHidden) requestAnimationFrame(() => this._teleMap && this._teleMap.invalidateSize());
    }

    _initTelemetryMap(el, located) {
        if (this._teleMap || el.hidden) return; // a later call may have won the race, or telemetry emptied out again
        // true, not the reticulum plugin's own Telemetry-tab false: that
        // map is a small widget embedded in a normal-scrolling page (you
        // don't want it hijacking page scroll), this map plays the core
        // Dashboard's dominant NODE MAP role instead, which is
        // scrollWheelZoom: true (node_map.js) -- same reasoning as every
        // other "match the real thing" fix in this page's history.
        this._teleMap = L.map(el, { scrollWheelZoom: true });
        const tileOpts = {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
            maxZoom: 19,
        };
        // Same shared tile source as the Dashboard/Topology maps
        // (Settings' "Dashboard map source" switch -- online OSM vs. an
        // offline-map plugin collection) -- reads live, no restart needed,
        // and this map follows it automatically rather than needing its
        // own separate setting. Synchronous fallback layer first, swapped
        // once the real source resolves: see map_tile_source.js's own
        // comment on MAP_TILE_URL_FALLBACK -- a map with zero tile layers
        // has no maxZoom yet, so anything that touches the map before the
        // fetch resolves (fitBounds below) would throw.
        let tileLayer = L.tileLayer(window.MAP_TILE_URL_FALLBACK, tileOpts).addTo(this._teleMap);
        window.getMapTileUrl().then((url) => {
            if (url && url !== window.MAP_TILE_URL_FALLBACK && this._teleMap) {
                this._teleMap.removeLayer(tileLayer);
                tileLayer = L.tileLayer(url, tileOpts).addTo(this._teleMap);
            }
        });
        this._teleMarkers = L.layerGroup().addTo(this._teleMap);
        this._renderHomeMarker(); // in case home loaded before the map existed
        this._updateTelemetryMarkers(located);
        // No peers to fit a view to -- start centered on home instead of
        // Leaflet's own default (world view), if we have one.
        if (!located.length) this._centerOnHome();
        // Belt-and-braces: re-measure once more on the following frame in
        // case the very first read still landed on a transitional layout
        // (e.g. the .dashboard__main grid columns hadn't settled their
        // widths yet).
        requestAnimationFrame(() => this._teleMap && this._teleMap.invalidateSize());
    }

    /** The device's own home location, on the map -- a distinct pin, kept
     * on its own layer (not this._teleMarkers) so peer-marker refreshes
     * never clear it. Safe to call before the map or the location exists
     * yet; whichever of _loadHomeLocation()/_initTelemetryMap() finishes
     * second is the one that actually adds it. */
    _renderHomeMarker() {
        if (!this._teleMap || this._homeLat == null || this._homeLon == null || this._homeMarker) return;
        const icon = L.divIcon({
            className: 'rtd-home-marker',
            html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                + '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
                + '<polyline points="9 22 9 12 15 12 15 22"/></svg>',
            iconSize: [26, 26],
            iconAnchor: [13, 13],
        });
        this._homeMarker = L.marker([this._homeLat, this._homeLon], { icon, zIndexOffset: 1000 })
            .bindTooltip('Home', { direction: 'top', offset: [0, -12] })
            .addTo(this._teleMap);
    }

    /** Map-header home button -- same "Center on home" the core
     * Dashboard's NODE MAP offers (node_map.js's centerOnHome()), zoom
     * level 14 to match. Home is a device-level setting (Configuration ->
     * Identity), not RF-specific, so it applies here too even though
     * Reticulum peers have no relation to it. */
    _centerOnHome() {
        if (!this._teleMap || this._homeLat == null || this._homeLon == null) return;
        this._teleMap.setView([this._homeLat, this._homeLon], 14);
    }

    _updateTelemetryMarkers(located) {
        this._teleMarkers.clearLayers();
        const bounds = [];
        located.forEach((t) => {
            const name = t.name || t.destination_hash.slice(0, 12);
            // The info line is a "·"-joined free-text string (see the
            // reticulum plugin's telemetry.py::_info_line). Split back
            // into small tags rather than one dense line.
            const tags = (t.info || '').split(' · ').filter(Boolean).map((seg) => {
                const spaceState = /^space (OPEN|CLOSED)$/.exec(seg);
                const cls = spaceState
                    ? `rt-tele-popup__tag rt-tele-popup__tag--${spaceState[1] === 'OPEN' ? 'open' : 'closed'}`
                    : 'rt-tele-popup__tag';
                return `<span class="${cls}">${this._esc(seg)}</span>`;
            }).join('');
            const popupHtml = `
                <div class="rt-tele-popup">
                    <div class="rt-tele-popup__head">
                        <span class="rt-tele-popup__name">${this._esc(name)}</span>
                        ${t.temperature_c != null ? `<span class="rt-tele-popup__temp">${t.temperature_c}°C</span>` : ''}
                    </div>
                    ${tags ? `<div class="rt-tele-popup__tags">${tags}</div>` : ''}
                </div>`;
            L.marker([t.latitude, t.longitude]).bindPopup(popupHtml).addTo(this._teleMarkers);
            bounds.push([t.latitude, t.longitude]);
        });
        this._fitTelemetryBounds();
    }

    /** Auto-frames the view on every marker refresh (not a button --
     * the panel-header home button does "center on home" instead, see
     * _centerOnHome). Recomputes from this._telemetry rather than taking
     * a parameter so it always reflects the latest fetch/WS state, not
     * whatever was current the last time markers were rebuilt. */
    _fitTelemetryBounds() {
        if (!this._teleMap) return;
        const bounds = this._telemetry
            .filter((t) => t.latitude != null && t.longitude != null)
            .map((t) => [t.latitude, t.longitude]);
        if (!bounds.length) return;
        if (bounds.length === 1) this._teleMap.setView(bounds[0], 12);
        else this._teleMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
    }

    // --- Map header actions (basemap / home / expand) -----------------------
    // Same behaviours as the core Dashboard's NODE MAP panel
    // (frontend/js/app.js's mapBasemapBtn/mapHomeBtn/mapExpandBtn wiring,
    // frontend/js/components/node_map.js's toggleBasemap/centerOnHome) --
    // reimplemented here rather than reused because node_map.js's own
    // versions are hardwired to the core map's specific #map id (both the
    // CSS filter rules and the DOM lookups), and app.js's expand handler
    // uses an unscoped `document.querySelector('.dashboard')` that would
    // grab whichever .dashboard comes first in the document, not
    // necessarily this page's own -- copying the *behaviour*, not the
    // exact code, avoids both traps. No cluster-toggle button -- located telemetry
    // peers are typically a small fraction of the peer roster, nowhere
    // near dense enough to need grouping the way RF nodes can be.

    _loadBasemapPref() {
        try {
            const v = localStorage.getItem('meshpoint.nodeMap.basemap');
            if (v === 'light') return true;
            if (v === 'dark') return false;
        } catch (_) { /* fall through */ }
        return document.documentElement.getAttribute('data-theme') === 'light';
    }

    _applyBasemap() {
        const el = this._q('#rtd-telemetry-map');
        if (!el) return;
        el.classList.toggle('map--basemap-light', this._basemapLight);
        el.classList.toggle('map--basemap-dark', !this._basemapLight);
    }

    _toggleBasemap() {
        this._basemapLight = !this._basemapLight;
        try {
            localStorage.setItem('meshpoint.nodeMap.basemap', this._basemapLight ? 'light' : 'dark');
        } catch (_) { /* best-effort */ }
        this._syncBasemapBtn(this._basemapLight);
    }

    _syncBasemapBtn(light) {
        this._applyBasemap();
        const btn = this._q('#rtd-map-basemap-btn');
        if (!btn) return;
        btn.innerHTML = window.themeGlyph ? window.themeGlyph(light ? 'moon' : 'sun', 14) : '';
        btn.title = light ? 'Darken the map' : 'Lighten the map';
    }

    _toggleExpand() {
        const dash = this._q('.dashboard');
        const btn = this._q('#rtd-map-expand-btn');
        if (!dash) return;
        const expanded = dash.classList.toggle('dashboard--map-expanded');
        if (btn) {
            btn.textContent = expanded ? '⤡' : '⤢';
            btn.title = expanded ? 'Collapse map' : 'Expand map';
        }
        setTimeout(() => this._teleMap && this._teleMap.invalidateSize(), 50);
    }

    _onWsPeer() { this._loadPeers(); }
    _onWsTelemetry() { this._loadTelemetry(); }

    _onWsAnnounce(entry) {
        if (!entry || !entry.ts) return;
        const tbody = this._q('#rtd-ticker-tbody');
        if (!tbody) return;
        const empty = this._q('#rtd-ticker-empty');
        if (empty) empty.style.display = 'none';

        this._announces.unshift(entry);
        if (this._announces.length > RTD_TICKER_LIMIT) this._announces.length = RTD_TICKER_LIMIT;

        const tr = document.createElement('tr');
        tr.className = 'lw-pkt-row packet-row--new';
        tr.dataset.rtTs = entry.ts;
        tr.dataset.rtHash = entry.destination_hash;
        tr.title = 'Click for details';
        tr.innerHTML = this._rowInner(entry);
        tr.addEventListener('animationend', () => tr.classList.remove('packet-row--new'));
        tbody.insertBefore(tr, tbody.firstChild);

        while (tbody.children.length > RTD_TICKER_LIMIT) {
            tbody.removeChild(tbody.lastChild);
        }
    }

    _rowHtml(a) {
        return `<tr class="lw-pkt-row" data-rt-ts="${this._esc(a.ts)}" data-rt-hash="${this._esc(a.destination_hash)}" title="Click for details">${this._rowInner(a)}</tr>`;
    }

    _rowInner(a) {
        return `
            <td class="lw-time">${this._fmtTime(a.ts)}</td>
            <td class="mt-name">${this._esc(a.display_name || '--')}</td>
            <td class="lw-id">${this._esc(a.destination_hash)}</td>
            <td>${this._fmtAspect(a.aspect)}</td>
        `;
    }

    _fmtAspect(aspect) {
        const cls = RTD_ASPECT_BADGES[aspect] || '';
        return `<span class="mt-badge ${cls}">${this._esc(aspect || '--')}</span>`;
    }

    _fmtTime(ts) {
        if (!ts) return '--';
        try {
            return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
        } catch (_) { return ts; }
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    _q(sel) { return this._root ? this._root.querySelector(sel) : null; }

    _setText(id, val) {
        const el = this._q(`#${id}`);
        if (el) el.textContent = val;
    }
}

window.registerSidebarPage({
    route: 'reticulum-dashboard',
    make: () => new ReticulumDashboard(),
});
