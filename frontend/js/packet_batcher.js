/* rAF-batched WebSocket packet fan-out (UI quick-wins: traffic storm
   responsiveness).

   index.html's WS 'packet' listener used to run feed/map/node-card
   DOM updates synchronously per packet. On a busy repeater (many
   packets/s) that serialized N DOM mutations per message and could
   starve input for seconds. Now app.js registers one batched handler:
   packets queue, drain inside animation frames under an ~8 ms/frame
   budget, strict FIFO (order of every component's data model is
   preserved — coalescing renders, if ever, belongs to the Phase 2
   per-component rewrite, not here), and any remainder reschedules to
   the next frame. Browsing stays fluid at 20+ packets/s because the
   main thread yields between frames like everywhere else.

   Hidden-tab rule: requestAnimationFrame never fires in a background
   tab, and letting the queue grow until the user returns would turn
   the first visible frame into a giant catch-up. So while
   document.hidden, packets bypass the queue and hit the handler
   directly — the consumer's own policy then decides what "apply"
   means (app.js skips all dashboard DOM work while hidden and lets
   the poller re-sync on return; see route-aware skip note there).

   Safety valve: if the live queue exceeds MAX_QUEUED (a pathological
   storm outrunning frame budget even across frames), the oldest
   overflow entries are applied immediately instead of dropped — the
   data model must never lose a packet, only its render may be late.
*/
(function () {
    'use strict';

    const FRAME_BUDGET_MS = 8;
    const MAX_QUEUED = 2000;

    let handler = null;
    const queue = [];
    let scheduled = false;
    let droppedWarned = false;

    function flush() {
        scheduled = false;
        if (!handler) return;
        const start = performance.now();
        while (queue.length && (performance.now() - start) < FRAME_BUDGET_MS) {
            try { handler(queue.shift()); }
            catch (e) { console.error('packet batch handler:', e); }
        }
        if (queue.length) schedule();
    }

    function schedule() {
        if (scheduled) return;
        scheduled = true;
        if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flush);
        else setTimeout(flush, 16);
    }

    window.MeshpointPacketBatch = {
        /** fn(packet) — called once per queued packet, in order. */
        init(fn) { handler = fn; },
        push(packet) {
            if (!handler) { handler_placeholder(packet); return; }
            if (document.hidden) {
                try { handler(packet); }
                catch (e) { console.error('packet handler (hidden):', e); }
                return;
            }
            queue.push(packet);
            if (queue.length > MAX_QUEUED) {
                const overflow = queue.splice(0, queue.length - MAX_QUEUED);
                if (!droppedWarned) {
                    droppedWarned = true;
                    console.warn('packet storm: applying', overflow.length,
                        'queued packets out-of-frame (once)');
                }
                overflow.forEach((p) => { try { handler(p); } catch (_) {} });
                // fall through: the kept remainder still drains per frame
            }
            schedule();
        },
        /** Test hook: process the queue synchronously. */
        _flushNow: flush,
    };

    function handler_placeholder(packet) {
        // init() not called yet (startup ordering): do not lose it.
        queue.push(packet);
        schedule();
    }
})();
