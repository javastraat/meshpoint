/**
 * Node drawer time-series chart (Chart.js).
 * Meshtastic-style device metrics: battery, voltage, util, temperature, RSSI.
 */
class NodeMetricsChart {
    constructor(canvas) {
        this._canvas = canvas;
        this._chart = null;
    }

    destroy() {
        if (this._chart) {
            this._chart.destroy();
            this._chart = null;
        }
    }

    /**
     * @param {{ telemetry: object[], signal: object[] }} history
     */
    render(history) {
        this.destroy();
        if (!window.Chart || !this._canvas) return false;

        const datasets = this._buildDatasets(history || {});
        if (datasets.length === 0) return false;

        const hasBattery = datasets.some((d) => d.yAxisID === 'y');
        const hasVoltage = datasets.some((d) => d.yAxisID === 'y1');
        const hasRssi = datasets.some((d) => d.yAxisID === 'y2');
        const hasTemp = datasets.some((d) => d.yAxisID === 'y3');

        this._chart = new Chart(this._canvas, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            boxWidth: 10,
                            font: { size: 10 },
                            color: '#94a3b8',
                        },
                    },
                    tooltip: {
                        callbacks: {
                            title: (items) => {
                                if (!items.length) return '';
                                const x = items[0].parsed.x;
                                return new Date(x).toLocaleString([], {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                });
                            },
                            label: (ctx) => this._tooltipLabel(ctx),
                        },
                    },
                },
                scales: {
                    x: {
                        type: 'linear',
                        ticks: {
                            maxTicksLimit: 5,
                            color: '#64748b',
                            font: { size: 9 },
                            callback: (v) => this._formatAxisTime(v),
                        },
                        grid: { color: 'rgba(51, 65, 85, 0.35)' },
                    },
                    y: {
                        display: hasBattery,
                        position: 'left',
                        min: 0,
                        max: 100,
                        title: {
                            display: hasBattery,
                            text: '%',
                            color: '#22c55e',
                            font: { size: 9 },
                        },
                        ticks: { color: '#64748b', font: { size: 9 } },
                        grid: { color: 'rgba(51, 65, 85, 0.25)' },
                    },
                    y1: {
                        display: hasVoltage,
                        position: 'right',
                        min: 0,
                        max: 5,
                        title: {
                            display: hasVoltage,
                            text: 'V',
                            color: '#eab308',
                            font: { size: 9 },
                        },
                        ticks: { color: '#64748b', font: { size: 9 } },
                        grid: { drawOnChartArea: false },
                    },
                    y2: {
                        display: hasRssi,
                        position: 'right',
                        min: -120,
                        max: -40,
                        title: {
                            display: hasRssi,
                            text: 'dBm',
                            color: '#06b6d4',
                            font: { size: 9 },
                        },
                        ticks: { color: '#64748b', font: { size: 9 } },
                        grid: { drawOnChartArea: false },
                    },
                    y3: {
                        display: hasTemp,
                        position: 'right',
                        title: {
                            display: hasTemp,
                            text: '°',
                            color: '#f97316',
                            font: { size: 9 },
                        },
                        ticks: { color: '#64748b', font: { size: 9 } },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        });
        return true;
    }

    _buildDatasets(history) {
        const out = [];
        const telem = history.telemetry || [];
        const signal = history.signal || [];

        this._addSeries(out, 'Battery', '#22c55e', 'y', telem, (t) => {
            const v = t.battery_level;
            return v != null && v > 0 ? v : null;
        });
        this._addSeries(out, 'Voltage', '#eab308', 'y1', telem, (t) => t.voltage);
        this._addSeries(out, 'ChUtil', '#a855f7', 'y', telem, (t) => t.channel_utilization);
        this._addSeries(out, 'AirUtil', '#3b82f6', 'y', telem, (t) => t.air_util_tx);
        this._addSeries(out, 'Temp', '#f97316', 'y3', telem, (t) => {
            if (t.temperature == null) return null;
            return t.temperature;
        });
        this._addSeries(out, 'RSSI', '#06b6d4', 'y2', signal, (s) => s.rssi);

        return out.filter((d) => d.data.length >= 2);
    }

    _addSeries(list, label, color, yAxisID, rows, pick) {
        const data = [];
        for (const row of rows) {
            const y = pick(row);
            if (y == null || Number.isNaN(Number(y))) continue;
            const x = new Date(row.timestamp).getTime();
            if (Number.isNaN(x)) continue;
            data.push({ x, y: Number(y) });
        }
        if (data.length === 0) return;
        list.push({
            label,
            data,
            yAxisID,
            borderColor: color,
            backgroundColor: color + '22',
            borderWidth: 1.5,
            pointRadius: 0,
            pointHitRadius: 6,
            tension: 0.25,
            fill: label === 'Battery' || label === 'Voltage',
        });
    }

    _formatAxisTime(ms) {
        const d = new Date(ms);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    _tooltipLabel(ctx) {
        const label = ctx.dataset.label || '';
        let value = ctx.parsed.y;
        if (label === 'Temp' && window.MeshpointDisplayUnits) {
            const formatted = window.MeshpointDisplayUnits.formatTemperature(value);
            return formatted ? `${label}: ${formatted}` : `${label}: ${value.toFixed(1)}`;
        }
        if (label === 'RSSI') return `${label}: ${value.toFixed(1)} dBm`;
        if (label === 'Voltage') return `${label}: ${value.toFixed(2)} V`;
        if (label === 'Battery') return `${label}: ${value.toFixed(0)}%`;
        if (label === 'ChUtil' || label === 'AirUtil') {
            return `${label}: ${value.toFixed(1)}%`;
        }
        return `${label}: ${value}`;
    }
}

window.NodeMetricsChart = NodeMetricsChart;
