/**
 * MeshCore monitoring panel.
 * Shows the imported contact census and live MeshCore packets.
 */

// Reuses the Meshtastic page's mt-badge--* palette so packet types wear
// the same colors on both protocol tabs.
const MC_TYPE_COLORS = {
    text:             'mt-badge--text',
    nodeinfo:         'mt-badge--nodeinfo',
    neighbour_advert: 'mt-badge--neighborinfo',
    telemetry:        'mt-badge--telemetry',
    position:         'mt-badge--position',
};

// Persisted Packets|Contacts tab choice (W10 pilot on this page).
const MC_TAB_STORE_KEY = 'meshpoint.mcTab';

class MeshCorePanel {
    constructor() {
        this._refreshTimer = null;
        this._mounted = false;
        this._nodeNames = {};
        this._allNodes = [];
        this._page = 0;
        this._pageSize = 50;
        let stored = null;
        try { stored = localStorage.getItem(MC_TAB_STORE_KEY); } catch (_) {}
        this._tab = stored === 'contacts' ? 'contacts' : 'packets';
    }

    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 15_000);
    }

    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
    }

    _mount() {
        const root = document.getElementById('meshcore-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">MeshCore</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="mc-export-btn">Export CSV</button>
                    <button class="terminal-button" type="button" id="mc-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="mc-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Total Contacts</div>
                    <div class="stat-card__value" id="mc-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Active (24h)</div>
                    <div class="stat-card__value" id="mc-stat-24h">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Active (7d)</div>
                    <div class="stat-card__value" id="mc-stat-7d">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Packets relayed</div>
                    <div class="stat-card__value" id="mc-stat-pkts">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-mc-tab="packets">Recent packets</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-mc-tab="contacts">Contacts</button>
                        </div>
                        <span class="lw-panel__limit" data-mc-suffix="packets">(last 100)</span>
                        <span class="lw-panel__limit" id="mc-node-count" data-mc-suffix="contacts" hidden></span>
                    </div>
                    <div data-mc-view="packets">
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--mc-packets">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-type">
                                    <col class="col-src">
                                    <col class="col-dst">
                                    <col class="col-rssi">
                                    <col class="col-snr">
                                    <col class="col-sf">
                                    <col class="col-hops">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Type</th>
                                        <th>Source</th>
                                        <th>Dest</th>
                                        <th class="lw-r">RSSI</th>
                                        <th class="lw-r">SNR</th>
                                        <th class="lw-r">SF</th>
                                        <th class="lw-r">Hops</th>
                                    </tr>
                                </thead>
                                <tbody id="mc-packet-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="mc-packet-empty" style="display:none">
                                No MeshCore packets captured yet.
                            </p>
                        </div>
                    </div>
                    <div data-mc-view="contacts" hidden>
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--mc-nodes">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-id">
                                    <col class="col-name">
                                    <col class="col-role">
                                    <col class="col-rssi">
                                    <col class="col-snr">
                                    <col class="col-dist">
                                    <col class="col-pkts">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Last heard</th>
                                        <th>Node ID</th>
                                        <th>Name</th>
                                        <th>Role</th>
                                        <th class="lw-r">RSSI</th>
                                        <th class="lw-r">SNR</th>
                                        <th class="lw-r">Dist</th>
                                        <th class="lw-r">Packets</th>
                                    </tr>
                                </thead>
                                <tbody id="mc-node-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="mc-node-empty" style="display:none">
                                No MeshCore contacts yet. Import contacts.json to populate.
                            </p>
                        </div>
                        <div class="lw-pagination" id="mc-pagination" style="display:none">
                            <button class="lw-page-btn" id="mc-page-prev">&#8249; Prev</button>
                            <span class="lw-page-info" id="mc-page-info"></span>
                            <button class="lw-page-btn" id="mc-page-next">Next &#8250;</button>
                        </div>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('mc-refresh-btn')
            ?.addEventListener('click', () => this._load());
        document.getElementById('mc-export-btn')
            ?.addEventListener('click', () => {
                const ds = this._tab === 'contacts' ? 'contacts' : 'packets';
                window.location = `/api/meshcore/export/${ds}.csv`;
            });
        document.getElementById('mc-page-prev')
            ?.addEventListener('click', () => { this._page--; this._renderNodePage(); });
        document.getElementById('mc-page-next')
            ?.addEventListener('click', () => { this._page++; this._renderNodePage(); });
        root.querySelectorAll('[data-mc-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.mcTab));
        });
        this._applyTab();

        const pktTbody = document.getElementById('mc-packet-tbody');
        if (pktTbody) {
            pktTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-pkt]');
                if (!tr || !window.PacketDetailModal) return;
                const pkt = (this._lastPackets || [])[Number(tr.dataset.pkt)];
                if (!pkt) return;
                window.PacketDetailModal.show(pkt, {
                    formatNodeId: (id) => this._nodeNames[id] || id || 'n/a',
                    selectedRow: tr,
                });
            });
        }

        const nodeTbody = document.getElementById('mc-node-tbody');
        if (nodeTbody) {
            nodeTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-node-id]');
                if (!tr || !window.nodeDrawer) return;
                const nodeId = tr.dataset.nodeId;
                const node = this._allNodes.find(n => n.node_id === nodeId);
                if (node) window.nodeDrawer.open({ ...node, has_position: !!(node.latitude && node.longitude) });
            });
        }
    }

    _setTab(tab) {
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(MC_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
    }

    _applyTab() {
        const root = document.getElementById('meshcore-panel');
        if (!root) return;
        root.querySelectorAll('[data-mc-tab]').forEach((btn) => {
            const active = btn.dataset.mcTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        root.querySelectorAll('[data-mc-view]').forEach((el) => {
            el.hidden = el.dataset.mcView !== this._tab;
        });
        root.querySelectorAll('[data-mc-suffix]').forEach((el) => {
            el.hidden = el.dataset.mcSuffix !== this._tab;
        });
    }

    async _load() {
        await Promise.all([this._loadStats(), this._loadNodes()]);
        await this._loadPackets();
    }

    async _loadStats() {
        try {
            const r = await fetch('/api/meshcore/stats');
            if (!r.ok) return;
            const s = await r.json();
            this._setText('mc-stat-total', s.total_nodes   ?? '--');
            this._setText('mc-stat-24h',   s.active_24h    ?? '--');
            this._setText('mc-stat-7d',    s.active_7d     ?? '--');
            this._setText('mc-stat-pkts',  s.total_packets ?? '--');
        } catch (_) {}
    }

    async _loadNodes() {
        try {
            const r = await fetch('/api/meshcore/nodes');
            if (!r.ok) return;
            const nodes = await r.json();
            const empty = document.getElementById('mc-node-empty');

            if (!nodes.length) {
                document.getElementById('mc-node-tbody').innerHTML = '';
                if (empty) empty.style.display = '';
                document.getElementById('mc-pagination').style.display = 'none';
                return;
            }
            if (empty) empty.style.display = 'none';

            this._nodeNames = {};
            nodes.forEach(n => {
                if (n.node_id) this._nodeNames[n.node_id] = (n.long_name || n.short_name || '').trim();
            });

            this._allNodes = nodes;
            this._page = 0;
            this._renderNodePage();
        } catch (_) {}
    }

    _renderNodePage() {
        const total = this._allNodes.length;
        const pages = Math.ceil(total / this._pageSize);
        this._page = Math.max(0, Math.min(this._page, pages - 1));

        const start = this._page * this._pageSize;
        const slice = this._allNodes.slice(start, start + this._pageSize);

        const tbody = document.getElementById('mc-node-tbody');
        if (tbody) {
            tbody.innerHTML = slice.map((n) => `
                <tr data-node-id="${this._esc(n.node_id || '')}" class="mc-contact-row">
                    <td class="lw-time">${this._fmtTime(n.last_heard)}</td>
                    <td class="lw-id">${this._esc(n.node_id || '--')}</td>
                    <td class="mt-name">${this._fmtName(n)}</td>
                    <td>${this._fmtRole(n.role)}</td>
                    <td class="lw-signal ${this._rssiClass(n.latest_rssi)}">${this._fmtRssi(n.latest_rssi)}</td>
                    <td class="lw-signal">${this._fmtSnr(n.latest_snr)}</td>
                    <td class="lw-num">${this._fmtDist(n.latitude, n.longitude)}</td>
                    <td class="lw-num">${n.packet_count ?? 0}</td>
                </tr>
            `).join('');
        }

        const pagination = document.getElementById('mc-pagination');
        const info = document.getElementById('mc-page-info');
        const prev = document.getElementById('mc-page-prev');
        const next = document.getElementById('mc-page-next');
        const count = document.getElementById('mc-node-count');

        if (pagination) pagination.style.display = pages > 1 ? '' : 'none';
        if (info) info.textContent = `Page ${this._page + 1} of ${pages}`;
        if (prev) prev.disabled = this._page === 0;
        if (next) next.disabled = this._page >= pages - 1;
        if (count) count.textContent = `(${total} total)`;
    }

    async _loadPackets() {
        try {
            const r = await fetch('/api/meshcore/packets?limit=100');
            if (!r.ok) return;
            const packets = await r.json();
            const tbody = document.getElementById('mc-packet-tbody');
            const empty = document.getElementById('mc-packet-empty');
            if (!tbody) return;

            if (!packets.length) {
                tbody.innerHTML = '';
                if (empty) empty.style.display = '';
                return;
            }
            if (empty) empty.style.display = 'none';

            this._lastPackets = packets;
            tbody.innerHTML = packets.map((p, i) => `
                <tr class="lw-pkt-row" data-pkt="${i}">
                    <td class="lw-time">${this._fmtTime(p.timestamp)}</td>
                    <td><span class="mt-badge ${MC_TYPE_COLORS[p.packet_type] || ''}">${this._esc(p.packet_type || '--')}</span></td>
                    <td class="lw-id">${this._fmtSrc(p.source_id)}</td>
                    <td class="lw-id">${this._fmtDest(p.destination_id)}</td>
                    <td class="lw-signal ${this._rssiClass(p.rssi)}">${this._fmtRssi(p.rssi)}</td>
                    <td class="lw-signal">${this._fmtSnr(p.snr)}</td>
                    <td class="lw-num">${p.spreading_factor ? `SF${p.spreading_factor}` : '--'}</td>
                    <td class="lw-num">${p.hops != null ? p.hops : '--'}</td>
                </tr>
            `).join('');
        } catch (_) {}
    }

    _fmtName(n) {
        const name = (n.long_name || n.short_name || '').trim();
        return name ? this._esc(name) : '<span class="lw-time">—</span>';
    }

    _fmtRole(role) {
        if (!role) return '--';
        const MC_REMAP = { ROUTER: 'REPEATER', CLIENT_MUTE: 'ROOMSERVER', ROUTER_CLIENT: 'REPEATER' };
        const normalized = MC_REMAP[role] || role;
        const label = normalized.replace(/_/g, ' ').toLowerCase()
            .replace(/\b\w/g, c => c.toUpperCase());
        return `<span class="mt-role-tag">${this._esc(label)}</span>`;
    }

    _fmtSrc(id) {
        if (!id) return '--';
        const name = this._nodeNames[id];
        if (name) return `<span class="mt-name">${this._esc(name)}</span> <span class="lw-time">${this._esc(id)}</span>`;
        return this._esc(id);
    }

    _fmtDest(id) {
        if (!id) return '--';
        if (id === 'ffffffff' || id === 'broadcast') return '<span class="lw-time">broadcast</span>';
        const name = this._nodeNames[id];
        if (name) return `<span class="mt-name">${this._esc(name)}</span> <span class="lw-time">${this._esc(id)}</span>`;
        return this._esc(id);
    }

    _fmtTime(ts) {
        if (!ts) return '--';
        try {
            const d = new Date(ts);
            const now = new Date();
            const sameDay = d.getFullYear() === now.getFullYear()
                && d.getMonth() === now.getMonth()
                && d.getDate() === now.getDate();
            if (sameDay) {
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            }
            return d.toLocaleString([], {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        } catch (_) { return ts; }
    }

    _fmtRssi(v) { return v != null ? `${Math.round(v)} dBm` : '--'; }
    _fmtSnr(v)  { return v != null ? `${Number(v).toFixed(1)} dB` : '--'; }

    _fmtDist(lat, lon) {
        const hLat = window._meshpointHomeLat;
        const hLon = window._meshpointHomeLon;
        if (hLat == null || hLon == null || lat == null || lon == null) return '--';
        const R = 6371, dLat = (lat - hLat) * Math.PI / 180, dLon = (lon - hLon) * Math.PI / 180;
        const a = Math.sin(dLat/2)**2 + Math.cos(hLat*Math.PI/180)*Math.cos(lat*Math.PI/180)*Math.sin(dLon/2)**2;
        const km = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        if (km < 0.05) return '--';
        return window.MeshpointDisplayUnits ? window.MeshpointDisplayUnits.formatDistanceKm(km) : `${km.toFixed(1)} km`;
    }

    _rssiClass(v) {
        if (v == null) return '';
        if (v >= -100) return 'lw-signal--good';
        if (v >= -115) return 'lw-signal--ok';
        return 'lw-signal--weak';
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }
}

window.MeshCorePanel = MeshCorePanel;
