/**
 * Reticulum plugin: click-to-detail panels for the Peers and Activity
 * tabs, added for parity with Meshtastic/MeshCore's node-drawer +
 * packet-detail-modal pattern (frontend/js/node_drawer.js,
 * frontend/js/packet_detail_modal.js).
 *
 * Deliberately NOT built on top of those shared components: NodeDrawer is
 * shaped around Meshtastic/MeshCore node fields (hardware, telemetry,
 * position, /api/packets/by-source) and PacketDetailModal around a
 * captured RF packet (RF/Mesh/Payload/Capture layers, source_id/
 * destination_id, decoded_payload) -- a Reticulum announce has none of
 * that (no RF signal, no packets-table row), it's just
 * {ts, destination_hash, display_name, aspect, app_data_hex}. Forcing it
 * through either shared component would mean a core file growing a
 * reticulum-shaped branch for data that doesn't actually fit. Same
 * "plugin stays self-contained" reasoning already applied to DAPNET/
 * RTL-SDR's own extraction and the curated-sidebar-icon design (see
 * memory/project_m1_meshpoint.md) -- own small components, reusing only
 * the app's existing CSS custom properties for visual consistency.
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

/** Right-side slide-in panel for a single Peers-tab row. */
class ReticulumPeerDrawer {
    constructor() {
        this._backdrop = null;
        this._drawer = null;
        this._onViewAnnounce = null;
    }

    /**
     * @param {object} peer -- {destination_hash, display_name, aspect, first_seen, last_seen}
     * @param {object[]} recentAnnounces -- this peer's own entries from the Activity ring buffer, newest first
     * @param {{onBrowse?: function, onViewAnnounce?: function}} opts
     */
    open(peer, recentAnnounces, opts = {}) {
        this.close();
        this._onViewAnnounce = opts.onViewAnnounce || null;

        const backdrop = document.createElement('div');
        backdrop.className = 'rt-drawer-backdrop';
        backdrop.addEventListener('click', () => this.close());

        const drawer = document.createElement('div');
        drawer.className = 'rt-drawer';
        drawer.addEventListener('click', (e) => e.stopPropagation());

        const showBrowse = peer.aspect === 'nomadnetwork.node' && typeof opts.onBrowse === 'function';

        drawer.innerHTML = `
            <header class="rt-drawer__head">
                <div class="rt-drawer__title">${_rtEsc(peer.display_name || peer.destination_hash)}</div>
                <button type="button" class="rt-drawer__close" aria-label="Close">&times;</button>
            </header>
            <div class="rt-drawer__body">
                <div class="rt-drawer__row"><span>Destination</span><span class="rt-mono">${_rtEsc(peer.destination_hash)}</span></div>
                <div class="rt-drawer__row"><span>Aspect</span><span>${_rtAspectBadge(peer.aspect)}</span></div>
                <div class="rt-drawer__row"><span>First seen</span><span>${_rtEsc(_rtFullTime(peer.first_seen))}</span></div>
                <div class="rt-drawer__row"><span>Last seen</span><span>${_rtEsc(_rtFullTime(peer.last_seen))}</span></div>
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
                row.innerHTML = `
                    <span class="lw-time">${_rtEsc(_rtFullTime(a.ts))}</span>
                    ${_rtAspectBadge(a.aspect)}
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
     * @param {object} entry -- {ts, destination_hash, display_name, aspect, app_data_hex}
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

        const hasAppData = !!entry.app_data_hex;
        modal.innerHTML = `
            <header class="rt-amodal__head">
                <div>
                    <h2 class="rt-amodal__title">Announce detail</h2>
                    <div class="rt-amodal__meta">${_rtEsc(_rtFullTime(entry.ts))}</div>
                </div>
                <button type="button" class="rt-amodal__close" aria-label="Close">&times;</button>
            </header>
            <div class="rt-amodal__body">
                <div class="rt-drawer__row"><span>Display name</span><span>${_rtEsc(entry.display_name || '--')}</span></div>
                <div class="rt-drawer__row"><span>Destination</span><span class="rt-mono">${_rtEsc(entry.destination_hash)}</span></div>
                <div class="rt-drawer__row"><span>Aspect</span><span>${_rtAspectBadge(entry.aspect)}</span></div>
                ${hasAppData ? `
                    <div class="rt-drawer__row rt-drawer__row--block">
                        <span>App data (hex)</span>
                        <pre class="rt-amodal__appdata">${_rtEsc(entry.app_data_hex)}</pre>
                    </div>
                ` : ''}
                ${opts.knownPeer && typeof opts.onViewPeer === 'function'
                    ? '<button type="button" class="terminal-button rt-amodal__view-peer">View peer</button>'
                    : ''}
            </div>
        `;

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
