/**
 * Soft hash router for the dashboard.
 *
 * One responsibility: turn the URL hash into a route id and notify
 * subscribers. No DOM, no styling, no business logic. The sidebar
 * controller subscribes to drive section visibility + active state.
 *
 * Route ids look like:
 *
 *   "dashboard"
 *   "stats"
 *   "messages"
 *   "radio"
 *   "terminal"
 *   "configuration/identity"
 *   "configuration/radio"
 *   "settings/updates"
 *
 * Default route is whatever was passed to the constructor; on a
 * fresh load with an empty hash we synthesize a #/<default> so
 * back-button history starts in a clean place.
 */

class Router {
    constructor(options = {}) {
        this._defaultRoute = options.defaultRoute || 'dashboard';
        this._allowedRoutes = new Set(options.allowedRoutes || []);
        // Optional role guard: (route) => bool. A rejected route renders
        // the "forbidden" section on a fresh load; when the user is
        // already on a page, navigation is cancelled in place and
        // onDenied fires instead (so a toast can explain why).
        this._guard = options.guard || null;
        this._onDenied = options.onDenied || null;
        this._listeners = new Set();
        this._currentRoute = null;
        this._onHashChange = this._onHashChange.bind(this);
    }

    start() {
        window.addEventListener('hashchange', this._onHashChange);
        if (!location.hash || location.hash === '#') {
            this.navigate(this._defaultRoute, { replace: true });
        } else {
            this._dispatch(this._readRouteFromHash());
        }
    }

    stop() {
        window.removeEventListener('hashchange', this._onHashChange);
    }

    onRouteChange(handler) {
        this._listeners.add(handler);
        if (this._currentRoute) handler(this._currentRoute);
        return () => this._listeners.delete(handler);
    }

    navigate(route, { replace = false } = {}) {
        const target = `#/${route}`;
        if (replace) {
            history.replaceState(null, '', target);
            this._dispatch(route);
        } else {
            location.hash = target;
        }
    }

    currentRoute() {
        return this._currentRoute;
    }

    _onHashChange() {
        const route = this._readRouteFromHash();
        if (route === 'forbidden'
            && this._currentRoute
            && this._currentRoute !== 'forbidden') {
            // In-app click on an admin route: stay where we are and
            // let the shell surface the denial (toast) instead of
            // yanking the user off to the forbidden page.
            history.replaceState(null, '', `#/${this._currentRoute}`);
            if (this._onDenied) this._onDenied();
            return;
        }
        if (route !== this._currentRoute) this._dispatch(route);
    }

    _readRouteFromHash() {
        const raw = location.hash.replace(/^#\/?/, '').trim();
        if (!raw) return this._defaultRoute;
        if (this._allowedRoutes.size && !this._allowedRoutes.has(raw)) {
            return this._defaultRoute;
        }
        if (this._guard && !this._guard(raw)) return 'forbidden';
        return raw;
    }

    _dispatch(route) {
        this._currentRoute = route;
        this._listeners.forEach((handler) => {
            try { handler(route); } catch (err) { console.error('Router listener:', err); }
        });
    }
}

window.Router = Router;
