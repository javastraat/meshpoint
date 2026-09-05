/**
 * Configuration panel orchestrator.
 *
 * Single responsibility: load ``/api/config`` once, mount the right
 * editable card into each Configuration subsection container, and
 * re-render every card on data changes. The subsections (Identity,
 * Radio, Channels, MeshCore, Serial, Reticulum, Transmit, MQTT, GPS,
 * Storage, Peripherals, Repeater Poll, Metrics)
 * all mount dedicated editable cards from ``frontend/js/configuration/``.
 * ("Storage" lives under the Settings sidebar group, not Configuration --
 * kept on this same panel/route prefix regardless, see storage_card.js.)
 * The observational read-only versions (``RadioIdentityCard``,
 * ``RadioConfigCard``, ``RadioChannels``, ``RadioCompanionCard``)
 * live on the top-level Radio page only.
 *
 * Each subsection lazy-mounts on first navigation so we don't
 * inflate every form's DOM at boot.
 */

class ConfigurationPanel {
    constructor() {
        this._config = null;
        this._cards = new Map();
        this._mounted = new Set();
    }

    bind() {
        // No global wiring needed; mounting happens in onSectionEnter().
    }

    async onSectionEnter(route) {
        // Storage lives under the Settings sidebar group/route, but its
        // mounting logic stays on this panel rather than a dedicated
        // controller -- see storage_card.js. (app.js's _bootConfigurationPanel
        // has a matching check before it even calls this method.)
        const isStorage = route === 'settings/storage';
        if (!isStorage && !route.startsWith('configuration/')) return;
        const section = isStorage ? 'storage' : route.slice('configuration/'.length);
        await this._loadConfig();
        this._mountSection(section);
        this._renderAll();
        if (section === 'radio') this._scrollToFocusTarget();
    }

