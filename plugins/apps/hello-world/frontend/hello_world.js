/**
 * Hello World -- the minimal reference plugin for the "sidebar" seam.
 *
 * Its route/label/category live in plugin.toml's [sidebar] table (parsed by
 * src/plugins/manifest.py, pushed to the browser by
 * src/plugins/assets.py:sidebar_descriptor_tags -- see
 * frontend/sidebar/sidebar_plugin_registry.js for how that becomes an
 * actual sidebar <li> + <section>). This script only supplies the content:
 * a mount()/show()/hide() object, same shape the Listener-tab ("panel")
 * seam already uses.
 */
window.registerSidebarPage({
    route: 'hello-world',
    make: () => ({
        mount(rootEl) {
            rootEl.innerHTML = `
                <div class="plugin-page">
                    <h2>Hello, World.</h2>
                    <p>This page is rendered entirely by a plugin --
                    <code>plugins/apps/hello-world/</code>. Its position in the
                    sidebar (under Networks) comes from <code>plugin.toml</code>'s
                    <code>[sidebar]</code> table, not from anything hardcoded in
                    the dashboard.</p>
                </div>
            `;
        },
        show() {},
        hide() {},
    }),
});
