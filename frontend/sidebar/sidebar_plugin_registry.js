/*
 * Plugin seam for top-level sidebar pages.
 *
 * Two halves feed this, both injected before app.js runs (server-side, from
 * src/plugins/assets.py):
 *
 *   1. A <script> per sidebar-capable plugin, generated from its
 *      plugin.toml [sidebar] table, pushing a descriptor onto
 *      window.MESHPOINT_SIDEBAR_PLUGINS -- {id, route, label, category, icon}.
 *   2. The plugin's own frontend script, calling:
 *
 *        window.registerSidebarPage({
 *            route: 'hello-world',      // must match plugin.toml's sidebar.route
 *            make: () => ({
 *                mount(rootEl) { rootEl.innerHTML = '<p>Hello, world.</p>'; },
 *                show() {},
 *                hide() {},
 *            }),
 *        });
 *
 * window.mountPluginSidebarPages(), called once from app.js *before* the
 * Router/SidebarController are constructed, builds the actual sidebar <li>
 * + content <section> for every descriptor that also got a matching
 * factory, mounts it, and returns [{routeId, panel}] so app.js can fold the
 * route ids into the Router's allowedRoutes and wire show/hide.
 *
 * category placement mirrors the real sidebar sections in index.html:
 *   "top" -- Dashboard's own tier, above "Networks" -- not a section at
 *     all (no data-category header exists for it), so this is its own
 *     special case in _findInsertionTarget() rather than a header lookup.
 *   "networks" / "radio" / "ops" -- flat item runs, identified by a
 *     data-category attribute on that section's <li class="sidebar__group-header">.
 *   "configuration" / "settings" -- the two collapsible submenus
 *     (<li class="sidebar__group" data-group="...">); the route is nested
 *     as "<category>/<route>", same convention as the built-in subitems
 *     (e.g. "settings/plugins").
 */

window.MESHPOINT_SIDEBAR_PLUGINS = window.MESHPOINT_SIDEBAR_PLUGINS || [];

