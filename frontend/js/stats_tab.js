/**
 * Stats tab: comprehensive local stats dashboard matching the cloud Meshradar
 * per-Meshpoint stats page. Sections: hero, protocols, signal intelligence,
 * range, reception, network, protocol detail, relay.
 */

const ROLE_NAMES = {
    0: 'Client', 1: 'Client Mute', 2: 'Router', 3: 'Router Client',
    4: 'Repeater', 5: 'Tracker', 6: 'Sensor', 7: 'TAK', 8: 'Client Hidden',
    9: 'Lost & Found', 10: 'TAK Tracker',
};

// HW_NAMES now lives in meshtastic_hw_names.js (shared with node_drawer.js,
// node_cards.js, and meshtastic_panel.js), loaded earlier in index.html.

function chartColors() {
    return (window.ChartTheme && window.ChartTheme.categorical) || [
        '#4c8dd6', '#e08e2a', '#2fa88f', '#c56ba6', '#7d7fd0',
        '#d1584f', '#93ab4b', '#48b0cf', '#a879c9', '#5aa469',
    ];
}
function chartSeries(k) {
    return (window.ChartTheme && window.ChartTheme.series(k)) || '#4c8dd6';
}
function chartStatus(l) {
    return (window.ChartTheme && window.ChartTheme.status(l)) || '#22c55e';
}

class StatsTab {
    constructor(containerId) {
        this._container = document.getElementById(containerId);
        this._charts = {};
        this._refreshInterval = null;
        this._rendered = false;
        this._statusStrip = null;
        this._fetchedAt = null;
    }

    async refresh() {
        try {
            const [res, snrRes] = await Promise.all([
                fetch('/api/stats/summary'),
                fetch('/api/analytics/signal/snr'),
            ]);
            const data = await res.json();
            data.snr_distribution = snrRes.ok ? await snrRes.json() : {};
            if (!this._rendered) {
                this._buildLayout();
                this._rendered = true;
            }
            this._fetchedAt = Date.now();
            this._update(data);
        } catch (e) {
            console.error('Stats refresh failed:', e);
        }

        if (!this._refreshInterval) {
            this._refreshInterval = setInterval(() => {
                const section = document.querySelector('[data-section="stats"]');
                if (section && section.classList.contains('section--active')) {
                    this.refresh();
                } else {
                    clearInterval(this._refreshInterval);
                    this._refreshInterval = null;
                }
            }, 15000);
        }
    }

