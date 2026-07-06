/** Configuration → Radio — telemetry broadcast interval editor. */

class TelemetryBroadcastCard {
    constructor(api) {
        this._inner = new window.BroadcastIntervalCard(api, {
            title: 'Telemetry broadcast interval',
            hint: 'How often this Meshpoint sends device health telemetry on the mesh '
                + '(TELEMETRY_APP). Separate from NodeInfo identity broadcasts.',
            saveLabel: 'Save telemetry interval',
            putUrl: '/api/config/telemetry',
            configKey: 'telemetry',
            cardId: 'cfg-telemetry-interval',
        });
    }

    mount(root) {
        this._inner.mount(root);
    }

    render(config) {
        this._inner.render(config);
    }
}

window.TelemetryBroadcastCard = TelemetryBroadcastCard;
