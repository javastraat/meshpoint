/*
 * Plugin seam for RTL-SDR listener tabs on the built-in Listener page.
 *
 * A plugin script (loaded before app.js, i.e. before ListenerPanel is
 * constructed) would register its tab like this:
 *
 *   window.registerListenerPanel({
 *     tab: 'acars',                 // unique slug; also the #lsn-tab-<slug> id
 *     label: 'ACARS',               // tabbar button text
 *     make: () => new window.PagerPanel('acars', '/api/acars', 'ACARS', rowFn),
 *   });
 *
 * `make` is a factory called once during ListenerPanel construction; it must
 * return an object with mount(rootEl) / show() / hide().
 *
 * Currently unused: every RTL-SDR plugin that used this seam (DAB+,
 * Pagers, POCSAG, P2000, RTL433, ACARS, ADS-B) has migrated onto the
 * RTL-SDR Plugins page instead (plugins/apps/rtlsdr/), via the DIFFERENT
 * "hook" seam (frontend/sidebar/page_hook_registry.js) -- that's for a
 * plugin injecting into another plugin's page, not adding a tab here. The
 * `radio` tab is the only one left on this page, hardcoded in
 * listener_panel.js (bespoke: audio element + skins). This file is kept
 * rather than deleted since Radio itself is expected to migrate the same
 * way eventually, at which point this whole page goes away and this
 * seam becomes fully dead, not just unused.
 */
window.LISTENER_PANELS = window.LISTENER_PANELS || [];

window.registerListenerPanel = function registerListenerPanel(descriptor) {
    window.LISTENER_PANELS.push(descriptor);
};
