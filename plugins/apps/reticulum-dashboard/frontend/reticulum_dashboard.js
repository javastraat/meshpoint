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
 * page instead gives Reticulum its own equivalent: the same stat-card +
 * live-table language, fed from Reticulum's own shape.
 *
 * Deliberately its own plugin (not a tab on the reticulum plugin's page):
 * the manifest only supports one [sidebar] entry per plugin, so a second
 * nav item needs a second plugin -- see plugins/apps/hello-world for the
 * same minimal, backend-free "sidebar" pattern this one follows. No new
 * backend routes: reads the reticulum plugin's already-public
 * /api/reticulum/{status,peers,announces} + /api/messages/conversations,
 * and listens on the shared dashboard WebSocket (window.concentratorWS)
 * for the same "reticulum_announce"/"reticulum_peer" broadcasts the
 * reticulum plugin's own page already uses. If reticulum isn't enabled,
 * those fetches just fail and the page sits in its empty state -- no
 * crash, no special-casing needed (same "fails open" shape used
 * throughout this app).
 *
 * The live ticker reuses the core dashboard's own new-row flash
 * (.packet-row--new / @keyframes packetFlash in frontend/css/dashboard.css,
 * loaded globally) rather than inventing a new animation -- same "cool,
 * data flowing through" effect the live PACKETS table gives RF users,
 * for Reticulum users instead.
 */

// Ring-buffer cap for the ticker's DOM rows. The reticulum plugin's own
// Activity tab keeps 200 (matches its backend ring buffer); this page is a
// glanceable live view, not a searchable log, so a much smaller cap keeps
// the DOM light while still feeling continuously "alive".
const RTD_TICKER_LIMIT = 60;

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
        this._onWsAnnounce = this._onWsAnnounce.bind(this);
        this._onWsPeer = this._onWsPeer.bind(this);
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

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header">
                        <h3>Live activity</h3>
                        <p class="lw-panel__limit">
                            Announces as they're heard, newest first -- full
                            history and peer management live on the
                            Reticulum page.
                        </p>
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
        `;
    }

    /** Called by the router (via registerSidebarPage) when the page becomes active. */
    show() {
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 20_000);
        if (window.concentratorWS) {
            window.concentratorWS.on('reticulum_announce', this._onWsAnnounce);
            window.concentratorWS.on('reticulum_peer', this._onWsPeer);
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
        await Promise.all([this._loadStatus(), this._loadPeerCounts(), this._loadConversationCount(), this._loadTickerSeed()]);
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

    async _loadPeerCounts() {
        try {
            const r = await fetch('/api/reticulum/peers', { credentials: 'same-origin' });
            if (!r.ok) return;
            const peers = await r.json();
            this._setText('rtd-stat-peers', peers.length);
            // "People" = actual message recipients (lxmf.delivery);
            // everything else is network infrastructure -- same split
            // the reticulum plugin's own page applies.
            const peopleCount = peers.filter((p) => p.aspect === 'lxmf.delivery').length;
            this._setText('rtd-stat-people', peopleCount);
            this._setText('rtd-stat-infra', peers.length - peopleCount);
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

    _onWsPeer() { this._loadPeerCounts(); }

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
