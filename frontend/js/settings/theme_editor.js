/**
 * Settings → Themes.
 *
 *  - Default-theme picker (moved here from Settings → System): PUTs
 *    dashboard.theme so a fresh browser lands on it.
 *  - Theme builder: pick a base theme, tweak its palette with colour
 *    inputs, preview live on the whole dashboard, download a
 *    `theme.css` (+ `theme.json`) to drop into `frontend/themes/<id>/`.
 *    Download-only — nothing is written server-side.
 *
 * Preview: the base theme stays applied via `data-theme`; only the
 * tokens the user changed are pushed as inline custom properties on
 * <html>, and `meshpoint:themechange` fires so charts / the terminal
 * follow. Leaving the page clears the inline overrides.
 */
(function () {
    const COLOR = 'color';
    const ALPHA = 'alpha';

    const GROUPS = [
        {
            legend: 'Base',
            tokens: [
                ['--bg-primary', COLOR], ['--bg-secondary', COLOR], ['--bg-card', COLOR],
                ['--border', COLOR],
                ['--text-primary', COLOR], ['--text-secondary', COLOR], ['--text-muted', COLOR],
            ],
        },
        {
            legend: 'Accents',
            tokens: [
                ['--accent-green', COLOR], ['--accent-cyan', COLOR], ['--accent-blue', COLOR],
                ['--accent-purple', COLOR], ['--accent-amber', COLOR], ['--accent-red', COLOR],
            ],
        },
        {
            legend: 'Sidebar',
            tokens: [
                ['--sidebar-bg', COLOR], ['--sidebar-border', COLOR], ['--sidebar-accent', COLOR],
                ['--sidebar-text', COLOR], ['--sidebar-text-muted', COLOR],
            ],
        },
        {
            legend: 'Surfaces & overlays',
            tokens: [
                ['--bg-glass', ALPHA], ['--bg-inset', COLOR], ['--bg-popover', COLOR],
                ['--hairline', ALPHA], ['--overlay-weak', ALPHA], ['--overlay-med', ALPHA],
                ['--overlay-strong', ALPHA], ['--sunken', ALPHA], ['--scrim', ALPHA],
                ['--border-glow', ALPHA],
                ['--sidebar-item-hover', ALPHA], ['--sidebar-item-active-bg', ALPHA],
            ],
        },
    ];

    const ALL_TOKENS = GROUPS.flatMap((g) => g.tokens.map((t) => t[0]));
    const root = document.documentElement;

    // ---- colour parsing -------------------------------------------------
    function resolveVar(value, depth) {
        value = (value || '').trim();
        const m = value.match(/^var\(\s*(--[a-z0-9-]+)\s*(?:,([\s\S]*))?\)$/i);
        if (m && depth < 8) {
            const inner = getComputedStyle(root).getPropertyValue(m[1]).trim();
            if (inner) return resolveVar(inner, depth + 1);
            if (m[2]) return resolveVar(m[2], depth + 1);
        }
        return value;
    }

    function toRgba(str) {
        str = (str || '').trim().toLowerCase();
        let m = str.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})?$/);
        if (m) {
            return {
                r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16),
                a: m[4] != null ? parseInt(m[4], 16) / 255 : 1,
            };
        }
        m = str.match(/^#([0-9a-f])([0-9a-f])([0-9a-f])$/);
        if (m) {
            return { r: parseInt(m[1] + m[1], 16), g: parseInt(m[2] + m[2], 16), b: parseInt(m[3] + m[3], 16), a: 1 };
        }
        m = str.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?\s*\)$/);
        if (m) {
            let a = m[4] == null ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
            return { r: +m[1], g: +m[2], b: +m[3], a };
        }
        return null;
    }

    const hex2 = (n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
    const toHex = (c) => c ? `#${hex2(c.r)}${hex2(c.g)}${hex2(c.b)}` : '#000000';
    const toRgbaStr = (c) => `rgba(${Math.round(c.r)}, ${Math.round(c.g)}, ${Math.round(c.b)}, ${+c.a.toFixed(3)})`;

    // ---- read a theme's authored token values -------------------------
    function readTheme(themeId) {
        const prev = root.getAttribute('data-theme');
        // Drop any live-preview inline props so we read the theme's own values.
        const stash = {};
        ALL_TOKENS.forEach((n) => {
            const v = root.style.getPropertyValue(n);
            if (v) { stash[n] = v; root.style.removeProperty(n); }
        });
        if (themeId === 'dark') root.removeAttribute('data-theme');
        else root.setAttribute('data-theme', themeId);
        const out = {};
        ALL_TOKENS.forEach((name) => {
            out[name] = resolveVar(getComputedStyle(root).getPropertyValue(name), 0);
        });
        if (prev) root.setAttribute('data-theme', prev);
        else root.removeAttribute('data-theme');
        Object.entries(stash).forEach(([n, v]) => root.style.setProperty(n, v));
        return out;
    }

    class ThemeEditor {
        constructor(el) {
            this.el = el;
            this.defaultSel = el.querySelector('[data-default-theme]');
            this.defaultStatus = el.querySelector('[data-default-theme-status]');
            this.baseSel = el.querySelector('[data-te-base]');
            this.nameInput = el.querySelector('[data-te-name]');
            this.groupsEl = el.querySelector('[data-te-groups]');
            this.status = el.querySelector('[data-te-status]');
            this.themes = [];
            this.base = 'dark';
            this._nameAuto = true;   // track auto-vs-typed name
            this.values = {};      // working values, keyed by token
            this.baseValues = {};   // the chosen base theme's values
            this.darkValues = {};   // the :root baseline
            this.active = false;
        }

        bind() {
            this.baseSel?.addEventListener('change', () => this._loadBase(this.baseSel.value));
            this.nameInput?.addEventListener('input', () => {
                this._nameAuto = !this.nameInput.value.trim();
            });
            this.defaultSel?.addEventListener('change', () => this._saveDefault());
            this.el.querySelector('[data-te-reset]')?.addEventListener('click', () => this._loadBase(this.base));
            this.el.querySelector('[data-te-download]')?.addEventListener('click', () => this._download());
            this.el.querySelector('[data-te-download-json]')?.addEventListener('click', () => this._downloadJson());
        }

        async onActivated() {
            const tc = window.themeController;
            this._enteredTheme = tc ? tc.current() : (root.getAttribute('data-theme') || 'dark');
            if (!this._loaded) {
                await this._fetchThemes();
                this.darkValues = readTheme('dark');
                this._renderGroups();
                this._loadBase(this.defaultSel?.value || this._enteredTheme || 'dark');
                this._loaded = true;
            }
            this.active = true;
            this._applyPreview();
        }

        onLeft() {
            this.active = false;
            ALL_TOKENS.forEach((n) => root.style.removeProperty(n));
            this._setTheme(this._enteredTheme || 'dark');
        }

        _setTheme(themeId) {
            const tc = window.themeController;
            if (tc && typeof tc._setAttr === 'function') { tc._setAttr(themeId); return; }
            if (themeId === 'dark') root.removeAttribute('data-theme');
            else root.setAttribute('data-theme', themeId);
            try { window.dispatchEvent(new CustomEvent('meshpoint:themechange')); } catch (_e) {}
        }

        async _fetchThemes() {
            try {
                const res = await fetch('/api/themes', { credentials: 'same-origin' });
                const data = res.ok ? await res.json() : {};
                this.themes = Array.isArray(data.themes) ? data.themes : [];
                const opts = this.themes.map((t) => `<option value="${t.id}">${t.label || t.id}</option>`).join('');
                if (this.defaultSel) { this.defaultSel.innerHTML = opts; this.defaultSel.value = data.default || 'dark'; }
                if (this.baseSel) this.baseSel.innerHTML = opts;
            } catch (_e) {
                this._set(this.status, 'error', 'Could not load the theme list.');
            }
        }

        _renderGroups() {
            this.groupsEl.innerHTML = GROUPS.map((g) => `
                <div class="te-group">
                    <div class="te-group__legend">${g.legend}</div>
                    <div class="te-swatches">
                        ${g.tokens.map(([name, type]) => `
                            <label class="te-swatch" data-token="${name}">
                                <input type="color" class="te-swatch__chip" data-role="hex">
                                <span class="te-swatch__meta">
                                    <span class="te-swatch__name">${name.replace(/^--/, '')}</span>
                                    <span class="te-swatch__value" data-role="val"></span>
                                </span>
                                ${type === ALPHA ? '<input type="range" class="te-swatch__alpha" min="0" max="1" step="0.01" data-role="alpha" title="opacity">' : ''}
                            </label>`).join('')}
                    </div>
                </div>`).join('');

            this.groupsEl.querySelectorAll('.te-swatch').forEach((sw) => {
                const token = sw.dataset.token;
                const hex = sw.querySelector('[data-role="hex"]');
                const alpha = sw.querySelector('[data-role="alpha"]');
                const on = () => {
                    const c = toRgba(hex.value) || { r: 0, g: 0, b: 0, a: 1 };
                    if (alpha) c.a = parseFloat(alpha.value);
                    this.values[token] = alpha ? toRgbaStr(c) : toHex(c);
                    this._syncSwatch(sw);
                    if (this.active) {
                        root.style.setProperty(token, this.values[token]);
                        try { window.dispatchEvent(new CustomEvent('meshpoint:themechange')); } catch (_e) {}
                    }
                };
                hex.addEventListener('input', on);
                alpha?.addEventListener('input', on);
            });
        }

        _loadBase(themeId) {
            this.base = themeId || 'dark';
            if (this.baseSel) this.baseSel.value = this.base;
            this.baseValues = readTheme(this.base);
            this.values = { ...this.baseValues };
            this.groupsEl.querySelectorAll('.te-swatch').forEach((sw) => this._syncSwatch(sw, true));
            if (this.active) this._applyPreview();
            if (this._nameAuto) this.nameInput.value = `${this.base}-custom`;
        }

        _syncSwatch(sw, fromBase) {
            const token = sw.dataset.token;
            const val = this.values[token] || '';
            const c = toRgba(val);
            const hex = sw.querySelector('[data-role="hex"]');
            const alpha = sw.querySelector('[data-role="alpha"]');
            const label = sw.querySelector('[data-role="val"]');
            if (c) {
                if (fromBase) hex.value = toHex(c);
                if (alpha && fromBase) alpha.value = String(c.a);
            }
            label.textContent = val;
            sw.classList.toggle('te-swatch--changed', val && val !== this.baseValues[token]);
        }

        _applyPreview() {
            ALL_TOKENS.forEach((n) => {
                if (this.values[n] && this.values[n] !== this.baseValues[n]) {
                    root.style.setProperty(n, this.values[n]);
                } else {
                    root.style.removeProperty(n);
                }
            });
            this._setTheme(this.base);
        }

        _slug() {
            return (this.nameInput.value || 'my-theme').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'my-theme';
        }

        _label() {
            const raw = (this.nameInput.value || 'My theme').trim();
            return raw.charAt(0).toUpperCase() + raw.slice(1);
        }

        _themeCss() {
            const slug = this._slug();
            // Include every token that differs from the :root (dark) baseline,
            // so the file is self-contained regardless of base polarity.
            const lines = ALL_TOKENS
                .filter((t) => (this.values[t] || '') && this.values[t] !== this.darkValues[t])
                .map((t) => `    ${t}: ${this.values[t]};`);
            return `/* ${this._label()} -- generated by the Meshpoint theme builder`
                + ` (based on ${this.base}). Drop this folder in frontend/themes/. */\n\n`
                + `html[data-theme="${slug}"] {\n${lines.join('\n')}\n}\n`;
        }

        _themeJson() {
            return JSON.stringify(
                { id: this._slug(), label: this._label(), order: 100, icon: 'palette' },
                null, 2,
            ) + '\n';
        }

        _download() {
            const changed = ALL_TOKENS.filter((t) => (this.values[t] || '') && this.values[t] !== this.darkValues[t]).length;
            if (!changed) { this._set(this.status, 'error', 'Nothing to save — the palette still matches the dark baseline.'); return; }
            this._save(`theme.css`, this._themeCss(), 'text/css');
            this._set(this.status, 'success', `Saved theme.css (${changed} tokens). Put it in frontend/themes/${this._slug()}/ with theme.json, then restart.`);
        }

        _downloadJson() {
            this._save('theme.json', this._themeJson(), 'application/json');
        }

        _save(filename, text, mime) {
            const blob = new Blob([text], { type: mime });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        }

        async _saveDefault() {
            const theme = this.defaultSel.value;
            try {
                const res = await fetch('/api/config/dashboard/theme', {
                    method: 'PUT',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this._set(this.defaultStatus, 'error', err.detail || `Could not save (${res.status}).`);
                    return;
                }
                this._set(this.defaultStatus, 'success', 'Saved. New sessions default to this theme.');
            } catch (_e) {
                this._set(this.defaultStatus, 'error', 'Could not reach the server.');
            }
        }

        _set(node, kind, msg) {
            if (!node) return;
            node.dataset.kind = kind;
            node.textContent = msg;
        }
    }

    window.ThemeEditor = ThemeEditor;
})();
