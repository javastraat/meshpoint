/**
 * Reticulum plugin: click-to-detail panels for the Peers and Activity
 * tabs, added for parity with Meshtastic/MeshCore's node-drawer +
 * packet-detail-modal pattern (frontend/js/node_drawer.js,
 * frontend/js/packet_detail_modal.js).
 *
 * Restyled (2026-09-08) to match core's PacketDetailModal visual
 * language -- uppercase labelled layers, key/value rows
 * (`packet_detail_modal.css`'s `.pdm-layer`/`.pdm-row`) -- once real
 * per-announce RSSI/SNR/quality and live per-peer hop/path/identity
 * data became available (see lxmf_service.py's `_on_announce`/
 * `peer_link_info()`), the same layered look genuinely fits: this
 * isn't a fake RF-packet-shaped view forced onto thin data anymore,
 * it's the same kind of RF + routing + payload breakdown Meshtastic/
 * MeshCore already show, just sourced from RNS/LXMF instead of a
 * captured packet. Still deliberately its own component, not a
 * `protocol === 'reticulum'` branch inside packet_detail_modal.js --
 * an announce/peer's fields (aspect, hops, path, identity) don't map
 * onto that modal's source_id/destination_id/decoded_payload shape,
 * and it's the same core-stays-generic reasoning as every other
 * plugin extraction this app has done. Own CSS (`rt-pdm-*` classes in
 * reticulum.css) mirrors `packet_detail_modal.css`'s class shapes
 * without importing or editing that core file.
 */

