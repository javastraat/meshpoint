/**
 * Sidebar Messages item — unread-DM count badge, kept correct from the
 * very first page load rather than only after the Messages page itself
 * has been opened once this session.
 *
 * messaging.js's own MessagingPanel._syncSidebarBadge() already keeps
 * #msg-unread-badge correct once the full panel is initialized — but
 * that only happens lazily, on visiting Messages (or a "Send Message"
 * action that opens a conversation there), since MessagingPanel.init()
 * early-returns if #messaging-panel isn't in the current page's DOM.
 * A session that lands on any other page first left the badge blank
 * even with real unread DMs waiting server-side. Confirmed live:
 * navigating straight to Reticulum Dashboard showed no badge despite
 * an unread Reticulum DM; opening Messages (or clicking a peer's own
 * "Send Message") made it appear correctly from then on.
 *
 * Same computation as MessagingContacts.getDmUnreadTotal() — sum
 * non-broadcast unread_count from GET /api/messages/conversations —
 * just runnable without the full panel existing. The two writers never
 * conflict: whichever ran most recently wins, and both compute the
 * same number from the same server truth.
 */
class MessagesUnreadBadge {
    constructor(ws) {
        this._ws = ws;
    }

    init() {
        this._refresh();
        if (this._ws && typeof this._ws.on === 'function') {
            this._ws.on('message_received', () => this._refresh());
        }
    }

    async _refresh() {
        try {
            const res = await fetch('/api/messages/conversations?include_overheard=true', {
                credentials: 'same-origin',
            });
            if (!res.ok) return;
            const conversations = await res.json();
            const total = conversations
                .filter((c) => !c.is_broadcast)
                .reduce((sum, c) => sum + (c.unread_count || 0), 0);
            this._apply(total);
        } catch (_e) {
            // Swallow: leaves the last-known badge state in place, next event retries.
        }
    }

    _apply(total) {
        const badge = document.getElementById('msg-unread-badge');
        if (!badge) return;
        if (total > 0) {
            badge.textContent = String(total);
            badge.style.display = 'inline-block';
        } else {
            badge.textContent = '';
            badge.style.display = 'none';
        }
    }
}

window.MessagesUnreadBadge = MessagesUnreadBadge;
