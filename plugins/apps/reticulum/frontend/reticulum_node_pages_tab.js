/**
 * Reticulum plugin page: "Pages" tab -- an editor for the local `.mu`
 * files a hosted NomadNet node serves (`plugins.reticulum.node_pages_dir`).
 *
 * Only shown when node hosting is on. Left: the file list (`index.mu`
 * first) + New. Right: a textarea of raw Micron with a live preview
 * rendered by the same `window.MicronParser` the Browse tab uses. Save
 * PUTs `/api/reticulum/nomad/pages/{name}`; the backend re-registers the
 * node's request handlers so a new page is served without a restart.
 *
 * Plain fetch()-driven, same shape as reticulum_settings_tab.js.
 */

class ReticulumNodePagesTab {
    constructor(el) {
        this._el = el;
        this._mounted = false;
        this._pages = [];
        this._current = null;        // { name, isNew }
        this._parser = window.MicronParser ? new window.MicronParser(true) : null;
        this._previewTimer = null;
        this._dirty = false;
    }

    show() {
        if (!this._mounted) this._mount();
        this._loadList();
    }

    hide() {
        clearTimeout(this._previewTimer);
    }

    _mount() {
        this._mounted = true;
        this._el.innerHTML = `
            <div class="rt-pages">
                <aside class="rt-pages__list">
                    <div class="rt-pages__list-head">
                        <span>Pages</span>
                        <button type="button" class="terminal-button rt-pages__new" data-pg-new>+ New</button>
                    </div>
                    <ul data-pg-list></ul>
                    <p class="rt-pages__dir" data-pg-dir></p>
                    <p class="rt-pages__hint" data-pg-hosting></p>
                </aside>
                <section class="rt-pages__editor">
                    <div class="rt-pages__editor-head">
                        <input type="text" class="cfg-field__input rt-pages__name" data-pg-name
                               placeholder="index.mu" autocomplete="off" spellcheck="false" hidden>
                        <span class="rt-pages__name-static" data-pg-name-static></span>
                        <div class="rt-pages__actions">
                            <button type="button" class="terminal-button" data-pg-sample>Load sample</button>
                            <button type="button" class="terminal-button" data-pg-delete hidden>Delete</button>
                            <button type="button" class="terminal-button terminal-button--primary" data-pg-save disabled>Save</button>
                        </div>
                    </div>
                    <p class="cfg-status" data-pg-status aria-live="polite"></p>
                    <div class="rt-pages__split">
                        <textarea class="rt-pages__src" data-pg-src spellcheck="false"
                                  placeholder="Pick a page on the left, or New, to start editing."
                                  disabled></textarea>
                        <div class="rt-nomad__page rt-pages__preview" data-pg-preview></div>
                    </div>
                </section>
            </div>
        `;
        this._list = this._q('[data-pg-list]');
        this._dirEl = this._q('[data-pg-dir]');
        this._hostingEl = this._q('[data-pg-hosting]');
        this._nameEl = this._q('[data-pg-name]');
        this._nameStaticEl = this._q('[data-pg-name-static]');
        this._srcEl = this._q('[data-pg-src]');
        this._previewEl = this._q('[data-pg-preview]');
        this._statusEl = this._q('[data-pg-status]');
        this._saveBtn = this._q('[data-pg-save]');
        this._deleteBtn = this._q('[data-pg-delete]');
        this._sampleBtn = this._q('[data-pg-sample]');

        this._q('[data-pg-new]').addEventListener('click', () => this._newPage());
        this._saveBtn.addEventListener('click', () => this._save());
        this._deleteBtn.addEventListener('click', () => this._delete());
        this._sampleBtn.addEventListener('click', () => this._loadSample());
        this._srcEl.addEventListener('input', () => {
            this._dirty = true;
            this._saveBtn.disabled = false;
            this._schedulePreview();
        });
        this._nameEl.addEventListener('input', () => {
            this._saveBtn.disabled = !this._nameEl.value.trim();
        });
    }

    _q(sel) { return this._el.querySelector(sel); }

    async _loadList() {
        try {
            const r = await fetch('/api/reticulum/nomad/pages', { credentials: 'same-origin' });
            if (!r.ok) { this._setStatus('error', `Could not load pages (HTTP ${r.status}).`); return; }
            const body = await r.json();
            this._pages = body.pages || [];
            this._dirEl.textContent = body.pages_dir ? `Folder: ${body.pages_dir}` : '';
            this._hostingEl.textContent = body.node_hosting
                ? 'Node is hosting — saved pages are served immediately.'
                : 'Node is not hosting right now — edits save but aren’t served until it starts.';
            this._renderList();
        } catch (_e) {
            this._setStatus('error', 'Network error loading pages.');
        }
    }

    _renderList() {
        this._list.innerHTML = '';
        this._pages.forEach((p) => {
            const li = document.createElement('li');
            li.className = 'rt-pages__item';
            if (this._current && !this._current.isNew && this._current.name === p.name) {
                li.classList.add('rt-pages__item--active');
            }
            li.textContent = p.name;
            if (!p.exists) {
                const tag = document.createElement('span');
                tag.className = 'rt-pages__tag';
                tag.textContent = 'not created';
                li.appendChild(tag);
            }
            li.addEventListener('click', () => this._open(p.name));
            this._list.appendChild(li);
        });
    }

