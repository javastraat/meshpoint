/**
 * Configuration → Firmware page: Meshtastic card.
 *
 * Second card on the shared Firmware page, sitting below MeshCore's own
 * (frontend/js/configuration/meshcore_firmware_card.js) -- moved out of
 * Configuration → Serial for the same reason MeshCore's was: flashing a
 * spare board is a different action than configuring an already-
 * assigned device. Drives src/api/routes/meshtastic_firmware_routes.py.
 *
 * Same shape as MeshCore's card (Version + searchable Board + Device to
 * flash, both lists refreshable without reloading the page) with one
 * real difference: no Flavor field. MeshCore ships separate BLE-only vs
 * USB-only builds per board; Meshtastic's per-board firmware already
 * covers BLE+USB+WiFi together in one image, so there's nothing to pick.
 */

class MeshtasticFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-mt-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Meshtastic firmware</h3>
                        <p class="cfg-card__hint">
                            Flash any connected USB-serial device with official Meshtastic
                            firmware straight from this dashboard -- no compiling needed, and
                            no need to add it as a configured device first. "Erase everything"
                            is on by default so this also works on a board currently running
                            something else entirely (e.g. MeshCore or extra/pocsag_companion);
                            turn it off to upgrade a board already running Meshtastic without
                            losing its channels and settings.
                        </p>
                        <div class="cfg-firmware-installed" data-mt-firmware-installed aria-live="polite">
                            <span class="cfg-firmware-installed__label">Installed</span>
                            <span class="cfg-firmware-installed__version">Checking…</span>
                            <span class="cfg-firmware-installed__meta"></span>
                        </div>
                    </header>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Version</span>
                        <select class="cfg-field__input" data-mt-firmware-tag></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-mt-rescan-releases
                                title="Re-check Meshtastic's GitHub releases for a newly-published version">
                            ↻ Refresh
                        </button>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Board</span>
                        <input class="cfg-field__input" type="text" list="mt-firmware-boards-list"
                               data-mt-firmware-board placeholder="Search boards…" autocomplete="off">
                        <datalist id="mt-firmware-boards-list"></datalist>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-mt-firmware-device></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-mt-rescan-usb
                                title="Re-scan connected USB devices">
                            ↻ Rescan USB
                        </button>
                    </label>
                    <label class="cfg-field cfg-field--toggle cfg-firmware-board-field" data-mt-erase-all-wrap>
                        <input type="checkbox" data-mt-erase-all checked>
                        <span class="cfg-field__label">Erase everything (required for a board not already running Meshtastic)</span>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-mt-firmware-flash>
                            Flash
                        </button>
                        <button class="terminal-button" type="button" data-mt-firmware-toggle-output>
                            Show output
                        </button>
                    </div>
                    <pre class="cfg-firmware-output" data-mt-firmware-output hidden></pre>
                    <p class="cfg-status" data-mt-firmware-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._root.querySelector('[data-mt-firmware-flash]')
            .addEventListener('click', () => this._flashMeshtasticFirmware());
        this._root.querySelector('[data-mt-firmware-toggle-output]')
            .addEventListener('click', (e) => this._toggleMtFirmwareOutput(e.currentTarget));
        // Board list depends on which release is selected (each release's
        // own manifest lists its own board catalog), so re-fetch it
        // whenever Version changes rather than only once at mount.
        this._root.querySelector('[data-mt-firmware-tag]')
            .addEventListener('change', () => this._loadMtFirmwareTargets());
        this._root.querySelector('[data-mt-firmware-board]')
            .addEventListener('input', () => this._updateFlashButtonState());
        this._root.querySelector('[data-mt-rescan-releases]')
            .addEventListener('click', (e) => this._rescanReleases(e.currentTarget));
        this._root.querySelector('[data-mt-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        this._loadMtFirmwareReleases();
        this._loadMtFirmwareTargets();
        this._refreshSerialPortsList();
        this._loadInstalledFirmware();
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
    }

    /** "Installed" callout in the card header -- the currently-connected
     * node's own reported firmware version, read fresh on every mount
     * and again right after a successful flash (so the callout reflects
     * the new version instead of the pre-flash one). Shows the first
     * connected device prominently; a second configured node (rare, but
     * possible with multiple Serial devices) only adds a "+N more" hint
     * rather than a full second row -- this card flashes one board at a
     * time, so a compact "what's on the boards I already have" summary
     * is enough context, not a full per-device breakdown. */
    async _loadInstalledFirmware() {
        const root = this._root?.querySelector('[data-mt-firmware-installed]');
        if (!root) return;
        const versionEl = root.querySelector('.cfg-firmware-installed__version');
        const metaEl = root.querySelector('.cfg-firmware-installed__meta');
        if (!versionEl || !metaEl) return;
        versionEl.textContent = 'Checking…';
        metaEl.textContent = '';
        const data = await this._api.get('/api/config/serial/firmware/installed');
        if (!data) {
            versionEl.textContent = 'Unavailable';
            metaEl.textContent = 'Could not query serial nodes';
            return;
        }
        const devices = Array.isArray(data.devices) ? data.devices : [];
        const connected = devices.filter((d) => d.connected);
        if (!connected.length) {
            versionEl.textContent = 'Not connected';
            metaEl.textContent = '';
            return;
        }
        const primary = connected[0];
        const version = (primary.version || '').trim() || 'Version not reported';
        let hw = (primary.hw_model || '').toString().trim();
        if (hw && typeof HW_NAMES !== 'undefined') {
            hw = HW_NAMES[hw] || HW_NAMES[String(hw)] || hw;
        }
        const port = this._shortPortLabel(primary.port) || primary.name || 'USB';
        versionEl.textContent = version;
        const meta = [];
        if (hw) meta.push(hw);
        if (port) meta.push(port);
        if (connected.length > 1) meta.push(`+${connected.length - 1} more`);
        metaEl.textContent = meta.join(' · ');
    }

    /** Same short-port-label idea as serial_card.js's own device picker --
     * prefer the raw ttyUSB0/ttyACM0 name over a long by-path string, for
     * a compact callout. */
    _shortPortLabel(port) {
        if (!port) return '';
        const raw = String(port);
        const tty = raw.match(/tty(?:USB|ACM|AMA)\d+/i);
        if (tty) return tty[0];
        const base = raw.split('/').pop() || '';
        if (base.startsWith('tty')) return base;
        for (const p of this._enumeratedPorts || []) {
            const aliases = [p.device, p.by_id, p.by_path, p.stable_path].filter(Boolean);
            if (aliases.includes(raw)) return String(p.device || '').split('/').pop() || 'USB';
        }
        if (base.startsWith('platform-') || base.includes('pci-')) return 'USB';
        return base;
    }

    /** Maps every currently-configured serial_port value (across Serial
     * devices, MeshCore companions, and POCSAG companions -- one shared
     * USB pool) to a human label, for the "already used by ..." hint in
     * the device picker. Same logic as meshcore_firmware_card.js's own copy --
     * duplicated rather than shared, this file is otherwise independent
     * of that one. */
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

    /** Live USB-serial enumeration for the device picker. Re-fetched
     * whenever this page is mounted; the "↻ Rescan USB" button covers a
     * device plugged in after landing on this page instead of needing a
     * full reload. */
    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        this._renderMtFirmwareDevicePicker();
    }

    /** "↻ Rescan USB" click handler -- disable + "Scanning…" while in
     * flight, same as MeshCore's own copy. */
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

    /** Native <datalist>-truncation-avoiding label, identical to
     * meshcore_firmware_card.js's own _portOptionLabel. */
    _portOptionLabel(p, usage) {
        const devName = (p.device || '').split('/').pop();
        const chip = (p.description || '')
            .replace(/^Silicon Labs\s+/i, '')
            .replace(/\s+USB to UART Bridge Controller.*$/i, '')
            .trim() || p.description || p.device;
        const usedBy = [p.device, p.by_id, p.by_path].filter(Boolean)
            .map((alias) => usage[alias]).find(Boolean);
        const parts = [devName, chip];
        if (usedBy) parts.push(`used by ${usedBy}`);
        return parts.filter(Boolean).join(' — ');
    }

    /** Board choices for the searchable Board field, derived live from
     * whichever release is currently selected (see
     * meshtastic_firmware_routes.py's module docstring -- ~130 real
     * targets from that release's own manifest, not a hardcoded list).
     * Re-fetches on every Version change, not just once at mount, since
     * each release's manifest lists its own board catalog. Renders as a
     * <datalist> (search-as-you-type) rather than a plain <select>,
     * matching this app's existing USB-port-picker pattern. */
    async _loadMtFirmwareTargets() {
        const input = this._root.querySelector('[data-mt-firmware-board]');
        const list = this._root.querySelector('#mt-firmware-boards-list');
        if (!input || !list) return;

        const tag = this._root.querySelector('[data-mt-firmware-tag]')?.value || '';
        const params = new URLSearchParams();
        if (tag) params.set('tag', tag);

        const result = await this._api.get(`/api/config/serial/firmware/targets?${params}`);
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        this._boards = boards;

        list.innerHTML = boards.map((b) => (
            `<option value="${this._esc(b.board)}" label="${this._esc(b.label)}"></option>`
        )).join('');

        // The previously-picked board might not exist in a different
        // release's manifest -- clear it rather than silently keep a
        // choice that would just fail to find a matching target at
        // flash time.
        if (input.value && !boards.some((b) => b.board === input.value)) {
            input.value = '';
        }
        this._updateFlashButtonState();
    }

    /** Flash is only enabled once BOTH a real board and a real device are
     * selected -- board and device availability are checked by two
     * independent async loads (targets vs. serial-ports), so this is the
     * one place that reconciles them instead of each overwriting the
     * other's disabled/title state. */
    _updateFlashButtonState() {
        const flashBtn = this._root.querySelector('[data-mt-firmware-flash]');
        if (!flashBtn) return;
        const boardInput = this._root.querySelector('[data-mt-firmware-board]');
        const hasPorts = (this._enumeratedPorts || []).length > 0;
        const hasBoard = !!(boardInput && boardInput.value);
        if (!hasPorts) {
            flashBtn.disabled = true;
            flashBtn.title = 'No USB-serial device connected to flash.';
        } else if (!hasBoard) {
            flashBtn.disabled = true;
            flashBtn.title = 'Pick a board first.';
        } else {
            flashBtn.disabled = false;
            flashBtn.title = '';
        }
    }

    /** Looks up a board's friendly label from the last-loaded list, for
     * the confirm-modal/status text -- falls back to a lightly cleaned
     * version of the raw value if it's somehow not in that list (e.g. a
     * stale value left over from before a Version change). */
    _boardLabel(board) {
        const match = (this._boards || []).find((b) => b.board === board);
        return match ? match.label : board.replace(/-/g, ' ');
    }

    /** Populates the "Device to flash" pulldown from every currently
     * enumerated USB-serial device -- deliberately NOT limited to
     * already-configured devices, so a spare board (or a friend's, just
     * passing through) can be flashed without adding-then-removing a
     * permanent device entry first. Options carry the same "used by ..."
     * hint as serial_card.js's own device port field. The selected value
     * is a stable_path, re-validated against the live enumeration
     * server-side -- never trusted as a raw path from the browser. */
    _renderMtFirmwareDevicePicker() {
        const select = this._root.querySelector('[data-mt-firmware-device]');
        if (!select) return;

        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};

        if (ports.length === 0) {
            select.innerHTML = '<option value="">No USB-serial devices detected</option>';
        } else {
            const previous = select.value;
            select.innerHTML = ports.map((p) => (
                `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`
            )).join('');
            if (previous && ports.some((p) => p.stable_path === previous)) select.value = previous;
        }
        this._updateFlashButtonState();
    }

    /** Version pulldown, from the last 10 Meshtastic releases (GET
     * .../releases), newest first. "Latest" (empty tag, the default)
     * covers routine flashing; this is for the deliberate case -- pinning
     * an older or specific version. Fetched once at mount; the
     * "↻ Refresh" button below covers a release published while already
     * on this page. */
    async _loadMtFirmwareReleases() {
        const select = this._root.querySelector('[data-mt-firmware-tag]');
        if (!select) return;
        const result = await this._api.get('/api/config/serial/firmware/releases');
        const releases = (result && Array.isArray(result.releases)) ? result.releases : [];
        const previous = select.value;
        const options = ['<option value="">Latest</option>'];
        releases.forEach((r) => {
            options.push(`<option value="${this._esc(r.tag)}">${this._esc(r.tag)}</option>`);
        });
        select.innerHTML = options.join('');
        if (previous && releases.some((r) => r.tag === previous)) select.value = previous;
    }

    /** "↻ Refresh" click handler for Version -- re-checks GitHub for a
     * newly-published release, then re-runs the Board fetch too: if
     * "Latest" is selected and a new release just landed, the board list
     * fetched at mount time is for the now-stale "latest". */
    async _rescanReleases(button) {
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Checking…';
        try {
            await this._loadMtFirmwareReleases();
            await this._loadMtFirmwareTargets();
        } finally {
            button.textContent = original;
            button.disabled = false;
        }
    }

    _toggleMtFirmwareOutput(button) {
        const pre = this._root.querySelector('[data-mt-firmware-output]');
        if (!pre) return;
        pre.hidden = !pre.hidden;
        button.textContent = pre.hidden ? 'Show output' : 'Hide output';
    }

    _appendMtFirmwareOutput(text) {
        const pre = this._root.querySelector('[data-mt-firmware-output]');
        if (!pre || !text) return;
        pre.textContent = pre.textContent ? `${pre.textContent}\n${text}` : text;
        pre.scrollTop = pre.scrollHeight;
    }

    async _flashMeshtasticFirmware() {
        const boardInput = this._root.querySelector('[data-mt-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-mt-firmware-device]');
        const tagSelect = this._root.querySelector('[data-mt-firmware-tag]');
        const eraseAllInput = this._root.querySelector('[data-mt-erase-all]');
        const board = (boardInput?.value || '').trim();
        const port = deviceSelect?.value;
        const eraseAll = eraseAllInput ? eraseAllInput.checked : true;
        if (!board || !port) return;

        const status = this._root.querySelector('[data-mt-firmware-status]');
        // Free-text field (search-as-you-type against the datalist) --
        // unlike a <select>, nothing stops a value that doesn't match any
        // real board from being submitted, so check before wasting a
        // round trip on a request that could only ever fail server-side.
        if (!(this._boards || []).some((b) => b.board === board)) {
            if (status) {
                status.dataset.kind = 'error';
                status.textContent = `"${board}" isn't in the current board list -- pick one from the suggestions.`;
            }
            return;
        }

        const boardLabel = this._boardLabel(board);
        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;
        const tag = tagSelect?.value || '';

        const ok = await window.confirmModal({
            label: 'Flash Meshtastic firmware',
            description: eraseAll
                ? `Erase the ENTIRE flash on "${deviceLabel}" and write official Meshtastic `
                    + `firmware (${tag || 'latest'}) for ${boardLabel}? This replaces whatever `
                    + 'is currently on the board -- not reversible from here.'
                : `Write official Meshtastic firmware (${tag || 'latest'}) for ${boardLabel} `
                    + `to "${deviceLabel}", keeping its existing channels and settings? Only `
                    + 'do this for a board already running Meshtastic -- on anything else, the '
                    + 'result is unpredictable.',
        });
        if (!ok) return;

        const flashBtn = this._root.querySelector('[data-mt-firmware-flash]');
        const outputPre = this._root.querySelector('[data-mt-firmware-output]');

        flashBtn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = `Flashing ${deviceLabel}…`;
        if (outputPre) outputPre.textContent = '';
        this._appendMtFirmwareOutput(`# Flashing ${boardLabel} (${tag || 'latest'}) onto ${port}…`);

        let finalResult = null;
        try {
            finalResult = await window.UpdateStreamClient.postNdjson(
                '/api/config/serial/firmware/flash/stream',
                { board, port, tag, erase_all: eraseAll },
                (event) => {
                    if (event.type === 'started' && Array.isArray(event.cmd)) {
                        this._appendMtFirmwareOutput(`$ ${event.cmd.join(' ')}`);
                    } else if (event.type === 'line') {
                        this._appendMtFirmwareOutput(event.text);
                    }
                },
            );
        } catch (err) {
            status.dataset.kind = 'error';
            status.textContent = `Request failed: ${err.message || err}`;
            this._appendMtFirmwareOutput(`! ${err.message || err}`);
            flashBtn.disabled = false;
            return;
        }

        const success = !!(finalResult && finalResult.success);
        status.dataset.kind = success ? 'success' : 'error';
        status.textContent = success
            ? 'Flashed.'
            : `Failed (exit code ${finalResult ? finalResult.returncode : '?'}). See output below.`;
        if (!success && outputPre) outputPre.hidden = false;
        const toggleBtn = this._root.querySelector('[data-mt-firmware-toggle-output]');
        if (toggleBtn && outputPre) {
            toggleBtn.textContent = outputPre.hidden ? 'Show output' : 'Hide output';
        }

        flashBtn.disabled = false;
        if (success) {
            await this._api.refresh();
            await this._loadInstalledFirmware();
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.MeshtasticFirmwareConfigCard = MeshtasticFirmwareConfigCard;
