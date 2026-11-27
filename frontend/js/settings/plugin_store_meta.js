/**
 * Plugin store card metadata (TODO 47a; look after upstream KMX415/meshpoint
 * plugin_store_data.js). Display only: what can be installed, and how, always
 * comes from the source's catalog (repo.json via /api/plugin-sources/catalog).
 * Known plugins get a store category, a one-line tagline and an icon; anything
 * else (another source, a new plugin) gets a sensible fallback, see
 * meshpointStoreMeta().
 */
(function () {
    // id: [category, tagline, icon]
    const KNOWN = {
        reticulum: ['Networks', 'Reticulum and LXMF messaging on your Meshpoint.', 'network'],
        'reticulum-browser': ['Networks', 'Browse NomadNet pages in tabs.', 'network'],
        'reticulum-call': ['Networks', 'Voice calls over Reticulum.', 'network'],
        'reticulum-dashboard': ['Networks', 'A live view of Reticulum activity.', 'network'],
        'reticulum-repeaters': ['Networks', 'Keep an eye on your microReticulum repeaters.', 'network'],
        'reticulum-scraper': ['Networks', 'Turn a website into offline Reticulum pages.', 'network'],
        localmesh: ['Networks', 'Hear LocalMesh through a USB receiver.', 'network'],
        'localmesh-bot': ['Networks', 'A command bot for LocalMesh.', 'network'],
        'localmesh-dashboard': ['Networks', 'A live view of LocalMesh activity.', 'network'],
        'localmesh-repeaters': ['Networks', 'What the LocalMesh repeaters report.', 'network'],
        rtlsdr: ['Radio', 'One place for all your RTL-SDR receivers.', 'spectrum'],
        radio: ['Radio', 'FM, AM and SSB in the browser, with RDS.', 'wave'],
        dab: ['Radio', 'DAB+ digital radio on your dashboard.', 'wave'],
        adsb: ['Aviation', 'See the air traffic overhead.', 'plane'],
        acars: ['Aviation', 'Read aircraft datalink messages.', 'plane'],
        rtl433: ['Sensors', 'Weather stations and 433 MHz sensors.', 'sensor'],
        'bluetooth-scanner': ['Sensors', 'A radar for nearby Bluetooth devices.', 'bluetooth'],
        p2000: ['Paging', 'Dutch emergency dispatch (P2000).', 'pager'],
        pagers: ['Paging', 'Pager messages on 172.45 MHz.', 'pager'],
        pocsag: ['Paging', 'Amateur POCSAG paging on 439.9875 MHz.', 'pager'],
        dapnet: ['Paging', 'Send and receive DAPNET pages.', 'pager'],
        'offline-map': ['Tools', 'Maps that work without internet.', 'map'],
        'oled-display': ['Tools', 'Status on a small OLED display.', 'display'],
        'raspberry-network': ['Tools', 'Switch WiFi from the dashboard.', 'wifi'],
        'hello-world-github': ['Examples', 'A minimal example plugin.', 'code'],
        'hello-world-github-hook': ['Examples', 'A minimal example hook.', 'code'],
    };

    /** Order of the filter chips; categories that no card uses are not shown. */
    window.MESHPOINT_STORE_CATEGORIES = [
        'Networks', 'Radio', 'Aviation', 'Sensors', 'Paging', 'Tools', 'Examples', 'Themes', 'Other',
    ];

    /** {category, tagline, icon} for a catalog entry (app or theme). */
    window.meshpointStoreMeta = function (entry) {
        const e = entry || {};
        if (e.kind === 'theme') return { category: 'Themes', tagline: e.description || '', icon: 'palette' };
        const known = KNOWN[e.id];
        if (known) return { category: known[0], tagline: known[1], icon: known[2] };
        // Unknown: an RTL-SDR hook is a receiver; otherwise "Other".
        const host = e.hook_host || e.requires || '';
        if (host === 'rtlsdr') return { category: 'Radio', tagline: e.description || '', icon: 'wave' };
        if (host === 'reticulum' || host === 'localmesh') return { category: 'Networks', tagline: e.description || '', icon: 'network' };
        return { category: 'Other', tagline: e.description || '', icon: 'box' };
    };

    const PATHS = {
        network: '<circle cx="12" cy="12" r="3"/><circle cx="4" cy="4" r="2"/><circle cx="20" cy="5" r="2"/><circle cx="19" cy="20" r="2"/><circle cx="4" cy="20" r="2"/><path d="m6 6 4 4m4 0 4-4m-4 8 4 4M6 18l4-4"/>',
        spectrum: '<path d="M3 19V9m4 10V5m5 14V2m5 17V7m4 12V12"/>',
        wave: '<path d="M2 12h3l3-8 4 16 4-16 3 8h3"/>',
        plane: '<path d="m12 3 2 7 7 5v2l-7-2v5l2 2-4-1-4 1 2-2v-5l-7 2v-2l7-5 2-7Z"/>',
        sensor: '<circle cx="12" cy="15" r="2"/><path d="M8 10a6 6 0 0 1 8 0M5 7a10 10 0 0 1 14 0M12 17v5"/>',
        pager: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 9h10v4H7zM7 16h2m3 0h2"/>',
        bluetooth: '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>',
        map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z"/><path d="M9 4v14m6-12v14"/>',
        display: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M7 9h6M7 13h10M9 21h6M12 17v4"/>',
        wifi: '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/>',
        code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16"/>',
        palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4A4.6 4.6 0 0 0 22 9.8C22 6 17.5 3 12 3Z"/><circle cx="7.5" cy="11.5" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="15" cy="7.5" r="1"/>',
        box: '<path d="M21 8 12 3 3 8v8l9 5 9-5V8Z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    };

    /** Inline SVG for a store icon name (unknown names get the box). */
    window.meshpointStoreIcon = function (name) {
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + (PATHS[name] || PATHS.box) + '</svg>';
    };
})();
