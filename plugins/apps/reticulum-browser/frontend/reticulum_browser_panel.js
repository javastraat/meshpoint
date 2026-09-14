/**
 * Reticulum Browser -- a full multi-tab NomadNet browser for Reticulum.
 *
 * Tabs, address bar, back/forward/reload, favourites, a raw/rendered
 * view toggle, and keyboard shortcuts -- built fresh against Meshpoint's
 * own patterns, the same ones the reticulum plugin's own Browse tab and
 * the reticulum-dashboard plugin's quick-browse modal already use
 * (_splitAddr/_followLink shape, the shared favourites list,
 * window.MicronParser rendering).
 *
 * Deliberately NOT included (see README.md "What's not here"):
 *   - fingerprint identification of remote hosts (not built yet)
 *   - a local NomadNet search engine + page cache (a background crawler
 *     + index, not a browser-tab feature -- its own service-seam plugin
 *     if built at all, not bundled into this one)
 *
 * Requires the reticulum plugin enabled (plugin.toml `requires =
 * "reticulum"`) -- window.MicronParser and the /api/reticulum/nomad/*
 * routes both come from there.
 */

// Same localStorage key + {hash, name} shape the reticulum plugin's own
// Browse tab / Peers drawer / and the reticulum-dashboard plugin's
// quick-browse modal all use -- duplicated here on purpose, same small-
// duplication convention all of those already follow, so a node
// favourited anywhere shows favourited everywhere.
const _RB_FAV_KEY = 'meshpoint.rtNomadFavourites';

function _rbFavourites() {
    try {
        const v = JSON.parse(localStorage.getItem(_RB_FAV_KEY) || '[]');
        return Array.isArray(v) ? v.filter((f) => f && f.hash) : [];
    } catch (_) { return []; }
}

function _rbIsFavourite(hash) {
    return _rbFavourites().some((f) => f.hash === hash);
}

function _rbToggleFavourite(hash, name) {
    const list = _rbFavourites();
    const idx = list.findIndex((f) => f.hash === hash);
    if (idx >= 0) list.splice(idx, 1);
    else list.push({ hash, name: name || `${hash.slice(0, 12)}…` });
    try { localStorage.setItem(_RB_FAV_KEY, JSON.stringify(list)); } catch (_) {}
    return idx < 0; // true if it's now favourited
}

let _rbTabSeq = 0;

