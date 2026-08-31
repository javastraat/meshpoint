/**
 * Theme controller.
 *
 * Sets a data-theme attribute on <html> and persists the choice.
 *
 * The set of available themes is discovered at runtime from
 * GET /api/themes, which scans frontend/themes/<id>/theme.json (see
 * src/api/theme_registry.py). Each non-baseline theme also ships a
 * theme.css, injected server-side into <head> so a persisted theme
 * paints correctly on first load. `dark` is the built-in baseline
 * (palette on :root in dashboard.css) and is always valid.
 *
 * Single responsibility: persist + apply. Settings UI flips the
 * attribute; CSS does the rest.
 */
const THEME_FALLBACK = [
    { id: 'dark', label: 'Dark', icon: 'moon' },
    { id: 'high-contrast', label: 'High contrast', icon: 'contrast' },
    { id: 'sunlight', label: 'Sunlight', icon: 'sun' },
];

class ThemeController {
    constructor(storageKey = 'meshpoint:theme:v1') {
        this._key = storageKey;
        this._current = this._readPersisted() || 'dark';
        this._themes = THEME_FALLBACK.slice();
        // Resolves once the /api/themes manifest has been folded in (or
        // the fetch has failed and the fallback stands). Consumers that
        // need the real label/icon list — e.g. the topbar toggle — await
        // this.
        this.ready = this._loadManifest();
    }

    init() { this.apply(this._current); }

    current() { return this._current; }

    /** Discovered themes: [{ id, label, icon }]. */
    themes() { return this._themes.slice(); }

    ids() { return this._themes.map((t) => t.id); }

    apply(theme) {
        const valid = this.ids();
        const next = valid.includes(theme) ? theme : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        this._current = next;
        try { localStorage.setItem(this._key, next); } catch (_e) {}
        return next;
    }

    cycle() {
        const order = this.ids();
        const idx = order.indexOf(this._current);
        const next = order[(idx + 1) % order.length];
        return this.apply(next);
    }

    async _loadManifest() {
        try {
            const res = await fetch('/api/themes', { credentials: 'same-origin' });
            if (!res.ok) return this._themes;
            const data = await res.json();
            if (Array.isArray(data.themes) && data.themes.length) {
                this._themes = data.themes.map((t) => ({
                    id: t.id,
                    label: t.label || t.id,
                    icon: t.icon || '',
                }));
            }
            // A persisted theme whose folder was removed falls back to dark.
            if (!this.ids().includes(this._current)) this.apply('dark');
        } catch (_e) {
            /* offline / pre-auth — fallback list stands */
        }
        return this._themes;
    }

    _readPersisted() {
        try { return localStorage.getItem(this._key); } catch (_e) { return null; }
    }
}

window.ThemeController = ThemeController;
window.themeController = new ThemeController();
