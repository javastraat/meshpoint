/**
 * Reconnect storyboard pill.
 *
 * When the websocket drops and recovers, paint a small pill in the
 * top-right showing what's resyncing:
 *   "Reconnecting..." while disconnected
 *   "Resyncing telemetry" -> "rooms" -> "nodes" -> "messages" -> "ready"
 * on reconnect, then fades out.
 *
 * A full page reload after applying an update tears down and rebuilds
 * this whole JS environment, so a fresh instance has no memory of why
 * it's about to see a disconnect (if it even does -- the reload only
 * happens once the backend is confirmed HTTP-ready, so the fresh
 * page's first WebSocket attempt often just succeeds cleanly with no
 * visible hiccup at all). Waiting for a `disconnected` event to relabel
 * is the wrong trigger: `update_panel_controller.js` leaves a
 * `sessionStorage` flag right before triggering that reload -- the one
 * thing that survives the JS teardown -- and `init()` checks it
 * proactively, showing "Restarting..." immediately regardless of
 * whether a disconnect ever actually fires, clearing to "Restarted."
 * (or just fading out, if the connection was already fine) once the
 * WebSocket confirms it either way.
 *
 * Single responsibility: own the pill DOM and choreograph the
 * stage transitions. Listens to dashboardWs connect/disconnect
 * events; never touches transport itself.
 */
class ReconnectStoryboard {
    static STAGES = [
        { label: 'Resyncing telemetry...', delay: 350 },
        { label: 'Catching up on packets...', delay: 600 },
        { label: 'Refreshing nodes...', delay: 850 },
        { label: 'Ready.', delay: 1100 },
    ];

    static JUST_UPDATED_KEY = 'meshpoint:justUpdated';
    static JUST_UPDATED_MAX_AGE_MS = 120000; // stale flag guard, e.g. a crashed reload

    constructor(dashboardWs) {
        this._ws = dashboardWs;
        this._root = null;
        this._labelEl = null;
        this._dotEl = null;
        this._wasOnline = false;
        this._timer = null;
        this._isUpdateRestart = false;
    }

    mount() {
        if (document.getElementById('reconnect-storyboard')) return;
        const root = document.createElement('div');
        root.id = 'reconnect-storyboard';
        root.className = 'reconnect-pill';
        root.setAttribute('role', 'status');
        root.setAttribute('aria-live', 'polite');
        root.innerHTML = `
            <span class="reconnect-pill__dot" aria-hidden="true"></span>
            <span class="reconnect-pill__label" id="reconnect-pill-label">--</span>
        `;
        document.body.appendChild(root);
        this._root = root;
        this._labelEl = root.querySelector('#reconnect-pill-label');
        this._dotEl = root.querySelector('.reconnect-pill__dot');
    }

    init() {
        if (!this._ws) return;
        this._ws.on('connected', () => this._onConnected());
        this._ws.on('disconnected', () => this._onDisconnected());
        // Proactive: don't wait for a disconnect event that may never
        // come. If we just reloaded because of an update, say so the
        // instant this page exists, then let whatever the WebSocket
        // actually does (connects clean, or stumbles first) resolve it.
        if (this._consumeJustUpdatedFlag()) {
            this._isUpdateRestart = true;
            this._wasOnline = true; // so _onConnected takes the resync-stages branch
            this._show();
            this._setStage('reconnecting', 'Restarting...');
        }
    }

    _onDisconnected() {
        const wasFirstAttempt = !this._wasOnline;
        this._wasOnline = true;
        this._show();
        // Only worth checking on the very first disconnect this page
        // instance sees -- a later real reconnect (e.g. a network
        // blip minutes into the session) should read as an ordinary
        // reconnect, not borrow update wording from a stale flag.
        // (Usually already consumed and primed by init() above; this
        // is the fallback for whatever timing gap lets a disconnect
        // fire before init() got to check.)
        if (wasFirstAttempt && !this._isUpdateRestart) {
            this._isUpdateRestart = this._consumeJustUpdatedFlag();
        }
        this._setStage(
            'reconnecting',
            this._isUpdateRestart ? 'Restarting...' : 'Reconnecting...',
        );
    }

    _onConnected() {
        if (!this._wasOnline) {
            // First-ever connect, no disconnect ever seen -- no
            // storyboard, just hide. Still consume a pending flag so
            // it can't attach to some later, unrelated reconnect.
            this._wasOnline = true;
            this._consumeJustUpdatedFlag();
            this._hide();
            return;
        }
        this._show();
        this._setStage('syncing', this._isUpdateRestart ? 'Restarted.' : 'Reconnected.');
        this._isUpdateRestart = false;
        this._stepThroughStages(0);
    }

    _consumeJustUpdatedFlag() {
        try {
            const raw = sessionStorage.getItem(ReconnectStoryboard.JUST_UPDATED_KEY);
            if (!raw) return false;
            sessionStorage.removeItem(ReconnectStoryboard.JUST_UPDATED_KEY);
            const age = Date.now() - parseInt(raw, 10);
            return Number.isFinite(age) && age >= 0 && age < ReconnectStoryboard.JUST_UPDATED_MAX_AGE_MS;
        } catch (_e) {
            return false;
        }
    }

    _stepThroughStages(index) {
        if (this._timer) clearTimeout(this._timer);
        const stage = ReconnectStoryboard.STAGES[index];
        if (!stage) {
            this._timer = setTimeout(() => this._hide(), 700);
            return;
        }
        this._timer = setTimeout(() => {
            this._setStage(
                index === ReconnectStoryboard.STAGES.length - 1
                    ? 'ready'
                    : 'syncing',
                stage.label,
            );
            this._stepThroughStages(index + 1);
        }, stage.delay);
    }

    _setStage(state, label) {
        if (!this._root) return;
        this._labelEl.textContent = label;
        this._root.classList.remove(
            'reconnect-pill--reconnecting',
            'reconnect-pill--syncing',
            'reconnect-pill--ready',
        );
        this._root.classList.add(`reconnect-pill--${state}`);
    }

    _show() {
        if (this._root) this._root.classList.add('reconnect-pill--visible');
    }

    _hide() {
        if (this._root) this._root.classList.remove('reconnect-pill--visible');
    }
}

window.ReconnectStoryboard = ReconnectStoryboard;
