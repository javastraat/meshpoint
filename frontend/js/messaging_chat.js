/**
 * Chat view renderer for interleaved sent/received messages.
 * Handles the message display area, compose bar, auto-scroll,
 * and lazy-loading of older messages.
 */
class MessagingChat {
    constructor(containerEl, onSend) {
        this._container = containerEl;
        this._onSend = onSend;
        this._conversation = null;
        this._messages = [];
        this._loading = false;
        this._allLoaded = false;
        this._lastDayKey = null;
        // MeshCore feedback that arrived before its bubble got a real id.
        this._feedback = new Map();
        this._build();
    }

    clearChat() {
        this._closePaths?.();
        this._conversation = null;
        this._messages = [];
        this._allLoaded = false;
        this._renderEmptyState();
        this._headerName.textContent = '';
        this._headerSubtitle.textContent = '';
        this._headerBadge.textContent = '';
        this._connectionBadge.textContent = '';
        this._headerAvatar.textContent = '';
        this._headerAvatar.className = 'msg-chat__avatar';
        this._container.classList.add('msg-chat--empty');
        this._input.disabled = true;
        this._sendBtn.disabled = true;
        this._clearAttachment();
    }

    setConversation(convo) {
        this._closePaths?.();
        this._conversation = convo;
        this._messages = [];
        this._allLoaded = false;
        this._clearAttachment();

        const name = convo.node_name || convo.node_id || '';
        const isChannel = (convo.node_id || '').startsWith('broadcast:');
        // A "keyed" bucket (see server.py's on_text_packet) is traffic
        // that decrypted fine with one of our configured keys but
        // carries a hash that doesn't match any locally-computed
        // name+key combo -- the remote side just named the channel
        // differently. We know exactly which key to reply with, so
        // this IS repliable (messaging.js routes the send through the
        // matched key index + echoes back the original hash byte).
        // A plain "unmapped" bucket, by contrast, has no matching key
        // at all -- there's no channel number a reply could correctly
        // go out on, so replying stays disabled there.
        const isKeyed = /:keyed:\d+:0x[0-9a-f]+$/i.test(convo.node_id || '');
        const isUnmapped = !isKeyed && (convo.node_id || '').includes(':unmapped:');
        // This page's own conversation list isn't Meshtastic/MeshCore-only
        // -- it reads from the same shared `messages` table Reticulum and
        // Pager also write to (protocol='reticulum'/'pager') -- so this
        // can't just be a binary MC/MT choice. Anything else falls back
        // to its own uppercased protocol name with the neutral badge/
        // avatar color (no --mt/--mc modifier applied), rather than being
        // mislabeled as Meshtastic.
        const PROTO_LABELS = { meshtastic: 'MT', meshcore: 'MC', reticulum: 'RT', localmesh: 'LM', pager: 'PAGER' };
        const proto = PROTO_LABELS[convo.protocol] || (convo.protocol || '').toUpperCase() || 'MT';

        this._headerName.textContent = name;
        this._headerName.classList.toggle('msg-chat__name--clickable', !isChannel);
        this._headerSubtitle.textContent = isUnmapped
            ? "Unmapped channel hash — no local channel matches, can't reply"
            : isKeyed
                ? 'Same key, different channel name on their side · replies still work'
                : isChannel
                    ? 'Public channel · all listeners on this PSK'
                    : 'Direct message';
        this._headerBadge.textContent = proto;
        this._headerBadge.className = 'msg-chat__protocol-badge ' + (
            convo.protocol === 'meshcore' ? 'msg-chat__protocol-badge--mc'
            : convo.protocol === 'meshtastic' ? 'msg-chat__protocol-badge--mt'
            : '' // reticulum/pager/etc -- neutral badge color, no wrong MT tint
        );

        // Which specific companion/stick this contact was last heard
        // through -- distinct from the protocol badge above, since a
        // multi-radio setup (2+ MeshCore companions, 2+ Meshtastic
        // sticks) can hear the SAME protocol on different bands.
        const connectionLabel = convo.protocol === 'localmesh' ? '' : this._formatConnectionLabel(convo.capture_source);
        this._connectionBadge.textContent = connectionLabel;
        this._connectionBadge.hidden = !connectionLabel;

        this._headerAvatar.textContent = isChannel ? '#' : this._initials(name);
        this._headerAvatar.className = 'msg-chat__avatar' + (
            isChannel ? ' msg-chat__avatar--channel'
            : convo.protocol === 'meshcore' ? ' msg-chat__avatar--mc'
            : convo.protocol === 'meshtastic' ? ' msg-chat__avatar--mt'
            : '' // reticulum/pager/etc -- neutral avatar color
        );

        this._messagesEl.innerHTML = '';
        this._lastDayKey = null;
        this._container.classList.remove('msg-chat--empty');
        // Image attachments are an LXMF thing (FIELD_IMAGE) -- Meshtastic/
        // MeshCore/Pager have no wire-level attachment mechanism at all,
        // so the icon only makes sense, and only appears, for Reticulum.
        this._attachBtn.hidden = convo.protocol !== 'reticulum';
        const readOnly = !!window.meshpointReadOnly;
        if (readOnly) this._attachBtn.hidden = true;
        this._input.disabled = isUnmapped || readOnly;
        this._sendBtn.disabled = isUnmapped || readOnly;
        this._input.placeholder = readOnly
            ? 'Read-only: sending needs an administrator'
            : isUnmapped
                ? "Can't reply -- no matching local channel"
                : 'Type a message…';
        if (!isUnmapped && !readOnly) this._input.focus();
        this._loadMessages();
    }

