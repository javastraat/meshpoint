/**
 * Reticulum Call -- a "Call" tab hooked into the Reticulum page
 * (window.registerPageHook, host: "reticulum" -- see plugin.toml's
 * [hook] table and frontend/sidebar/page_hook_registry.js for the seam
 * itself).
 *
 * Talks to the *reticulum* plugin's own backend, not one of its own --
 * this plugin has no backend beyond a no-op register() (see
 * backend/__init__.py). Everything here is the client half of the
 * byte-pipe built in plugins/apps/reticulum/backend/audio_call.py +
 * call_routes.py:
 *
 *   POST /api/reticulum/call/initiate        -- dial out
 *   POST /api/reticulum/call/{hash}/hangup   -- end a call
 *   WS   /api/reticulum/call/{hash}/audio    -- the actual audio, one
 *                                                binary frame per
 *                                                Codec2-encoded chunk,
 *                                                each way
 *   WS event "reticulum_incoming_call" (on window.concentratorWS, the
 *   dashboard's own shared socket -- same one messaging.js listens to
 *   for "message_received") -- fired when a peer's call link connects.
 *
 * Wire format is deliberately NOT reticulum-meshchat's own (that wraps
 * each frame in a protobuf AudioCallPayload carrying the codec mode
 * alongside the bytes) -- every frame here is just
 * [1 mode-index byte][codec2-encoded bytes], no protobuf dependency to
 * vendor. This means real interop with an actual Sideband/meshchat
 * peer's audio calls is NOT guaranteed (their framing differs) --
 * meshpoint-to-meshpoint calls are what this targets. If real interop
 * ever matters, the fix is matching their exact frame shape, not
 * something guessed at here.
 *
 * Ringing/answer semantics: there aren't any, by design -- confirmed
 * against reticulum-meshchat's own CallPage.vue, an RNS.Link reaches
 * ACTIVE the moment the destination responds, with no separate
 * consent step at the protocol level. An "incoming call" here just
 * means a link connected; the only real choice the UI offers is
 * whether to open the audio bridge and actually join.
 */

const RT_CALL_MODES = window.ReticulumCallCodec.MODES;
const RT_CALL_DEFAULT_MODE = window.ReticulumCallCodec.DEFAULT_MODE;
const RT_CALL_SAMPLE_RATE = 8000;
const RT_CALL_WORKLET_URL = '/plugins/apps/reticulum-call/codec2/processor.js';
const RT_CALL_WORKLET_NAME = 'reticulum-call-audio-processor';

class ReticulumCallHookPanel {
    constructor() {
        this._root = null;
        this._state = 'idle'; // idle | dialing | in-call
        this._callHash = null;
        this._isOutbound = false;
        this._mode = RT_CALL_DEFAULT_MODE;
        this._ws = null;
        this._audioCtx = null;
        this._workletNode = null;
        this._micStream = null;
        this._mediaStreamSource = null;
        this._nextPlayTime = 0;
        this._incomingCalls = new Map(); // call_hash -> {node_id, node_name}
        this._wsUnsubscribe = null;
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.innerHTML = `
            <div class="rtcall">
                <div class="rtcall__dial" data-rtcall-dial>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Destination hash</span>
                        <input class="cfg-field__input" type="text" data-rtcall-dest
                               placeholder="peer's Reticulum destination hash"
                               autocomplete="off" spellcheck="false">
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Codec2 mode</span>
                        <select class="cfg-field__input" data-rtcall-mode>
                            ${RT_CALL_MODES.map((m) => `<option value="${m}" ${m === RT_CALL_DEFAULT_MODE ? 'selected' : ''}>${m}</option>`).join('')}
                        </select>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary" type="button" data-rtcall-dial-btn>Call</button>
                    </div>
                </div>
                <div class="rtcall__incoming" data-rtcall-incoming hidden></div>
                <div class="rtcall__active" data-rtcall-active hidden>
                    <p class="rtcall__status" data-rtcall-status></p>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--danger" type="button" data-rtcall-hangup-btn>Hang up</button>
                    </div>
                </div>
                <p class="cfg-status" data-rtcall-msg aria-live="polite"></p>
                <p class="cfg-field__hint">
                    Voice over Reticulum, Codec2 encoded. Works meshpoint-to-meshpoint;
                    not guaranteed to interoperate with Sideband/reticulum-meshchat's own
                    calls (different wire framing). Call quality depends entirely on the
                    link underneath -- fine over the TCP backbone, marginal over LoRa.
                </p>
            </div>
        `;

        this._destEl = this._q('[data-rtcall-dest]');
        this._modeEl = this._q('[data-rtcall-mode]');
        this._dialSectionEl = this._q('[data-rtcall-dial]');
        this._incomingEl = this._q('[data-rtcall-incoming]');
        this._activeEl = this._q('[data-rtcall-active]');
        this._statusEl = this._q('[data-rtcall-status]');
        this._msgEl = this._q('[data-rtcall-msg]');

        this._q('[data-rtcall-dial-btn]')?.addEventListener('click', () => this._dial());
        this._q('[data-rtcall-hangup-btn]')?.addEventListener('click', () => this._hangup());

        if (window.concentratorWS && typeof window.concentratorWS.on === 'function') {
            this._wsUnsubscribe = window.concentratorWS.on(
                'reticulum_incoming_call', (data) => this._onIncomingCall(data),
            );
        }

        this._render();
    }

