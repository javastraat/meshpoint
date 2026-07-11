/**
 * Settings → Meshpoint: display unit preferences (local browser only).
 */

class MeshpointDisplayForm {
    constructor(rootEl) {
        this.root = rootEl;
        this._statusEl = rootEl.querySelector('[data-display-units-status]');
        this._tempInputs = Array.from(rootEl.querySelectorAll('[data-display-temp]'));
        this._distInputs = Array.from(rootEl.querySelectorAll('[data-display-distance]'));
        this._msgToastInput = rootEl.querySelector('[data-display-msg-toast]');
        this._msgSoundInput = rootEl.querySelector('[data-display-msg-sound]');
        this._bind();
        this._syncFromStorage();
    }

    _bind() {
        const onChange = () => this._save();
        this._tempInputs.forEach((el) => el.addEventListener('change', onChange));
        this._distInputs.forEach((el) => el.addEventListener('change', onChange));
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

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }
}

window.MeshpointDisplayForm = MeshpointDisplayForm;
