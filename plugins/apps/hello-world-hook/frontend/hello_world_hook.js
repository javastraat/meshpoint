/**
 * Hello World Hook -- the minimal reference plugin for the "hook" seam.
 *
 * Unlike "panel" (a Listener sub-tab) or "sidebar" (a whole page of its
 * own), "hook" lets a plugin inject content into ANOTHER page instead of
 * owning one -- here, the Hello World sidebar page
 * (plugins/apps/hello-world/). See frontend/sidebar/page_hook_registry.js
 * for the seam itself and docs/PLUGINS.md for the full writeup.
 *
 * The target host is plugin.toml's [hook].host ("hello-world") -- must
 * match the host plugin's own [sidebar].route exactly, and the host's own
 * frontend script must call window.mountPageHooks() from its mount() for
 * this to ever actually render (see hello_world.js).
 */
window.registerPageHook({
    host: 'hello-world',
    make: () => ({
        mount(rootEl) {
            rootEl.innerHTML = `
                <div class="hello-world-hook">
                    <p>This box was not drawn by the Hello World page itself
                    -- it was injected by a second, independent plugin
                    (<code>plugins/apps/hello-world-hook/</code>) via
                    <code>window.registerPageHook()</code>, proving a plugin
                    can attach into another plugin's already-rendered page
                    instead of needing a whole page of its own.</p>
                </div>
            `;
        },
        show() {},
        hide() {},
    }),
});
