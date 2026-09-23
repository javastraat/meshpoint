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
 * this whole JS environment, so a fresh instance starts with no idea
 * the disconnect it's about to see is expected -- the very first
 * WebSocket attempt on the reloaded page can still fail even once the
 * server is answering plain HTTP again (its WS-serving subsystem can
 * lag a beat behind), and this pill would otherwise label that
 * "Reconnecting...", which reads as "something's wrong" rather than
 * "we just restarted, hang on". `update_panel_controller.js` leaves a
 * `sessionStorage` flag right before triggering that reload -- the
 * only thing that survives the JS teardown -- and this class checks
 * it once, on the very next disconnect/connect cycle, for calmer
 * wording ("Restarting..." / "Restarted.").
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
    }

    _onDisconnected() {
        const wasFirstAttempt = !this._wasOnline;
        this._wasOnline = true;
        this._show();
        // Only worth checking on the very first disconnect this page
        // instance sees -- a later real reconnect (e.g. a network
        // blip minutes into the session) should read as an ordinary
        // reconnect, not borrow update wording from a stale flag.
        if (wasFirstAttempt) {
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