    addMessage(msg) {
        this._messages.push(msg);
        this._appendBubble(msg);
        this._scrollToBottom();
    }

    addOptimisticMessage(text, protocol, localPreviewUrl) {
        const msg = {
            id: Date.now(),
            direction: 'sent',
            text: text,
            node_id: this._conversation?.node_id || '',
            node_name: '',
            protocol: protocol || this._conversation?.protocol || 'meshtastic',
            channel: 0,
            timestamp: new Date().toISOString(),
            status: 'sending...',
            packet_id: '',
            // Client-only, never round-trips to/from the server -- see
            // _buildAttachmentHtml's own comment on why this bubble needs
            // its own preview instead of the real attachment id.
            _localPreviewUrl: localPreviewUrl || null,
        };
        this.addMessage(msg);
        return msg;
    }

    removeMessage(tempId) {
        const bubble = this._messagesEl.querySelector(`[data-msg-id="${tempId}"]`);
        if (bubble) bubble.remove();
        this._messages = this._messages.filter((m) => m.id !== tempId);
        if (this._messages.length === 0) {
            this._lastDayKey = null;
            this._renderConversationEmptyState();
        }
    }

    updateMessageStatus(tempId, status, packetId, feedback = {}) {
        const msg = this._messages.find((m) => m.id === tempId);
        const bubble = this._messagesEl.querySelector(`[data-msg-id="${tempId}"]`);
        if (!msg) {
            // Not in the list (shouldn't happen): keep the old plain update.
            const meta = bubble && bubble.querySelector('.msg-bubble__meta');
            if (meta) {
                const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                meta.textContent = `${time} · ${status}`;
            }
            return;
        }
        msg.status = status;
        if (packetId) msg.packet_id = packetId;
        if (!msg.timestamp) msg.timestamp = new Date().toISOString();
        this._mergeFeedback(msg, feedback || {});
        if (feedback && feedback.id != null) msg.id = feedback.id;
        if (bubble) {
            bubble.dataset.msgId = msg.id;
            if (packetId) bubble.dataset.pktId = packetId;
            const meta = bubble.querySelector('.msg-bubble__meta');
            if (meta) {
                if (this._pathAnchor && meta.contains(this._pathAnchor)) this._closePaths();
                meta.innerHTML = this._buildMetaHtml(msg, true);
            }
        }
    }

    /** WS 'message_repeats': a later echo or ACK for a MeshCore send. */
    updateMeshcoreFeedback(data) {
        if (!data || data.protocol !== 'meshcore' || !data.packet_id) return;
        const cached = this._feedback.get(data.packet_id) || {};
        this._mergeFeedback(cached, data);
        this._feedback.set(data.packet_id, cached);
        if (this._feedback.size > 128) this._feedback.delete(this._feedback.keys().next().value);
        const msg = this._messages.find((m) => m.direction === 'sent'
            && m.protocol === 'meshcore' && m.packet_id === data.packet_id);
        if (msg) this.updateMessageStatus(msg.id, msg.status, msg.packet_id, cached);
    }

    /** Repeats only go up; status only ever becomes 'delivered'. */
    _mergeFeedback(msg, data) {
        if (Number.isInteger(data.heard_repeats) && data.heard_repeats >= 0) {
            msg.heard_repeats = Math.max(msg.heard_repeats || 0, data.heard_repeats);
        }
        if (data.status === 'delivered') msg.status = 'delivered';
    }

    /** Bubble footer: time, status, MeshCore feedback, signal. */
    _buildMetaHtml(msg, showStatus) {
        this._mergeFeedback(msg, this._feedback.get(msg.packet_id) || {});
        const time = msg.timestamp
            ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
            : '';
        let status = showStatus && msg.status && !['delivered', 'read'].includes(msg.status)
            ? msg.status : '';
        let repeat = '';
        if (msg.direction === 'sent' && msg.protocol === 'meshcore') {
            const direct = !(msg.node_id || '').startsWith('broadcast:');
            if (msg.status === 'delivered') status = 'Delivered';
            else if (direct && msg.status === 'sent') status = 'Sent · Delivery unconfirmed';
            if (Number.isInteger(msg.heard_repeats) && msg.heard_repeats >= 0) {
                const n = msg.heard_repeats;
                const label = `Heard ${n} repeat${n === 1 ? '' : 's'}`;
                // A button: hover/tap shows which repeaters (upstream a451d1e2).
                repeat = ` · <button type="button" class="msg-heard" aria-haspopup="dialog" aria-expanded="false"`
                    + ` aria-label="${label}. Show heard paths">${label}</button>`;
            }
        }
        return `${time}${status ? ' · ' + this._esc(status) : ''}${repeat}${this._buildSignalHtml(msg)}`;
    }

    clear() {
        this.clearChat();
    }

