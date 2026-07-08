/**
 * Radio tab — SX1302 Concentrator Channels card (observational).
 *
 * Read-only table of the full 9-slot concentrator plan the capture
 * source runs: per channel frequency, bandwidth, SF, sync word,
 * protocol, RF chain, and enabled state. Data comes from the
 * ``concentrator`` block of GET /api/config (rebuilt server-side with
 * the same call the capture source makes). Hidden when the box has no
 * concentrator source configured.
 */
class RadioConcentratorCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        rootEl.style.display = 'none';
    }

    render(config) {
        const conc = (config && config.concentrator) || {};
        const channels = conc.channels || [];
        if (!conc.active || !channels.length) {
            this._root.style.display = 'none';
            return;
        }
        this._root.style.display = '';

        const rows = channels.map((ch) => {
            const sf = ch.spreading_factor
                ? `SF${ch.spreading_factor}`
                : 'SF7–12';
            const proto = ch.protocol === 'meshtastic' ? 'Meshtastic' : 'LoRaWAN';
            const stateClass = ch.enabled
                ? 'ch-table__pill ch-table__pill--on'
                : 'ch-table__pill ch-table__pill--off';
            const dim = ch.enabled ? '' : ' style="opacity:0.45"';
            return `
                <tr class="ch-table__row"${dim}>
                    <td class="ch-table__idx">${ch.ch}</td>
                    <td class="ch-table__hash">${ch.frequency_mhz.toFixed(3)}</td>
                    <td class="ch-table__hash">${ch.bandwidth_khz} kHz</td>
                    <td class="ch-table__hash">${sf}</td>
                    <td class="ch-table__hash">${this._esc(ch.syncword)}</td>
                    <td class="ch-table__name">${ch.enabled ? proto : '—'}</td>
                    <td class="ch-table__idx">RF${ch.rf_chain}</td>
                    <td><span class="${stateClass}">${ch.enabled ? 'On' : 'Off'}</span></td>
                </tr>
            `;
        }).join('');

        const onCount = channels.filter((c) => c.enabled).length;
        const rf = (conc.radio_0_mhz != null && conc.radio_1_mhz != null)
            ? ` · RF0 ${conc.radio_0_mhz} / RF1 ${conc.radio_1_mhz} MHz`
            : '';

        this._root.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Concentrator Channels</h3>
                <span class="r-card__subtitle">
                    SX1302 · ${onCount} of ${channels.length} on${rf}
                </span>
            </div>
            <table class="ch-table ch-table--readout">
                <thead>
                    <tr>
                        <th>CH</th>
                        <th>Freq (MHz)</th>
                        <th>BW</th>
                        <th>SF</th>
                        <th>Sync</th>
                        <th>Protocol</th>
                        <th>RF</th>
                        <th>State</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <a class="r-config-link" href="#/configuration/radio">
                <span>Region &amp; frequency settings</span>
                <span aria-hidden="true">→</span>
            </a>
        `;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.RadioConcentratorCard = RadioConcentratorCard;
