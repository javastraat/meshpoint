// MeshCore cards show a connected USB capture companion even with native TX off.
// Ported idea from upstream KMX415/meshpoint 23a5fe7e. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(file, className) {
    const window = {};
    const ctx = vm.createContext({ window, console, document: {} });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
    return window[className];
}

const RadioCompanionCard = load('frontend/js/radio_companion_card.js', 'RadioCompanionCard');
const MeshcoreConfigCard = load('frontend/js/configuration/meshcore_card.js', 'MeshcoreConfigCard');

function config({ txEnabled, companions }) {
    return {
        transmit: { enabled: txEnabled },
        meshcore: { connected: false, status_note: txEnabled ? '' : 'transmit_disabled', companions },
    };
}

function radioCard(cfg) {
    const card = new RadioCompanionCard({});
    card._root = { innerHTML: '', classList: { add() {} } };
    card._renderOffline(cfg);
    return card._root.innerHTML;
}

function configCard(cfg) {
    const card = Object.create(MeshcoreConfigCard.prototype);
    card._body = { innerHTML: '' };
    card._setStatus = () => {};
    card._renderOffline(cfg);
    return card._body.innerHTML;
}

for (const txEnabled of [false, true]) {
    test(`capture connected, TX ${txEnabled ? 'on' : 'off'}: both cards say connected`, () => {
        const cfg = config({ txEnabled, companions: [{ name: 'meshcore_usb', connected: true }] });
        const radio = radioCard(cfg);
        assert.match(radio, /USB CONNECTED/);
        assert.match(radio, /status-lamp--ready/);
        assert.doesNotMatch(radio, />NONE</);
        const conf = configCard(cfg);
        assert.match(conf, /USB companion connected/);
        assert.doesNotMatch(conf, /No companion connected/);
    });
}

for (const companions of [undefined, [], [{ name: 'meshcore_usb', connected: false }]]) {
    test(`no connected capture (${JSON.stringify(companions)}): cards say none`, () => {
        const cfg = config({ txEnabled: false, companions });
        const radio = radioCard(cfg);
        assert.match(radio, />NONE</);
        assert.match(radio, /status-lamp--off/);
        assert.match(configCard(cfg), /No companion connected/);
    });
}
