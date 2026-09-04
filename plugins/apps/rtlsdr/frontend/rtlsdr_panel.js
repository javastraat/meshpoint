/**
 * RTL-SDR Plugins -- the future RTL-SDR host page, under construction.
 *
 * The built-in Listener page (Radio + every RTL-SDR plugin's tab via
 * window.registerListenerPanel) is still core, but RTL-SDR plugins are
 * migrating off it onto THIS page instead, one at a time, via a DIFFERENT
 * seam -- a plugin injecting content into another plugin's page via
 * window.registerPageHook() (see frontend/sidebar/page_hook_registry.js
 * and docs/PLUGINS.md). DAB+ (plugins/apps/dab/) was the first to move --
 * see its own README for why. The plan is for every other RTL-SDR plugin,
 * and eventually Radio itself, to follow, at which point the built-in
 * Listener page goes away entirely.
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
                    Plugins are migrating onto this page one at a time --
                    anything not listed here yet still runs on the
                    Listener page (in the sidebar, under this same
                    section) instead.</p>
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
