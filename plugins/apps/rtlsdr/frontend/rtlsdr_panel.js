/**
 * RTL-SDR -- staging ground for the eventual RTL-SDR host page.
 *
 * Today the built-in Listener page (Radio + every RTL-SDR plugin's tab via
 * window.registerListenerPanel) is still the real thing. This page exists
 * to prove out a DIFFERENT seam -- a plugin injecting content into another
 * plugin's page via window.registerPageHook() (see
 * frontend/sidebar/page_hook_registry.js and docs/PLUGINS.md) -- against a
 * real, non-trivial plugin (DAB+, see plugins/apps/dab/frontend/
 * dab_rtlsdr_hook.js) rather than just the hello-world-hook toy example.
 *
 * If this pans out, the plan is to eventually move the Listener page's
 * shell (tabbar, #listener-panel ownership, window.LISTENER_PANELS
 * consumption) out of core into this plugin, with Radio itself becoming
 * an ordinary plugin registering into it like every other RTL-SDR tab.
 * Not done yet -- this page is deliberately just a placeholder + a hook
 * mount point until that's decided.
 */
window.registerSidebarPage({
    route: 'rtlsdr',
    make: () => ({
        mount(rootEl) {
            const hasHooks = (window.MESHPOINT_PAGE_HOOKS || [])
                .some((h) => h.host === 'rtlsdr');
            rootEl.innerHTML = `
                <div class="plugin-page">
                    <h2>RTL-SDR Plugins</h2>
                    <p>Enable RTL-SDR plugins to see their content here.
                    This page is a staging ground for the real RTL-SDR host
                    page -- for now, the Listener page (in the sidebar,
                    under this same section) is still where Radio/DAB+/
                    P2000/Pagers/POCSAG/RTL433/ADS-B/ACARS actually run.</p>
                    ${hasHooks ? '<div class="rtlsdr-hooks" data-rtlsdr-hooks></div>' : ''}
                </div>
            `;
            if (hasHooks && typeof window.mountPageHooks === 'function') {
                window.mountPageHooks('rtlsdr', rootEl.querySelector('[data-rtlsdr-hooks]'));
            }
        },
        show() {},
        hide() {},
    }),
});
