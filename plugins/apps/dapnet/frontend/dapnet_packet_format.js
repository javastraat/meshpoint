/**
 * Registers DAPNET's packet-display quirks with core's
 * frontend/js/protocol_format_registry.js, in place of the
 * `protocol === 'dapnet'` special cases that used to live directly in
 * simple_packet_feed.js and packet_detail_modal.js.
 */
window.registerProtocolFormat('dapnet', {
    // DAPNET has no hex node-ID space -- source/destination are the
    // literal string "broadcast" or a decimal capcode, so show them
    // verbatim rather than running Meshtastic's "!" + last-4-hex-char
    // shortening over them (that mangled e.g. capcode 2041152 into
    // "!1152" and "broadcast" into "!cast").
    formatId(id, esc) {
        return `<span class="td-node-short">${esc(String(id))}</span>`;
    },

    // /api/dapnet/packets (and dapnet_panel.js's own live-WS mirror of
    // that shape) return capcode/function/text as top-level fields
    // rather than the destination_id + nested decoded_payload object
    // every other protocol's packet rows already have.
    normalize(packet) {
        if (packet.decoded_payload) return null;
        return {
            ...packet,
            destination_id: packet.capcode,
            decoded_payload: {
                capcode: packet.capcode, function: packet.function, text: packet.text,
            },
        };
    },

    // POCSAG pages are broadcast in the clear -- there's no key/decrypt
    // step to report on at all.
    decryptedByDefault: true,

    // packet_type values carry a "dapnet_" prefix (dapnet_alpha,
    // dapnet_numeric, ...) to stay unambiguous next to Meshtastic/
    // MeshCore's own type constants in the shared `packets` table --
    // strip it back off for display.
    typePrefix: 'dapnet_',

    summaryFor(type, payload) {
        switch (type) {
            case 'dapnet_alpha':
            case 'dapnet_numeric':
                return payload.text || '';
            case 'dapnet_tone':
                return 'Tone-only page (no text)';
            case 'dapnet_activation':
                return 'Activation page (no text)';
            default:
                return undefined;
        }
    },
});
