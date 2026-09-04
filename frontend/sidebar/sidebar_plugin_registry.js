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
        li.innerHTML = `<a href="#/${routeId}" class="sidebar__link" data-route="${routeId}">` +
            `${iconHtml}<span class="sidebar__label">${_escape(label)}</span></a>`;
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
