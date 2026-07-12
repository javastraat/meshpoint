/**
 * Sidebar Settings item — GitHub update-available badge.
 *
 * Surfaces the periodic server-side update check (src/api/routes
 * /update_routes.py's periodic_update_check_loop) on the Settings
 * sidebar item, so an update is visible on any page without having
 * to expand Settings and open the Updates tab to find out. Reuses
 * the exact same git-fetch + commits-behind check as the manual
 * "Check for updates" button, so this badge and that button always
 * agree.
 *
 * Mirrors radio_tx_badge.js's structure: a small poller that pushes
 * into SidebarController.setStatusBadge(), decoupled from whichever
 * page happens to be mounted.
 */
class UpdateCheckBadge {
    constructor(sidebar, fetchImpl = null) {
        this._sidebar = sidebar;
        this._fetch = fetchImpl || ((url, opts) => window.fetch(url, opts));
        this._pollInterval = null;
    }

    init() {
        this._refresh();
        this._pollInterval = setInterval(() => this._refresh(), POLL_MS);
    }

    /** Re-fetch the (cheap, cache-only) badge status right away --
     * called after a manual "Check for updates" so the sidebar
     * doesn't wait for the next scheduled poll to catch up. */
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
            if (!res.ok) return; // e.g. 403 for viewer role -- badge just stays hidden
            const data = await res.json();
            this._apply(data);
        } catch (_e) {
            // Swallow, same rationale as radio_tx_badge.js: an intermittent
            // failure shouldn't spam the console, next poll tries again.
        }
    }

    _apply(data) {
        const available = Boolean(data && data.update_available);
        const label = available ? 'Update' : null;
        this._sidebar.setStatusBadge('settings', label, 'update');
        this._sidebar.setStatusBadge('settings/updates', label, 'update');
    }
}

const POLL_MS = 5 * 60 * 1000;

window.UpdateCheckBadge = UpdateCheckBadge;
