/**
 * Reticulum plugin page: "Settings" tab.
 *
 * Ported from the old core Configuration -> Reticulum card
 * (frontend/js/configuration/reticulum_config_card.js) to a
 * plain-fetch()-driven tab -- a plugin's own page has no access to
 * ConfigurationPanel's `this._api` wrapper, so `_request`/`_toast` below
 * replicate the essential bits (same shape as dapnet_settings_tab.js).
 *
 * Edits the RNode radio + TCP backbone fields (plus display name) that
 * scripts/write_rnsd_config.py turns into rnsd's own config file. There's
 * no "enabled" checkbox -- Settings -> Plugins' own toggle is the sole
 * on/off switch. Saving only updates local.yaml; the RNode/backbone
 * fields need an rnsd restart ("Restart rnsd" below) to apply, and
 * display name needs the usual meshpoint restart.
 */

const RT_BANDWIDTHS_HZ = [
    7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000,
];

class ReticulumSettingsTab {
    constructor(el) {
        this._el = el;
        this._mounted = false;
        this._enumeratedPorts = [];
        this._portUsage = {};
        this._pendingPort = '';
    }

    show() {
        if (!this._mounted) this._mount();
        this._load();
    }

    hide() {}

    _mount() {
        this._mounted = true;
        this._el.innerHTML = `
            <div class="cfg-section" data-rt-settings-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Reticulum</h3>
                        <p class="cfg-card__hint">
                            Native Reticulum/LXMF messaging, sharing an RNode over USB with
                            the opt-in <code>rnsd</code> service. Requires <code>rnsd</code>
                            to be installed (Settings → Plugins, or
                            <code>sudo meshpoint plugin setup reticulum</code>) --
                            this tab only edits its config. Enable/disable the whole plugin
                            from Settings → Plugins.
                        </p>
                    </header>
                    <form class="cfg-form" data-rt-form>
                        <label class="cfg-field">
                            <span class="cfg-field__label">Display name</span>
                            <input class="cfg-field__input" type="text" maxlength="32"
                                   placeholder="Meshpoint" data-rt-display-name>
                            <span class="cfg-field__hint">Shown to peers over LXMF announces.</span>
                        </label>
                        <label class="cfg-field cfg-field--narrow">
                            <span class="cfg-field__label">NomadNet timeout (s)</span>
                            <input class="cfg-field__input" type="number" min="5" max="120" step="1"
                                   data-rt-nomad-timeout>
                            <span class="cfg-field__hint">Browse tab: link/path budget. Bump for multi-hop LoRa nodes. Takes effect immediately.</span>
                        </label>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">RNode radio</legend>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-rnode-enabled>
                                <span class="cfg-field__label">Enable RNode radio interface</span>
                            </label>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Serial port</span>
                                <select class="cfg-field__input" data-rt-serial-port></select>
                                <button class="terminal-button cfg-firmware-rescan" type="button"
                                        data-rt-rescan-usb title="Re-scan connected USB devices">
                                    ↻ Rescan USB
                                </button>
                            </label>
                            <div class="cfg-row">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Frequency (Hz)</span>
                                    <input class="cfg-field__input" type="number"
                                           min="100000000" max="1000000000" step="1"
                                           data-rt-frequency>
                                    <span class="cfg-field__hint" data-rt-frequency-mhz>--</span>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Bandwidth</span>
                                    <select class="cfg-field__input" data-rt-bandwidth>
                                        ${RT_BANDWIDTHS_HZ.map((hz) => (
                                            `<option value="${hz}">${(hz / 1000).toLocaleString()} kHz</option>`
                                        )).join('')}
                                    </select>
                                </label>
                            </div>
                            <div class="cfg-row">
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">TX power (dBm)</span>
                                    <input class="cfg-field__input" type="number"
                                           min="0" max="22" step="1" data-rt-tx-power>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Spreading factor</span>
                                    <input class="cfg-field__input" type="number"
                                           min="5" max="12" step="1" data-rt-sf>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Coding rate</span>
                                    <input class="cfg-field__input" type="number"
                                           min="5" max="8" step="1" data-rt-cr>
                                </label>
                            </div>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">TCP backbone</legend>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-backbone-enabled>
                                <span class="cfg-field__label">Enable TCP backbone interface</span>
                            </label>
                            <p class="cfg-field__hint">
                                Community Reticulum backbone hop, reached over the internet
                                alongside the RNode's LoRa interface. At least one of the two
                                interfaces above must stay enabled.
                            </p>
                            <div class="cfg-row">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Host</span>
                                    <input class="cfg-field__input" type="text"
                                           placeholder="node.reticulumnet.nl" data-rt-backbone-host>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Port</span>
                                    <input class="cfg-field__input" type="number"
                                           min="1" max="65535" data-rt-backbone-port>
                                </label>
                            </div>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">Propagation node</legend>
                            <p class="cfg-field__hint" data-rt-prop-status>
                                Run an LXMF store-and-forward relay: messages for a peer
                                who's offline get held here until their client next syncs
                                from this node. The natural job for an always-on box. Off
                                by default; takes effect after a restart.
                            </p>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-prop-enabled>
                                <span class="cfg-field__label">Act as an LXMF propagation node</span>
                            </label>
                            <label class="cfg-field cfg-field--narrow">
                                <span class="cfg-field__label">Store limit (MB)</span>
                                <input class="cfg-field__input" type="number"
                                       min="0" max="100000" step="10" data-rt-prop-storage>
                                <span class="cfg-field__hint">
                                    Cap for the on-disk message store. 0 = LXMF's own
                                    default (don't leave it uncapped on a small SD card).
                                </span>
                            </label>
                            <p class="cfg-field__hint rt-prop-divider">
                                <strong>Use another node as your propagation node</strong> —
                                route your messages to offline peers through it, and sync
                                any messages parked there for you. Independent of the relay
                                toggle above. Takes effect after a restart.
                            </p>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Outbound propagation node</span>
                                <select class="cfg-field__input" data-rt-prop-outbound>
                                    <option value="">-- none (don't use one) --</option>
                                </select>
                                <span class="cfg-field__hint" data-rt-prop-client-status>
                                    Pick an <code>lxmf.propagation</code> peer heard on the
                                    network, or leave as none.
                                </span>
                            </label>
                            <label class="cfg-field cfg-field--narrow">
                                <span class="cfg-field__label">Auto-sync every (s)</span>
                                <input class="cfg-field__input" type="number"
                                       min="0" max="86400" step="60" data-rt-prop-autosync>
                                <span class="cfg-field__hint">
                                    0 = manual only (use "Sync inbox" on the Reticulum page).
                                    Otherwise re-syncs on this interval; minimum 300.
                                </span>
                            </label>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">Telemetry</legend>
                            <p class="cfg-field__hint" data-rt-telemetry-status>
                                Periodically send this box's own host stats — CPU
                                temperature, load, RAM/disk, a status line — to a
                                collector address as a Sideband-compatible LXMF telemetry
                                frame. Off by default; takes effect after a restart.
                            </p>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-telemetry-enabled>
                                <span class="cfg-field__label">Publish telemetry</span>
                            </label>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Collector address</span>
                                <input class="cfg-field__input" type="text" maxlength="64"
                                       placeholder="lxmf.delivery destination hash"
                                       data-rt-telemetry-collector>
                                <span class="cfg-field__hint">
                                    The LXMF address that should receive the frames — e.g.
                                    a Sideband client subscribed to this node.
                                </span>
                            </label>
                            <label class="cfg-field cfg-field--narrow">
                                <span class="cfg-field__label">Send every (s)</span>
                                <input class="cfg-field__input" type="number"
                                       min="300" max="86400" step="60" data-rt-telemetry-interval>
                            </label>
                            <div class="cfg-card__actions">
                                <button class="terminal-button" type="button" data-rt-telemetry-send>
                                    Send telemetry now
                                </button>
                            </div>
                            <p class="cfg-status" data-rt-telemetry-send-status aria-live="polite"></p>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">NomadNet node</legend>
                            <p class="cfg-field__hint" data-rt-node-status>
                                Host a NomadNet node — serve Micron pages over Reticulum,
                                on the same identity as your LXMF address (so you're both
                                "message me" and "browse me" on one hash). Off by default.
                            </p>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-node-enabled>
                                <span class="cfg-field__label">Host a NomadNet node</span>
                            </label>
                            <p class="cfg-field__hint">
                                Turning this on or off takes effect after the next
                                Meshpoint restart.
                            </p>
                            <div class="cfg-row">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Node name</span>
                                    <input class="cfg-field__input" type="text" maxlength="64"
                                           placeholder="(defaults to display name)" data-rt-node-name>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Announce every (s)</span>
                                    <input class="cfg-field__input" type="number"
                                           min="600" max="604800" step="60" data-rt-node-interval>
                                </label>
                            </div>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Pages directory</span>
                                <input class="cfg-field__input" type="text"
                                       placeholder="data/reticulum/pages" data-rt-node-pages>
                                <span class="cfg-field__hint">
                                    Drop <code>.mu</code> files here for extra pages; files under
                                    a <code>files/</code> subdir are served at <code>/file/…</code>.
                                    A built-in index page shows live Meshpoint stats; an
                                    <code>index.mu</code> here replaces it — see
                                    <code>plugins/apps/reticulum/sample-pages/index.mu</code>.
                                    Changes need a restart.
                                </span>
                            </label>
                            <label class="cfg-field">
                                <span class="cfg-field__label">SpaceAPI URL (optional)</span>
                                <input class="cfg-field__input" type="text"
                                       placeholder="https://your-space/spaceapi.json" data-rt-node-spaceapi>
                                <span class="cfg-field__hint">
                                    Hackerspace status feed. Set it and the node also serves
                                    <code>/page/spacestate.mu</code> (open/closed + address);
                                    any of your own <code>.mu</code> pages can use the
                                    <code>{spacestate}</code> token for a live OPEN/CLOSED word.
                                    Find yours at <code>directory.spaceapi.io</code>. Restart to apply.
                                </span>
                            </label>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Events iCal URL (optional)</span>
                                <input class="cfg-field__input" type="text"
                                       placeholder="https://your-wiki/Events.ics" data-rt-node-events>
                                <span class="cfg-field__hint">
                                    An <code>.ics</code> calendar feed. Set it and the node also
                                    serves <code>/page/events.mu</code> — the next dozen upcoming
                                    events, fetched on demand (once at boot, then only when the
                                    page is viewed). Restart to apply.
                                </span>
                            </label>
                            <label class="cfg-field cfg-field--toggle">
                                <input type="checkbox" data-rt-talkback-enabled>
                                <span class="cfg-field__label">Talk-back bot</span>
                            </label>
                            <p class="cfg-field__hint">
                                Auto-reply to a DM starting with <code>.help</code>, <code>.ping</code>,
                                <code>.stats</code>, <code>.spacestate</code>, <code>.events</code> or
                                <code>.nodes</code> with the same data those pages show — the leading
                                dot means an ordinary message that happens to say "ping" never
                                triggers a reply. Requires "Host a NomadNet node" above. Restart to apply.
                            </p>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">Message notifications</legend>
                            <label class="cfg-field">
                                <span class="cfg-field__label">ntfy / webhook URL (optional)</span>
                                <input class="cfg-field__input" type="text"
                                       placeholder="https://ntfy.sh/your-topic" data-rt-notify-url>
                                <span class="cfg-field__hint">
                                    When an LXMF direct message arrives, POST its text here
                                    with the sender as the <code>Title</code> header — an
                                    <a href="https://ntfy.sh" target="_blank" rel="noopener">ntfy</a>
                                    topic or any webhook that takes a plain-text body. This
                                    sends the message text to that third-party service; use a
                                    self-hosted ntfy or private webhook if that matters.
                                    Restart to apply.
                                </span>
                            </label>
                        </fieldset>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary" type="submit">
                                Save Reticulum
                            </button>
                        </div>
                        <p class="cfg-status" data-rt-status aria-live="polite"></p>
                    </form>
                    <div class="cfg-card__actions">
                        <button class="terminal-button" type="button" data-rt-restart-rnsd>
                            Restart rnsd
                        </button>
                    </div>
                    <p class="cfg-field__hint">
                        Applies saved RNode/backbone settings by restarting the
                        <code>rnsd</code> service directly, without a full meshpoint
                        restart. Display name changes still need the usual meshpoint
                        service restart (Settings → System).
                    </p>
                    <p class="cfg-status" data-rt-rnsd-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._form = this._q('[data-rt-form]');
        this._displayName = this._q('[data-rt-display-name]');
        this._nomadTimeout = this._q('[data-rt-nomad-timeout]');
        this._rnodeEnabled = this._q('[data-rt-rnode-enabled]');
        this._serialPort = this._q('[data-rt-serial-port]');
        this._frequency = this._q('[data-rt-frequency]');
        this._frequencyMhz = this._q('[data-rt-frequency-mhz]');
        this._bandwidth = this._q('[data-rt-bandwidth]');
        this._txPower = this._q('[data-rt-tx-power]');
        this._sf = this._q('[data-rt-sf]');
        this._cr = this._q('[data-rt-cr]');
        this._backboneEnabled = this._q('[data-rt-backbone-enabled]');
        this._backboneHost = this._q('[data-rt-backbone-host]');
        this._backbonePort = this._q('[data-rt-backbone-port]');
        this._propEnabled = this._q('[data-rt-prop-enabled]');
        this._propStorage = this._q('[data-rt-prop-storage]');
        this._propStatusEl = this._q('[data-rt-prop-status]');
        this._propOutbound = this._q('[data-rt-prop-outbound]');
        this._propAutoSync = this._q('[data-rt-prop-autosync]');
        this._propClientStatusEl = this._q('[data-rt-prop-client-status]');
        this._telemetryEnabled = this._q('[data-rt-telemetry-enabled]');
        this._telemetryCollector = this._q('[data-rt-telemetry-collector]');
        this._telemetryInterval = this._q('[data-rt-telemetry-interval]');
        this._telemetryStatusEl = this._q('[data-rt-telemetry-status]');
        this._telemetrySendStatusEl = this._q('[data-rt-telemetry-send-status]');
        this._nodeEnabled = this._q('[data-rt-node-enabled]');
        this._nodeName = this._q('[data-rt-node-name]');
        this._nodeInterval = this._q('[data-rt-node-interval]');
        this._nodePages = this._q('[data-rt-node-pages]');
        this._nodeSpaceapi = this._q('[data-rt-node-spaceapi]');
        this._nodeEvents = this._q('[data-rt-node-events]');
        this._talkbackEnabled = this._q('[data-rt-talkback-enabled]');
        this._notifyUrl = this._q('[data-rt-notify-url]');
        this._nodeStatusEl = this._q('[data-rt-node-status]');
        this._statusEl = this._q('[data-rt-status]');
        this._rnsdStatusEl = this._q('[data-rt-rnsd-status]');

        this._form.addEventListener('submit', (e) => this._onSubmit(e));
        this._frequency.addEventListener('input', () => this._renderFrequencyHint());
        this._q('[data-rt-rescan-usb]').addEventListener('click', (e) => this._rescanUsb(e.currentTarget));
        this._q('[data-rt-restart-rnsd]').addEventListener('click', () => this._restartRnsd());
        this._q('[data-rt-telemetry-send]')?.addEventListener('click', (e) => this._sendTelemetry(e.currentTarget));
    }

    _q(sel) { return this._el.querySelector(sel); }

    async _load() {
        // The reticulum settings (fast -- just plugins.reticulum.*) render
        // immediately; the port dropdown + its "used by" hints (which need
        // the big GET /api/config + a USB rescan) fill in a beat later so
        // the form isn't blank while those run.
        const rt = await this._request('GET', '/api/config/reticulum');
        this._pendingPort = (rt && rt.rnode_serial_port) || '';
        this._render(rt || {});

        this._request('GET', '/api/config').then((config) => {
            this._portUsage = this._buildPortUsageMap(config || {});
            this._refreshSerialPortsList();
        });
    }

    _render(rt) {
        if (this._displayName) this._displayName.value = rt.display_name || 'Meshpoint';
        if (this._nomadTimeout) this._nomadTimeout.value = rt.nomad_timeout_s ?? 20;
        if (this._nodeEnabled) this._nodeEnabled.checked = !!rt.node_enabled;
        if (this._nodeName) this._nodeName.value = rt.node_name || '';
        if (this._nodeInterval) this._nodeInterval.value = rt.node_announce_interval_s ?? 21600;
        if (this._nodePages) this._nodePages.value = rt.node_pages_dir || 'data/reticulum/pages';
        if (this._nodeSpaceapi) this._nodeSpaceapi.value = rt.node_spaceapi_url || '';
        if (this._nodeEvents) this._nodeEvents.value = rt.node_events_ical_url || '';
        if (this._talkbackEnabled) this._talkbackEnabled.checked = !!rt.talkback_enabled;
        if (this._notifyUrl) this._notifyUrl.value = rt.notify_url || '';
        this._loadNodeStatus();
        if (this._rnodeEnabled) this._rnodeEnabled.checked = rt.rnode_enabled !== false;
        if (this._frequency) {
            this._frequency.value = rt.rnode_frequency_hz ?? 869463000;
            this._renderFrequencyHint();
        }
        if (this._bandwidth) this._bandwidth.value = rt.rnode_bandwidth_hz ?? 125000;
        if (this._txPower) this._txPower.value = rt.rnode_tx_power ?? 20;
        if (this._sf) this._sf.value = rt.rnode_spreading_factor ?? 8;
        if (this._cr) this._cr.value = rt.rnode_coding_rate ?? 5;
        if (this._backboneEnabled) this._backboneEnabled.checked = rt.backbone_enabled !== false;
        if (this._backboneHost) this._backboneHost.value = rt.backbone_host || 'node.reticulumnet.nl';
        if (this._backbonePort) this._backbonePort.value = rt.backbone_port ?? 4242;
        if (this._propEnabled) this._propEnabled.checked = !!rt.propagation_enabled;
        if (this._propStorage) this._propStorage.value = rt.propagation_storage_limit_mb ?? 250;
        if (this._propAutoSync) this._propAutoSync.value = rt.propagation_auto_sync_interval_s ?? 0;
        this._pendingOutbound = (rt.propagation_outbound_node || '').toLowerCase();
        this._populateOutboundNodes();
        if (this._telemetryEnabled) this._telemetryEnabled.checked = !!rt.telemetry_enabled;
        if (this._telemetryCollector) this._telemetryCollector.value = rt.telemetry_collector || '';
        if (this._telemetryInterval) this._telemetryInterval.value = rt.telemetry_interval_s ?? 900;
        this._loadPropagationStatus();
        this._loadTelemetryStatus();
    }

    async _loadTelemetryStatus() {
        if (!this._telemetryStatusEl) return;
        let t = null;
        try {
            const r = await fetch('/api/reticulum/telemetry', { credentials: 'same-origin' });
            if (r.ok) t = await r.json();
        } catch (_) { return; }
        if (!t || !t.enabled) return;
        const when = t.last_sent_at
            ? `last sent ${this._agoStr(Math.round(Date.now() / 1000 - t.last_sent_at))}`
            : 'nothing sent yet';
        const err = t.last_error ? ` — last error: ${t.last_error}` : '';
        this._telemetryStatusEl.textContent =
            `Publishing to ${(t.collector || '?').slice(0, 12)}… every ${t.interval_s}s — ${when}${err}.`;
    }

    _agoStr(s) {
        if (s == null) return 'never';
        if (s < 90) return `${s}s ago`;
        if (s < 5400) return `${Math.round(s / 60)}m ago`;
        return `${Math.round(s / 3600)}h ago`;
    }

    /** Fill the outbound-propagation-node <select> from the roster's
     * lxmf.propagation peers, keeping the currently-saved hash selectable
     * even if that peer hasn't re-announced this session. */
    async _populateOutboundNodes() {
        const sel = this._propOutbound;
        if (!sel) return;
        let peers = [];
        try {
            const r = await fetch('/api/reticulum/peers', { credentials: 'same-origin' });
            if (r.ok) peers = (await r.json()).filter((p) => p.aspect === 'lxmf.propagation');
        } catch (_) {}
        const saved = this._pendingOutbound || '';
        const opts = ['<option value="">-- none (don\'t use one) --</option>'];
        const seen = new Set();
        peers.forEach((p) => {
            seen.add(p.destination_hash);
            const label = (p.petname || p.display_name || p.destination_hash);
            opts.push(`<option value="${this._esc(p.destination_hash)}">${this._esc(label)} — ${this._esc(p.destination_hash.slice(0, 12))}…</option>`);
        });
        if (saved && !seen.has(saved)) {
            opts.push(`<option value="${this._esc(saved)}">${this._esc(saved)} (not heard this session)</option>`);
        }
        sel.innerHTML = opts.join('');
        sel.value = saved;
    }

    async _loadPropagationStatus() {
        if (!this._propStatusEl) return;
        let p = null;
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (r.ok) p = (await r.json()).propagation;
        } catch (_) { return; }
        if (p && p.enabled) {
            const held = p.messages_held == null ? '' : `, ${p.messages_held} message(s) held`;
            const cap = p.storage_limit_mb ? `${p.storage_limit_mb} MB store` : 'store uncapped';
            this._propStatusEl.textContent =
                `Relaying now — address ${p.address || '(pending)'}, ${cap}${held}. `
                + 'Point a client at this address to sync from it.';
        }
        await this._loadPropagationClientStatus();
    }

    async _loadPropagationClientStatus() {
        if (!this._propClientStatusEl) return;
        let c = null;
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (r.ok) c = (await r.json()).propagation_client;
        } catch (_) { return; }
        if (!c || !c.outbound_node) return;
        const last = c.last_result == null ? '' : ` · last sync: ${c.last_result} message(s) received`;
        const auto = c.auto_sync_interval_s > 0
            ? ` · auto-sync every ${c.auto_sync_interval_s}s` : '';
        const state = (c.state && c.state !== 'idle' && c.state !== 'complete')
            ? ` · ${c.state.replace(/_/g, ' ')}` : '';
        this._propClientStatusEl.textContent =
            `Using ${c.outbound_node.slice(0, 12)}… as your propagation node${auto}${state}${last}.`;
    }

    async _loadNodeStatus() {
        if (!this._nodeStatusEl) return;
        let node = null;
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (r.ok) node = (await r.json()).node;
        } catch (_) { return; }
        if (!node || !node.hosting) return;
        const ago = node.last_announce_s_ago;
        const agoStr = ago == null ? 'never'
            : ago < 90 ? `${ago}s ago`
            : ago < 5400 ? `${Math.round(ago / 60)}m ago`
            : `${Math.round(ago / 3600)}h ago`;
        this._nodeStatusEl.textContent =
            `Hosting now as "${node.name}" — ${node.pages} page(s), `
            + `last announce ${agoStr}, ${node.requests_served} request(s) served.`;
    }

    _renderFrequencyHint() {
        if (!this._frequencyMhz) return;
        const hz = Number(this._frequency.value);
        this._frequencyMhz.textContent = hz ? `= ${(hz / 1_000_000).toFixed(3)} MHz` : '--';
    }

    /** Same shared USB pool every other companion's port picker draws from
     * -- duplicated logic, not a shared import, matching this codebase's
     * established convention for these cards. */
    _buildPortUsageMap(config) {
        const usage = {};
        const cap = config.capture || {};
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
        (Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : []).forEach((c) => {
            if (c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        return usage;
    }

    async _refreshSerialPortsList() {
        const result = await this._request('GET', '/api/config/serial-ports');
        this._enumeratedPorts = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._renderDevicePicker();
    }

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

    _renderDevicePicker() {
        if (!this._serialPort) return;
        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};
        const pending = this._pendingPort || '';
        const options = ['<option value="">-- none --</option>'];
        ports.forEach((p) => {
            options.push(
                `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`,
            );
        });
        // Match against every known alias (device / stable_path / by_id /
        // by_path), not just stable_path -- a pinned "/dev/ttyUSBn" in
        // local.yaml vs. a by-id stable_path here for the same device
        // would otherwise wrongly show as "not connected".
        const pendingConnected = pending && ports.some((p) => (
            [p.device, p.stable_path, p.by_id, p.by_path].includes(pending)
        ));
        if (pending && !pendingConnected) {
            options.push(`<option value="${this._esc(pending)}">${this._esc(pending)} (not currently connected)</option>`);
        }
        this._serialPort.innerHTML = options.join('');
        if (pendingConnected) {
            const match = ports.find((p) => (
                [p.device, p.stable_path, p.by_id, p.by_path].includes(pending)
            ));
            this._serialPort.value = match.stable_path;
        } else {
            this._serialPort.value = pending;
        }
    }

    async _onSubmit(event) {
        event.preventDefault();
        const rnodeEnabled = !!this._rnodeEnabled.checked;
        const backboneEnabled = !!this._backboneEnabled.checked;
        if (!rnodeEnabled && !backboneEnabled) {
            this._setStatus(
                'error',
                'At least one of RNode radio or TCP backbone must stay enabled '
                + '(disable the whole plugin from Settings → Plugins instead).',
            );
            return;
        }
        if (this._talkbackEnabled?.checked && !this._nodeEnabled.checked) {
            this._setStatus(
                'error',
                'The talk-back bot answers from data the hosted NomadNet node '
                + 'caches -- enable "Host a NomadNet node" first.',
            );
            return;
        }
        const outboundNode = (this._propOutbound?.value || '').trim();
        const autoSync = Number(this._propAutoSync?.value) || 0;
        if (autoSync > 0 && !outboundNode) {
            this._setStatus('error', 'Auto-sync needs an outbound propagation node — pick one, or set the interval to 0.');
            return;
        }
        if (autoSync > 0 && autoSync < 300) {
            this._setStatus('error', 'Auto-sync interval must be 0 or at least 300 seconds.');
            return;
        }
        const telemetryEnabled = !!this._telemetryEnabled?.checked;
        const telemetryCollector = (this._telemetryCollector?.value || '').trim();
        if (telemetryEnabled && !telemetryCollector) {
            this._setStatus('error', 'Telemetry publishing needs a collector address — set one, or turn telemetry off.');
            return;
        }
        const payload = {
            display_name: this._displayName.value.trim() || 'Meshpoint',
            nomad_timeout_s: Number(this._nomadTimeout.value) || 20,
            node_enabled: !!this._nodeEnabled.checked,
            node_name: this._nodeName.value.trim(),
            node_pages_dir: this._nodePages.value.trim() || 'data/reticulum/pages',
            node_announce_interval_s: Number(this._nodeInterval.value) || 21600,
            node_spaceapi_url: (this._nodeSpaceapi?.value || '').trim(),
            node_events_ical_url: (this._nodeEvents?.value || '').trim(),
            talkback_enabled: !!this._talkbackEnabled?.checked,
            notify_url: (this._notifyUrl?.value || '').trim(),
            propagation_enabled: !!this._propEnabled?.checked,
            propagation_storage_limit_mb: Number(this._propStorage?.value) || 0,
            propagation_outbound_node: outboundNode,
            propagation_auto_sync_interval_s: autoSync,
            telemetry_enabled: telemetryEnabled,
            telemetry_collector: telemetryCollector,
            telemetry_interval_s: Number(this._telemetryInterval?.value) || 900,
            rnode_enabled: rnodeEnabled,
            rnode_serial_port: this._serialPort.value,
            rnode_frequency_hz: Number(this._frequency.value),
            rnode_bandwidth_hz: Number(this._bandwidth.value),
            rnode_tx_power: Number(this._txPower.value),
            rnode_spreading_factor: Number(this._sf.value),
            rnode_coding_rate: Number(this._cr.value),
            backbone_enabled: backboneEnabled,
            backbone_host: this._backboneHost.value.trim() || 'node.reticulumnet.nl',
            backbone_port: Number(this._backbonePort.value),
        };

        this._setStatus('pending', 'Saving…');
        const result = await this._request('PUT', '/api/config/reticulum', payload);
        if (result) {
            this._setStatus('success', 'Saved.');
            this._toast(
                'Reticulum settings updated. RNode/backbone changes need "Restart rnsd" '
                + 'below; display name needs a meshpoint restart (Settings → System).',
            );
        } else {
            this._setStatus('error', 'Save failed.');
        }
    }

    async _sendTelemetry(button) {
        const statusEl = this._telemetrySendStatusEl;
        button.disabled = true;
        if (statusEl) { statusEl.dataset.kind = 'pending'; statusEl.textContent = 'Sending…'; }
        try {
            const r = await fetch('/api/reticulum/telemetry/send', {
                method: 'POST', credentials: 'same-origin',
            });
            const body = await r.json().catch(() => ({}));
            if (statusEl) {
                statusEl.dataset.kind = r.ok ? 'success' : 'error';
                statusEl.textContent = r.ok ? 'Sent.' : (body.detail || 'Send failed.');
            }
        } catch (_) {
            if (statusEl) { statusEl.dataset.kind = 'error'; statusEl.textContent = 'Send failed.'; }
        } finally {
            button.disabled = false;
            this._loadTelemetryStatus();
        }
    }

    async _restartRnsd() {
        const ok = window.confirmModal
            ? await window.confirmModal({
                label: 'Restart rnsd',
                description: 'Restart the rnsd service now? It briefly drops the RNode '
                    + 'interface and Reticulum messaging while it reconnects.',
            })
            : window.confirm('Restart the rnsd service now?');
        if (!ok) return;

        const button = this._q('[data-rt-restart-rnsd]');
        button.disabled = true;
        this._setRnsdStatus('pending', 'Restarting rnsd…');
        try {
            const result = await this._request('POST', '/api/config/reticulum/restart-rnsd', {});
            if (result && result.success) {
                this._setRnsdStatus('success', 'rnsd restarted.');
            } else {
                this._setRnsdStatus('error', 'Restart failed.');
            }
        } finally {
            button.disabled = false;
        }
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }

    _setRnsdStatus(kind, message) {
        if (!this._rnsdStatusEl) return;
        this._rnsdStatusEl.dataset.kind = kind;
        this._rnsdStatusEl.textContent = message;
    }

    /** Minimal stand-in for ConfigurationPanel's `this._api` wrapper --
     * same error-toast-on-failure shape as configuration_panel.js's own
     * _request(). */
    async _request(method, url, body) {
        const init = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
        if (body !== undefined && body !== null) init.body = JSON.stringify(body);
        const isGet = method === 'GET';
        try {
            const res = await fetch(url, init);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this._toast(`${isGet ? 'Error' : 'Save failed'}: ${err.detail || res.status}`);
                return null;
            }
            return await res.json();
        } catch (e) {
            this._toast(`${isGet ? 'Error' : 'Save failed'}: ${e.message}`);
            return null;
        }
    }

    /** Reuses the Configuration page's own #cfg-toast singleton/CSS
     * (frontend/css/configuration.css, loaded globally). */
    _toast(text) {
        let toast = document.getElementById('cfg-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'cfg-toast';
            toast.className = 'cfg-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.classList.add('cfg-toast--visible');
        setTimeout(() => toast.classList.remove('cfg-toast--visible'), 2800);
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.ReticulumSettingsTab = ReticulumSettingsTab;
