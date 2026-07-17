/**
 * Meshpoint status card.
 *
 * A single self-contained custom element, no build step and no
 * framework dependency -- matches the plain-JS style the rest of
 * Meshpoint's own dashboard frontend uses (frontend/js/*.js).
 *
 * Groups every entity belonging to one Meshpoint device (as created by
 * the homeassistant/custom_components/meshpoint integration) into a
 * status header, a stats grid, a signal section, and a relay section --
 * matching known entity names from metric_meta.py. Anything not
 * recognized (a metric Meshpoint adds later, before this card's lookup
 * table is updated for it) still renders, grouped into a generic "More"
 * grid at the bottom, so new stats show up without needing this file
 * to catch up first.
 *
 * Config (YAML card, no visual editor yet):
 *   type: custom:meshpoint-card
 *   entity: sensor.meshpoint_<...>_uptime   # any one entity on the device
 * or:
 *   type: custom:meshpoint-card
 *   device_id: <ha device registry id>
 */

const KNOWN_SECTIONS = {
    header: new Set(['Uptime', 'Nodes Known', 'Nodes Active (24h)']),
    stats: new Set([
        'Packets (Last Hour)', 'Packets (Last Minute)', 'Packet Rate',
        'Packets Stored', 'Session Packets',
        'Direct Packets (Session)', 'Relayed Packets (Session)',
    ]),
    protocol: new Set([
        'Meshtastic Packets (Session)', 'MeshCore Packets (Session)',
        'LoRaWAN Packets (Session)',
    ]),
    signal: new Set([
        'RSSI (Recent Average)', 'SNR (Recent Average)',
        'RSSI (Session Average)', 'SNR (Session Average)', 'Noise Floor',
    ]),
    relay: new Set([
        'Relay Enabled', 'Packets Relayed', 'Packets Rejected By Relay',
        'Relay Rate', 'Relay Rate Remaining', 'Relay Duty Usage',
    ]),
    diagnostic: new Set([
        'Noise Floor Stale', 'CRC Bad Frames', 'No-CRC Frames',
    ]),
};

