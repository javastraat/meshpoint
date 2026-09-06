/**
 * Reticulum plugin page: "Browse" tab -- a minimal NomadNet browser.
 *
 * Lists `nomadnetwork.node` peers, fetches a node's pages via
 * POST /api/reticulum/nomad/page, renders the Micron markup with
 * window.MicronParser (reticulum_micron.js), and lets you follow links
 * and submit page forms. Back/forward history, same-node (`:/path`) and
 * cross-node (`<hash>:/path`) links.
 *
 * Admin-only (like Send/Settings) -- POST /api/reticulum/nomad/page
 * requires admin, and browsing establishes real RNS Links.
 */

class ReticulumNomadTab {
    constructor(el) {
        this._el = el;
        this._mounted = false;
        this._nodes = [];
        this._history = [];      // [{hash, path, field_data}]
        this._historyIdx = -1;
        this._parser = null;
        this._loading = false;
    }

    show() {
        if (!this._mounted) this._mount();
        this._loadNodes();
    }

    hide() {}

    /** Called by the panel when a Peers-row "Browse" button is clicked. */
    openNode(destinationHash) {
        if (!this._mounted) this._mount();
        this._loadNodes();
        this._go(destinationHash, '/page/index.mu');
    }

    _mount() {
        this._mounted = true;
        this._parser = window.MicronParser ? new window.MicronParser(true) : null;
        this._el.innerHTML = `
            <div class="rt-nomad">
                <div class="rt-nomad__bar">
                    <select class="cfg-field__input rt-nomad__nodes" data-nomad-nodes>
                        <option value="">— pick a node —</option>
                    </select>
                    <input type="text" class="cfg-field__input rt-nomad__addr" data-nomad-addr
                           placeholder="&lt;destination hash&gt;:/page/index.mu" autocomplete="off" spellcheck="false">
                    <button class="terminal-button" type="button" data-nomad-go>Go</button>
                    <button class="terminal-button" type="button" data-nomad-back title="Back" disabled>&larr;</button>
                    <button class="terminal-button" type="button" data-nomad-fwd title="Forward" disabled>&rarr;</button>
                    <button class="terminal-button" type="button" data-nomad-reload title="Reload" disabled>&#x21bb;</button>
                </div>
                <p class="cfg-status" data-nomad-status aria-live="polite"></p>
                <div class="rt-nomad__page" data-nomad-page>
                    <p class="lw-empty">Pick a NomadNet node above, or type a
                    <code>&lt;hash&gt;:/page/index.mu</code> address, to start browsing.</p>
                </div>
            </div>
        `;

        this._nodesEl = this._q('[data-nomad-nodes]');
        this._addrEl = this._q('[data-nomad-addr]');
        this._statusEl = this._q('[data-nomad-status]');
        this._pageEl = this._q('[data-nomad-page]');

        this._nodesEl.addEventListener('change', () => {
            if (this._nodesEl.value) this._go(this._nodesEl.value, '/page/index.mu');
        });
        this._q('[data-nomad-go]').addEventListener('click', () => this._goFromAddr());
        this._addrEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this._goFromAddr(); }
        });
        this._q('[data-nomad-back]').addEventListener('click', () => this._history_go(-1));
        this._q('[data-nomad-fwd]').addEventListener('click', () => this._history_go(1));
        this._q('[data-nomad-reload]').addEventListener('click', () => {
            const e = this._history[this._historyIdx];
            if (e) this._fetch(e.hash, e.path, e.field_data, false);
        });

        // Delegated: a Micron link inside the rendered page.
        this._pageEl.addEventListener('click', (e) => {
            const a = e.target.closest('a[data-nomad-url]');
            if (!a) return;
            e.preventDefault();
            this._followLink(a);
        });
    }

    _q(sel) { return this._el.querySelector(sel); }

    async _loadNodes() {
        try {
            const r = await fetch('/api/reticulum/nomad/nodes', { credentials: 'same-origin' });
            if (!r.ok) return;
            this._nodes = await r.json();
        } catch (_) { return; }
        const current = this._nodesEl.value;
        this._nodesEl.innerHTML = '<option value="">— pick a node —</option>'
            + this._nodes.map((n) => `
                <option value="${this._esc(n.destination_hash)}">
                    ${this._esc(n.display_name || n.destination_hash)}
                </option>`).join('');
        if (current) this._nodesEl.value = current;
    }

    _goFromAddr() {
        const raw = (this._addrEl.value || '').trim();
        if (!raw) return;
        const { hash, path } = this._splitAddr(raw);
        if (!hash) { this._status('error', 'Address must be <hash>:/page/path.mu'); return; }
        this._go(hash, path);
    }

    /** "<hex>:/page/x.mu" -> {hash, path}. A bare "/page/x.mu" or ":/page/x.mu"
     * resolves against the current node. */
    _splitAddr(raw, currentHash) {
        raw = raw.replace(/^nomadnetwork:\/\//, '');
        if (raw.startsWith(':')) return { hash: currentHash || '', path: raw.slice(1) || '/page/index.mu' };
        if (raw.startsWith('/')) return { hash: currentHash || '', path: raw };
        const idx = raw.indexOf(':');
        if (idx === -1) return { hash: raw, path: '/page/index.mu' };
        return { hash: raw.slice(0, idx), path: raw.slice(idx + 1) || '/page/index.mu' };
    }

    _go(hash, path, fieldData) {
        this._fetch(hash, path, fieldData, true);
    }

    _history_go(delta) {
        const next = this._historyIdx + delta;
        if (next < 0 || next >= this._history.length) return;
        this._historyIdx = next;
        const e = this._history[next];
        this._fetch(e.hash, e.path, e.field_data, false);
        this._syncNav();
    }

    async _fetch(hash, path, fieldData, pushHistory) {
        if (this._loading) return;
        this._loading = true;
        this._status('pending', `Fetching ${hash.slice(0, 8)}… ${path}`);
        this._addrEl.value = `${hash}:${path}`;
        try {
            const r = await fetch('/api/reticulum/nomad/page', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ destination_hash: hash, path, field_data: fieldData || null }),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
                this._status('error', data.error || `Failed (HTTP ${r.status})`);
                return;
            }
            this._render(data.content || '');
            this._status('success', `${hash.slice(0, 8)}… ${path}`);
            if (pushHistory) {
                this._history = this._history.slice(0, this._historyIdx + 1);
                this._history.push({ hash, path, field_data: fieldData || null });
                this._historyIdx = this._history.length - 1;
            }
            this._syncNav();
        } catch (e) {
            this._status('error', `Network error: ${e.message}`);
        } finally {
            this._loading = false;
        }
    }

    _render(micron) {
        this._pageEl.textContent = '';
        if (!this._parser) {
            this._pageEl.textContent = micron;   // parser missing -- show raw
            return;
        }
        this._pageEl.appendChild(this._parser.parseToHtml(micron));
    }

    _followLink(a) {
        const currentHash = this._history[this._historyIdx]?.hash || '';
        const rawUrl = a.dataset.nomadUrl || '';
        // rawUrl may carry `key=val|key2=val2 request vars after a backtick
        let addrPart = rawUrl;
        const varData = {};
        const btick = rawUrl.indexOf('`');
        if (btick !== -1) {
            addrPart = rawUrl.slice(0, btick);
            for (const pair of rawUrl.slice(btick + 1).split('|')) {
                const eq = pair.indexOf('=');
                if (eq !== -1) varData[`var_${pair.slice(0, eq)}`] = pair.slice(eq + 1);
            }
        }
        const { hash, path } = this._splitAddr(addrPart, currentHash);
        if (!hash) { this._status('error', 'Link has no node — nothing to open'); return; }

        // gather form fields this link asks to submit
        const fieldData = { ...varData };
        const spec = a.dataset.nomadFields;
        if (spec) {
            const wantAll = spec === '*';
            const wanted = wantAll ? null : new Set(spec.split('|'));
            this._pageEl.querySelectorAll('input[name], select[name], textarea[name]').forEach((inp) => {
                if (!wantAll && !wanted.has(inp.name)) return;
                if ((inp.type === 'checkbox' || inp.type === 'radio') && !inp.checked) return;
                fieldData[`field_${inp.name}`] = inp.value;
            });
        }
        this._go(hash, path, Object.keys(fieldData).length ? fieldData : null);
    }

    _syncNav() {
        this._q('[data-nomad-back]').disabled = this._historyIdx <= 0;
        this._q('[data-nomad-fwd]').disabled = this._historyIdx >= this._history.length - 1;
        this._q('[data-nomad-reload]').disabled = this._historyIdx < 0;
    }

    _status(kind, msg) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = msg;
    }

    _esc(s) {
        const el = document.createElement('span');
        el.textContent = s == null ? '' : String(s);
        return el.innerHTML;
    }
}

window.ReticulumNomadTab = ReticulumNomadTab;
