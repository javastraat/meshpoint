// Settings -> Plugins -> Sources -> Browse as store cards (TODO 47a, look after upstream's plugin store).
// The cards must keep the old row's data-src-* hooks so install/update/batch keep working.
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ctx = vm.createContext({ window: {}, document: {}, console });
for (const f of ['frontend/js/settings/plugin_store_meta.js', 'frontend/js/settings/plugins_panel_controller.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', f), 'utf8'), ctx);
}
const { meshpointStoreMeta: meta, PluginsPanelController: C } = ctx.window;
const ctl = Object.create(C.prototype);
const card = (p, extra = {}) => ctl._catalogCardHtml({ plugin: { kind: 'app', version: '1.0.0', compatible: true, ...p }, ...extra });

test('known plugins, themes and fallbacks get a category', () => {
    assert.strictEqual(meta({ id: 'adsb' }).category, 'Aviation');
    assert.strictEqual(meta({ id: 'reticulum-call' }).category, 'Networks');
    assert.strictEqual(meta({ id: 'x', kind: 'theme', description: 'Dark' }).category, 'Themes');
    assert.strictEqual(meta({ id: 'new-rx', hook_host: 'rtlsdr', description: 'd' }).category, 'Radio');
    assert.strictEqual(meta({ id: 'thing', description: 'd' }).category, 'Other');
});

test('install, update, downgrade and reinstall keep their data-src hooks', () => {
    assert.match(card({ id: 'adsb' }), /data-src-install data-id="adsb" data-action="install"/);
    assert.match(card({ id: 'adsb', installed: true, update_available: true, installed_version: '0.9.0' }),
        /data-action="update" data-from="0.9.0" data-to="1.0.0"/);
    assert.match(card({ id: 'adsb', installed: true, update_available: true, installed_version: '2.0.0' }), /data-action="downgrade"/);
    assert.match(card({ id: 'adsb', installed: true, installed_version: '1.0.0' }), /data-action="reinstall"/);
    assert.match(card({ id: 'adsb', compatible: false }), /disabled title="Update Meshpoint first"/);
});

test('batch checkbox: selectable, remembered, disabled for downgrades', () => {
    assert.match(card({ id: 'adsb' }, { selected: new Set(['adsb']) }), /data-src-select data-id="adsb" data-kind="app"[^>]*checked/);
    assert.match(card({ id: 'adsb', installed: true, update_available: true, installed_version: '2.0.0' }), /data-src-select[^>]*disabled/);
});

test('badges, hook note, setup note and search text', () => {
    const html = card({ id: 'radio', hook_host: 'rtlsdr', has_setup: true, installed: true, installed_version: '1.0.0' });
    assert.match(html, /data-category="Radio"/);
    assert.match(html, /data-state="installed"/);
    assert.match(html, /Hooks into <code>rtlsdr<\/code>/);
    assert.match(html, /Runs a setup script after install/);
    assert.match(html, /data-store-text="[^"]*radio[^"]*rtlsdr/);
    assert.match(card({ id: 'adsb' }), /class="store-badge">available/);
});

test('catalog text is escaped and only http(s) homepages become links', () => {
    const html = card({ id: 'evil"><img src=x>', description: '<script>x</script>', homepage: 'javascript:alert(1)' });
    assert.doesNotMatch(html, /<img src=x>|<script>/);
    assert.doesNotMatch(html, /javascript:/);
    assert.match(card({ id: 'a', description: 'd', homepage: 'https://example.org' }), /href="https:\/\/example.org"/);
});

test('search text and category chip only hide cards; an empty grid says so', () => {
    const mk = (category, text) => ({ dataset: { category, storeText: text }, hidden: false });
    const cards = [mk('Aviation', 'adsb aviation air traffic'), mk('Radio', 'radio rtlsdr fm'), mk('Aviation', 'acars aviation')];
    const empty = { hidden: true };
    const count = { textContent: '(3)' };
    const grid = { querySelectorAll: () => cards, querySelector: () => empty, previousElementSibling: { querySelector: () => count } };
    const chips = ['All', 'Aviation', 'Radio'].map((c) => ({ dataset: { storeChip: c }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }));
    const catEl = { querySelectorAll: (sel) => (sel === '.store-grid' ? [grid] : chips) };
    const c = Object.create(C.prototype);
    c._storeFilters = new Map();
    const show = (text, category) => {
        c._storeFilters.set('u', { text, category });
        c._applyStoreFilter('u', catEl);
        return cards.map((x) => !x.hidden);
    };
    assert.deepStrictEqual(show('', 'All'), [true, true, true]);
    assert.strictEqual(count.textContent, '(3)');
    assert.deepStrictEqual(show('', 'Aviation'), [true, false, true]);
    assert.strictEqual(count.textContent, '(2 of 3)');
    assert.strictEqual(chips[1].attrs['aria-pressed'], 'true');
    assert.deepStrictEqual(show('air traffic', 'All'), [true, false, false]);
    assert.strictEqual(empty.hidden, true);
    assert.deepStrictEqual(show('nothing', 'All'), [false, false, false]);
    assert.strictEqual(empty.hidden, false);
});
