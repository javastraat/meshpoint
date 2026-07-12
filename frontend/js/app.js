/**
 * Single-page controller for the local Meshpoint dashboard.
 * Wires up map, node list, packet feed, stat cards, and WebSocket.
 *
 * Auth boundary:
 *   - install401Redirect intercepts every same-origin /api/* fetch
 *     and bounces to /login?next=... when the session has expired.
 *   - DOMContentLoaded does a quick /api/identity probe so a fresh
 *     install (no admin password yet) lands on /setup, not on a
 *     blank dashboard with broken API calls.
 */

(function install401Redirect() {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
        const res = await originalFetch(input, init);
        if (res.status === 401 && _isLocalApiRequest(input)) {
            const next = encodeURIComponent(location.pathname + location.search);
            location.assign(`/login?next=${next}`);
        }
        return res;
    };

    function _isLocalApiRequest(input) {
        const raw = typeof input === 'string' ? input : (input && input.url) || '';
        try {
            const parsed = new URL(raw, location.origin);
            return parsed.origin === location.origin
                && parsed.pathname.startsWith('/api/');
        } catch (_) {
            return false;
        }
    }
})();

document.addEventListener('DOMContentLoaded', async () => {
    if (await _redirectIfSetupRequired()) return;

    const identity = await _loadIdentity();

    const router = new Router({
        defaultRoute: 'dashboard',
        allowedRoutes: [
            'dashboard', 'meshtastic', 'meshcore', 'lorawan', 'listener', 'stats', 'rf', 'repeaters', 'topology', 'messages', 'radio', 'terminal',
            'configuration/identity', 'configuration/radio',
            'configuration/channels', 'configuration/transmit',
            'configuration/mqtt',
            'configuration/gps', 'configuration/advanced',
            'configuration/peripherals',
            'configuration/meshcore', 'configuration/serial',
            'settings/updates', 'settings/auth', 'settings/dangerous',
        ],
        guard: _buildRouteGuard(identity),
        onDenied: _toastAdminRequired,
    });
    const sidebar = new SidebarController({ router, identity });
    sidebar.bind();
    window.sidebar = sidebar;

    if (window.RadioTxBadge) {
        const radioTxBadge = new RadioTxBadge(sidebar);
        radioTxBadge.init();
        window.radioTxBadge = radioTxBadge;
    }

    if (window.UpdateCheckBadge) {
        const updateCheckBadge = new UpdateCheckBadge(sidebar);
        updateCheckBadge.init();
        window.updateCheckBadge = updateCheckBadge;
    }

    if (window.SinceLineController && window.lastVisitTracker) {
        const sinceCtrl = new SinceLineController(router, window.lastVisitTracker);
        const dashHost = document.getElementById('dashboard-since-host');
        if (dashHost) {
            sinceCtrl.register('dashboard', {
                hostEl: dashHost,
                label: 'packets',
                getCount: () => (window.getTotalPackets ? window.getTotalPackets() : 0),
            });
        }
        sinceCtrl.start();
        window.sinceLineController = sinceCtrl;
    }

    router.start();

    const logoFrame = document.getElementById('sidebar-logo-frame');
    if (logoFrame && window.SidebarLogoPip) {
        const pip = new SidebarLogoPip(logoFrame, window.concentratorWS);
        pip.init();
        window.sidebarLogoPip = pip;
    }

    const topbarRoot = document.getElementById('topbar');
    if (topbarRoot && window.TopbarController) {
        const topbar = new TopbarController(topbarRoot, window.concentratorWS);
        topbar.init();
        window.topbar = topbar;
        _registerThemeToggle(topbar);
    }

    if (window.BuildStamp) {
        const stamp = new BuildStamp();
        stamp.mount();
        window.buildStamp = stamp;
    }

    const telemetryRoot = document.getElementById('telemetry-rail');
    if (telemetryRoot && window.SidebarTelemetryRail) {
        const rail = new SidebarTelemetryRail(telemetryRoot, window.concentratorWS);
        rail.init();
        window.telemetryRail = rail;
    }

    if (window.ReconnectStoryboard) {
        const story = new ReconnectStoryboard(window.concentratorWS);
        story.mount();
        story.init();
        window.reconnectStoryboard = story;
    }

    if (window.TabTitleTelemetry) {
        const tabTitle = new TabTitleTelemetry(window.concentratorWS);
        tabTitle.init();
        window.tabTitleTelemetry = tabTitle;
    }

    if (window.themeController) window.themeController.init();
    _bootCommandPaletteAndKeymap(router);
    _wireSoundEvents();
    if (window.messageNotifier && window.concentratorWS) {
        window.messageNotifier.init(window.concentratorWS);
    }

    new SignOutController('signout-btn').bind();

    _bootAuthPanel(router);
    _bootTerminalPanel(router);
    _bootUpdatePanel(router);
    _bootConfigurationPanel(router);
    _bootDangerousPanel(router);
    _bootLoRaWANPanel(router);
    _bootListenerPanel(router);
    _bootRepeatersPanel(router);
    _bootTopologyPanel(router);
    _bootMeshtasticPanel(router);
    _bootMeshCorePanel(router);

    const nodeMap = new NodeMap('map');
    const packetFeed = new SimplePacketFeed('packet-tbody');

    const nodeDrawer = new NodeDrawer('node-drawer', {
        onSendMessage: (node) => _openMessagingForNode(node),
        onViewOnMap: (node) => {
            if (node.latitude && node.longitude) {
                nodeMap.centerOn(node.latitude, node.longitude);
            }
        },
    });

    const nodeCards = new NodeCards('node-list', (node) => nodeDrawer.open(node));

    const backdrop = document.getElementById('node-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', () => {
            nodeDrawer.close();
            backdrop.classList.remove('nd-backdrop--visible');
        });
    }

    const origOpen = nodeDrawer.open.bind(nodeDrawer);
    nodeDrawer.open = async (node) => {
        if (backdrop) backdrop.classList.add('nd-backdrop--visible');
        await origOpen(node);
    };
    const origClose = nodeDrawer.close.bind(nodeDrawer);
    nodeDrawer.close = () => {
        if (backdrop) backdrop.classList.remove('nd-backdrop--visible');
        origClose();
    };

    window.nodeDrawer = nodeDrawer;

    packetFeed.setOnFocus(sourceId => {
        if (sourceId) nodeMap.drawFocusLine(sourceId);
        else nodeMap.clearFocusLine();
    });

    const mapHomeBtn = document.getElementById('map-home-btn');
    if (mapHomeBtn) {
        mapHomeBtn.addEventListener('click', () => nodeMap.centerOnHome());
    }

    const mapExpandBtn = document.getElementById('map-expand-btn');
    const dashboard = document.querySelector('.dashboard');
    if (mapExpandBtn && dashboard) {
        mapExpandBtn.addEventListener('click', () => {
            const expanded = dashboard.classList.toggle('dashboard--map-expanded');
            mapExpandBtn.textContent = expanded ? '⤡' : '⤢';
            mapExpandBtn.title = expanded ? 'Collapse map' : 'Expand map';
            setTimeout(() => nodeMap.invalidateSize(), 50);
        });
    }

    await _loadInitial(nodeMap, nodeCards, packetFeed);
    await _updateStats();
    _checkForUpdate();

    window.concentratorWS.on('packet', (packet) => {
        packetFeed.addPacket(packet);
        nodeMap.updateFromPacket(packet);
        nodeCards.updateFromPacket(packet);
        _incrementPacketCount();
    });

    window.concentratorWS.connect();

    setInterval(() => {
        _refreshData(nodeMap, nodeCards, packetFeed);
        _updateStats();
    }, 15_000);

    setInterval(_checkForUpdate, 300_000);

    if (window.MeshpointDisplayUnits?.onChange) {
        window.MeshpointDisplayUnits.onChange(_renderCpuTemp);
    }
});

