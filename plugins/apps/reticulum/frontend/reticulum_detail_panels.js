/**
 * Reticulum plugin: click-to-detail panels for the Peers and Activity
 * tabs -- the Peers drawer and Activity popup, matching Meshtastic/
 * MeshCore's node drawer + packet-detail modal *exactly*, pixel for
 * pixel: this renders the literal core CSS class names
 * (`nd-drawer`/`nd-section`/`nd-row` from node_drawer.css,
 * `pdm-modal`/`pdm-layer`/`pdm-row` from packet_detail_modal.css)
 * rather than a hand-copied approximation. Those class names are just
 * layout/color rules with no protocol-specific behaviour baked in --
 * reusing them is exactly like this plugin already reusing `mt-badge`/
 * `lw-*`/`terminal-button`/`cfg-*` elsewhere, not a special case.
 *
 * What stays plugin-owned is the *markup construction and data* --
 * this never touches `NodeDrawer`/`PacketDetailModal`'s own JS classes
 * or their singleton DOM elements (`#node-drawer`, `#packet-detail-*`).
 * Reticulum peers/announces don't have Meshtastic/MeshCore's shape
 * (source_id/destination_id/decoded_payload, a `packets` table row) --
 * teaching those classes a Reticulum branch would be the same
 * core-grows-a-protocol-special-case problem this app's whole plugin
 * architecture exists to avoid. Own small classes, own DOM, core's
 * existing CSS applied to both -- same visual system, zero shared
 * runtime coupling.
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

// Identical to node_drawer.js's own _hashColor -- same avatar-color
// scheme for the same visual language.
function _rtHashColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    return `hsl(${Math.abs(hash) % 360}, 55%, 45%)`;
}

/** One collapsible `.nd-section` (node_drawer.css), populated with
 * plain `.nd-row` label/value pairs -- same shell + toggle behaviour as
 * NodeDrawer's own `_buildSection`. `rows` entries with a null/empty
 * value are dropped; an empty section shows the same "No data
 * available" placeholder NodeDrawer uses. `value` is inserted as HTML
 * (callers are responsible for escaping plain text themselves via
 * `_rtEsc`) so a caller can pass a badge or other markup through. */
function _rtSection(title, rows, expanded) {
    const kept = rows.filter((r) => r.value != null && r.value !== '');

    const section = document.createElement('div');
    section.className = 'nd-section';

    const header = document.createElement('div');
    header.className = 'nd-section__header';
    header.innerHTML = `<span class="nd-section__title">${_rtEsc(title)}</span>
        <span class="nd-section__arrow">${expanded ? '▼' : '▶'}</span>`;

    const content = document.createElement('div');
    content.className = 'nd-section__content';
    if (!kept.length) {
        content.innerHTML = '<div class="nd-section__empty">No data available</div>';
    } else {
        kept.forEach(({ label, value }) => {
            const row = document.createElement('div');
            row.className = 'nd-row';
            row.innerHTML = `<span class="nd-row__label">${_rtEsc(label)}</span>
                <span class="nd-row__value">${value}</span>`;
            content.appendChild(row);
        });
    }
    content.style.display = expanded ? '' : 'none';

    header.addEventListener('click', () => {
        const visible = content.style.display !== 'none';
        content.style.display = visible ? 'none' : '';
        header.querySelector('.nd-section__arrow').textContent = visible ? '▶' : '▼';
    });

    section.appendChild(header);
    section.appendChild(content);
    return section;
}