    async _loadMessages() {
        if (!this._conversation || this._loading) return;
        this._loading = true;

        try {
            const nodeId = encodeURIComponent(this._conversation.node_id);
            const res = await fetch(`/api/messages/conversation/${nodeId}?limit=50`);
            const messages = await res.json();
            this._messages = messages;

            this._messagesEl.innerHTML = '';
            if (messages.length === 0) {
                this._renderConversationEmptyState();
            } else {
                messages.forEach(msg => this._appendBubble(msg));
                this._scrollToBottom();
            }

            if (messages.length < 50) this._allLoaded = true;

            // Read state is shared: a viewer must not clear it (admin-only on the server too).
            if (!window.meshpointReadOnly) {
                await fetch(`/api/messages/conversation/${nodeId}/read`, { method: 'POST' });
            }
        } catch (e) {
            console.error('Failed to load messages:', e);
        } finally {
            this._loading = false;
        }
    }

    _renderEmptyState() {
        this._messagesEl.innerHTML = `
            <div class="msg-chat__placeholder">
                <div class="msg-chat__placeholder-icon" aria-hidden="true">
                    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M14 18a6 6 0 016-6h24a6 6 0 016 6v18a6 6 0 01-6 6H28l-9 8v-8h-1a6 6 0 01-4-2"
                              stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
                        <circle cx="26" cy="27" r="1.8" fill="currentColor" />
                        <circle cx="32" cy="27" r="1.8" fill="currentColor" />
                        <circle cx="38" cy="27" r="1.8" fill="currentColor" />
                    </svg>
                </div>
                <h3 class="msg-chat__placeholder-title">No conversation selected</h3>
                <p class="msg-chat__placeholder-body">
                    Choose a channel or direct message in the list on the left,
                    or tap <span class="msg-chat__placeholder-cta">+ New</span>
                    to start a DM with a specific node.
                </p>
                <p class="msg-chat__placeholder-hint">
                    Filter the list with
                    <span class="msg-chat__placeholder-tag msg-chat__placeholder-tag--all">All</span>,
                    <span class="msg-chat__placeholder-tag msg-chat__placeholder-tag--mt">MT</span>
                    (Meshtastic), or
                    <span class="msg-chat__placeholder-tag msg-chat__placeholder-tag--mc">MC</span>
                    (MeshCore). Open a thread to read messages; highlight text
                    to copy like any web page.
                </p>
            </div>
        `;
    }

    _renderConversationEmptyState() {
        this._messagesEl.innerHTML = `
            <div class="msg-chat__placeholder msg-chat__placeholder--inset">
                <div class="msg-chat__placeholder-icon msg-chat__placeholder-icon--small" aria-hidden="true">
                    <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M10 14a4 4 0 014-4h20a4 4 0 014 4v14a4 4 0 01-4 4H22l-7 6v-6h-1a4 4 0 01-4-4V14z"
                              stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
                    </svg>
                </div>
                <p class="msg-chat__placeholder-body">
                    No messages in this thread yet. Type below and send
                    when you are ready.
                </p>
            </div>
        `;
    }

    /** "meshcore_usb_433" -> "433", "serial_868" -> "868", bare
     * "meshcore_usb"/"serial" -> "USB", "concentrator" -> "Concentrator",
     * anything else shown as-is. Empty/missing capture_source (e.g. a
     * brand-new conversation/channel with no packet history yet) hides
     * the badge entirely rather than showing a blank pill. Channel
     * conversations get this too now -- scoped to whichever capture
     * source most recently heard that PROTOCOL, not the exact channel
     * (packets aren't tagged per-channel), so it's a coarser signal than
     * the per-contact DM case but still tells 868 and 433 apart. */
    _formatConnectionLabel(captureSource) {
        if (!captureSource) return '';
        if (captureSource === 'concentrator') return 'Concentrator';
        const match = captureSource.match(/_(\d+)$/);
        if (match) return match[1];
        if (captureSource === 'meshcore_usb' || captureSource === 'serial') return 'USB';
        return captureSource;
    }

