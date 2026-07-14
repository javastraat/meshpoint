/**
 * Configuration → MeshCore card.
 *
 * Renders two cards: "USB capture sources" (one row per configured
 * companion, each with its own live radio/firmware readouts AND its own
 * editable name/advert controls -- mirrors SerialConfigCard's per-device
 * layout, since every companion has an independent connection and
 * identity) and "MeshCore Companion" (connection status plus the shared
 * channel-key table, since MeshCore channels are mesh-wide config synced
 * only through the primary/TX-bound companion, not per-device).
 */

class MeshcoreConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._focusedRow = null;
    }

    _MAX_COMPANIONS = 4;

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-mc-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">USB capture sources</h3>
                        <p class="cfg-card__hint">
                            One entry per MeshCore companion (Heltec V3/V4, T-Beam, etc.).
                            Up to ${this._MAX_COMPANIONS}. Requires a service restart after changes.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-mc-usb-enable>
                        <span class="cfg-field__label">Include meshcore_usb capture source</span>
                    </label>
                    <div class="cfg-companions" data-mc-companions></div>
                    <datalist id="mc-serial-ports-list"></datalist>
                    <div class="cfg-companions__add-row">
                        <button class="terminal-button" type="button" data-mc-add-companion>
                            + Add companion
                        </button>
                        <button class="terminal-button" type="button" data-mc-rescan-usb
                                title="Re-scan connected USB devices for the port picker below">
                            ↻ Rescan USB
                        </button>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-mc-usb-save>
                            Save USB sources
                        </button>
                    </div>
                    <p class="cfg-status" data-mc-usb-status aria-live="polite"></p>
                </article>
                <article class="cfg-card" data-mc-card>
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">MeshCore Companion</h3>
                        <p class="cfg-card__hint">
                            Channel keys for the USB companion. Keys are hex to match the
                            MeshCore native app. Channel save applies at runtime.
                        </p>
                    </header>
                    <div data-mc-body></div>
                    <p class="cfg-status" data-mc-status aria-live="polite"></p>
                </article>
            </div>
        `;
        this._body = this._root.querySelector('[data-mc-body]');
        this._statusEl = this._root.querySelector('[data-mc-status]');
        this._companionsEl = this._root.querySelector('[data-mc-companions]');

        this._root.querySelector('[data-mc-add-companion]')
            .addEventListener('click', () => this._addCompanionRow());
        this._root.querySelector('[data-mc-usb-save]')
            .addEventListener('click', () => this._saveCompanions());
        this._root.querySelector('[data-mc-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));
    }

    /** Manual re-scan for the port-picker datalist -- lets a user unplug
     * one device, plug in another, and immediately see it in the
     * dropdown without waiting for the next automatic dashboard poll or
     * reloading the page. */
    async _rescanUsb(button) {
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Scanning…';
        try {
            await this._refreshSerialPortsList();
        } finally {
            button.textContent = original;
            button.disabled = false;
        }
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
        this._refreshSerialPortsList();

        const cap = config.capture || {};
        const companions = Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : [];
        const sources = cap.sources || [];
        const mc = (config && config.meshcore) || {};
        // Per-companion live readouts (own connection/radio/device each) --
        // unlike mc.radio/mc.device below, which only ever reflect
        // company[0], the one companion wired for sending.
        this._liveCompanions = Array.isArray(mc.companions) ? mc.companions : [];

        const enableEl = this._root.querySelector('[data-mc-usb-enable]');
        if (enableEl) enableEl.checked = sources.includes('meshcore_usb');

        // Render companion rows from config
        this._companionsEl.innerHTML = '';
        const list = companions.length > 0 ? companions : [{ label: '', serial_port: '', baud_rate: 115200, auto_detect: true }];
        list.forEach((c) => this._addCompanionRow(c));
        this._syncAddBtn();

        if (!mc.connected) {
            this._renderOffline(config);
            return;
        }
        this._renderOnline(mc);
    }

    _liveCompanionFor(label) {
        const name = label ? `meshcore_usb_${label}` : 'meshcore_usb';
        return (this._liveCompanions || []).find((c) => c.name === name) || null;
    }

    /** Maps every currently-configured serial_port value (across BOTH
     * MeshCore companions AND Serial devices -- the same physical USB
     * pool, so a port pinned by one protocol is just as "in use" from
     * the other's perspective) to a human label, for the "already used
     * by ..." warning in the port picker below. */
    _buildPortUsageMap(config) {
        const usage = {};
        const cap = (config && config.capture) || {};
        (Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : []).forEach((c) => {
            if (c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
        return usage;
    }

    /** Populates the shared <datalist> so every "Pinned serial port" input
     * can suggest currently-connected USB devices -- refreshed on every
     * render() (each dashboard poll) and via the "Rescan USB" button, so
     * newly plugged devices show up without a full page reload. Any
     * option already claimed by a configured companion/device (matched
     * across all 3 possible name forms: raw device, by-id, by-path,
     * since older configs may still be pinned by the raw path even
     * though by-path is now recommended) gets an "already used by ..."
     * suffix -- still selectable (there's no way to disable one
     * <option> in a native datalist, nor would we want to: the row
     * showing its OWN currently-pinned port will also see this label,
     * which is accurate, not a bug), just informative. Best-effort:
     * silently no-ops if the enumeration endpoint is unavailable,
     * leaving the field as a plain free-text input (the existing
     * behavior). */
    async _refreshSerialPortsList() {
        const list = this._root.querySelector('#mc-serial-ports-list');
        if (!list) return;
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        const usage = this._portUsage || {};
        list.innerHTML = ports.map((p) => {
            const devName = (p.device || '').split('/').pop();
            const base = `${p.description || p.device}${devName ? ` (${devName})` : ''}`;
            const usedBy = [p.device, p.by_id, p.by_path].filter(Boolean)
                .map((alias) => usage[alias]).find(Boolean);
            const label = usedBy ? `${base} — already used by ${usedBy}` : base;
            return `<option value="${this._esc(p.stable_path)}" label="${this._esc(label)}"></option>`;
        }).join('');
    }

    _addCompanionRow(data = {}) {
        const idx = this._companionsEl.children.length;
        if (idx >= this._MAX_COMPANIONS) return;

        const label    = this._esc(data.label || '');
        const port     = this._esc(data.serial_port || '');
        const baud     = data.baud_rate != null ? data.baud_rate : 115200;
        const autodet  = data.auto_detect !== false;
        const live     = this._liveCompanionFor(data.label || '');

        const div = document.createElement('div');
        div.className = 'cfg-companion';
        div.dataset.companionIdx = idx;
        div.innerHTML = `
            <div class="cfg-companion__header">
                <span class="cfg-companion__num">Companion ${idx + 1}</span>
                <label class="cfg-companion__label-wrap">
                    <span class="cfg-field__label">Label</span>
                    <input class="cfg-field__input cfg-companion__label-input"
                           type="text" maxlength="16"
                           placeholder="e.g. 868 or 433"
                           value="${label}" data-companion-label>
                </label>
                <button class="cfg-companion__remove terminal-button terminal-button--danger"
                        type="button" title="Remove companion">✕</button>
            </div>
            <label class="cfg-field cfg-field--toggle">
                <input type="checkbox" data-companion-autodetect ${autodet ? 'checked' : ''}>
                <span class="cfg-field__label">Auto-detect serial port</span>
            </label>
            <label class="cfg-field">
                <span class="cfg-field__label">Pinned serial port</span>
                <input class="cfg-field__input" type="text"
                       placeholder="/dev/ttyACM0" value="${port}"
                       list="mc-serial-ports-list"
                       data-companion-port>
                <span class="cfg-field__hint">
                    Pick a connected device below, or type a path. Prefer the
                    /dev/serial/by-path/... entries over plain /dev/ttyUSBn --
                    those stay stable across reboots/replugs even when two
                    boards share an identical USB serial number.
                </span>
            </label>
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">Baud rate</span>
                <input class="cfg-field__input" type="number"
                       value="${baud}" data-companion-baud>
            </label>
            ${this._companionIdentityHtml(data, live)}
            ${this._companionReadoutsHtml(live)}
        `;

        div.querySelector('.cfg-companion__remove').addEventListener('click', () => {
            div.remove();
            this._reindexCompanions();
            this._syncAddBtn();
        });

        const firmwareCheck = div.querySelector('[data-companion-firmware-check]');
        if (firmwareCheck) {
            firmwareCheck.addEventListener('click', () => {
                this._checkCompanionFirmwareUpdate(div, live.device.firmware_version);
            });
        }

        const saveNameBtn = div.querySelector('[data-companion-name-save]');
        if (saveNameBtn) {
            saveNameBtn.addEventListener('click', () => {
                this._saveCompanionName(div, data.label || '');
            });
        }

        this._companionsEl.appendChild(div);
        this._syncAddBtn();
    }

    _companionReadoutsHtml(live) {
        if (!live || !live.connected) {
            return `<p class="cfg-companion__offline-hint">Not connected.</p>`;
        }
        const radio = live.radio || {};
        const device = live.device || {};
        return `
            <div class="cfg-mc-readouts">
                <div class="cfg-mc-readout" title="${this._esc(radio.public_key || '')}">
                    <span class="cfg-mc-readout__label">Node ID</span>
                    <span class="cfg-mc-readout__value">${this._fmtNodeId(radio.public_key)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Frequency</span>
                    <span class="cfg-mc-readout__value">${this._fmtFreq(radio.frequency_mhz)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Bandwidth</span>
                    <span class="cfg-mc-readout__value">${this._fmtBw(radio.bandwidth_khz)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">SF</span>
                    <span class="cfg-mc-readout__value">${this._fmtSf(radio.spreading_factor)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">TX Power</span>
                    <span class="cfg-mc-readout__value">${this._fmtTxPower(radio.tx_power)}</span>
                </div>
                <div class="cfg-mc-readout" title="${this._esc(this._firmwareTitle(device))}">
                    <span class="cfg-mc-readout__label">Firmware</span>
                    <span class="cfg-mc-readout__value">${this._fmtFirmware(device)}</span>
                    ${device.firmware_version ? `
                        <button class="cfg-mc-readout__check" type="button" data-companion-firmware-check>
                            Check for updates
                        </button>
                        <span class="cfg-mc-readout__update-status" data-companion-firmware-status></span>
                    ` : ''}
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Hardware</span>
                    <span class="cfg-mc-readout__value">${this._esc(device.model || '--')}</span>
                </div>
            </div>
        `;
    }

    async _checkCompanionFirmwareUpdate(companionDiv, currentVersion) {
        const button = companionDiv.querySelector('[data-companion-firmware-check]');
        const status = companionDiv.querySelector('[data-companion-firmware-status]');
        if (!button || !status || !currentVersion) return;
        button.disabled = true;
        status.dataset.kind = '';
        status.textContent = 'Checking…';
        try {
            const result = await this._api.get(
                `/api/config/meshcore/firmware-check?current_version=${encodeURIComponent(currentVersion)}`,
            );
            if (!result) {
                status.dataset.kind = 'error';
                status.textContent = 'Check failed';
            } else if (result.error) {
                status.dataset.kind = 'error';
                status.textContent = result.error;
            } else if (result.update_available) {
                status.dataset.kind = 'warn';
                // release_url always comes from GitHub's own API response, not
                // user input -- but only allow http(s) schemes defensively,
                // since HTML-escaping the text doesn't stop a javascript: URI
                // from executing when the link is clicked.
                const isSafeUrl = typeof result.release_url === 'string'
                    && /^https?:\/\//i.test(result.release_url);
                const link = isSafeUrl
                    ? ` — <a href="${this._esc(result.release_url)}" target="_blank" rel="noopener">release notes</a>`
                    : '';
                status.innerHTML = `Update available: ${this._esc(result.latest_version || '?')}${link}`;
            } else {
                status.dataset.kind = 'ok';
                status.textContent = 'Up to date';
            }
        } finally {
            button.disabled = false;
        }
    }

    _reindexCompanions() {
        this._companionsEl.querySelectorAll('.cfg-companion').forEach((el, i) => {
            el.dataset.companionIdx = i;
            const num = el.querySelector('.cfg-companion__num');
            if (num) num.textContent = `Companion ${i + 1}`;
        });
    }

    _syncAddBtn() {
        const btn = this._root.querySelector('[data-mc-add-companion]');
        if (!btn) return;
        const count = this._companionsEl.children.length;
        btn.disabled = count >= this._MAX_COMPANIONS;
        btn.title = count >= this._MAX_COMPANIONS
            ? `Maximum ${this._MAX_COMPANIONS} companions`
            : '';
    }

    async _saveCompanions() {
        const status = this._root.querySelector('[data-mc-usb-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const companions = [];
        this._companionsEl.querySelectorAll('.cfg-companion').forEach((div) => {
            companions.push({
                label:       (div.querySelector('[data-companion-label]')?.value || '').trim(),
                serial_port: (div.querySelector('[data-companion-port]')?.value || '').trim() || null,
                baud_rate:   Number(div.querySelector('[data-companion-baud]')?.value) || 115200,
                auto_detect: div.querySelector('[data-companion-autodetect]')?.checked ?? true,
            });
        });

        const result = await this._api.put('/api/config/capture/meshcore-companions', {
            enable_source: this._root.querySelector('[data-mc-usb-enable]').checked,
            companions,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            this._api.signalRestart('MeshCore USB companions updated.');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _renderOffline(config) {
        const tx = (config && config.transmit) || {};
        const mc = (config && config.meshcore) || {};
        const transmitOff = !tx.enabled || mc.status_note === 'transmit_disabled';
        const transmitCallout = transmitOff ? `
            <p class="cfg-callout">
                <strong>Native TX is disabled.</strong>
                Enable it under
                <a class="cfg-inline-link" href="#/configuration/transmit">Configuration → Transmit</a>,
                then restart the service. Until then this card cannot query the
                USB companion, even if USB capture is already receiving packets.
            </p>
        ` : '';
        this._body.innerHTML = `
            ${transmitCallout}
            <div class="cfg-empty">
                <div class="cfg-empty__title">No companion connected</div>
                <p class="cfg-empty__body">
                    Enable the USB capture source above, plug in a companion
                    (Heltec V3/V4, T-Beam, ...), then restart the service.
                </p>
            </div>
        `;
        this._setStatus('', '');
    }

    _renderOnline(mc) {
        const name = this._esc(mc.companion_name || 'Connected');
        const publicKeyHex = this._esc(mc.public_key_hex || '8b3387e9c5cdea6ac9e5edbaa115cd72');
        const privateSet = new Set(mc.private_channels || []);
        const channelRows = this._buildChannelRows(mc.channel_keys || [], privateSet);

        this._body.innerHTML = `
            <div class="cfg-mc-status">
                <span class="cfg-mc-status__lamp" aria-hidden="true"></span>
                <span class="cfg-mc-status__name">${name}</span>
            </div>
            <div class="cfg-mc-channels">
                <table class="ch-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Name</th>
                            <th>Key (Hex)</th>
                            <th title="Hide from viewer role">Admin only</th>
                        </tr>
                    </thead>
                    <tbody data-mc-channels-body>
                        <tr class="ch-table__row ch-table__row--public" data-index="0">
                            <td class="ch-table__idx">0</td>
                            <td>Public</td>
                            <td class="ch-table__psk-cell">
                                <input class="ch-table__name-input" data-field="public_key_hex"
                                       type="password" value="${publicKeyHex}"
                                       placeholder="32-char hex default public key" />
                                <button class="ch-table__reveal" type="button"
                                        title="Show/hide key">&#128065;</button>
                            </td>
                            <td></td>
                        </tr>
                        ${channelRows}
                    </tbody>
                </table>
            </div>
            <div class="cfg-card__actions cfg-mc-toolbar">
                <button class="terminal-button terminal-button--danger"
                        type="button" data-mc-delete style="display:none">
                    Delete Channel
                </button>
                <button class="terminal-button" type="button" data-mc-add>
                    + Add Channel
                </button>
                <button class="terminal-button terminal-button--primary"
                        type="button" data-mc-save>
                    Save Channels
                </button>
                <button class="terminal-button" type="button" data-mc-advert>
                    Send Advert
                </button>
                <button class="terminal-button" type="button" data-mc-refresh>
                    Refresh
                </button>
            </div>
        `;
        this._focusedRow = null;
        this._wire();
        this._reindexChannelRows();
        this._updateAddBtn();
    }

    _buildChannelRows(channelKeys, privateSet = new Set()) {
        return channelKeys.map((ch, i) => {
            const idx = i + 1;
            const name = this._esc(ch.name || '');
            const keyHex = this._esc(ch.key_hex || '');
            const isPrivate = privateSet.has(ch.name || '');
            return `
                <tr class="ch-table__row" data-index="${idx}">
                    <td class="ch-table__idx">
                        <span class="ch-table__idx-num">${idx}</span>
                        <span class="ch-table__reorder">
                            <button type="button" class="ch-table__move" data-move="up" title="Move up">&#9650;</button>
                            <button type="button" class="ch-table__move" data-move="down" title="Move down">&#9660;</button>
                        </span>
                    </td>
                    <td>
                        <input class="ch-table__name-input" data-field="name"
                               value="${name}" placeholder="Channel name" />
                    </td>
                    <td class="ch-table__psk-cell">
                        <input class="ch-table__name-input" data-field="key_hex"
                               type="password" value="${keyHex}"
                               placeholder="32-char hex (empty = hashtag)" />
                        <button class="ch-table__reveal" type="button"
                                title="Show/hide key">&#128065;</button>
                    </td>
                    <td class="ch-table__admin-cell">
                        <input type="checkbox" data-field="admin_only" title="Hide from viewer role" ${isPrivate ? 'checked' : ''} />
                    </td>
                </tr>
            `;
        }).join('');
    }

    _wire() {
        this._wireChannelHandlers(this._body);

        const addBtn = this._body.querySelector('[data-mc-add]');
        if (addBtn) addBtn.addEventListener('click', () => this._addEmptyRow());

        const saveBtn = this._body.querySelector('[data-mc-save]');
        if (saveBtn) saveBtn.addEventListener('click', () => this._saveChannels());

        const delBtn = this._body.querySelector('[data-mc-delete]');
        if (delBtn) {
            delBtn.addEventListener('mousedown', (e) => e.preventDefault());
            delBtn.addEventListener('click', () => this._deleteRow());
        }

        const advert = this._body.querySelector('[data-mc-advert]');
        if (advert) advert.addEventListener('click', () => this._sendAdvert(advert));

        const refresh = this._body.querySelector('[data-mc-refresh]');
        if (refresh) refresh.addEventListener('click', () => this._api.refresh());
    }

    _wireChannelHandlers(scope) {
        scope.querySelectorAll('.ch-table__reveal').forEach((btn) => {
            btn.addEventListener('click', () => {
                const input = btn.closest('tr').querySelector('[data-field="key_hex"], [data-field="public_key_hex"]');
                if (input) input.type = input.type === 'password' ? 'text' : 'password';
            });
        });

        // Reorders are DOM-only until Save is pressed -- _saveChannels()
        // submits rows in document order, and the server preserves that
        // as channel_keys dict insertion order (round-trips through
        // save_section_to_yaml's sort_keys=False), so this is the whole
        // mechanism: no separate "order" field or backend change needed.
        scope.querySelectorAll('.ch-table__move').forEach((btn) => {
            btn.addEventListener('click', () => {
                const tr = btn.closest('tr');
                if (!tr) return;
                if (btn.dataset.move === 'up') {
                    const prev = tr.previousElementSibling;
                    if (prev && !prev.classList.contains('ch-table__row--public')) {
                        tr.parentElement.insertBefore(tr, prev);
                    }
                } else {
                    const next = tr.nextElementSibling;
                    if (next) tr.parentElement.insertBefore(next, tr);
                }
                this._reindexChannelRows();
            });
        });

        scope.querySelectorAll('.ch-table__row:not(.ch-table__row--locked) input').forEach((input) => {
            input.addEventListener('focus', () => {
                this._focusedRow = input.closest('tr');
                this._syncDeleteBtn();
            });
            input.addEventListener('blur', () => {
                setTimeout(() => {
                    const tbody = this._body.querySelector('[data-mc-channels-body]');
                    if (tbody && !tbody.querySelector('input:focus')) {
                        this._focusedRow = null;
                        this._syncDeleteBtn();
                    }
                }, 0);
            });
        });
    }

    _syncDeleteBtn() {
        const btn = this._body.querySelector('[data-mc-delete]');
        if (btn) btn.style.display = this._focusedRow ? '' : 'none';
    }

    /** Renumber rows after add/delete/reorder and disable move buttons
     * at the top/bottom edge (Public row 0 is never a valid target). */
    _reindexChannelRows() {
        const tbody = this._body.querySelector('[data-mc-channels-body]');
        if (!tbody) return;
        const rows = Array.from(tbody.querySelectorAll('tr:not(.ch-table__row--public)'));
        rows.forEach((row, i) => {
            const idx = i + 1;
            row.dataset.index = idx;
            const idxLabel = row.querySelector('.ch-table__idx-num');
            if (idxLabel) idxLabel.textContent = idx;
            const upBtn = row.querySelector('[data-move="up"]');
            const downBtn = row.querySelector('[data-move="down"]');
            if (upBtn) upBtn.disabled = i === 0;
            if (downBtn) downBtn.disabled = i === rows.length - 1;
        });
    }

    // Device has 41 slots: 0 = Public (locked row), 1–40 = user channels.
    _MC_MAX_USER_CHANNELS = 40;

    _updateAddBtn() {
        const btn = this._body.querySelector('[data-mc-add]');
        if (!btn) return;
        const tbody = this._body.querySelector('[data-mc-channels-body]');
        const count = tbody
            ? tbody.querySelectorAll('tr:not(.ch-table__row--locked)').length
            : 0;
        const atLimit = count >= this._MC_MAX_USER_CHANNELS;
        btn.disabled = atLimit;
        btn.title = atLimit
            ? `Only ${this._MC_MAX_USER_CHANNELS} user channels (slots 1–40)`
            : '';
    }

    _addEmptyRow() {
        const tbody = this._body.querySelector('[data-mc-channels-body]');
        if (!tbody) return;
        const idx = tbody.querySelectorAll('tr').length;
        const tr = document.createElement('tr');
        tr.className = 'ch-table__row';
        tr.dataset.index = idx;
        tr.innerHTML = `
            <td class="ch-table__idx">
                <span class="ch-table__idx-num">${idx}</span>
                <span class="ch-table__reorder">
                    <button type="button" class="ch-table__move" data-move="up" title="Move up">&#9650;</button>
                    <button type="button" class="ch-table__move" data-move="down" title="Move down">&#9660;</button>
                </span>
            </td>
            <td>
                <input class="ch-table__name-input" data-field="name"
                       value="" placeholder="Channel name" />
            </td>
            <td class="ch-table__psk-cell">
                <input class="ch-table__name-input" data-field="key_hex"
                       type="password" value="" placeholder="32-char hex (empty = hashtag)" />
                <button class="ch-table__reveal" type="button"
                        title="Show/hide key">&#128065;</button>
            </td>
            <td class="ch-table__admin-cell">
                <input type="checkbox" data-field="admin_only" title="Hide from viewer role" />
            </td>
        `;
        this._wireChannelHandlers(tr);
        tbody.appendChild(tr);
        this._reindexChannelRows();
        this._updateAddBtn();
    }

    async _deleteRow() {
        if (!this._focusedRow) return;
        const ok = await window.confirmModal({
            label: 'Delete channel',
            description: 'Remove this channel from the list? '
                + 'Nothing is deleted until you press Save Channels.',
        });
        if (!ok || !this._focusedRow) return;
        this._focusedRow.remove();
        this._focusedRow = null;
        this._syncDeleteBtn();
        this._reindexChannelRows();
        this._updateAddBtn();
    }

    async _saveChannels() {
        const publicKeyHex = (this._body.querySelector('[data-field="public_key_hex"]')?.value || '').trim();

        const rows = this._body.querySelectorAll(
            '[data-mc-channels-body] tr:not(.ch-table__row--public)',
        );
        const channels = [];
        const private_channels = [];
        rows.forEach((row) => {
            const name = (row.querySelector('[data-field="name"]')?.value || '').trim();
            const keyHex = (row.querySelector('[data-field="key_hex"]')?.value || '').trim();
            if (name || keyHex) {
                channels.push({ name, key_hex: keyHex });
                if (row.querySelector('[data-field="admin_only"]')?.checked && name) {
                    private_channels.push(name);
                }
            }
        });

        this._setStatus('pending', 'Saving…');
        const res = await this._api.put('/api/config/meshcore/channels', { channels, public_key_hex: publicKeyHex, private_channels });
        if (res) {
            this._setStatus('success', 'Channels saved.');
            this._api.toast('MeshCore channels saved');
        } else {
            this._setStatus('error', 'Save failed.');
        }
    }

    async _sendAdvert(button) {
        button.disabled = true;
        try {
            const result = await this._api.post('/api/messages/advert', {});
            if (result && result.success) {
                this._api.toast('Advert sent');
            } else if (result) {
                this._api.toast(
                    'Advert failed' + (result.error ? `: ${result.error}` : ''),
                );
            }
        } finally {
            button.disabled = false;
        }
    }

    _companionIdentityHtml(data, live) {
        const nameValue = this._esc(
            data.companion_name || (live && live.radio && live.radio.name) || '',
        );
        return `
            <div class="cfg-mc-identity" data-companion-identity>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">Companion name</span>
                    <input class="cfg-field__input" type="text"
                           data-companion-name maxlength="32"
                           value="${nameValue}"
                           placeholder="My Meshpoint">
                </label>
                <label class="cfg-field cfg-field--toggle">
                    <input type="checkbox" data-companion-name-advert checked>
                    <span class="cfg-field__label">
                        Send advert after save
                    </span>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-companion-name-save>
                        Save Name
                    </button>
                </div>
                <p class="cfg-status" data-companion-name-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveCompanionName(companionDiv, label) {
        const input = companionDiv.querySelector('[data-companion-name]');
        const advertEl = companionDiv.querySelector('[data-companion-name-advert]');
        const status = companionDiv.querySelector('[data-companion-name-status]');
        const button = companionDiv.querySelector('[data-companion-name-save]');
        if (!input || !status) return;

        const value = (input.value || '').trim();
        if (!value) {
            status.dataset.kind = 'error';
            status.textContent = 'Name must not be empty.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Renaming companion…';

        const result = await this._api.put(
            '/api/config/meshcore/companion-name',
            { name: value, label },
        );

        if (!result) {
            // _api.put toasts the server detail on non-2xx; we just
            // clear the inline status so the toast is the user's
            // canonical signal.
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
            button.disabled = false;
            return;
        }

        status.dataset.kind = 'success';
        status.textContent = `Renamed to "${result.name || value}".`;
        this._api.toast('Companion renamed');

        // Default-on per the v0.7.5 spec: identity on the mesh is the
        // advert packet, so a rename without a follow-up advert leaves
        // every neighbor seeing the old name until the next periodic
        // beacon (which on MeshCore is operator-driven, not automatic).
        // Targets THIS companion specifically (not the general
        // /api/messages/advert, which always hits the primary one).
        if (advertEl && advertEl.checked) {
            try {
                const advertRes = await this._api.post(
                    '/api/config/meshcore/companion-advert',
                    { label },
                );
                if (advertRes && advertRes.success) {
                    this._api.toast('Advert sent');
                } else if (advertRes) {
                    this._api.toast(
                        'Advert failed' +
                            (advertRes.error ? `: ${advertRes.error}` : ''),
                    );
                }
            } catch (_e) {
                // Rename already stuck on flash; advert failure is a
                // soft error. Rely on the toast to surface it.
            }
        }

        await this._api.refresh();
        button.disabled = false;
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }

    _fmtFreq(v)    { return v ? `${v} MHz` : '--'; }
    _fmtBw(v)      { return v ? `${v} kHz` : '--'; }
    _fmtSf(v)      { return v ? `SF${v}` : '--'; }
    _fmtTxPower(v) { return v != null ? `${v} dBm` : '--'; }
    // MeshCore's own node identity is a 64-char public key -- far too
    // long for a tile, so show a short prefix (same visual weight as
    // Meshtastic's 8-hex-char `!09d406f4` Node ID), full key on hover.
    _fmtNodeId(v)  { return v ? `#${v.slice(0, 8)}` : '--'; }

    _fmtFirmware(device) {
        if (!device) return '--';
        if (device.firmware_version) return device.firmware_version;
        // Older companion firmware only reports the bare protocol version,
        // no human-readable version string (see get_device_info()'s docstring).
        if (device.protocol_version) return `protocol v${device.protocol_version}`;
        return '--';
    }

    _firmwareTitle(device) {
        // Model now has its own visible Hardware row below, so the
        // tooltip here only needs build date.
        if (!device || !device.firmware_version || !device.build_date) return '';
        return `built ${device.build_date}`;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.MeshcoreConfigCard = MeshcoreConfigCard;
