/**
 * Sidebar RTL-SDR item — live "dongle in use" badge.
 *
 * The RTL-SDR page has four tabs (Radio/P2000/Pagers/POCSAG) that all
 * share one physical dongle (src/audio/sdr_registry.py) — only one
 * can be tuned at a time. An operator elsewhere in the dashboard has
 * no way to tell one is running without navigating to the Listener
 * page, so this surfaces it on the sidebar item instead: a green dot
 * + which tab currently holds the dongle, hidden when idle.
 *
 * Any of the four status endpoints reports the same shared
 * `dongle_owner` field (src/audio/sdr_registry.py's `current_owner()`),
 * so polling just one (/api/listener/status) is enough — no need to
 * poll all four.
 */
class ListenerBadge {
    constructor(sidebar, fetchImpl = null) {
        this._sidebar = sidebar;
        this._fetch = fetchImpl || ((url, opts) => window.fetch(url, opts));
        this._pollInterval = null;
    }

    init() {
        this._refresh();
        this._pollInterval = setInterval(() => this._refresh(), LISTENER_BADGE_POLL_MS);
    }

    destroy() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async _refresh() {
        try {
            const res = await this._fetch('/api/listener/status', {
                credentials: 'same-origin',
            });
            if (!res.ok) return;
            const status = await res.json();
            this._apply(status);
        } catch (_e) {
            // Swallow: leaves the last-known badge in place; next poll retries.
        }
    }

    _apply(status) {
        const owner = status && status.dongle_owner;
        if (!owner) {
            this._sidebar.setStatusBadge('listener', null);
            return;
        }
        this._sidebar.setStatusBadge('listener', _LISTENER_OWNER_LABELS[owner] || owner, 'live');
    }
}

const LISTENER_BADGE_POLL_MS = 5000;

// Matches src/audio/sdr_registry.py's owner names.
const _LISTENER_OWNER_LABELS = {
    radio: 'Radio', p2000: 'P2000', pagers: 'Pagers', pocsag: 'POCSAG', rtl433: 'RTL433',
};

window.ListenerBadge = ListenerBadge;
