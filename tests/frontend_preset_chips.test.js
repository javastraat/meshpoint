// Preset chips and "show only" filter (upstream 829a17e4/45adf5c5, TODO 30). Ours: LongMod is "LMd",
// "LM" is LocalMesh, protocols without a Meshtastic preset get no chip. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(extra = {}) {
    const store = new Map();
    const listeners = new Map();
    const document = {
        getElementById: () => null,
        addEventListener(type, fn) { (listeners.get(type) || listeners.set(type, []).get(type)).push(fn); },
        dispatchEvent(ev) { (listeners.get(ev.type) || []).forEach((fn) => fn(ev)); },
        createElement: () => ({ dataset: {}, classList: { add() {} }, addEventListener() {} }),
        ...extra.document,
    };
    const ctx = vm.createContext({
        window: {}, document, console,
        localStorage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
        CustomEvent: class { constructor(type, o) { this.type = type; this.detail = o && o.detail; } },
        requestAnimationFrame: (fn) => { fn(); return 1; },
    });
    for (const f of ['modem_preset_label.js', 'radio_view_filter.js', ...(extra.files || [])]) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js', f), 'utf8'), ctx);
    }
    ctx.window.__ctx = ctx;
    return ctx.window;
}

test('SF/BW map to the Meshtastic presets; LongMod is LMd', () => {
    const L = load().ModemPresetLabel;
    const chip = (sf, bw, proto) => (L.fromProtocolAndModem(proto, sf, bw) || {}).chip;
    assert.strictEqual(chip(11, 250), 'LF');
    assert.strictEqual(chip(9, 250.0), 'MF');
    assert.strictEqual(chip(11, 500), 'LT');
    assert.strictEqual(chip(11, 125), 'LMd');
    assert.strictEqual(chip(12, 62.5), 'VL');
    assert.strictEqual(chip(8, 333), undefined);
});

test('MeshCore is MC, LocalMesh is LM, other protocols get no chip', () => {
    const L = load().ModemPresetLabel;
    assert.strictEqual(L.fromProtocolAndModem('meshcore', 8, 62.5).chip, 'MC');
    assert.strictEqual(L.fromProtocolAndModem('localmesh', 7, 62.5).chip, 'LM');
    assert.strictEqual(L.fromProtocolAndModem('pager', 1200, 25), null);
    assert.strictEqual(L.fromProtocolAndModem('lorawan', 7, 125), null);
    assert.strictEqual(L.fromNode({ protocol: 'meshtastic', latest_spreading_factor: 11, latest_bandwidth_khz: 250 }).chip, 'LF');
    assert.strictEqual(L.fromPacket({ protocol: 'meshtastic', signal: { spreading_factor: 9, bandwidth_khz: 250 } }).chip, 'MF');
});

test('filter: all matches everything, a preset only itself, the choice is remembered', () => {
    const w = load();
    const F = w.MeshpointRadioViewFilter;
    const lf = { protocol: 'meshtastic', latest_spreading_factor: 11, latest_bandwidth_khz: 250 };
    const mc = { protocol: 'meshcore' };
    assert.strictEqual(F.current(), 'all');
    assert.ok(F.matchesNode(lf) && F.matchesNode(mc));
    F.set('mc');
    assert.strictEqual(F.current(), 'mc');
    assert.ok(!F.matchesNode(lf) && F.matchesNode(mc));
    F.set('bogus');
    assert.strictEqual(F.current(), 'mc');
});

test('packet table: preset column, data-preset, hidden by the filter', () => {
    const rows = [];
    const tbody = {
        children: rows,
        prepend(tr) { rows.unshift(tr); },
        removeChild(tr) { rows.splice(rows.indexOf(tr), 1); },
        get lastChild() { return rows[rows.length - 1]; },
    };
    const w = load({
        files: ['simple_packet_feed.js'],
        document: {
            getElementById: (id) => (id === 'tbody' ? tbody : null),
            createElement: () => ({ dataset: {}, hidden: false, classList: { add() {}, remove() {} }, addEventListener() {} }),
        },
    });
    vm.runInContext('window.__Feed = SimplePacketFeed;', w.__ctx);
    const feed = new w.__Feed('tbody', 50);
    feed._summarize = () => '';
    feed.addPacket({ protocol: 'meshtastic', source_id: 'aa', signal: { spreading_factor: 11, bandwidth_khz: 250 } });
    feed.addPacket({ protocol: 'meshtastic', source_id: 'bb', signal: { spreading_factor: 9, bandwidth_khz: 250 } });
    feed.addPacket({ protocol: 'meshcore', source_id: 'cc' });
    const presets = rows.map((tr) => tr.dataset.preset);
    assert.deepStrictEqual(presets, ['mc', 'mf', 'lf']);
    assert.match(rows[1].innerHTML, /packet-chip--medium" title="MediumFast">MF</);
    w.MeshpointRadioViewFilter.set('mf');
    assert.deepStrictEqual(rows.map((tr) => tr.hidden), [true, false, true]);
    feed.addPacket({ protocol: 'meshtastic', source_id: 'dd', signal: { spreading_factor: 11, bandwidth_khz: 250 } });
    assert.strictEqual(rows[0].hidden, true, 'a new LF row stays hidden while MF is selected');
    w.MeshpointRadioViewFilter.set('all');
    assert.ok(rows.every((tr) => !tr.hidden));
});

test('map marker: dot or diamond with the preset chip next to it (30b)', () => {
    const L = load().ModemPresetLabel;
    const lf = L.fromProtocolAndModem('meshtastic', 11, 250);
    const html = L.markerMarkup(lf, true, ' node-marker-wrap--recent');
    assert.match(html, /^<div class="node-marker-wrap node-marker-wrap--recent"><div class="node-marker__dot"><\/div>/);
    assert.match(html, /<span class="node-marker__preset packet-chip packet-chip--long">LF<\/span>/);
    assert.match(L.markerMarkup(L.fromProtocolAndModem('meshcore'), false, ''), /node-marker__diamond.*packet-chip--mc">MC</);
    assert.doesNotMatch(L.markerMarkup(null, true, ''), /node-marker__preset/);
});

test('narrow screens hide Freq/SF/Hops/Details but keep the Preset column (8)', () => {
    const css = fs.readFileSync(path.join(__dirname, '..', 'frontend/css/responsive.css'), 'utf8');
    const block = css.slice(css.indexOf('.packet-table th:nth-child(9)'), css.indexOf('{ display: none; }', css.indexOf('.packet-table th:nth-child(9)')));
    assert.ok(/nth-child\(12\)/.test(block) && !/nth-child\(8\)/.test(block), block);
});
