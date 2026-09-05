/**
 * Small lookup so a plugin-owned protocol (see src/api/protocol_registry.py
 * on the backend side) can override packet-display formatting at a handful
 * of real behavior branches in core's shared packet UI, without those files
 * growing a permanent `protocol === '<plugin protocol>'` special case.
 *
 * Scoped narrowly to genuine behavior differences (ID shape, decrypted-by-
 * default assumption, packet-type prefix stripping, payload summary text)
 * -- NOT a general "plugin owns some UI" seam. Cosmetic-only per-protocol
 * differences (colors, map icons) already degrade gracefully with static
 * fallback data in chart_theme.js/node_map.js and don't need this.
 *
 * A spec is a plain object, all fields optional:
 *   formatId(id, esc) -> html string
 *       simple_packet_feed.js's _fmtId -- how to render a source/
 *       destination id that isn't a Meshtastic-style hex node id.
 *   normalize(packet) -> reshaped packet, or null/undefined to decline
 *       packet_detail_modal.js's _normalize -- reshape a flattened API
 *       response row into the common `decoded_payload` object shape.
 *   decryptedByDefault: bool
 *       packet_detail_modal.js's _payloadRows -- true for protocols with
 *       no encryption/key-matching step at all (nothing to report on).
 *   typePrefix: string
 *       packet_detail_modal.js's _typeLabel -- packet_type values prefixed
 *       to stay unambiguous in the shared `packets` table get the prefix
 *       stripped back off for display.
 *   summaryFor(packet_type, decoded_payload) -> string, or undefined to
 *       decline (falls through to the built-in switch)
 *       packet_detail_modal.js's _payloadSummary one-line content preview.
 */
(function () {
    const _formats = new Map();

    function registerProtocolFormat(protocol, spec) {
        _formats.set(protocol, spec || {});
    }

    function getProtocolFormat(protocol) {
        return _formats.get(protocol) || null;
    }

    window.registerProtocolFormat = registerProtocolFormat;
    window.getProtocolFormat = getProtocolFormat;
})();
