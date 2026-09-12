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

window.getMapTileUrl = getMapTileUrl;
