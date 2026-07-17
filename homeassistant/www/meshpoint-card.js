/**
 * Meshpoint cards.
 *
 * Three self-contained custom elements from one file, no build step, no
 * framework dependency -- matches the plain-JS style the rest of
 * Meshpoint's own dashboard frontend uses (frontend/js/*.js). One
 * resource install (www/meshpoint-card.js + a Lovelace resource entry)
 * gives you three card types to pick from in Add Card:
 *
 *   custom:meshpoint-card           Status -- online, node count, uptime,
 *                                   packet rate, protocol split, signal,
 *                                   relay. The at-a-glance one.
 *   custom:meshpoint-health-card    Host health -- CPU/RAM/disk/temp/fan.
 *   custom:meshpoint-insights-card  Records -- best signal ever, farthest
 *                                   contact, node role distribution.
 *
 * Split into three instead of one mega-card because the integration now
 * polls three Meshpoint endpoints (~140 entities total) -- mixing mesh
 * stats, host health, and historical records into one card made it an
 * unreadable wall of tiles. Each card only pulls in the entities that
 * belong to it (see classifyEntity below); anything not yet curated for
 * a given card still shows up in a "More" grid there, grouped by
 * whichever source it came from, so a metric Meshpoint adds later is
 * never silently dropped -- just not pretty until metric_meta.py catches
 * up. High-cardinality data (raw hardware-model codes, the 14-way packet-
 * type breakdown) is deliberately left out of all three cards -- those
 * numeric codes aren't meaningful as tiles; Meshpoint's own Stats page
 * already charts them properly. Still available as plain HA entities for
 * anyone who wants to build their own automation/card on them.
 *
 * Config (YAML card, no visual editor yet), same for all three types:
 *   type: custom:meshpoint-card
 *   entity: sensor.meshpoint_<...>_uptime   # any one entity on the device
 * or:
 *   type: custom:meshpoint-card
 *   device_id: <ha device registry id>
 */