    _buildLayout() {
        this._container.innerHTML = `
        <div class="stats-panel">

            <div class="stats-hero">
                <div>
                    <span id="ss-total" class="stats-hero__number">0</span>
                    <span class="stats-hero__label">packets captured</span>
                </div>
                <div id="ss-session-hero" class="stats-hero__session" style="display:none">
                    <span id="ss-session-count" class="stats-hero__session-num">0</span>
                    <span class="stats-hero__session-label">this session</span>
                </div>
            </div>

            <div class="stats-strip">
                <div class="stats-strip__card">
                    <span id="ss-nodes" class="stats-strip__value">0</span>
                    <span class="stats-strip__label">Nodes Added</span>
                </div>
                <div class="stats-strip__card">
                    <span id="ss-days" class="stats-strip__value">0</span>
                    <span class="stats-strip__label">Days Since First Pkt</span>
                </div>
                <div class="stats-strip__card">
                    <span id="ss-uptime" class="stats-strip__value">--</span>
                    <span class="stats-strip__label">Uptime</span>
                </div>
                <div class="stats-strip__card">
                    <span id="ss-firmware" class="stats-strip__value">--</span>
                    <span class="stats-strip__label">Firmware</span>
                </div>
            </div>

            <section class="stats-section">
                <div class="stats-section__head">
                    <h2 class="stats-section__title">Protocols</h2>
                    <div class="stats-toggle" id="proto-toggle">
                        <button class="stats-toggle__btn stats-toggle__btn--active" data-view="alltime">All-time</button>
                        <button class="stats-toggle__btn" data-view="session">Session</button>
                    </div>
                </div>
                <div class="stats-row">
                    <div class="stats-card">
                        <div class="stats-card__label">Protocol Split</div>
                        <div class="stats-card__desc">Meshtastic vs Meshcore packet share</div>
                        <canvas id="sc-protocol"></canvas>
                    </div>
                    <div class="stats-card">
                        <div class="stats-card__label">Packet Types</div>
                        <div class="stats-card__desc">Breakdown by decoded message type</div>
                        <canvas id="sc-types"></canvas>
                    </div>
                </div>
            </section>

            <section class="stats-section">
                <h2 class="stats-section__title">Signal Intelligence</h2>
                <div class="stats-signal-nums">
                    <div class="stats-signal-num">
                        <div class="stats-signal-num__label">Best RSSI</div>
                        <div id="ss-best-rssi" class="stats-signal-num__value">--</div>
                    </div>
                    <div class="stats-signal-num">
                        <div class="stats-signal-num__label">Avg RSSI</div>
                        <div id="ss-avg-rssi" class="stats-signal-num__value">--</div>
                    </div>
                    <div class="stats-signal-num">
                        <div class="stats-signal-num__label">Best SNR</div>
                        <div id="ss-best-snr" class="stats-signal-num__value">--</div>
                    </div>
                    <div class="stats-signal-num">
                        <div class="stats-signal-num__label">Avg SNR</div>
                        <div id="ss-avg-snr" class="stats-signal-num__value">--</div>
                    </div>
                </div>
                <div class="stats-row">
                    <div class="stats-card">
                        <div class="stats-card__label">RSSI Distribution</div>
                        <div class="stats-card__desc">Packet count by signal strength bucket (dBm)</div>
                        <canvas id="sc-rssi"></canvas>
                    </div>
                    <div class="stats-card">
                        <div class="stats-card__label">SNR Distribution</div>
                        <div class="stats-card__desc">Packet count by signal-to-noise bucket (dB), last 500 packets</div>
                        <canvas id="sc-snr"></canvas>
                    </div>
                    <div class="stats-card">
                        <div class="stats-card__label">Avg Signal Quality</div>
                        <div class="stats-card__desc">Average RSSI mapped to 0-100 scale</div>
                        <canvas id="sc-quality"></canvas>
                    </div>
                </div>
            </section>

            <section class="stats-section">
                <h2 class="stats-section__title">Range</h2>
                <div class="stats-range-grid">
                    <div class="stats-range-card" title="Farthest node your antenna received directly, no relay hops (Meshtastic or MeshCore, whichever band — LoRaWAN never qualifies, this session)">
                        <div class="stats-range-card__header">Farthest Direct Signal</div>
                        <div class="stats-range-card__desc">Farthest direct reception, no relay hops (Meshtastic or MeshCore)</div>
                        <div class="stats-range-card__value">
                            <span id="ss-direct-mi" class="stats-range-card__miles">--</span>
                            <span id="ss-direct-unit" class="stats-range-card__unit">mi</span>
                        </div>
                        <div id="ss-direct-detail" class="stats-range-card__detail"></div>
                        <div class="stats-range-bar"><div id="ss-direct-bar" class="stats-range-bar__fill"></div></div>
                    </div>
                    <div class="stats-range-card">
                        <div class="stats-range-card__header">Farthest Via Meshtastic</div>
                        <div class="stats-range-card__desc">Farthest Meshtastic node relayed through other nodes (1+ hops)</div>
                        <div class="stats-range-card__value">
                            <span id="ss-mesh-mi" class="stats-range-card__miles">--</span>
                            <span id="ss-mesh-unit" class="stats-range-card__unit"></span>
                        </div>
                        <div id="ss-mesh-detail" class="stats-range-card__detail"></div>
                        <div class="stats-range-bar"><div id="ss-mesh-bar" class="stats-range-bar__fill stats-range-bar__fill--mesh"></div></div>
                    </div>
                    <div class="stats-range-card" title="Farthest MeshCore node in your roster with a known position — not necessarily ever received directly, may include imported contacts">
                        <div class="stats-range-card__header">Farthest MeshCore Contact</div>
                        <div class="stats-range-card__desc">Farthest roster contact with known position — not necessarily heard directly</div>
                        <div class="stats-range-card__value">
                            <span id="ss-mc-mi" class="stats-range-card__miles">--</span>
                            <span id="ss-mc-unit" class="stats-range-card__unit"></span>
                        </div>
                        <div id="ss-mc-detail" class="stats-range-card__detail"></div>
                        <div class="stats-range-bar"><div id="ss-mc-bar" class="stats-range-bar__fill stats-range-bar__fill--meshcore"></div></div>
                    </div>
                </div>
            </section>

            <section class="stats-section">
                <h2 class="stats-section__title">Reception</h2>
                <div class="stats-row">
                    <div class="stats-card">
                        <div class="stats-card__label">Direct vs Relayed</div>
                        <div class="stats-card__desc">Packets received directly (0 hops) vs relayed through other nodes</div>
                        <canvas id="sc-direct-relayed"></canvas>
                    </div>
                    <div class="stats-card">
                        <div class="stats-card__label">Active Nodes (24h)</div>
                        <div class="stats-card__desc">Nodes seen in the last 24 hours out of all nodes ever captured</div>
                        <canvas id="sc-active-nodes"></canvas>
                    </div>
                </div>
            </section>

            <section class="stats-section" id="ss-network-section" style="display:none">
                <h2 class="stats-section__title">Network</h2>
                <div class="stats-row">
                    <div class="stats-card" id="ss-roles-card" style="display:none">
                        <div class="stats-card__label">Device Roles</div>
                        <div class="stats-card__desc">Distribution of node roles seen on the mesh</div>
                        <canvas id="sc-roles"></canvas>
                    </div>
                    <div class="stats-card" id="ss-hw-card" style="display:none">
                        <div class="stats-card__label">Hardware Models</div>
                        <div class="stats-card__desc">Hardware types reported by nodes via NodeInfo</div>
                        <canvas id="sc-hw"></canvas>
                    </div>
                </div>
            </section>

            <section class="stats-section">
                <h2 class="stats-section__title">Protocol Detail</h2>
                <div id="ss-proto-bars" class="stats-proto-bars"></div>
            </section>

            <section class="stats-section" id="ss-relay-section">
                <h2 class="stats-section__title">Relay</h2>
                <div class="stats-row">
                    <div class="stats-card">
                        <div class="stats-card__label">Relay Breakdown</div>
                        <div class="stats-card__desc">Packets relayed vs rejected by the smart relay engine</div>
                        <canvas id="sc-relay"></canvas>
                    </div>
                    <div class="stats-card">
                        <div class="stats-card__label">Rejection Reasons</div>
                        <div class="stats-card__desc">Why packets were not relayed</div>
                        <canvas id="sc-reject"></canvas>
                    </div>
                </div>
            </section>

            <section class="stats-section">
                <h2 class="stats-section__title">Traffic</h2>
                <div class="stats-row">
                    <div class="stats-card stats-card--full">
                        <div class="stats-card__label">Traffic (60 min)</div>
                        <div class="stats-card__desc">Packets per 5-minute bucket over the last hour</div>
                        <canvas id="sc-timeline"></canvas>
                    </div>
                </div>
            </section>

            <div id="stats-status-strip-host"></div>

        </div>`;

        const host = document.getElementById('stats-status-strip-host');
        if (host && window.StatusStrip) {
            this._statusStrip = new window.StatusStrip(host, 'TRAFFIC');
            this._statusStrip.mount();
        }
    }

