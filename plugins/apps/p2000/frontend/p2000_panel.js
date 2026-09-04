/*
 * P2000 plugin -- Listener tab.
 *
 * Loaded (as <script defer>) into the dashboard by Meshpoint's plugin asset
 * injector when plugins.p2000.enabled is set. Registers a "P2000" tab on
 * the Listener page that reuses the core PagerPanel (its default
 * protocol/capcode/message row shape fits FLEX pages as-is, no custom row
 * renderer needed) -- same as how Pagers/POCSAG (still core) and the
 * ACARS/RTL433 plugins all reuse it.
 */
(function () {
    'use strict';

    if (typeof window.registerListenerPanel !== 'function' || !window.PagerPanel) {
        console.warn('P2000 plugin: listener panel registry or PagerPanel missing');
        return;
    }

    window.registerListenerPanel({
        tab: 'p2000',
        label: 'P2000',
        make: () => new window.PagerPanel('p2000', '/api/p2000', 'P2000'),
    });
})();
