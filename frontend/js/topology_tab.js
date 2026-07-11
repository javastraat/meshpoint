/**
 * Topology page: force-directed mesh graph on a canvas.
 *
 * Data comes from GET /api/topology/graph (traceroute chains, direct
 * receptions by this box, MeshCore neighbour star). Rendering is a small
 * hand-rolled force simulation -- no external libraries, matching the
 * dashboard's self-contained frontend.
 *
 * Interactions: drag nodes, drag background to pan, wheel to zoom,
 * hover for a tooltip, click a node to highlight its edges, legend
 * chips to filter edge kinds.
 */
class TopologyTab {
    constructor() {
        this.root = document.getElementById('topology-panel');
        this._nodes = [];
        this._edges = [];
        this._staleDays = 7;
        this._kinds = { route: true, direct: true, neighbour: true };
        this._show = { self: true, anchor: true, meshtastic: true, meshcore: true };
        this._mode = this._readMode();
        this._context = false;
        this._contextNodes = null;
        this._map = null;
        this._mapLayer = null;
        this._built = false;
        this._visible = false;
        this._raf = null;
        this._alpha = 0;
        this._view = { x: 0, y: 0, k: 1 };
        this._drag = null;
        this._hover = null;
        this._selected = null;
    }

    show() {
        if (!this.root) return;
        if (!this._built) this._build();
        this.root.closest('.section').style.display = '';
        this._visible = true;
        this._load();
    }

    hide() {
        if (!this.root) return;
        this.root.closest('.section').style.display = 'none';
        this._visible = false;
        if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
    }

