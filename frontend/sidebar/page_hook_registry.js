/*
 * Plugin seam for injecting content into ANOTHER plugin's already-rendered
 * page, instead of owning a page/tab of your own -- "panel" (a Listener
 * sub-tab) and "sidebar" (a whole top-level page) both give a plugin its
 * OWN space; "hook" instead lets a plugin attach into a HOST's space.
 *
 * A host page opts in by calling window.mountPageHooks(hostId, containerEl)
 * once from inside its own mount(rootEl) -- typically after rendering its
 * own content, passing a dedicated element for hook content to render
 * into. Nothing else is required of a host, and it costs nothing when zero
 * hook plugins target it (mountPageHooks is a no-op then). hostId is
 * whatever id the host's own page is known by -- for a "sidebar" plugin,
 * that's its plugin.toml [sidebar].route.
 *
 * A hook plugin registers via:
 *
 *   window.registerPageHook({
 *       host: 'hello-world',     // must match plugin.toml's [hook].host
 *       make: () => ({
 *           mount(el) { el.innerHTML = '<p>Hello from a hook.</p>'; },
 *           show() {},
 *           hide() {},
 *       }),
 *   });
 *
 * Ordering: every plugin's frontend script runs before app.js (see
 * src/plugins/assets.py's injection-marker comment) -- so every
 * registerPageHook() call has already landed in the queue below by the
 * time any host's own mount() runs and calls mountPageHooks(), even
 * though mount() itself is only called later (e.g. a "sidebar" host's
 * mount() runs from window.mountPluginSidebarPages(), itself called from
 * app.js).
 */

window.MESHPOINT_PAGE_HOOKS = window.MESHPOINT_PAGE_HOOKS || [];

window.registerPageHook = function registerPageHook({ host, make }) {
    window.MESHPOINT_PAGE_HOOKS.push({ host, make });
};

/**
 * Mounts every hook registered for *hostId* under *containerEl*, in
 * registration order -- each into its OWN child wrapper element, never
 * directly into containerEl itself. A panel's mount(el) typically does
 * `el.innerHTML = ...`, which would wipe out any sibling hook's content
 * if two hooks were both handed the same element directly (only ever
 * mattered once a host had more than one hook registered -- the original
 * single-hook hello-world-hook case never surfaced it).
 *
 * Returns the mounted panel objects (each has mount/show/hide) so a host
 * can propagate its own show()/hide() lifecycle into its hooks -- REQUIRED
 * for any hook whose own show() kicks off data loading or polling (e.g.
 * the DAB+ plugin's panels), not just optional polish.
 */
window.mountPageHooks = function mountPageHooks(hostId, containerEl) {
    const mounted = [];
    if (!containerEl) return mounted;
    window.MESHPOINT_PAGE_HOOKS
        .filter((h) => h.host === hostId)
        .forEach(({ make }) => {
            try {
                const panel = make();
                const wrapper = document.createElement('div');
                containerEl.appendChild(wrapper);
                if (panel && typeof panel.mount === 'function') panel.mount(wrapper);
                mounted.push(panel);
            } catch (err) {
                console.error(`Page hook for host "${hostId}" failed to mount:`, err);
            }
        });
    return mounted;
};
