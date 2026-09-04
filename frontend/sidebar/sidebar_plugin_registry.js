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
    const _ICON_PATHS = {
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

    function _iconSvg(name) {
        const inner = _ICON_PATHS[name] || _ICON_PATHS.plug;
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
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