    _initProtoToggle() {
        const toggle = document.getElementById('proto-toggle');
        if (!toggle || toggle.dataset.bound) return;
        toggle.dataset.bound = '1';
        toggle.addEventListener('click', e => {
            const btn = e.target.closest('[data-view]');
            if (!btn) return;
            toggle.querySelectorAll('.stats-toggle__btn').forEach(b => b.classList.remove('stats-toggle__btn--active'));
            btn.classList.add('stats-toggle__btn--active');
            const view = btn.dataset.view;
            const p = view === 'session' ? (this._protoSession || {}) : (this._protoAlltime || {});
            const t = view === 'session' ? (this._typesSession || {}) : (this._typesAlltime || {});
            const totalOverride = view === 'alltime' ? this._totalPackets : undefined;
            const sig = view === 'session' ? (this._signalSession || {}) : (this._signalAlltime || {});
            const rssiDist = view === 'session' ? (this._rssiDistSession || {}) : (this._rssiDistAlltime || {});
            const dr = view === 'session' ? (this._directRelayedSession || {}) : (this._directRelayedAlltime || {});
            this._updateProtocol(p, totalOverride);
            this._updateTypes(t);
            this._updateProtoBars(p);
            this._updateSignalNums(sig);
            this._updateRssiHist(rssiDist);
            this._updateQuality(sig);
            this._updateDirectRelayed(dr);
        });
    }

