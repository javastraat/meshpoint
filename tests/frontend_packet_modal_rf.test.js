// Packet detail RF rows: a 0 frequency/SF/BW means "not reported" (older MeshCore rows were
// stored before the receiver snapshot of item 27), not "0.000 MHz · SF0 · BW0". Idea from
// upstream tests/frontend/packet_protocol_metadata.test.cjs (fc15bc36); ours says "n/a" like
// every other missing value in the modal, and the feed table already skips zeros.
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ctx = vm.createContext({ window: {}, document: {} });
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js/packet_detail_modal.js'), 'utf8'), ctx);
const modal = ctx.window.PacketDetailModal;
const rows = (p) => Object.fromEntries(modal._rfRows(p).map((r) => [r.key, r.val]));

test('MeshCore row without receiver settings: n/a, signal still shown', () => {
    const r = rows({ protocol: 'meshcore', signal: { frequency_mhz: 0, spreading_factor: 0, bandwidth_khz: 0,
        coding_rate: '4/8', rssi: -53, snr: 11 } });
    assert.strictEqual(r.Frequency, 'n/a');
    assert.strictEqual(r.Modem, 'CR 4/8');
    assert.strictEqual(r.RSSI, '-53 dBm');
    assert.strictEqual(r.SNR, '11.0 dB');
});

test('MeshCore row with the receiver snapshot keeps its values', () => {
    const r = rows({ protocol: 'meshcore', signal: { frequency_mhz: 869.618, spreading_factor: 8,
        bandwidth_khz: 62.5, coding_rate: '4/8', rssi: -90, snr: 2.5 } });
    assert.strictEqual(r.Frequency, '869.618 MHz');
    assert.strictEqual(r.Modem, 'SF8 · BW62.5 · CR 4/8');
});

test('Meshtastic row unchanged', () => {
    const r = rows({ protocol: 'meshtastic', signal: { frequency_mhz: 869.525, spreading_factor: 11,
        bandwidth_khz: 250, coding_rate: '4/5', rssi: -80, snr: 0 } });
    assert.strictEqual(r.Frequency, '869.525 MHz');
    assert.strictEqual(r.Modem, 'SF11 · BW250 · CR 4/5');
    assert.strictEqual(r.SNR, '0.0 dB'); // a real 0 dB SNR stays
});
