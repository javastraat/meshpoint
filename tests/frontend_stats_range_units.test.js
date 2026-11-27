// Stats → Range cards follow a km/mi switch right away, without waiting for the next poll
// (upstream b91d994b, tests/frontend/node_sort_stats_units.test.cjs; ours shows value and
// unit in one span and also has a MeshCore range card).
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
    const elements = new Map(), stored = new Map(), listeners = new Map();
    for (const prefix of ['ss-direct', 'ss-mesh', 'ss-mc']) {
        for (const suffix of ['mi', 'unit', 'detail', 'bar']) {
            elements.set(`${prefix}-${suffix}`, { textContent: '', style: {} });
        }
    }
    const window = {
        addEventListener(type, fn) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(fn);
        },
        dispatchEvent(event) { for (const fn of listeners.get(event.type) || []) fn(event); },
    };
    const ctx = vm.createContext({
        window, console,
        CustomEvent: class { constructor(type, opts) { this.type = type; this.detail = opts.detail; } },
        localStorage: { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, v) },
        document: { getElementById: (id) => elements.get(id) || null, querySelectorAll: () => [], addEventListener() {} },
    });
    for (const file of ['meshpoint_display_units.js', 'stats_tab.js']) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js', file), 'utf8'), ctx);
    }
    const text = (id) => elements.get(id).textContent;
    return { window, elements, text };
}

test('direct, mesh and MeshCore range redraw on a unit switch', () => {
    const { window, elements, text } = fixture();
    const stats = window.statsTab;
    stats._rendered = true;
    stats._updateRange({ farthest_direct: { miles: 1 } }, { miles: 20 });
    stats._updateMeshCoreRange({ miles: 0.01 });
    assert.strictEqual(text('ss-direct-mi'), '1.6 km'); // metric is the default
    assert.strictEqual(text('ss-mesh-mi'), '32 km');
    assert.strictEqual(text('ss-mc-mi'), '16 m');
    const bar = elements.get('ss-direct-bar').style.width;

    window.MeshpointDisplayUnits.savePrefs({ distance: 'imperial' });
    assert.strictEqual(text('ss-direct-mi'), '1.0 mi');
    assert.strictEqual(text('ss-mesh-mi'), '20 mi');
    assert.strictEqual(text('ss-mc-mi'), '53 ft');
    assert.strictEqual(elements.get('ss-direct-bar').style.width, bar); // bars don't move

    window.MeshpointDisplayUnits.savePrefs({ distance: 'metric' });
    assert.strictEqual(text('ss-direct-mi'), '1.6 km');
});

test('no redraw before the tab has rendered or without data', () => {
    const { window, text } = fixture();
    window.MeshpointDisplayUnits.savePrefs({ distance: 'imperial' }); // nothing stored yet: no error
    assert.strictEqual(text('ss-direct-mi'), '');
});