function formatUptime(seconds) {
    const s = Number(seconds);
    if (!Number.isFinite(s) || s < 0) return '--';
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function formatNumber(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return value;
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

class MeshpointCard extends HTMLElement {
    setConfig(config) {
        if (!config || (!config.entity && !config.device_id)) {
            throw new Error(
                'meshpoint-card: set "entity" (any one Meshpoint sensor) or "device_id"'
            );
        }
        this._config = config;
        this._deviceId = config.device_id || null;
        if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    }

    set hass(hass) {
        this._hass = hass;
        if (!this._deviceId && this._config.entity) {
            const entry = hass.entities && hass.entities[this._config.entity];
            this._deviceId = entry ? entry.device_id : null;
        }
        this._render();
    }

    getCardSize() {
        return 6;
    }

    static getStubConfig(hass) {
        const entities = (hass && hass.entities) || {};
        const match = Object.values(entities).find((e) => e.platform === 'meshpoint');
        return match ? { entity: match.entity_id } : { entity: '' };
    }

    _collectEntities() {
        const hass = this._hass;
        if (!hass || !hass.entities || !this._deviceId) return [];
        return Object.values(hass.entities)
            .filter((e) => e.device_id === this._deviceId)
            .map((e) => {
                const state = hass.states[e.entity_id];
                return {
                    entityId: e.entity_id,
                    name: e.name || e.original_name || e.entity_id,
                    state: state ? state.state : undefined,
                    unit: state ? state.attributes.unit_of_measurement : undefined,
                    available: !!state && state.state !== 'unavailable' && state.state !== 'unknown',
                };
            });
    }

    _render() {
        if (!this.shadowRoot) return;

        const items = this._collectEntities();
        if (items.length === 0) {
            this.shadowRoot.innerHTML = `
                <ha-card>
                    <div class="mp-empty">
                        ${this._deviceId
                            ? 'No entities found for this Meshpoint device yet.'
                            : 'Set "entity" to any Meshpoint sensor, or "device_id", in the card config.'}
                    </div>
                </ha-card>
                <style>${this._style()}</style>
            `;
            return;
        }

        const byName = new Map(items.map((i) => [i.name, i]));
        const bucketed = new Set();
        const bucket = (names) => {
            const found = [];
            for (const name of names) {
                const item = byName.get(name);
                if (item) {
                    found.push(item);
                    bucketed.add(item.name);
                }
            }
            return found;
        };

        const header = bucket(KNOWN_SECTIONS.header);
        const stats = bucket(KNOWN_SECTIONS.stats);
        const protocol = bucket(KNOWN_SECTIONS.protocol);
        const signal = bucket(KNOWN_SECTIONS.signal);
        const relay = bucket(KNOWN_SECTIONS.relay);
        const diagnostic = bucket(KNOWN_SECTIONS.diagnostic);
        const more = items.filter((i) => !bucketed.has(i.name));

        const uptimeItem = byName.get('Uptime');
        const online = uptimeItem ? uptimeItem.available : items.some((i) => i.available);
        const nodesItem = byName.get('Nodes Known');

        this.shadowRoot.innerHTML = `
            <ha-card>
                <div class="mp-card">
                    <div class="mp-header">
                        <div class="mp-status">
                            <span class="mp-dot ${online ? 'mp-dot--on' : 'mp-dot--off'}"></span>
                            <span>${online ? 'Online' : 'Offline'}</span>
                        </div>
                        ${nodesItem
                            ? `<span class="mp-chip">${this._esc(formatNumber(nodesItem.state))} Nodes</span>`
                            : ''}
                    </div>
                    <div class="mp-title">Meshpoint</div>

                    ${this._section('', this._tileRow([
                        ...(uptimeItem ? [{ label: 'Uptime', value: formatUptime(uptimeItem.state) }] : []),
                        ...stats.map((i) => ({ label: i.name, value: this._fmt(i) })),
                    ]))}

                    ${protocol.length ? this._section('Protocols', this._tileRow(
                        protocol.map((i) => ({ label: i.name.replace(' Packets (Session)', ''), value: this._fmt(i) }))
                    )) : ''}

                    ${signal.length ? this._section('Signal', this._tileRow(
                        signal.map((i) => ({ label: i.name, value: this._fmt(i) }))
                    )) : ''}

                    ${relay.length ? this._section('Relay', this._tileRow(
                        relay.map((i) => ({ label: i.name, value: this._fmt(i) }))
                    )) : ''}

                    ${more.length ? this._section('More', this._tileRow(
                        more.map((i) => ({ label: i.name, value: this._fmt(i) }))
                    )) : ''}

                    ${diagnostic.length ? `<div class="mp-diagnostic">${diagnostic
                        .map((i) => `${this._esc(i.name)}: ${this._esc(this._fmt(i))}`)
                        .join(' · ')}</div>` : ''}
                </div>
            </ha-card>
            <style>${this._style()}</style>
        `;
    }

    _fmt(item) {
        if (item.state === undefined) return '--';
        const value = formatNumber(item.state);
        return item.unit ? `${value} ${item.unit}` : `${value}`;
    }

    _tileRow(tiles) {
        return tiles
            .map(
                (t) => `
                    <div class="mp-tile">
                        <div class="mp-tile__value">${this._esc(t.value)}</div>
                        <div class="mp-tile__label">${this._esc(t.label)}</div>
                    </div>
                `
            )
            .join('');
    }

    _section(title, tilesHtml) {
        return `
            <div class="mp-section">
                ${title ? `<div class="mp-section__title">${this._esc(title)}</div>` : ''}
                <div class="mp-grid">${tilesHtml}</div>
            </div>
        `;
    }

    _esc(value) {
        const div = document.createElement('div');
        div.textContent = value === undefined || value === null ? '' : String(value);
        return div.innerHTML;
    }

    _style() {
        return `
            ha-card { padding: 0; }
            .mp-card { padding: 16px; }
            .mp-empty {
                padding: 16px;
                color: var(--secondary-text-color);
                font-size: 0.9em;
            }
            .mp-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 4px;
            }
            .mp-status {
                display: flex;
                align-items: center;
                gap: 6px;
                font-size: 0.85em;
                color: var(--secondary-text-color);
            }
            .mp-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                display: inline-block;
            }
            .mp-dot--on { background: var(--success-color, #43a047); }
            .mp-dot--off { background: var(--error-color, #db4437); }
            .mp-chip {
                font-size: 0.8em;
                padding: 2px 10px;
                border-radius: 999px;
                border: 1px solid var(--divider-color);
                color: var(--secondary-text-color);
            }
            .mp-title {
                font-size: 1.3em;
                font-weight: 600;
                color: var(--primary-text-color);
                margin-bottom: 12px;
            }
            .mp-section {
                margin-top: 14px;
            }
            .mp-section__title {
                font-size: 0.75em;
                font-weight: 600;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                color: var(--secondary-text-color);
                margin-bottom: 8px;
                padding-bottom: 4px;
                border-bottom: 1px solid var(--divider-color);
            }
            .mp-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
                gap: 10px;
            }
            .mp-tile {
                background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
                border-radius: 10px;
                padding: 8px 10px;
            }
            .mp-tile__value {
                font-size: 1.05em;
                font-weight: 600;
                color: var(--primary-text-color);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .mp-tile__label {
                font-size: 0.72em;
                color: var(--secondary-text-color);
                margin-top: 2px;
            }
            .mp-diagnostic {
                margin-top: 12px;
                font-size: 0.72em;
                color: var(--secondary-text-color);
                opacity: 0.8;
            }
        `;
    }
}

customElements.define('meshpoint-card', MeshpointCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'meshpoint-card',
    name: 'Meshpoint Card',
    description: 'Status card for a Meshpoint gateway: uptime, packets, nodes, signal, relay stats.',
});
