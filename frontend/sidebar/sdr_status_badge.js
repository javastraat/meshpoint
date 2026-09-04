/**
 * Sidebar RTL-SDR item — live "dongle in use" badge.
 *
 * Every RTL-SDR listener (Radio, DAB+, P2000, Pagers, POCSAG, RTL433,
 * ACARS, ADS-B — all opt-in plugins hooked into the shared RTL-SDR page,
 * see plugins/apps/rtlsdr/) shares one physical dongle
 * (src/audio/sdr_registry.py) — only one can be tuned at a time. An
 * operator elsewhere in the dashboard has no way to tell one is running
 * without navigating to the RTL-SDR page, so this surfaces it on the
 * sidebar item instead: a green dot + which plugin currently holds the
 * dongle, hidden when idle.
 *
 * Polls a small core-owned endpoint (GET /api/sdr/status,
 * src/api/routes/sdr_status_routes.py) rather than any one plugin's own
 * status route — that route might not exist at all if its plugin isn't
 * installed/enabled, but the shared dongle-owner state always does.
 */
class SdrStatusBadge {
    constructor(sidebar, fetchImpl = null) {
        this._sidebar = sidebar;
        this._fetch = fetchImpl || ((url, opts) => window.fetch(url, opts));
        this._pollInterval = null;
    }

    init() {
        this._refresh();
        this._pollInterval = setInterval(() => this._refresh(), SDR_STATUS_BADGE_POLL_MS);
    }

    destroy() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async _refresh() {
        try {
            const res = await this._fetch('/api/sdr/status', {
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
            this._sidebar.setStatusBadge('rtlsdr', null);
            return;
        }
        this._sidebar.setStatusBadge('rtlsdr', _SDR_OWNER_LABELS[owner] || owner, 'live');
    }
}

const SDR_STATUS_BADGE_POLL_MS = 5000;

// Matches src/audio/sdr_registry.py's owner names, as claimed by each
// RTL-SDR plugin's own backend/listener.py.
const _SDR_OWNER_LABELS = {
    radio: 'Radio', p2000: 'P2000', pagers: 'Pagers', pocsag: 'POCSAG', rtl433: 'RTL433',
    acars: 'ACARS', adsb: 'ADS-B', dab: 'DAB+', dab_scan: 'DAB+ scan',
};

window.SdrStatusBadge = SdrStatusBadge;
