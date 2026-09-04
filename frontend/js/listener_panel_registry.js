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
 * return an object with mount(rootEl) / show() / hide() (PagerPanel, AdsbPanel,
 * DabPanel all satisfy this).
 *
 * The `radio` tab is the only one NOT registered here -- it's bespoke
 * (audio element + skins) and stays hardcoded in listener_panel.js. Every
 * other Listener tab, including DAB+, is a plugin using this seam.
 */
window.LISTENER_PANELS = window.LISTENER_PANELS || [];

window.registerListenerPanel = function registerListenerPanel(descriptor) {
    window.LISTENER_PANELS.push(descriptor);
};
