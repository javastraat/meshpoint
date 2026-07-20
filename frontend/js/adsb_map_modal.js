/**
 * Modal showing currently-tracked ADS-B aircraft over a live OpenStreetMap
 * (Leaflet + the same CARTO dark tiles topology_tab.js already uses for the
 * node map, so the app has exactly one basemap style). Reuses the
 * pdm-overlay/pdm-modal shell (packet_detail_modal.css) with the
 * wide/flush-body modifiers so the map can fill the dialog.
 *
 * Polls /api/adsb/status itself on a 2 s timer while open -- independent of
 * whether AdsbPanel's own tab happens to be mounted -- and tears the
 * Leaflet instance down on close() (L.map() throws "already initialized"
 * if reused against a stale container, so the map is always rebuilt fresh
 * against a new <div> each time show() runs).
 *
 * The plane marker is a rotated "navigation arrow" (feather-icons style --
 * matches the sidebar's own stroke-based SVG icon language, see
 * frontend/index.html's .sidebar__icon svgs) pointed by `track`, not a
 * literal reuse of dump1090's bundled Google-Maps plane silhouette
 * (dump1090/public_html/planeObject.js `funcGetIcon`) since that's a
 * `google.maps.Symbol` path string tied to the Google Maps API we don't
 * use here. What IS borrowed from planeObject.js: rotate-by-track, the
 * emergency squawk color convention (7500 hijack / 7600 radio failure /
 * 7700 general emergency), and its "stale after 15s unseen" dimming rule.
 */
class AdsbMapModal {
    constructor() {
        this._overlay = null;
        this._map = null;
        this._layer = null;
        this._pollTimer = null;
        this._fitted = false;
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    show() {
        if (this._overlay) return; // already open

        const overlay = document.createElement('div');
        overlay.className = 'pdm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'ADS-B aircraft map');

        const modal = document.createElement('div');
        modal.className = 'pdm-modal pdm-modal--wide';
        modal.addEventListener('click', (e) => e.stopPropagation());
        modal.innerHTML = `
            <header class="pdm-modal__header">
                <div>
                    <h2 class="pdm-modal__title">Aircraft map</h2>
                    <div class="pdm-modal__meta" data-adsb-map-meta>0 aircraft</div>
                </div>
                <button type="button" class="pdm-modal__close" aria-label="Close">&times;</button>
            </header>
            <div class="pdm-modal__body pdm-modal__body--flush">
                <div class="adsb-map"></div>
            </div>
        `;
        modal.querySelector('.pdm-modal__close').addEventListener('click', () => this.close());
        overlay.addEventListener('click', () => this.close());
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;

        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.pdm-modal__close').focus();

        this._initMap(modal.querySelector('.adsb-map'));
        this._poll();
        this._pollTimer = setInterval(() => this._poll(), 2000);
    }

    close() {
        document.removeEventListener('keydown', this._onKeyDown);
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
        if (this._map) {
            this._map.remove();
            this._map = null;
            this._layer = null;
        }
        this._fitted = false;
        if (this._overlay) {
            this._overlay.remove();
            this._overlay = null;
        }
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') this.close();
    }

    _initMap(el) {
        if (!window.L) return; // leaflet not loaded yet -- nothing to draw into
        this._map = L.map(el, { zoomControl: true, scrollWheelZoom: true });
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; CARTO &copy; OpenStreetMap contributors',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(this._map);
        this._layer = L.layerGroup().addTo(this._map);
        this._map.setView([52.37, 4.89], 8); // same default center as topology_tab.js
        // Leaflet measures its container on init; the modal has only just
        // been attached to the DOM this same tick.
        setTimeout(() => { if (this._map) this._map.invalidateSize(); }, 50);
    }

    async _poll() {
        try {
            const res = await fetch('/api/adsb/status');
            if (!res.ok) return;
            const status = await res.json();
            this._render(status);
        } catch (_e) { /* transient network hiccup -- next poll retries */ }
    }

    _render(status) {
        if (!this._map || !this._layer || !this._overlay) return;
        const metric = !!status.metric;
        const aircraft = status.aircraft || [];
        this._layer.clearLayers();

        const placed = aircraft.filter((a) => a.lat != null && a.lon != null);
        const meta = this._overlay.querySelector('[data-adsb-map-meta]');
        if (meta) {
            meta.textContent = placed.length === aircraft.length
                ? `${aircraft.length} aircraft`
                : `${placed.length} of ${aircraft.length} aircraft positioned`;
        }

        const bounds = [];
        placed.forEach((a) => {
            bounds.push([a.lat, a.lon]);
            const marker = L.marker([a.lat, a.lon], { icon: this._icon(a) }).addTo(this._layer);
            marker.bindTooltip(this._tooltipHtml(a, metric), { direction: 'top', offset: [0, -8] });
        });

        if (bounds.length && !this._fitted) {
            this._map.fitBounds(bounds, { padding: [40, 40], maxZoom: 10 });
            this._fitted = true;
        }
    }

    _icon(a) {
        const squawk = String(a.squawk || '');
        const stale = (a.seen || 0) > 15;
        let color = '#22d3ee'; // accent-cyan -- normal aircraft
        if (squawk === '7500') color = '#f87171'; // hijack
        else if (squawk === '7600') color = '#60a5fa'; // radio failure
        else if (squawk === '7700') color = '#fbbf24'; // general emergency
        else if (stale) color = 'rgba(139, 154, 171, 0.6)';
        const rotation = a.track != null ? a.track : 0;
        const html = `<svg viewBox="0 0 24 24" width="20" height="20" `
            + `style="transform: rotate(${rotation}deg)" fill="${color}" fill-opacity="0.9" `
            + `stroke="${color}" stroke-width="1" stroke-linejoin="round">`
            + `<polygon points="12 2 20 21 12 17 4 21"/></svg>`;
        return L.divIcon({
            html,
            className: 'adsb-marker',
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        });
    }

    _tooltipHtml(a, metric) {
        const label = a.flight ? this._esc(a.flight) : this._esc(a.hex || '');
        const alt = a.altitude != null ? `${a.altitude} ${metric ? 'm' : 'ft'}` : '—';
        const speed = a.speed != null ? `${a.speed} ${metric ? 'km/h' : 'kt'}` : '—';
        return `<strong>${label}</strong><br>${this._esc(a.hex || '')} · ${alt} · ${speed}`;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.AdsbMapModal = new AdsbMapModal();
