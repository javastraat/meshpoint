/**
 * DAB+ -> RTL-SDR page hook.
 *
 * Test case for the "hook" seam (frontend/sidebar/page_hook_registry.js)
 * against a real, non-trivial plugin -- the DAB+ tab itself lives on the
 * built-in Listener page as always (dab_panel.js/dab_config_panel.js,
 * unchanged); this is a SEPARATE, small read-only status card injected
 * into the rtlsdr plugin's page (plugins/apps/rtlsdr/), proving a real
 * plugin can hook into another plugin's page without disturbing its own
 * existing UI. See plugins/apps/rtlsdr/README.md for the full context.
 *
 * One-shot status fetch on mount, no polling -- this is a proof of
 * mechanism, not a live dashboard; the real DAB+ tab already covers that.
 */
window.registerPageHook({
    host: 'rtlsdr',
    make: () => ({
        mount(rootEl) {
            rootEl.innerHTML = `
                <div class="dab-rtlsdr-hook">
                    <h3>DAB+</h3>
                    <p data-dab-hook-status>Loading status…</p>
                </div>
            `;
            const statusEl = rootEl.querySelector('[data-dab-hook-status]');
            fetch('/api/dab/status')
                .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
                .then((st) => {
                    if (st.running) {
                        statusEl.textContent = `Tuned to ${st.channel}`
                            + (st.ensemble_label ? ` — ${st.ensemble_label}` : '')
                            + (typeof st.snr === 'number' ? ` (SNR ${st.snr.toFixed(1)} dB)` : '');
                    } else if (st.dongle_owner) {
                        statusEl.textContent = `Idle — RTL-SDR dongle busy with ${st.dongle_owner}`;
                    } else {
                        statusEl.textContent = 'Idle';
                    }
                })
                .catch(() => {
                    statusEl.textContent = 'Status unavailable';
                });
        },
        show() {},
        hide() {},
    }),
});
