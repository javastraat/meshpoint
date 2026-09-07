/**
 * Reticulum/LXMF monitoring page (plugin "sidebar" seam).
 *
 * Ported from the core page (frontend/js/reticulum_panel.js,
 * document.getElementById('reticulum-panel')) as part of the core->plugin
 * extraction -- see memory/plugin-reticulum.md. Behaviour is unchanged;
 * the edits are the ones every sidebar-plugin port needs:
 *  - mount(rootEl)/show()/hide() replace the old lazy _mount()+show()/hide()
 *    pair a hand-wired _bootReticulumPanel(router, identity) used to drive;
 *  - every DOM lookup is root-scoped (this._root.querySelector), not
 *    document.getElementById -- the section id is assigned by
 *    mountPluginSidebarPages(), not 'reticulum-panel';
 *  - identity/role (for the admin-only Send tab) comes from
 *    window.meshpointIdentity, not a constructor argument;
 *  - plain fetch(), no Configuration _api wrapper.
 *
 * Peers (roster) + Messages (flat conversation summary, reuses the
 * cross-protocol GET /api/messages/conversations filtered client-side to
 * protocol==='reticulum') + an admin-only Send tab. Reuses core's shared
 * lorawan.css / dashboard.css classes (lw-*, stat-card, mt-badge, cfg-*,
 * terminal-button) -- those stay core, shared by several pages.
 */

const RT_TAB_STORE_KEY = 'meshpoint.rtTab';
// The public Reticulum network's peer count grows unbounded (1000+ after a
// few hours) -- rendering every row gets visibly heavy, so the Peers tab
// shows only the most recent RT_PEER_LIMIT by default with a "Show all"
// toggle, client-side since this list has no backend limit param.
const RT_PEER_LIMIT = 100;

// Reuses MeshCore/Meshtastic's own mt-badge--* color set (lorawan.css):
// delivery = an actual message recipient (cyan); propagation/
// nomadnetwork.node are infrastructure, so the muted routing/info colors.
const RT_ASPECT_BADGES = {
    'lxmf.delivery': 'mt-badge--text',
    'lxmf.propagation': 'mt-badge--routing',
    'nomadnetwork.node': 'mt-badge--nodeinfo',
    'call.audio': 'mt-badge--routing',
};

// Rows kept in the Activity table's DOM (backend ring buffer is 200).
const RT_ANNOUNCE_LIMIT = 200;

