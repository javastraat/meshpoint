// Top-bar MeshCore badges follow the USB capture connection, also while native TX is off
// (idea from upstream tests/frontend/meshcore_topbar_capture.test.cjs; ours draws one badge
// per companion from meshcore.companions[], not one pill from capture_connected).
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
    return {
        children: [], attributes: {}, className: '', textContent: '', href: '',
        classList: { _set: new Set(), toggle(name, on) { if (on) this._set.add(name); else this._set.delete(name); } },
        setAttribute(name, value) { this.attributes[name] = value; },
        appendChild(child) { this.children.push(child); return child; },
    };
}

const window = {};
vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, '..', 'frontend/topbar/topbar_meshcore_chip.js'), 'utf8'),
    { window, document: { createElement: () => element() } },
);
const Chip = window.TopbarMeshcoreChip;

const find = (badge, cls) => badge.children.find((c) => c.className.split(' ')[0] === cls);
const status = (companions, reachable = true) => {
    const group = element();
    const chip = new Chip(group);
    chip.setDashboardReachable(reachable);
    // Top-level "connected" is the TX client's view: false with native TX off.
    chip.setMeshcore({ connected: false, status_note: 'transmit_disabled', companions });
    return group;
};

test('TX off, capture connected: badge says Companion, lamp connected', () => {
    const group = status([{ name: 'meshcore_usb', connected: true, radio: {} }]);
    assert.strictEqual(group.hidden, false);
    const badge = group.children[0];
    assert.strictEqual(find(badge, 'topbar-meshcore__name').textContent, 'Companion');
    assert.strictEqual(find(badge, 'topbar-meshcore__lamp').attributes['aria-label'], 'MeshCore companion connected');
});

test('capture not connected: No companion, lamp offline', () => {
    const badge = status([{ name: 'meshcore_usb', connected: false, radio: {} }]).children[0];
    assert.strictEqual(find(badge, 'topbar-meshcore__name').textContent, 'No companion');
    assert.strictEqual(find(badge, 'topbar-meshcore__lamp').attributes['aria-label'], 'MeshCore companion offline');
});

test('one badge per companion, labelled by suffix', () => {
    const group = status([
        { name: 'meshcore_usb_868', connected: true, radio: { name: 'PD2EMC' } },
        { name: 'meshcore_usb_2', connected: false, radio: {} },
    ]);
    assert.strictEqual(group.children.length, 2);
    assert.strictEqual(find(group.children[0], 'topbar-meshcore__name').textContent, 'PD2EMC (868)');
    assert.strictEqual(find(group.children[1], 'topbar-meshcore__name').textContent, 'No companion');
});

test('no companions configured: group hidden', () => {
    assert.strictEqual(status([]).hidden, true);
});

test('dashboard unreachable: Reconnecting… instead of the last state', () => {
    const badge = status([{ name: 'meshcore_usb', connected: true, radio: {} }], false).children[0];
    assert.strictEqual(find(badge, 'topbar-meshcore__name').textContent, 'Reconnecting…');
});
