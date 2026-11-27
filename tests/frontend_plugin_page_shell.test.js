// Plugin pages get data-plugin-page, so css/plugin_pages.css (upstream's shared plugin-page look,
// TODO 47b) applies to them and not to built-in pages. Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const el = () => ({ dataset: {}, style: {}, className: '', innerHTML: '', children: [],
    appendChild(c) { this.children.push(c); return c; } });

function mountOne(desc) {
    const content = el(), sublist = el();
    const document = {
        createElement: () => el(),
        getElementById: (id) => (id === 'app-content' ? content : null),
        querySelector: (sel) => (sel.includes('sidebar__sublist') ? sublist : null),
    };
    const window = { MESHPOINT_SIDEBAR_PLUGINS: [desc] };
    const ctx = vm.createContext({ window, document, console });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/sidebar/sidebar_plugin_registry.js'), 'utf8'), ctx);
    let mountedInto = null;
    window.registerSidebarPage({ route: desc.route, make: () => ({ mount(root) { mountedInto = root; } }) });
    window.mountPluginSidebarPages();
    return { section: content.children[0], mountedInto };
}

test('a plugin page section carries data-plugin-page with the plugin id', () => {
    const { section, mountedInto } = mountOne({ id: 'oled-display', route: 'oled', label: 'OLED', category: 'settings' });
    assert.strictEqual(section.className, 'section');
    assert.strictEqual(section.dataset.pluginPage, 'oled-display');
    assert.strictEqual(section.dataset.section, 'settings/oled');
    assert.strictEqual(mountedInto, section);
});

test('the shared stylesheet is loaded and only targets plugin pages and the theme editor', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'frontend/index.html'), 'utf8');
    assert.match(html, /href="css\/plugin_pages\.css"/);
    const css = fs.readFileSync(path.join(__dirname, '..', 'frontend/css/plugin_pages.css'), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '');
    for (const rule of css.split('}').map((r) => r.split('{')[0].trim()).filter(Boolean)) {
        if (rule.startsWith('@media')) continue;
        for (const sel of rule.replace(/^@media[^{]*\{/, '').split(/,(?![^(]*\))/)) {
            assert.match(sel.trim(), /data-plugin-page|theme-editor|^\.plugin-page|^\.page-hook-tabbar/, `unscoped selector: ${sel}`);
        }
    }
});

test('plugin dashboards (core .dashboard layout) keep full height and their maps', () => {
    const css = fs.readFileSync(path.join(__dirname, '..', 'frontend/css/plugin_pages.css'), 'utf8');
    assert.match(css, /\.section\[data-plugin-page\]:has\(> \.dashboard\)\s*\{\s*padding: 0; overflow: hidden;/);
    const panel = css.match(/\.section\[data-plugin-page\] \.dashboard \.panel \{([^}]*)\}/);
    assert.ok(panel && /height: 100%/.test(panel[1]), 'dashboard panels must keep height 100% (maps collapse otherwise)');
});

test('primary buttons keep their colour and the theme editor marks its active tab', () => {
    const css = fs.readFileSync(path.join(__dirname, '..', 'frontend/css/plugin_pages.css'), 'utf8');
    assert.match(css, /:is\(\.section\[data-plugin-page\], \.theme-editor\) \.terminal-button--primary \{[^}]*var\(--term-accent\)/);
    assert.match(css, /\.theme-editor :is\(\.lw-tab--active/);
});

test('every page (core and plugin) gets thin theme-coloured scrollbars', () => {
    const css = fs.readFileSync(path.join(__dirname, '..', 'frontend/css/dashboard.css'), 'utf8');
    assert.match(css, /\.section \{ scrollbar-color: var\(--overlay-strong\) transparent; \}/);
    assert.match(css, /\.section, \.section \* \{ scrollbar-width: thin; \}/);
});

test('dashboard stat cards only use styled sub-label classes', () => {
    // "24h / total" used .stat-card__subtitle, which has no style anywhere, so it rendered
    // as large plain text instead of the small grey .stat-card__sub every other card uses.
    const html = fs.readFileSync(path.join(__dirname, '..', 'frontend/index.html'), 'utf8');
    assert.doesNotMatch(html, /stat-card__subtitle/);
});