function _rtEsc(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function _rtFullTime(ts) {
    if (!ts) return '--';
    try {
        return new Date(ts).toLocaleString([], { hour12: false });
    } catch (_) { return ts; }
}

// Duplicated from reticulum_panel.js's own RT_ASPECT_BADGES (a top-level
// `const` there, not a window property, so not reachable from here) --
// four entries, not worth a cross-file export for.
const _RT_ASPECT_BADGES = {
    'lxmf.delivery': 'mt-badge--text',
    'lxmf.propagation': 'mt-badge--routing',
    'nomadnetwork.node': 'mt-badge--nodeinfo',
    'call.audio': 'mt-badge--routing',
};

function _rtAspectBadge(aspect) {
    const cls = _RT_ASPECT_BADGES[aspect] || '';
    return `<span class="mt-badge ${cls}">${_rtEsc(aspect || '--')}</span>`;
}

// Same tier breaks as node_drawer.js's _signalQuality() -- same physical
// quantity (LoRa RSSI in dBm), same meaning, so the same thresholds.
function _rtSignalQuality(rssi) {
    if (rssi > -80) return 'Excellent';
    if (rssi >= -100) return 'Good';
    if (rssi >= -115) return 'Fair';
    return 'Poor';
}

/** One `.rt-pdm-layer` section: a label + a list of rows. Rows with a
 * null/empty value are dropped (never printed as blank); the whole
 * layer is omitted if every row was dropped, matching
 * packet_detail_modal.js's own "drop the layer if nothing to show"
 * behaviour (e.g. no Signal section at all for a TCP-heard peer). */
function _rtLayer(label, rows) {
    const rowsHtml = rows
        .filter((r) => r.val != null && r.val !== '')
        .map((r) => `
            <div class="rt-pdm-row">
                <span class="rt-pdm-row__key">${_rtEsc(r.key)}:</span>
                <span class="rt-pdm-row__val${r.cls ? ` rt-pdm-row__val--${r.cls}` : ''}">${r.html ? r.val : _rtEsc(r.val)}</span>
            </div>
        `)
        .join('');
    if (!rowsHtml) return '';
    return `
        <section class="rt-pdm-layer">
            <div class="rt-pdm-layer__label">${_rtEsc(label)}</div>
            <div class="rt-pdm-layer__rows">${rowsHtml}</div>
        </section>
    `;
}

function _rtExpandableRow(key, fullText, previewLen) {
    const needsToggle = fullText.length > previewLen;
    const preview = needsToggle ? fullText.slice(0, previewLen) + '…' : fullText;
    return `
        <div class="rt-pdm-row rt-pdm-row--block">
            <span class="rt-pdm-row__key">${_rtEsc(key)}:</span>
            <pre class="rt-pdm-payload-text">${_rtEsc(preview)}</pre>
            ${needsToggle ? `<button type="button" class="rt-pdm-expand" data-rt-expand>Show more</button>` : ''}
        </div>
    `;
}

function _wireExpandableRows(root, fullTextByIndex) {
    root.querySelectorAll('[data-rt-expand]').forEach((btn, i) => {
        const pre = btn.previousElementSibling;
        const full = fullTextByIndex[i];
        let expanded = false;
        btn.addEventListener('click', () => {
            expanded = !expanded;
            pre.textContent = expanded ? full.full : full.preview;
            btn.textContent = expanded ? 'Show less' : 'Show more';
        });
    });
}

/** Right-side slide-in panel for a single Peers-tab row. */
class ReticulumPeerDrawer {
    constructor() {
        this._backdrop = null;
        this._drawer = null;
        this._onViewAnnounce = null;
        this._openToken = 0;
    }

    /**
     * @param {object} peer -- {destination_hash, display_name, aspect, first_seen, last_seen}
     * @param {object[]} recentAnnounces -- this peer's own entries from the Activity ring buffer, newest first
     * @param {{onBrowse?: function, onViewAnnounce?: function}} opts
     */
    open(peer, recentAnnounces, opts = {}) {
        this.close();
        this._onViewAnnounce = opts.onViewAnnounce || null;
        const token = ++this._openToken;

        const backdrop = document.createElement('div');
        backdrop.className = 'rt-drawer-backdrop';
        backdrop.addEventListener('click', () => this.close());

        const drawer = document.createElement('div');
        drawer.className = 'rt-drawer';
        drawer.addEventListener('click', (e) => e.stopPropagation());

        const showBrowse = peer.aspect === 'nomadnetwork.node' && typeof opts.onBrowse === 'function';

        const identityLayer = _rtLayer('Identity', [
            { key: 'Destination', val: peer.destination_hash, cls: 'mono' },
            { key: 'Aspect', val: _rtAspectBadge(peer.aspect), html: true },
            { key: 'First seen', val: _rtFullTime(peer.first_seen) },
            { key: 'Last seen', val: _rtFullTime(peer.last_seen) },
        ]);

        drawer.innerHTML = `
            <header class="rt-drawer__head">
                <div class="rt-drawer__title">${_rtEsc(peer.display_name || peer.destination_hash)}</div>
                <button type="button" class="rt-drawer__close" aria-label="Close">&times;</button>
            </header>
            <div class="rt-drawer__body">
                ${identityLayer}
                <div data-rt-link-layers>
                    <div class="rt-pdm-loading">Loading routing info…</div>
                </div>
                ${showBrowse ? '<button type="button" class="terminal-button rt-drawer__browse">Browse this node</button>' : ''}
                <div class="rt-drawer__section-title">Recent activity</div>
                <div class="rt-drawer__announces"></div>
            </div>
        `;

        const announcesEl = drawer.querySelector('.rt-drawer__announces');
        if (!recentAnnounces || !recentAnnounces.length) {
            announcesEl.innerHTML = '<p class="lw-empty">No announces from this peer yet this session.</p>';
        } else {
            recentAnnounces.slice(0, 20).forEach((a) => {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'rt-drawer__announce-row';
                const sig = a.rssi != null ? `<span class="lw-time">${Number(a.rssi).toFixed(0)} dBm</span>` : '';
                row.innerHTML = `
                    <span class="lw-time">${_rtEsc(_rtFullTime(a.ts))}</span>
                    ${_rtAspectBadge(a.aspect)}
                    ${sig}
                `;
                row.addEventListener('click', () => {
                    if (this._onViewAnnounce) this._onViewAnnounce(a);
                });
                announcesEl.appendChild(row);
            });
        }

        if (showBrowse) {
            drawer.querySelector('.rt-drawer__browse').addEventListener('click', () => {
                this.close();
                opts.onBrowse(peer.destination_hash);
            });
        }
        drawer.querySelector('.rt-drawer__close').addEventListener('click', () => this.close());

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);
        this._backdrop = backdrop;
        this._drawer = drawer;
        // Next frame, so the transform transition actually plays.
        requestAnimationFrame(() => {
            backdrop.classList.add('rt-drawer-backdrop--visible');
            drawer.classList.add('rt-drawer--open');
        });

        this._fetchLink(peer.destination_hash, token);
    }

    async _fetchLink(destinationHash, token) {
        let info = null;
        try {
            const r = await fetch(
                `/api/reticulum/peers/${encodeURIComponent(destinationHash)}/link`,
                { credentials: 'same-origin' },
            );
            if (r.ok) info = await r.json();
        } catch (_) { /* leave info null -- rendered as unavailable below */ }
        // The drawer may have been closed or reopened on a different peer
        // by the time this resolves -- only render if we're still the
        // open() call that kicked this fetch off.
        if (token !== this._openToken || !this._drawer) return;
        this._renderLink(info);
    }

    _renderLink(info) {
        const target = this._drawer?.querySelector('[data-rt-link-layers]');
        if (!target) return;
        if (!info) {
            target.innerHTML = '<p class="lw-empty">Routing info unavailable.</p>';
            return;
        }

        const routingLayer = _rtLayer('Routing', [
            { key: 'Hops', val: info.hops != null ? String(info.hops) : 'unknown' },
            { key: 'Path known', val: info.has_path ? 'Yes' : 'No', cls: info.has_path ? 'good' : undefined },
            { key: 'Next hop interface', val: info.next_hop_interface },
            { key: 'Identity resolved', val: info.identity_resolved ? 'Yes' : 'No', cls: info.identity_resolved ? 'good' : undefined },
            { key: 'Announces this session', val: info.announces_this_session ? String(info.announces_this_session) : null },
        ]);

        const hasSignal = info.rssi != null || info.snr != null || info.quality != null;
        const signalLayer = hasSignal ? _rtLayer('Signal (most recent announce)', [
            { key: 'RSSI', val: info.rssi != null ? `${Number(info.rssi).toFixed(0)} dBm` : null },
            { key: 'SNR', val: info.snr != null ? `${Number(info.snr).toFixed(1)} dB` : null },
            { key: 'Quality', val: info.rssi != null ? _rtSignalQuality(info.rssi) : (info.quality != null ? `${info.quality}/100` : null) },
            { key: 'As of', val: info.signal_at ? _rtFullTime(info.signal_at) : null },
        ]) : '';

        target.innerHTML = routingLayer + signalLayer;
    }

    close() {
        if (this._drawer) { this._drawer.remove(); this._drawer = null; }
        if (this._backdrop) { this._backdrop.remove(); this._backdrop = null; }
    }
}

