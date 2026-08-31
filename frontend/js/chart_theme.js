/**
 * Theme-aware colours for Chart.js and the hand-drawn canvases.
 *
 * Chart.js renders to <canvas>, so it can't read CSS variables the way
 * the rest of the dashboard does. This module:
 *   - pushes the current palette into `Chart.defaults` (axis labels,
 *     gridlines, legend, tooltip) on load and on every
 *     `meshpoint:themechange`, then repaints every live chart;
 *   - exposes `ChartTheme.ink()` (chrome colours), `.series(key)` /
 *     `.categorical` (data-series colours) and `.status(level)` so
 *     charts stop hardcoding hex.
 *
 * Series colours: semantic ones (battery/temp/rssi/…) resolve to the
 * theme's `--accent-*` tokens so they track the theme and keep their
 * meaning. Everything else draws from a fixed categorical scale chosen
 * to stay distinguishable and legible on BOTH light and dark
 * backgrounds (a Paul Tol / Okabe-Ito style set, minus the pure yellow
 * and pure black that only work on one polarity). A categorical scale
 * is deliberately NOT theme-switched -- a series should keep its colour.
 */
(function () {
    function token(name, fallback) {
        try {
            const v = getComputedStyle(document.documentElement)
                .getPropertyValue(name).trim();
            return v || fallback;
        } catch (_e) {
            return fallback;
        }
    }

    const CATEGORICAL = [
        '#4c8dd6', '#e08e2a', '#2fa88f', '#c56ba6',
        '#7d7fd0', '#d1584f', '#93ab4b', '#48b0cf',
        '#a879c9', '#5aa469', '#d98282', '#c9a13c',
    ];

    // Semantic series -> palette token (theme-tracked). Anything not
    // listed falls through to the categorical scale by index.
    const SEMANTIC = {
        battery: () => token('--accent-green', '#22c55e'),
        voltage: () => CATEGORICAL[11],            // gold, not pure yellow
        temp: () => token('--accent-amber', '#f97316'),
        temperature: () => token('--accent-amber', '#f97316'),
        humidity: () => token('--accent-cyan', '#38bdf8'),
        pressure: () => token('--accent-purple', '#c084fc'),
        rssi: () => token('--accent-cyan', '#06b6d4'),
        snr: () => CATEGORICAL[2],
        duty: () => token('--accent-cyan', '#06b6d4'),
        chutil: () => token('--accent-purple', '#a855f7'),
        airutil: () => token('--accent-blue', '#3b82f6'),
        // protocol identity -- matches the topbar chips
        meshtastic: () => token('--accent-cyan', '#06b6d4'),
        meshcore: () => token('--accent-purple', '#a855f7'),
        lorawan: () => token('--accent-blue', '#3b82f6'),
        pager: () => token('--accent-amber', '#f59e0b'),
        dapnet: () => token('--accent-amber', '#f59e0b'),
        median: () => token('--accent-cyan', '#06b6d4'),
        peak: () => token('--accent-purple', '#a855f7'),
    };

    function series(key) {
        if (typeof key === 'number') return CATEGORICAL[key % CATEGORICAL.length];
        const norm = String(key || '').toLowerCase().replace(/[^a-z]/g, '');
        return SEMANTIC[norm] ? SEMANTIC[norm]() : CATEGORICAL[0];
    }

    function status(level) {
        let key = level;
        if (typeof level === 'number') key = level >= 70 ? 'ok' : level >= 40 ? 'warn' : 'bad';
        return {
            ok: token('--accent-green', '#22c55e'),
            warn: token('--accent-amber', '#f59e0b'),
            bad: token('--accent-red', '#ef4444'),
        }[key] || token('--accent-green', '#22c55e');
    }

    function ink() {
        return {
            fg: token('--text-secondary', '#94a3b8'),
            faint: token('--text-muted', '#64748b'),
            grid: token('--hairline', 'rgba(148, 163, 184, 0.18)'),
            surface: token('--bg-card', '#162033'),
            border: token('--border', '#233049'),
            text: token('--text-primary', '#e2e8f0'),
        };
    }

    function applyDefaults() {
        if (!window.Chart) return;
        const c = ink();
        const d = window.Chart.defaults;
        d.color = c.fg;
        d.borderColor = c.grid;
        if (d.scale) {
            d.scale.grid = { ...(d.scale.grid || {}), color: c.grid };
            d.scale.ticks = { ...(d.scale.ticks || {}), color: c.faint };
            if (d.scale.title) d.scale.title.color = c.faint;
        }
        if (d.plugins) {
            if (d.plugins.legend?.labels) d.plugins.legend.labels.color = c.fg;
            if (d.plugins.tooltip) {
                d.plugins.tooltip.backgroundColor = c.surface;
                d.plugins.tooltip.titleColor = c.fg;
                d.plugins.tooltip.bodyColor = c.fg;
                d.plugins.tooltip.borderColor = c.border;
                d.plugins.tooltip.borderWidth = 1;
            }
        }
    }

    // Repaint every live chart on a theme switch: axis ticks / gridlines
    // / legend are always neutral, so re-token them. A dataset tagged
    // `_meshSeries` re-resolves its own colour (for accent-tracked
    // series that stay on screen, e.g. an open node drawer).
    function repaintAll() {
        if (!window.Chart) return;
        const c = ink();
        Object.values(window.Chart.instances || {}).forEach((chart) => {
            try {
                Object.values(chart.options?.scales || {}).forEach((ax) => {
                    if (ax?.ticks && 'color' in ax.ticks) ax.ticks.color = c.faint;
                    if (ax?.grid && 'color' in ax.grid) ax.grid.color = c.grid;
                });
                const ll = chart.options?.plugins?.legend?.labels;
                if (ll && 'color' in ll) ll.color = c.fg;
                (chart.data?.datasets || []).forEach((ds) => {
                    if (!ds._meshSeries) return;
                    const col = series(ds._meshSeries);
                    ds.borderColor = col;
                    if (typeof ds.backgroundColor === 'string' && ds._meshFill) {
                        ds.backgroundColor = col + ds._meshFill;
                    }
                });
                chart.update('none');
            } catch (_e) {}
        });
    }

    function refresh() {
        applyDefaults();
        repaintAll();
    }

    applyDefaults();
    window.addEventListener('meshpoint:themechange', refresh);
    document.addEventListener('DOMContentLoaded', applyDefaults);

    window.ChartTheme = {
        ink, series, status, applyDefaults, refresh,
        get categorical() { return CATEGORICAL.slice(); },
    };
})();
