/**
 * Configuration → Serial (Meshtastic USB) card.
 *
 * Edits the list of Meshtastic USB serial devices (T5 multi-stick
 * support) so adding a second stick (e.g. one on 433 MHz, one on 868
 * MHz) doesn't need hand-editing local.yaml. Each device row also gets
 * its own live readouts plus editable long/short name + "Send advert
 * after save" -- these sticks have no Bluetooth, so this is the only
 * way to rename them without a laptop and a USB cable running the
 * official Meshtastic app. Mirrors MeshcoreConfigCard's "USB capture
 * sources" card -- same shape, minus the auto-detect toggle:
 * SerialDeviceConfig has no such field, an empty serial port already
 * means "let meshtastic-python auto-detect".
 */

class SerialConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    _MAX_DEVICES = 4;

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-serial-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">USB capture sources</h3>
                        <p class="cfg-card__hint">
                            One entry per Meshtastic USB stick (Heltec V3, T-Beam, etc.).
                            Up to ${this._MAX_DEVICES}. Requires a service restart after changes.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-serial-enable>
                        <span class="cfg-field__label">Include serial capture source</span>
                    </label>
                    <div class="cfg-companions" data-serial-devices></div>
                    <datalist id="serial-ports-list"></datalist>
                    <div class="cfg-companions__add-row">
                        <button class="terminal-button" type="button" data-serial-add-device>
                            + Add device
                        </button>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-serial-save>
                            Save USB sources
                        </button>
                    </div>
                    <p class="cfg-status" data-serial-status aria-live="polite"></p>
                </article>
            </div>
        `;
        this._devicesEl = this._root.querySelector('[data-serial-devices]');

        this._root.querySelector('[data-serial-add-device]')
            .addEventListener('click', () => this._addDeviceRow());
        this._root.querySelector('[data-serial-save]')
            .addEventListener('click', () => this._saveDevices());
    }

    render(config) {
        this._refreshSerialPortsList();

        const cap = config.capture || {};
        const devices = Array.isArray(cap.serial) ? cap.serial : [];
        const sources = cap.sources || [];
        // Top-level config.serial is the LIVE status array (one entry per
        // running SerialCaptureSource, keyed by `name` -- e.g. "serial_433"
        // or bare "serial" with no label) -- a completely different thing
        // from cap.serial (config.capture.serial) above despite the
        // similar path, matching the API's own existing naming.
        this._liveStatuses = Array.isArray(config.serial) ? config.serial : [];

        const enableEl = this._root.querySelector('[data-serial-enable]');
        if (enableEl) enableEl.checked = sources.includes('serial');

        this._devicesEl.innerHTML = '';
        const list = devices.length > 0
            ? devices
            : [{ label: '', serial_port: '', serial_baud: 115200 }];
        list.forEach((d) => this._addDeviceRow(d));
        this._syncAddBtn();
    }

    _liveStatusFor(label) {
        const name = label ? `serial_${label}` : 'serial';
        return (this._liveStatuses || []).find((s) => s.name === name) || null;
    }

    /** Populates the shared <datalist> so every "Serial port" input can
     * suggest currently-connected USB devices -- refreshed on every
     * render() (each dashboard poll). Shared with MeshcoreConfigCard's
     * identical method/endpoint (GET /api/config/serial-ports lists ALL
     * USB-serial devices regardless of protocol, since both cards pin
     * from the same physical pool). Best-effort: silently no-ops if the
     * enumeration endpoint is unavailable, leaving the field as a plain
     * free-text input (the existing behavior). */
    async _refreshSerialPortsList() {
        const list = this._root.querySelector('#serial-ports-list');
        if (!list) return;
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        list.innerHTML = ports.map((p) => `
            <option value="${this._esc(p.stable_path)}" label="${this._esc(p.description || p.device)}"></option>
        `).join('');
    }

    _addDeviceRow(data = {}) {
        const idx = this._devicesEl.children.length;
        if (idx >= this._MAX_DEVICES) return;

        const label = this._esc(data.label || '');
        const port = this._esc(data.serial_port || '');
        const baud = data.serial_baud != null ? data.serial_baud : 115200;
        const live = this._liveStatusFor(data.label || '');

        const div = document.createElement('div');
        div.className = 'cfg-companion';
        div.dataset.deviceIdx = idx;
        div.innerHTML = `
            <div class="cfg-companion__header">
                <span class="cfg-companion__num">Device ${idx + 1}</span>
                <label class="cfg-companion__label-wrap">
                    <span class="cfg-field__label">Label</span>
                    <input class="cfg-field__input cfg-companion__label-input"
                           type="text" maxlength="16"
                           placeholder="e.g. 433 or 868"
                           value="${label}" data-device-label>
                </label>
                <button class="cfg-companion__remove terminal-button terminal-button--danger"
                        type="button" title="Remove device">✕</button>
            </div>
            <label class="cfg-field">
                <span class="cfg-field__label">Serial port</span>
                <input class="cfg-field__input" type="text"
                       placeholder="/dev/ttyUSB0 (blank = auto-detect)" value="${port}"
                       list="serial-ports-list"
                       data-device-port>
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
                       value="${baud}" data-device-baud>
            </label>
            ${this._identityHtml(data, live)}
            ${this._readoutsHtml(live)}
        `;

        div.querySelector('.cfg-companion__remove').addEventListener('click', () => {
            div.remove();
            this._reindexDevices();
            this._syncAddBtn();
        });

        const firmwareCheck = div.querySelector('[data-serial-firmware-check]');
        if (firmwareCheck) {
            firmwareCheck.addEventListener('click', () => {
                this._checkFirmwareUpdate(div, live.firmware_version);
            });
        }

        const saveNameBtn = div.querySelector('[data-device-name-save]');
        if (saveNameBtn) {
            saveNameBtn.addEventListener('click', () => {
                this._saveDeviceIdentity(div, data.label || '');
            });
        }

        this._devicesEl.appendChild(div);
        this._syncAddBtn();
    }

    _identityHtml(data, live) {
        const longValue = this._esc(data.long_name || (live && live.long_name) || '');
        const shortValue = this._esc(data.short_name || (live && live.short_name) || '');
        return `
            <div class="cfg-mc-identity" data-device-identity>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">Long name</span>
                    <input class="cfg-field__input" type="text"
                           data-device-long-name maxlength="36"
                           value="${longValue}"
                           placeholder="My Meshpoint 433">
                </label>
                <label class="cfg-field cfg-field--inline cfg-field--narrow">
                    <span class="cfg-field__label">Short name</span>
                    <input class="cfg-field__input" type="text"
                           data-device-short-name maxlength="4"
                           value="${shortValue}"
                           placeholder="M433">
                </label>
                <label class="cfg-field cfg-field--toggle">
                    <input type="checkbox" data-device-advert checked>
                    <span class="cfg-field__label">
                        Send advert after save
                    </span>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-device-name-save>
                        Save Name
                    </button>
                </div>
                <p class="cfg-status" data-device-name-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveDeviceIdentity(deviceDiv, label) {
        const longInput = deviceDiv.querySelector('[data-device-long-name]');
        const shortInput = deviceDiv.querySelector('[data-device-short-name]');
        const advertEl = deviceDiv.querySelector('[data-device-advert]');
        const status = deviceDiv.querySelector('[data-device-name-status]');
        const button = deviceDiv.querySelector('[data-device-name-save]');
        if (!longInput || !shortInput || !status) return;

        const longValue = (longInput.value || '').trim();
        const shortValue = (shortInput.value || '').trim();
        if (!longValue && !shortValue) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter a long name or short name.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Renaming device…';

        // null (not empty string) for a blank field -- matches the
        // backend's set_owner() "None means leave unchanged" semantics,
        // so renaming just the long name doesn't force retyping short.
        const result = await this._api.put('/api/config/serial/identity', {
            label,
            long_name: longValue || null,
            short_name: shortValue || null,
        });

        if (!result) {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
            button.disabled = false;
            return;
        }

        status.dataset.kind = 'success';
        status.textContent = 'Renamed.';
        this._api.toast('Device renamed');

        if (advertEl && advertEl.checked) {
            try {
                const advertRes = await this._api.post('/api/config/serial/advert', { label });
                if (advertRes && advertRes.success) {
                    this._api.toast('Advert sent');
                } else if (advertRes) {
                    this._api.toast(
                        'Advert failed' + (advertRes.error ? `: ${advertRes.error}` : ''),
                    );
                }
            } catch (_e) {
                // Rename already applied live; advert failure is a soft error.
            }
        }

        await this._api.refresh();
        button.disabled = false;
    }

    async _checkFirmwareUpdate(deviceDiv, currentVersion) {
        const button = deviceDiv.querySelector('[data-serial-firmware-check]');
        const status = deviceDiv.querySelector('[data-serial-firmware-status]');
        if (!button || !status || !currentVersion) return;
        button.disabled = true;
        status.dataset.kind = '';
        status.textContent = 'Checking…';
        try {
            const result = await this._api.get(
                `/api/config/serial/firmware-check?current_version=${encodeURIComponent(currentVersion)}`,
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

    _reindexDevices() {
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((el, i) => {
            el.dataset.deviceIdx = i;
            const num = el.querySelector('.cfg-companion__num');
            if (num) num.textContent = `Device ${i + 1}`;
        });
    }

    _syncAddBtn() {
        const btn = this._root.querySelector('[data-serial-add-device]');
        if (!btn) return;
        const count = this._devicesEl.children.length;
        btn.disabled = count >= this._MAX_DEVICES;
        btn.title = count >= this._MAX_DEVICES
            ? `Maximum ${this._MAX_DEVICES} devices`
            : '';
    }

    async _saveDevices() {
        const status = this._root.querySelector('[data-serial-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const devices = [];
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((div) => {
            devices.push({
                label: (div.querySelector('[data-device-label]')?.value || '').trim(),
                serial_port: (div.querySelector('[data-device-port]')?.value || '').trim() || null,
                serial_baud: Number(div.querySelector('[data-device-baud]')?.value) || 115200,
            });
        });

        const result = await this._api.put('/api/config/capture/serial-devices', {
            enable_source: this._root.querySelector('[data-serial-enable]').checked,
            devices,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            this._api.signalRestart('Serial USB devices updated.');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _readoutsHtml(live) {
        if (!live || !live.connected) {
            return `<p class="cfg-companion__offline-hint">Not connected.</p>`;
        }
        const nodeId = live.own_node_id_hex ? `!${live.own_node_id_hex}` : '--';
        const name = live.long_name || live.short_name || '--';
        const sf = live.spreading_factor ? `SF${live.spreading_factor}` : '--';
        const bw = live.bandwidth_khz ? `${live.bandwidth_khz} kHz` : '--';
        const freq = live.frequency_mhz ? `${live.frequency_mhz} MHz` : '--';
        const txPower = (live.tx_power || live.tx_power === 0) ? `${live.tx_power} dBm` : '--';
        return `
            <div class="cfg-mc-readouts">
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Node ID</span>
                    <span class="cfg-mc-readout__value">${this._esc(nodeId)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Name</span>
                    <span class="cfg-mc-readout__value">${this._esc(name)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Frequency</span>
                    <span class="cfg-mc-readout__value">${this._esc(freq)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Region</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.region || '--')}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">SF</span>
                    <span class="cfg-mc-readout__value">${sf}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Bandwidth</span>
                    <span class="cfg-mc-readout__value">${bw}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">TX Power</span>
                    <span class="cfg-mc-readout__value">${this._esc(txPower)}</span>
                </div>
                <div class="cfg-mc-readout" data-firmware-readout>
                    <span class="cfg-mc-readout__label">Firmware</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.firmware_version || '--')}</span>
                    ${live.firmware_version ? `
                        <button class="cfg-mc-readout__check" type="button" data-serial-firmware-check>
                            Check for updates
                        </button>
                        <span class="cfg-mc-readout__update-status" data-serial-firmware-status></span>
                    ` : ''}
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Hardware</span>
                    <span class="cfg-mc-readout__value">${this._esc(this._fmtHwModel(live.hw_model))}</span>
                </div>
            </div>
        `;
    }

    _fmtHwModel(v) {
        if (!v) return '--';
        return v.split('_')
            .map((w) => (w.length <= 2 ? w : w[0] + w.slice(1).toLowerCase()))
            .join(' ');
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.SerialConfigCard = SerialConfigCard;
