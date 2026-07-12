/**
 * Sidebar header — GitHub update-available pill.
 *
 * Surfaces the periodic server-side update check (src/api/routes
 * /update_routes.py's periodic_update_check_loop) right under the
 * device name/status at the top of the sidebar, so an update is
 * visible on any page without digging into Settings. Reuses the
 * exact same git-fetch + commits-behind check as the manual "Check
 * for updates" button, so this pill and that button always agree.
 *
 * Only drives the one header pill (#sidebar-update-pill, a plain
 * link) -- the Settings-group/Updates-subitem badges were dropped
 * per user request (redundant once the header pill existed).
 *
 * Mirrors radio_tx_badge.js's overall structure (a small poller),
 * decoupled from whichever page happens to be mounted.
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
        // Plain <a href="#/settings/updates"> navigates on its own via
        // the router's hashchange listener -- this only needs to
        // toggle visibility, no click handler.
        const headerPill = document.getElementById('sidebar-update-pill');
        if (headerPill) headerPill.style.display = available ? '' : 'none';
    }
}

const POLL_MS = 5 * 60 * 1000;

window.UpdateCheckBadge = UpdateCheckBadge;
