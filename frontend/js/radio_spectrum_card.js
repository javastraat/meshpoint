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
 */
class RadioSpectrumCard {
    static MEDIAN_COLOR = '#06b6d4';
    static PEAK_COLOR = '#a855f7';
    static MARKER_COLORS = {
        lorawan: '#3b82f6',
        meshtastic: '#10b981',
        meshcore: '#f59e0b',
    };

    constructor(api) {
        this._api = api;
        this._root = null;
        this._sweep = null;
        this._markers = [];
        this._pollTimer = null;
        this._refreshTimer = null;
        this._redraw = () => this._draw();
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        rootEl.style.display = 'none';
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Band Spectrum</h3>
                <span class="spectrum-actions">
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
            <div class="spectrum-legend" data-sp-legend>
                <span><i style="background:${RadioSpectrumCard.MEDIAN_COLOR}"></i>Median</span>
                <span><i style="background:${RadioSpectrumCard.PEAK_COLOR}"></i>Peak (p95)</span>
                <span><i style="background:${RadioSpectrumCard.MARKER_COLORS.lorawan}"></i>LoRaWAN ch</span>
                <span><i style="background:${RadioSpectrumCard.MARKER_COLORS.meshtastic}"></i>Meshtastic</span>
                <span><i style="background:${RadioSpectrumCard.MARKER_COLORS.meshcore}"></i>MeshCore</span>
            </div>
        `;
        this._canvas = rootEl.querySelector('[data-sp-canvas]');
        this._tooltip = rootEl.querySelector('[data-sp-tooltip]');

        rootEl.querySelector('[data-sp-sweep]')
            .addEventListener('click', () => this._sweepNow());
        window.addEventListener('resize', this._redraw);
        this._canvas.addEventListener('mousemove', (e) => this._onHover(e));
        this._canvas.addEventListener('mouseleave', () => {
            this._tooltip.hidden = true;
        });
    }

    render(config) {
        this._markers = this._buildMarkers(config);
        this._load();
        this._armAutoRefresh();
    }

    _buildMarkers(config) {
        const markers = [];
        const conc = (config && config.concentrator) || {};
        (conc.channels || []).forEach((ch) => {
            if (!ch.enabled) return;
            markers.push({
                mhz: ch.frequency_mhz,
                protocol: ch.protocol,
                label: ch.protocol === 'meshtastic' ? 'MT' : `L${ch.ch}`,
            });
        });
        const mc = config && config.meshcore && config.meshcore.radio;
        if (mc && mc.frequency_mhz) {
            markers.push({
                mhz: Number(mc.frequency_mhz),
                protocol: 'meshcore',
                label: 'MC',
            });
        }
        return markers;
    }

    async _load() {
        try {
            const res = await fetch('/api/device/spectrum');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (!data.available) {
                this._root.style.display = 'none';
                return;
            }
            this._root.style.display = '';
            this._sweep = data.sweep;
            this._draw();
        } catch (e) {
            console.error('Spectrum load failed:', e);
        }
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
        yMin = Math.max(-150, Math.floor((yMin - 4) / 5) * 5);
        yMax = Math.min(-40, Math.ceil((yMax + 4) / 5) * 5);
        if (yMax - yMin < 10) yMax = yMin + 10;

        const x = (mhz) => pad.l + ((mhz - fMin) / (fMax - fMin)) * plotW;
        const y = (dbm) => pad.t + ((yMax - dbm) / (yMax - yMin)) * plotH;
        this._geom = { x, y, fMin, fMax, pad, plotW, plotH, cssH };

        // grid + axes (recessive)
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.fillStyle = 'rgba(148, 163, 184, 0.7)';
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.12)';
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
            ctx.textAlign = 'center';
            ctx.fillText(f.toFixed(0), x(f), cssH - 8);
        }

        // channel markers under the data lines
        this._markers.forEach((m) => {
            if (m.mhz < fMin || m.mhz > fMax) return;
            const color = RadioSpectrumCard.MARKER_COLORS[m.protocol]
                || 'rgba(148,163,184,0.5)';
            ctx.strokeStyle = color;
            ctx.globalAlpha = 0.55;
            ctx.setLineDash([3, 4]);
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
        ctx.strokeStyle = RadioSpectrumCard.PEAK_COLOR;
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
        ctx.strokeStyle = RadioSpectrumCard.MEDIAN_COLOR;
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
            `${best.frequency_mhz.toFixed(3)} MHz · median ${best.median_dbm}${peak} dBm`;
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