    _update(data) {
        const live = data.live || {};
        const traffic = data.traffic || {};
        const signal = data.signal || {};
        const network = data.network || {};
        const device = data.device || {};
        const directRelayed = data.direct_relayed || {};

        this._totalPackets = traffic.total_packets || 0;
        this._setText('ss-total', this._totalPackets.toLocaleString());
        this._setText('ss-nodes', network.total_nodes || 0);
        this._setText('ss-days', this._calcDays(data.first_packet_time, device.days_online));
        this._setText('ss-firmware', device.firmware || '--');

        this._setText('ss-uptime', this._formatUptime(device.uptime_seconds || 0));

        // Store both views for the toggle
        this._protoAlltime = live.protocols_alltime || traffic.protocol_distribution || {};
        this._typesAlltime = live.packet_types_alltime || traffic.type_distribution || {};
        this._protoSession = live.protocols || {};
        this._typesSession = live.packet_types || {};

        const h = live.rssi_histogram || {};
        this._signalAlltime = signal;
        this._signalSession = {
            best_rssi: live.best_rssi,
            avg_rssi: live.avg_rssi_session,
            best_snr: live.best_snr,
            avg_snr: live.avg_snr_session,
        };
        this._rssiDistAlltime = data.rssi_distribution || {};
        this._rssiDistSession = {
            buckets: ['Excellent', 'Good', 'Fair', 'Weak'],
            counts: [h.excellent || 0, h.good || 0, h.fair || 0, h.weak || 0],
        };
        this._directRelayedAlltime = directRelayed;
        this._directRelayedSession = {
            direct: live.direct_count || 0,
            relayed: live.relayed_count || 0,
        };

        const sessionTotal = Object.values(this._protoSession).reduce((a, b) => a + b, 0);
        const sessionHero = document.getElementById('ss-session-hero');
        if (sessionHero) {
            if (sessionTotal > 0) {
                sessionHero.style.display = '';
                this._setText('ss-session-count', sessionTotal.toLocaleString());
            } else {
                sessionHero.style.display = 'none';
            }
        }

        this._initProtoToggle();

        // Default display: whichever view the toggle is on
        const activeView = document.querySelector('#proto-toggle .stats-toggle__btn--active')?.dataset.view || 'alltime';
        const protoData = activeView === 'session' ? this._protoSession : this._protoAlltime;
        const typesData = activeView === 'session' ? this._typesSession : this._typesAlltime;
        const totalOverride = activeView === 'alltime' ? this._totalPackets : undefined;

        const sigData = activeView === 'session' ? this._signalSession : this._signalAlltime;
        const rssiDistData = activeView === 'session' ? this._rssiDistSession : this._rssiDistAlltime;
        const drData = activeView === 'session' ? this._directRelayedSession : this._directRelayedAlltime;

        this._updateRange(live, data.farthest_mesh);
        this._updateMeshCoreRange(data.farthest_meshcore);
        this._updateProtocol(protoData, totalOverride);
        this._updateTypes(typesData);
        this._updateSignalNums(sigData);
        this._updateRssiHist(rssiDistData);
        this._updateSnrHist(data.snr_distribution || {});
        this._updateQuality(sigData);
        this._updateDirectRelayed(drData);
        this._updateActiveNodes(network);
        this._updateRoles(network.roles || {});
        this._updateHwModels(network.hw_models || {});
        this._updateProtoBars(protoData);
        this._updateTimeline(data.traffic_timeline || {});
        this._updateRelay(data.relay || {});
        this._updateRejectReasons(data.relay || {});
        this._updateStatusStrip(traffic, network, device, data.relay || {});
    }

