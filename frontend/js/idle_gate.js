/* Visibility-gated timers (UI quick-wins: idle discipline).

   A backgrounded dashboard tab used to keep polling /api/* and
   repainting sparklines/rails/badges at full rate — dozens of wasted
   fetch+render cycles per minute on a machine that is not even looking.
   MeshpointIdle.every() is a drop-in for setInterval with two rules:

     - the callback is skipped while document.hidden
     - when the tab becomes visible again every gated callback runs
       once immediately (the periodic cadence then continues normally),
       so returning to the tab shows fresh data without waiting out the
       interval.

   Returns a numeric id compatible with native clearInterval(), so the
   many `this._timer = ...; clearInterval(this._timer)` call sites and
   start/stop lifecycle code work unchanged.

   Deliberately NOT gated here: the auth pages' lockout/blip clocks
   (different document, always foreground), the update progress
   elapsed timer (cosmetic, driven by a Date diff anyway), and
   node_map's one-shot pop-fade chain (a few hundred ms, not a poller).
*/
(function () {
    'use strict';

    const gated = new Map(); // interval id -> callback

    // Call sites stop timers with plain clearInterval(this._timer) all
    // over the codebase; wrap it so gating metadata follows the timer
    // and a stopped poller is never replayed when the tab re-shows.
    const _clearInterval = window.clearInterval;
    window.clearInterval = function (id) {
        gated.delete(id);
        return _clearInterval(id);
    };

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        // One burst, deferred so every panel's reconnect/repaint settle
        // first; each callback is an idempotent refresh.
        setTimeout(() => {
            if (document.hidden) return;
            gated.forEach((fn) => {
                try { fn(); } catch (e) { console.error('idle-gate replay:', e); }
            });
        }, 150);
    });

    window.MeshpointIdle = {
        /** setInterval-compatible creator, paused while hidden. Argument
         * order matches native setInterval(fn, delay) -- every call site
         * in this patch invokes it that way, e.g.
         * `MeshpointIdle.every(() => this._load(), 15_000)`. */
        every(fn, ms) {
            const id = setInterval(() => {
                if (document.hidden) return;
                fn();
            }, ms);
            gated.set(id, fn);
            return id;
        },
        /** Unregister + clear. */
        stop(id) {
            gated.delete(id);
            clearInterval(id);
        },
        active() { return !document.hidden; },
    };
})();
