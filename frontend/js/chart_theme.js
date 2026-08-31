/**
 * Theme-aware defaults for Chart.js.
 *
 * Chart.js renders to <canvas>, so it can't read CSS variables the way
 * the rest of the dashboard does -- axis labels, gridlines and legends
 * would stay their hardcoded dark-theme grey on the light theme. This
 * module pushes the current palette into `Chart.defaults` once at load
 * and again on every `meshpoint:themechange`, then repaints every live
 * chart. Individual charts can also call `ChartTheme.ink()` for the
 * same colours when they build custom scales.
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

    function ink() {
        return {
            fg: token('--text-secondary', '#94a3b8'),
            faint: token('--text-muted', '#64748b'),
            grid: token('--hairline', 'rgba(148, 163, 184, 0.18)'),
            surface: token('--bg-card', '#162033'),
            border: token('--border', '#233049'),
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

    // Repaint every live chart: axis ticks / gridlines / legend text are
    // always a neutral in this codebase, so overwrite them with the live
    // token. Axis *title* colours are left alone -- they deliberately
    // match a data series.
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

    window.ChartTheme = { ink, applyDefaults, refresh };
})();