    async _loadConfig() {
        try {
            const res = await fetch('/api/config', { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this._config = await res.json();
        } catch (e) {
            console.error('Configuration load failed:', e);
            this._config = {};
        }
    }

    _mountSection(section) {
        if (this._mounted.has(section)) return;
        const api = this._buildApi();

        if (section === 'identity' && window.IdentityConfigCard) {
            const host = document.getElementById('cfg-identity-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.IdentityConfigCard(api);
                card.mount(host);
                this._cards.set('identity', card);
            }
        } else if (section === 'radio' && window.RadioConfigEditCard) {
            const host = document.getElementById('cfg-radio-panel');
            if (host) {
                host.innerHTML = `
                    <div class="cfg-section">
                        <div data-cfg-radio></div>
                        <div data-cfg-radio-advanced></div>
                        <div data-cfg-radio-pager></div>
                        <div data-cfg-nodeinfo-edit></div>
                        <div data-cfg-telemetry-edit></div>
                        <div data-cfg-nodeinfo-status></div>
                        <div data-cfg-telemetry-status></div>
                    </div>
                `;
                const radio = new window.RadioConfigEditCard(api);
                radio.mount(host.querySelector('[data-cfg-radio]'));
                this._cards.set('radio', radio);
                if (window.RadioAdvancedConfigCard) {
                    const radioAdv = new window.RadioAdvancedConfigCard(api);
                    radioAdv.mount(host.querySelector('[data-cfg-radio-advanced]'));
                    this._cards.set('radio-advanced', radioAdv);
                }
                if (window.RadioPagerConfigCard) {
                    const radioPager = new window.RadioPagerConfigCard(api);
                    radioPager.mount(host.querySelector('[data-cfg-radio-pager]'));
                    this._cards.set('radio-pager', radioPager);
                }
                if (window.NodeInfoConfigCard) {
                    const edit = new window.NodeInfoConfigCard(api);
                    edit.mount(host.querySelector('[data-cfg-nodeinfo-edit]'));
                    this._cards.set('nodeinfo-edit', edit);
                }
                if (window.RadioNodeInfoCard) {
                    const status = new window.RadioNodeInfoCard(api);
                    status.mount(host.querySelector('[data-cfg-nodeinfo-status]'));
                    this._cards.set('nodeinfo-status', status);
                }
                if (window.TelemetryBroadcastCard) {
                    const telem = new window.TelemetryBroadcastCard(api);
                    telem.mount(host.querySelector('[data-cfg-telemetry-edit]'));
                    this._cards.set('telemetry-edit', telem);
                }
                if (window.BroadcastStatusCard) {
                    const telemStatus = new window.BroadcastStatusCard(api, {
                        title: 'Telemetry Broadcast',
                        configKey: 'telemetry',
                        editRoute: '#/configuration/radio',
                        scrollTarget: 'cfg-telemetry-interval',
                    });
                    telemStatus.mount(host.querySelector('[data-cfg-telemetry-status]'));
                    this._cards.set('telemetry-status', telemStatus);
                }
            }
        } else if (section === 'channels') {
            const host = document.getElementById('cfg-channels-panel');
            if (host) {
                host.innerHTML = `
                    <div class="cfg-section">
                        <div data-quick-deploy-mount></div>
                        <div data-channels-mount></div>
                    </div>
                `;
                if (window.QuickDeployCard) {
                    const quickMount = host.querySelector('[data-quick-deploy-mount]');
                    const quick = new window.QuickDeployCard(api);
                    quick.mount(quickMount);
                    this._cards.set('quick-deploy', quick);
                }
                if (window.ChannelsConfigCard) {
                    const channelsMount = host.querySelector('[data-channels-mount]');
                    const card = new window.ChannelsConfigCard(api);
                    card.mount(channelsMount);
                    this._cards.set('channels', card);
                }
            }
        } else if (section === 'meshcore' && window.MeshcoreConfigCard) {
            const host = document.getElementById('cfg-meshcore-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.MeshcoreConfigCard(api);
                card.mount(host);
                this._cards.set('meshcore', card);
            }
        } else if (section === 'serial' && window.SerialConfigCard) {
            const host = document.getElementById('cfg-serial-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.SerialConfigCard(api);
                card.mount(host);
                this._cards.set('serial', card);
            }
        } else if (section === 'firmware') {
            const host = document.getElementById('cfg-firmware-panel');
            if (host) {
                host.innerHTML = `
                    <div class="cfg-section">
                        <div data-firmware-meshtastic></div>
                        <div data-firmware-meshcore></div>
                        <div data-firmware-pocsag></div>
                        <div data-firmware-pager></div>
                        <div data-firmware-rfenv></div>
                        <div data-firmware-reticulum></div>
                        <div data-firmware-rnode></div>
                    </div>
                `;
                if (window.MeshtasticFirmwareConfigCard) {
                    const meshtastic = new window.MeshtasticFirmwareConfigCard(api);
                    meshtastic.mount(host.querySelector('[data-firmware-meshtastic]'));
                    this._cards.set('firmware-meshtastic', meshtastic);
                }
                if (window.MeshcoreFirmwareConfigCard) {
                    const meshcore = new window.MeshcoreFirmwareConfigCard(api);
                    meshcore.mount(host.querySelector('[data-firmware-meshcore]'));
                    this._cards.set('firmware-meshcore', meshcore);
                }
                if (window.PocsagFirmwareConfigCard) {
                    const pocsag = new window.PocsagFirmwareConfigCard(api);
                    pocsag.mount(host.querySelector('[data-firmware-pocsag]'));
                    this._cards.set('firmware-pocsag', pocsag);
                }
                if (window.PagerFirmwareConfigCard) {
                    const pager = new window.PagerFirmwareConfigCard(api);
                    pager.mount(host.querySelector('[data-firmware-pager]'));
                    this._cards.set('firmware-pager', pager);
                }
                if (window.RfenvCompanionFirmwareConfigCard) {
                    const rfenv = new window.RfenvCompanionFirmwareConfigCard(api);
                    rfenv.mount(host.querySelector('[data-firmware-rfenv]'));
                    this._cards.set('firmware-rfenv', rfenv);
                }
                if (window.ReticulumCompanionFirmwareConfigCard) {
                    const reticulum = new window.ReticulumCompanionFirmwareConfigCard(api);
                    reticulum.mount(host.querySelector('[data-firmware-reticulum]'));
                    this._cards.set('firmware-reticulum', reticulum);
                }
                if (window.RnodeFirmwareConfigCard) {
                    const rnode = new window.RnodeFirmwareConfigCard(api);
                    rnode.mount(host.querySelector('[data-firmware-rnode]'));
                    this._cards.set('firmware-rnode', rnode);
                }
            }
        } else if (section === 'transmit' && window.TransmitConfigCard) {
            const host = document.getElementById('cfg-transmit-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.TransmitConfigCard(api);
                card.mount(host);
                this._cards.set('transmit', card);
            }
        } else if (section === 'mqtt' && window.MqttConfigCard) {
            const host = document.getElementById('cfg-mqtt-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.MqttConfigCard(api);
                card.mount(host);
                this._cards.set('mqtt', card);
            }
        } else if (section === 'gps' && window.GpsConfigCard) {
            const host = document.getElementById('cfg-gps-panel');
            if (host) {
                host.innerHTML = `
                    <div class="cfg-section">
                        <div data-cfg-gps-main></div>
                        <div data-cfg-position-edit></div>
                        <div data-cfg-position-status></div>
                    </div>
                `;
                const card = new window.GpsConfigCard(api);
                card.mount(host.querySelector('[data-cfg-gps-main]'));
                this._cards.set('gps', card);
                if (window.PositionBroadcastCard) {
                    const pos = new window.PositionBroadcastCard(api);
                    pos.mount(host.querySelector('[data-cfg-position-edit]'));
                    this._cards.set('position-edit', pos);
                }
                if (window.BroadcastStatusCard) {
                    const posStatus = new window.BroadcastStatusCard(api, {
                        title: 'Position Broadcast',
                        configKey: 'position',
                        editRoute: '#/configuration/gps',
                        scrollTarget: 'cfg-position-interval',
                    });
                    posStatus.mount(host.querySelector('[data-cfg-position-status]'));
                    this._cards.set('position-status', posStatus);
                }
            }
        } else if (section === 'storage' && window.StorageConfigCard) {
            const host = document.getElementById('settings-storage-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.StorageConfigCard(api);
                card.mount(host);
                this._cards.set('storage', card);
            }
        } else if (section === 'peripherals' && window.HardwareConfigCard) {
            const host = document.getElementById('cfg-peripherals-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.HardwareConfigCard(api);
                card.mount(host);
                this._cards.set('peripherals', card);
            }
        } else if (section === 'repeater-poll' && window.RepeaterPollConfigCard) {
            const host = document.getElementById('cfg-repeater-poll-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.RepeaterPollConfigCard(api);
                card.mount(host);
                this._cards.set('repeater-poll', card);
            }
        } else if (section === 'reticulum' && window.ReticulumConfigCard) {
            const host = document.getElementById('cfg-reticulum-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.ReticulumConfigCard(api);
                card.mount(host);
                this._cards.set('reticulum', card);
            }
        } else if (section === 'metrics' && window.MetricsConfigCard) {
            const host = document.getElementById('cfg-metrics-panel');
            if (host) {
                host.innerHTML = '';
                const card = new window.MetricsConfigCard(api);
                card.mount(host);
                this._cards.set('metrics', card);
            }
        }
        this._mounted.add(section);
    }

    _renderAll() {
        if (!this._config) return;
        this._cards.forEach((card) => {
            try {
                card.render(this._config);
            } catch (e) {
                console.error('Configuration card render failed:', e);
            }
        });
    }

    _buildApi() {
        const self = this;
        return {
            get: (url) => self._request('GET', url, undefined),
            put: (url, body) => self._request('PUT', url, body),
            post: (url, body) => self._request('POST', url, body),
            delete: (url) => self._request('DELETE', url, undefined),
            refresh: () => self._loadConfig().then(() => self._renderAll()),
            toast: (msg) => self._toast(msg),
            signalRestart: (msg) => self._toast(
                msg + ' Restart the service from Settings → System to apply.',
            ),
            escape: (str) => {
                const el = document.createElement('span');
                el.textContent = str || '';
                return el.innerHTML;
            },
        };
    }

    async _request(method, url, body) {
        const init = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
        if (body !== undefined && body !== null) init.body = JSON.stringify(body);
        const isGet = method === 'GET';
        try {
            const res = await fetch(url, init);
            if (!res.ok) {
                // Toast on GET failures too (used to be save-only) -- a
                // failed read used to leave whatever empty/default state
                // the caller started with, no visible sign anything went
                // wrong (e.g. the Firmware page's Version/Board dropdowns
                // silently staying empty when GitHub rate-limits the
                // Pi's IP, with the real error only visible in DevTools).
                const err = await res.json().catch(() => ({}));
                this._toast(`${isGet ? 'Error' : 'Save failed'}: ${err.detail || res.status}`);
                return null;
            }
            return await res.json();
        } catch (e) {
            this._toast(`${isGet ? 'Error' : 'Save failed'}: ${e.message}`);
            return null;
        }
    }

    _scrollToFocusTarget() {
        const targetId = sessionStorage.getItem('cfg-scroll-target');
        if (!targetId) return;
        sessionStorage.removeItem('cfg-scroll-target');
        requestAnimationFrame(() => {
            const el = document.getElementById(targetId);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }

    _toast(text) {
        let toast = document.getElementById('cfg-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'cfg-toast';
            toast.className = 'cfg-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.classList.add('cfg-toast--visible');
        setTimeout(() => toast.classList.remove('cfg-toast--visible'), 2800);
    }
}

window.ConfigurationPanel = ConfigurationPanel;
