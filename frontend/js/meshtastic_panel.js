/**
 * Meshtastic monitoring panel.
 * Shows a node census and a recent-packets feed.
 * Loaded once; auto-refreshes every 15 seconds while the section is visible.
 */

const MT_TYPE_LABELS = {
    text:             'Text',
    position:         'Position',
    telemetry:        'Telemetry',
    nodeinfo:         'NodeInfo',
    routing:          'Routing',
    traceroute:       'Traceroute',
    neighborinfo:     'NeighborInfo',
    encrypted:        'Encrypted',
    admin:            'Admin',
    waypoint:         'Waypoint',
    range_test:       'RangeTest',
    store_forward:    'StoreForward',
    detection_sensor: 'Detection',
    paxcounter:       'Pax',
    map_report:       'MapReport',
    unknown:          'Unknown',
};

const MT_TYPE_COLORS = {
    text:         'mt-badge--text',
    position:     'mt-badge--position',
    telemetry:    'mt-badge--telemetry',
    nodeinfo:     'mt-badge--nodeinfo',
    encrypted:    'mt-badge--encrypted',
    routing:      'mt-badge--routing',
    traceroute:   'mt-badge--traceroute',
    neighborinfo: 'mt-badge--neighborinfo',
};

class MeshtasticPanel {
    constructor() {
        this._refreshTimer = null;
        this._mounted = false;
        this._allNodes = [];
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
        const root = document.getElementById('meshtastic-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Meshtastic</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="mt-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="mt-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Total Packets</div>
                    <div class="stat-card__value" id="mt-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Unique Nodes</div>
                    <div class="stat-card__value" id="mt-stat-nodes">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Active (24h)</div>
                    <div class="stat-card__value" id="mt-stat-active">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Text Messages</div>
                    <div class="stat-card__value" id="mt-stat-text">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header">Nodes</div>
                    <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--mt-nodes">
                            <colgroup>
                                <col class="col-id">
                                <col class="col-name">
                                <col class="col-hw">
                                <col class="col-role">
                                <col class="col-rssi">
                                <col class="col-snr">
                                <col class="col-hops">
                                <col class="col-dist">
                                <col class="col-pkts">
                                <col class="col-time">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Node ID</th>
                                    <th>Name</th>
                                    <th>Hardware</th>
                                    <th>Role</th>
                                    <th class="lw-r">RSSI</th>
                                    <th class="lw-r">SNR</th>
                                    <th class="lw-r">Hops</th>
                                    <th class="lw-r">Dist</th>
                                    <th class="lw-r">Packets</th>
                                    <th>Last heard</th>
                                </tr>
                            </thead>
                            <tbody id="mt-node-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="mt-node-empty" style="display:none">
                            No Meshtastic nodes heard yet.
                        </p>
                    </div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header">
                        Recent packets
                        <span class="lw-panel__limit">(last 100)</span>
                    </div>
                    <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--mt-packets">
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
                            <tbody id="mt-packet-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="mt-packet-empty" style="display:none">
                            No packets yet.
                        </p>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('mt-refresh-btn')
            ?.addEventListener('click', () => this._load());

        const nodeTbody = document.getElementById('mt-node-tbody');
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

    async _load() {
        await Promise.all([
            this._loadStats(),
            this._loadNodes(),
            this._loadPackets(),
        ]);
    }

    async _loadStats() {
        try {
            const r = await fetch('/api/meshtastic/stats');
            if (!r.ok) return;
            const s = await r.json();
            this._setText('mt-stat-total',  s.total_packets  ?? '--');
            this._setText('mt-stat-nodes',  s.unique_nodes   ?? '--');
            this._setText('mt-stat-active', s.active_24h     ?? '--');
            this._setText('mt-stat-text',   s.by_type?.text  ?? 0);
        } catch (_) {}
    }

    async _loadNodes() {
        try {
            const r = await fetch('/api/meshtastic/nodes');
            if (!r.ok) return;
            const nodes = await r.json();
            const tbody = document.getElementById('mt-node-tbody');
            const empty = document.getElementById('mt-node-empty');
            if (!tbody) return;

            if (!nodes.length) {
                tbody.innerHTML = '';
                if (empty) empty.style.display = '';
                return;
            }
            if (empty) empty.style.display = 'none';

            this._allNodes = nodes;

            tbody.innerHTML = nodes.map((n) => `
                <tr data-node-id="${this._esc(n.node_id || '')}" class="mt-node-row">
                    <td class="lw-id">${this._fmtNodeId(n.node_id)}</td>
                    <td class="mt-name">${this._fmtName(n)}</td>
                    <td class="mt-hw">${this._fmtHw(n.hardware_model)}</td>
                    <td>${this._fmtRole(n.role)}</td>
                    <td class="lw-signal ${this._rssiClass(n.latest_rssi)}">${this._fmtRssi(n.latest_rssi)}</td>
                    <td class="lw-signal">${this._fmtSnr(n.latest_snr)}</td>
                    <td class="lw-num">${n.latest_hops != null ? n.latest_hops : '--'}</td>
                    <td class="lw-num">${this._fmtDist(n.latitude, n.longitude)}</td>
                    <td class="lw-num">${n.packet_count ?? '--'}</td>
                    <td class="lw-time">${this._fmtTime(n.last_heard)}</td>
                </tr>
            `).join('');
        } catch (_) {}
    }

    async _loadPackets() {
        try {
            const r = await fetch('/api/meshtastic/packets?limit=100');
            if (!r.ok) return;
            const packets = await r.json();
            const tbody = document.getElementById('mt-packet-tbody');
            const empty = document.getElementById('mt-packet-empty');
            if (!tbody) return;

            if (!packets.length) {
                tbody.innerHTML = '';
                if (empty) empty.style.display = '';
                return;
            }
            if (empty) empty.style.display = 'none';

            tbody.innerHTML = packets.map((p) => `
                <tr>
                    <td class="lw-time">${this._fmtTime(p.timestamp)}</td>
                    <td>${this._fmtType(p.packet_type)}</td>
                    <td class="lw-id">${p.source_id || '--'}</td>
                    <td class="lw-id">${this._fmtDest(p.destination_id)}</td>
                    <td class="lw-signal ${this._rssiClass(p.rssi)}">${this._fmtRssi(p.rssi)}</td>
                    <td class="lw-signal">${this._fmtSnr(p.snr)}</td>
                    <td class="lw-num">${p.spreading_factor != null ? `SF${p.spreading_factor}` : '--'}</td>
                    <td class="lw-num">${p.hops != null ? p.hops : '--'}</td>
                </tr>
            `).join('');
        } catch (_) {}
    }

    _fmtNodeId(id) {
        if (!id) return '--';
        return id.startsWith('!') ? id : `!${id}`;
    }

    _fmtName(n) {
        const long  = (n.long_name  || '').trim();
        const short = (n.short_name || '').trim();
        if (long  && long  !== n.node_id) return this._esc(long);
        if (short && short !== n.node_id) return this._esc(short);
        return '<span class="lw-time">—</span>';
    }

    _fmtHw(model) {
        if (model == null || model === '') return '--';
        const num = Number(model);
        const name = (!isNaN(num) && typeof HW_NAMES !== 'undefined')
            ? (HW_NAMES[num] || model)
            : model;
        return `<span class="mt-hw-tag">${this._esc(name)}</span>`;
    }

    _fmtRole(role) {
        if (!role) return '--';
        const label = role.replace(/_/g, ' ').toLowerCase()
            .replace(/\b\w/g, c => c.toUpperCase());
        return `<span class="mt-role-tag">${this._esc(label)}</span>`;
    }

    _fmtType(t) {
        const label = MT_TYPE_LABELS[t] || t || '--';
        const cls = MT_TYPE_COLORS[t] || '';
        return `<span class="mt-badge ${cls}">${label}</span>`;
    }

    _fmtDest(id) {
        if (!id) return '--';
        if (id === 'ffffffff' || id === '!ffffffff') return '<span class="lw-time">BCAST</span>';
        return id.startsWith('!') ? id : `!${id}`;
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

window.MeshtasticPanel = MeshtasticPanel;
