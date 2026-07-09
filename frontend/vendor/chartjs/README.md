# Vendored Chart.js

Pinned, byte-for-byte copy of the Chart.js UMD bundle used by the RF
Environment tab's histogram (`frontend/js/rf_tab.js`) and the node drawer's
metrics charts (`frontend/js/node_metrics_chart.js`).

Vendored so those charts still render on Pis with no outbound CDN access
(same rationale as `frontend/vendor/xterm/` and `frontend/vendor/qrcode/`).

## Files

| File                    | Source                                                              | Bytes  |
|-------------------------|----------------------------------------------------------------------|-------:|
| `chart.umd.min.js`      | https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js    | 205749 |

## Version

- `chart.js` 4.4.4 (UMD build, exposes global `Chart`)

## Dashboard usage

Loaded from `frontend/index.html` before `js/node_metrics_chart.js`. Exposes
global `Chart` used by `node_metrics_chart.js` and `js/rf_tab.js`.

## License

MIT, owned by the Chart.js authors. See https://github.com/chartjs/Chart.js
for the full text. The vendored copy retains the upstream banner comment.

## Refresh procedure

```bash
curl -fsSLo frontend/vendor/chartjs/chart.umd.min.js \
    "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
```

Then update the version and byte count above, and re-check the RF
Environment histogram and node drawer metrics charts render on a Pi.
