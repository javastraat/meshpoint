// MeshCore "Heard N repeats" button and heard-paths popover contents.
// Ported idea from upstream KMX415/meshpoint e8c4c6e1 + a451d1e2. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Just enough DOM for _esc(): a span whose textContent comes back escaped.
const document = {
    addEventListener() {},
    createElement: () => ({
        set textContent(v) {
            this.innerHTML = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },
    }),
};
const ctx = vm.createContext({ window: {}, console, document, setTimeout, clearTimeout });
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js/messaging_chat.js'), 'utf8')
    + '\n;this.__Chat = MessagingChat;', ctx);
const Chat = ctx.__Chat;

function chat() {
    const c = Object.create(Chat.prototype);
    c._feedback = new Map();
    return c;
}

test('sent MeshCore channel message: count as a button, no status word', () => {
    const html = chat()._buildMetaHtml({ direction: 'sent', protocol: 'meshcore', node_id: 'broadcast:meshcore:0',
        status: 'sent', heard_repeats: 2, timestamp: '2026-11-26T20:00:00Z' }, true);
    assert.match(html, /<button type="button" class="msg-heard"[^>]*>Heard 2 repeats<\/button>/);
    assert.doesNotMatch(html, /Delivery unconfirmed/);
});

test('MeshCore DM: delivery wording, no repeat button', () => {
    const c = chat();
    const pending = c._buildMetaHtml({ direction: 'sent', protocol: 'meshcore', node_id: 'aabbccddeeff',
        status: 'sent', heard_repeats: null }, true);
    assert.match(pending, /Sent · Delivery unconfirmed/);
    assert.doesNotMatch(pending, /msg-heard/);
    assert.match(c._buildMetaHtml({ direction: 'sent', protocol: 'meshcore', node_id: 'aabbccddeeff',
        status: 'delivered' }, true), /Delivered/);
});

test('feedback only goes up and delivered sticks', () => {
    const c = chat();
    const msg = { heard_repeats: 3, status: 'sent' };
    c._mergeFeedback(msg, { heard_repeats: 1, status: 'sent' });
    c._mergeFeedback(msg, { status: 'delivered' });
    assert.deepStrictEqual(msg, { heard_repeats: 3, status: 'delivered' });
});

test('other protocols are unchanged', () => {
    const html = chat()._buildMetaHtml({ direction: 'sent', protocol: 'meshtastic', status: 'sent',
        heard_repeats: 4 }, true);
    assert.doesNotMatch(html, /msg-heard|Heard/);
    assert.match(html, /· sent/);
});

test('popover lists each copy with names, ids and signal', () => {
    const html = chat()._pathsHtml({ count: 2, recorded: true, observations: [
        { hops: [{ id: 'aa', name: 'Roof <b>', ambiguous: false }], rssi: -71.5, snr: 4.25 },
        { hops: [{ id: 'bb', name: null, ambiguous: true }], rssi: null, snr: null },
    ] });
    assert.match(html, /2 heard copies/);
    assert.match(html, /Roof &lt;b&gt;/);              // escaped
    assert.match(html, /Ambiguous repeater/);
    assert.match(html, /-71\.5 <small>dBm<\/small>/);
    assert.match(html, /Unavailable/);
    assert.match(html, /Your radio/);
});

test('popover empty states', () => {
    assert.match(chat()._pathsHtml({ count: 0, recorded: true, observations: [] }), /No repeated paths heard yet/);
    assert.match(chat()._pathsHtml({ count: 3, recorded: false, observations: [] }), /weren’t recorded/);
    assert.match(chat()._pathsHtml({ count: 40, recorded: true,
        observations: Array.from({ length: 32 }, () => ({ hops: [] })) }), /first 32 saved/);
});
