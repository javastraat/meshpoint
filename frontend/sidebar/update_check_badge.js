/**
 * Sidebar header — update-available pills (meshpoint itself, and
 * installed plugins/themes with a newer version at a configured
 * source).
 *
 * Both signals are cheap, cache-only reads: the real checks (a git
 * fetch for meshpoint, a repo.json fetch per plugin source) run
 * backend-side on a single shared timer (src/api/routes/update_routes
 * .py's periodic_update_check_loop + its extra_check hook, wired to
 * plugin_source_routes.run_periodic_plugin_check in server.py's
 * lifespan) driven by the one "Automatic checks" interval setting --
 * deliberately not two independent cadences. This poller mirrors that:
 * it learns the configured interval from the meshpoint badge response
 * (`interval_minutes`) and re-times its own polling to match, instead
 * of polling on a separate hardcoded cadence of its own.
 *
 * Only drives the two header pills: #sidebar-update-pill (a plain,
 * fixed link) and #sidebar-plugin-update-pill (its href/target tab
 * change per refresh -- see _applyPlugins -- since a plugin update and
 * a theme update live on two different pages). The Settings-group/
 * Updates-subitem badges were dropped per user request (redundant once
 * the header pill existed).
 *
 * Mirrors radio_tx_badge.js's overall structure (a small poller),
 * decoupled from whichever page happens to be mounted.
 */
class UpdateCheckBadge {
    constructor(sidebar, fetchImpl = null) {
        this._sidebar = sidebar;
        this._fetch = fetchImpl || ((url, opts) => window.fetch(url, opts));
        this._pollInterval = null;
        this._currentIntervalMs = null;
    }

    init() {
        // A safe fallback cadence so polling definitely starts even if
        // the very first request fails (network blip, viewer role) --
        // replaced below the moment a real interval_minutes arrives.
        this._scheduleNext(DEFAULT_POLL_MINUTES);
        this._refresh();

        // The plugin pill's destination depends on what actually has an
        // update -- a plugin update belongs on Settings -> Plugins ->
        // Installed, a theme update on Settings -> Themes -> Installed
        // themes, entirely different pages each with their own sticky
        // per-browser tab preference (localStorage). _applyPlugins()
        // below keeps this._pluginPillRoute current on every refresh;
        // one listener here reads whatever it says *at click time*
        // (not bound to whatever it was when the pill first appeared)
        // and sets that page's tab preference just before the plain
        // href navigates there.
        const pluginPill = document.getElementById('sidebar-plugin-update-pill');
        if (pluginPill) {
            pluginPill.addEventListener('click', () => {
                const route = this._pluginPillRoute;
                if (!route) return;
                try { localStorage.setItem(route.storageKey, route.tab); } catch (_e) {}
            });
        }
    }

    /** Re-fetch both (cheap, cache-only) badge statuses right away --
     * called after a manual "Check for updates" so the sidebar doesn't
     * wait for the next scheduled poll to catch up. */
    refreshNow() {
        this._refresh();
    }

    destroy() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async _refresh() {
        try {
            const res = await this._fetch('/api/update/badge', {
                credentials: 'same-origin',
            });
            if (res.ok) {
                const data = await res.json();
                this._applyCore(data);
                this._scheduleNext(data.interval_minutes);
            }
        } catch (_e) {
            // Swallow, same rationale as radio_tx_badge.js: an intermittent
            // failure shouldn't spam the console, next poll tries again.
        }

        try {
            const res = await this._fetch('/api/plugin-sources/update-badge', {
                credentials: 'same-origin',
            });
            if (res.ok) {
                this._applyPlugins(await res.json());
            }
        } catch (_e) {
            // Same as above -- plugin sources may just be disabled/unreachable.
        }
    }

    /** Re-time the poll loop to the backend's configured interval, so
     * there's exactly one number controlling both how often the real
     * checks run and how often the browser looks for a fresh result.
     * A no-op when the interval hasn't actually changed, so a normal
     * tick doesn't keep tearing down and rebuilding its own timer. */
    _scheduleNext(intervalMinutes) {
        const minutes = (typeof intervalMinutes === 'number' && intervalMinutes >= MIN_POLL_MINUTES)
            ? intervalMinutes
            : DEFAULT_POLL_MINUTES;
        const ms = minutes * 60 * 1000;
        if (ms === this._currentIntervalMs) return;
        this._currentIntervalMs = ms;
        if (this._pollInterval) clearInterval(this._pollInterval);
        this._pollInterval = MeshpointIdle.every(() => this._refresh(), ms);
    }

    _applyCore(data) {
        const available = Boolean(data && data.update_available);
        // Plain <a href="#/settings/updates"> navigates on its own via
        // the router's hashchange listener -- this only needs to
        // toggle visibility, no click handler.
        const headerPill = document.getElementById('sidebar-update-pill');
        if (headerPill) headerPill.style.display = available ? '' : 'none';
    }

    /** Picks where the plugin pill points, since "an update is
     * available" alone doesn't say which page actually shows it:
     * - plugin update only -> Plugins page, Installed tab
     * - theme update only -> Themes page, Installed themes tab
     * - both at once (one source offering an updated plugin AND an
     *   updated theme) -> Plugins page, Sources tab -- that tab's own
     *   catalog view lists both kinds together, rather than guessing
     *   which single page/tab combination to prioritize. */
    _applyPlugins(data) {
        const available = Boolean(data && data.update_available);
        const headerPill = document.getElementById('sidebar-plugin-update-pill');
        if (!headerPill) return;
        headerPill.style.display = available ? '' : 'none';
        if (!available) return;

        const hasPlugin = Boolean(data && data.plugin_update_available);
        const hasTheme = Boolean(data && data.theme_update_available);
        if (hasPlugin && hasTheme) {
            headerPill.href = '#/settings/plugins';
            this._pluginPillRoute = { storageKey: 'meshpoint:plugins-tab', tab: 'sources' };
        } else if (hasTheme) {
            headerPill.href = '#/settings/themes';
            this._pluginPillRoute = { storageKey: 'meshpoint:themes-tab', tab: 'installed' };
        } else {
            headerPill.href = '#/settings/plugins';
            this._pluginPillRoute = { storageKey: 'meshpoint:plugins-tab', tab: 'installed' };
        }
    }
}

// Used only until the real configured interval is learned from the
// backend, and as a floor against a nonsensical value -- matches
// update_routes.py's own MIN_CHECK_INTERVAL_MINUTES/default.
const DEFAULT_POLL_MINUTES = 60;
const MIN_POLL_MINUTES = 5;

window.UpdateCheckBadge = UpdateCheckBadge;
