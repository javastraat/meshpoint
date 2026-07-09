/**
 * Topbar — Meshtastic USB serial device chip(s).
 *
 * One small cyan badge per configured `capture.serial` device (T5
 * multi-stick support). Unlike MeshCore's single TX-bound "primary"
 * companion, every serial device is a passive capture-only source
 * (Meshtastic TX from the dashboard goes through the concentrator,
 * not a USB stick) -- there's no single "the" device, so this renders
 * one badge per configured stick and hides the whole group when none
 * are configured.
 */
class TopbarSerialChip {
    constructor(groupEl) {
        this._group = groupEl;
    }

    setSerial(devices) {
        const list = Array.isArray(devices) ? devices : [];
        this._group.hidden = list.length === 0;
        this._group.textContent = '';
        list.forEach((dev) => this._group.appendChild(this._buildBadge(dev)));
    }

    _buildBadge(dev) {
        const connected = Boolean(dev.connected);
        const label = this._labelFromName(dev.name);

        const root = document.createElement('span');
        root.className = 'topbar-serial';
        root.setAttribute(
            'aria-label',
            `Meshtastic USB${label ? ` ${label}` : ''} ${connected ? 'connected' : 'offline'}`,
        );

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'USB';
        root.appendChild(brand);

        const lamp = document.createElement('span');
        lamp.className = `topbar-serial__lamp topbar-serial__lamp--${connected ? 'online' : 'offline'}`;
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        if (label) {
            const labelEl = document.createElement('span');
            labelEl.className = 'topbar-serial__label';
            labelEl.textContent = label;
            root.appendChild(labelEl);
        }

        const region = (dev.region && dev.region !== 'UNSET') ? dev.region : '--';
        const regionEl = document.createElement('span');
        regionEl.className = 'topbar-serial__region';
        regionEl.textContent = region;
        root.appendChild(this._sep());
        root.appendChild(regionEl);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = this._formatFreq(dev.frequency_mhz);
        root.appendChild(this._sep());
        root.appendChild(freqEl);

        root.classList.toggle('topbar-serial--offline', !connected);
        return root;
    }

    _sep() {
        const sep = document.createElement('span');
        sep.className = 'topbar-serial__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = '·';
        return sep;
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(3)} MHz`;
    }

    /** "serial_433" -> "433"; bare "serial" -> null (no useful label). */
    _labelFromName(name) {
        const raw = String(name || '');
        const idx = raw.indexOf('_');
        if (idx === -1) return null;
        return raw.slice(idx + 1) || null;
    }
}

window.TopbarSerialChip = TopbarSerialChip;
