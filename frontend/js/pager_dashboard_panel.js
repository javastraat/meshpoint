/**
 * Emergency pager project dashboard panel (concentrator ch9, FSK).
 *
 * Not to be confused with pager_panel.js (the RTL-SDR P2000/Pagers/
 * POCSAG listener tab under Listener) -- an unrelated, pre-existing
 * feature that happens to share the word "pager". This is the
 * concentrator's own dedicated FSK channel, its own page under
 * Networks, backed by /api/pager/* (see emergency_pager_routes.py).
 *
 * Structurally mirrors DapnetPanel (one-way-at-a-time broadcast log,
 * no conversations) but with two tabs of history instead of one --
 * Inbox and Outbox are genuinely separate here since, unlike DAPNET's
 * serial companion, a sent message is never echoed back into the
 * receive path (no over-the-air loopback exists), so the send route
 * stores its own Outbox row directly.
 *
 * Every message is a JSON envelope, {"from":<capcode>,"to":<capcode>,
 * "text":"..."} (see pager_event_adapter.py) -- from/to are plain
 * POCSAG-style capcodes, e.g. this fork's own real DAPNET capcode as
 * "from", and a specific pager's number or a shared address like 911
 * as "to". "Sent" only ever means the concentrator hardware accepted
 * and queued the transmission; there is no ACK yet, so it never means
 * anything was actually received by another device.
 */

const PGD_TAB_STORE_KEY = 'meshpoint.pagerDashTab';

class PagerDashboardPanel {
    constructor(identity) {
        this._refreshTimer = null;
        this._mounted = false;
        this._inbox = [];
        this._outbox = [];
        // Same reasoning as DapnetPanel: fail open with no identity info
        // (no-auth dev setup), hide only for an explicit "viewer" role.
        // The real security boundary is server-side (POST /api/pager/send
        // already requires admin) -- this just keeps a viewer from seeing
        // a control they can't use.
        this._isAdmin = identity?.role !== 'viewer';
        let storedTab = null;
        try { storedTab = localStorage.getItem(PGD_TAB_STORE_KEY); } catch (_) {}
        this._tab = (storedTab === 'outbox' || (storedTab === 'send' && this._isAdmin))
            ? storedTab : 'inbox';
    }

