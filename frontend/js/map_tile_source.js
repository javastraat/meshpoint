/**
 * Shared Leaflet tile URL source for every map on the dashboard (Dashboard
 * node map, Topology map). Reads `dashboard.map_tile_url` from GET
 * /api/config -- defaults to the public OSM tile server, same as this app
 * always hardcoded, but can be pointed at a local source instead (e.g. the
 * offline-map plugin's own `/api/offline-map/tiles/<collection>/<style>/
 * {z}/{x}/{y}.png`) for offline/emergency use.
 *
 * Fetched once per page load and cached -- every map on the page shares
 * the same source, and it isn't expected to change without a reload.
 */
const MAP_TILE_URL_FALLBACK = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

let _mapTileUrlPromise = null;

function getMapTileUrl() {
    if (!_mapTileUrlPromise) {
        _mapTileUrlPromise = fetch('/api/config', { credentials: 'same-origin' })
            .then((r) => (r.ok ? r.json() : null))
            .then((cfg) => (cfg && cfg.dashboard && cfg.dashboard.map_tile_url) || MAP_TILE_URL_FALLBACK)
            .catch(() => MAP_TILE_URL_FALLBACK);
    }
    return _mapTileUrlPromise;
}

// Callers add a tile layer with this SYNCHRONOUSLY, immediately at map
// construction, then swap it out once getMapTileUrl() resolves if it
// turns out to be something else. A map with zero tile layers has no
// maxZoom at all -- anything that runs before an async-only tileLayer.
// addTo() finishes (fitBounds, a saved-view setView, etc.) throws
// "Uncaught (in promise) Map has no maxZoom specified". Keeping this
// synchronous removes that race entirely rather than chasing every call
// site that could lose it.
window.MAP_TILE_URL_FALLBACK = MAP_TILE_URL_FALLBACK;
window.getMapTileUrl = getMapTileUrl;
