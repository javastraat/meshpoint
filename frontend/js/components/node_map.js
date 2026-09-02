/**
 * Leaflet map with marker clustering for the local Meshpoint dashboard.
 * Displays the Meshpoint device and captured nodes with protocol-colored markers.
 */

const MAP_VIEW_STORAGE_KEY = 'meshpoint.nodeMap.view';
const MAP_PROTO_STORAGE_KEY = 'meshpoint.nodeMap.protocols';
const MAP_CLUSTER_STORAGE_KEY = 'meshpoint.nodeMap.clustered';
const MAP_BASEMAP_STORAGE_KEY = 'meshpoint.nodeMap.basemap';
const MAP_DEFAULT_CENTER = [39.8, -98.5];
const MAP_DEFAULT_ZOOM = 4;

const PROTO_LABELS = {
    meshtastic: 'Meshtastic',
    meshcore: 'MeshCore',
    reticulum: 'Reticulum',
    lorawan: 'LoRaWAN',
    dapnet: 'DAPNET',
};

class NodeMap {
    constructor(containerId) {
        this._containerId = containerId;
        this._map = null;
        this._markerGroup = null;
        this._deviceMarker = null;
        this._markers = {};
        this._markerProto = {};       // node_id -> protocol
        this._seenProtocols = new Set();
        this._protoDummies = {};      // protocol -> dummy layer used as a control toggle
        this._enabledProtocols = this._loadEnabledProtocols();  // Set, or null = all
        this._clustered = this._loadClusterPref();
        this._basemapLight = this._loadBasemapPref();
        this._initialized = false;
        this._hasFitBounds = false;
        this._init();
    }

    _init() {
        const el = document.getElementById(this._containerId);
        if (!el) return;

        this._map = L.map(this._containerId, {
            zoomControl: true,
            scrollWheelZoom: true,
        });

        const savedView = this._loadSavedView();
        if (savedView) {
            this._map.setView(savedView.center, savedView.zoom);
            // Honor the user's saved view; skip the first-load auto-fit.
            this._hasFitBounds = true;
        } else {
            this._map.setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM);
        }

        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(this._map);

        this._applyBasemap();
        this._wireResizeRecalc();

        this._topologyLayer = L.layerGroup();
        this._topologyVisible = false;
        this._focusLine = null;

        this._clusterOpts = {
            maxClusterRadius: 50,
            disableClusteringAtZoom: 13,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            iconCreateFunction: (cluster) => {
                const count = cluster.getChildCount();
                let size = 'small';
                if (count > 50) size = 'large';
                else if (count > 10) size = 'medium';
                return L.divIcon({
                    html: `<div><span>${count}</span></div>`,
                    className: `marker-cluster marker-cluster-${size}`,
                    iconSize: L.point(40, 40),
                });
            },
        };
        this._buildMarkerGroup();

        this._layersControl = L.control.layers(
            null, { 'Topology Links': this._topologyLayer },
            { position: 'topright', collapsed: true },
        ).addTo(this._map);

        this._map.on('overlayadd', (e) => this._onOverlayToggle(e.layer, true));
        this._map.on('overlayremove', (e) => this._onOverlayToggle(e.layer, false));

        this._initialized = true;

        this._map.on('moveend', () => this._saveCurrentView());
        this._map.on('zoomend', () => this._saveCurrentView());

        if (window.MeshpointNodeFavorites) {
            window.MeshpointNodeFavorites.onChange(() => {
                if (this._lastNodes) {
                    this.loadNodes(this._lastNodes, this._lastDevice);
                }
            });
        }