/** Center modal with one Activity-tab announce's full detail. */
class ReticulumAnnounceModal {
    constructor() {
        this._overlay = null;
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    /**
     * @param {object} entry -- {ts, destination_hash, display_name, aspect, app_data_hex, rssi, snr, quality}
     * @param {{knownPeer?: boolean, onViewPeer?: function}} opts
     */
    show(entry, opts = {}) {
        this.close();

        const overlay = document.createElement('div');
        overlay.className = 'rt-amodal-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.addEventListener('click', () => this.close());

        const modal = document.createElement('div');
        modal.className = 'rt-amodal';
        modal.addEventListener('click', (e) => e.stopPropagation());

        const routingLayer = _rtLayer('Routing', [
            { key: 'Destination', val: entry.destination_hash, cls: 'mono' },
            { key: 'Aspect', val: _rtAspectBadge(entry.aspect), html: true },
        ]);

        const hasSignal = entry.rssi != null || entry.snr != null || entry.quality != null;
        const signalLayer = hasSignal ? _rtLayer('Signal', [
            { key: 'RSSI', val: entry.rssi != null ? `${Number(entry.rssi).toFixed(0)} dBm` : null },
            { key: 'SNR', val: entry.snr != null ? `${Number(entry.snr).toFixed(1)} dB` : null },
            { key: 'Quality', val: entry.rssi != null ? _rtSignalQuality(entry.rssi) : (entry.quality != null ? `${entry.quality}/100` : null) },
        ]) : '';

        const expandables = [];
        let payloadRows = `<div class="rt-pdm-row"><span class="rt-pdm-row__key">Display name:</span><span class="rt-pdm-row__val">${_rtEsc(entry.display_name || '--')}</span></div>`;
        if (entry.app_data_hex) {
            payloadRows += _rtExpandableRow('App data (hex)', entry.app_data_hex, 120);
            expandables.push({ full: entry.app_data_hex, preview: entry.app_data_hex.slice(0, 120) + (entry.app_data_hex.length > 120 ? '…' : '') });
        }
        const payloadLayer = `
            <section class="rt-pdm-layer">
                <div class="rt-pdm-layer__label">Payload</div>
                <div class="rt-pdm-layer__rows">${payloadRows}</div>
            </section>
        `;

        modal.innerHTML = `
            <header class="rt-amodal__head">
                <div>
                    <h2 class="rt-amodal__title">Announce detail</h2>
                    <div class="rt-amodal__meta">${_rtEsc(_rtFullTime(entry.ts))}</div>
                </div>
                <button type="button" class="rt-amodal__close" aria-label="Close">&times;</button>
            </header>
            <div class="rt-amodal__body">
                ${routingLayer}
                ${signalLayer}
                ${payloadLayer}
                ${opts.knownPeer && typeof opts.onViewPeer === 'function'
                    ? '<button type="button" class="terminal-button rt-amodal__view-peer">View peer</button>'
                    : ''}
            </div>
        `;

        _wireExpandableRows(modal, expandables);

        modal.querySelector('.rt-amodal__close').addEventListener('click', () => this.close());
        const viewPeerBtn = modal.querySelector('.rt-amodal__view-peer');
        if (viewPeerBtn) {
            viewPeerBtn.addEventListener('click', () => {
                this.close();
                opts.onViewPeer(entry.destination_hash);
            });
        }

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;
        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.rt-amodal__close').focus();
    }

    close() {
        document.removeEventListener('keydown', this._onKeyDown);
        if (this._overlay) { this._overlay.remove(); this._overlay = null; }
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') this.close();
    }
}

window.ReticulumPeerDrawer = ReticulumPeerDrawer;
window.ReticulumAnnounceModal = ReticulumAnnounceModal;
