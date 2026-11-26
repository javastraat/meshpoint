// Viewer = read-only Messages (upstream b91d994b; TODO.md item 37d).
// Run: node --test tests/
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
    return {
        innerHTML: '', className: '', dataset: {}, hidden: false,
        classList: { add() {}, toggle() {} },
        addEventListener() {},
        querySelector(sel) {
            const cls = sel.replace(/^\./, '');
            return this.innerHTML.includes(cls) ? { addEventListener() {} } : null;
        },
    };
}

function load(readOnly) {
    const fetches = [];
    const window = { meshpointReadOnly: readOnly };
    const ctx = vm.createContext({
        window, console,
        document: { createElement: element, addEventListener() {} },
        fetch: async (url, init) => { fetches.push([url, init && init.method]); return { ok: true }; },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend/js/messaging_contacts.js'), 'utf8')
        + '\n;this.__C = MessagingContacts;', ctx);
    const contacts = Object.create(ctx.__C.prototype);
    contacts._conversations = [{ node_id: 'aabbccddeeff', unread_count: 2, protocol: 'meshcore' }];
    contacts.render = () => {};
    contacts._esc = (s) => String(s);
    return { contacts, fetches };
}

const convo = { node_id: 'aabbccddeeff', protocol: 'meshcore', unread_count: 2, node_name: 'X', last_message: 'hi' };

test('viewer: no read POST, unread count stays', async () => {
    const { contacts, fetches } = load(true);
    await contacts.markConversationRead('aabbccddeeff');
    assert.deepStrictEqual(fetches, []);
    assert.strictEqual(contacts._conversations[0].unread_count, 2);
});

test('admin: read POST as before', async () => {
    const { contacts, fetches } = load(false);
    await contacts.markConversationRead('aabbccddeeff');
    assert.deepStrictEqual(fetches, [['/api/messages/conversation/aabbccddeeff/read', 'POST']]);
});

test('viewer has no delete button, admin does', () => {
    for (const [readOnly, expected] of [[true, false], [false, true]]) {
        const { contacts } = load(readOnly);
        const el = contacts._buildConvoEl(convo);
        assert.strictEqual(el.innerHTML.includes('msg-convo__delete'), expected);
    }
});

test('the chat and New button follow the flag', () => {
    const chat = fs.readFileSync(path.join(__dirname, '..', 'frontend/js/messaging_chat.js'), 'utf8');
    assert.match(chat, /this\._sendBtn\.disabled = isUnmapped \|\| readOnly/);
    assert.match(chat, /if \(!window\.meshpointReadOnly\) \{\s*await fetch\(`\/api\/messages\/conversation\/\$\{nodeId\}\/read`/);
    const panel = fs.readFileSync(path.join(__dirname, '..', 'frontend/js/messaging.js'), 'utf8');
    assert.match(panel, /newBtn\.hidden = !!window\.meshpointReadOnly/);
    const app = fs.readFileSync(path.join(__dirname, '..', 'frontend/js/app.js'), 'utf8');
    assert.match(app, /window\.meshpointReadOnly = !!identity && !!identity\.role && identity\.role !== 'admin'/);
});