    _build() {
        this._built = true;
        this.root.innerHTML = `
            <div class="panel topo-panel">
                <div class="panel__header panel__header--tabs">
                    <h2>Mesh Topology</h2>
                    <div class="lw-tabs" data-topo-modes>
                        <button class="lw-tab" data-mode="graph">Graph</button>
                        <button class="lw-tab" data-mode="map">Map</button>
                    </div>
                    <div class="topo-chips">
                        <button class="topo-chip topo-chip--route topo-chip--active" data-kind="route">Traceroute</button>
                        <button class="topo-chip topo-chip--direct topo-chip--active" data-kind="direct">Direct RX</button>
                        <button class="topo-chip topo-chip--neighbour topo-chip--active" data-kind="neighbour">Neighbours</button>
                        <button class="terminal-button" type="button" data-topo-zoom="out" title="Zoom out">&minus;</button>
                        <button class="terminal-button" type="button" data-topo-zoom="in" title="Zoom in">+</button>
                        <button class="terminal-button" type="button" data-topo-fit title="Fit graph to view">Fit</button>
                        <button class="terminal-button" type="button" data-topo-refresh>Refresh</button>
                    </div>
                </div>
                <div class="topo-canvas-wrap">
                    <canvas class="topo-canvas"></canvas>
                    <div class="topo-map" hidden></div>
                    <div class="topo-map-note" hidden></div>
                    <div class="topo-tooltip" hidden></div>
                    <div class="topo-empty" hidden>
                        No topology data yet. Edges appear from traceroutes, direct
                        receptions, and imported MeshCore neighbours.
                    </div>
                </div>
                <div class="topo-legend">
                    <button class="topo-legend__item topo-legend__toggle" data-show="self"><i class="topo-dot topo-dot--self"></i> this box</button>
                    <button class="topo-legend__item topo-legend__toggle" data-show="anchor"><i class="topo-dot topo-dot--anchor"></i> neighbour source</button>
                    <button class="topo-legend__item topo-legend__toggle" data-show="meshtastic"><i class="topo-dot topo-dot--meshtastic"></i> Meshtastic</button>
                    <button class="topo-legend__item topo-legend__toggle" data-show="meshcore"><i class="topo-dot topo-dot--meshcore"></i> MeshCore</button>
                    <button class="topo-legend__item topo-legend__toggle topo-legend__toggle--off" data-topo-context title="Map only: show all positioned nodes without known links as faint dots"><i class="topo-dot topo-dot--context"></i> all positions</button>
                    <span class="topo-legend__item topo-legend__hint">drag = move / pan · wheel = zoom · click = highlight · legend = show/hide</span>
                    <span class="topo-legend__stats" data-topo-stats></span>
                </div>
            </div>`;

        this._canvas = this.root.querySelector('.topo-canvas');
        this._ctx = this._canvas.getContext('2d');
        this._tooltip = this.root.querySelector('.topo-tooltip');
        this._emptyEl = this.root.querySelector('.topo-empty');
        this._statsEl = this.root.querySelector('[data-topo-stats]');

        this.root.querySelector('[data-topo-refresh]').addEventListener('click', () => this._load());
        this.root.querySelectorAll('[data-topo-zoom]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const zoomIn = btn.dataset.topoZoom === 'in';
                if (this._mode === 'map' && this._map) {
                    if (zoomIn) this._map.zoomIn(); else this._map.zoomOut();
                    return;
                }
                this._zoomBy(zoomIn ? 1.3 : 1 / 1.3);
            });
        });
        this.root.querySelector('[data-topo-fit]').addEventListener('click', () => {
            if (this._mode === 'map') this._fitMap();
            else this._fitView();
        });
        const ctxBtn = this.root.querySelector('[data-topo-context]');
        ctxBtn.addEventListener('click', async () => {
            this._context = !this._context;
            ctxBtn.classList.toggle('topo-legend__toggle--off', !this._context);
            if (this._context && this._contextNodes === null) await this._load();
            if (this._mode === 'map') this._renderMap();
        });
        this.root.querySelectorAll('[data-show]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.show;
                this._show[key] = !this._show[key];
                btn.classList.toggle('topo-legend__toggle--off', !this._show[key]);
                if (this._selected && !this._nodeVisible(this._selected)) this._selected = null;
                if (this._mode === 'map') this._renderMap();
                this._kick(0.3);
            });
        });
        this.root.querySelectorAll('.topo-chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const kind = chip.dataset.kind;
                this._kinds[kind] = !this._kinds[kind];
                chip.classList.toggle('topo-chip--active', this._kinds[kind]);
                if (this._mode === 'map') this._renderMap();
                this._kick(0.3);
            });
        });

        this.root.querySelectorAll('[data-mode]').forEach((btn) => {
            btn.addEventListener('click', () => this._setMode(btn.dataset.mode));
        });

        this._bindPointer();
        window.addEventListener('resize', () => { if (this._visible) this._resize(); });
        this._applyMode();
    }

    _readMode() {
        try {
            return localStorage.getItem('meshpoint.topoMode') === 'map' ? 'map' : 'graph';
        } catch (_e) { return 'graph'; }
    }

    _setMode(mode) {
        this._mode = mode === 'map' ? 'map' : 'graph';
        try { localStorage.setItem('meshpoint.topoMode', this._mode); } catch (_e) {}
        this._applyMode();
    }

    _applyMode() {
        const mapEl = this.root.querySelector('.topo-map');
        const noteEl = this.root.querySelector('.topo-map-note');
        this.root.querySelectorAll('[data-mode]').forEach((btn) => {
            btn.classList.toggle('lw-tab--active', btn.dataset.mode === this._mode);
        });
        const onMap = this._mode === 'map';
        mapEl.hidden = !onMap;
        if (!onMap) {
            if (noteEl) noteEl.hidden = true;
            this._kick(0.1);
            return;
        }
        this._initMap();
        this._renderMap();
        // Leaflet measures its container; it is display:none until now.
        setTimeout(() => { if (this._map) this._map.invalidateSize(); }, 50);
    }

    _initMap() {
        if (this._map || !window.L) return;
        const mapEl = this.root.querySelector('.topo-map');
        this._map = L.map(mapEl, { zoomControl: false, scrollWheelZoom: true });
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(this._map);
        this._mapLayer = L.layerGroup().addTo(this._map);
        this._map.setView([52.37, 4.89], 11);
    }

    _renderMap() {
        if (!this._map || !this._mapLayer) return;
        const col = this._colors();
        this._mapLayer.clearLayers();

        const placed = (n) => n.lat != null && n.lon != null;
        const visible = this._visibleNodes();
        const bounds = [];

        if (this._context && Array.isArray(this._contextNodes)) {
            this._contextNodes.forEach((n) => {
                const dot = L.circleMarker([n.lat, n.lon], {
                    radius: 3,
                    color: '#6b7687',
                    weight: 1,
                    fillColor: '#6b7687',
                    fillOpacity: 0.35,
                    opacity: 0.4,
                }).addTo(this._mapLayer);
                dot.bindTooltip(
                    `${n.name || n.id}<br>no link evidence yet`,
                );
                dot.on('click', () => {
                    if (!window.nodeDrawer) return;
                    window.nodeDrawer.open({
                        node_id: n.id,
                        long_name: n.name || null,
                        protocol: n.protocol || null,
                    });
                });
            });
        }

        this._activeEdges().forEach((e) => {
            if (!placed(e.na) || !placed(e.nb)) return;
            L.polyline(
                [[e.na.lat, e.na.lon], [e.nb.lat, e.nb.lon]],
                {
                    color: col[e.kind] || col.dim,
                    weight: Math.min(1 + Math.log2(1 + (e.count || 1)), 4),
                    opacity: e.stale ? 0.3 : 0.65,
                    dashArray: e.stale ? '4 6' : null,
                },
            ).addTo(this._mapLayer);
        });

        let unplaced = 0;
        visible.forEach((n) => {
            if (!placed(n)) { unplaced += 1; return; }
            bounds.push([n.lat, n.lon]);
            const fill = n.is_self ? col.self
                : (n.protocol === 'meshcore' ? col.meshcore : col.meshtastic);
            const marker = L.circleMarker([n.lat, n.lon], {
                radius: n.is_self || n.is_anchor ? 8 : 5,
                color: n.is_anchor && !n.is_self ? col.meshcore : fill,
                weight: n.is_self || n.is_anchor ? 3 : 1.5,
                fillColor: fill,
                fillOpacity: 0.85,
            }).addTo(this._mapLayer);
            marker.bindTooltip(
                `${n.name || n.id}${n.name ? `<br>${n.id}` : ''} · ${n.degree} link${n.degree === 1 ? '' : 's'}`,
            );
            marker.on('click', () => {
                if (!window.nodeDrawer) return;
                window.nodeDrawer.open({
                    node_id: n.id,
                    long_name: n.name || null,
                    protocol: n.protocol || null,
                    role: n.role || null,
                });
            });
        });

        const noteEl = this.root.querySelector('.topo-map-note');
        if (noteEl) {
            noteEl.textContent = unplaced > 0
                ? `${unplaced} node${unplaced === 1 ? '' : 's'} without position not shown`
                : '';
            noteEl.hidden = unplaced === 0;
        }
        if (bounds.length && !this._mapFitted) {
            this._map.fitBounds(bounds, { padding: [40, 40] });
            this._mapFitted = true;
        }
    }

    _fitMap() {
        const pts = this._visibleNodes()
            .filter((n) => n.lat != null && n.lon != null)
            .map((n) => [n.lat, n.lon]);
        if (pts.length && this._map) this._map.fitBounds(pts, { padding: [40, 40] });
    }

    async _load() {
        try {
            const res = await fetch(this._context ? '/api/topology/graph?context=1' : '/api/topology/graph');
            if (!res.ok) return;
            const data = await res.json();
            if (data.context_nodes) this._contextNodes = data.context_nodes;
            this._ingest(data);
        } catch (_e) { /* transient */ }
    }

    _ingest(data) {
        this._staleDays = data.stale_days || 7;
        const prev = new Map(this._nodes.map((n) => [n.id, n]));
        this._nodes = (data.nodes || []).map((n) => {
            const old = prev.get(n.id);
            return Object.assign({
                x: old ? old.x : (Math.random() - 0.5) * 400,
                y: old ? old.y : (Math.random() - 0.5) * 400,
                vx: 0, vy: 0,
            }, n);
        });
        const byId = new Map(this._nodes.map((n) => [n.id, n]));
        const cutoff = Date.now() - this._staleDays * 86400 * 1000;
        this._edges = (data.edges || []).map((e) => Object.assign({}, e, {
            na: byId.get(e.a),
            nb: byId.get(e.b),
            stale: e.last_seen ? (Date.parse(e.last_seen) < cutoff) : true,
        })).filter((e) => e.na && e.nb);

        // Node degree drives radius and label visibility.
        this._nodes.forEach((n) => { n.degree = 0; });
        this._edges.forEach((e) => { e.na.degree += 1; e.nb.degree += 1; });

        if (this._statsEl && data.counts) {
            const c = data.counts;
            this._statsEl.textContent =
                `${c.nodes} nodes · ${c.edges} edges (${c.route} route / ${c.direct} direct / ${c.neighbour} neighbour)`;
        }
        if (this._emptyEl) this._emptyEl.hidden = this._edges.length > 0;
        this._needsFit = true;
        this._resize();
        this._kick(1);
        if (this._mode === 'map') this._renderMap();
    }

    _zoomBy(factor) {
        this._view.k = Math.min(Math.max(this._view.k * factor, 0.2), 5);
        this._view.x *= factor;
        this._view.y *= factor;
        this._draw();
    }

    _fitView() {
        const visible = this._visibleNodes();
        if (!visible.length) return;
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        visible.forEach((n) => {
            if (n.x < minX) minX = n.x;
            if (n.x > maxX) maxX = n.x;
            if (n.y < minY) minY = n.y;
            if (n.y > maxY) maxY = n.y;
        });
        const bw = Math.max(maxX - minX, 40);
        const bh = Math.max(maxY - minY, 40);
        // 80px margin keeps labels that extend past node centers readable.
        const k = Math.min((this._w - 160) / bw, (this._h - 100) / bh);
        this._view.k = Math.min(Math.max(k, 0.2), 2.5);
        this._view.x = -((minX + maxX) / 2) * this._view.k;
        this._view.y = -((minY + maxY) / 2) * this._view.k;
        this._draw();
    }

    _nodeVisible(n) {
        if (n.is_self) return this._show.self;
        if (n.is_anchor) return this._show.anchor;
        return n.protocol === 'meshcore' ? this._show.meshcore : this._show.meshtastic;
    }

    _visibleNodes() {
        return this._nodes.filter((n) => this._nodeVisible(n));
    }

    _activeEdges() {
        return this._edges.filter((e) =>
            this._kinds[e.kind] && this._nodeVisible(e.na) && this._nodeVisible(e.nb));
    }

    _resize() {
        const wrap = this._canvas.parentElement;
        const dpr = window.devicePixelRatio || 1;
        const w = wrap.clientWidth || 800;
        const h = wrap.clientHeight || 520;
        this._canvas.width = w * dpr;
        this._canvas.height = h * dpr;
        this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this._w = w;
        this._h = h;
        this._draw();
    }

    _kick(alpha) {
        this._alpha = Math.max(this._alpha, alpha);
        if (!this._raf) this._tickLoop();
    }

    _tickLoop() {
        this._raf = requestAnimationFrame(() => {
            this._raf = null;
            if (!this._visible) return;
            this._simulate();
            this._draw();
            this._alpha *= 0.985;
            if (this._needsFit && this._alpha < 0.05) {
                this._needsFit = false;
                this._fitView();
            }
            if (this._alpha > 0.005 || this._drag) this._tickLoop();
        });
    }

    _simulate() {
        const nodes = this._visibleNodes();
        const edges = this._activeEdges();
        const a = this._alpha;
        const repulsion = 1800;
        const springLen = 90;
        const springK = 0.04;

        for (let i = 0; i < nodes.length; i++) {
            const n1 = nodes[i];
            for (let j = i + 1; j < nodes.length; j++) {
                const n2 = nodes[j];
                let dx = n1.x - n2.x;
                let dy = n1.y - n2.y;
                let d2 = dx * dx + dy * dy;
                if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
                const f = (repulsion / d2) * a;
                const d = Math.sqrt(d2);
                dx /= d; dy /= d;
                n1.vx += dx * f; n1.vy += dy * f;
                n2.vx -= dx * f; n2.vy -= dy * f;
            }
        }
        edges.forEach((e) => {
            const dx = e.nb.x - e.na.x;
            const dy = e.nb.y - e.na.y;
            const d = Math.sqrt(dx * dx + dy * dy) || 1;
            const f = (d - springLen) * springK * a;
            const fx = (dx / d) * f;
            const fy = (dy / d) * f;
            e.na.vx += fx; e.na.vy += fy;
            e.nb.vx -= fx; e.nb.vy -= fy;
        });
        nodes.forEach((n) => {
            // Gentle centering so disconnected clusters stay on screen.
            n.vx -= n.x * 0.003 * a;
            n.vy -= n.y * 0.003 * a;
            if (this._drag && this._drag.node === n) { n.vx = 0; n.vy = 0; return; }
            n.x += n.vx; n.y += n.vy;
            n.vx *= 0.85; n.vy *= 0.85;
        });
    }

    _colors() {
        const styles = getComputedStyle(document.documentElement);
        const v = (name, fb) => (styles.getPropertyValue(name) || '').trim() || fb;
        return {
            meshtastic: v('--accent-cyan', '#22d3ee'),
            meshcore: v('--accent-amber', '#fbbf24'),
            self: v('--accent-green', '#34d399'),
            text: v('--text-primary', '#dbe4ee'),
            dim: v('--text-secondary', '#8b98a9'),
            route: v('--accent-cyan', '#22d3ee'),
            direct: v('--accent-green', '#34d399'),
            neighbour: v('--accent-amber', '#fbbf24'),
        };
    }

    _draw() {
        const ctx = this._ctx;
        if (!ctx) return;
        const col = this._colors();
        ctx.clearRect(0, 0, this._w, this._h);
        ctx.save();
        ctx.translate(this._w / 2 + this._view.x, this._h / 2 + this._view.y);
        ctx.scale(this._view.k, this._view.k);

        const selected = this._selected;
        this._activeEdges().forEach((e) => {
            const emphasized = selected && (e.na === selected || e.nb === selected);
            const faded = selected && !emphasized;
            ctx.beginPath();
            ctx.moveTo(e.na.x, e.na.y);
            ctx.lineTo(e.nb.x, e.nb.y);
            ctx.strokeStyle = col[e.kind] || col.dim;
            ctx.globalAlpha = faded ? 0.08 : (e.stale ? 0.25 : (emphasized ? 0.95 : 0.55));
            ctx.lineWidth = Math.min(1 + Math.log2(1 + (e.count || 1)), 4) / this._view.k;
            ctx.setLineDash(e.stale ? [4 / this._view.k, 4 / this._view.k] : []);
            ctx.stroke();
        });
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;

        this._visibleNodes().forEach((n) => {
            const r = (n.is_self ? 9 : 4 + Math.min(Math.log2(1 + n.degree) * 2, 6)) / Math.sqrt(this._view.k);
            const fill = n.is_self ? col.self : (n.protocol === 'meshcore' ? col.meshcore : col.meshtastic);
            const faded = selected && n !== selected &&
                !this._activeEdges().some((e) => (e.na === selected && e.nb === n) || (e.nb === selected && e.na === n));
            ctx.globalAlpha = faded ? 0.2 : 1;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
            ctx.fillStyle = fill;
            ctx.fill();
            if (n.is_self || n.is_anchor || n === selected) {
                ctx.beginPath();
                ctx.arc(n.x, n.y, r + 3 / this._view.k, 0, Math.PI * 2);
                ctx.strokeStyle = n.is_anchor && !n.is_self ? col.meshcore : col.self;
                ctx.lineWidth = 1.5 / this._view.k;
                ctx.stroke();
            }
            const label = n.name || (n.degree >= 3 ? n.id : null);
            if (label && !faded) {
                ctx.font = `${11 / this._view.k}px sans-serif`;
                ctx.fillStyle = n.name ? col.text : col.dim;
                ctx.fillText(label, n.x + r + 4 / this._view.k, n.y + 4 / this._view.k);
            }
        });
        ctx.globalAlpha = 1;
        ctx.restore();
    }

    // ---- pointer interactions -------------------------------------------

    _toWorld(px, py) {
        return {
            x: (px - this._w / 2 - this._view.x) / this._view.k,
            y: (py - this._h / 2 - this._view.y) / this._view.k,
        };
    }

    _nodeAt(px, py) {
        const p = this._toWorld(px, py);
        let best = null;
        let bestD = 12 / this._view.k;
        this._visibleNodes().forEach((n) => {
            const d = Math.hypot(n.x - p.x, n.y - p.y);
            if (d < bestD) { best = n; bestD = d; }
        });
        return best;
    }

    _bindPointer() {
        const canvas = this._canvas;
        const pos = (ev) => {
            const rect = canvas.getBoundingClientRect();
            return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
        };

        canvas.addEventListener('pointerdown', (ev) => {
            const p = pos(ev);
            const node = this._nodeAt(p.x, p.y);
            this._drag = node
                ? { node, moved: false }
                : { pan: true, sx: p.x, sy: p.y, vx: this._view.x, vy: this._view.y, moved: false };
            canvas.setPointerCapture(ev.pointerId);
        });

        canvas.addEventListener('pointermove', (ev) => {
            const p = pos(ev);
            if (this._drag) {
                this._drag.moved = true;
                if (this._drag.node) {
                    const w = this._toWorld(p.x, p.y);
                    this._drag.node.x = w.x;
                    this._drag.node.y = w.y;
                    this._kick(0.15);
                } else {
                    this._view.x = this._drag.vx + (p.x - this._drag.sx);
                    this._view.y = this._drag.vy + (p.y - this._drag.sy);
                    this._draw();
                }
                return;
            }
            const node = this._nodeAt(p.x, p.y);
            if (node !== this._hover) {
                this._hover = node;
                this._renderTooltip(node, p);
                canvas.style.cursor = node ? 'pointer' : 'grab';
            } else if (node) {
                this._renderTooltip(node, p);
            }
        });

        const endDrag = (ev) => {
            if (!this._drag) return;
            if (!this._drag.moved) {
                const p = pos(ev);
                const node = this._nodeAt(p.x, p.y);
                this._selected = (node && node !== this._selected) ? node : null;
                this._draw();
                if (this._selected && window.nodeDrawer) {
                    window.nodeDrawer.open({
                        node_id: this._selected.id,
                        long_name: this._selected.name || null,
                        protocol: this._selected.protocol || null,
                        role: this._selected.role || null,
                    });
                }
            }
            this._drag = null;
        };
        canvas.addEventListener('pointerup', endDrag);
        canvas.addEventListener('pointercancel', () => { this._drag = null; });
        canvas.addEventListener('pointerleave', () => {
            this._hover = null;
            if (this._tooltip) this._tooltip.hidden = true;
        });

        canvas.addEventListener('wheel', (ev) => {
            ev.preventDefault();
            const factor = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
            this._view.k = Math.min(Math.max(this._view.k * factor, 0.2), 5);
            this._draw();
        }, { passive: false });
    }

    _renderTooltip(node, p) {
        if (!this._tooltip) return;
        if (!node) { this._tooltip.hidden = true; return; }
        const lines = [];
        lines.push(`<strong>${this._esc(node.name || node.id)}</strong>`);
        if (node.name) lines.push(this._esc(node.id));
        const meta = [node.protocol, node.role].filter(Boolean).join(' · ');
        if (meta) lines.push(this._esc(meta));
        lines.push(`${node.degree} link${node.degree === 1 ? '' : 's'}`);
        this._tooltip.innerHTML = lines.join('<br>');
        this._tooltip.style.left = `${p.x + 14}px`;
        this._tooltip.style.top = `${p.y + 14}px`;
        this._tooltip.hidden = false;
    }

    _esc(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

window.TopologyTab = TopologyTab;
