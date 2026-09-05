/**
 * Topbar plugin chip registry.
 *
 * Lets a plugin add its own status chip to the topbar, the same visual
 * shape as the built-in Meshtastic/MeshCore/Serial/Pager/Reticulum chips
 * (reuse the shared `.topbar-serial` classes -- see
 * topbar_reticulum_chip.js for the closest existing precedent: a chip
 * that runs its own status poll rather than reading the shared
 * GET /api/config blob every core chip otherwise reads from).
 *
 * Unlike core's own chips, a plugin chip has no GET /api/config-driven
 * enabled flag to gate visibility on -- the plugin being loaded at all
 * already means it's enabled, so its chip is mounted unconditionally;
 * from there it owns its own polling and can hide itself (`el.hidden`)
 * whenever it has nothing worth showing (e.g. no device configured yet).
 *
 * window.registerTopbarChip({ id, make }) -- call this from your
 * plugin's own frontend script (loaded before app.js ever runs, so
 * TopbarController always sees every registered chip by the time it's
 * constructed -- same load-order guarantee sidebar_plugin_registry.js
 * and page_hook_registry.js already rely on). `make()` returns an
 * object shaped like every existing chip:
 *   - mount(rootEl)  required -- build your initial DOM into rootEl
 *   - init()         optional -- called once, right after mount; start
 *                     your own polling/timers here
 *   - destroy()      optional -- called on teardown (no real teardown
 *                     path exists today; kept for symmetry)
 *
 * No `provides`/`plugin.toml` capability gate exists for this one --
 * same bare-seam precedent as `"panel"` (a plugin either calls this or
 * it doesn't; there's no declarative metadata for a custom-rendered
 * chip to validate against, unlike `"sidebar"`'s route/label/icon).
 */
(function () {
    const _specs = [];

    function registerTopbarChip(spec) {
        _specs.push(spec);
    }

    function mountTopbarChips(containerEl) {
        const mounted = [];
        for (const spec of _specs) {
            const wrapper = document.createElement('span');
            wrapper.className = 'topbar__group topbar__group--plugin';
            wrapper.dataset.topbarChip = spec.id;
            containerEl.appendChild(wrapper);
            const chip = spec.make();
            chip.mount(wrapper);
            if (chip.init) chip.init();
            mounted.push(chip);
        }
        return mounted;
    }

    window.registerTopbarChip = registerTopbarChip;
    window.mountTopbarChips = mountTopbarChips;
})();
