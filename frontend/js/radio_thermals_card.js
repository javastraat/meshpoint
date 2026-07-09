/**
 * Radio tab — Thermals card (observational).
 *
 * CPU temperature and fan duty history from ``GET /api/device/thermals``
 * (the fan controller's in-memory ring buffer, one sample per poll).
 * Two stacked Chart.js panels sharing the time window — temperature in
 * °C on top, fan duty in % below — rather than one dual-axis chart, so
 * each panel keeps a single honest scale. Card hides itself when fan
 * control is disabled (``available: false``), matching the stat-bar
 * Fan card.
 */
class RadioThermalsCard {
    static TEMP_COLOR = '#f97316';   // matches "Temp" series in node drawer
    static DUTY_COLOR = '#06b6d4';
    static MAX_DRAW_POINTS = 720;

    constructor(api) {
        this._api = api;
        this._root = null;
        this._charts = [];
        this._refreshTimer = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        rootEl.style.display = 'none';
        rootEl.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Thermals</h3>
                <span class="thermals-meta" data-th-meta></span>
            </div>
            <div class="thermals-empty" data-th-empty hidden>
                Collecting data — first samples arrive within a minute.
            </div>
            <div class="thermals-panel">
                <div class="thermals-panel__label">CPU temp (&deg;C)</div>
                <div class="thermals-panel__plot">
                    <canvas data-th-temp></canvas>
                </div>
            </div>
            <div class="thermals-panel">
                <div class="thermals-panel__label">Fan duty (%)</div>
                <div class="thermals-panel__plot">
                    <canvas data-th-duty></canvas>
                </div>
            </div>
        `;
    }

    render() {
        this._load();
        this._armAutoRefresh();
    }

    async _load() {
        try {
            const res = await fetch('/api/device/thermals');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (!data.available) {
                this._root.style.display = 'none';
                return;
            }
            this._root.style.display = '';
            this._draw(data.points || []);
        } catch (e) {
            console.error('Thermals load failed:', e);
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

    _draw(points) {
        const empty = this._root.querySelector('[data-th-empty]');
        const panels = this._root.querySelectorAll('.thermals-panel');
        const tooFew = points.length < 2 || !window.Chart;
        empty.hidden = !tooFew;
        panels.forEach((p) => { p.hidden = tooFew; });
        if (tooFew) return;

        const rows = this._downsample(points, RadioThermalsCard.MAX_DRAW_POINTS);
        const minX = rows[0].ts * 1000;
        const maxX = rows[rows.length - 1].ts * 1000;
        const span = maxX - minX;

        this._charts.forEach((c) => c.destroy());
        this._charts = [
            this._panelChart(
                this._root.querySelector('[data-th-temp]'),
                rows.map((r) => ({ x: r.ts * 1000, y: r.temp_c })),
                RadioThermalsCard.TEMP_COLOR,
                {
                    minX, maxX, span,
                    suggestedMin: 40, suggestedMax: 60,
                    fmt: (v) => `${v.toFixed(1)} °C`,
                    hideXTicks: true,
                },
            ),
            this._panelChart(
                this._root.querySelector('[data-th-duty]'),
                rows.map((r) => ({ x: r.ts * 1000, y: r.duty * 100 })),
                RadioThermalsCard.DUTY_COLOR,
                {
                    minX, maxX, span,
                    suggestedMin: 0, suggestedMax: 100,
                    fmt: (v) => `${v.toFixed(0)}%`,
                    hideXTicks: false,
                },
            ),
        ];

        const meta = this._root.querySelector('[data-th-meta]');
        const last = rows[rows.length - 1];
        meta.textContent =
            `${last.temp_c.toFixed(1)} °C · fan ${(last.duty * 100).toFixed(0)}%`;
    }

    _panelChart(canvas, data, color, opts) {
        return new Chart(canvas, {
            type: 'line',
            data: {
                datasets: [{
                    data,
                    borderColor: color,
                    backgroundColor: color + '22',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHitRadius: 8,
                    tension: 0.25,
                    fill: true,
                    spanGaps: true,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', axis: 'x', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (items) => {
                                if (!items.length) return '';
                                return new Date(items[0].parsed.x)
                                    .toLocaleString([], {
                                        month: 'short',
                                        day: 'numeric',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        hour12: false,
                                    });
                            },
                            label: (ctx) => opts.fmt(ctx.parsed.y),
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: opts.minX,
                        max: opts.maxX,
                        ticks: {
                            display: !opts.hideXTicks,
                            maxTicksLimit: 6,
                            color: '#64748b',
                            font: { size: 9 },
                            callback: (v) => this._formatAxisTime(v, opts.span),
                        },
                        grid: { color: 'rgba(51, 65, 85, 0.25)' },
                    },
                    y: {
                        suggestedMin: opts.suggestedMin,
                        suggestedMax: opts.suggestedMax,
                        ticks: {
                            maxTicksLimit: 4,
                            color: '#64748b',
                            font: { size: 9 },
                        },
                        grid: { color: 'rgba(51, 65, 85, 0.25)' },
                    },
                },
            },
        });
    }

    _downsample(rows, maxPoints) {
        if (rows.length <= maxPoints) return rows;
        const step = Math.ceil(rows.length / maxPoints);
        const out = [];
        for (let i = 0; i < rows.length; i += step) out.push(rows[i]);
        if (out[out.length - 1] !== rows[rows.length - 1]) {
            out.push(rows[rows.length - 1]);
        }
        return out;
    }

    _formatAxisTime(ms, spanMs) {
        const d = new Date(ms);
        if (spanMs > 6 * 3600000) {
            return d.toLocaleString([], {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
            });
        }
        return d.toLocaleTimeString(
            [], { hour: '2-digit', minute: '2-digit', hour12: false },
        );
    }
}

window.RadioThermalsCard = RadioThermalsCard;