    _updateStatusStrip(traffic, network, device, relay) {
        if (!this._statusStrip) return;
        const total = traffic.total_packets || 0;
        const nodes = network.total_nodes || 0;
        const region = device.region || 'region n/a';
        const relayed = relay.relayed ?? relay.relayed_count ?? 0;
        const rejected = relay.rejected ?? relay.rejected_count ?? 0;
        const relayLine = relay.enabled
            ? `relay ${relayed} ok / ${rejected} blocked`
            : 'relay off';
        this._statusStrip.update(
            [
                'concentrator',
                `${total.toLocaleString()} pkts`,
                `${nodes} nodes`,
                region,
                relayLine,
            ],
            this._fetchedAt,
        );
    }

    _setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    _formatUptime(seconds) {
        if (seconds < 60) return `${seconds}s`;
        if (seconds < 3600) {
            return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
        }
        if (seconds < 86400) {
            return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
        }
        return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
    }

    _calcDays(firstPacketTime, fallback) {
        if (firstPacketTime) {
            const first = new Date(firstPacketTime);
            const now = new Date();
            return Math.max(1, Math.floor((now - first) / 86400000));
        }
        return fallback || 0;
    }

    _updateSignalNums(signal) {
        const s = signal || {};
        this._setText('ss-best-rssi', s.best_rssi != null ? `${s.best_rssi} dBm` : '--');
        this._setText('ss-avg-rssi',  s.avg_rssi  != null ? `${s.avg_rssi} dBm`  : '--');
        this._setText('ss-best-snr',  s.best_snr  != null ? `${s.best_snr} dB`   : '--');
        this._setText('ss-avg-snr',   s.avg_snr   != null ? `${s.avg_snr} dB`    : '--');
    }

    _updateRange(live, farthestMesh) {
        const fd = live.farthest_direct;
        if (fd && fd.miles > 0) {
            const formatted = MeshpointDisplayUnits.formatDistanceKm(fd.miles * 1.60934) || `${fd.miles.toFixed(1)} mi`;
            this._setText('ss-direct-mi', formatted);
            this._setText('ss-direct-unit', '');
            const detail = [];
            if (fd.snr != null) detail.push(`SNR ${fd.snr} dB`);
            else if (fd.rssi) detail.push(`${fd.rssi} dBm`);
            if (fd.node_name || fd.node_id) detail.push(fd.node_name || fd.node_id);
            this._setText('ss-direct-detail', detail.join('  ·  '));
            const bar = document.getElementById('ss-direct-bar');
            if (bar) bar.style.width = `${Math.min(100, (fd.miles / 200) * 100)}%`;
        } else {
            this._setText('ss-direct-unit', '');
        }

        if (farthestMesh && farthestMesh.miles > 0) {
            const formatted = MeshpointDisplayUnits.formatDistanceKm(farthestMesh.miles * 1.60934) || `${farthestMesh.miles.toFixed(1)} mi`;
            this._setText('ss-mesh-mi', formatted);
            this._setText('ss-mesh-unit', '');
            this._setText('ss-mesh-detail', farthestMesh.node_name || farthestMesh.node_id || '');
            const bar = document.getElementById('ss-mesh-bar');
            if (bar) bar.style.width = `${Math.min(100, (farthestMesh.miles / 300) * 100)}%`;
        } else {
            this._setText('ss-mesh-unit', '');
        }
    }