    show() {}

    hide() {}

    _q(sel) {
        return this._root ? this._root.querySelector(sel) : null;
    }

    _setMsg(kind, text) {
        if (!this._msgEl) return;
        this._msgEl.dataset.kind = kind;
        this._msgEl.textContent = text;
    }

    _onIncomingCall(data) {
        if (!data || !data.call_hash) return;
        this._incomingCalls.set(data.call_hash, {
            node_id: data.node_id || '', node_name: data.node_name || '',
        });
        this._renderIncoming();
    }

    _renderIncoming() {
        if (!this._incomingEl) return;
        if (this._state === 'in-call' || this._incomingCalls.size === 0) {
            this._incomingEl.hidden = true;
            this._incomingEl.innerHTML = '';
            return;
        }
        this._incomingEl.hidden = false;
        this._incomingEl.innerHTML = [...this._incomingCalls.entries()].map(([hash, info]) => `
            <div class="rtcall__incoming-row" data-rtcall-incoming-hash="${this._esc(hash)}">
                <span>Incoming call from ${this._esc(info.node_name || info.node_id || hash)}</span>
                <button class="terminal-button terminal-button--primary" type="button" data-rtcall-join>Join</button>
                <button class="terminal-button" type="button" data-rtcall-ignore>Ignore</button>
            </div>
        `).join('');
        this._incomingEl.querySelectorAll('[data-rtcall-incoming-hash]').forEach((row) => {
            const hash = row.dataset.rtcallIncomingHash;
            row.querySelector('[data-rtcall-join]')?.addEventListener('click', () => this._joinIncoming(hash));
            row.querySelector('[data-rtcall-ignore]')?.addEventListener('click', () => {
                this._incomingCalls.delete(hash);
                this._renderIncoming();
            });
        });
    }

    async _joinIncoming(callHash) {
        this._incomingCalls.delete(callHash);
        this._renderIncoming();
        await this._startCall(callHash, false);
    }