class ReticulumBrowserPanel {
    constructor() {
        this._root = null;
        this._tabs = [];
        this._activeTabId = null;
        this._nodes = [];
        this._nodeSearchQuery = '';
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Reticulum Browser</h2>
                <div class="lw-panel__actions">
                    <span class="lw-panel__limit">A multi-tab NomadNet browser</span>
                </div>
            </header>

            <div class="rb-bar">
                <div class="rb-bar-row rb-bar-row--find">
                    <input type="search" class="cfg-field__input rb-search" data-rb-search
                           placeholder="Filter nodes…" autocomplete="off" spellcheck="false"
                           aria-label="Filter NomadNet nodes">
                    <select class="cfg-field__input rb-nodes" data-rb-nodes>
                        <option value="">— pick a node —</option>
                    </select>
                    <select class="cfg-field__input rb-favs" data-rb-favs aria-label="Jump to a favourite node">
                        <option value="">★ Favourites</option>
                    </select>
                    <button class="terminal-button rt-nomad__fav" type="button" data-rb-fav
                            title="Favourite this node" disabled>&#9734;</button>
                </div>
                <div class="rb-bar-row rb-bar-row--nav">
                    <button class="terminal-button" type="button" data-rb-back title="Back" disabled>&larr;</button>
                    <button class="terminal-button" type="button" data-rb-forward title="Forward" disabled>&rarr;</button>
                    <button class="terminal-button" type="button" data-rb-reload title="Reload" disabled>&#x21bb;</button>
                    <input type="text" class="cfg-field__input rb-addr" data-rb-addr
                           placeholder="&lt;hash&gt;:/page/x.mu  —  or  :/page/info.mu on the current node"
                           autocomplete="off" spellcheck="false" aria-label="Node address">
                    <button class="terminal-button" type="button" data-rb-go>Go</button>
                    <button class="terminal-button" type="button" data-rb-raw
                            title="Toggle raw/rendered view">{ }</button>
                </div>
            </div>

            <div class="rb-tabstrip" data-rb-tabstrip></div>

            <div class="rb-page" data-rb-page>
                <p class="lw-empty">Pick a node above, or type an address
                (<code>&lt;hash&gt;:/page/x.mu</code>). Once you're on a node, the bar
                holds its full address — edit the path and press Go, or open a new tab
                (<code>Ctrl/Cmd+T</code>) to browse a second node alongside this one.</p>
            </div>
        `;

        this._searchEl = this._q('[data-rb-search]');
        this._nodesEl = this._q('[data-rb-nodes]');
        this._favsEl = this._q('[data-rb-favs]');
        this._favBtn = this._q('[data-rb-fav]');
        this._addrEl = this._q('[data-rb-addr]');
        this._backBtn = this._q('[data-rb-back]');
        this._fwdBtn = this._q('[data-rb-forward]');
        this._reloadBtn = this._q('[data-rb-reload]');
        this._rawBtn = this._q('[data-rb-raw]');
        this._tabstripEl = this._q('[data-rb-tabstrip]');
        this._pageEl = this._q('[data-rb-page]');

        this._searchEl.addEventListener('input', (e) => {
            this._nodeSearchQuery = e.target.value.trim().toLowerCase();
            this._renderNodeOptions();
        });
        this._nodesEl.addEventListener('change', () => {
            const hash = this._nodesEl.value;
            if (hash) this._go(hash, '/page/index.mu');
        });
        this._favsEl.addEventListener('change', () => {
            const chosen = this._favsEl.value;
            this._favsEl.value = '';
            if (chosen) this._go(chosen, '/page/index.mu');
        });
        this._favBtn.addEventListener('click', () => {
            const tab = this._activeTab();
            if (!tab || !tab.hash) return;
            const nowOn = _rbToggleFavourite(tab.hash, tab.title);
            this._syncFavBtn(nowOn);
            this._renderFavsSelect();
        });
        this._q('[data-rb-go]').addEventListener('click', () => this._goFromAddr());
        this._addrEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this._goFromAddr(); }
        });
        this._backBtn.addEventListener('click', () => this._historyGo(-1));
        this._fwdBtn.addEventListener('click', () => this._historyGo(1));
        this._reloadBtn.addEventListener('click', () => this._reload());
        this._rawBtn.addEventListener('click', () => this._toggleRaw());
        this._pageEl.addEventListener('click', (e) => {
            const a = e.target.closest('a[data-nomad-url]');
            if (!a) return;
            e.preventDefault();
            this._followLink(a);
        });
        this._tabstripEl.addEventListener('click', (e) => {
            const closeBtn = e.target.closest('[data-rb-tab-close]');
            if (closeBtn) { this._closeTab(closeBtn.dataset.rbTabClose); return; }
            const newBtn = e.target.closest('[data-rb-tab-new]');
            if (newBtn) { this._newTab(); return; }
            const tabEl = e.target.closest('[data-rb-tab-id]');
            if (tabEl) this._switchTab(tabEl.dataset.rbTabId);
        });

        this._renderFavsSelect();
        this._newTab();
    }

    show() {
        this._loadNodes();
        document.addEventListener('keydown', this._onKeyDown);
    }

    hide() {
        document.removeEventListener('keydown', this._onKeyDown);
    }

    // --- Tabs ---------------------------------------------------------------

    _activeTab() {
        return this._tabs.find((t) => t.id === this._activeTabId) || null;
    }

    _newTab() {
        const tab = {
            id: `rb${++_rbTabSeq}`, hash: null, path: null, title: 'New tab',
            content: null, rawMode: false, history: [], historyIdx: -1,
        };
        this._tabs.push(tab);
        this._activeTabId = tab.id;
        this._renderTabStrip();
        this._renderActiveTab();
        this._addrEl.focus();
    }

    _closeTab(tabId) {
        const idx = this._tabs.findIndex((t) => t.id === tabId);
        if (idx === -1) return;
        this._tabs.splice(idx, 1);
        if (!this._tabs.length) {
            // Never zero tabs -- a fresh blank one takes its place.
            this._newTab();
            return;
        }
        if (this._activeTabId === tabId) {
            const next = this._tabs[Math.min(idx, this._tabs.length - 1)];
            this._activeTabId = next.id;
        }
        this._renderTabStrip();
        this._renderActiveTab();
    }

    _switchTab(tabId) {
        if (!this._tabs.some((t) => t.id === tabId)) return;
        this._activeTabId = tabId;
        this._renderTabStrip();
        this._renderActiveTab();
    }

    _renderTabStrip() {
        const html = this._tabs.map((t) => `
            <div class="rb-tab${t.id === this._activeTabId ? ' rb-tab--active' : ''}"
                 data-rb-tab-id="${t.id}" title="${this._esc(t.hash || 'New tab')}">
                <span class="rb-tab__title">${this._esc(t.title)}</span>
                <button type="button" class="rb-tab__close" data-rb-tab-close="${t.id}"
                        title="Close tab (Ctrl/Cmd+W)" aria-label="Close tab">&times;</button>
            </div>
        `).join('');
        this._tabstripEl.innerHTML = html
            + `<button type="button" class="rb-tab__new" data-rb-tab-new title="New tab (Ctrl/Cmd+T)">+</button>`;
    }

    /** Re-renders the page body + syncs the toolbar (address/back/forward/
     * reload/favourite/raw) from the active tab's own cached state --
     * switching tabs never re-fetches, it just re-displays what that tab
     * already loaded. */
    _renderActiveTab() {
        const tab = this._activeTab();
        if (!tab) return;
        this._addrEl.value = tab.hash ? `${tab.hash}:${tab.path}` : '';
        this._backBtn.disabled = tab.historyIdx <= 0;
        this._fwdBtn.disabled = tab.historyIdx >= tab.history.length - 1;
        this._reloadBtn.disabled = tab.historyIdx < 0;
        this._rawBtn.classList.toggle('is-active', tab.rawMode);
        this._syncFavBtn(tab.hash ? _rbIsFavourite(tab.hash) : false);
        this._renderPage(tab);
    }

    _renderPage(tab) {
        if (tab.content == null) {
            this._pageEl.innerHTML = `<p class="lw-empty">Pick a node above, or type an address
                (<code>&lt;hash&gt;:/page/x.mu</code>).</p>`;
            return;
        }
        if (tab.rawMode) {
            this._pageEl.textContent = tab.content;
            return;
        }
        this._pageEl.textContent = '';
        if (window.MicronParser) {
            this._pageEl.appendChild(new window.MicronParser(true).parseToHtml(tab.content));
        } else {
            this._pageEl.textContent = tab.content;
        }
    }

    _toggleRaw() {
        const tab = this._activeTab();
        if (!tab) return;
        tab.rawMode = !tab.rawMode;
        this._rawBtn.classList.toggle('is-active', tab.rawMode);
        this._renderPage(tab);
    }

    // --- Navigation (per active tab) -----------------------------------------

    _goFromAddr() {
        const tab = this._activeTab();
        const raw = (this._addrEl.value || '').trim();
        if (!tab || !raw) return;
        const { hash, path } = this._splitAddr(raw, tab.hash);
        if (!hash) return;
        this._go(hash, path);
    }

    _go(hash, path) {
        const tab = this._activeTab();
        if (tab) this._fetch(tab, hash, path, true);
    }

    _reload() {
        const tab = this._activeTab();
        if (!tab) return;
        const e = tab.history[tab.historyIdx];
        if (e) this._fetch(tab, e.hash, e.path, false);
    }

    _historyGo(delta) {
        const tab = this._activeTab();
        if (!tab) return;
        const next = tab.historyIdx + delta;
        if (next < 0 || next >= tab.history.length) return;
        tab.historyIdx = next;
        const e = tab.history[next];
        this._fetch(tab, e.hash, e.path, false);
    }

    async _fetch(tab, hash, path, pushHistory) {
        this._pageEl.innerHTML = '<p class="lw-empty">Loading…</p>';
        try {
            const r = await fetch('/api/reticulum/nomad/page', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ destination_hash: hash, path, field_data: null }),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
                this._pageEl.textContent = data.error || `Failed (HTTP ${r.status})`;
                return;
            }
            tab.hash = hash;
            tab.path = path;
            tab.content = data.content || '';
            const known = this._nodes.find((n) => n.destination_hash === hash);
            const fav = _rbFavourites().find((f) => f.hash === hash);
            tab.title = fav?.name || known?.display_name || `${hash.slice(0, 8)}…`;
            if (pushHistory) {
                tab.history = tab.history.slice(0, tab.historyIdx + 1);
                tab.history.push({ hash, path });
                tab.historyIdx = tab.history.length - 1;
            }
            if (tab.id === this._activeTabId) this._renderActiveTab();
            this._renderTabStrip();
        } catch (e) {
            this._pageEl.textContent = `Network error: ${e.message}`;
        }
    }

    /** Simplified from the reticulum plugin's own reticulum_nomad.js --
     * no form-field submission, no /file/ downloads yet (same scope note
     * as this plugin's README "what's not here" -- may follow later).
     * An external http(s) link opens a normal browser tab. */
    _followLink(a) {
        const tab = this._activeTab();
        if (!tab) return;
        let addr = (a.dataset.nomadUrl || '').split('`')[0];
        addr = addr.replace(/^nomadnetwork:\/\//, '');
        if (/^https?:\/\//i.test(addr)) {
            window.open(addr, '_blank', 'noopener');
            return;
        }
        const { hash, path } = this._splitAddr(addr, tab.hash);
        if (!hash || path.startsWith('/file/')) return;
        this._go(hash, path);
    }

    _splitAddr(raw, currentHash) {
        raw = raw.replace(/^nomadnetwork:\/\//, '');
        if (raw.startsWith(':')) return { hash: currentHash || '', path: raw.slice(1) || '/page/index.mu' };
        if (raw.startsWith('/')) return { hash: currentHash || '', path: raw };
        const idx = raw.indexOf(':');
        if (idx === -1) return { hash: raw, path: '/page/index.mu' };
        return { hash: raw.slice(0, idx), path: raw.slice(idx + 1) || '/page/index.mu' };
    }

    // --- Node picker / favourites --------------------------------------------

    async _loadNodes() {
        try {
            const r = await fetch('/api/reticulum/nomad/nodes', { credentials: 'same-origin' });
            if (!r.ok) return;
            this._nodes = await r.json();
            this._renderNodeOptions();
        } catch (_) {}
    }

    _renderNodeOptions() {
        const q = this._nodeSearchQuery;
        const filtered = q
            ? this._nodes.filter((n) =>
                (n.display_name || '').toLowerCase().includes(q)
                || n.destination_hash.toLowerCase().includes(q))
            : this._nodes;
        this._nodesEl.innerHTML = '<option value="">— pick a node —</option>'
            + filtered.map((n) => {
                const name = (n.display_name || n.destination_hash.slice(0, 12)).slice(0, 46);
                return `<option value="${this._esc(n.destination_hash)}" title="${this._esc(n.destination_hash)}">${this._esc(name)}</option>`;
            }).join('');
    }

    _renderFavsSelect() {
        const favs = _rbFavourites();
        this._favsEl.innerHTML = '<option value="">★ Favourites</option>'
            + favs.map((f) => `<option value="${this._esc(f.hash)}">${this._esc(f.name)}</option>`).join('');
        this._favsEl.disabled = !favs.length;
    }

    _syncFavBtn(isFav) {
        const tab = this._activeTab();
        this._favBtn.disabled = !tab || !tab.hash;
        this._favBtn.classList.toggle('rt-nomad__fav--on', !!isFav);
        this._favBtn.innerHTML = isFav ? '&#9733;' : '&#9734;';
        this._favBtn.title = isFav ? 'Remove from favourites' : 'Favourite this node';
    }

    // --- Keyboard shortcuts ---------------------------------------------------
    // Only active while this page is shown (wired in show()/hide()). Ctrl on
    // Windows/Linux, Cmd on macOS -- e.metaKey covers Cmd, e.ctrlKey covers Ctrl.

    _onKeyDown(e) {
        const mod = e.metaKey || e.ctrlKey;
        if (mod && e.key.toLowerCase() === 't') {
            e.preventDefault();
            this._newTab();
        } else if (mod && e.key.toLowerCase() === 'w') {
            e.preventDefault();
            if (this._activeTabId) this._closeTab(this._activeTabId);
        } else if (mod && e.key.toLowerCase() === 'r') {
            e.preventDefault();
            this._reload();
        } else if (e.altKey && e.key === 'ArrowLeft') {
            e.preventDefault();
            this._historyGo(-1);
        } else if (e.altKey && e.key === 'ArrowRight') {
            e.preventDefault();
            this._historyGo(1);
        }
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    _q(sel) { return this._root ? this._root.querySelector(sel) : null; }
}

window.registerSidebarPage({
    route: 'reticulum-browser',
    make: () => new ReticulumBrowserPanel(),
});
