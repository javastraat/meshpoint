/**
 * Incoming-message notifications: an in-dashboard toast plus an optional
 * sound for websocket 'message_received' events.
 *
 * Fires only for direction === 'received' — never for messages we sent,
 * and never for 'overheard' traffic (monitor mode would toast half the
 * mesh; the Messages page already lists it). Stays quiet while the
 * Messages page itself is visible in a focused tab.
 *
 * Toast and sound are independent per-browser switches (localStorage):
 * toast defaults ON, sound defaults OFF. Settings > System flips them, so
 * does the command palette. The sound plays through soundEngine.playAlert
 * so it works without opting into the global UI-sounds chrome.
 *
 * Bursts coalesce: while the toast is showing, further messages update it
 * in place with a "+N more" line instead of stacking.
 */
class MessageNotifier {
    constructor() {
        this._toastKey = 'meshpoint:msg-toast:enabled:v1';
        this._soundKey = 'meshpoint:msg-sound:enabled:v1';
        this._el = null;
        this._hideTimer = null;
        this._extraCount = 0;
        this._lastConvo = null;
    }

    init(ws) {
        if (!ws || typeof ws.on !== 'function') return;
        ws.on('message_received', (data) => this._onMessage(data));
    }

    // Missing key means default: toast on, sound off.
    isToastEnabled() { return this._readFlag(this._toastKey, true); }
    isSoundEnabled() { return this._readFlag(this._soundKey, false); }

    setToastEnabled(enabled) {
        this._writeFlag(this._toastKey, enabled);
        if (enabled) this._show({ node_name: 'Message popups on', text: 'New messages will appear here.' }, { probe: true });
    }

    setSoundEnabled(enabled) {
        this._writeFlag(this._soundKey, enabled);
        if (enabled && window.soundEngine) window.soundEngine.playAlert('message');
    }

    _onMessage(data) {
        if (!data || data.direction !== 'received') return;
        if (this._onMessagesPage() && document.visibilityState === 'visible') return;

        if (this.isSoundEnabled() && window.soundEngine) {
            window.soundEngine.playAlert('message');
        }
        if (this.isToastEnabled()) {
            this._show(data);
        }
    }

    _onMessagesPage() {
        return (location.hash || '').replace(/^#\//, '').startsWith('messages');
    }

    _show(data, opts = {}) {
        const el = this._ensureEl();
        const showing = el.classList.contains('msg-notify--visible');

        if (showing && !opts.probe) {
            this._extraCount += 1;
        } else {
            this._extraCount = 0;
        }
        this._lastConvo = opts.probe ? null : data;

        el.querySelector('.msg-notify__name').textContent = data.node_name || data.node_id || 'Message';
        el.querySelector('.msg-notify__text').textContent = this._snippet(data.text);
        const more = el.querySelector('.msg-notify__more');
        more.textContent = this._extraCount > 0 ? `+${this._extraCount} more` : '';
        more.hidden = this._extraCount === 0;

        el.classList.add('msg-notify--visible');
        clearTimeout(this._hideTimer);
        this._hideTimer = setTimeout(() => this._hide(), 5000);
    }

    _hide() {
        if (this._el) this._el.classList.remove('msg-notify--visible');
        this._extraCount = 0;
    }

    _snippet(text) {
        const t = (text || '').trim();
        return t.length > 90 ? `${t.slice(0, 90)}…` : t;
    }

    _ensureEl() {
        if (this._el) return this._el;
        const el = document.createElement('div');
        el.className = 'msg-notify';
        el.setAttribute('role', 'status');
        el.innerHTML = [
            '<div class="msg-notify__name"></div>',
            '<div class="msg-notify__text"></div>',
            '<div class="msg-notify__more" hidden></div>',
        ].join('');
        el.addEventListener('click', () => {
            this._hide();
            this._openConversation();
        });
        document.body.appendChild(el);
        this._el = el;
        return el;
    }

    _openConversation() {
        const data = this._lastConvo;
        if (!data) return;
        if (window.sidebar && window.sidebar._router) {
            window.sidebar._router.navigate('messages');
        } else if (location.hash !== '#/messages') {
            location.hash = '#/messages';
        }
        setTimeout(() => {
            if (!window.messagingPanel) return;
            window.messagingPanel.openConversation({
                node_id: data.node_id,
                node_name: data.node_name || data.node_id,
                protocol: data.protocol || 'meshtastic',
                is_broadcast: (data.node_id || '').startsWith('broadcast:'),
            });
        }, 100);
    }

    _readFlag(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            if (raw === null) return fallback;
            return raw === '1';
        } catch (_e) { return fallback; }
    }

    _writeFlag(key, enabled) {
        try { localStorage.setItem(key, enabled ? '1' : '0'); } catch (_e) {}
    }
}

window.MessageNotifier = MessageNotifier;
window.messageNotifier = new MessageNotifier();
