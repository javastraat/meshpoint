/*
 * Pagers plugin -- Listener tab.
 *
 * Loaded (as <script defer>) into the dashboard by Meshpoint's plugin asset
 * injector when plugins.pagers.enabled is set. Registers a "Pagers" tab on
 * the Listener page that reuses the core PagerPanel (its default
 * protocol/capcode/message row shape fits POCSAG pages as-is, no custom
 * row renderer needed) -- same as the P2000/POCSAG/RTL433/ACARS plugins.
 */
(function () {
    'use strict';

    if (typeof window.registerListenerPanel !== 'function' || !window.PagerPanel) {
        console.warn('Pagers plugin: listener panel registry or PagerPanel missing');
        return;
    }

    window.registerListenerPanel({
        tab: 'pagers',
        label: 'Pagers',
        make: () => new window.PagerPanel('pagers', '/api/pagers', 'Pagers'),
    });
})();
