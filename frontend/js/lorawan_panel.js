/**
 * LoRaWAN monitoring panel.
 * Shows a device census (one row per DevEUI/DevAddr) and a recent-packets feed.
 * Loaded once; auto-refreshes every 15 seconds while the section is visible.
 */

// Persisted Packets|Devices tab choice (W10, same pattern as MeshCore).
const LW_TAB_STORE_KEY = 'meshpoint.lwTab';

class LoRaWANPanel {
    constructor() {
        this._refreshTimer = null;
        this._mounted = false;
        this._allDevices = [];
        this._deviceSearchQuery = '';
        let storedTab = null;
        try { storedTab = localStorage.getItem(LW_TAB_STORE_KEY); } catch (_) {}
        this._tab = storedTab === 'devices' ? 'devices' : 'packets';
    }

    /** Called by the router when the section becomes active. */
    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 15_000);
    }

    /** Called by the router when the section is hidden. */
    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
    }

    _mount() {
        const root = document.getElementById('lorawan-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">LoRaWAN</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="lw-export-btn">Export CSV</button>
                    <button class="terminal-button" type="button" id="lw-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="lw-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Total Packets</div>
                    <div class="stat-card__value" id="lw-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Unique Devices</div>
                    <div class="stat-card__value" id="lw-stat-devices">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Joins</div>
                    <div class="stat-card__value" id="lw-stat-joins">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Data Uplinks</div>
                    <div class="stat-card__value" id="lw-stat-data">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-lw-tab="packets">Recent packets</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-lw-tab="devices">Devices</button>
                        </div>
                        <span class="lw-panel__limit" data-lw-suffix="packets">(last 100)</span>
                        <div class="lw-search-wrap" data-lw-suffix="devices" hidden>
                            <input type="text" id="lw-device-search" class="lw-search"
                                   placeholder="Search..." autocomplete="off" spellcheck="false" />
                            <button id="lw-device-search-clear" class="lw-search-clear"
                                    title="Clear search" hidden>&times;</button>
                        </div>
                    </div>
                    <div data-lw-view="packets">
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--packets">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-type">
                                <col class="col-dev">
                                <col class="col-rssi">
                                <col class="col-snr">
                                <col class="col-freq">
                                <col class="col-sf">
                                <col class="col-fport">
                                <col class="col-fcnt">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Type</th>
                                    <th>Device</th>
                                    <th class="lw-r">RSSI</th>
                                    <th class="lw-r">SNR</th>
                                    <th class="lw-r">Freq (MHz)</th>
                                    <th class="lw-r">SF</th>
                                    <th class="lw-r">FPort</th>
                                    <th class="lw-r">FCnt</th>
                                </tr>
                            </thead>
                            <tbody id="lw-packet-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="lw-packet-empty" style="display:none">
                            No packets yet.
                        </p>
                        </div>
                    </div>
                    <div data-lw-view="devices" hidden>
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--devices">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-time">
                                <col class="col-id">
                                <col class="col-type">
                                <col class="col-frames">
                                <col class="col-rssi">
                                <col class="col-snr">
                                <col class="col-freq">
                                <col class="col-sf">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Last seen</th>
                                    <th>First seen</th>
                                    <th>DevEUI / DevAddr</th>
                                    <th>Type</th>
                                    <th class="lw-r">Frames</th>
                                    <th class="lw-r">RSSI</th>
                                    <th class="lw-r">SNR</th>
                                    <th class="lw-r">Freq (MHz)</th>
                                    <th class="lw-r">SF</th>
                                </tr>
                            </thead>
                            <tbody id="lw-device-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="lw-device-empty" style="display:none">
                            No LoRaWAN devices heard yet.
                        </p>
                        </div>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('lw-refresh-btn')
            ?.addEventListener('click', () => this._load());
        document.getElementById('lw-export-btn')
            ?.addEventListener('click', () => {
                const ds = this._tab === 'devices' ? 'devices' : 'packets';
                window.location = `/api/lorawan/export/${ds}.csv`;
            });
        root.querySelectorAll('[data-lw-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.lwTab));
        });
        this._applyTab();

        const pktTbody = document.getElementById('lw-packet-tbody');
        if (pktTbody) {
            pktTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-pkt]');
                if (!tr || !window.PacketDetailModal) return;
                const pkt = (this._lastPackets || [])[Number(tr.dataset.pkt)];
                if (!pkt) return;
                window.PacketDetailModal.show(pkt, { selectedRow: tr });
            });
        }

        const deviceSearchEl = document.getElementById('lw-device-search');
        const deviceSearchClearEl = document.getElementById('lw-device-search-clear');
        if (deviceSearchEl) {
            deviceSearchEl.addEventListener('input', (e) => {
                this._deviceSearchQuery = e.target.value.toLowerCase();
                if (deviceSearchClearEl) deviceSearchClearEl.hidden = !e.target.value;
                this._renderDevices();
            });
        }
        if (deviceSearchClearEl && deviceSearchEl) {
            deviceSearchClearEl.addEventListener('click', () => {
                deviceSearchEl.value = '';
                this._deviceSearchQuery = '';
                deviceSearchClearEl.hidden = true;
                deviceSearchEl.focus();
                this._renderDevices();
            });
        }

        const deviceTbody = document.getElementById('lw-device-tbody');
        if (deviceTbody) {
            deviceTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-device-id]');
                if (!tr || !window.nodeDrawer) return;
                const deviceId = tr.dataset.deviceId;
                const dev = this._allDevices.find(d => (d.dev_eui || d.source_id) === deviceId);
                if (!dev) return;
                const nodeId = dev.dev_eui || dev.source_id;
                window.nodeDrawer.open({
                    node_id: nodeId,
                    long_name: nodeId,
                    short_name: (nodeId || '').slice(-4),
                    protocol: 'lorawan',
                    packet_count: dev.frame_count,
                    first_seen: dev.first_seen,
                    last_heard: dev.last_seen,
                    latest_rssi: dev.last_rssi,
                    latest_snr: dev.last_snr,
                    has_position: false,
                });
            });
        }
    }

    _setTab(tab) {
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(LW_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
    }

    _applyTab() {
        const root = document.getElementById('lorawan-panel');
        if (!root) return;
        root.querySelectorAll('[data-lw-tab]').forEach((btn) => {
            const active = btn.dataset.lwTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        root.querySelectorAll('[data-lw-view]').forEach((el) => {
            el.hidden = el.dataset.lwView !== this._tab;
        });
        root.querySelectorAll('[data-lw-suffix]').forEach((el) => {
            el.hidden = el.dataset.lwSuffix !== this._tab;
        });
    }

    async _load() {
        await Promise.all([
            this._loadStats(),
            this._loadDevices(),
            this._loadPackets(),
        ]);
    }

    async _loadStats() {
        try {
            const r = await fetch('/api/lorawan/stats');
            if (!r.ok) return;
            const s = await r.json();
            this._setText('lw-stat-total', s.total_packets ?? '--');
            this._setText('lw-stat-devices', s.unique_devices ?? '--');
            this._setText('lw-stat-joins', s.by_type?.lorawan_join ?? 0);
            this._setText('lw-stat-data', s.by_type?.lorawan_data ?? 0);
        } catch (_) {}
    }

    async _loadDevices() {
        try {
            const r = await fetch('/api/lorawan/devices');
            if (!r.ok) return;
            this._allDevices = await r.json();
            this._renderDevices();
        } catch (_) {}
    }

    _renderDevices() {
        const tbody = document.getElementById('lw-device-tbody');
        const empty = document.getElementById('lw-device-empty');
        if (!tbody) return;

        let devices = this._allDevices;
        if (this._deviceSearchQuery) {
            devices = devices.filter((d) => {
                const id = (d.dev_eui || d.source_id || '').toLowerCase();
                const type = (d.packet_type || '').toLowerCase();
                return id.includes(this._deviceSearchQuery) || type.includes(this._deviceSearchQuery);
            });
        }

        if (!devices.length) {
            tbody.innerHTML = '';
            if (empty) {
                empty.textContent = this._allDevices.length
                    ? 'No devices match your search.'
                    : 'No LoRaWAN devices heard yet.';
                empty.style.display = '';
            }
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = devices.map((d) => `
            <tr data-device-id="${this._esc(d.dev_eui || d.source_id || '')}" class="lw-device-row">
                <td class="lw-time">${this._fmtTime(d.last_seen)}</td>
                <td class="lw-time">${this._fmtTime(d.first_seen)}</td>
                <td class="lw-id">${this._fmtId(d)}</td>
                <td>${this._fmtType(d.packet_type)}</td>
                <td class="lw-num">${d.frame_count}</td>
                <td class="lw-signal ${this._rssiClass(d.last_rssi)}">${this._fmtRssi(d.last_rssi)}</td>
                <td class="lw-signal">${this._fmtSnr(d.last_snr)}</td>
                <td class="lw-num">${d.last_frequency_mhz != null ? d.last_frequency_mhz.toFixed(3) : '--'}</td>
                <td class="lw-num">${d.last_sf != null ? `SF${d.last_sf}` : '--'}</td>
            </tr>
        `).join('');
    }

    async _loadPackets() {
        try {
            const r = await fetch('/api/lorawan/packets?limit=100');
            if (!r.ok) return;
            const packets = await r.json();
            const tbody = document.getElementById('lw-packet-tbody');
            const empty = document.getElementById('lw-packet-empty');
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
                    <td>${this._fmtType(p.packet_type)}</td>
                    <td class="lw-id">${p.dev_eui || p.source_id || '--'}</td>
                    <td class="lw-signal ${this._rssiClass(p.rssi)}">${this._fmtRssi(p.rssi)}</td>
                    <td class="lw-signal">${this._fmtSnr(p.snr)}</td>
                    <td class="lw-num">${p.frequency_mhz != null ? p.frequency_mhz.toFixed(3) : '--'}</td>
                    <td class="lw-num">${p.spreading_factor != null ? `SF${p.spreading_factor}` : '--'}</td>
                    <td class="lw-num">${p.f_port ?? '--'}</td>
                    <td class="lw-num">${p.f_cnt ?? '--'}</td>
                </tr>
            `).join('');
        } catch (_) {}
    }

    _fmtId(d) {
        if (d.dev_eui) return d.dev_eui;
        if (d.source_id) return d.source_id;
        return '--';
    }

    _fmtType(t) {
        const map = {
            lorawan_join:   '<span class="lw-badge lw-badge--join">Join</span>',
            lorawan_data:   '<span class="lw-badge lw-badge--data">Data</span>',
            lorawan_rejoin: '<span class="lw-badge lw-badge--rejoin">Rejoin</span>',
        };
        return map[t] || `<span class="lw-badge">${t || '--'}</span>`;
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
    _fmtSnr(v)  { return v != null ? `${v.toFixed(1)} dB` : '--'; }

    _rssiClass(v) {
        if (v == null) return '';
        if (v >= -100) return 'lw-signal--good';
        if (v >= -115) return 'lw-signal--ok';
        return 'lw-signal--weak';
    }

    _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
}

window.LoRaWANPanel = LoRaWANPanel;
