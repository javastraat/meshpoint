// Settings -> Updates: the apply/rollback progress panel sits at the top (under the header, above the
// channel card) and scrolls into view when it starts, instead of opening below "Automatic checks"
// where nobody saw it. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('progress panel comes before the channel card and the automatic checks', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'frontend/index.html'), 'utf8');
    const page = html.slice(html.indexOf('data-section="settings/updates"'));
    const progress = page.indexOf('data-update-progress');
    assert.ok(progress > 0);
    assert.ok(progress < page.indexOf('<article class="update-card">'), 'above the channel card');
    assert.ok(progress < page.indexOf('Automatic checks'));
    assert.ok(page.indexOf('data-update-release-notes') > page.indexOf('Automatic checks'), 'release notes stay below');
});

test('starting an update scrolls the panel into view', () => {
    const ctx = vm.createContext({ window: { setInterval: () => 1, clearInterval() {} }, document: { createElement: () => ({}) }, console, setInterval: () => 1, clearInterval() {} });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js/settings/update_progress_view.js'), 'utf8'), ctx);
    let scrolled = null;
    const root = {
        hidden: true, dataset: {}, innerHTML: '',
        querySelector: () => ({ appendChild() {}, textContent: '', scrollTop: 0, scrollHeight: 0 }),
        querySelectorAll: () => [],
        scrollIntoView(opts) { scrolled = opts; },
    };
    const view = new ctx.window.UpdateProgressView(root);
    view.start({ channelLabel: 'Custom branch', branch: 'upstream-sync' });
    assert.strictEqual(root.hidden, false);
    assert.strictEqual(JSON.stringify(scrolled), JSON.stringify({ behavior: 'smooth', block: 'start' }));
});
