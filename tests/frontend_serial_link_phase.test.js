// Meshtastic USB recovery shown in the top bar and Configuration -> Serial.
// Ported idea from upstream KMX415/meshpoint 459c4d7c. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Minimal DOM: enough for TopbarSerialChip._buildBadge().
class El {
    constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.textContent = '';
        const cls = new Set(); this._cls = cls;
        this.classList = { add: (...c) => c.forEach((x) => cls.add(x)),
            toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)), contains: (c) => cls.has(c) }; }
    set className(v) { this._cls.clear(); String(v).split(/\s+/).filter(Boolean).forEach((c) => this._cls.add(c)); }
    get className() { return [...this._cls].join(' '); }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    appendChild(c) { this.children.push(c); return c; }
    find(cls) { if (this._cls.has(cls)) return this;
        for (const c of this.children) { const f = c.find && c.find(cls); if (f) return f; } return null; }
}

function load(file, name, extra = {}) {
    const window = {};
    const ctx = vm.createContext({ window, console, document: { createElement: (t) => new El(t),
        addEventListener() {}, removeEventListener() {} }, ...extra });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
    return window[name];
}

const Chip = load('frontend/topbar/topbar_serial_chip.js', 'TopbarSerialChip');

function badge(dev, reachable = true) {
    const chip = new Chip({ hidden: false, textContent: '', appendChild() {} });
    chip._dashboardReachable = reachable;
    return chip._buildBadge(dev);
}

test('rebooting: amber phase with countdown instead of the preset', () => {
    const b = badge({ connected: false, reconnecting: true, link_phase: 'rebooting', retry_in_s: 12,
        modem_preset: 'LONG_FAST' });
    assert.ok(b.classList.contains('topbar-serial--rebooting'));
    assert.ok(!b.classList.contains('topbar-serial--offline'));
    assert.ok(b.find('topbar-serial__lamp--rebooting'));
    assert.strictEqual(b.find('topbar-serial__preset--phase').textContent, 'REBOOTING 12s');
});

test('reconnecting without countdown', () => {
    const b = badge({ connected: false, reconnecting: true, link_phase: 'reconnecting', retry_in_s: 0 });
    assert.ok(b.classList.contains('topbar-serial--reconnecting'));
    assert.strictEqual(b.find('topbar-serial__preset--phase').textContent, 'RECONNECTING');
});

test('connected and plain offline are unchanged', () => {
    const on = badge({ connected: true, modem_preset: 'LONG_FAST' });
    assert.ok(on.find('topbar-serial__lamp--online'));
    assert.strictEqual(on.find('topbar-serial__preset').textContent, 'LongFast');
    const off = badge({ connected: false });
    assert.ok(off.classList.contains('topbar-serial--offline'));
    assert.strictEqual(off.find('topbar-serial__preset--phase'), null);
});

test('dashboard unreachable wins over a stale phase', () => {
    const b = badge({ connected: false, link_phase: 'rebooting', retry_in_s: 9 }, false);
    assert.ok(b.classList.contains('topbar-serial--reconnecting'));
    assert.strictEqual(b.find('topbar-serial__preset--phase'), null);
});

const Card = load('frontend/js/configuration/serial_card.js', 'SerialConfigCard',
    { setTimeout, fetch: async () => ({ ok: false }) });

test('Serial card status line: rebooting, reconnecting, not connected', () => {
    const card = Object.create(Card.prototype);
    const reboot = card._readoutsHtml({ connected: false, reconnecting: true, link_phase: 'rebooting', retry_in_s: 7 });
    assert.match(reboot, /Rebooting\./);
    assert.match(reboot, /Next try in 7s/);
    assert.match(reboot, /data-serial-link-status/);
    assert.match(card._readoutsHtml({ connected: false, reconnecting: true, link_phase: 'reconnecting' }),
        /Reconnecting\..*Connecting…/s);
    assert.match(card._readoutsHtml(null), /Not connected\./);
});
