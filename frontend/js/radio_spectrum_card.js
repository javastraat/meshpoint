/**
 * Radio tab — Band Spectrum card (observational).
 *
 * Draws the latest SX1302 spectral-scan band sweep from
 * ``GET /api/device/spectrum`` as a canvas envelope chart:
 * median level (filled line) and p95 "peak activity" (thin line)
 * per 100 kHz step, with the concentrator/MeshCore channel positions
 * overlaid as dashed markers. Admin "Sweep now" triggers
 * ``POST /api/device/spectrum/sweep``. Card hides itself when the
 * box has no spectral-scan support (no SX1261 path).
 *
 * A sweep with ``units: "db_rel"`` (the SX1302 capture-RAM fallback on
 * boards without an SX1261) carries dB over the noise floor instead of
 * dBm, and only covers part of the band: the axis is left unclamped and
 * labels/legend say "dB over floor". That fallback also offers
 * Calibrate / Reset (``POST``/``DELETE /api/device/spectrum/calibrate``):
 * a saved baseline of the radios' own filter shape that later sweeps
 * subtract, so flat = quiet.
 */
// MeshCore's community default per Meshpoint region (REGION_PRESETS in
// src/cli/meshcore_radio_config.py: EU_UK_NARROW / USA_CANADA). Drawn as
// a faint dotted reference line when this box has no MeshCore radio, so
// a peak there can be read as "probably MeshCore" -- it isn't a channel
// this box monitors.
const MESHCORE_REFERENCE_MHZ = { EU_868: 869.618, US: 910.525 };

class RadioSpectrumCard {
    // Colours resolved live so they track the active theme -- median /
    // peak / per-protocol channel markers, matching the topbar chips.
    _color(key) {
        // Reference marker: MeshCore's colour, drawn faint + dotted.
        if (key === 'meshcore_ref') key = 'meshcore';
        return (window.ChartTheme && window.ChartTheme.series(key))
            || { median: '#06b6d4', peak: '#a855f7', lorawan: '#3b82f6',
                 meshtastic: '#10b981', meshcore: '#f59e0b', pager: '#ef4444' }[key]
            || '#94a3b8';
    }