    _initials(name) {
        if (!name) return '?';
        const trimmed = name.trim();
        const parts = trimmed.split(/[\s_\-.]+/).filter(Boolean);
        if (parts.length === 0) return trimmed[0].toUpperCase();
        if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    /** LocalMesh channel messages stored before the plugin named senders: the row's name is a bare member
     * number and the text starts with the "Name: " the app puts in front. Show them like the newer rows. */
    _normalizeLocalMeshChannelMessage(msg) {
        if (msg.protocol !== 'localmesh' || msg.direction !== 'received'
            || !(msg.node_id || '').startsWith('broadcast:')) return msg;
        if (msg.node_name && !/^\d+$/.test(msg.node_name)) return msg;
        const found = /^([^:\n]{1,32}): ([\s\S]*)$/.exec(msg.text || '');
        return found ? { ...msg, node_name: found[1].trim(), text: found[2] } : msg;
    }

    _appendBubble(msg) {
        msg = this._normalizeLocalMeshChannelMessage(msg);
        const empty = this._messagesEl.querySelector('.msg-chat__empty');
        if (empty) empty.remove();

        this._insertDaySeparator(msg.timestamp);

        const bubble = document.createElement('div');
        bubble.className = `msg-bubble msg-bubble--${msg.direction}`;
        bubble.dataset.msgId = msg.id;
        if (msg.packet_id) bubble.dataset.pktId = msg.packet_id;

        const senderHtml = this._buildSenderHtml(msg);
        const attachmentHtml = this._buildAttachmentHtml(msg);

        bubble.innerHTML = `
            ${senderHtml}
            ${attachmentHtml}
            <div class="msg-bubble__text">${this._esc(msg.text)}</div>
            <div class="msg-bubble__meta">${this._buildMetaHtml(msg, true)}</div>
        `;

        this._messagesEl.appendChild(bubble);
    }

    /** Currently only Reticulum's Send-tab image attachments populate
     * this (see plugins/apps/reticulum/backend/attachments.py) -- the
     * `attachments` array shape is generic (`{kind, id, mime, size}`) so
     * any future protocol/kind can reuse the same column without a
     * migration, but only `kind: "image"` renders here today. */
    _buildAttachmentHtml(msg) {
        // The optimistic bubble for our own just-sent image (see
        // _sendReticulumMessage's data: URI) has no server-assigned
        // attachment id yet -- show the local preview until the real
        // message data replaces it (see the class doc comment above).
        if (msg._localPreviewUrl) {
            return `<img class="msg-bubble__attachment" src="${this._esc(msg._localPreviewUrl)}" alt="Attached image">`;
        }
        const list = Array.isArray(msg.attachments) ? msg.attachments : [];
        const images = list.filter((a) => a && a.kind === 'image' && a.id);
        if (!images.length) return '';
        return images.map((a) => {
            const url = `/api/reticulum/attachments/${encodeURIComponent(a.id)}`;
            return `<img class="msg-bubble__attachment" src="${this._esc(url)}" `
                + `alt="Attached image" loading="lazy" data-attachment-open="${this._esc(url)}">`;
        }).join('');
    }

    _buildSenderHtml(msg) {
        if (msg.direction !== 'received') return '';
        const name = this._receivedSenderLabel(msg);
        if (!name) return '';
        const nid = this._senderNodeId(msg);
        // LocalMesh channel rows from before packet ids carry no member, only the name (or number) shown here.
        const lmByName = !nid && msg.protocol === 'localmesh' && (msg.node_id || '').startsWith('broadcast:');
        const attr = nid ? ` data-node-id="${this._esc(nid)}"`
            : lmByName ? ` data-lm-name="${this._esc(name)}"` : '';
        const cls = nid || lmByName ? ' msg-bubble__sender--clickable' : '';
        return `<div class="msg-bubble__sender${cls}"${attr}>${this._esc(name)}</div>`;
    }

    /** The real node ID behind a received message's sender label, or
     * null if none is available to click through to. DMs: node_id IS
     * the one contact. Channels: node_id is the channel/broadcast
     * identifier, not a node -- the actual per-message sender's ID
     * only arrives as source_id, resolved server-side from the
     * packet (message_name_resolver.py's _resolve_broadcast_sender). */
    _senderNodeId(msg) {
        const nid = msg.node_id || '';
        if (nid.startsWith('broadcast:')) {
            // LocalMesh packet ids are "localmesh:<member>:<channel>:<counter>" (see the plugin's listener.py).
            const lm = msg.protocol === 'localmesh' ? /^localmesh:(\d+):/.exec(msg.packet_id || '') : null;
            return lm ? `localmesh:${lm[1]}` : (msg.source_id || null);
        }
        return nid || null;
    }

    _scrollToBottom() {
        requestAnimationFrame(() => {
            this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
        });
    }

    async _handleSend() {
        const text = this._input.value.trim();
        if (!text || !this._conversation) return;

        let image = null;
        if (this._pendingImageFile) {
            try {
                const image_type = (this._pendingImageFile.type || '').replace('image/', '') || 'bin';
                const image_b64 = this._arrayBufferToBase64(await this._pendingImageFile.arrayBuffer());
                image = { image_type, image_b64 };
            } catch (_) {
                this._showAttachmentError('Could not read the image file.');
                return;
            }
        }

        this._input.value = '';
        this._clearAttachment();
        this._onSend(text, this._conversation, image);
    }

    /** Same 5 MB cap as backend/attachments.py's MAX_IMAGE_BYTES (see
     * reticulum_panel.js's own Send-tab image picker) -- checked here
     * too so an oversized picture fails fast instead of base64-encoding
     * several extra MB just to have the server reject it. */
    _onFilePicked() {
        const file = this._fileInput.files?.[0] || null;
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
            this._showAttachmentError(`Image is ${(file.size / 1024 / 1024).toFixed(1)} MB, max 5 MB.`);
            this._fileInput.value = '';
            return;
        }
        this._pendingImageFile = file;
        this._attachmentChip.classList.remove('msg-compose-attachment--error');
        this._attachmentNameEl.textContent = file.name;
        this._attachmentChip.hidden = false;
    }

    _showAttachmentError(text) {
        this._pendingImageFile = null;
        this._attachmentChip.classList.add('msg-compose-attachment--error');
        this._attachmentNameEl.textContent = text;
        this._attachmentChip.hidden = false;
    }

