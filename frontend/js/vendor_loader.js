/* Lazy vendor loader (UI quick-wins: route-scoped third-party JS).
 *
 * Chart.js (200 KB), the six xterm bundles (~380 KB), qrcode (24 KB)
 * and leaflet.markercluster (34 KB) are each used by exactly one or two
 * routes, yet until now they parsed on every dashboard boot. This file
 * removes them from index.html and loads each one on demand:
 *
 *   - the hash router warms a route's vendors on navigation
 *     (MeshpointVendor.warmFor), so the panel's own code usually finds
 *     the library already present;
 *   - consumer call sites keep a `!window.X` guard that calls
 *     ensure(name) and retries — so the race where a panel renders
 *     before the warm resolves degrades into "first paint missing,
 *     redraw when loaded" instead of a ReferenceError.
 *
 * Script order inside a vendor is guaranteed (sequential injection);
 * the promise is cached so ensure() is idempotent and free. External
 * plugin/theme URLs are NOT handled here — only the vendored files
 * listed below, resolved relative to the site root like index.html
 * did before.
 */
(function () {
    'use strict';

    const VENDOR_SCRIPTS = {
        chart: ['vendor/chartjs/chart.umd.min.js'],
        qrcode: ['vendor/qrcode/qrcode.min.js'],
        markercluster: ['vendor/markercluster/leaflet.markercluster.js'],
        xterm: [
            'vendor/xterm/xterm.js',
            'vendor/xterm/xterm-addon-fit.js',
            'vendor/xterm/xterm-addon-webgl.js',
            'vendor/xterm/xterm-addon-search.js',
            'vendor/xterm/xterm-addon-web-links.js',
            'vendor/xterm/xterm-addon-unicode11.js',
        ],
    };

    // First path segment of the hash route -> vendors to warm. Panels
    // that use a vendor off-route (node drawer's metrics chart opens on
    // any route) still work through the consumer-side ensure() guards.
    const ROUTE_VENDORS = {
        dashboard: ['markercluster', 'chart'],
        stats: ['chart'],
        rf: ['chart'],
        radio: ['chart'],
        topology: [],
        terminal: ['xterm'],
        configuration: ['qrcode', 'chart'],
        settings: [],
    };

    const cache = new Map();   // name -> Promise

    function loadOne(url) {
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = url;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('vendor load failed: ' + url));
            document.head.appendChild(s);
        });
    }

    function ensure(name) {
        if (cache.has(name)) return cache.get(name);
        const urls = VENDOR_SCRIPTS[name];
        if (!urls) return Promise.reject(new Error('unknown vendor: ' + name));
        const p = urls
            .reduce((chain, url) => chain.then(() => loadOne(url)), Promise.resolve())
            .then(() => {
                // Chart.js only became themable after it existed;
                // chart_theme.js bailed at boot with a !window.Chart
                // guard, so push the palette now that defaults exist.
                if (name === 'chart' && window.ChartTheme) {
                    try { window.ChartTheme.applyDefaults(); } catch (_) { /* noop */ }
                }
            })
            .catch((err) => { cache.delete(name); throw err; });
        cache.set(name, p);
        return p;
    }

    function warmForRoute(route) {
        const root = (route || '').split('/')[0];
        (ROUTE_VENDORS[root] || []).forEach((name) => {
            ensure(name).catch(() => { /* consumer guards report it */ });
        });
    }

    // Router-agnostic: the hash is the single source of truth, so
    // listen to hashchange directly and warm on boot too. (sidebar
    // navigation is exactly this event.)
    window.addEventListener('hashchange', () => {
        warmForRoute((location.hash || '').replace(/^#\/?/, '').trim());
    });
    warmForRoute((location.hash || '').replace(/^#\/?/, '').trim() || 'dashboard');

    window.MeshpointVendor = { ensure, warmFor: warmForRoute };
})();