    /** Called by the router when the section becomes active. */
    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        this._refreshTimer = MeshpointIdle.every(() => this._load(), 15_000);
    }

    /** Called by the router when the section is hidden. */
    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
    }

    _mount() {
        const root = document.getElementById('pager-dashboard-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Pager</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="pgd-export-btn">Export CSV</button>
                    <button class="terminal-button" type="button" id="pgd-refresh-btn">Refresh</button>
                </div>
            </header>

            <p class="cfg-card__hint" id="pgd-status-hint"></p>

            <section class="lw-stats" id="pgd-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Messages (In / Out)</div>
                    <div class="stat-card__value" id="pgd-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Unique Capcodes</div>
                    <div class="stat-card__value" id="pgd-stat-capcodes">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Acked</div>
                    <div class="stat-card__value" id="pgd-stat-acked">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Pending</div>
                    <div class="stat-card__value" id="pgd-stat-pending">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-pgd-tab="inbox">Inbox</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-pgd-tab="outbox">Outbox</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-pgd-tab="send" ${this._isAdmin ? '' : 'hidden'}>New Message</button>
                        </div>
                        <span class="lw-panel__limit" data-pgd-suffix="inbox">(last 100)</span>
                        <span class="lw-panel__limit" data-pgd-suffix="outbox" hidden>(last 100)</span>
                    </div>
                    <div data-pgd-view="inbox">
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--dapnet-packets">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-id">
                                <col class="col-id">
                                <col class="col-text">
                                <col class="col-type">
                                <col class="col-type">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>From</th>
                                    <th>To</th>
                                    <th>Text</th>
                                    <th>RSSI</th>
                                    <th>SNR</th>
                                </tr>
                            </thead>
                            <tbody id="pgd-inbox-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="pgd-inbox-empty" style="display:none">
                            No messages received yet.
                        </p>
                        </div>
                    </div>
                    <div data-pgd-view="outbox" hidden>
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--dapnet-packets">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-id">
                                <col class="col-id">
                                <col class="col-text">
                                <col class="col-type">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>From</th>
                                    <th>To</th>
                                    <th>Text</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody id="pgd-outbox-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="pgd-outbox-empty" style="display:none">
                            No messages sent yet.
                        </p>
                        </div>
                    </div>
                    <div data-pgd-view="send" hidden>
                        <div class="panel__body">
                            <form class="cfg-form" id="pgd-send-form" style="max-width:480px">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">To (capcode)</span>
                                    <input class="cfg-field__input" type="number" min="0"
                                           id="pgd-send-to" placeholder="e.g. 911 or a pager's own number" required>
                                </label>
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Message</span>
                                    <input class="cfg-field__input" type="text"
                                           id="pgd-send-text" placeholder="Message text" required maxlength="255">
                                </label>
                                <div class="cfg-card__actions">
                                    <button class="terminal-button terminal-button--primary"
                                            type="submit" id="pgd-send-btn">Send</button>
                                </div>
                                <p class="cfg-status" id="pgd-send-status" aria-live="polite"></p>
                                <p class="cfg-field__hint">
                                    "Sent" only confirms the concentrator accepted the
                                    transmission -- there's no acknowledgement scheme yet,
                                    so it never confirms anything actually received it.
                                </p>
                            </form>
                        </div>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('pgd-refresh-btn')
            ?.addEventListener('click', () => this._load());
        document.getElementById('pgd-export-btn')
            ?.addEventListener('click', () => {
                const ds = this._tab === 'outbox' ? 'outbox' : 'inbox';
                window.location = `/api/pager/export/${ds}.csv`;
            });
        root.querySelectorAll('[data-pgd-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.pgdTab));
        });
        this._applyTab();

        document.getElementById('pgd-send-form')
            ?.addEventListener('submit', (e) => this._handleSend(e));

        this._wireRowClicks('pgd-inbox-tbody', () => this._inbox);
        this._wireRowClicks('pgd-outbox-tbody', () => this._outbox);
    }

    /** Opens PacketDetailModal for a clicked Inbox/Outbox row -- same
     * pattern as dapnet_panel.js's own packet-table click handler. */
    _wireRowClicks(tbodyId, getRows) {
        const tbody = document.getElementById(tbodyId);
        if (!tbody) return;
        tbody.addEventListener('click', (e) => {
            const tr = e.target.closest('tr[data-pkt]');
            if (!tr || !window.PacketDetailModal) return;
            const pkt = (getRows() || [])[Number(tr.dataset.pkt)];
            if (!pkt) return;
            window.PacketDetailModal.show(pkt, { selectedRow: tr });
        });
    }

    _setTab(tab) {
        if (tab === 'send' && !this._isAdmin) return;
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(PGD_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
    }

    _applyTab() {
        const root = document.getElementById('pager-dashboard-panel');
        if (!root) return;
        root.querySelectorAll('[data-pgd-tab]').forEach((btn) => {
            const active = btn.dataset.pgdTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        root.querySelectorAll('[data-pgd-view]').forEach((el) => {
            el.hidden = el.dataset.pgdView !== this._tab;
        });
        root.querySelectorAll('[data-pgd-suffix]').forEach((el) => {
            el.hidden = el.dataset.pgdSuffix !== this._tab;
        });
    }

    async _load() {
        await Promise.all([
            this._loadStatus(), this._loadStats(), this._loadInbox(), this._loadOutbox(),
        ]);
    }

    async _loadStats() {
        try {
            const r = await fetch('/api/pager/stats');
            if (!r.ok) return;
            const s = await r.json();
            const inCount = s.inbox_count ?? '--';
            const outCount = s.outbox_count ?? '--';
            this._setText('pgd-stat-total', `${inCount} / ${outCount}`);
            this._setText('pgd-stat-capcodes', s.unique_capcodes ?? '--');
            this._setText('pgd-stat-acked', s.acked ?? '--');
            this._setText('pgd-stat-pending', s.pending ?? '--');
        } catch (_) {}
    }

    _setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    async _loadStatus() {
        const hint = document.getElementById('pgd-status-hint');
        if (!hint) return;
        try {
            const r = await fetch('/api/pager/status');
            if (!r.ok) return;
            const s = await r.json();
            if (!s.concentrator_available) {
                hint.textContent = 'Concentrator not available.';
            } else if (!s.pager_enabled) {
                hint.textContent = 'Pager channel (ch9) is currently disabled -- '
                    + 'enable it from Configuration → Radio (Pager).';
            } else if (!s.pager_capcode) {
                hint.textContent = 'Set your own capcode in Configuration → Radio (Pager) before sending.';
            } else {
                // Frequency + capcode are already shown on the topbar Pager
                // pill -- no need to restate them here once everything's OK.
                hint.textContent = '';
            }
        } catch (_) {}
    }

    async _loadInbox() {
        try {
            const r = await fetch('/api/pager/messages?direction=in&limit=100');
            if (!r.ok) return;
            this._inbox = await r.json();
            this._renderInbox();
        } catch (_) {}
    }

    async _loadOutbox() {
        try {
            const r = await fetch('/api/pager/messages?direction=out&limit=100');
            if (!r.ok) return;
            this._outbox = await r.json();
            this._renderOutbox();
        } catch (_) {}
    }

    _renderInbox() {
        const tbody = document.getElementById('pgd-inbox-tbody');
        const empty = document.getElementById('pgd-inbox-empty');
        if (!tbody) return;
        if (!this._inbox.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        tbody.innerHTML = this._inbox.map((m, i) => `
            <tr class="lw-pkt-row" data-pkt="${i}">
                <td class="lw-time">${this._fmtTime(m.timestamp)}</td>
                <td class="lw-id">${this._esc(m.from_capcode ?? '--')}</td>
                <td class="lw-id">${this._esc(m.to_capcode ?? '--')}</td>
                <td class="lw-text">${this._esc(m.text || '')}</td>
                <td>${m.rssi != null ? m.rssi.toFixed(1) : '--'}</td>
                <td>${m.snr != null ? m.snr.toFixed(1) : '--'}</td>
            </tr>
        `).join('');
    }

    _renderOutbox() {
        const tbody = document.getElementById('pgd-outbox-tbody');
        const empty = document.getElementById('pgd-outbox-empty');
        if (!tbody) return;
        if (!this._outbox.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        tbody.innerHTML = this._outbox.map((m, i) => `
            <tr class="lw-pkt-row" data-pkt="${i}">
                <td class="lw-time">${this._fmtTime(m.timestamp)}</td>
                <td class="lw-id">${this._esc(m.from_capcode ?? '--')}</td>
                <td class="lw-id">${this._esc(m.to_capcode ?? '--')}</td>
                <td class="lw-text">${this._esc(m.text || '')}</td>
                <td>${this._statusBadge(m.status)}</td>
            </tr>
        `).join('');
    }

    // "acked" (real ACK reply from the pager, see coordinator.py's
    // ack-matching branch) gets the same green "confirmed" styling
    // LoRaWAN's own Join badge already uses -- "sent" (still just
    // means the concentrator accepted the transmission, not that
    // anything received it) stays the neutral default badge color.
    _statusBadge(status) {
        if (status === 'acked') return '<span class="lw-badge lw-badge--join">Acked</span>';
        return '<span class="lw-badge">Sent</span>';
    }

    async _handleSend(event) {
        event.preventDefault();
        const status = document.getElementById('pgd-send-status');
        const btn = document.getElementById('pgd-send-btn');
        const toEl = document.getElementById('pgd-send-to');
        const textEl = document.getElementById('pgd-send-text');
        const text = (textEl?.value || '').trim();
        const toRaw = (toEl?.value || '').trim();
        if (!text || !toRaw) return;

        btn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending…';
        try {
            const r = await fetch('/api/pager/send', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ to_capcode: Number(toRaw), text }),
            });
            const result = await r.json().catch(() => ({}));
            if (r.ok) {
                status.dataset.kind = 'success';
                status.textContent = 'Sent.';
                textEl.value = '';
                this._loadOutbox();
            } else {
                status.dataset.kind = 'error';
                status.textContent = result.detail || 'Send failed.';
            }
        } catch (_) {
            status.dataset.kind = 'error';
            status.textContent = 'Send failed.';
        } finally {
            btn.disabled = false;
        }
    }

    _fmtTime(ts) {
        if (!ts) return '--';
        try {
            const d = new Date(ts);
            const now = new Date();
            const sameDay = d.getFullYear() === now.getFullYear()
                && d.getMonth() === now.getMonth()
                && d.getDate() === now.getDate();
            if (sameDay) {
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            }
            return d.toLocaleString([], {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        } catch (_) { return ts; }
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
}

window.PagerDashboardPanel = PagerDashboardPanel;