    _updateMeshCoreRange(farthest) {
        if (farthest && farthest.miles > 0) {
            const formatted = MeshpointDisplayUnits.formatDistanceKm(farthest.miles * 1.60934) || `${farthest.miles.toFixed(1)} mi`;
            this._setText('ss-mc-mi', formatted);
            this._setText('ss-mc-unit', '');
            this._setText('ss-mc-detail', farthest.node_name || farthest.node_id || '');
            const bar = document.getElementById('ss-mc-bar');
            if (bar) bar.style.width = `${Math.min(100, (farthest.miles / 300) * 100)}%`;
        } else {
            this._setText('ss-mc-unit', '');
        }
    }

    _updateProtocol(protocols, overrideTotal) {
        const labels = Object.keys(protocols);
        const values = Object.values(protocols);
        const total = overrideTotal != null ? overrideTotal : values.reduce((a, b) => a + b, 0);
        this._renderDoughnut('sc-protocol', labels, values, chartColors(), total);
    }

    _updateTypes(types) {
        const sorted = Object.entries(types).sort((a, b) => b[1] - a[1]);
        const labels = sorted.map(e => e[0]);
        const values = sorted.map(e => e[1]);
        this._renderHorizontalBar('sc-types', labels, values);
    }

    _updateRssiHist(dist) {
        const buckets = dist.buckets || [];
        const counts = dist.counts || [];
        this._renderChart('sc-rssi', 'bar', {
            labels: buckets,
            datasets: [{
                data: counts,
                backgroundColor: chartSeries('rssi') + '99',
                borderColor: chartSeries('rssi'),
                borderWidth: 1,
            }],
        }, { plugins: { legend: { display: false } } });
    }

    _updateSnrHist(dist) {
        const buckets = dist.buckets || [];
        const counts = dist.counts || [];
        this._renderChart('sc-snr', 'bar', {
            labels: buckets,
            datasets: [{
                data: counts,
                backgroundColor: chartSeries('snr') + '99',
                borderColor: chartSeries('snr'),
                borderWidth: 1,
            }],
        }, { plugins: { legend: { display: false } } });
    }

