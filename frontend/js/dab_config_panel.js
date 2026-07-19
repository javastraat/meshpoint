/**
 * DAB+ Config tab -- shows what scripts/dab_channel_scan.py found (read
 * from its JSON output via GET /api/dab/scan-results) and lets an admin
 * set a friendlier display name per channel (PUT .../scan-results/{ch}/name),
 * layered on top of the raw broadcast ensemble label without touching it.
 *
 * Read-only against the RTL-SDR dongle itself -- this tab only reads/edits
 * a file the scan script already wrote on the device, so unlike Radio/
 * DAB+/P2000/Pagers/POCSAG/RTL433 it never needs to fight for the dongle
 * (see src/audio/sdr_registry.py) and needs no start/stop of its own.
 */
class DabConfigPanel {
    constructor() {
        this._root = null;
        this._data = null;
        this._editingChannel = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <section class="lsn-section">
                <div class="panel">
                    <div class="panel__header dabcfg-header">
                        <span>DAB+ Config</span>
                        <button class="terminal-button" type="button" data-dabcfg-refresh>Refresh</button>
                    </div>
                    <div class="panel__body">
                        <div class="dabcfg-hint">
                            Channels found by <code>scripts/dab_channel_scan.py</code> (run on the device).
                            Names here are editable overrides -- the raw scanned label is kept underneath
                            and used as the default whenever no override is set.
                        </div>
                        <div data-dabcfg-body>Loading...</div>
                    </div>
                </div>
            </section>
        `;
        this._root.querySelector('[data-dabcfg-refresh]').addEventListener('click', () => this._refresh());
    }

    show() {
        this._refresh();
    }

    hide() {
        // Static file, no live polling to stop.
    }

    async _refresh() {
        const body = this._root.querySelector('[data-dabcfg-body]');
        body.innerHTML = 'Loading...';
        try {
            const res = await fetch('/api/dab/scan-results');
            if (res.status === 404) {
                this._data = null;
                const err = await res.json().catch(() => ({}));
                body.innerHTML = `<div class="dabcfg-empty">
                    ${this._esc(err.detail || 'No DAB channel scan results found yet.')}
                </div>`;
                return;
            }
            if (!res.ok) {
                body.innerHTML = `<div class="dabcfg-empty">Error loading scan results (HTTP ${res.status}).</div>`;
                return;
            }
            this._data = await res.json();
            this._render();
        } catch (e) {
            body.innerHTML = `<div class="dabcfg-empty">Error loading scan results: ${this._esc(e.message)}</div>`;
        }
    }

    _render() {
        const body = this._root.querySelector('[data-dabcfg-body]');
        const channels = (this._data.channels || []).filter(c => c.ensemble || (c.stations || []).length);
        if (!channels.length) {
            body.innerHTML = `<div class="dabcfg-empty">Scan results loaded, but no channel has decoded anything yet.</div>`;
            return;
        }
        const lastRun = this._data.last_run_at ? new Date(this._data.last_run_at).toLocaleString() : 'unknown';
        body.innerHTML = `
            <div class="dabcfg-meta">Last scan: ${this._esc(lastRun)} &middot; ${channels.length} channel(s) with content</div>
            ${channels.map(c => this._rowHtml(c)).join('')}
        `;
        channels.forEach((c) => {
            const row = body.querySelector(`[data-dabcfg-row="${CSS.escape(c.channel)}"]`);
            if (!row) return;
            const editBtn = row.querySelector('[data-dabcfg-edit]');
            const saveBtn = row.querySelector('[data-dabcfg-save]');
            const cancelBtn = row.querySelector('[data-dabcfg-cancel]');
            if (editBtn) editBtn.addEventListener('click', () => this._startEdit(c.channel));
            if (saveBtn) saveBtn.addEventListener('click', () => this._saveEdit(c.channel));
            if (cancelBtn) cancelBtn.addEventListener('click', () => { this._editingChannel = null; this._render(); });
        });
    }

    _rowHtml(c) {
        const displayName = c.custom_name || c.ensemble || c.channel;
        const editing = this._editingChannel === c.channel;
        const stationCount = (c.stations || []).length;
        return `
            <div class="dabcfg-row" data-dabcfg-row="${this._esc(c.channel)}">
                <div class="dabcfg-row__top">
                    <div class="dabcfg-row__chan">${this._esc(c.channel)}</div>
                    <div class="dabcfg-row__name">
                        ${editing
                            ? `<input type="text" class="dabcfg-row__input" data-dabcfg-input
                                   value="${this._esc(c.custom_name || '')}"
                                   placeholder="${this._esc(c.ensemble || c.channel)}">`
                            : `${this._esc(displayName)}` +
                              (c.custom_name ? ' <span class="dabcfg-row__badge">custom</span>' : '')}
                    </div>
                    <div class="dabcfg-row__meta">SNR ${Number(c.snr || 0).toFixed(1)} dB &middot; ${stationCount} station(s)</div>
                    <div class="dabcfg-row__actions">
                        ${editing
                            ? `<button class="terminal-button" type="button" data-dabcfg-save>Save</button>
                               <button class="terminal-button" type="button" data-dabcfg-cancel>Cancel</button>`
                            : `<button class="terminal-button" type="button" data-dabcfg-edit>Rename</button>`}
                    </div>
                </div>
                ${stationCount ? `<div class="dabcfg-row__stations">${(c.stations || []).map(s => this._esc(s)).join(', ')}</div>` : ''}
            </div>
        `;
    }

    _startEdit(channel) {
        this._editingChannel = channel;
        this._render();
        const row = this._root.querySelector(`[data-dabcfg-row="${CSS.escape(channel)}"]`);
        const input = row && row.querySelector('[data-dabcfg-input]');
        if (input) { input.focus(); input.select(); }
    }

    async _saveEdit(channel) {
        const row = this._root.querySelector(`[data-dabcfg-row="${CSS.escape(channel)}"]`);
        const input = row && row.querySelector('[data-dabcfg-input]');
        const name = input ? input.value : '';
        try {
            const res = await fetch(`/api/dab/scan-results/${encodeURIComponent(channel)}/name`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ custom_name: name }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert('Error saving name: ' + (err.detail || `HTTP ${res.status}`));
                return;
            }
        } catch (e) {
            alert('Error saving name: ' + e.message);
            return;
        }
        this._editingChannel = null;
        await this._refresh();
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.DabConfigPanel = DabConfigPanel;
