/*
 * POCSAG plugin -- Listener tab.
 *
 * Loaded (as <script defer>) into the dashboard by Meshpoint's plugin asset
 * injector when plugins.pocsag.enabled is set. Registers a "POCSAG" tab on
 * the Listener page that reuses the core PagerPanel (its default
 * protocol/capcode/message row shape fits POCSAG pages as-is, no custom
 * row renderer needed) -- same as how Pagers (still core) and the
 * ACARS/RTL433/P2000 plugins all reuse it.
 */
(function () {
    'use strict';

    if (typeof window.registerListenerPanel !== 'function' || !window.PagerPanel) {
        console.warn('POCSAG plugin: listener panel registry or PagerPanel missing');
        return;
    }

    window.registerListenerPanel({
        tab: 'pocsag',
        label: 'POCSAG',
        make: () => new window.PagerPanel('pocsag', '/api/pocsag', 'POCSAG'),
    });
})();
