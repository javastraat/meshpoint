/**
 * Browser-local "favorite" channel list for the Messages sidebar.
 *
 * User request (2026-07-12, on behalf of a friend): channels sorted by
 * the server-side config order (channel_keys insertion order) all the
 * time was too rigid -- some users want their own channel(s) pinned to
 * the top regardless of where they land in local.yaml. Mirrors
 * meshpoint_node_favorites.js's shape exactly (a proven pattern already
 * shipped for the Node Cards list/drawer/map), just for channel node_ids
 * instead of mesh node_ids -- kept as a separate module rather than
 * generalizing the node one, since the two domains have nothing else in
 * common and duplication here is cheap.
 *
 * Storage key: meshpoint.channelFavorites (array of node_id strings).
 * Change event: meshpoint:channel-favorites (CustomEvent with detail.list).
 *
 * Cap is 50 entries -- generous for a channel list (realistically a
 * handful per protocol) while still bounding localStorage growth.
 *
 * IIFE wrap: see meshpoint_node_favorites.js's comment on why -- classic
 * <script> tags share one global lexical scope, so sibling modules'
 * top-level const/let would collide without this.
 */

(function () {
    const STORAGE_KEY = 'meshpoint.channelFavorites';
    const CHANGE_EVENT = 'meshpoint:channel-favorites';
    const MAX_FAVORITES = 50;

    function _load() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) return [];
            return parsed.filter((v) => typeof v === 'string' && v.length > 0);
        } catch (_e) {
            return [];
        }
    }

    let _favorites = _load();

    function _save() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(_favorites));
        } catch (_e) {
            /* private mode / quota -- best-effort persistence */
        }
    }

    function _emit() {
        window.dispatchEvent(new CustomEvent(CHANGE_EVENT, {
            detail: { list: [..._favorites] },
        }));
    }

    class MeshpointChannelFavorites {
        /** @returns {string[]} a copy of the favorites list (no live reference). */
        static list() {
            return [..._favorites];
        }

        /** @param {string} nodeId */
        static has(nodeId) {
            if (!nodeId) return false;
            return _favorites.includes(String(nodeId));
        }

        /**
         * Toggle membership. Returns true if the channel is now favorited,
         * false if it was just removed.
         * @param {string} nodeId
         */
        static toggle(nodeId) {
            if (!nodeId) return false;
            const id = String(nodeId);
            const idx = _favorites.indexOf(id);
            if (idx >= 0) {
                _favorites.splice(idx, 1);
                _save();
                _emit();
                return false;
            }
            if (_favorites.length >= MAX_FAVORITES) {
                console.warn(
                    `MeshpointChannelFavorites: cap of ${MAX_FAVORITES} reached, ` +
                    'dropping oldest entry to make room.'
                );
                _favorites.shift();
            }
            _favorites.push(id);
            _save();
            _emit();
            return true;
        }

        /**
         * Subscribe to favorite-list changes.
         * @param {(event: CustomEvent) => void} handler
         * @returns {() => void} unsubscribe function
         */
        static onChange(handler) {
            window.addEventListener(CHANGE_EVENT, handler);
            return () => window.removeEventListener(CHANGE_EVENT, handler);
        }
    }

    window.MeshpointChannelFavorites = MeshpointChannelFavorites;
})();
