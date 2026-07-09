/** Configuration → GPS — position broadcast interval editor. */

class PositionBroadcastCard {
    constructor(api) {
        this._inner = new window.BroadcastIntervalCard(api, {
            title: 'Position broadcast interval',
            hint: 'How often this Meshpoint sends POSITION packets on the mesh '
                + '(Meshtastic app map). Separate from NodeInfo identity broadcasts.',
            saveLabel: 'Save position interval',
            putUrl: '/api/config/position',
            configKey: 'position',
            cardId: 'cfg-position-interval',
        });
    }

    mount(root) {
        this._inner.mount(root);
    }

    render(config) {
        this._inner.render(config);
    }
}

window.PositionBroadcastCard = PositionBroadcastCard;