/** Right-side slide-in panel for a single Peers-tab row -- same
 * `nd-drawer`/`nd-header`/`nd-section` chrome as the Meshtastic/
 * MeshCore node drawer. */
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
        this._peer = peer;
        this._recentAnnounces = recentAnnounces || [];
        this._opts = opts;
        const token = ++this._openToken;

        const backdrop = document.createElement('div');
        backdrop.className = 'nd-backdrop';
        backdrop.addEventListener('click', () => this.close());

        const drawer = document.createElement('div');
        drawer.className = 'nd-drawer';
        drawer.addEventListener('click', (e) => e.stopPropagation());

        const name = _rtEsc(peer.display_name || peer.destination_hash);
        const shortLabel = _rtEsc((peer.destination_hash || '').slice(0, 2)).toUpperCase();
        const color = _rtHashColor(peer.destination_hash || '');

        drawer.innerHTML = `
            <div class="nd-header">
                <div class="nd-header__left">
                    <div class="nd-avatar" style="background:${color}">${shortLabel}</div>
                    <div class="nd-header__info">
                        <div class="nd-header__name">${name}</div>
                        <div class="nd-header__id">${_rtEsc(peer.destination_hash)}</div>
                    </div>
                </div>
                <button class="nd-close" title="Close">&times;</button>
            </div>
            <div class="nd-body">
                <div class="nd-loading">Loading routing info…</div>
            </div>
        `;
        drawer.querySelector('.nd-close').addEventListener('click', () => this.close());

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);
        this._backdrop = backdrop;
        this._drawer = drawer;
        requestAnimationFrame(() => {
            backdrop.classList.add('nd-backdrop--visible');
            drawer.classList.add('nd-drawer--open');
        });

        this._renderSections(null);  // identity + recent activity immediately, routing/signal once fetched
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
        this._renderSections(info);
    }

    _renderSections(link) {
        const body = this._drawer?.querySelector('.nd-body');
        if (!body) return;
        const peer = this._peer;
        const opts = this._opts;

        body.innerHTML = '';

        if (peer.aspect === 'nomadnetwork.node' && typeof opts.onBrowse === 'function') {
            const actions = document.createElement('div');
            actions.className = 'nd-actions';
            const browseBtn = document.createElement('button');
            browseBtn.className = 'nd-action-btn nd-action-btn--primary';
            browseBtn.textContent = 'Browse this node';
            browseBtn.addEventListener('click', () => {
                this.close();
                opts.onBrowse(peer.destination_hash);
            });
            actions.appendChild(browseBtn);
            body.appendChild(actions);
        }

        body.appendChild(_rtSection('Identity', [
            { label: 'Destination', value: `<span class="nd-row__value">${_rtEsc(peer.destination_hash)}</span>` },
            { label: 'Aspect', value: _rtAspectBadge(peer.aspect) },
            { label: 'First seen', value: _rtEsc(_rtFullTime(peer.first_seen)) },
            { label: 'Last seen', value: _rtEsc(_rtFullTime(peer.last_seen)) },
        ], true));

        if (link === null) {
            const loading = document.createElement('div');
            loading.className = 'nd-loading';
            loading.textContent = 'Loading routing info…';
            body.appendChild(loading);
        } else if (link) {
            body.appendChild(_rtSection('Routing', [
                { label: 'Hops', value: _rtEsc(link.hops != null ? String(link.hops) : 'unknown') },
                { label: 'Path known', value: _rtEsc(link.has_path ? 'Yes' : 'No') },
                { label: 'Next hop interface', value: link.next_hop_interface ? _rtEsc(link.next_hop_interface) : null },
                { label: 'Identity resolved', value: _rtEsc(link.identity_resolved ? 'Yes' : 'No') },
                { label: 'Announces this session', value: link.announces_this_session ? _rtEsc(String(link.announces_this_session)) : null },
            ], true));

            const hasSignal = link.rssi != null || link.snr != null || link.quality != null;
            if (hasSignal) {
                body.appendChild(_rtSection('Signal (most recent announce)', [
                    { label: 'RSSI', value: link.rssi != null ? `${Number(link.rssi).toFixed(0)} dBm` : null },
                    { label: 'SNR', value: link.snr != null ? `${Number(link.snr).toFixed(1)} dB` : null },
                    { label: 'Quality', value: link.rssi != null ? _rtSignalQuality(link.rssi) : (link.quality != null ? `${link.quality}/100` : null) },
                    { label: 'As of', value: link.signal_at ? _rtEsc(_rtFullTime(link.signal_at)) : null },
                ], true));
            }
        }

        const activitySection = _rtSection('Recent Activity', [], true);
        const activityContent = activitySection.querySelector('.nd-section__content');
        if (!this._recentAnnounces.length) {
            activityContent.innerHTML = '<div class="nd-section__empty">No announces from this peer yet this session.</div>';
        } else {
            activityContent.innerHTML = '';
            this._recentAnnounces.slice(0, 20).forEach((a) => {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'nd-row rt-activity-row';
                const sig = a.rssi != null ? `<span class="nd-row__value">${Number(a.rssi).toFixed(0)} dBm</span>` : '';
                row.innerHTML = `<span class="nd-row__label">${_rtEsc(_rtFullTime(a.ts))}</span> ${_rtAspectBadge(a.aspect)} ${sig}`;
                row.addEventListener('click', () => {
                    if (this._onViewAnnounce) this._onViewAnnounce(a);
                });
                activityContent.appendChild(row);
            });
        }
        body.appendChild(activitySection);
    }

    close() {
        if (this._drawer) { this._drawer.remove(); this._drawer = null; }
        if (this._backdrop) { this._backdrop.remove(); this._backdrop = null; }
    }
}