// Topbar theme toggle: cycles dark -> high-contrast -> sunlight, with an
// icon + tooltip that reflect the current theme. Reuses window.themeController.
function _registerThemeToggle(topbar) {
    const tc = window.themeController;
    if (!tc || typeof topbar.registerAction !== 'function') return;

    const SVG = (inner, extra = '') => `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round" width="16" height="16"
             aria-hidden="true" ${extra}>${inner}</svg>`;
    const ICONS = {
        'dark': SVG('<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'),
        'high-contrast': SVG('<circle cx="12" cy="12" r="9"/>'
            + '<path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/>'),
        'sunlight': SVG('<circle cx="12" cy="12" r="4"/>'
            + '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
            + 'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    };
    const LABELS = { 'dark': 'Dark', 'high-contrast': 'High contrast', 'sunlight': 'Sunlight' };

    const btn = topbar.registerAction({
        id: 'theme',
        label: 'Theme',
        icon: ICONS[tc.current()] || ICONS.dark,
        onClick: () => update(tc.cycle()),
    });

    function update(theme) {
        if (!btn) return;
        btn.innerHTML = ICONS[theme] || ICONS.dark;
        const name = LABELS[theme] || theme;
        btn.setAttribute('title', `Theme: ${name} · click to cycle`);
        btn.setAttribute('aria-label', `Theme: ${name}`);
    }
    update(tc.current());
}

function _bootDangerousPanel(router) {
    const root = document.getElementById('settings-dangerous-panel');
    if (!root || !window.DangerousPanelController) return;
    const prefsRoot = document.getElementById('meshpoint-display-prefs');
    if (prefsRoot && window.MeshpointDisplayForm) {
        new window.MeshpointDisplayForm(prefsRoot);
    }
    const backupRoot = document.getElementById('meshpoint-backup-restore');
    let backupCard = null;
    if (backupRoot && window.BackupRestoreCard) {
        backupCard = new window.BackupRestoreCard(backupRoot);
        backupCard.bind();
    }
    const controller = new window.DangerousPanelController(root);
    controller.bind();
    let primed = false;
    router.onRouteChange((route) => {
        if (route !== 'settings/dangerous') return;
        if (primed) return;
        primed = true;
        controller.refresh();
        backupCard?.refresh();
    });
}

function _bootLoRaWANPanel(router) {
    if (!window.LoRaWANPanel) return;
    const panel = new window.LoRaWANPanel();
    router.onRouteChange((route) => {
        if (route === 'lorawan') panel.show();
        else panel.hide();
    });
}

function _bootListenerPanel(router) {
    if (!window.ListenerPanel) return;
    const panel = new window.ListenerPanel();
    router.onRouteChange((route) => {
        if (route === 'listener') panel.show();
        else panel.hide();
    });
}

function _bootTopologyPanel(router) {
    if (!window.TopologyTab) return;
    const panel = new window.TopologyTab();
    router.onRouteChange((route) => {
        if (route === 'topology') panel.show();
        else panel.hide();
    });
}

function _bootRepeatersPanel(router) {
    if (!window.RepeatersTab) return;
    const panel = new window.RepeatersTab();
    // Reveal the sidebar item only when repeater polling is configured.
    panel.checkAvailable().then((available) => {
        const nav = document.getElementById('nav-repeaters');
        if (nav) nav.style.display = available ? '' : 'none';
    });
    router.onRouteChange((route) => {
        if (route === 'repeaters') panel.show();
        else panel.hide();
    });
}

function _bootMeshCorePanel(router) {
    if (!window.MeshCorePanel) return;
    const panel = new window.MeshCorePanel();
    router.onRouteChange((route) => {
        if (route === 'meshcore') panel.show();
        else panel.hide();
    });
}

function _bootMeshtasticPanel(router) {
    if (!window.MeshtasticPanel) return;
    const panel = new window.MeshtasticPanel();
    router.onRouteChange((route) => {
        if (route === 'meshtastic') panel.show();
        else panel.hide();
    });
}

function _bootConfigurationPanel(router) {
    if (!window.ConfigurationPanel) return;
    const panel = new window.ConfigurationPanel();
    panel.bind();
    router.onRouteChange((route) => {
        if (!route || !route.startsWith('configuration/')) return;
        panel.onSectionEnter(route);
    });
}

function _bootUpdatePanel(router) {
    const root = document.getElementById('settings-updates-panel');
    if (!root || !window.UpdatePanelController) return;
    const controller = new window.UpdatePanelController(root);
    controller.bind();
    router.onRouteChange((route) => {
        if (route !== 'settings/updates') return;
        controller.refresh();
    });
}

function _bootTerminalPanel(router) {
    const root = document.getElementById('terminal-panel');
    if (!root || !window.TerminalPanelController) return;
    const controller = new window.TerminalPanelController(root);
    controller.bind();
    let primed = false;
    router.onRouteChange((route) => {
        if (route !== 'terminal') return;
        if (!primed) {
            primed = true;
            controller.refresh();
        }
        controller.onSectionEnter();
    });
}

function _bootAuthPanel(router) {
    const root = document.getElementById('settings-auth-panel');
    if (!root || !window.AuthPanelController) return;
    const controller = new window.AuthPanelController(root);
    controller.bind();
    let primed = false;
    const maybeRefresh = (route) => {
        if (route !== 'settings/auth') return;
        if (primed) return;
        primed = true;
        controller.refresh();
    };
    router.onRouteChange(maybeRefresh);
    if ((location.hash || '').replace(/^#\//, '') === 'settings/auth') {
        maybeRefresh('settings/auth');
    }
}

async function _loadIdentity() {
    try {
        const res = await fetch('/api/identity', { credentials: 'same-origin' });
        if (!res.ok) return null;
        return await res.json();
    } catch (_) {
        return null;
    }
}

// Denied in-app navigation (viewer clicked an admin link): stay on the
// current page and explain via the shared r-toast pill. Deep links and
// fresh loads still render the "forbidden" section (see router.js).
function _toastAdminRequired() {
    let toast = document.getElementById('r-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'r-toast';
        toast.className = 'r-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = 'Admin access required — the viewer role is read-only';
    toast.classList.add('r-toast--visible');
    setTimeout(() => toast.classList.remove('r-toast--visible'), 2500);
}

/**
 * Role guard for the router: viewers who deep-link to an admin page
 * (#/configuration/*, #/terminal, #/settings/*) get the "forbidden"
 * section instead of the page. Belt-and-braces with the server-side
 * require_admin gates -- this only shapes the UI.
 */
function _buildRouteGuard(identity) {
    const sections = new Set((identity && identity.available_sections) || []);
    if (!sections.size) return null; // no auth info -> fail open (setup/dev)

    const requiredSection = (route) => {
        if (route.startsWith('configuration/')) {
            return `configuration.${route.split('/')[1]}`;
        }
        if (route === 'terminal') return 'terminal';
        if (route === 'settings/dangerous') return 'settings.dangerous';
        if (route.startsWith('settings/')) return 'settings';
        return null; // everything else is open to any signed-in role
    };

    return (route) => {
        const need = requiredSection(route);
        return !need || sections.has(need);
    };
}

function _openMessagingForNode(node) {
    if (window.sidebar && window.sidebar._router) {
        window.sidebar._router.navigate('messages');
    } else if (location.hash !== '#/messages') {
        location.hash = '#/messages';
    }

    setTimeout(() => {
        if (window.messagingPanel) {
            window.messagingPanel.openConversation({
                node_id: node.node_id,
                node_name: node.display_name || node.long_name || node.node_id,
                protocol: node.protocol || 'meshtastic',
                is_broadcast: false,
            });
        }
    }, 100);
}

async function _loadInitial(nodeMap, nodeList, packetFeed) {
    try {
        const [deviceRes, nodesRes, packetsRes] = await Promise.all([
            fetch('/api/device'),
            fetch('/api/nodes?enrich=true'),
            fetch('/api/packets?limit=50'),
        ]);
        const device = await deviceRes.json();
        const nodesData = await nodesRes.json();
        const packetsData = await packetsRes.json();

        _setText('sidebar-device-name', _resolveDeviceLabel(device));

        const nodes = nodesData.nodes || nodesData || [];
        window._meshpointHomeLat = device.latitude ?? null;
        window._meshpointHomeLon = device.longitude ?? null;
        nodeMap.loadNodes(nodes, device);
        nodeList.setHomePosition(device.latitude, device.longitude);
        nodeList.loadNodes(nodes);
        packetFeed.loadNodes(nodes);

        const packets = packetsData.packets || packetsData || [];
        const sorted = packets.sort((a, b) => {
            const aTime = a.rx_time || new Date(a.timestamp || 0).getTime() / 1000;
            const bTime = b.rx_time || new Date(b.timestamp || 0).getTime() / 1000;
            return aTime - bTime;
        });
        sorted.forEach(pkt => packetFeed.addPacket(pkt));
        _totalPackets = sorted.length;
    } catch (e) {
        console.error('Initial load failed:', e);
    }
}

async function _refreshData(nodeMap, nodeList, packetFeed) {
    try {
        const [nodesRes, deviceRes] = await Promise.all([
            fetch('/api/nodes?enrich=true'),
            fetch('/api/device'),
        ]);
        const data = await nodesRes.json();
        const nodes = data.nodes || data || [];
        const device = deviceRes.ok ? await deviceRes.json() : undefined;
        nodeMap.loadNodes(nodes, device);
        if (device) nodeList.setHomePosition(device.latitude, device.longitude);
        nodeList.loadNodes(nodes);
        packetFeed.loadNodes(nodes);
    } catch (e) {
        console.error('Refresh failed:', e);
    }
}

async function _updateStats() {
    try {
        const [trafficRes, signalRes, nodeRes, deviceRes, metricsRes] = await Promise.all([
            fetch('/api/analytics/traffic'),
            fetch('/api/analytics/signal/summary'),
            fetch('/api/nodes/count'),
            fetch('/api/device/status'),
            fetch('/api/device/metrics'),
        ]);

        const traffic = await trafficRes.json();
        const signal = await signalRes.json();
        const nodeCount = await nodeRes.json();
        const device = await deviceRes.json();

        _setText('stat-nodes-val', `${nodeCount.active} / ${nodeCount.count}`);
        _setText('stat-packets-val', traffic.packets_last_24h != null
            ? `${traffic.packets_last_24h} / ${traffic.total_packets}`
            : traffic.total_packets);
        _setText('stat-rate-val', traffic.packets_per_minute);
        _setText('stat-rssi-val', signal.avg_rssi != null ? `${signal.avg_rssi} dBm` : '--');

        const relay = device.relay || {};
        _setText('stat-relay-val', relay.relayed ?? 0);
        const evaluated = (relay.relayed ?? 0) + (relay.rejected ?? 0);
        _setText('stat-relay-sub', evaluated > 0
            ? `${evaluated} evaluated`
            : relay.enabled ? 'listening...' : 'relay off');

        _setText('stat-uptime-val', _formatUptime(device.uptime_seconds || 0));

        _setText('sidebar-device-name', _resolveDeviceLabel(device));
        const statusText = device.firmware_version
            ? `online · v${device.firmware_version}`
            : 'online';
        _setText('sidebar-status-text', statusText);
        const statusDot = document.getElementById('sidebar-status-dot');
        if (statusDot) {
            statusDot.classList.remove('status-dot--disconnected');
            statusDot.classList.add('status-dot--connected');
        }

        if (metricsRes.ok) {
            const metrics = await metricsRes.json();
            _setText('stat-cpu-val', `${metrics.cpu_percent}%`);
            _setText('stat-ram-val', `${metrics.memory_percent}%`);
            _setText('stat-ram-sub', `${metrics.memory_used_mb} / ${metrics.memory_total_mb} MB`);
            _setText('stat-disk-val', `${metrics.disk_percent}%`);
            _setText('stat-disk-sub', `${metrics.disk_used_gb} / ${metrics.disk_total_gb} GB`);
            _lastCpuTempC = metrics.cpu_temp_c;
            _renderCpuTemp();
            if (Array.isArray(metrics.load_avg)) {
                const [m1, m5, m15] = metrics.load_avg;
                _setText('stat-load-val', m1.toFixed(2));
                _setText('stat-load-sub', `5m ${m5.toFixed(2)} · 15m ${m15.toFixed(2)}`);
            } else {
                _setText('stat-load-val', 'N/A');
                _setText('stat-load-sub', '');
            }

            const fanCard = document.getElementById('stat-fan');
            if (fanCard) {
                const dutyPct = metrics.fan_duty_percent;
                if (dutyPct == null) {
                    fanCard.hidden = true;
                } else {
                    fanCard.hidden = false;
                    _setText('stat-fan-val', dutyPct > 0 ? `${dutyPct}%` : 'Off');
                    const prevPct = metrics.fan_previous_duty_percent;
                    _setText('stat-fan-sub', prevPct != null
                        ? `was ${prevPct > 0 ? `${prevPct}%` : 'off'}`
                        : '');
                }
            }
        }
    } catch (e) {
        console.error('Failed to update stats:', e);
    }
}

let _totalPackets = 0;

function _incrementPacketCount() {
    _totalPackets++;
}

window.getTotalPackets = () => _totalPackets;

let _lastCpuTempC = null;

function _renderCpuTemp() {
    const formatter = window.MeshpointDisplayUnits?.formatTemperature;
    let text;
    if (_lastCpuTempC == null) {
        text = 'N/A';
    } else if (typeof formatter === 'function') {
        text = formatter(_lastCpuTempC) ?? 'N/A';
    } else {
        text = `${_lastCpuTempC}\u00B0C`;
    }
    _setText('stat-temp-val', text);
}

function _formatUptime(totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

async function _checkForUpdate() {
    try {
        const res = await fetch('/api/device/update-check');
        const data = await res.json();
        if (window.sidebar) {
            window.sidebar.setStatusBadge(
                'settings/updates',
                data.update_available ? '1' : null,
                'update'
            );
        }
    } catch (_) {}
}

function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

/**
 * Pick the most user-meaningful name for the device label.
 *
 * Order:
 *  1. device_name -- explicitly set by the user for the sidebar/dashboard.
 *  2. long_name   -- mesh broadcast name, fallback if device_name not set.
 *  3. "Meshpoint" -- last resort default.
 *
 * device_name takes priority because the user set it specifically for the
 * dashboard. long_name defaults to "Meshpoint" in the config so it must
 * not override an explicitly chosen device_name.
 */
function _resolveDeviceLabel(device) {
    if (!device) return 'Meshpoint';
    const name    = (device.device_name || '').trim();
    const long    = (device.long_name   || '').trim();
    const neither = name === 'Meshpoint' && long === 'Meshpoint';
    if (name && name !== 'Meshpoint') return name;
    if (long && long !== 'Meshpoint') return long;
    return neither ? 'Meshpoint' : (name || long || 'Meshpoint');
}

async function _redirectIfSetupRequired() {
    try {
        const res = await fetch('/api/identity', { credentials: 'same-origin' });
        if (!res.ok) return false;
        const data = await res.json();
        if (data.setup_required) {
            location.replace('/setup');
            return true;
        }
    } catch (_) {
        /* silent: the dashboard handles its own auth via 401 interception */
    }
    return false;
}

function _bootCommandPaletteAndKeymap(router) {
    if (!window.CommandPalette || !window.KeymapOverlay) return;

    const palette = new CommandPalette();
    palette.init();
    window.commandPalette = palette;

    const keymap = new KeymapOverlay();
    keymap.init();
    window.keymapOverlay = keymap;

    const routeCommands = [
        ['dashboard', 'Go to Dashboard', 'Pages'],
        ['stats', 'Go to Stats', 'Pages'],
        ['messages', 'Go to Messages', 'Pages'],
        ['radio', 'Go to Hardware', 'Pages'],
        ['rf', 'Go to RF Environment', 'Pages'],
        ['repeaters', 'Go to Repeaters', 'Pages'],
        ['topology', 'Go to Topology', 'Pages'],
        ['terminal', 'Go to Terminal', 'Pages'],
        ['configuration/identity', 'Go to Configuration · Identity', 'Configuration'],
        ['configuration/radio', 'Go to Configuration · Radio', 'Configuration'],
        ['configuration/channels', 'Go to Configuration · Channels', 'Configuration'],
        ['configuration/meshcore', 'Go to Configuration · MeshCore', 'Configuration'],
        ['configuration/serial', 'Go to Configuration · Serial', 'Configuration'],
        ['configuration/peripherals', 'Go to Configuration · Peripherals', 'Configuration'],
        ['settings/auth', 'Go to Settings · Auth', 'Settings'],
        ['settings/updates', 'Go to Settings · Updates', 'Settings'],
        ['settings/dangerous', 'Go to Settings · System', 'Settings'],
    ];
    routeCommands.forEach(([routeId, label, group]) => {
        palette.register({
            id: `route:${routeId}`,
            label,
            group,
            icon: '→',
            run: () => router.navigate(routeId),
        });
    });

    palette.register({
        id: 'theme:cycle',
        label: 'Cycle theme (dark / high-contrast / sunlight)',
        group: 'View',
        icon: '◐',
        run: () => {
            if (!window.themeController) return;
            const next = window.themeController.cycle();
            console.info('theme →', next);
        },
    });

    palette.register({
        id: 'sound:toggle',
        label: 'Toggle UI sounds',
        group: 'View',
        icon: '♪',
        run: () => {
            if (!window.soundEngine) return;
            const next = !window.soundEngine.isEnabled();
            window.soundEngine.setEnabled(next);
            console.info('sounds →', next ? 'on' : 'off');
        },
    });

    palette.register({
        id: 'messages:toggle-toast',
        label: 'Toggle message popups',
        group: 'View',
        icon: '💬',
        run: () => {
            if (!window.messageNotifier) return;
            const next = !window.messageNotifier.isToastEnabled();
            window.messageNotifier.setToastEnabled(next);
            console.info('message popups →', next ? 'on' : 'off');
        },
    });

    palette.register({
        id: 'messages:toggle-sound',
        label: 'Toggle message sound',
        group: 'View',
        icon: '🔔',
        run: () => {
            if (!window.messageNotifier) return;
            const next = !window.messageNotifier.isSoundEnabled();
            window.messageNotifier.setSoundEnabled(next);
            console.info('message sound →', next ? 'on' : 'off');
        },
    });

    palette.register({
        id: 'help:keymap',
        label: 'Show keyboard shortcuts',
        group: 'Help',
        icon: '?',
        run: () => keymap.open(),
    });

    keymap.registerAll([
        { keys: ['Ctrl', 'K'], label: 'Open command palette', group: 'Global' },
        { keys: ['?'], label: 'Show this shortcuts overlay', group: 'Global' },
        { keys: ['Esc'], label: 'Close any modal / overlay', group: 'Global' },
        { keys: ['['], label: 'Collapse / expand sidebar', group: 'Global' },
        { keys: ['Ctrl', 'Shift', 'C'], label: 'Copy terminal selection', group: 'Terminal' },
        { keys: ['Ctrl', 'Shift', 'V'], label: 'Paste into terminal', group: 'Terminal' },
        { keys: ['Ctrl', 'Shift', 'F'], label: 'Find in terminal output', group: 'Terminal' },
    ]);
}

function _wireSoundEvents() {
    if (!window.soundEngine || !window.concentratorWS) return;
    const ws = window.concentratorWS;
    if (typeof ws.on === 'function') {
        ws.on('connected', () => window.soundEngine.play('connect'));
        ws.on('disconnected', () => window.soundEngine.play('disconnect'));
    }
}