    async _dial() {
        const destination = (this._destEl?.value || '').trim();
        if (!destination) {
            this._setMsg('error', 'Enter a destination hash first.');
            return;
        }
        this._mode = this._modeEl?.value || RT_CALL_DEFAULT_MODE;
        this._setMsg('pending', 'Dialing…');
        try {
            const r = await fetch('/api/reticulum/call/initiate', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ destination_hash: destination }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) {
                this._setMsg('error', body.detail || `Call failed (HTTP ${r.status}).`);
                return;
            }
            await this._startCall(body.call_hash, true);
        } catch (_e) {
            this._setMsg('error', 'Network error.');
        }
    }

    async _startCall(callHash, isOutbound) {
        this._mode = this._modeEl?.value || RT_CALL_DEFAULT_MODE;
        this._callHash = callHash;
        this._isOutbound = isOutbound;
        this._state = 'in-call';
        this._render();
        this._setMsg('pending', 'Connecting audio…');

        try {
            await this._startAudio();
        } catch (e) {
            console.error('Reticulum call: could not start audio', e);
            this._setMsg('error', 'Microphone access failed — check browser permissions.');
            this._endCallLocally();
            return;
        }

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${proto}//${location.host}/api/reticulum/call/${encodeURIComponent(callHash)}/audio`);
        ws.binaryType = 'arraybuffer';
        this._ws = ws;

        ws.onopen = () => {
            this._setMsg('success', 'Call connected.');
            this._startMicCapture();
        };
        ws.onmessage = (event) => this._onAudioFrame(event.data);
        ws.onclose = () => {
            if (this._callHash === callHash) this._endCallLocally();
        };
        ws.onerror = () => {
            this._setMsg('error', 'Audio connection error.');
        };
    }

    async _hangup() {
        if (!this._callHash) return;
        const hash = this._callHash;
        try {
            await fetch(`/api/reticulum/call/${encodeURIComponent(hash)}/hangup`, {
                method: 'POST', credentials: 'same-origin',
            });
        } catch (_e) { /* best-effort -- still tear down locally either way */ }
        this._endCallLocally();
    }

    _endCallLocally() {
        if (this._ws) {
            try { this._ws.close(); } catch (_e) {}
            this._ws = null;
        }
        this._stopAudio();
        this._callHash = null;
        this._state = 'idle';
        this._setMsg('', 'Call ended.');
        this._render();
        this._renderIncoming();
    }

    _render() {
        if (this._dialSectionEl) this._dialSectionEl.hidden = this._state !== 'idle';
        if (this._activeEl) this._activeEl.hidden = this._state !== 'in-call';
        if (this._statusEl) {
            this._statusEl.textContent = this._state === 'in-call'
                ? `${this._isOutbound ? 'Calling' : 'In call'} — mode ${this._mode}`
                : '';
        }
        this._renderIncoming();
    }

    // ── Audio: mic capture -> Codec2 encode -> WS, and WS -> Codec2 decode -> playback ──

    async _startAudio() {
        this._audioCtx = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: RT_CALL_SAMPLE_RATE,
        });
        await this._audioCtx.audioWorklet.addModule(RT_CALL_WORKLET_URL);
        this._workletNode = new AudioWorkletNode(this._audioCtx, RT_CALL_WORKLET_NAME);
        this._micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this._mediaStreamSource = this._audioCtx.createMediaStreamSource(this._micStream);
        this._mediaStreamSource.connect(this._workletNode);
        this._nextPlayTime = 0;
    }

    _startMicCapture() {
        if (!this._workletNode) return;
        this._workletNode.port.onmessage = async (event) => {
            if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
            try {
                const encoded = await window.ReticulumCallCodec.encode(this._mode, event.data);
                if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                    // 1-byte mode index prefix so the receiver always
                    // decodes with the mode that was actually used to
                    // encode, regardless of what its own UI has selected
                    // -- two ends picking different modes would otherwise
                    // silently decode to garbage.
                    const modeIndex = RT_CALL_MODES.indexOf(this._mode);
                    const framed = new Uint8Array(encoded.length + 1);
                    framed[0] = modeIndex >= 0 ? modeIndex : 0;
                    framed.set(encoded, 1);
                    this._ws.send(framed);
                }
            } catch (e) {
                console.error('Reticulum call: encode failed', e);
            }
        };
    }

    async _onAudioFrame(data) {
        if (!this._audioCtx) return;
        try {
            const bytes = new Uint8Array(data);
            if (bytes.length < 2) return; // at least the mode byte + something to decode
            const mode = RT_CALL_MODES[bytes[0]] || RT_CALL_DEFAULT_MODE;
            const encoded = bytes.subarray(1);
            const samples = await window.ReticulumCallCodec.decode(mode, encoded);
            this._playSamples(samples);
        } catch (e) {
            console.error('Reticulum call: decode failed', e);
        }
    }

    _playSamples(samples) {
        if (!this._audioCtx || samples.length === 0) return;
        const buffer = this._audioCtx.createBuffer(1, samples.length, RT_CALL_SAMPLE_RATE);
        buffer.copyToChannel(samples, 0);
        const source = this._audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(this._audioCtx.destination);
        const now = this._audioCtx.currentTime;
        const startAt = Math.max(now, this._nextPlayTime);
        source.start(startAt);
        this._nextPlayTime = startAt + buffer.duration;
    }

    _stopAudio() {
        if (this._workletNode) {
            this._workletNode.port.onmessage = null;
            this._workletNode.disconnect();
            this._workletNode = null;
        }
        if (this._mediaStreamSource) {
            this._mediaStreamSource.disconnect();
            this._mediaStreamSource = null;
        }
        if (this._micStream) {
            this._micStream.getTracks().forEach((t) => t.stop());
            this._micStream = null;
        }
        if (this._audioCtx && this._audioCtx.state !== 'closed') {
            this._audioCtx.close();
        }
        this._audioCtx = null;
        this._nextPlayTime = 0;
    }

    _esc(value) {
        const div = document.createElement('div');
        div.textContent = String(value ?? '');
        return div.innerHTML;
    }
}

window.registerPageHook({
    host: 'reticulum',
    label: 'Call',
    make: () => new ReticulumCallHookPanel(),
});