    constructor(api) {
        this._api = api;
        this._root = null;
        this._sweep = null;
        this._markers = [];
        this._pollTimer = null;
        this._refreshTimer = null;
        this._emptyRetryTimer = null;
        this._calibration = null;
        this._redraw = () => this._draw();
        this._reskin = () => { if (this._root) this._renderLegend(); this._draw(); };
        window.addEventListener('meshpoint:themechange', this._reskin);
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        rootEl.style.display = 'none';
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Band Spectrum</h3>
                <span class="spectrum-actions">
                    <button class="spectrum-btn" type="button" data-sp-cal hidden
                            title="Save the radios' quiet shape as a baseline">Calibrate</button>
                    <button class="spectrum-btn" type="button" data-sp-cal-reset hidden
                            title="Forget the baseline">Reset cal</button>
                    <button class="spectrum-btn" type="button" data-sp-sweep
                            title="Run a sweep now">Sweep now</button>
                </span>
            </div>
            <div class="spectrum-body" data-sp-body>
                <canvas class="spectrum-canvas" data-sp-canvas></canvas>
                <div class="spectrum-tooltip" data-sp-tooltip hidden></div>
                <div class="spectrum-empty" data-sp-empty hidden>
                    No sweep yet — press "Sweep now" or wait for the next
                    automatic sweep.
                </div>
            </div>
            <div class="spectrum-legend" data-sp-legend></div>
        `;
        this._canvas = rootEl.querySelector('[data-sp-canvas]');
        this._tooltip = rootEl.querySelector('[data-sp-tooltip]');

        rootEl.querySelector('[data-sp-sweep]')
            .addEventListener('click', () => this._sweepNow());
        rootEl.querySelector('[data-sp-cal]')
            .addEventListener('click', () => this._calibrate());
        rootEl.querySelector('[data-sp-cal-reset]')
            .addEventListener('click', () => this._resetCalibration());
        window.addEventListener('resize', this._redraw);
        this._canvas.addEventListener('mousemove', (e) => this._onHover(e));
        this._canvas.addEventListener('mouseleave', () => {
            this._tooltip.hidden = true;
        });
    }

    render(config) {
        this._markers = this._buildMarkers(config);
        this._renderLegend();
        this._load();
        this._armAutoRefresh();
    }

    // Median/Peak are always shown (the chart's own data lines always
    // draw when there are points at all). The four channel-marker
    // entries are guarded on whether that protocol actually has a
    // marker in _markers -- e.g. MeshCore's swatch shouldn't appear if
    // no MeshCore radio is configured (mc.frequency_mhz unset), same
    // reasoning for Pager. Without this, the legend claimed a color
    // for a line that was never actually drawn on the chart.
    _isRelative() {
        return !!(this._sweep && this._sweep.units === 'db_rel');
    }

    _renderLegend() {
        const legend = this._root.querySelector('[data-sp-legend]');
        if (!legend) return;
        const present = new Set(this._markers.map((m) => m.protocol));
        const entries = [
            { label: 'Median', color: this._color('median') },
            { label: 'Peak (p95)', color: this._color('peak') },
            { protocol: 'lorawan', label: 'LoRaWAN ch', color: this._color('lorawan') },
            { protocol: 'meshtastic', label: 'Meshtastic', color: this._color('meshtastic') },
            { protocol: 'meshcore', label: 'MeshCore', color: this._color('meshcore') },
            { protocol: 'pager', label: 'Pager', color: this._color('pager') },
            { protocol: 'meshcore_ref', label: 'MeshCore (default, not monitored)',
              color: this._color('meshcore_ref'), dotted: true,
              title: "MeshCore's default frequency for this region. No MeshCore radio "
                  + 'is configured on this box, so a peak here is probably MeshCore traffic.' },
        ];
        legend.innerHTML = entries
            .filter((e) => !e.protocol || present.has(e.protocol))
            .map((e) => `<span${e.title ? ` title="${e.title}"` : ''}><i style="background:${e.color}${
                e.dotted ? ';opacity:0.6' : ''}"></i>${e.label}</span>`)
            .join('')
            + (this._isRelative()
                ? '<span title="SX1302 capture RAM: no SX1261 on this board, so levels are relative and only part of the band is covered">dB over floor · capture RAM'
                    + (this._sweep.calibrated ? ' · calibrated' : ' · uncalibrated')
                    + '</span>'
                : '');
    }

    _buildMarkers(config) {
        const markers = [];
        const conc = (config && config.concentrator) || {};
        (conc.channels || []).forEach((ch) => {
            if (!ch.enabled) return;
            let label;
            if (ch.protocol === 'meshtastic') label = 'MT';
            else if (ch.protocol === 'pager') label = 'PG';
            else label = `L${ch.ch}`;
            markers.push({
                mhz: ch.frequency_mhz,
                protocol: ch.protocol,
                label,
            });
        });
        const mc = config && config.meshcore && config.meshcore.radio;
        if (mc && mc.frequency_mhz) {
            markers.push({
                mhz: Number(mc.frequency_mhz),
                protocol: 'meshcore',
                label: 'MC',
            });
        } else {
            const region = config && config.radio && config.radio.region;
            const ref = MESHCORE_REFERENCE_MHZ[region];
            if (ref) {
                markers.push({ mhz: ref, protocol: 'meshcore_ref', label: 'MC?', reference: true });
            }
        }
        return markers;
    }

    async _load() {
        try {
            const res = await fetch('/api/device/spectrum');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (!data.available) {
                // Spectral scan genuinely unsupported/disabled on this box.
                this._root.style.display = 'none';
                return;
            }
            this._root.style.display = '';
            this._sweep = data.sweep;
            this._calibration = data.calibration || null;
            this._renderCalButtons();
            this._renderLegend();
            this._draw();
        } catch (e) {
            console.error('Spectrum load failed:', e);
            // Transient failure (service still starting): stay visible with
            // the "no sweep yet" hint instead of vanishing.
            this._root.style.display = '';
            this._draw();
        }
        this._armEmptyRetry();
    }

    // While visible but without sweep data (service just started, first
    // sweep still running), poll faster than the 60s auto-refresh so the
    // chart fills in shortly after the first scan completes.
    _armEmptyRetry() {
        const havePoints = !!(
            this._sweep && this._sweep.points && this._sweep.points.length
        );
        if (havePoints || this._root.style.display === 'none') return;
        if (this._emptyRetryTimer) return;
        this._emptyRetryTimer = setTimeout(() => {
            this._emptyRetryTimer = null;
            this._load();
        }, 10000);
    }

    _armAutoRefresh() {
        if (this._refreshTimer) return;
        this._refreshTimer = setInterval(() => {
            const section = this._root && this._root.closest('[data-section]');
            if (section && section.classList.contains('section--active')) {
                this._load();
            }
        }, 60000);
    }

    _renderCalButtons() {
        const cal = this._calibration;
        const calBtn = this._root.querySelector('[data-sp-cal]');
        const resetBtn = this._root.querySelector('[data-sp-cal-reset]');
        calBtn.hidden = !cal;
        resetBtn.hidden = !(cal && cal.calibrated);
        if (!cal || this._calWaiting) return;
        calBtn.disabled = !!cal.calibrating;
        calBtn.textContent = cal.calibrating ? 'Calibrating…' : 'Calibrate';
    }

    async _calibrate() {
        const ok = await window.confirmModal({
            label: 'Calibrate band spectrum',
            description: 'Takes ~20 s of captures and saves the median shape as the '
                + 'baseline, so later sweeps show flat = quiet. Do it at a quiet time: '
                + 'short packets are fine, but a signal on air the whole time gets '
                + 'baked into the baseline (Reset cal undoes it). Keep the antenna '
                + 'connected.',
        });
        if (!ok) return;
        const before = this._sweep && this._sweep.generated_at;
        const result = await this._api.post('/api/device/spectrum/calibrate', {});
        if (!result) return;
        const btn = this._root.querySelector('[data-sp-cal]');
        this._calWaiting = true;
        btn.disabled = true;
        btn.textContent = 'Calibrating…';
        let tries = 0;
        clearInterval(this._calTimer);
        this._calTimer = setInterval(async () => {
            tries += 1;
            await this._load();
            const now = this._sweep && this._sweep.generated_at;
            if ((now && now !== before && this._sweep.calibrated) || tries > 30) {
                clearInterval(this._calTimer);
                this._calTimer = null;
                this._calWaiting = false;
                this._renderCalButtons();
            }
        }, 2000);
    }

    async _resetCalibration() {
        const ok = await window.confirmModal({
            label: 'Reset calibration',
            description: 'Forget the saved baseline? Sweeps go back to showing the '
                + 'radios\' own filter shape until you calibrate again.',
        });
        if (!ok) return;
        if (await this._api.delete('/api/device/spectrum/calibrate')) {
            // Next sweep comes out uncalibrated; run one now so the chart matches.
            await this._sweepNow();
        }
    }

    async _sweepNow() {
        const btn = this._root.querySelector('[data-sp-sweep]');
        const before = this._sweep && this._sweep.generated_at;
        const result = await this._api.post('/api/device/spectrum/sweep', {});
        if (!result) return; // 403/503 already toasted by the api helper
        btn.disabled = true;
        btn.textContent = 'Sweeping…';
        let tries = 0;
        clearInterval(this._pollTimer);
        this._pollTimer = setInterval(async () => {
            tries += 1;
            await this._load();
            const now = this._sweep && this._sweep.generated_at;
            if ((now && now !== before) || tries > 20) {
                clearInterval(this._pollTimer);
                this._pollTimer = null;
                btn.disabled = false;
                btn.textContent = 'Sweep now';
            }
        }, 2000);
    }

    // ── drawing ──────────────────────────────────────────────────

    _draw() {
        const canvas = this._canvas;
        if (!canvas || this._root.style.display === 'none') return;
        const empty = this._root.querySelector('[data-sp-empty]');
        const points = (this._sweep && this._sweep.points) || [];

        if (!points.length) {
            empty.hidden = false;
            canvas.style.visibility = 'hidden';
            return;
        }
        empty.hidden = true;
        canvas.style.visibility = '';

        const dpr = window.devicePixelRatio || 1;
        const cssW = canvas.clientWidth || canvas.parentElement.clientWidth;
        const cssH = canvas.clientHeight || 240;
        canvas.width = Math.round(cssW * dpr);
        canvas.height = Math.round(cssH * dpr);
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        const pad = { l: 44, r: 10, t: 18, b: 26 };
        const plotW = cssW - pad.l - pad.r;
        const plotH = cssH - pad.t - pad.b;
        if (plotW < 40 || plotH < 40) return;

        const freqs = points.map((p) => p.frequency_mhz);
        const fMin = Math.min(...freqs);
        const fMax = Math.max(...freqs);
        let yMin = Math.min(...points.map((p) => p.floor_dbm ?? p.median_dbm));
        let yMax = Math.max(...points.map((p) => p.p95_dbm ?? p.median_dbm));
        if (this._isRelative()) {
            yMin = Math.floor((yMin - 2) / 5) * 5;
            yMax = Math.ceil((yMax + 2) / 5) * 5;
        } else {
            yMin = Math.max(-150, Math.floor((yMin - 4) / 5) * 5);
            yMax = Math.min(-40, Math.ceil((yMax + 4) / 5) * 5);
        }
        if (yMax - yMin < 10) yMax = yMin + 10;

        const x = (mhz) => pad.l + ((mhz - fMin) / (fMax - fMin)) * plotW;
        const y = (dbm) => pad.t + ((yMax - dbm) / (yMax - yMin)) * plotH;
        this._geom = { x, y, fMin, fMax, pad, plotW, plotH, cssH };

        // grid + axes (recessive) -- theme-aware
        const ink = (window.ChartTheme && window.ChartTheme.ink()) || {};
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.fillStyle = ink.faint || 'rgba(148, 163, 184, 0.7)';
        ctx.strokeStyle = ink.grid || 'rgba(148, 163, 184, 0.12)';
        ctx.lineWidth = 1;
        for (let dbm = yMin; dbm <= yMax; dbm += 10) {
            ctx.beginPath();
            ctx.moveTo(pad.l, y(dbm));
            ctx.lineTo(pad.l + plotW, y(dbm));
            ctx.stroke();
            ctx.textAlign = 'right';
            ctx.fillText(`${dbm}`, pad.l - 6, y(dbm) + 3);
        }
        const fStep = (fMax - fMin) > 4 ? 1 : 0.5;
        for (let f = Math.ceil(fMin); f <= fMax; f += fStep) {
            // Keep the end labels inside the canvas instead of clipped.
            const px = x(f);
            ctx.textAlign = px > pad.l + plotW - 16 ? 'right'
                : px < pad.l + 16 ? 'left' : 'center';
            ctx.fillText(f.toFixed(fStep < 1 ? 1 : 0), px, cssH - 8);
        }

        // channel markers under the data lines
        this._markers.forEach((m) => {
            if (m.mhz < fMin || m.mhz > fMax) return;
            const color = this._color(m.protocol);
            ctx.strokeStyle = color;
            ctx.globalAlpha = m.reference ? 0.4 : 0.55;
            ctx.setLineDash(m.reference ? [1, 3] : [3, 4]);
            ctx.beginPath();
            ctx.moveTo(x(m.mhz), pad.t);
            ctx.lineTo(x(m.mhz), pad.t + plotH);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
            ctx.fillStyle = color;
            ctx.textAlign = 'center';
            ctx.fillText(m.label, x(m.mhz), pad.t - 5);
        });

        // p95 peak line (thin)
        ctx.strokeStyle = this._color('peak');
        ctx.lineWidth = 1;
        ctx.beginPath();
        points.forEach((p, i) => {
            const v = p.p95_dbm ?? p.median_dbm;
            if (i === 0) ctx.moveTo(x(p.frequency_mhz), y(v));
            else ctx.lineTo(x(p.frequency_mhz), y(v));
        });
        ctx.stroke();

        // median line + fill
        ctx.beginPath();
        points.forEach((p, i) => {
            if (i === 0) ctx.moveTo(x(p.frequency_mhz), y(p.median_dbm));
            else ctx.lineTo(x(p.frequency_mhz), y(p.median_dbm));
        });
        ctx.strokeStyle = this._color('median');
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.lineTo(x(points[points.length - 1].frequency_mhz), pad.t + plotH);
        ctx.lineTo(x(points[0].frequency_mhz), pad.t + plotH);
        ctx.closePath();
        ctx.fillStyle = 'rgba(6, 182, 212, 0.12)';
        ctx.fill();
    }

    _onHover(event) {
        const points = (this._sweep && this._sweep.points) || [];
        if (!points.length || !this._geom) return;
        const rect = this._canvas.getBoundingClientRect();
        const px = event.clientX - rect.left;
        const { x } = this._geom;
        let best = null;
        let bestDist = Infinity;
        points.forEach((p) => {
            const d = Math.abs(x(p.frequency_mhz) - px);
            if (d < bestDist) { bestDist = d; best = p; }
        });
        if (!best || bestDist > 24) {
            this._tooltip.hidden = true;
            return;
        }
        const peak = best.p95_dbm != null ? ` · peak ${best.p95_dbm}` : '';
        this._tooltip.textContent =
            `${best.frequency_mhz.toFixed(3)} MHz · median ${best.median_dbm}${peak} `
            + (this._isRelative() ? 'dB over floor' : 'dBm');
        this._tooltip.hidden = false;
        const bodyRect = this._canvas.parentElement.getBoundingClientRect();
        let left = event.clientX - bodyRect.left + 12;
        const maxLeft = bodyRect.width - this._tooltip.offsetWidth - 8;
        if (left > maxLeft) left = maxLeft;
        this._tooltip.style.left = `${Math.max(0, left)}px`;
        this._tooltip.style.top = `${event.clientY - bodyRect.top - 30}px`;
    }
}

window.RadioSpectrumCard = RadioSpectrumCard;
