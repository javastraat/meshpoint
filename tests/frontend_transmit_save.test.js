// Configuration → Transmit save (upstream 553bdd83, PR #177; adapted: our card keeps the
// burst/RSSI relay filters and only sends PUT /api/config/relay when one is filled in).
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'frontend/js/configuration/transmit_card.js'), 'utf8');

// results: one entry per PUT, in order (an object = saved, null = failed, Error = rejected).
function setup(results, relayFilters = {}) {
    const window = {};
    vm.runInNewContext(SRC, { window });
    const calls = [], restarts = [], elements = new Map();
    const root = {
        innerHTML: '',
        querySelector(selector) {
            const attribute = selector.slice(1, -1);
            if (!this.innerHTML.includes(attribute)) return null; // like the browser
            if (!elements.has(selector)) elements.set(selector, {
                _value: '', get value() { return this._value; },
                set value(v) { this._value = String(v); },
                checked: false, dataset: {}, textContent: '',
                addEventListener() {},
            });
            return elements.get(selector);
        },
    };
    const card = new window.TransmitConfigCard({
        async put(url, payload) {
            calls.push({ url, payload: JSON.parse(JSON.stringify(payload)) });
            const result = results[calls.length - 1];
            if (result instanceof Error) throw result;
            return result;
        },
        signalRestart(message) { restarts.push(message); },
    });
    card.mount(root);
    card.render({ transmit: { enabled: true, tx_power_dbm: 17, max_duty_cycle_percent: 1,
        relay: { enabled: false, max_relay_per_minute: 12, ...relayFilters } } });
    return { card, calls, restarts, status: elements.get('[data-tx-status]') };
}

const submit = (card) => card._onSubmit({ preventDefault() {} });

test('blank relay filters: one PUT to /api/config/transmit, Saved, restart asked', async () => {
    const { card, calls, restarts, status } = setup([{ saved: true }]);
    await submit(card);
    assert.deepStrictEqual(calls, [{ url: '/api/config/transmit', payload: {
        enabled: true, tx_power_dbm: 17, max_duty_cycle_percent: 1,
        relay: { enabled: false, max_relay_per_minute: 12 },
    } }]);
    assert.strictEqual(status.dataset.kind, 'success');
    assert.strictEqual(status.textContent, 'Saved.');
    assert.deepStrictEqual(restarts, ['Transmit settings updated.']);
});

test('filled-in relay filters also go to /api/config/relay', async () => {
    const { card, calls, status } = setup([{ saved: true }, { saved: true }],
        { burst_size: 3, min_relay_rssi: -120, max_relay_rssi: -40 });
    await submit(card);
    assert.deepStrictEqual(calls.map((c) => c.url), ['/api/config/transmit', '/api/config/relay']);
    assert.deepStrictEqual(calls[1].payload, { burst_size: 3, min_relay_rssi: -120, max_relay_rssi: -40 });
    assert.strictEqual(status.textContent, 'Saved.');
});

for (const [name, result] of [['failed response', null], ['request rejection', new Error('offline')]]) {
    test(`transmit ${name}: error instead of Saving…, no restart`, async () => {
        const { card, calls, restarts, status } = setup([result]);
        await submit(card);
        assert.strictEqual(calls.length, 1);
        assert.strictEqual(status.dataset.kind, 'error');
        assert.strictEqual(status.textContent, 'Transmit save failed.');
        assert.deepStrictEqual(restarts, []);
    });

    test(`relay filter ${name}: error instead of Saving…, no restart`, async () => {
        const { card, calls, restarts, status } = setup([{ saved: true }, result], { burst_size: 3 });
        await submit(card);
        assert.strictEqual(calls.length, 2);
        assert.strictEqual(status.dataset.kind, 'error');
        assert.strictEqual(status.textContent, 'Relay filter save failed.');
        assert.deepStrictEqual(restarts, []);
    });
}