        document.addEventListener('meshpoint:nodeCardsFilter', () => {
            if (this._lastNodes) {
                this.loadNodes(this._lastNodes, this._lastDevice);
            }
        });
    }

    _nodesForMapMarkers(nodes) {
        const filter = window.MeshpointNodeCardsSort
            ? window.MeshpointNodeCardsSort.readSavedFilter()
            : 'all';
        if (filter === 'all' || !window.MeshpointNodeCardsSort) {
            return nodes;
        }
        return window.MeshpointNodeCardsSort.applyFilter(nodes, filter);
    }

    _loadSavedView() {
        try {
            const raw = localStorage.getItem(MAP_VIEW_STORAGE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            const lat = Number(parsed.lat);
            const lon = Number(parsed.lon);
            const zoom = Number(parsed.zoom);
            if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(zoom)) {
                return null;
            }
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
            if (zoom < 0 || zoom > 19) return null;
            return { center: [lat, lon], zoom };
        } catch (_e) {
            return null;
        }
    }

    _saveCurrentView() {
        if (!this._map) return;
        try {
            const c = this._map.getCenter();
            localStorage.setItem(MAP_VIEW_STORAGE_KEY, JSON.stringify({
                lat: c.lat,
                lon: c.lng,
                zoom: this._map.getZoom(),
            }));
        } catch (_e) {
            /* private mode / quota -- best-effort persistence */
        }
    }

    // ---- marker group: cluster <-> flat -------------------------------

    _buildMarkerGroup() {
        if (this._markerGroup) {
            this._markerGroup.clearLayers();   // detach markers so they can be re-added
            this._map.removeLayer(this._markerGroup);
        }
        this._markerGroup = this._clustered
            ? L.markerClusterGroup(this._clusterOpts)
            : L.layerGroup();
        this._map.addLayer(this._markerGroup);
    }

    _groupAdd(markers) {
        if (!markers.length) return;
        if (this._markerGroup.addLayers) this._markerGroup.addLayers(markers);
        else markers.forEach((m) => this._markerGroup.addLayer(m));
    }

    _groupRemove(markers) {
        if (!markers.length) return;
        if (this._markerGroup.removeLayers) this._markerGroup.removeLayers(markers);
        else markers.forEach((m) => this._markerGroup.removeLayer(m));
    }

    /** Toggle clustering. Returns the new state. */
    toggleClustered() {
        this._clustered = !this._clustered;
        try { localStorage.setItem(MAP_CLUSTER_STORAGE_KEY, this._clustered ? 'on' : 'off'); } catch (_e) {}
        const visible = Object.keys(this._markers)
            .filter((id) => this._isProtocolEnabled(this._markerProto[id]))
            .map((id) => this._markers[id]);
        this._buildMarkerGroup();
        this._groupAdd(visible);
        return this._clustered;
    }

    isClustered() { return this._clustered; }

    _loadClusterPref() {
        try { return localStorage.getItem(MAP_CLUSTER_STORAGE_KEY) !== 'off'; }
        catch (_e) { return true; }
    }

    // ---- basemap: dark-inverted <-> native OSM colours ---------------

    _loadBasemapPref() {
        try {
            const v = localStorage.getItem(MAP_BASEMAP_STORAGE_KEY);
            if (v === 'light') return true;
            if (v === 'dark') return false;
        } catch (_e) { /* fall through */ }
        // No explicit choice yet: match what the theme would do today
        // (only the `light` theme ships a native basemap).
        return document.documentElement.getAttribute('data-theme') === 'light';
    }

    _applyBasemap() {
        const el = document.getElementById(this._containerId);
        if (!el) return;
        el.classList.toggle('map--basemap-light', this._basemapLight);
        el.classList.toggle('map--basemap-dark', !this._basemapLight);
    }

    /** Toggle the basemap between dark-inverted and native. Returns the new state (true = light). */
    toggleBasemap() {
        this._basemapLight = !this._basemapLight;
        try {
            localStorage.setItem(MAP_BASEMAP_STORAGE_KEY, this._basemapLight ? 'light' : 'dark');
        } catch (_e) { /* best-effort */ }
        this._applyBasemap();
        return this._basemapLight;
    }

    basemapIsLight() { return this._basemapLight; }

    // ---- per-protocol layer filter -----------------------------------

    _loadEnabledProtocols() {
        try {
            const raw = localStorage.getItem(MAP_PROTO_STORAGE_KEY);
            if (!raw || raw === 'all') return null;
            const arr = JSON.parse(raw);
            return Array.isArray(arr) ? new Set(arr) : null;
        } catch (_e) {
            return null;
        }
    }

    _saveEnabledProtocols() {
        try {
            localStorage.setItem(
                MAP_PROTO_STORAGE_KEY,
                this._enabledProtocols ? JSON.stringify([...this._enabledProtocols]) : 'all',
            );
        } catch (_e) { /* best-effort */ }
    }

    _isProtocolEnabled(proto) {
        return !this._enabledProtocols || this._enabledProtocols.has(proto);
    }

    _protoLabel(proto) {
        return PROTO_LABELS[proto] || (proto.charAt(0).toUpperCase() + proto.slice(1));
    }

    /** Add a checkbox to the layers control the first time a protocol appears. */
    _ensureProtocolOverlay(proto) {
        if (this._protoDummies[proto]) return;
        const dummy = L.layerGroup();
        this._protoDummies[proto] = dummy;
        // Adding to the map before addOverlay makes the checkbox render ticked.
        if (this._isProtocolEnabled(proto)) this._map.addLayer(dummy);
        this._layersControl.addOverlay(dummy, this._protoLabel(proto));
    }

    _onOverlayToggle(layer, on) {
        if (layer === this._topologyLayer) {
            this._topologyVisible = on;
            if (on) this._loadTopology();
            return;
        }
        const proto = Object.keys(this._protoDummies).find((p) => this._protoDummies[p] === layer);
        if (!proto) return;
        if (!this._enabledProtocols) this._enabledProtocols = new Set(this._seenProtocols);
        if (on) this._enabledProtocols.add(proto);
        else this._enabledProtocols.delete(proto);
        this._saveEnabledProtocols();
        this._applyProtocolFilter();
    }

    _applyProtocolFilter() {
        const toAdd = [];
        const toRemove = [];
        for (const id of Object.keys(this._markers)) {
            const marker = this._markers[id];
            const on = this._isProtocolEnabled(this._markerProto[id]);
            const inGroup = this._markerGroup.hasLayer(marker);
            if (on && !inGroup) toAdd.push(marker);
            else if (!on && inGroup) toRemove.push(marker);
        }
        this._groupRemove(toRemove);
        this._groupAdd(toAdd);
    }

    loadNodes(nodes, device) {
        if (!this._initialized) return;

        this._lastNodes = nodes;
        this._lastDevice = device;

        this._markerGroup.clearLayers();
        this._markers = {};
        this._markerProto = {};

        const bounds = [];

        if (device && device.latitude && device.longitude) {
            this._addDeviceMarker(device);
            bounds.push([device.latitude, device.longitude]);
        }

        const mapNodes = this._nodesForMapMarkers(nodes);
        for (const n of mapNodes) {
            const lat = n.latitude;
            const lon = n.longitude;
            if (lat == null || lon == null) continue;

            bounds.push([lat, lon]);
            this._addNodeMarker(n);
        }

        if (!this._hasFitBounds && bounds.length > 0) {
            if (bounds.length > 1) {
                this._map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
            } else {
                this._map.setView(bounds[0], 13);
            }
            this._hasFitBounds = true;
        }

        if (this._topologyVisible) {
            this._loadTopology();
        }
    }

    _addDeviceMarker(device) {
        if (this._deviceMarker) {
            const cur = this._deviceMarker.getLatLng();
            if (
                Math.abs(cur.lat - device.latitude) < 1e-6
                && Math.abs(cur.lng - device.longitude) < 1e-6
            ) {
                return;  // position unchanged; preserve existing marker + open popup
            }
            this._map.removeLayer(this._deviceMarker);
        }

        this._deviceMarker = L.marker([device.latitude, device.longitude], {
            icon: L.divIcon({
                html: '<div class="device-marker"></div>',
                className: '',
                iconSize: [16, 16],
                iconAnchor: [8, 8],
            }),
            zIndexOffset: 1000,
        });

        const name = device.device_name || 'Meshpoint';
        this._deviceMarker.bindPopup(
            `<strong>${this._esc(name)}</strong><br>` +
            `Type: Meshpoint<br>` +
            `Lat: ${device.latitude.toFixed(4)}<br>` +
            `Lon: ${device.longitude.toFixed(4)}`
        );

        this._deviceMarker.addTo(this._map);
    }

    _addNodeMarker(n) {
        const proto = n.protocol || 'meshtastic';
        const isMeshtastic = proto === 'meshtastic';
        const protoColor = isMeshtastic ? '#06b6d4' : '#a855f7';

        const heard = n.last_heard || n.last_seen;
        const isRecent = heard && (Date.now() - new Date(heard).getTime()) < 60000;
        const isFav = !!(window.MeshpointNodeFavorites && window.MeshpointNodeFavorites.has(n.node_id));

        let marker;
        if (isMeshtastic) {
            // Order of border color precedence: recent (green) > favorite (amber) > protocol (cyan).
            let borderColor = protoColor;
            if (isFav) borderColor = '#f59e0b';
            if (isRecent) borderColor = '#00ff88';
            marker = L.circleMarker([n.latitude, n.longitude], {
                radius: 6,
                fillColor: protoColor,
                fillOpacity: 0.8,
                color: borderColor,
                weight: (isRecent || isFav) ? 2 : 1,
                className: isRecent ? 'node-pulse' : '',
            });
            marker._meshpointKind = 'circle';
        } else {
            const recentClass = isRecent ? ' node-marker__diamond--recent' : '';
            const favClass = isFav ? ' node-marker__diamond--fav' : '';
            marker = L.marker([n.latitude, n.longitude], {
                icon: L.divIcon({
                    html: `<div class="node-marker__diamond${favClass}${recentClass}"></div>`,
                    className: '',
                    iconSize: [12, 12],
                    iconAnchor: [6, 6],
                }),
            });
            marker._meshpointKind = 'diamond';
        }

        const name = n.long_name || n.name || n.node_id || '--';
        const rssi = (n.rssi ?? n.latest_rssi) != null
            ? `${Number(n.rssi ?? n.latest_rssi).toFixed(0)} dBm` : '--';
        const lastHeard = this._formatRelativeTime(heard);

        marker.bindPopup(
            `<strong>${this._esc(name)}</strong><br>` +
            `Protocol: ${n.protocol || 'meshtastic'}<br>` +
            `RSSI: ${rssi}<br>` +
            `Last heard: ${lastHeard}`
        );

        this._markers[n.node_id] = marker;
        this._markerProto[n.node_id] = proto;
        this._seenProtocols.add(proto);
        this._ensureProtocolOverlay(proto);
        if (this._isProtocolEnabled(proto)) this._markerGroup.addLayer(marker);
    }

    _formatRelativeTime(timestamp) {
        if (!timestamp) return 'unknown';
        const t = new Date(timestamp).getTime();
        if (Number.isNaN(t)) return 'unknown';
        const diffMs = Date.now() - t;
        if (diffMs < 0) return 'just now';
        const sec = Math.floor(diffMs / 1000);
        if (sec < 60) return `${sec}s ago`;
        const min = Math.floor(sec / 60);
        if (min < 60) return `${min}m ago`;
        const hr = Math.floor(min / 60);
        if (hr < 24) return `${hr}h ago`;
        const days = Math.floor(hr / 24);
        return `${days}d ago`;
    }

    drawFocusLine(sourceNodeId) {
        this.clearFocusLine();
        if (!this._initialized || !this._deviceMarker) return;
        const srcMarker = this._markers[sourceNodeId];
        if (!srcMarker) return;

        this._focusLine = L.polyline(
            [srcMarker.getLatLng(), this._deviceMarker.getLatLng()],
            { color: '#f59e0b', weight: 3, opacity: 0.9 }
        ).addTo(this._map);
    }

    clearFocusLine() {
        if (this._focusLine) {
            this._map.removeLayer(this._focusLine);
            this._focusLine = null;
        }
    }

    centerOn(lat, lng, zoom = 15) {
        if (this._map) this._map.flyTo([lat, lng], zoom);
    }

    /** Recenter on the Meshpoint's own configured location, on demand
     * (the map-home-btn in the panel header) -- uses the same device
     * position loadNodes() already cached, so no separate fetch needed. */
    centerOnHome() {
        const device = this._lastDevice;
        if (device && device.latitude && device.longitude) {
            this.centerOn(device.latitude, device.longitude, 14);
        }
    }

    invalidateSize() {
        if (this._map) this._map.invalidateSize();
    }

    _wireResizeRecalc() {
        if (!this._map) return;

        requestAnimationFrame(() => {
            if (this._map) this._map.invalidateSize();
        });

        let resizeTimer = null;
        const recalc = () => {
            if (!this._map) return;
            this._map.invalidateSize();
        };

        window.addEventListener('resize', () => {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(recalc, 150);
        });

        document.addEventListener('sidebar:routeActivated', (event) => {
            if (event.detail && event.detail.route === 'dashboard') {
                requestAnimationFrame(recalc);
            }
        });

        if (typeof ResizeObserver === 'function') {
            const el = document.getElementById(this._containerId);
            if (el) {
                this._resizeObserver = new ResizeObserver(() => {
                    if (resizeTimer) clearTimeout(resizeTimer);
                    resizeTimer = setTimeout(recalc, 150);
                });
                this._resizeObserver.observe(el);
            }
        }
    }

    updateFromPacket(packet) {
        if (!packet.source_id || !this._initialized) return;
        const marker = this._markers[packet.source_id];
        if (!marker) return;

        const isMeshtastic = (packet.protocol || 'meshtastic') === 'meshtastic';
        const proto = isMeshtastic ? '#06b6d4' : '#a855f7';

        if (marker._meshpointKind === 'diamond') {
            const el = marker.getElement()?.querySelector('.node-marker__diamond');
            if (el) el.classList.add('node-marker__diamond--recent');
            this._drawPacketLine(marker);
            setTimeout(() => {
                const el2 = marker.getElement()?.querySelector('.node-marker__diamond');
                if (el2) el2.classList.remove('node-marker__diamond--recent');
            }, 5000);
            return;
        }

        // Default: circleMarker (Meshtastic).
        marker.setStyle({ color: '#00ff88', weight: 2 });
        this._drawPacketLine(marker);
        setTimeout(() => {
            const isFav = !!(window.MeshpointNodeFavorites
                && window.MeshpointNodeFavorites.has(packet.source_id));
            marker.setStyle({
                color: isFav ? '#f59e0b' : proto,
                weight: isFav ? 2 : 1,
            });
        }, 5000);
    }

    _drawPacketLine(sourceMarker) {
        if (!this._deviceMarker) return;
        const deviceLatLng = this._deviceMarker.getLatLng();
        const nodeLatLng = sourceMarker.getLatLng();

        const line = L.polyline([nodeLatLng, deviceLatLng], {
            color: '#00e5a0',
            weight: 2,
            opacity: 0.8,
            dashArray: '6, 4',
            className: 'packet-line',
        }).addTo(this._map);

        let opacity = 0.8;
        const fade = setInterval(() => {
            opacity -= 0.1;
            if (opacity <= 0) {
                clearInterval(fade);
                this._map.removeLayer(line);
            } else {
                line.setStyle({ opacity });
            }
        }, 200);
    }

    _showTopologyMapHint(show) {
        let el = document.getElementById('map-topology-hint');
        if (!el && this._map) {
            el = document.createElement('div');
            el.id = 'map-topology-hint';
            el.className = 'map-topology-hint';
            el.hidden = true;
            this._map.getContainer().appendChild(el);
        }
        if (!el) return;
        if (show) {
            el.textContent =
                'Links need GPS on both endpoints. Open the Topology tab for the logical graph.';
            el.hidden = false;
        } else {
            el.hidden = true;
        }
    }

    async _loadTopology() {
        try {
            // Same graph the Topology tab uses (traceroute chains + direct
            // hears + MeshCore neighbour rows). The old /api/analytics/topology
            // was NEIGHBORINFO-only, which modern firmware doesn't broadcast.
            const res = await fetch('/api/topology/graph', { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`topology ${res.status}`);
            const data = await res.json();
            const edges = Array.isArray(data.edges) ? data.edges : [];
            this._topologyLayer.clearLayers();

            // The graph lowercases node ids; markers are keyed by the nodes
            // API's casing. Match case-insensitively.
            const byLcId = {};
            for (const id of Object.keys(this._markers)) {
                byLcId[id.toLowerCase()] = this._markers[id];
            }

            const css = (name, fb) => {
                try {
                    const v = getComputedStyle(document.documentElement)
                        .getPropertyValue(name).trim();
                    return v || fb;
                } catch (_e) { return fb; }
            };
            const kindColor = {
                route: css('--accent-cyan', '#22d3ee'),
                direct: css('--accent-green', '#34d399'),
                neighbour: css('--accent-amber', '#fbbf24'),
            };
            const dimColor = css('--text-secondary', '#8b98a9');

            let drawn = 0;
            for (const e of edges) {
                const a = byLcId[String(e.a || '').toLowerCase()];
                const b = byLcId[String(e.b || '').toLowerCase()];
                if (!a || !b) continue;

                const line = L.polyline([a.getLatLng(), b.getLatLng()], {
                    color: kindColor[e.kind] || dimColor,
                    weight: 1.5,
                    opacity: 0.65,
                    dashArray: '4, 4',
                });
                const bits = [`${e.a} ↔ ${e.b}`, e.kind];
                if (e.rssi != null) bits.push(`RSSI: ${e.rssi} dBm`);
                if (e.snr != null) bits.push(`SNR: ${e.snr} dB`);
                line.bindTooltip(bits.filter(Boolean).join('<br>'));

                this._topologyLayer.addLayer(line);
                drawn += 1;
            }
            this._showTopologyMapHint(
                this._topologyVisible && edges.length > 0 && drawn === 0,
            );
        } catch (e) {
            console.error('Topology load failed:', e);
            this._showTopologyMapHint(false);
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str;
        return el.innerHTML;
    }
}