class ReticulumPanel {
    constructor() {
        this._root = null;
        this._refreshTimer = null;
        this._peers = [];
        this._peersShowAll = false;
        this._announces = [];
        this._sendPeerSearchQuery = '';
        // Fails open like every other panel's own guard (no identity/role
        // info at all means show it) -- the real security boundary is
        // server-side (POST /api/reticulum/send already requires admin).
        this._isAdmin = window.meshpointIdentity?.role !== 'viewer';
        let stored = null;
        try { stored = localStorage.getItem(RT_TAB_STORE_KEY); } catch (_) {}
        // 'pages' restores optimistically -- _syncPagesTab() bounces it
        // back to 'peers' on the first /status if no node is hosting.
        this._tab = (['messages', 'announces'].includes(stored)
            || (['send', 'settings', 'browse', 'pages'].includes(stored) && this._isAdmin))
            ? stored : 'peers';
        this._settingsTab = null;
        this._nomadTab = null;
        this._nodePagesTab = null;
        this._onWsPeer = this._onWsPeer.bind(this);
        this._onWsMessage = this._onWsMessage.bind(this);
        this._onWsAnnounce = this._onWsAnnounce.bind(this);
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Reticulum</h2>
                <div class="lw-panel__actions">
                    <span class="lw-panel__limit" id="rt-own-address"></span>
                    <button class="terminal-button" type="button" id="rt-announce-btn"
                            ${this._isAdmin ? '' : 'hidden'}>Announce now</button>
                    <button class="terminal-button" type="button" id="rt-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="rt-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Status</div>
                    <div class="stat-card__value" id="rt-stat-status">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Known Peers</div>
                    <div class="stat-card__value" id="rt-stat-peers">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">People</div>
                    <div class="stat-card__value" id="rt-stat-people">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Infrastructure</div>
                    <div class="stat-card__value" id="rt-stat-infra">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Conversations</div>
                    <div class="stat-card__value" id="rt-stat-conversations">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="peers">Peers</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="messages">Messages</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="announces">Activity</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="send" ${this._isAdmin ? '' : 'hidden'}>Send</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="browse" ${this._isAdmin ? '' : 'hidden'}>Browse</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="settings" ${this._isAdmin ? '' : 'hidden'}>Settings</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="pages" hidden>Pages</button>
                        </div>
                    </div>
                    <div data-rt-view="peers">
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--rt-peers">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-id">
                                    <col class="col-type">
                                    <col class="col-time">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Last seen</th>
                                        <th>Display name</th>
                                        <th>Destination</th>
                                        <th>Aspect</th>
                                        <th>First seen</th>
                                    </tr>
                                </thead>
                                <tbody id="rt-peer-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rt-peer-empty" style="display:none">
                                No Reticulum peers heard yet.
                            </p>
                            <p class="lw-panel__limit" id="rt-peer-limit-note" style="display:none"></p>
                        </div>
                    </div>
                    <div data-rt-view="messages" hidden>
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--rt-messages">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-text">
                                    <col class="col-type">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Last message</th>
                                        <th>Peer</th>
                                        <th>Preview</th>
                                        <th class="lw-r">Unread</th>
                                    </tr>
                                </thead>
                                <tbody id="rt-message-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rt-message-empty" style="display:none">
                                No Reticulum messages yet.
                            </p>
                        </div>
                    </div>
                    <div data-rt-view="announces" hidden>
                        <div class="panel__body lw-table-wrap">
                            <p class="lw-panel__limit">
                                Announces heard since the service last started — the raw
                                feed (repeats and all), newest first. The deduped roster
                                is the Peers tab.
                            </p>
                            <table class="lw-table lw-table--rt-announces">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-id">
                                    <col class="col-type">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Time</th>
                                        <th>Display name</th>
                                        <th>Destination</th>
                                        <th>Aspect</th>
                                    </tr>
                                </thead>
                                <tbody id="rt-announce-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rt-announce-empty" style="display:none">
                                No announces heard yet.
                            </p>
                        </div>
                    </div>
                    <div data-rt-view="settings" hidden>
                        <div class="panel__body" data-rt-settings-body></div>
                    </div>
                    <div data-rt-view="pages" hidden>
                        <div class="panel__body" data-rt-nodepages-body></div>
                    </div>
                    <div data-rt-view="browse" hidden>
                        <div class="panel__body" data-rt-nomad-body></div>
                    </div>
                    <div data-rt-view="send" hidden>
                        <div class="panel__body">
                            <form class="cfg-form" id="rt-send-form" style="max-width:480px">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Peer</span>
                                    <div class="lw-search-wrap">
                                        <input type="text" id="rt-send-peer-search" class="lw-search"
                                               placeholder="Search by name or ID..."
                                               autocomplete="off" spellcheck="false" />
                                        <button id="rt-send-peer-search-clear" class="lw-search-clear"
                                                type="button" title="Clear search" hidden>&times;</button>
                                    </div>
                                    <select class="cfg-field__input" id="rt-send-peer" required></select>
                                </label>
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Message</span>
                                    <input class="cfg-field__input" type="text"
                                           id="rt-send-text" placeholder="Message text" required>
                                </label>
                                <div class="cfg-card__actions">
                                    <button class="terminal-button terminal-button--primary"
                                            type="submit" id="rt-send-btn">Send message</button>
                                </div>
                                <p class="cfg-status" id="rt-send-status" aria-live="polite"></p>
                            </form>
                        </div>
                    </div>
                </div>
            </section>
        `;

        if (window.ReticulumSettingsTab) {
            this._settingsTab = new window.ReticulumSettingsTab(this._q('[data-rt-settings-body]'));
        }
        if (window.ReticulumNomadTab) {
            this._nomadTab = new window.ReticulumNomadTab(this._q('[data-rt-nomad-body]'));
        }
        if (window.ReticulumNodePagesTab) {
            this._nodePagesTab = new window.ReticulumNodePagesTab(this._q('[data-rt-nodepages-body]'));
        }

        this._q('#rt-refresh-btn')?.addEventListener('click', () => this._load());
        this._q('#rt-announce-btn')?.addEventListener('click', () => this._handleAnnounce());
        this._root.querySelectorAll('[data-rt-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.rtTab));
        });
        const messageTbody = this._q('#rt-message-tbody');
        if (messageTbody) {
            messageTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-node-id]');
                if (tr) this._markRead(tr.dataset.nodeId);
            });
        }
        this._q('#rt-send-form')?.addEventListener('submit', (e) => this._handleSend(e));

        const sendPeerSearchEl = this._q('#rt-send-peer-search');
        const sendPeerSearchClearEl = this._q('#rt-send-peer-search-clear');
        if (sendPeerSearchEl) {
            sendPeerSearchEl.addEventListener('input', (e) => {
                this._sendPeerSearchQuery = e.target.value.toLowerCase();
                if (sendPeerSearchClearEl) sendPeerSearchClearEl.hidden = !e.target.value;
                this._renderSendPeers();
            });
        }
        if (sendPeerSearchClearEl && sendPeerSearchEl) {
            sendPeerSearchClearEl.addEventListener('click', () => {
                sendPeerSearchEl.value = '';
                this._sendPeerSearchQuery = '';
                sendPeerSearchClearEl.hidden = true;
                sendPeerSearchEl.focus();
                this._renderSendPeers();
            });
        }
        this._applyTab();
    }

    /** Called by the router (via registerSidebarPage) when the page becomes active. */
    show() {
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 15_000);
        if (window.concentratorWS) {
            window.concentratorWS.on('reticulum_peer', this._onWsPeer);
            window.concentratorWS.on('reticulum_message', this._onWsMessage);
            window.concentratorWS.on('reticulum_announce', this._onWsAnnounce);
        }
        this._activateSubTab();
    }

    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
        // ConcentratorWebSocket has no unsubscribe primitive -- re-adding
        // the same bound callback on the next show() just means a brief
        // doubled-up refresh, not a real leak (both handlers just reload).
        if (this._settingsTab) this._settingsTab.hide();
        if (this._nomadTab) this._nomadTab.hide();
        if (this._nodePagesTab) this._nodePagesTab.hide();
    }

    /** Load only the sub-tab that's actually visible -- the Settings and
     * Browse tabs each do heavy fetches (config + serial ports; a full
     * peer query + a big node <select>), so firing both on every page
     * visit made the Reticulum page slow to open. */
    _activateSubTab() {
        if (this._tab === 'settings' && this._settingsTab) this._settingsTab.show();
        else if (this._tab === 'browse' && this._nomadTab) this._nomadTab.show();
        else if (this._tab === 'pages' && this._nodePagesTab) this._nodePagesTab.show();
        else if (this._tab === 'announces') this._loadAnnounces();
    }

    /** Open the Browse tab pointed at a specific node (Peers-row "Browse" button). */
    browseNode(destinationHash) {
        this._setTab('browse');
        if (this._nomadTab) this._nomadTab.openNode(destinationHash);
    }

    _onWsPeer() { this._loadPeers(); }
    _onWsMessage() { this._loadMessages(); }

    _onWsAnnounce(entry) {
        if (!entry || !entry.ts) return;
        this._announces.unshift(entry);
        if (this._announces.length > RT_ANNOUNCE_LIMIT) {
            this._announces.length = RT_ANNOUNCE_LIMIT;
        }
        if (this._tab === 'announces') this._renderAnnounces();
    }

    _q(sel) { return this._root ? this._root.querySelector(sel) : null; }

    _setTab(tab) {
        if ((tab === 'send' || tab === 'settings' || tab === 'browse' || tab === 'pages') && !this._isAdmin) return;
        if (tab === 'pages' && !this._nodeHosting) return;
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(RT_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
        this._activateSubTab();
    }

    _applyTab() {
        if (!this._root) return;
        this._root.querySelectorAll('[data-rt-tab]').forEach((btn) => {
            const active = btn.dataset.rtTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        this._root.querySelectorAll('[data-rt-view]').forEach((el) => {
            el.hidden = el.dataset.rtView !== this._tab;
        });
    }

    async _load() {
        const jobs = [this._loadStatus(), this._loadPeers(), this._loadMessages()];
        if (this._tab === 'announces') jobs.push(this._loadAnnounces());
        await Promise.all(jobs);
    }

    async _loadStatus() {
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (!r.ok) return;
            const s = await r.json();
            this._setText('rt-stat-status', s.running ? 'Running' : (s.available ? 'Stopped' : 'Unavailable'));
            const addrEl = this._q('#rt-own-address');
            if (addrEl) addrEl.textContent = s.own_address ? `You: ${s.own_address}` : '';
            this._syncPagesTab(this._isAdmin && !!s.node);
        } catch (_) {}
    }

    /** The Pages tab only makes sense while a NomadNet node is actually
     * hosting (`/status`.node != null). Show/hide its button accordingly,
     * and bounce off it if the node just stopped. */
    _syncPagesTab(hosting) {
        this._nodeHosting = hosting;
        const btn = this._root?.querySelector('[data-rt-tab="pages"]');
        if (btn) btn.hidden = !hosting;
        if (!hosting && this._tab === 'pages') this._setTab('peers');
    }

    async _loadPeers() {
        try {
            const r = await fetch('/api/reticulum/peers', { credentials: 'same-origin' });
            if (!r.ok) return;
            const peers = await r.json();
            this._peers = peers;
            this._setText('rt-stat-peers', peers.length);
            // "People" = actual message recipients (lxmf.delivery);
            // everything else is network infrastructure -- same split
            // _renderSendPeers() applies to the picker.
            const peopleCount = peers.filter((p) => p.aspect === 'lxmf.delivery').length;
            this._setText('rt-stat-people', peopleCount);
            this._setText('rt-stat-infra', peers.length - peopleCount);
            this._renderPeers();
            this._renderSendPeers();
        } catch (_) {}
    }

    _renderSendPeers() {
        // Only lxmf.delivery destinations are real message recipients,
        // matching the backend's own send_message() semantics.
        const select = this._q('#rt-send-peer');
        if (!select) return;
        let deliveryPeers = this._peers.filter((p) => p.aspect === 'lxmf.delivery');
        if (this._sendPeerSearchQuery) {
            const q = this._sendPeerSearchQuery;
            deliveryPeers = deliveryPeers.filter((p) =>
                (p.display_name || '').toLowerCase().includes(q)
                || p.destination_hash.toLowerCase().includes(q)
            );
        }
        const previous = select.value;
        select.innerHTML = deliveryPeers.length
            ? deliveryPeers.map((p) => `
                <option value="${this._esc(p.destination_hash)}">
                    ${this._esc(p.display_name || p.destination_hash)}
                </option>
            `).join('')
            : '<option value="" disabled selected>No matching peers</option>';
        if (previous && deliveryPeers.some((p) => p.destination_hash === previous)) {
            select.value = previous;
        }
    }

    _renderPeers() {
        const tbody = this._q('#rt-peer-tbody');
        const empty = this._q('#rt-peer-empty');
        const limitNote = this._q('#rt-peer-limit-note');
        if (!tbody) return;

        if (!this._peers.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            if (limitNote) limitNote.style.display = 'none';
            return;
        }
        if (empty) empty.style.display = 'none';

        // Already sorted last_seen DESC by the API -- truncating to the
        // first RT_PEER_LIMIT keeps the most recently active peers. The
        // full list is already in memory from the one fetch.
        const total = this._peers.length;
        const truncated = !this._peersShowAll && total > RT_PEER_LIMIT;
        const visible = truncated ? this._peers.slice(0, RT_PEER_LIMIT) : this._peers;

        if (limitNote) {
            if (total > RT_PEER_LIMIT) {
                limitNote.style.display = '';
                limitNote.innerHTML = truncated
                    ? `Showing ${RT_PEER_LIMIT} of ${total} peers — `
                      + `<button type="button" class="lw-link-btn" id="rt-peer-show-all">Show all</button>`
                    : `Showing all ${total} peers — `
                      + `<button type="button" class="lw-link-btn" id="rt-peer-show-less">Show last ${RT_PEER_LIMIT}</button>`;
                this._q('#rt-peer-show-all')
                    ?.addEventListener('click', () => { this._peersShowAll = true; this._renderPeers(); });
                this._q('#rt-peer-show-less')
                    ?.addEventListener('click', () => { this._peersShowAll = false; this._renderPeers(); });
            } else {
                limitNote.style.display = 'none';
            }
        }

        tbody.innerHTML = visible.map((p) => `
            <tr>
                <td class="lw-time">${this._fmtTime(p.last_seen)}</td>
                <td class="mt-name">${this._esc(p.display_name || '--')}</td>
                <td class="lw-id">${this._esc(p.destination_hash)}</td>
                <td>${this._fmtAspect(p.aspect)}${
                    p.aspect === 'nomadnetwork.node' && this._isAdmin
                        ? ` <button type="button" class="lw-link-btn" data-rt-browse="${this._esc(p.destination_hash)}">Browse</button>`
                        : ''
                }</td>
                <td class="lw-time">${this._fmtTime(p.first_seen)}</td>
            </tr>
        `).join('');

        tbody.querySelectorAll('[data-rt-browse]').forEach((btn) => {
            btn.addEventListener('click', () => this.browseNode(btn.dataset.rtBrowse));
        });
    }

    async _markRead(nodeId) {
        try {
            await fetch(`/api/messages/conversation/${encodeURIComponent(nodeId)}/read`, {
                method: 'POST', credentials: 'same-origin',
            });
        } catch (_) {}
        this._loadMessages();
    }

    async _loadMessages() {
        try {
            const r = await fetch('/api/messages/conversations', { credentials: 'same-origin' });
            if (!r.ok) return;
            const conversations = (await r.json())
                .filter((c) => c.protocol === 'reticulum');
            this._setText('rt-stat-conversations', conversations.length);
            this._renderMessages(conversations);
        } catch (_) {}
    }

    _renderMessages(conversations) {
        const tbody = this._q('#rt-message-tbody');
        const empty = this._q('#rt-message-empty');
        if (!tbody) return;

        if (!conversations.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = conversations.map((c) => `
            <tr class="lw-pkt-row" data-node-id="${this._esc(c.node_id)}"
                ${c.unread_count ? 'title="Click to mark as read"' : ''}>
                <td class="lw-time">${this._fmtTime(c.last_timestamp)}</td>
                <td class="mt-name">${this._esc(c.node_name || c.node_id)}</td>
                <td>${this._esc(c.last_message || '')}</td>
                <td class="lw-num">${c.unread_count ? c.unread_count : ''}</td>
            </tr>
        `).join('');
    }

    async _loadAnnounces() {
        try {
            const r = await fetch('/api/reticulum/announces', { credentials: 'same-origin' });
            if (!r.ok) return;
            this._announces = await r.json();
            this._renderAnnounces();
        } catch (_) {}
    }

    _renderAnnounces() {
        const tbody = this._q('#rt-announce-tbody');
        const empty = this._q('#rt-announce-empty');
        if (!tbody) return;
        if (!this._announces.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        tbody.innerHTML = this._announces.slice(0, RT_ANNOUNCE_LIMIT).map((a) => `
            <tr>
                <td class="lw-time">${this._fmtTime(a.ts)}</td>
                <td class="mt-name">${this._esc(a.display_name || '--')}</td>
                <td class="lw-id">${this._esc(a.destination_hash)}</td>
                <td>${this._fmtAspect(a.aspect)}</td>
            </tr>
        `).join('');
    }

    async _handleAnnounce() {
        const btn = this._q('#rt-announce-btn');
        if (!btn) return;
        btn.disabled = true;
        try {
            const r = await fetch('/api/reticulum/announce', {
                method: 'POST', credentials: 'same-origin',
            });
            this._toast(r.ok ? 'Announce sent.' : 'Announce failed.');
        } catch (_) {
            this._toast('Announce failed.');
        } finally {
            btn.disabled = false;
        }
    }

    _toast(message) {
        // Same shared #r-toast pill app.js's own _toastAdminRequired() uses.
        let toast = document.getElementById('r-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'r-toast';
            toast.className = 'r-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('r-toast--visible');
        setTimeout(() => toast.classList.remove('r-toast--visible'), 2500);
    }

    async _handleSend(event) {
        event.preventDefault();
        const status = this._q('#rt-send-status');
        const btn = this._q('#rt-send-btn');
        const peerEl = this._q('#rt-send-peer');
        const textEl = this._q('#rt-send-text');
        const destination_hash = peerEl?.value || '';
        const text = (textEl?.value || '').trim();
        if (!destination_hash || !text) return;

        btn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending…';
        try {
            const r = await fetch('/api/reticulum/send', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ destination_hash, text }),
            });
            const result = await r.json().catch(() => ({}));
            if (r.ok) {
                status.dataset.kind = 'success';
                status.textContent = 'Sent.';
                textEl.value = '';
                this._loadMessages();
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

    _fmtAspect(aspect) {
        const cls = RT_ASPECT_BADGES[aspect] || '';
        return `<span class="mt-badge ${cls}">${this._esc(aspect || '--')}</span>`;
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

    _setText(id, val) {
        const el = this._q(`#${id}`);
        if (el) el.textContent = val;
    }
}

window.registerSidebarPage({
    route: 'reticulum',
    make: () => new ReticulumPanel(),
});
