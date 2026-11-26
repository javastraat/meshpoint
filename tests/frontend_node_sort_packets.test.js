// Node list "Sort: Packets" (upstream b91d994b; comparator by yourasmit15-web, upstream PR #128).
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ctx = vm.createContext({ window: {}, console, localStorage: { getItem: () => null } });
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js/node_cards_sort.js'), 'utf8')
    + '\n;this.__Sort = MeshpointNodeCardsSort;', ctx);
const Sort = ctx.__Sort;

const node = (id, packet_count, last_heard) => ({ node_id: id, packet_count, last_heard });
const ids = (list) => list.map((n) => n.node_id).join(',');

test('most packets first, missing/zero last, ties by last heard', () => {
    const nodes = [
        node('zero', 0, '2026-11-26T10:00:00Z'),
        node('few', 3, '2026-11-26T09:00:00Z'),
        node('many', 120, '2026-11-26T08:00:00Z'),
        node('none', undefined, '2026-11-26T11:00:00Z'),
        node('few-newer', 3, '2026-11-26T12:00:00Z'),
    ];
    assert.strictEqual(ids(Sort.applySort(nodes, 'packets')), 'many,few-newer,few,none,zero');
});

test('favourites stay pinned on top', () => {
    const nodes = [node('a', 1, '2026-11-26T10:00:00Z'), node('b', 50, '2026-11-26T10:00:00Z')];
    assert.strictEqual(ids(Sort.applySort(nodes, 'packets', new Set(['a']))), 'a,b');
});

test('the dashboard offers the option', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'frontend/index.html'), 'utf8');
    assert.match(html, /<option value="packets">Sort: Packets<\/option>/);
    const cards = fs.readFileSync(path.join(__dirname, '..', 'frontend/js/node_cards.js'), 'utf8');
    assert.match(cards, /SORT_KEYS = new Set\(\[[^\]]*'packets'/);
});
