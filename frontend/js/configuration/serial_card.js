/**
 * Configuration → Serial (Meshtastic USB) card.
 *
 * Edits the list of Meshtastic USB serial devices (T5 multi-node
 * support) so adding a second node (e.g. one on 433 MHz, one on 868
 * MHz) doesn't need hand-editing local.yaml. Each device row also gets
 * its own live readouts plus editable long/short name + "Send advert
 * after save" -- these nodes have no Bluetooth, so this is the only
 * way to rename them without a laptop and a USB cable running the
 * official Meshtastic app. Mirrors MeshcoreConfigCard's "USB capture
 * sources" card -- same shape, minus the auto-detect toggle:
 * SerialDeviceConfig has no such field, an empty serial port already
 * means "let meshtastic-python auto-detect".
 *
 * The "Meshtastic firmware" flash card used to live here too; it moved
 * to the standalone Configuration → Firmware page
 * (frontend/js/configuration/meshtastic_firmware_card.js) for the same
 * reason MeshCore's did: flashing a spare board reads as its own action
 * instead of being buried inside this specific protocol's settings page.
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
                            One entry per Meshtastic USB node (Heltec V3, T-Beam, etc.).
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
                        <button class="terminal-button" type="button" data-serial-rescan-usb
                                title="Re-scan connected USB devices for the port picker below">
                            ↻ Rescan USB
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
        this._root.querySelector('[data-serial-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        // The top bar polls /api/config (every second while a USB node is
        // rebooting/reconnecting) and broadcasts it: keep each device's
        // status line current without re-rendering the form, so nothing
        // being typed is lost (upstream 459c4d7c).
        if (this._onConfigUpdated) {
            document.removeEventListener('meshpoint:configUpdated', this._onConfigUpdated);
        }
        this._onConfigUpdated = (ev) => this._syncLiveStatus(ev.detail || {});
        document.addEventListener('meshpoint:configUpdated', this._onConfigUpdated);
    }

    _syncLiveStatus(cfg) {
        if (!Array.isArray(cfg.serial) || !this._devicesEl) return;
        this._liveStatuses = cfg.serial;
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((div) => {
            const label = (div.querySelector('[data-device-label]')?.value || '').trim();
            const slot = div.querySelector('[data-serial-link-status]');
            if (slot) slot.outerHTML = this._readoutsHtml(this._liveStatusFor(label));
        });
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

    /** Maps every currently-configured serial_port value (across BOTH
     * Serial devices AND MeshCore companions -- the same physical USB
     * pool, so a port pinned by one protocol is just as "in use" from
     * the other's perspective) to a human label, for the "already used
     * by ..." warning in the port picker below. */
    _buildPortUsageMap(config) {
        const usage = {};
        const cap = (config && config.capture) || {};
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
        (Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : []).forEach((c) => {
            if (c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        (Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `POCSAG ${d.label}` : 'POCSAG';
        });
        return usage;
    }

    /** Populates the shared <datalist> so every "Serial port" input can
     * suggest currently-connected USB devices -- refreshed on every
     * render() (each dashboard poll) and via the "Rescan USB" button.
     * Shared with MeshcoreConfigCard's identical method/endpoint
     * (GET /api/config/serial-ports lists ALL USB-serial devices
     * regardless of protocol, since both cards pin from the same
     * physical pool). Any option already claimed by a configured
     * companion/device (matched across all 3 possible name forms: raw
     * device, by-id, by-path) gets an "already used by ..." suffix --
     * still selectable (no way to disable one <option> in a native
     * datalist, nor would we want to: the row showing its OWN
     * currently-pinned port will also see this label, which is
     * accurate, not a bug), just informative. Best-effort: silently
     * no-ops if the enumeration endpoint is unavailable, leaving the
     * field as a plain free-text input (the existing behavior). */
    async _refreshSerialPortsList() {
        const list = this._root.querySelector('#serial-ports-list');
        if (!list) return;
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        const usage = this._portUsage || {};
        list.innerHTML = ports.map((p) => `
            <option value="${this._esc(p.stable_path)}" label="${this._esc(this._portOptionLabel(p, usage))}"></option>
        `).join('');
        // Ports arrive asynchronously, after rows may have already been
        // built with no enumeration data yet -- refresh every row's
        // "resolved to ttyUSBn" hint now that it's available.
        this._devicesEl.querySelectorAll('[data-device-port]').forEach((input) => {
            this._updateResolvedPort(input);
        });
    }

    /** A pinned by-path/by-id value is long and not something a user can
     * eyeball as "which physical ttyUSBn is that" -- shows the
     * underlying /dev/ttyUSBn next to the field once it's resolvable
     * (matched against the enumerated ports' stable_path/by_id/by_path/
     * device, whichever form the pinned value happens to be in), and
     * clears it when the value doesn't currently resolve to anything
     * connected (nothing to show, not a stale/wrong hint). */
    _updateResolvedPort(input) {
        const resolvedEl = input.parentElement.querySelector('[data-device-port-resolved]');
        const warnEl = input.parentElement.querySelector('[data-device-port-warn]');
        const value = (input.value || '').trim();
        const match = this._matchEnumeratedPort(value);
        if (resolvedEl) {
            resolvedEl.textContent = (match && match.device && match.device !== value) ? `→ ${match.device}` : '';
        }
        if (warnEl) {
            if (match && match.port_class === 'gps_known') {
                warnEl.hidden = false;
                warnEl.textContent = match.held_hint
                    || 'This looks like a GPS receiver; gpsd may hold the port.';
            } else {
                warnEl.hidden = true;
                warnEl.textContent = '';
            }
        }
    }

    /** Native <datalist> popups truncate long labels with no CSS control
     * over wrapping/width -- the important "used by ..." warning was
     * getting cut off entirely when it came after a full USB descriptor
     * string like "Silicon Labs CP2102 USB to UART Bridge Controller".
     * Puts the short/critical bits first and drops the boilerplate
     * "Silicon Labs .../USB to UART Bridge Controller" wording that's
     * identical (and uninformative) across every CP210x device anyway. */
    _portOptionLabel(p, usage) {
        const devName = (p.device || '').split('/').pop();
        const chip = (p.description || '')
            .replace(/^Silicon Labs\s+/i, '')
            .replace(/\s+USB to UART Bridge Controller.*$/i, '')
            .trim() || p.description || p.device;
        const usedBy = [p.device, p.by_id, p.by_path].filter(Boolean)
            .map((alias) => usage[alias]).find(Boolean);
        const parts = [devName, chip];
        if (p.port_class === 'gps_known') parts.push('GPS');
        if (usedBy) parts.push(`used by ${usedBy}`);
        return parts.filter(Boolean).join(' — ');
    }

    /** Finds this pinned value's enumerated port entry, if any -- same
     * matching (stable_path/by_id/by_path/device, whichever form the
     * pinned value happens to be in) used by both _updateResolvedPort's
     * "resolves to ttyUSBn" hint and the GPS-port save confirmation, so
     * the two never disagree about which physical device a value means. */
    _matchEnumeratedPort(value) {
        if (!value) return null;
        return (this._enumeratedPorts || []).find((p) =>
            p.stable_path === value || p.by_id === value || p.by_path === value || p.device === value,
        ) || null;
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
                <span class="cfg-field__resolved" data-device-port-resolved></span>
                <span class="cfg-field__hint cfg-field__hint--warn" data-device-port-warn hidden></span>
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
            ${this._radioControlsHtml(live)}
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

        const saveRegionBtn = div.querySelector('[data-device-region-save]');
        if (saveRegionBtn) {
            saveRegionBtn.addEventListener('click', () => {
                this._saveDeviceRegion(div, data.label || '');
            });
        }

        const savePresetBtn = div.querySelector('[data-device-preset-save]');
        if (savePresetBtn) {
            savePresetBtn.addEventListener('click', () => {
                this._saveDeviceModemPreset(div, data.label || '');
            });
        }

        const saveIntervalsBtn = div.querySelector('[data-device-intervals-save]');
        if (saveIntervalsBtn) {
            saveIntervalsBtn.addEventListener('click', () => {
                this._saveDeviceBroadcastIntervals(div, data.label || '');
            });
        }

        const saveBtBtn = div.querySelector('[data-device-bt-save]');
        if (saveBtBtn) {
            saveBtBtn.addEventListener('click', () => {
                this._saveDeviceBluetooth(div, data.label || '');
            });
        }

        const btEnabledEl = div.querySelector('[data-device-bt-enabled]');
        const btModeWrap = div.querySelector('[data-device-bt-mode-wrap]');
        const btModeEl = div.querySelector('[data-device-bt-mode]');
        const btPinWrap = div.querySelector('[data-device-bt-pin-wrap]');
        const syncBtVisibility = () => {
            if (btModeWrap) btModeWrap.hidden = !btEnabledEl?.checked;
            if (btPinWrap) {
                btPinWrap.hidden = !(btEnabledEl?.checked && btModeEl?.value === 'FIXED_PIN');
            }
        };
        if (btEnabledEl) btEnabledEl.addEventListener('change', syncBtVisibility);
        if (btModeEl) btModeEl.addEventListener('change', syncBtVisibility);

        this._wireRadioControls(div, live);

        const portInput = div.querySelector('[data-device-port]');
        if (portInput) {
            portInput.addEventListener('input', () => this._updateResolvedPort(portInput));
            this._updateResolvedPort(portInput);
        }

        this._devicesEl.appendChild(div);
        this._syncAddBtn();
    }

    /** Every Config.LoRaConfig.RegionCode value except UNSET (0) --
     * that one's Meshtastic's own factory-default "not configured yet"
     * state, not something you'd deliberately pick from this dropdown.
     * Straight from meshtastic/protobufs' config.proto, not a curated
     * subset like the Meshtastic-firmware-flash board list -- this is a
     * small, genuinely complete enum, not a sprawling hardware catalog. */
    static _REGION_CODES = [
        'US', 'EU_433', 'EU_868', 'CN', 'JP', 'ANZ', 'KR', 'TW', 'RU', 'IN',
        'NZ_865', 'TH', 'LORA_24', 'UA_433', 'MY_433', 'MY_919', 'SG_923',
        'PH_433', 'PH_868', 'PH_915', 'ANZ_433', 'KZ_433', 'KZ_863', 'NP_865',
        'BR_902', 'ITU1_2M', 'ITU2_2M', 'EU_866', 'EU_874', 'EU_917', 'EU_N_868',
        'ITU3_2M', 'ITU1_70CM', 'ITU2_70CM', 'ITU3_70CM', 'ITU2_125CM',
    ];

    /** Named ModemPreset values this control exposes -- matches the
     * same preset list Configuration -> Radio's own concentrator page
     * shows (LongFast/LongTurbo/.../ShortTurbo), not the full modern
     * Meshtastic enum (which also has Lite/Narrow/Tiny/MediumTurbo
     * variants not offered there either). "Custom" is deliberately not
     * included -- that's a fully custom spread-factor/bandwidth/coding-
     * rate config, not a named preset, and isn't exposed from here. */
    static _MODEM_PRESETS = [
        { value: 'LONG_FAST', label: 'LongFast' },
        { value: 'LONG_TURBO', label: 'LongTurbo' },
        { value: 'LONG_MODERATE', label: 'LongModerate' },
        { value: 'LONG_SLOW', label: 'LongSlow' },
        { value: 'VERY_LONG_SLOW', label: 'VeryLongSlow' },
        { value: 'MEDIUM_FAST', label: 'MediumFast' },
        { value: 'MEDIUM_SLOW', label: 'MediumSlow' },
        { value: 'SHORT_FAST', label: 'ShortFast' },
        { value: 'SHORT_SLOW', label: 'ShortSlow' },
        { value: 'SHORT_TURBO', label: 'ShortTurbo' },
    ];

    /** Same preset-minutes list as NodeInfoConfigCard/TelemetryBroadcastCard
     * (Configuration -> Radio's own broadcast-interval cards) -- reused
     * verbatim so a device row's chip-row looks and behaves identically
     * to those, not a different-looking control for the same idea. */
    static _INTERVAL_PRESETS = [
        { minutes: 0, label: 'Off', off: true },
        { minutes: 5, label: '5m' },
        { minutes: 30, label: '30m' },
        { minutes: 60, label: '1h' },
        { minutes: 180, label: '3h' },
        { minutes: 360, label: '6h' },
        { minutes: 720, label: '12h' },
        { minutes: 1440, label: '24h' },
    ];

    /** This node's radio/security config -- LoRa region, modem preset
     * (chip row), NodeInfo/telemetry broadcast intervals (chip row +
     * custom-minutes fallback, exactly the same pattern Configuration ->
     * Radio's own NodeInfoConfigCard/TelemetryBroadcastCard use), and
     * Bluetooth. Deliberately rendered as PLAIN .cfg-field elements with
     * matching Configuration -> Radio's own card structure EXACTLY
     * (`.cfg-card` > `.cfg-card__head` with title+hint > `.cfg-form`) --
     * grouped into two sub-cards, "Modem settings" (region + preset,
     * mirroring Radio's own Region+Modem-preset fields) and "Other
     * settings" (broadcast intervals + Bluetooth), sitting alongside the
     * pre-existing Name box so a device row reads as three peer cards:
     * Name, Modem settings, Other settings. Nesting `.cfg-card` inside
     * `.cfg-companion` is deliberate here (unlike the earlier all-flat
     * draft) -- these are genuinely distinct settings groups, same as
     * Radio/NodeInfo/Telemetry are separate top-level cards elsewhere,
     * just one level deeper since they belong to one specific device.
     * Always shown when connected, so this also serves as a way to
     * change any of these later. None of these persist to local.yaml --
     * all live durably in the device's own NVS, and re-applying them to
     * a swapped-in blank replacement is a much rarer need than
     * re-applying the name (which does persist, see _identityHtml). */
    _radioControlsHtml(live) {
        if (!live || !live.connected) return '';
        const region = live.region && live.region !== 'UNSET' ? live.region : '';
        const regionOptions = SerialConfigCard._REGION_CODES.map((r) => (
            `<option value="${r}" ${r === region ? 'selected' : ''}>${r.replace(/_/g, ' ')}</option>`
        )).join('');

        const btEnabled = live.bluetooth_enabled !== false; // default checked if unknown
        const btMode = live.bluetooth_mode || 'RANDOM_PIN';
        const btModeOptions = [
            ['RANDOM_PIN', 'Random PIN (shown on device)'],
            ['FIXED_PIN', 'Fixed PIN (set your own)'],
            ['NO_PIN', 'No PIN'],
        ].map(([value, label]) => (
            `<option value="${value}" ${value === btMode ? 'selected' : ''}>${label}</option>`
        )).join('');

        return `
            <div class="cfg-card">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">Modem settings</h3>
                    <p class="cfg-card__hint">
                        Region and modem preset for this node, set over its live
                        serial connection.
                    </p>
                </header>
                <div class="cfg-form">
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Region</span>
                        <select class="cfg-field__input" data-device-region-input>
                            <option value="" disabled ${region ? '' : 'selected'}>-- select --</option>
                            ${regionOptions}
                        </select>
                    </label>
                    ${live.region === 'UNSET' ? `
                        <p class="cfg-field__hint">
                            Region is UNSET -- this node will not transmit at all until
                            a region is set (Meshtastic's factory default on a fresh flash).
                        </p>
                    ` : ''}
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-device-region-save>
                            Set Region
                        </button>
                    </div>
                    <p class="cfg-status" data-device-region-status aria-live="polite"></p>

                    <div class="cfg-field">
                        <span class="cfg-field__label">Modem preset</span>
                        <div class="cfg-chip-row" data-device-preset-chips></div>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-device-preset-save>
                            Set Preset
                        </button>
                    </div>
                    <p class="cfg-status" data-device-preset-status aria-live="polite"></p>
                </div>
            </div>

            <div class="cfg-card">
                <header class="cfg-card__head">
                    <h3 class="cfg-card__title">Other settings</h3>
                    <p class="cfg-card__hint">
                        This node's own NodeInfo/telemetry broadcast timing and
                        Bluetooth -- not the same as Meshpoint's own concentrator
                        broadcast-interval cards on Configuration &rarr; Radio.
                    </p>
                </header>
                <div class="cfg-form">
                    <div class="cfg-field">
                        <span class="cfg-field__label">NodeInfo broadcast interval</span>
                        <div class="cfg-chip-row" data-device-ni-chips></div>
                    </div>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Custom (minutes)</span>
                        <input class="cfg-field__input" type="number" min="0" max="1440"
                               data-device-ni-input>
                    </label>

                    <div class="cfg-field">
                        <span class="cfg-field__label">Telemetry broadcast interval</span>
                        <div class="cfg-chip-row" data-device-tel-chips></div>
                    </div>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Custom (minutes)</span>
                        <input class="cfg-field__input" type="number" min="0" max="1440"
                               data-device-tel-input>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-device-intervals-save>
                            Set Intervals
                        </button>
                    </div>
                    <p class="cfg-status" data-device-intervals-status aria-live="polite"></p>

                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-device-bt-enabled ${btEnabled ? 'checked' : ''}>
                        <span class="cfg-field__label">Bluetooth enabled</span>
                    </label>
                    <label class="cfg-field cfg-field--narrow"
                           data-device-bt-mode-wrap ${btEnabled ? '' : 'hidden'}>
                        <span class="cfg-field__label">Pairing mode</span>
                        <select class="cfg-field__input" data-device-bt-mode>
                            ${btModeOptions}
                        </select>
                    </label>
                    <label class="cfg-field cfg-field--narrow"
                           data-device-bt-pin-wrap ${(btEnabled && btMode === 'FIXED_PIN') ? '' : 'hidden'}>
                        <span class="cfg-field__label">Fixed PIN</span>
                        <input class="cfg-field__input" type="number" min="0" max="999999"
                               placeholder="e.g. 123456" data-device-bt-pin>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-device-bt-save>
                            Set Bluetooth
                        </button>
                    </div>
                    <p class="cfg-status" data-device-bt-status aria-live="polite"></p>
                </div>
            </div>
        `;
    }

    /** Wires up the modem-preset and both interval chip-rows for one
     * device row -- called once per row from _addDeviceRow, mirroring
     * NodeInfoConfigCard's own _renderChips/_setActiveChip pattern
     * (click a chip -> highlight it + populate the paired custom-minutes
     * input; typing in the custom input directly highlights a matching
     * chip if any, clears selection otherwise). */
    _wireRadioControls(div, live) {
        const presetChips = div.querySelector('[data-device-preset-chips]');
        if (presetChips) {
            presetChips.innerHTML = SerialConfigCard._MODEM_PRESETS.map((p) => (
                `<button type="button" class="cfg-chip" data-preset="${p.value}">${p.label}</button>`
            )).join('');
            const current = live?.modem_preset;
            presetChips.querySelectorAll('[data-preset]').forEach((chip) => {
                chip.classList.toggle('cfg-chip--selected', chip.dataset.preset === current);
                chip.addEventListener('click', () => {
                    presetChips.querySelectorAll('[data-preset]').forEach((c) => (
                        c.classList.toggle('cfg-chip--selected', c === chip)
                    ));
                });
            });
        }

        this._wireIntervalChips(
            div, '[data-device-ni-chips]', '[data-device-ni-input]',
            live?.node_info_broadcast_secs,
        );
        this._wireIntervalChips(
            div, '[data-device-tel-chips]', '[data-device-tel-input]',
            live?.telemetry_device_update_interval,
        );
    }

    _wireIntervalChips(div, chipsSelector, inputSelector, currentSecs) {
        const chipsEl = div.querySelector(chipsSelector);
        const inputEl = div.querySelector(inputSelector);
        if (!chipsEl || !inputEl) return;

        chipsEl.innerHTML = SerialConfigCard._INTERVAL_PRESETS.map((p) => {
            const offCls = p.off ? ' cfg-chip--off' : '';
            return `<button type="button" class="cfg-chip${offCls}"
                    data-minutes="${p.minutes}">${p.label}</button>`;
        }).join('');

        const currentMinutes = currentSecs != null ? Math.round(currentSecs / 60) : null;
        inputEl.value = currentMinutes != null ? String(currentMinutes) : '';

        const setActive = (minutes) => {
            chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
                chip.classList.toggle(
                    'cfg-chip--selected', parseInt(chip.dataset.minutes, 10) === minutes,
                );
            });
        };
        setActive(currentMinutes);

        chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
            chip.addEventListener('click', () => {
                const minutes = parseInt(chip.dataset.minutes, 10);
                inputEl.value = String(minutes);
                setActive(minutes);
            });
        });
        inputEl.addEventListener('input', () => {
            const minutes = parseInt(inputEl.value, 10);
            setActive(isNaN(minutes) ? null : minutes);
        });
    }

    async _saveDeviceRegion(deviceDiv, label) {
        const input = deviceDiv.querySelector('[data-device-region-input]');
        const status = deviceDiv.querySelector('[data-device-region-status]');
        const button = deviceDiv.querySelector('[data-device-region-save]');
        if (!input || !status) return;

        const region = input.value;
        if (!region) {
            status.dataset.kind = 'error';
            status.textContent = 'Pick a region.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting region…';

        const result = await this._api.put('/api/config/serial/region', { label, region });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Region set to ${result.region}.`;
            this._api.toast('LoRa region updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceModemPreset(deviceDiv, label) {
        const chipsEl = deviceDiv.querySelector('[data-device-preset-chips]');
        const status = deviceDiv.querySelector('[data-device-preset-status]');
        const button = deviceDiv.querySelector('[data-device-preset-save]');
        if (!chipsEl || !status) return;

        const selected = chipsEl.querySelector('.cfg-chip--selected');
        if (!selected) {
            status.dataset.kind = 'error';
            status.textContent = 'Pick a preset.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting modem preset…';

        const result = await this._api.put('/api/config/serial/modem-preset', {
            label, modem_preset: selected.dataset.preset,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Preset set to ${result.modem_preset}.`;
            this._api.toast('Modem preset updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceBluetooth(deviceDiv, label) {
        const enabledEl = deviceDiv.querySelector('[data-device-bt-enabled]');
        const modeEl = deviceDiv.querySelector('[data-device-bt-mode]');
        const pinEl = deviceDiv.querySelector('[data-device-bt-pin]');
        const status = deviceDiv.querySelector('[data-device-bt-status]');
        const button = deviceDiv.querySelector('[data-device-bt-save]');
        if (!enabledEl || !status) return;

        const enabled = enabledEl.checked;
        const mode = enabled ? modeEl?.value : null;
        let fixedPin = null;
        if (enabled && mode === 'FIXED_PIN') {
            const pinValue = (pinEl?.value || '').trim();
            if (!pinValue) {
                status.dataset.kind = 'error';
                status.textContent = 'Enter a PIN.';
                return;
            }
            fixedPin = Number(pinValue);
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting Bluetooth…';

        const result = await this._api.put('/api/config/serial/bluetooth', {
            label, enabled, mode, fixed_pin: fixedPin,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = enabled ? 'Bluetooth updated.' : 'Bluetooth disabled.';
            this._api.toast('Bluetooth config updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceBroadcastIntervals(deviceDiv, label) {
        const nodeInfoEl = deviceDiv.querySelector('[data-device-ni-input]');
        const telemetryEl = deviceDiv.querySelector('[data-device-tel-input]');
        const status = deviceDiv.querySelector('[data-device-intervals-status]');
        const button = deviceDiv.querySelector('[data-device-intervals-save]');
        if (!status) return;

        const nodeInfoMin = (nodeInfoEl?.value || '').trim();
        const telemetryMin = (telemetryEl?.value || '').trim();
        if (!nodeInfoMin && !telemetryMin) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter at least one interval.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting intervals…';

        const result = await this._api.put('/api/config/serial/broadcast-intervals', {
            label,
            node_info_broadcast_secs: nodeInfoMin ? Number(nodeInfoMin) * 60 : null,
            telemetry_device_update_interval: telemetryMin ? Number(telemetryMin) * 60 : null,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Intervals updated.';
            this._api.toast('Broadcast intervals updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    _identityHtml(data, live) {
        const longValue = this._esc(data.long_name || (live && live.long_name) || '');
        const shortValue = this._esc(data.short_name || (live && live.short_name) || '');
        return `
            <div class="cfg-mc-identity" data-device-identity>
                <label class="cfg-field">
                    <span class="cfg-field__label">Long name</span>
                    <input class="cfg-field__input" type="text"
                           data-device-long-name maxlength="36"
                           value="${longValue}"
                           placeholder="My Meshpoint 433">
                </label>
                <label class="cfg-field">
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
                status.innerHTML = `Update available: ${this._esc(result.latest_version || '?')}${link}`
                    + ` — <a class="cfg-inline-link" href="#/configuration/firmware">flash it</a>`;
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

        const devices = [];
        let gpsSelected = false;
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((div) => {
            const serialPort = (div.querySelector('[data-device-port]')?.value || '').trim();
            const match = this._matchEnumeratedPort(serialPort);
            if (match && match.port_class === 'gps_known') gpsSelected = true;
            devices.push({
                label: (div.querySelector('[data-device-label]')?.value || '').trim(),
                serial_port: serialPort || null,
                serial_baud: Number(div.querySelector('[data-device-baud]')?.value) || 115200,
            });
        });

        if (gpsSelected) {
            const ok = await this._confirm({
                label: 'GPS port selected',
                description: 'One or more selected serial ports look like a GPS receiver. '
                    + 'gpsd may hold the port and Meshtastic capture will fail until it\'s '
                    + 'free. Save anyway?',
            });
            if (!ok) {
                status.dataset.kind = '';
                status.textContent = 'Save cancelled.';
                return;
            }
        }

        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

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
        if (live && !live.connected && (live.reconnecting || live.link_phase)) {
            const rebooting = live.link_phase === 'rebooting';
            const n = Number(live.retry_in_s) || 0;
            const why = rebooting
                ? 'The node is rebooting to apply its new settings; USB comes back by itself.'
                : 'The USB link dropped; retrying in the background.';
            const wait = n > 0 ? ` Next try in ${n}s.` : ' Connecting…';
            return `<p class="cfg-companion__offline-hint" data-serial-link-status>`
                + `<strong>${rebooting ? 'Rebooting' : 'Reconnecting'}.</strong> ${why}${wait}</p>`;
        }
        if (!live || !live.connected) {
            return `<p class="cfg-companion__offline-hint" data-serial-link-status>Not connected.</p>`;
        }
        const nodeId = live.own_node_id_hex ? `!${live.own_node_id_hex}` : '--';
        const name = live.long_name || live.short_name || '--';
        const sf = live.spreading_factor ? `SF${live.spreading_factor}` : '--';
        const bw = live.bandwidth_khz ? `${live.bandwidth_khz} kHz` : '--';
        const freq = live.frequency_mhz ? `${live.frequency_mhz} MHz` : '--';
        const txPower = (live.tx_power || live.tx_power === 0) ? `${live.tx_power} dBm` : '--';
        return `
            <div class="cfg-mc-readouts" data-serial-link-status>
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

    /** In-app confirmation dialog (replaces the browser's native
     * ``window.confirm`` popup). Uses the shared confirmModal helper;
     * falls back to native confirm if that script failed to load. Same
     * pattern as metrics_card.js's own identical helper. */
    _confirm({ label, description }) {
        if (window.confirmModal) {
            return window.confirmModal({ label, description });
        }
        return Promise.resolve(window.confirm(`${label}\n\n${description}`));
    }
}

window.SerialConfigCard = SerialConfigCard;