(function () {
    const factories = {};

    window.registerSidebarPage = function registerSidebarPage({ route, make }) {
        factories[route] = make;
    };

    // Curated icon set for a plugin's sidebar item -- keyed by name, not
    // arbitrary SVG from plugin.toml (that would let a manifest inject
    // whatever markup it wants). Matches src/plugins/manifest.py's
    // KNOWN_SIDEBAR_ICONS exactly; add a key in both places together.
    // "chart"/"message"/"terminal"/"grid"/"topology"/"rf"/"pager"/"dapnet"/
    // "reticulum"/"lorawan"/"gear" are exact copies of this same file's own
    // Stats/Messages/Terminal/Dashboard/Topology/RF Environment/Pager/
    // DAPNET/Reticulum/LoRaWAN/Settings sidebar icons -- reuse, not new
    // geometry. "antenna"/"map"/"list" are well-known standard icon shapes
    // (wifi/map-pin/list) not sourced from elsewhere in this app. "plug" is
    // the original default, kept for anything not fitting the others.
    // "usb" is the RTL-SDR page's own icon, inherited from the built-in
    // Listener page's nav item -- a single fill path (not stroke-based
    // like every other entry here) in a much larger native viewBox, both
    // handled by _ICON_VIEWBOX/_iconSvg() below rather than redrawing it
    // to fit the standard 24x24 stroke style the rest share.
    // Everything after "gear" is a straight Lucide copy (see the comment
    // there). An unknown key renders as "plug" -- manifest.py already maps
    // it to "plug" with a warning, so a plugin asking for an icon from a
    // newer core still loads here.
    const _ICON_PATHS = {
        // USB dongle glyph (user-supplied file) -- RTL-SDR is literally a
        // USB stick, so this reads clearer than a generic antenna. Single
        // fill path, fill swapped to currentColor same as every other
        // icon here. Provenance/license unconfirmed; generic pictogram,
        // no brand mark.
        usb: '<path fill="currentColor" d="M60.18,24.74l0.86,0.86L84.54,2.11C85.94,0.71,87.8,0,89.66,0h0.01h0.01h0.01c1.86,0.01,3.71,0.71,5.11,2.11l25.91,25.91 c1.41,1.41,2.12,3.27,2.12,5.13c0,0.1-0.01,0.2-0.01,0.3c-0.07,1.76-0.77,3.5-2.11,4.84L97.22,61.77l0.92,0.92 c0.99,0.99,1.49,2.29,1.49,3.6c0,0.11-0.01,0.22-0.02,0.33c-0.07,1.19-0.56,2.36-1.47,3.26l-48.38,48.38 c-3.08,3.08-7.13,4.61-11.18,4.61c-4.05,0-8.1-1.54-11.18-4.61l-2.18-2.18L7.24,98.1l-2.63-2.63C1.54,92.4,0,88.35,0,84.3 c0-4.05,1.54-8.1,4.61-11.18l48.38-48.38c0.99-0.99,2.29-1.48,3.59-1.48l0.01,0v-0.01C57.89,23.25,59.19,23.75,60.18,24.74 L60.18,24.74z M37.63,79.35c1.47-1.47,3.39-1.55,4.95-0.64l1.31-1.31c0.03-1.46-0.54-2.89-1.07-4.23c-1.15-2.88-2.15-5.38,1.3-7.7 c-0.68-1.17-0.51-2.7,0.49-3.7c1.2-1.2,3.14-1.2,4.34,0c1.2,1.2,1.2,3.14,0,4.34c-0.86,0.86-2.12,1.11-3.2,0.72l0.02,0.03 c-0.4,0.23-0.72,0.47-0.98,0.71c-1.45,1.39-0.81,3-0.07,4.83c0.04,0.11,0.09,0.22,0.13,0.33c0.35,0.88,0.7,1.81,0.91,2.79 L57.8,63.5l-1.62-1.62l-0.37-0.37l0.63-0.16l6.95-1.78l-1.94,7.59l-2.2-2.2l-9.18,9.18c0.99,0.2,1.92,0.54,2.82,0.9 c0.14,0.05,0.27,0.11,0.41,0.16c1.85,0.74,3.48,1.39,4.88-0.13c0.19-0.2,0.37-0.45,0.55-0.74l-1.03-1.03 c-0.17-0.17-0.17-0.46,0-0.63l3.81-3.81c0.17-0.17,0.45-0.17,0.63,0L66,72.74c0.17,0.17,0.17,0.45,0,0.63l-3.81,3.81 c-0.17,0.17-0.45,0.17-0.63,0l-1.35-1.35c-2.31,3.43-4.81,2.43-7.68,1.28c-1.37-0.55-2.85-1.14-4.35-1.07l-4.14,4.14 c0.92,1.56,0.83,3.48-0.64,4.95c-1.47,1.47-4.18,1.6-5.77,0C36.04,83.53,36.16,80.82,37.63,79.35L37.63,79.35z M13.15,95.57 c0.16,0.11,0.31,0.23,0.45,0.37l13.79,13.79c0.14,0.14,0.26,0.29,0.37,0.45l3.87,3.87c1.91,1.91,4.43,2.87,6.96,2.87 c2.52,0,5.05-0.96,6.96-2.87L93.3,66.29L56.59,29.58L8.83,77.34c-1.91,1.91-2.87,4.43-2.87,6.96c0,2.52,0.96,5.05,2.87,6.96 L13.15,95.57L13.15,95.57z M100.67,36.81L100.67,36.81c1.26,1.26,1.26,3.32,0,4.57l-4.23,4.23c-1.26,1.26-3.32,1.26-4.57,0l0,0 c-1.26-1.26-1.26-3.31,0-4.57l4.23-4.23C97.36,35.55,99.42,35.55,100.67,36.81L100.67,36.81z M87,23.13L87,23.13 c1.26,1.26,1.26,3.32,0,4.57l-4.23,4.23c-1.26,1.26-3.32,1.26-4.57,0l0,0c-1.26-1.26-1.26-3.31,0-4.57l4.23-4.23 C83.68,21.88,85.74,21.88,87,23.13L87,23.13z M116.49,32.24L90.58,6.33C90.33,6.07,90,5.95,89.68,5.95v0l-0.02,0 c-0.32,0-0.65,0.13-0.91,0.38L65.32,29.76l27.74,27.74l23.43-23.43c0.22-0.22,0.35-0.51,0.38-0.79c0-0.04,0-0.08,0-0.12 C116.86,32.82,116.74,32.48,116.49,32.24L116.49,32.24z"/>',
        plug: '<path d="M9 2v4M15 2v4M7 8h10l-1 6a4 4 0 0 1-4 4h0a4 4 0 0 1-4-4z"/>'
            + '<path d="M12 18v4"/>',
        antenna: '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/>'
            + '<path d="M5 12.859a10 10 0 0 1 14 0"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/>',
        chart: '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/>'
            + '<line x1="6" y1="20" x2="6" y2="16"/>',
        message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
        terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
        map: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
        list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>'
            + '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>'
            + '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
        grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>'
            + '<rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
        topology: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/>'
            + '<circle cx="19" cy="19" r="2"/><line x1="12" y1="7" x2="5" y2="17"/>'
            + '<line x1="12" y1="7" x2="19" y2="17"/><line x1="5" y1="19" x2="19" y2="19"/>',
        rf: '<path d="M4 18v-4"/><path d="M8 18V8"/><path d="M12 18v-6"/>'
            + '<path d="M16 18V4"/><path d="M20 18v-9"/>',
        pager: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>'
            + '<polyline points="22,6 12,13 2,6"/>',
        dapnet: '<path d="M17 7l2-3"/><rect x="5" y="7" width="14" height="13" rx="2"/>'
            + '<rect x="8" y="10" width="8" height="4" rx="0.5"/>'
            + '<circle cx="8" cy="17" r="0.6" fill="currentColor" stroke="none"/>'
            + '<circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none"/>'
            + '<circle cx="16" cy="17" r="0.6" fill="currentColor" stroke="none"/>',
        reticulum: '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/>'
            + '<circle cx="12" cy="18" r="2"/><path d="M6.7 7.3 10.3 16.3M17.3 7.3 13.7 16.3M7 6h10"/>',
        lorawan: '<path d="M2 12C2 12 5 5 12 5s10 7 10 7-3 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="2"/>',
        gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06,.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82,.33l-.06,.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06,.06a1.65 1.65 0 0 0 1.82,.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06,.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
        // Lucide v0.525.0 (ISC, https://lucide.dev), copied verbatim minus
        // React's per-element "key" attribute. "train" = Lucide train-front,
        // "home" = Lucide house.
        bluetooth: '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>',
        wifi: '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/><path d="M5 12.859a10 10 0 0 1 14 0"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/>',
        network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
        radio: '<path d="M16.247 7.761a6 6 0 0 1 0 8.478"/><path d="M19.075 4.933a10 10 0 0 1 0 14.134"/><path d="M4.925 19.067a10 10 0 0 1 0-14.134"/><path d="M7.753 16.239a6 6 0 0 1 0-8.478"/><circle cx="12" cy="12" r="2"/>',
        satellite: '<path d="m13.5 6.5-3.148-3.148a1.205 1.205 0 0 0-1.704 0L6.352 5.648a1.205 1.205 0 0 0 0 1.704L9.5 10.5"/><path d="M16.5 7.5 19 5"/><path d="m17.5 10.5 3.148 3.148a1.205 1.205 0 0 1 0 1.704l-2.296 2.296a1.205 1.205 0 0 1-1.704 0L13.5 14.5"/><path d="M9 21a6 6 0 0 0-6-6"/><path d="M9.352 10.648a1.205 1.205 0 0 0 0 1.704l2.296 2.296a1.205 1.205 0 0 0 1.704 0l4.296-4.296a1.205 1.205 0 0 0 0-1.704l-2.296-2.296a1.205 1.205 0 0 0-1.704 0z"/>',
        'satellite-dish': '<path d="M4 10a7.31 7.31 0 0 0 10 10Z"/><path d="m9 15 3-3"/><path d="M17 13a6 6 0 0 0-6-6"/><path d="M21 13A10 10 0 0 0 11 3"/>',
        signal: '<path d="M2 20h.01"/><path d="M7 20v-4"/><path d="M12 20v-8"/><path d="M17 20V8"/><path d="M22 4v16"/>',
        cpu: '<path d="M12 20v2"/><path d="M12 2v2"/><path d="M17 20v2"/><path d="M17 2v2"/><path d="M2 12h2"/><path d="M2 17h2"/><path d="M2 7h2"/><path d="M20 12h2"/><path d="M20 17h2"/><path d="M20 7h2"/><path d="M7 20v2"/><path d="M7 2v2"/><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1"/>',
        server: '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
        monitor: '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
        battery: '<path d="M 22 14 L 22 10"/><rect x="2" y="6" width="16" height="12" rx="2"/>',
        thermometer: '<path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"/>',
        zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
        plane: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
        ship: '<path d="M12 10.189V14"/><path d="M12 2v3"/><path d="M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6"/><path d="M19.38 20A11.6 11.6 0 0 0 21 14l-8.188-3.639a2 2 0 0 0-1.624 0L3 14a11.6 11.6 0 0 0 2.81 7.76"/><path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1s1.2 1 2.5 1c2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>',
        car: '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
        train: '<path d="M8 3.1V7a4 4 0 0 0 8 0V3.1"/><path d="m9 15-1-1"/><path d="m15 15 1-1"/><path d="M9 19c-2.8 0-5-2.2-5-5v-4a8 8 0 0 1 16 0v4c0 2.8-2.2 5-5 5Z"/><path d="m8 19-2 3"/><path d="m16 19 2 3"/>',
        cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
        wind: '<path d="M12.8 19.6A2 2 0 1 0 14 16H2"/><path d="M17.5 8a2.5 2.5 0 1 1 2 4H2"/><path d="M9.8 4.4A2 2 0 1 1 11 8H2"/>',
        globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
        compass: '<path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"/><circle cx="12" cy="12" r="10"/>',
        navigation: '<polygon points="3 11 22 2 13 21 11 13 3 11"/>',
        bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
        camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
        mic: '<path d="M12 19v3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><rect x="9" y="2" width="6" height="13" rx="3"/>',
        headphones: '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>',
        music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
        phone: '<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/>',
        users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>',
        shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
        lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
        clock: '<path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="10"/>',
        calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
        database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
        folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
        download: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
        activity: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
        eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
        star: '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
        flag: '<path d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528"/>',
        wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
        code: '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
        book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/>',
        home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
        search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
    };

    // Every icon shares the same 24x24 stroke-based viewBox except "usb",
    // drawn as a single fill path in its own much larger native
    // coordinate space (see _ICON_PATHS.usb's own comment).
    const _ICON_VIEWBOX = { usb: '0 0 122.83 122.88' };

    function _iconSvg(name) {
        const inner = _ICON_PATHS[name] || _ICON_PATHS.plug;
        const viewBox = _ICON_VIEWBOX[name] || '0 0 24 24';
        return `<svg viewBox="${viewBox}" fill="none" stroke="currentColor" `
            + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + inner + '</svg>';
    }

    function _escape(value) {
        return String(value || '').replace(/[&<>"']/g, (c) => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function _isNested(category) {
        return category === 'configuration' || category === 'settings';
    }

    /** Where to insert this category's new <li> -- {parent, before} (before
     * may be null, meaning "append at the end of parent"), or null if the
     * category's own anchor isn't in the DOM (shouldn't happen; every
     * KNOWN_SIDEBAR_CATEGORIES value has one in index.html). */
    function _findInsertionTarget(category) {
        if (category === 'top') {
            // Dashboard itself has no data-category header (it isn't a
            // section, just a bare <li> above "Networks") -- so this is a
            // special case rather than a header lookup like every other
            // category below. Anchor on the Dashboard link, then walk
            // forward the same way the header-based branch does, so a
            // second "top" plugin appends after the first one instead of
            // always landing directly under Dashboard and pushing earlier
            // "top" plugins down.
            const list = document.querySelector('.sidebar__nav .sidebar__list');
            const dashLink = list && list.querySelector('a[data-route="dashboard"]');
            const dashItem = dashLink && dashLink.closest('li');
            if (!dashItem) return null;
            let node = dashItem.nextElementSibling;
            while (
                node
                && !node.classList.contains('sidebar__group-header')
                && !node.classList.contains('sidebar__group')
            ) {
                node = node.nextElementSibling;
            }
            return { parent: list, before: node };
        }
        if (_isNested(category)) {
            const sublist = document.querySelector(
                `.sidebar__group[data-group="${category}"] .sidebar__sublist`,
            );
            return sublist ? { parent: sublist, before: null } : null;
        }
        const list = document.querySelector('.sidebar__nav .sidebar__list');
        const header = list && list.querySelector(
            `.sidebar__group-header[data-category="${category}"]`,
        );
        if (!header) return null;
        // Walk to the end of this section's run of items (next header/group
        // starts the next section; end of list = last section).
        let node = header.nextElementSibling;
        while (
            node
            && !node.classList.contains('sidebar__group-header')
            && !node.classList.contains('sidebar__group')
        ) {
            node = node.nextElementSibling;
        }
        return { parent: list, before: node };
    }

    function _buildLink(routeId, label, nested, icon) {
        const li = document.createElement('li');
        li.className = nested ? 'sidebar__subitem' : 'sidebar__item';
        const iconHtml = nested ? '' : `<span class="sidebar__icon">${_iconSvg(icon)}</span>`;
        // Same data-badge-for convention as the built-in sidebar items
        // (messages/radio/settings-updates in index.html) -- gives every
        // plugin sidebar page a status-badge slot via
        // SidebarController.setStatusBadge(routeId, ...), even though
        // only the rtlsdr plugin actually populates one today (see
        // sdr_status_badge.js). Hidden until a badge script sets it.
        li.innerHTML = `<a href="#/${routeId}" class="sidebar__link" data-route="${routeId}">` +
            `${iconHtml}<span class="sidebar__label">${_escape(label)}</span>` +
            `<span class="sidebar__badge" data-badge-for="${routeId}" style="display:none"></span></a>`;
        return li;
    }

    window.mountPluginSidebarPages = function mountPluginSidebarPages() {
        const mounted = [];
        const content = document.getElementById('app-content');
        if (!content) return mounted;

        window.MESHPOINT_SIDEBAR_PLUGINS.forEach((desc) => {
            const make = factories[desc.route];
            if (!make) {
                console.warn(
                    `Plugin sidebar page "${desc.route}" (${desc.id}) is declared in ` +
                    `plugin.toml but its frontend script never called registerSidebarPage().`,
                );
                return;
            }
            const target = _findInsertionTarget(desc.category);
            if (!target) {
                console.warn(
                    `Plugin sidebar page "${desc.route}" (${desc.id}): unknown category ` +
                    `"${desc.category}" -- not mounted.`,
                );
                return;
            }

            const nested = _isNested(desc.category);
            const routeId = nested ? `${desc.category}/${desc.route}` : desc.route;

            const li = _buildLink(routeId, desc.label, nested, desc.icon);
            if (target.before) target.parent.insertBefore(li, target.before);
            else target.parent.appendChild(li);

            const section = document.createElement('section');
            section.className = 'section';
            section.dataset.section = routeId;
            section.style.display = 'none';
            content.appendChild(section);

            let panel = null;
            try {
                panel = make();
                if (panel && typeof panel.mount === 'function') panel.mount(section);
            } catch (err) {
                console.error(`Plugin sidebar page "${routeId}" (${desc.id}) failed to mount:`, err);
            }

            mounted.push({ routeId, panel });
        });

        return mounted;
    };
})();