    _updateQuality(signal) {
        const avgRssi = signal.avg_rssi;
        if (avgRssi == null) return;
        const quality = Math.max(0, Math.min(100, ((avgRssi + 130) / 90) * 100));
        const remaining = 100 - quality;
        const color = chartStatus(quality);
        this._renderChart('sc-quality', 'doughnut', {
            labels: ['Signal', ''],
            datasets: [{
                data: [quality, remaining],
                backgroundColor: [color, this._ink().border],
                borderWidth: 0,
            }],
        }, {
            cutout: '75%',
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false },
            },
        }, `${avgRssi} dBm`);
    }

    _updateDirectRelayed(dr) {
        const direct = dr.direct || 0;
        const relayed = dr.relayed || 0;
        const total = direct + relayed;
        this._renderDoughnut('sc-direct-relayed',
            ['Direct', 'Relayed'],
            [direct, relayed],
            [chartColors()[0], chartColors()[3]],
            total > 0 ? total.toLocaleString() : '0',
        );
    }

    _updateActiveNodes(network) {
        const active = network.active_24h || 0;
        const total = network.total_nodes || 0;
        const inactive = Math.max(0, total - active);
        this._renderDoughnut('sc-active-nodes',
            [`${active} active`, `${inactive} inactive`],
            [active, inactive],
            [chartStatus('ok'), this._ink().border],
            `${active} / ${total}`,
        );
    }

    _updateRoles(roles) {
        const card = document.getElementById('ss-roles-card');
        const entries = Object.entries(roles);
        if (entries.length === 0) {
            if (card) card.style.display = 'none';
            this._reconcileNetworkSection();
            return;
        }
        if (card) card.style.display = '';
        const labels = entries.map(([k]) => ROLE_NAMES[k] || k);
        const values = entries.map(([, v]) => v);
        const total = values.reduce((a, b) => a + b, 0);
        this._renderDoughnut('sc-roles', labels, values, chartColors(), total);
        this._reconcileNetworkSection();
    }

    _updateHwModels(hw) {
        const card = document.getElementById('ss-hw-card');
        const entries = Object.entries(hw);
        if (entries.length === 0) {
            if (card) card.style.display = 'none';
            this._reconcileNetworkSection();
            return;
        }
        if (card) card.style.display = '';
        const labels = entries.map(([k]) => HW_NAMES[k] || k);
        const values = entries.map(([, v]) => v);
        const total = values.reduce((a, b) => a + b, 0);
        this._renderDoughnut('sc-hw', labels, values, chartColors(), total);
        this._reconcileNetworkSection();
    }

    _reconcileNetworkSection() {
        const section = document.getElementById('ss-network-section');
        if (!section) return;
        const rolesVisible = document.getElementById('ss-roles-card')?.style.display !== 'none';
        const hwVisible = document.getElementById('ss-hw-card')?.style.display !== 'none';
        section.style.display = rolesVisible || hwVisible ? '' : 'none';
    }

    _updateProtoBars(protocols) {
        const container = document.getElementById('ss-proto-bars');
        if (!container) return;
        const entries = Object.entries(protocols).sort((a, b) => b[1] - a[1]);
        const maxVal = entries.length > 0 ? entries[0][1] : 1;
        container.innerHTML = entries.map(([name, count]) => {
            const pct = Math.max(1, (count / maxVal) * 100);
            return `<div class="stats-proto-row">
                <span class="stats-proto-name">${name}</span>
                <div class="stats-proto-track"><div class="stats-proto-fill" style="width:${pct}%"></div></div>
                <span class="stats-proto-count">${count.toLocaleString()}</span>
            </div>`;
        }).join('');
    }

    _updateTimeline(timeline) {
        const labels = timeline.labels || [];
        const counts = timeline.counts || [];
        this._renderChart('sc-timeline', 'bar', {
            labels,
            datasets: [{
                data: counts,
                backgroundColor: chartSeries('airutil') + '99',
                borderColor: chartSeries('airutil'),
                borderWidth: 1,
            }],
        }, { plugins: { legend: { display: false } } });
    }

    _updateRelay(relay) {
        const section = document.getElementById('ss-relay-section');
        const relayed = relay.relayed || 0;
        const rejected = relay.rejected || 0;
        if (!relay.enabled || (relayed === 0 && rejected === 0)) {
            if (section) section.style.display = 'none';
            return;
        }
        if (section) section.style.display = '';
        this._renderDoughnut('sc-relay',
            ['Relayed', 'Rejected'],
            [relayed, rejected],
            [chartStatus('ok'), chartStatus('bad')],
        );
    }

    _updateRejectReasons(relay) {
        const reasons = relay.rejection_reasons || {};
        const labels = Object.keys(reasons);
        const values = Object.values(reasons);
        if (labels.length === 0) return;
        this._renderHorizontalBar('sc-reject', labels, values, chartStatus('bad'));
    }

    _renderDoughnut(canvasId, labels, values, colors, centerText) {
        const data = {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 0,
            }],
        };

        // If chart already exists, update data and center text in place.
        // Center text is stored on the chart instance so the plugin can always
        // read the latest value — avoids the stale-closure problem.
        if (this._charts[canvasId]) {
            const chart = this._charts[canvasId];
            if (centerText != null) chart._meshCenterText = centerText;
            chart.data = data;
            chart.update('none');
            return;
        }

        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const centerPlugin = {
            id: `center-${canvasId}`,
            afterDraw(chart) {
                if (chart._meshCenterText == null) return;
                const { ctx, chartArea } = chart;
                if (!chartArea) return;
                const cx = (chartArea.left + chartArea.right) / 2;
                const cy = (chartArea.top + chartArea.bottom) / 2;
                ctx.save();
                ctx.font = 'bold 16px "JetBrains Mono", monospace';
                ctx.fillStyle = this._ink().text;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(chart._meshCenterText), cx, cy);
                ctx.restore();
            },
        };

        const opts = {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: this._ink().fg,
                        font: { size: 11 },
                        padding: 8,
                        usePointStyle: true,
                        pointStyleWidth: 8,
                    },
                },
            },
        };

        const chart = new Chart(canvas, { type: 'doughnut', data, options: opts, plugins: [centerPlugin] });
        chart._meshCenterText = centerText;
        this._charts[canvasId] = chart;
    }

    _renderHorizontalBar(canvasId, labels, values, color) {
        const barColor = color || chartSeries('rssi');
        this._renderChart(canvasId, 'bar', {
            labels,
            datasets: [{
                data: values,
                backgroundColor: barColor + '99',
                borderColor: barColor,
                borderWidth: 1,
            }],
        }, {
            indexAxis: 'y',
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { color: this._ink().faint, precision: 0 }, grid: { color: this._ink().grid } },
                y: { ticks: { color: this._ink().fg, font: { size: 11 } }, grid: { display: false } },
            },
        });
    }

    _ink() {
        return (window.ChartTheme && window.ChartTheme.ink()) || {
            fg: '#94a3b8', faint: '#64748b', grid: 'rgba(30, 41, 59, 0.5)', text: '#e2e8f0', border: '#233049',
        };
    }

    _renderChart(canvasId, type, data, extraOpts, centerLabel, extraPlugins) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        if (this._charts[canvasId]) {
            const chart = this._charts[canvasId];
            // centerLabel was accepted here but never actually used on the
            // update path -- _updateQuality's "NN dBm" center text (unlike
            // _renderDoughnut's charts, which store/redraw it the same way)
            // was silently dropped on every refresh after the first render.
            if (centerLabel != null) chart._meshCenterText = centerLabel;
            chart.data = data;
            chart.update('none');
            return;
        }

        const baseOpts = {
            responsive: true,
            maintainAspectRatio: false,
            scales: type === 'bar' && !(extraOpts && extraOpts.indexAxis) ? {
                x: { ticks: { color: this._ink().faint, font: { size: 10 } }, grid: { color: this._ink().grid } },
                y: { ticks: { color: this._ink().faint }, grid: { color: this._ink().grid } },
            } : undefined,
        };

        const opts = { ...baseOpts, ...(extraOpts || {}) };
        const plugins = extraPlugins || [];

        // Same center-text-drawing plugin _renderDoughnut() already has for
        // its two donuts -- _renderChart() accepted a centerLabel param but
        // never actually drew it anywhere, so "Avg Signal Quality" (the one
        // caller that passes one) rendered as a bare ring with no reading.
        if (centerLabel != null) {
            plugins.push({
                id: `center-${canvasId}`,
                afterDraw(chart) {
                    if (chart._meshCenterText == null) return;
                    const { ctx, chartArea } = chart;
                    if (!chartArea) return;
                    const cx = (chartArea.left + chartArea.right) / 2;
                    const cy = (chartArea.top + chartArea.bottom) / 2;
                    ctx.save();
                    ctx.font = 'bold 16px "JetBrains Mono", monospace';
                    ctx.fillStyle = this._ink().text;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(String(chart._meshCenterText), cx, cy);
                    ctx.restore();
                },
            });
        }

        this._charts[canvasId] = new Chart(canvas, { type, data, options: opts, plugins });
        if (centerLabel != null) this._charts[canvasId]._meshCenterText = centerLabel;
    }
}

window.statsTab = new StatsTab('stats-panel');