    async _open(name) {
        if (!(await this._confirmDiscard())) return;
        try {
            const r = await fetch(`/api/reticulum/nomad/pages/${encodeURIComponent(name)}`,
                { credentials: 'same-origin' });
            if (!r.ok) { this._setStatus('error', `Could not open ${name} (HTTP ${r.status}).`); return; }
            const body = await r.json();
            this._current = { name, isNew: false };
            this._nameEl.hidden = true;
            this._nameStaticEl.textContent = name;
            this._srcEl.disabled = false;
            this._srcEl.value = body.content || '';
            this._deleteBtn.hidden = false;
            this._saveBtn.disabled = true;
            this._dirty = false;
            this._setStatus('', '');
            this._renderList();
            this._renderPreview();
        } catch (_e) {
            this._setStatus('error', 'Network error opening page.');
        }
    }

    async _newPage() {
        if (!(await this._confirmDiscard())) return;
        this._current = { name: null, isNew: true };
        this._nameEl.hidden = false;
        this._nameEl.value = '';
        this._nameStaticEl.textContent = '';
        this._srcEl.disabled = false;
        this._srcEl.value = '';
        this._deleteBtn.hidden = true;
        this._saveBtn.disabled = true;
        this._dirty = false;
        this._setStatus('', 'New page — name it (e.g. about.mu) and Save.');
        this._renderList();
        this._renderPreview();
        this._nameEl.focus();
    }

    async _loadSample() {
        if (this._srcEl.disabled) {
            this._setStatus('error', 'Open a page or start a new one first.');
            return;
        }
        if (this._srcEl.value.trim() && !window.confirm('Replace the editor contents with the sample page?')) {
            return;
        }
        try {
            const r = await fetch('/api/reticulum/nomad/sample-page', { credentials: 'same-origin' });
            const body = await r.json();
            this._srcEl.value = body.content || '';
            this._dirty = true;
            this._saveBtn.disabled = this._current?.isNew && !this._nameEl.value.trim();
            this._renderPreview();
        } catch (_e) {
            this._setStatus('error', 'Could not load the sample.');
        }
    }

    async _save() {
        const name = this._current?.isNew ? this._nameEl.value.trim() : this._current?.name;
        if (!name) return;
        this._saveBtn.disabled = true;
        this._setStatus('pending', 'Saving…');
        try {
            const r = await fetch(`/api/reticulum/nomad/pages/${encodeURIComponent(name)}`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: this._srcEl.value }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) {
                this._setStatus('error', body.detail || `Save failed (HTTP ${r.status}).`);
                this._saveBtn.disabled = false;
                return;
            }
            this._current = { name, isNew: false };
            this._nameEl.hidden = true;
            this._nameStaticEl.textContent = name;
            this._deleteBtn.hidden = false;
            this._dirty = false;
            this._setStatus('success', body.served
                ? `Saved — ${name} is live on the node.`
                : `Saved. Enable node hosting to serve it.`);
            await this._loadList();
        } catch (_e) {
            this._setStatus('error', 'Network error saving page.');
            this._saveBtn.disabled = false;
        }
    }

    async _delete() {
        const name = this._current?.name;
        if (!name || this._current.isNew) return;
        if (!window.confirm(`Delete ${name} from the node's pages folder?`)) return;
        try {
            const r = await fetch(`/api/reticulum/nomad/pages/${encodeURIComponent(name)}`, {
                method: 'DELETE', credentials: 'same-origin',
            });
            if (!r.ok) {
                const body = await r.json().catch(() => ({}));
                this._setStatus('error', body.detail || `Delete failed (HTTP ${r.status}).`);
                return;
            }
            this._current = null;
            this._srcEl.value = '';
            this._srcEl.disabled = true;
            this._deleteBtn.hidden = true;
            this._nameStaticEl.textContent = '';
            this._saveBtn.disabled = true;
            this._previewEl.innerHTML = '';
            this._setStatus('success', `${name} deleted.`);
            await this._loadList();
        } catch (_e) {
            this._setStatus('error', 'Network error deleting page.');
        }
    }

    _schedulePreview() {
        clearTimeout(this._previewTimer);
        this._previewTimer = setTimeout(() => this._renderPreview(), 200);
    }

    _renderPreview() {
        if (!this._previewEl) return;
        this._previewEl.innerHTML = '';
        const text = this._srcEl.value;
        if (!text.trim()) return;
        if (this._parser) {
            try {
                this._previewEl.appendChild(this._parser.parseToHtml(text));
            } catch (_e) {
                this._previewEl.textContent = text;
            }
        } else {
            this._previewEl.textContent = text;
        }
    }

    async _confirmDiscard() {
        if (!this._dirty) return true;
        return window.confirm('Discard unsaved changes to this page?');
    }

    _setStatus(kind, msg) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = msg;
    }
}

window.ReticulumNodePagesTab = ReticulumNodePagesTab;
