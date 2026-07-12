/**
 * Modal listing a repeater's reported neighbours -- secondhand RF
 * observations (the repeater's own radio heard these, not Meshpoint's),
 * freshest-first, with names resolved against the known roster where a
 * pubkey prefix already matches. Reuses the packet detail modal's
 * pdm-* CSS classes for a consistent look.
 */
class NeighboursModal {
    constructor() {
        this._overlay = null;
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    show(repeaterName, neighbours) {
        this.close();

        const overlay = document.createElement('div');
        overlay.className = 'pdm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Repeater neighbours');

        const modal = document.createElement('div');
        modal.className = 'pdm-modal';
        modal.addEventListener('click', (e) => e.stopPropagation());

        const sorted = (neighbours || [])
            .slice()
            .sort((a, b) => (a.secs_ago ?? Infinity) - (b.secs_ago ?? Infinity));

        modal.innerHTML = `
            <header class="pdm-modal__header">
                <div>
                    <h2 class="pdm-modal__title">Neighbours</h2>
                    <div class="pdm-modal__meta">${this._esc(repeaterName)} · ${sorted.length} reported</div>
                </div>
                <button type="button" class="pdm-modal__close" aria-label="Close">&times;</button>
            </header>
            <div class="pdm-modal__body">
                <div class="nbm-list"></div>
            </div>
        `;

        const list = modal.querySelector('.nbm-list');
        if (sorted.length) {
            sorted.forEach((n) => list.appendChild(this._row(n)));
        } else {
            list.innerHTML = '<div class="pdm-row">No neighbours reported yet.</div>';
        }

        modal.querySelector('.pdm-modal__close').addEventListener('click', () => this.close());
        overlay.addEventListener('click', () => this.close());
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;

        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.pdm-modal__close').focus();
    }

    close() {
        document.removeEventListener('keydown', this._onKeyDown);
        if (this._overlay) {
            this._overlay.remove();
            this._overlay = null;
        }
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') this.close();
    }

    _row(n) {
        const row = document.createElement('div');
        row.className = 'pdm-row nbm-row';
        const label = n.name
            ? `${this._esc(n.name)} <span class="nbm-row__key">(${this._esc(n.pubkey)})</span>`
            : this._esc(n.pubkey);
        row.innerHTML = `
            <span class="pdm-row__val nbm-row__name">${label}</span>
            <span class="pdm-row__val nbm-row__meta">${this._ago(n.secs_ago)} · SNR ${this._snr(n.snr)}</span>
        `;
        if (window.nodeDrawer) {
            row.classList.add('nbm-row--clickable');
            row.addEventListener('click', () => {
                window.nodeDrawer.open({
                    node_id: n.pubkey,
                    long_name: n.name || n.pubkey,
                    protocol: 'meshcore',
                });
            });
        }
        return row;
    }

    _ago(secs) {
        if (secs == null) return 'unknown';
        if (secs < 90) return 'just now';
        if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
        if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
        return `${Math.floor(secs / 86400)}d ago`;
    }

    _snr(snr) {
        return snr != null ? `${Number(snr).toFixed(1)} dB` : 'n/a';
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.NeighboursModal = new NeighboursModal();
