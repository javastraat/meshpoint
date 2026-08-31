/**
 * Settings → Meshpoint: display unit preferences (local browser only),
 * plus the server-side default theme (admin -> dashboard.theme).
 */

class MeshpointDisplayForm {
    constructor(rootEl) {
        this.root = rootEl;
        this._statusEl = rootEl.querySelector('[data-display-units-status]');
        this._tempInputs = Array.from(rootEl.querySelectorAll('[data-display-temp]'));
        this._distInputs = Array.from(rootEl.querySelectorAll('[data-display-distance]'));
        this._msgToastInput = rootEl.querySelector('[data-display-msg-toast]');
        this._msgSoundInput = rootEl.querySelector('[data-display-msg-sound]');
        this._themeSelect = rootEl.querySelector('[data-default-theme]');
        this._bind();
        this._syncFromStorage();
        this._loadDefaultTheme();
    }

    _bind() {
        const onChange = () => this._save();
        this._tempInputs.forEach((el) => el.addEventListener('change', onChange));
        this._distInputs.forEach((el) => el.addEventListener('change', onChange));
        if (this._themeSelect) {
            this._themeSelect.addEventListener('change', () => this._saveDefaultTheme());
        }
        // Message notification switches write straight to the notifier —
        // they are independent per-browser flags, not display units.
        if (this._msgToastInput) {
            this._msgToastInput.addEventListener('change', () => {
                if (window.messageNotifier) {
                    window.messageNotifier.setToastEnabled(this._msgToastInput.checked);
                }
                this._setStatus('success', 'Saved. Message notification settings apply to this browser.');
            });
        }
        if (this._msgSoundInput) {
            this._msgSoundInput.addEventListener('change', () => {
                if (window.messageNotifier) {
                    window.messageNotifier.setSoundEnabled(this._msgSoundInput.checked);
                }
                this._setStatus('success', 'Saved. Message notification settings apply to this browser.');
            });
        }
    }

    _syncFromStorage() {
        const prefs = window.MeshpointDisplayUnits.getPrefs();
        this._tempInputs.forEach((el) => {
            el.checked = el.value === prefs.temperature;
        });
        this._distInputs.forEach((el) => {
            el.checked = el.value === prefs.distance;
        });
        if (this._msgToastInput && window.messageNotifier) {
            this._msgToastInput.checked = window.messageNotifier.isToastEnabled();
        }
        if (this._msgSoundInput && window.messageNotifier) {
            this._msgSoundInput.checked = window.messageNotifier.isSoundEnabled();
        }
    }

    _save() {
        const temp = this._tempInputs.find((el) => el.checked);
        const dist = this._distInputs.find((el) => el.checked);
        window.MeshpointDisplayUnits.savePrefs({
            temperature: temp ? temp.value : 'fahrenheit',
            distance: dist ? dist.value : 'imperial',
        });
        this._setStatus('success', 'Saved. Node cards and details will use these units.');
    }

    async _loadDefaultTheme() {
        if (!this._themeSelect) return;
        try {
            const res = await fetch('/api/themes', { credentials: 'same-origin' });
            if (!res.ok) return;
            const data = await res.json();
            const themes = Array.isArray(data.themes) ? data.themes : [];
            this._themeSelect.innerHTML = themes
                .map((t) => `<option value="${t.id}">${t.label || t.id}</option>`)
                .join('');
            this._themeSelect.value = data.default || 'dark';
        } catch (_e) {
            this._themeSelect.closest('fieldset')?.setAttribute('hidden', '');
        }
    }

    async _saveDefaultTheme() {
        const theme = this._themeSelect.value;
        try {
            const res = await fetch('/api/config/dashboard/theme', {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                this._setStatus('error', err.detail || `Could not save theme (${res.status}).`);
                return;
            }
            this._setStatus('success', 'Saved. New sessions default to this theme; your own choice in the topbar toggle still wins here.');
        } catch (_e) {
            this._setStatus('error', 'Could not reach the server to save the theme.');
        }
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }
}

window.MeshpointDisplayForm = MeshpointDisplayForm;