    _clearAttachment() {
        this._pendingImageFile = null;
        if (this._fileInput) this._fileInput.value = '';
        if (this._attachmentChip) {
            this._attachmentChip.hidden = true;
            this._attachmentChip.classList.remove('msg-compose-attachment--error');
        }
    }

    /** Same chunked encode reticulum_panel.js's own Send-tab image picker
     * uses -- String.fromCharCode.apply on the whole buffer at once can
     * blow the call stack on a large image, so this feeds it in 32 KB
     * chunks instead. */
    _arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        const chunkSize = 0x8000;
        let binary = '';
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        return btoa(binary);
    }

    _build() {
        this._container.classList.add('msg-chat', 'msg-chat--empty');
        this._container.innerHTML = `
            <div class="msg-chat__header">
                <span class="msg-chat__avatar" aria-hidden="true"></span>
                <div class="msg-chat__header-text">
                    <span class="msg-chat__name"></span>
                    <span class="msg-chat__subtitle"></span>
                </div>
                <span class="msg-chat__protocol-badge"></span>
                <span class="msg-chat__connection-badge" title="Which USB companion/stick this contact was last heard through"></span>
            </div>
            <div class="msg-chat__messages"></div>
            <div class="msg-compose-attachment" hidden>
                <span class="msg-compose-attachment__name"></span>
                <button type="button" class="msg-compose-attachment__remove" aria-label="Remove attachment">&times;</button>
            </div>
            <div class="msg-compose">
                <button class="msg-compose__attach" type="button" title="Attach image" aria-label="Attach image" hidden>
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
                    </svg>
                </button>
                <input class="msg-compose__file" type="file" accept="image/*" hidden />
                <input class="msg-compose__input" placeholder="Type a message…" disabled maxlength="228" />
                <button class="msg-compose__send" type="button" disabled>
                    <span class="msg-compose__send-label">Send</span>
                    <span class="msg-compose__send-arrow" aria-hidden="true">→</span>
                </button>
            </div>
        `;

        this._headerName = this._container.querySelector('.msg-chat__name');
        this._headerSubtitle = this._container.querySelector('.msg-chat__subtitle');
        this._headerBadge = this._container.querySelector('.msg-chat__protocol-badge');
        this._connectionBadge = this._container.querySelector('.msg-chat__connection-badge');
        this._headerAvatar = this._container.querySelector('.msg-chat__avatar');
        this._messagesEl = this._container.querySelector('.msg-chat__messages');
        this._input = this._container.querySelector('.msg-compose__input');
        this._sendBtn = this._container.querySelector('.msg-compose__send');
        this._attachBtn = this._container.querySelector('.msg-compose__attach');
        this._fileInput = this._container.querySelector('.msg-compose__file');
        this._attachmentChip = this._container.querySelector('.msg-compose-attachment');
        this._attachmentNameEl = this._container.querySelector('.msg-compose-attachment__name');
        this._pendingImageFile = null;

        this._renderEmptyState();
        this._setupPaths();

        this._attachBtn.addEventListener('click', () => this._fileInput.click());
        this._fileInput.addEventListener('change', () => this._onFilePicked());
        this._attachmentChip.querySelector('.msg-compose-attachment__remove')
            .addEventListener('click', () => this._clearAttachment());

        this._sendBtn.addEventListener('click', () => this._handleSend());
        this._input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._handleSend();
            }
        });

        this._messagesEl.addEventListener('scroll', () => {
            if (this._messagesEl.scrollTop === 0 && !this._allLoaded) {
                this._loadOlderMessages();
            }
        });

        this._headerName.addEventListener('click', () => {
            if (!this._conversation) return;
            const isChannel = (this._conversation.node_id || '').startsWith('broadcast:');
            if (isChannel) return;
            this._openNodeInfo(this._conversation.node_id);
        });

        this._messagesEl.addEventListener('click', (e) => {
            const senderEl = e.target.closest('.msg-bubble__sender[data-node-id], .msg-bubble__sender[data-lm-name]');
            if (senderEl) {
                if (senderEl.dataset.nodeId) this._openNodeInfo(senderEl.dataset.nodeId);
                else this._openLocalMeshMemberByName(senderEl.dataset.lmName);
                return;
            }
            const attachmentEl = e.target.closest('[data-attachment-open]');
            if (attachmentEl) {
                window.open(attachmentEl.dataset.attachmentOpen, '_blank', 'noopener');
            }
        });
    }

    /** The generic node drawer (window.nodeDrawer) only knows GET /api/nodes/
     * <id> -- Meshtastic/MeshCore's own nodes table. Reticulum peers aren't
     * in it either (they have their own ReticulumPeerRepository), but
     * nothing here has routed a Reticulum conversation's header click
     * through a protocol-specific drawer yet -- that's a pre-existing gap,
     * not something this LocalMesh branch is trying to fully solve. What
     * *is* new: LocalMesh member ids ("localmesh:<member>") are even less
     * likely to coincidentally resolve through that table, and the
     * LocalMesh plugin already ships its own member drawer (same
     * node_drawer.css chrome, GET /api/localmesh/members as the data
     * source) -- so route those through it instead of a drawer that can
     * never find them. */
    async _openNodeInfo(nodeId) {
        const lmMember = /^localmesh:(\d+)$/.exec(nodeId || '');
        if (lmMember) {
            if (!window.LocalMeshMemberDrawer) return;   // plugin not enabled -- nothing to open
            const member = parseInt(lmMember[1], 10);
            try {
                const r = await fetch('/api/localmesh/members', { credentials: 'same-origin' });
                const members = r.ok ? await r.json() : [];
                const m = members.find((x) => x.member === member);
                if (m) this._openLocalMeshDrawer(m);
            } catch (_) {}
            return;
        }
        if (window.nodeDrawer) window.nodeDrawer.open({ node_id: nodeId });
    }

    _openLocalMeshDrawer(m) {
        if (!this._lmDrawer) this._lmDrawer = new window.LocalMeshMemberDrawer();
        const onMessage = (window.LocalMeshPanel && !m.blocked)
            ? (mem) => window.LocalMeshPanel.composeMessageTo(mem, m.name)
            : undefined;
        this._lmDrawer.open(m, onMessage ? { onMessage } : {});
    }

    /** Older LocalMesh channel messages only know the sender's name (or bare member number). */
    async _openLocalMeshMemberByName(name) {
        if (!window.LocalMeshMemberDrawer || !name) return;
        try {
            const r = await fetch('/api/localmesh/members', { credentials: 'same-origin' });
            const members = r.ok ? await r.json() : [];
            const m = /^\d+$/.test(name)
                ? members.find((x) => x.member === parseInt(name, 10))
                : members.find((x) => x.name === name);
            if (m) this._openLocalMeshDrawer(m);
        } catch (_) {}
    }

    // -- Heard-paths popover (upstream a451d1e2): which repeaters passed a
    //    sent MeshCore message on, from GET /api/messages/{id}/heard-paths.

    _setupPaths() {
        this._pathRequest = 0;
        const trigger = e => e.target.closest?.('.msg-heard');
        this._messagesEl.addEventListener('pointerover', e => {
            const button = trigger(e);
            if (e.pointerType === 'mouse' && button && button !== this._pathDismissed) {
                clearTimeout(this._pathCloseTimer);
                if (this._pathAnchor !== button) this._openPaths(button);
            }
        });
        this._messagesEl.addEventListener('pointerout', e => {
            const button = trigger(e);
            if (button && !button.contains(e.relatedTarget)) {
                if (this._pathDismissed === button) this._pathDismissed = null;
                this._schedulePathClose();
            }
        });
        this._messagesEl.addEventListener('focusin', e => {
            const button = trigger(e);
            if (button) this._openPaths(button);
        });
        this._messagesEl.addEventListener('focusout', e => {
            if (trigger(e) && !this._pathPanel?.contains(e.relatedTarget)) this._schedulePathClose();
        });
        this._messagesEl.addEventListener('keydown', e => {
            if (trigger(e) && this._pathPanel && e.key === 'Tab' && !e.shiftKey) {
                e.preventDefault();
                this._pathPanel.querySelector('button').focus();
            }
        });
        this._messagesEl.addEventListener('click', e => {
            const button = trigger(e);
            if (!button) return;
            if (this._pathAnchor === button && this._pathPinned) this._closePaths();
            else { this._pathPinned = true; this._openPaths(button); }
        });
        document.addEventListener('pointerdown', e => {
            if (!e.target.closest?.('.msg-heard, .msg-paths')) this._closePaths();
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && this._pathPanel) {
                const anchor = this._pathAnchor;
                this._closePaths();
                // Avoid reopening through focusin when restoring focus.
                if (anchor && document.activeElement !== anchor) {
                    this._suppressPathFocus = true;
                    anchor.focus();
                    this._suppressPathFocus = false;
                }
            }
        });
        this._messagesEl.addEventListener('scroll', () => this._closePaths());
        window.addEventListener('resize', () => this._closePaths());
    }

    _schedulePathClose() {
        clearTimeout(this._pathCloseTimer);
        this._pathCloseTimer = setTimeout(() => {
            if (!this._pathPinned && !this._pathPanel?.matches(':hover')
                && !this._pathPanel?.contains(document.activeElement)) this._closePaths();
        }, 220);
    }

    _closePaths() {
        clearTimeout(this._pathCloseTimer);
        this._pathRequest = (this._pathRequest || 0) + 1;
        if (this._pathAnchor) this._pathDismissed = this._pathAnchor;
        this._pathAnchor?.setAttribute('aria-expanded', 'false');
        this._pathAnchor?.removeAttribute('aria-controls');
        this._pathPanel?.remove();
        this._pathPanel = null;
        this._pathAnchor = null;
        this._pathPinned = false;
    }

    async _openPaths(button) {
        if (this._suppressPathFocus) return;
        clearTimeout(this._pathCloseTimer);
        if (this._pathAnchor === button) return;
        const pinned = this._pathPinned;
        this._closePaths();
        this._pathPinned = pinned;
        const row = button.closest('[data-msg-id]');
        if (!row) return;
        const id = row.dataset.msgId;
        const msg = this._messages.find(item => String(item.id) === id);
        this._pathAnchor = button;
        button.setAttribute('aria-expanded', 'true');
        button.setAttribute('aria-controls', 'msg-heard-paths');
        const panel = document.createElement('section');
        panel.className = 'msg-paths';
        panel.id = 'msg-heard-paths';
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', 'Heard paths');
        panel.innerHTML = '<header class="msg-paths__header"><strong>Heard paths</strong><button type="button" class="msg-paths__close" aria-label="Close heard paths"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg></button></header><div class="msg-paths__body" aria-live="polite"><p class="msg-paths__empty">Loading saved paths…</p></div><footer>Copies heard by this Meshpoint\'s own radio, not unique repeaters or delivery. Signal received here · names matched locally.</footer>';
        this._pathPanel = panel;
        document.body.appendChild(panel);
        panel.querySelector('.msg-paths__close').addEventListener('click', () => {
            this._closePaths();
            this._suppressPathFocus = true;
            button.focus();
            this._suppressPathFocus = false;
        });
        panel.addEventListener('pointerenter', () => clearTimeout(this._pathCloseTimer));
        panel.addEventListener('pointerleave', () => this._schedulePathClose());
        panel.addEventListener('focusout', e => {
            if (!panel.contains(e.relatedTarget) && e.relatedTarget !== button) this._closePaths();
        });
        this._positionPaths();
        const request = this._pathRequest;
        try {
            if (!msg?.packet_id) throw new Error('Message still saving');
            const response = await fetch(`/api/messages/${encodeURIComponent(id)}/heard-paths`);
            if (!response.ok) throw new Error('Unavailable');
            const data = await response.json();
            if (this._pathRequest !== request || !button.isConnected) return;
            panel.querySelector('.msg-paths__body').innerHTML = this._pathsHtml(data);
        } catch (_) {
            if (this._pathRequest !== request) return;
            panel.querySelector('.msg-paths__body').innerHTML = '<p class="msg-paths__empty">Paths unavailable. Close and reopen to retry.</p>';
        }
        if (this._pathRequest === request) this._positionPaths();
    }

    _positionPaths() {
        if (!this._pathPanel || !this._pathAnchor) return;
        const a = this._pathAnchor.getBoundingClientRect();
        const panel = this._pathPanel;
        const width = panel.offsetWidth;
        const height = panel.offsetHeight;
        panel.style.left = Math.max(12, Math.min(a.right - width, window.innerWidth - width - 12)) + 'px';
        const above = a.top - height - 8;
        panel.style.top = Math.max(12, Math.min(above >= 12 ? above : a.bottom + 8,
            window.innerHeight - height - 12)) + 'px';
    }

    _pathsHtml(data) {
        const observations = Array.isArray(data.observations) ? data.observations : [];
        if (!observations.length) return `<p class="msg-paths__empty">${data.recorded
            ? 'No repeated paths heard yet.' : 'Path details weren’t recorded for this message.'}</p>`;
        const metric = (value, unit) => Number.isFinite(value) ? `${this._esc(String(value))} <small>${unit}</small>` : 'Unavailable';
        const rows = observations.map(observation => {
            const hops = (observation.hops || []).map(hop => {
                const label = hop.name || (hop.ambiguous ? 'Ambiguous repeater' : 'Unknown repeater');
                return `<li><span class="msg-paths__node">${this._esc(label)}</span><code>${this._esc(hop.id)}</code></li>`;
            }).join('');
            return `<li class="msg-paths__copy"><ol class="msg-paths__route" aria-label="Reported repeater path">${hops}<li class="msg-paths__here"><span class="msg-paths__node">Your radio</span></li></ol><dl class="msg-paths__signal"><div><dt>RSSI</dt><dd>${metric(observation.rssi, 'dBm')}</dd></div><div><dt>SNR</dt><dd>${metric(observation.snr, 'dB')}</dd></div></dl></li>`;
        }).join('');
        const count = Number.isInteger(data.count) ? data.count : observations.length;
        return `<p class="msg-paths__summary">${count} heard ${count === 1 ? 'copy' : 'copies'}${observations.length < count ? ' · first ' + observations.length + ' saved' : ''}</p><ul class="msg-paths__copies">${rows}</ul>`;
    }

    async _loadOlderMessages() {
        if (!this._conversation || this._loading || this._allLoaded) return;
        if (this._messages.length === 0) return;
        this._loading = true;

        try {
            const oldest = this._messages[0];
            const nodeId = encodeURIComponent(this._conversation.node_id);
            const res = await fetch(
                `/api/messages/conversation/${nodeId}?limit=50&before=${oldest.timestamp}`
            );
            const older = await res.json();
            if (older.length === 0) {
                this._allLoaded = true;
                return;
            }

            const scrollBefore = this._messagesEl.scrollHeight;
            const frag = document.createDocumentFragment();
            let prevKey = null;
            older.forEach(msg => {
                const key = msg.timestamp ? this._dayKey(msg.timestamp) : null;
                if (key && key !== prevKey) {
                    const sep = this._buildDaySeparatorEl(msg.timestamp);
                    frag.appendChild(sep);
                    prevKey = key;
                }
                frag.appendChild(this._buildBubbleEl(msg));
            });

            const firstExistingKey = this._messages[0]?.timestamp
                ? this._dayKey(this._messages[0].timestamp) : null;
            if (prevKey && prevKey === firstExistingKey) {
                const existingSep = this._messagesEl.querySelector('.msg-day-separator');
                if (existingSep) existingSep.remove();
            }

            this._messagesEl.prepend(frag);
            this._messages = [...older, ...this._messages];

            const scrollAfter = this._messagesEl.scrollHeight;
            this._messagesEl.scrollTop = scrollAfter - scrollBefore;
        } catch (e) {
            console.error('Failed to load older messages:', e);
        } finally {
            this._loading = false;
        }
    }

    _buildBubbleEl(msg) {
        msg = this._normalizeLocalMeshChannelMessage(msg);
        const bubble = document.createElement('div');
        bubble.className = `msg-bubble msg-bubble--${msg.direction}`;
        bubble.dataset.msgId = msg.id;
        if (msg.packet_id) bubble.dataset.pktId = msg.packet_id;
        const senderHtml = this._buildSenderHtml(msg);
        const attachmentHtml = this._buildAttachmentHtml(msg);

        bubble.innerHTML = `
            ${senderHtml}
            ${attachmentHtml}
            <div class="msg-bubble__text">${this._esc(msg.text)}</div>
            <div class="msg-bubble__meta">${this._buildMetaHtml(msg, false)}</div>
        `;
        return bubble;
    }

    updateBubbleSignal(packetId, rssi, snr, rxCount) {
        const bubble = this._messagesEl.querySelector(`[data-pkt-id="${packetId}"]`);
        if (!bubble) return;

        const meta = bubble.querySelector('.msg-bubble__meta');
        if (!meta) return;

        const sig = meta.querySelector('.msg-signal');
        if (sig) sig.remove();
        const rx = meta.querySelector('.msg-rx-count');
        if (rx) rx.remove();

        const fakeMsg = { direction: 'received', rssi, snr, rx_count: rxCount };
        meta.insertAdjacentHTML('beforeend', this._buildSignalHtml(fakeMsg));
    }

    _buildSignalHtml(msg) {
        if (msg.direction === 'sent' || msg.rssi == null) return '';

        const rssi = msg.rssi;
        const snr = msg.snr;
        const level = rssi > -80 ? 5 : rssi > -95 ? 4 : rssi > -110 ? 3 : rssi > -125 ? 2 : 1;
        const cls = level >= 4 ? 'excellent' : level === 3 ? 'good' : level === 2 ? 'fair' : 'poor';

        let bars = '';
        for (let i = 1; i <= 5; i++) {
            const active = i <= level ? 'active' : '';
            bars += `<span class="sig-bar sig-bar--h${i} ${active}"></span>`;
        }

        const snrStr = snr != null ? ` · ${snr.toFixed(1)} dB` : '';
        const rxStr = (msg.rx_count || 1) > 1
            ? `<span class="msg-rx-count" title="Received via ${msg.rx_count} RF paths">×${msg.rx_count}</span>`
            : '';
        return `<span class="msg-signal msg-signal--${cls}">${bars}<span class="msg-signal__val">${rssi.toFixed(1)}${snrStr}</span></span>${rxStr}`;
    }

    _insertDaySeparator(ts) {
        if (!ts) return;
        const key = this._dayKey(ts);
        if (key === this._lastDayKey) return;
        this._lastDayKey = key;

        const d = new Date(ts);
        const now = new Date();
        const sameDay = d.getFullYear() === now.getFullYear()
            && d.getMonth() === now.getMonth()
            && d.getDate() === now.getDate();

        let label;
        if (sameDay) {
            label = 'Today';
        } else {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const sameYesterday = d.getFullYear() === yesterday.getFullYear()
                && d.getMonth() === yesterday.getMonth()
                && d.getDate() === yesterday.getDate();
            if (sameYesterday) {
                label = 'Yesterday';
            } else {
                label = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
            }
        }

        const div = document.createElement('div');
        div.className = 'msg-day-separator';
        div.textContent = label;
        this._messagesEl.appendChild(div);
    }

    _buildDaySeparatorEl(ts) {
        const d = new Date(ts);
        const now = new Date();
        const sameDay = d.getFullYear() === now.getFullYear()
            && d.getMonth() === now.getMonth()
            && d.getDate() === now.getDate();

        let label;
        if (sameDay) {
            label = 'Today';
        } else {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const sameYesterday = d.getFullYear() === yesterday.getFullYear()
                && d.getMonth() === yesterday.getMonth()
                && d.getDate() === yesterday.getDate();
            label = sameYesterday
                ? 'Yesterday'
                : d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
        }

        const div = document.createElement('div');
        div.className = 'msg-day-separator';
        div.textContent = label;
        return div;
    }

    _dayKey(ts) {
        const d = new Date(ts);
        return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    }

    _receivedSenderLabel(msg) {
        let name = (msg.node_name || '').trim();
        if (name.startsWith('broadcast:')) name = '';
        if (name.toLowerCase() === 'broadcast') name = '';
        if (!name && msg.source_id) {
            const sid = String(msg.source_id);
            if (sid && sid !== 'ffffffff' && !sid.startsWith('broadcast')) {
                name = sid.length > 6 ? `!${sid.slice(-4)}` : sid;
            }
        }
        if (!name) {
            const nid = msg.node_id || '';
            if (!nid.startsWith('broadcast:')) name = nid;
        }
        return name;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}
