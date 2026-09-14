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
 * page instead mirrors the core Dashboard's own layout -- stat cards, a
 * map, a "nodes" list, a live table -- fed from Reticulum's own shape:
 *   - map          -> located telemetry peers (Sideband-style LXMF
 *                     telemetry frames with lat/lon), not RF nodes
 *   - nodes list   -> the peer roster (right column)
 *   - live table   -> the announce ticker (bottom, full width)
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

class ReticulumDashboard {
    constructor() {
        this._root = null;
        this._refreshTimer = null;
        this._peers = [];
        this._telemetry = [];
        this._peerSearchQuery = '';
        this._onWsAnnounce = this._onWsAnnounce.bind(this);
        this._onWsPeer = this._onWsPeer.bind(this);
        this._onWsTelemetry = this._onWsTelemetry.bind(this);
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Reticulum Dashboard</h2>
                <div class="lw-panel__actions">
                    <span class="lw-panel__limit" id="rtd-own-address"></span>
                </div>
            </header>

            <section class="lw-stats" id="rtd-stats">
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
            </section>

            <section class="rtd-grid">
                <div class="rtd-panel rtd-map-panel">
                    <div class="rtd-panel__header">
                        <h3>Telemetry map</h3>
                        <p class="lw-panel__limit">
                            Peers that reported a location (Sideband-style
                            LXMF telemetry) -- most Reticulum peers don't.
                        </p>
                    </div>
                    <div class="rtd-panel__body">
                        <div id="rtd-telemetry-map" class="rt-telemetry-map" hidden></div>
                        <p class="lw-empty" id="rtd-telemetry-empty">
                            No located peers yet.
                        </p>
                    </div>
                </div>
                <div class="rtd-panel rtd-peers-panel">
                    <div class="rtd-panel__header">
                        <h3>Peers</h3>
                        <input class="cfg-field__input" type="search" id="rtd-peer-search"
                               placeholder="Search name or hash" autocomplete="off">
                    </div>
                    <div class="rtd-panel__body">
                        <div class="rtd-peers-list" id="rtd-peers-list"></div>
                        <p class="lw-empty" id="rtd-peers-empty">
                            No Reticulum peers heard yet.
                        </p>
                    </div>
                </div>
            </section>

            <section class="lw-section">
                <div class="rtd-panel">
                    <div class="rtd-panel__header">
                        <h3>Live activity</h3>
                        <p class="lw-panel__limit">
                            Announces as they're heard, newest first -- full
                            history and peer management live on the
                            Reticulum page.
                        </p>
                    </div>
                    <div class="rtd-panel__body lw-table-wrap">
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
        `;

        this._q('#rtd-peer-search')?.addEventListener('input', (e) => {
            this._peerSearchQuery = e.target.value.trim().toLowerCase();
            this._renderPeersList();
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
            this._loadTickerSeed(), this._loadTelemetry(),
        ]);
    }

    async _loadStatus() {
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (!r.ok) return;
            const s = await r.json();
            this._setText('rtd-stat-status', s.running ? 'Running' : (s.available ? 'Stopped' : 'Unavailable'));
            const addrEl = this._q('#rtd-own-address');
            if (addrEl) addrEl.textContent = s.own_address ? `You: ${s.own_address}` : '';
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
            <div class="rtd-peer-row" title="${this._esc(p.destination_hash)}">
                <span class="rtd-peer-row__name">${this._esc(p.display_name || p.destination_hash.slice(0, 12) + '…')}</span>
                ${this._fmtAspect(p.aspect)}
                <span class="rtd-peer-row__time">${this._fmtTime(p.last_seen)}</span>
            </div>
        `).join('');
    }

    // --- Telemetry map -----------------------------------------------------

    /** Lightweight Leaflet map of telemetry peers that reported a location.
     * Own markers only -- not the core dashboard's NodeMap (that's fed
     * from the RF nodes table, which Reticulum telemetry peers aren't
     * in). Ported from reticulum_panel.js's own Telemetry tab map. */
    _renderTelemetryMap() {
        const el = this._q('#rtd-telemetry-map');
        const empty = this._q('#rtd-telemetry-empty');
        if (!el || typeof L === 'undefined') return;
        const located = this._telemetry.filter((t) => t.latitude != null && t.longitude != null);
        if (!located.length) {
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
            // the whole page instead of staying inside this ~300px box.
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
        this._teleMap = L.map(el, { scrollWheelZoom: false });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(this._teleMap);
        this._teleMarkers = L.layerGroup().addTo(this._teleMap);
        this._updateTelemetryMarkers(located);
        // Belt-and-braces: re-measure once more on the following frame in
        // case the very first read still landed on a transitional layout
        // (e.g. the .rtd-grid columns hadn't settled their widths yet).
        requestAnimationFrame(() => this._teleMap && this._teleMap.invalidateSize());
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
        if (bounds.length === 1) this._teleMap.setView(bounds[0], 12);
        else this._teleMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
    }

    _onWsPeer() { this._loadPeers(); }
    _onWsTelemetry() { this._loadTelemetry(); }

    _onWsAnnounce(entry) {
        if (!entry || !entry.ts) return;
        const tbody = this._q('#rtd-ticker-tbody');
        if (!tbody) return;
        const empty = this._q('#rtd-ticker-empty');
        if (empty) empty.style.display = 'none';

        const tr = document.createElement('tr');
        tr.className = 'lw-pkt-row packet-row--new';
        tr.innerHTML = this._rowInner(entry);
        tr.addEventListener('animationend', () => tr.classList.remove('packet-row--new'));
        tbody.insertBefore(tr, tbody.firstChild);

        while (tbody.children.length > RTD_TICKER_LIMIT) {
            tbody.removeChild(tbody.lastChild);
        }
    }

    _rowHtml(a) {
        return `<tr class="lw-pkt-row">${this._rowInner(a)}</tr>`;
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