/** Center modal with one Activity-tab announce's full detail -- same
 * `pdm-overlay`/`pdm-modal`/`pdm-layer` chrome as the Meshtastic/
 * MeshCore packet-detail modal. */
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
        overlay.className = 'pdm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Announce detail');
        overlay.addEventListener('click', () => this.close());

        const modal = document.createElement('div');
        modal.className = 'pdm-modal';
        modal.addEventListener('click', (e) => e.stopPropagation());

        modal.innerHTML = `
            <header class="pdm-modal__header">
                <div>
                    <h2 class="pdm-modal__title">Announce detail</h2>
                    <div class="pdm-modal__meta">${_rtEsc(_rtFullTime(entry.ts))}</div>
                </div>
                <button type="button" class="pdm-modal__close" aria-label="Close">&times;</button>
            </header>
            <div class="pdm-modal__body"></div>
        `;

        const body = modal.querySelector('.pdm-modal__body');
        for (const layer of [
            this._buildLayer('Routing', [
                { key: 'Destination', val: entry.destination_hash },
                { key: 'Aspect', val: entry.aspect, html: () => _rtAspectBadge(entry.aspect) },
            ]),
            this._buildSignalLayer(entry),
            this._buildPayloadLayer(entry),
        ]) {
            if (layer) body.appendChild(layer);
        }

        if (opts.knownPeer && typeof opts.onViewPeer === 'function') {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'terminal-button rt-amodal__view-peer';
            btn.textContent = 'View peer';
            btn.addEventListener('click', () => {
                this.close();
                opts.onViewPeer(entry.destination_hash);
            });
            body.appendChild(btn);
        }

        modal.querySelector('.pdm-modal__close').addEventListener('click', () => this.close());
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;
        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.pdm-modal__close').focus();
    }

    _buildSignalLayer(entry) {
        const hasSignal = entry.rssi != null || entry.snr != null || entry.quality != null;
        if (!hasSignal) return null;
        return this._buildLayer('Signal', [
            { key: 'RSSI', val: entry.rssi != null ? `${Number(entry.rssi).toFixed(0)} dBm` : null },
            { key: 'SNR', val: entry.snr != null ? `${Number(entry.snr).toFixed(1)} dB` : null },
            { key: 'Quality', val: entry.rssi != null ? _rtSignalQuality(entry.rssi) : (entry.quality != null ? `${entry.quality}/100` : null) },
        ]);
    }

    _buildPayloadLayer(entry) {
        const rows = [{ key: 'Display name', val: entry.display_name || '--' }];
        if (entry.app_data_hex) {
            rows.push({ key: 'App data (hex)', expandable: true, full: entry.app_data_hex, previewLen: 120 });
        }
        return this._buildLayer('Payload', rows);
    }

    /** Mirrors packet_detail_modal.js's own _buildLayer/_row/
     * _expandableBlock -- same class names, same "drop the layer if
     * every row was empty" behaviour. */
    _buildLayer(label, rows) {
        const rowsEl = document.createElement('div');
        rowsEl.className = 'pdm-layer__rows';
        for (const row of rows) {
            if (row.expandable) {
                rowsEl.appendChild(this._expandableRow(row.key, row.full, row.previewLen));
                continue;
            }
            if (row.val == null || row.val === '') continue;
            rowsEl.appendChild(this._row(row.key, row.html ? row.html() : _rtEsc(row.val), !!row.html));
        }
        if (!rowsEl.children.length) return null;

        const layer = document.createElement('section');
        layer.className = 'pdm-layer';
        layer.innerHTML = `<div class="pdm-layer__label">${_rtEsc(label)}</div>`;
        layer.appendChild(rowsEl);
        return layer;
    }

    _row(key, val, isHtml) {
        const row = document.createElement('div');
        row.className = 'pdm-row';
        row.innerHTML = `
            <span class="pdm-row__key">${_rtEsc(key)}:</span>
            <span class="pdm-row__val">${isHtml ? val : val}</span>
        `;
        return row;
    }

    _expandableRow(key, fullText, previewLen) {
        const wrap = document.createElement('div');
        wrap.className = 'pdm-row';
        const needsToggle = fullText.length > previewLen;
        const preview = needsToggle ? fullText.slice(0, previewLen) + '…' : fullText;

        const keySpan = document.createElement('span');
        keySpan.className = 'pdm-row__key';
        keySpan.textContent = `${key}:`;

        const pre = document.createElement('pre');
        pre.className = 'pdm-payload-text';
        pre.textContent = preview;

        wrap.appendChild(keySpan);
        wrap.appendChild(pre);

        if (needsToggle) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'pdm-expand';
            btn.textContent = 'Show more';
            let expanded = false;
            btn.addEventListener('click', () => {
                expanded = !expanded;
                pre.textContent = expanded ? fullText : preview;
                btn.textContent = expanded ? 'Show less' : 'Show more';
            });
            wrap.appendChild(btn);
        }
        return wrap;
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
