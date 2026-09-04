/*
 * Plugin seam for RTL-SDR listener tabs on the Listener page.
 *
 * A plugin script (loaded before app.js, i.e. before ListenerPanel is
 * constructed) registers its tab:
 *
 *   window.registerListenerPanel({
 *     tab: 'acars',                 // unique slug; also the #lsn-tab-<slug> id
 *     label: 'ACARS',               // tabbar button text
 *     make: () => new window.PagerPanel('acars', '/api/acars', 'ACARS', rowFn),
 *   });
 *
 * `make` is a factory called once during ListenerPanel construction; it must
 * return an object with mount(rootEl) / show() / hide() (PagerPanel and
 * AdsbPanel both satisfy this).
 *
 * The `radio` tab is the only one NOT registered here -- it's bespoke
 * (audio element + skins) and stays hardcoded in listener_panel.js. Every
 * other Listener tab is a plugin using this seam. DAB+ used to be one of
 * them too, but now lives on the RTL-SDR Plugins page instead, via the
 * DIFFERENT "hook" seam (frontend/sidebar/page_hook_registry.js) --
 * that's for a plugin injecting into another plugin's page, not adding a
 * Listener tab, so it doesn't call registerListenerPanel() at all anymore.
 */
window.LISTENER_PANELS = window.LISTENER_PANELS || [];

window.registerListenerPanel = function registerListenerPanel(descriptor) {
    window.LISTENER_PANELS.push(descriptor);
};