const STATUS_SECTIONS = {
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

const HEALTH_SECTIONS = {
    main: new Set([
        'CPU Usage', 'CPU Temperature', 'Memory Usage', 'Memory Used',
        'Disk Usage', 'Disk Used', 'System Uptime', 'Fan Duty',
    ]),
};

const INSIGHTS_SECTIONS = {
    records: new Set(['Best RSSI Ever', 'Best SNR Ever', 'First Packet Ever Heard']),
    farthest: new Set([
        'Farthest Relayed Contact', 'Farthest Relayed Contact Name',
        'Farthest MeshCore Contact', 'Farthest MeshCore Contact Name',
    ]),
    roles: new Set([
        'Client Nodes', 'Router Nodes', 'Repeater Nodes',
        'Client (Mute) Nodes', 'Nodes With Position',
    ]),
};

function allNames(sections) {
    const out = new Set();
    for (const set of Object.values(sections)) {
        for (const name of set) out.add(name);
    }
    return out;
}

const STATUS_NAMES = allNames(STATUS_SECTIONS);
const HEALTH_NAMES = allNames(HEALTH_SECTIONS);
const INSIGHTS_NAMES = allNames(INSIGHTS_SECTIONS);

/**
 * Which card an entity belongs to. Curated names are matched exactly;
 * uncurated (fallback-named) entities from the two JSON endpoints keep
 * their "Device "/"Stats " prefix (see metric_meta.py's fallback()), so
 * they route correctly even without being in a curated set yet.
 * Uncurated /metrics fallback names have no prefix marker and default to
 * the status card, matching this integration's original behavior.
 */
function classifyEntity(name) {
    if (HEALTH_NAMES.has(name) || name.startsWith('Device ')) return 'health';
    if (INSIGHTS_NAMES.has(name) || name.startsWith('Stats ')) return 'insights';
    return 'status';
}

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

/**
 * Shared plumbing for all three card types: config, hass wiring, entity
 * collection/classification, tile rendering, and CSS. Subclasses provide
 * `_kind` (which classifyEntity() bucket they render) and `_renderBody()`.
 */
class MeshpointCardBase extends HTMLElement {
    setConfig(config) {
        if (!config || (!config.entity && !config.device_id)) {
            throw new Error(
                `${this._cardLabel()}: set "entity" (any one Meshpoint sensor) or "device_id"`
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
        return 4;
    }

    static getStubConfig(hass) {
        const entities = (hass && hass.entities) || {};
        const match = Object.values(entities).find((e) => e.platform === 'meshpoint');
        return match ? { entity: match.entity_id } : { entity: '' };
    }

    _cardLabel() {
        return 'meshpoint-card';
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
            })
            .filter((item) => classifyEntity(item.name) === this._kind);
    }

    _render() {
        if (!this.shadowRoot) return;

        const items = this._collectEntities();
        if (items.length === 0) {
            this.shadowRoot.innerHTML = `
                <ha-card>
                    <div class="mp-empty">
                        ${this._deviceId
                            ? `No ${this._cardLabel()} entities found on this Meshpoint device yet.`
                            : 'Set "entity" to any Meshpoint sensor, or "device_id", in the card config.'}
                    </div>
                </ha-card>
                <style>${this._style()}</style>
            `;
            return;
        }

        this.shadowRoot.innerHTML = `
            <ha-card>
                <div class="mp-card">
                    ${this._renderBody(items)}
                </div>
            </ha-card>
            <style>${this._style()}</style>
        `;
    }

    _bucket(items, sections) {
        const byName = new Map(items.map((i) => [i.name, i]));
        const bucketed = new Set();
        const out = {};
        for (const [section, names] of Object.entries(sections)) {
            const found = [];
            for (const name of names) {
                const item = byName.get(name);
                if (item) {
                    found.push(item);
                    bucketed.add(item.name);
                }
            }
            out[section] = found;
        }
        out.more = items.filter((i) => !bucketed.has(i.name));
        return out;
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
        if (!tilesHtml) return '';
        return `
            <div class="mp-section">
                ${title ? `<div class="mp-section__title">${this._esc(title)}</div>` : ''}
                <div class="mp-grid">${tilesHtml}</div>
            </div>
        `;
    }

    _esc(str) {
        const div = document.createElement('span');
        div.textContent = str === undefined || str === null ? '' : String(str);
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
            .mp-section:first-child {
                margin-top: 0;
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

class MeshpointStatusCard extends MeshpointCardBase {
    _kind = 'status';

    _cardLabel() {
        return 'Meshpoint status';
    }

    _renderBody(items) {
        const b = this._bucket(items, STATUS_SECTIONS);
        const byName = new Map(items.map((i) => [i.name, i]));
        const uptimeItem = byName.get('Uptime');
        const nodesItem = byName.get('Nodes Known');
        const online = uptimeItem ? uptimeItem.available : items.some((i) => i.available);

        return `
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
                ...b.stats.map((i) => ({ label: i.name, value: this._fmt(i) })),
            ]))}

            ${this._section('Protocols', this._tileRow(
                b.protocol.map((i) => ({ label: i.name.replace(' Packets (Session)', ''), value: this._fmt(i) }))
            ))}

            ${this._section('Signal', this._tileRow(
                b.signal.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}

            ${this._section('Relay', this._tileRow(
                b.relay.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}

            ${this._section('More', this._tileRow(
                b.more.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}

            ${b.diagnostic.length ? `<div class="mp-diagnostic">${b.diagnostic
                .map((i) => `${this._esc(i.name)}: ${this._esc(this._fmt(i))}`)
                .join(' · ')}</div>` : ''}
        `;
    }
}

class MeshpointHealthCard extends MeshpointCardBase {
    _kind = 'health';

    _cardLabel() {
        return 'Meshpoint host health';
    }

    _renderBody(items) {
        const b = this._bucket(items, HEALTH_SECTIONS);
        return `
            <div class="mp-title">Meshpoint Host</div>
            ${this._section('', this._tileRow(
                b.main.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}
            ${this._section('More', this._tileRow(
                b.more.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}
        `;
    }
}

class MeshpointInsightsCard extends MeshpointCardBase {
    _kind = 'insights';

    _cardLabel() {
        return 'Meshpoint insights';
    }

    _renderBody(items) {
        const b = this._bucket(items, INSIGHTS_SECTIONS);
        return `
            <div class="mp-title">Meshpoint Insights</div>
            ${this._section('Best Ever', this._tileRow(
                b.records.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}
            ${this._section('Farthest Contacts', this._tileRow(
                b.farthest.map((i) => ({ label: i.name.replace('Farthest ', ''), value: this._fmt(i) }))
            ))}
            ${this._section('Node Roles', this._tileRow(
                b.roles.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}
            ${this._section('More', this._tileRow(
                b.more.map((i) => ({ label: i.name, value: this._fmt(i) }))
            ))}
        `;
    }
}

customElements.define('meshpoint-card', MeshpointStatusCard);
customElements.define('meshpoint-health-card', MeshpointHealthCard);
customElements.define('meshpoint-insights-card', MeshpointInsightsCard);

window.customCards = window.customCards || [];
window.customCards.push(
    {
        type: 'meshpoint-card',
        name: 'Meshpoint Status',
        description: 'At-a-glance Meshpoint status: online, nodes, uptime, packets, protocols, signal, relay.',
    },
    {
        type: 'meshpoint-health-card',
        name: 'Meshpoint Host Health',
        description: 'Meshpoint host system health: CPU, memory, disk, temperature, fan.',
    },
    {
        type: 'meshpoint-insights-card',
        name: 'Meshpoint Insights',
        description: 'Best signal ever, farthest contact, and node role distribution.',
    },
);
