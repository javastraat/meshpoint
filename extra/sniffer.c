/*
 * Passive LoRa sniffer — Sencap M1 / SX1303
 * Captures: Meshtastic EU_868 LongFast + general EU868 scan
 *
 * SX1302/1303 HAL architecture:
 *   8 multi-SF channels (0-7) : BW125 fixed, SF5-SF12 via global bitmask
 *   1 LoRa service channel (8): configurable BW {125/250/500} + single SF
 *
 * Note: MeshCore uses BW62.5, which is physically unsupported by the SX1302/1303.
 *       MeshCore sniffing requires an SX1262-based companion radio instead.
 *
 * Channel plan:
 *   ch0–ch7 : EU868 scan BW125 multi-SF (SF5–SF12)
 *   ch8     : 869.525 MHz BW250 SF11 [MESHTASTIC]
 *
 * Build: make
 * Run:   bash reset_m1.sh && sudo ./sniffer
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>

#include <openssl/evp.h>

#include "loragw_hal.h"
#include "loragw_aux.h"
#include "loragw_reg.h"

/* ── config ────────────────────────────────────────────────────────────── */

#define SPI_DEV             "/dev/spidev0.0"
#define NODE_DB_FILE        "nodes.csv"   /* persists NodeInfo across restarts */
#define KEYS_FILE           "keys.txt"    /* extra channel PSKs, one base64 per line */

/* RF chain centres */
#define RF0_FREQ_HZ         868300000U  /* 868.3 MHz — lower EU868, centred on standard channels */
#define RF1_FREQ_HZ         869525000U  /* 869.525 MHz — centred on Meshtastic */

/* Meshtastic EU_868 LongFast — LoRa service channel (index 8) */
#define MESHTASTIC_FREQ_HZ  RF1_FREQ_HZ
#define MESHTASTIC_RF_CHAIN 1
#define MESHTASTIC_IF_HZ    0           /* RF1 centre = 869.525 MHz */
#define MESHTASTIC_BW       BW_250KHZ
#define MESHTASTIC_SF       DR_LORA_SF11

/*
 * Multi-SF channel table (channels 0–7):
 *   Bandwidth is fixed at BW125 by the hardware.
 *   SF range (SF5–SF12) is set globally via lgw_demod_setconf().
 *   Per-channel config sets rf_chain and freq_offset only.
 */
typedef struct {
    uint8_t     rf_chain;
    int32_t     freq_offset;   /* Hz offset from RF chain centre */
    const char *label;
} multisf_chan_t;

static const multisf_chan_t MULTISF_CHANS[LGW_MULTI_NB] = {
    /* RF0 @ 868.3 MHz — lower EU868 */
    { 0, -400000, "867.9 MHz BW125 multi-SF — EU868 optional, sub-band L (1%, 25mW)" },
    { 0, -200000, "868.1 MHz BW125 multi-SF — EU868 mandatory ch1 (LoRaWAN)" },
    { 0,       0, "868.3 MHz BW125 multi-SF — EU868 mandatory ch2 (LoRaWAN)" },
    { 0,  200000, "868.5 MHz BW125 multi-SF — EU868 mandatory ch3 (LoRaWAN)" },
    /* RF1 @ 869.525 MHz — upper EU868 */
    { 1, -300000, "869.225 MHz BW125 multi-SF — EU868 sub-band N edge (0.1%, 25mW)" },
    { 1, -100000, "869.425 MHz BW125 multi-SF — EU868 sub-band P (10%, 500mW)" },
    { 1,  100000, "869.625 MHz BW125 multi-SF — EU868 sub-band P/Q edge" },
    { 1,  300000, "869.825 MHz BW125 multi-SF — EU868 sub-band Q (1%, 25mW)" },
    /* ch8 (LoRa service channel, RF1) configured separately: 869.525 MHz BW250 SF11 [MESHTASTIC] */
    /* ch9 (FSK channel, RF0 or RF1)  disabled — not used */
};

/* ── globals ───────────────────────────────────────────────────────────── */

static volatile bool keep_running = true;
static uint64_t pkt_count = 0;

static void sig_handler(int s) { (void)s; keep_running = false; }

/* ── helpers ───────────────────────────────────────────────────────────── */

static const char *sf_str(uint32_t dr) {
    switch (dr) {
        case DR_LORA_SF5:  return "SF5";
        case DR_LORA_SF6:  return "SF6";
        case DR_LORA_SF7:  return "SF7";
        case DR_LORA_SF8:  return "SF8";
        case DR_LORA_SF9:  return "SF9";
        case DR_LORA_SF10: return "SF10";
        case DR_LORA_SF11: return "SF11";
        case DR_LORA_SF12: return "SF12";
        default:           return "SFx";
    }
}

static bool is_meshtastic(uint32_t freq) {
    return freq >= MESHTASTIC_FREQ_HZ - 2000 && freq <= MESHTASTIC_FREQ_HZ + 2000;
}

static void print_packet(const uint8_t *buf, uint16_t len,
                         uint32_t freq, uint32_t dr,
                         float rssi, float snr) {
    time_t now = time(NULL);
    struct tm *t = localtime(&now);

    printf("[%02d:%02d:%02d] %u Hz %s  RSSI=%+.1f SNR=%+.1f  len=%u%s\n",
           t->tm_hour, t->tm_min, t->tm_sec,
           freq, sf_str(dr), rssi, snr, len,
           is_meshtastic(freq) ? "  ← MESHTASTIC" : "");

    printf("          raw: ");
    for (uint16_t i = 0; i < len; i++) {
        printf("%02x ", buf[i]);
        if ((i + 1) % 16 == 0 && i + 1 < len)
            printf("\n               ");
    }
    printf("\n\n");
}

/* ── Meshtastic decrypt + decode ─────────────────────────────────────────── */

/* ── node database ─────────────────────────────────────────────────────── */

#define NODE_DB_MAX  1024

typedef struct {
    uint32_t id;
    char     long_name[64];
    char     short_name[8];
    char     hw_model[24];
    uint8_t  pkey[32];       /* X25519 public key from NodeInfo field 8 */
    bool     has_pkey;
    time_t   last_seen;
} node_rec_t;

static node_rec_t node_db[NODE_DB_MAX];
static int        node_db_n = 0;

static node_rec_t *node_find(uint32_t id) {
    for (int i = 0; i < node_db_n; i++)
        if (node_db[i].id == id) return &node_db[i];
    return NULL;
}

static node_rec_t *node_get_or_add(uint32_t id) {
    node_rec_t *r = node_find(id);
    if (r) return r;
    if (node_db_n >= NODE_DB_MAX) return NULL;
    r = &node_db[node_db_n++];
    memset(r, 0, sizeof *r);
    r->id = id;
    return r;
}

static void node_db_save(void) {
    FILE *f = fopen(NODE_DB_FILE, "w");
    if (!f) { perror("fopen " NODE_DB_FILE); return; }
    fprintf(f, "# node_id|long_name|short_name|hw_model|public_key_hex|last_seen\n");
    for (int i = 0; i < node_db_n; i++) {
        node_rec_t *r = &node_db[i];
        fprintf(f, "%08x|%s|%s|%s|", r->id, r->long_name, r->short_name, r->hw_model);
        if (r->has_pkey)
            for (int j = 0; j < 32; j++) fprintf(f, "%02x", r->pkey[j]);
        else
            fprintf(f, "-");
        fprintf(f, "|%ld\n", (long)r->last_seen);
    }
    fclose(f);
}

static void node_db_load(void) {
    FILE *f = fopen(NODE_DB_FILE, "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        char id_s[16]="", ln[64]="", sn[8]="", hw[24]="", pk[65]="", ts[24]="";
        int n = sscanf(line, "%15[^|]|%63[^|]|%7[^|]|%23[^|]|%64[^|]|%23[^\n]",
                       id_s, ln, sn, hw, pk, ts);
        if (n < 1) continue;
        uint32_t id = (uint32_t)strtoul(id_s, NULL, 16);
        node_rec_t *r = node_get_or_add(id);
        if (!r) break;
        if (n >= 2) strncpy(r->long_name,  ln, sizeof r->long_name  - 1);
        if (n >= 3) strncpy(r->short_name, sn, sizeof r->short_name - 1);
        if (n >= 4) strncpy(r->hw_model,   hw, sizeof r->hw_model   - 1);
        if (n >= 5 && strlen(pk) == 64) {
            for (int j = 0; j < 32; j++) {
                unsigned v = 0; sscanf(pk + 2*j, "%02x", &v);
                r->pkey[j] = (uint8_t)v;
            }
            r->has_pkey = true;
        }
        if (n >= 6) r->last_seen = (time_t)atol(ts);
    }
    fclose(f);
    if (node_db_n > 0)
        printf("Node DB: loaded %d nodes from %s\n", node_db_n, NODE_DB_FILE);
}

static void node_upsert(uint32_t id,
                        const char *long_name, const char *short_name,
                        const char *hw_model, const uint8_t *pkey) {
    node_rec_t *r = node_get_or_add(id);
    if (!r) return;
    if (long_name[0])  strncpy(r->long_name,  long_name,  sizeof r->long_name  - 1);
    if (short_name[0]) strncpy(r->short_name, short_name, sizeof r->short_name - 1);
    if (hw_model[0])   strncpy(r->hw_model,   hw_model,   sizeof r->hw_model   - 1);
    if (pkey) { memcpy(r->pkey, pkey, 32); r->has_pkey = true; }
    r->last_seen = time(NULL);
    node_db_save();
}

/* ── channel PSK list ──────────────────────────────────────────────────── */

#define MAX_KEYS 17   /* default key + up to 16 from keys.txt */

static uint8_t mesh_keys[MAX_KEYS][32];
static int     mesh_key_len[MAX_KEYS];
static int     mesh_key_count = 0;

/* Expand Meshtastic key from raw bytes (mirrors firmware Channels::getKey).
   Returns actual key length: 16 for AES-128, 32 for AES-256. */
static int expand_key(const uint8_t *raw, int rawlen, uint8_t out[32]) {
    static const uint8_t DEFAULT_PSK[16] = {
        0xD4, 0xF1, 0xBB, 0x3A, 0x20, 0x29, 0x07, 0x59,
        0xF0, 0xBC, 0xFF, 0xAB, 0xCF, 0x4E, 0x69, 0x01,
    };
    if (rawlen == 0)  { memset(out, 0, 16); return 16; }
    if (rawlen == 16) { memcpy(out, raw, 16); return 16; }
    if (rawlen == 32) { memcpy(out, raw, 32); return 32; }
    if (rawlen == 1) {
        memcpy(out, DEFAULT_PSK, 16);
        out[15] = (uint8_t)((DEFAULT_PSK[15] + raw[0] - 1) & 0xFF);
        return 16;
    }
    memset(out, 0, 16);
    memcpy(out, raw, rawlen < 16 ? rawlen : 16);
    return 16;
}

/* Decode base64 string to bytes; returns decoded length or -1 */
static int b64_decode(const char *in, uint8_t *out, int out_max) {
    int ilen = (int)strlen(in);
    if (ilen == 0 || ilen % 4 != 0) return -1;
    int olen = EVP_DecodeBlock(out, (const unsigned char *)in, ilen);
    if (olen < 0) return -1;
    if (ilen >= 2 && in[ilen-1] == '=') olen--;
    if (ilen >= 2 && in[ilen-2] == '=') olen--;
    return (olen <= out_max) ? olen : -1;
}

static void keys_load(void) {
    /* default public channel key (index 1 / "AQ==") is always first */
    static const uint8_t DEF_RAW[1] = { 0x01 };
    mesh_key_len[0] = expand_key(DEF_RAW, 1, mesh_keys[0]);
    mesh_key_count = 1;

    FILE *f = fopen(KEYS_FILE, "r");
    if (!f) return;
    char line[128];
    while (fgets(line, sizeof line, f) && mesh_key_count < MAX_KEYS) {
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '#' || line[0] == '\0') continue;
        uint8_t raw[32]; int rlen = b64_decode(line, raw, 32);
        if (rlen <= 0) { fprintf(stderr, "keys.txt: bad base64 '%s'\n", line); continue; }
        mesh_key_len[mesh_key_count] = expand_key(raw, rlen, mesh_keys[mesh_key_count]);
        mesh_key_count++;
    }
    fclose(f);
    if (mesh_key_count > 1)
        printf("Keys:    loaded %d channel PSKs (%d extra from %s)\n",
               mesh_key_count, mesh_key_count - 1, KEYS_FILE);
}


#define MESH_HDR 16   /* bytes: dest(4) src(4) id(4) flags(1) ch(1) nhop(1) relay(1) */

typedef struct {
    uint32_t dest, src, id;
    uint8_t  hop_limit, hop_start, channel_hash, relay_node;
    bool     want_ack, via_mqtt;
} mesh_hdr_t;

static void parse_mesh_hdr(const uint8_t *b, mesh_hdr_t *h) {
    memcpy(&h->dest, b,      4);
    memcpy(&h->src,  b + 4,  4);
    memcpy(&h->id,   b + 8,  4);
    uint8_t f    = b[12];
    h->hop_limit    = f & 0x07;
    h->want_ack     = (f >> 3) & 1;
    h->via_mqtt     = (f >> 4) & 1;
    h->hop_start    = (f >> 5) & 0x07;
    h->channel_hash = b[13];
    h->relay_node   = b[15];
}

static int aes_ctr(const uint8_t *key, int key_len,
                   uint32_t pkt_id, uint32_t src_id,
                   const uint8_t *in, int len, uint8_t *out) {
    /* nonce: pkt_id(4 LE) + 0x00(4) + src_id(4 LE) + 0x00(4) */
    uint8_t nonce[16] = {0};
    memcpy(nonce,     &pkt_id, 4);
    memcpy(nonce + 8, &src_id, 4);
    const EVP_CIPHER *cipher = (key_len == 32) ? EVP_aes_256_ctr() : EVP_aes_128_ctr();
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return -1;
    int n1 = 0, n2 = 0;
    int ok = EVP_EncryptInit_ex(ctx, cipher, NULL, key, nonce)
          && EVP_EncryptUpdate(ctx, out, &n1, in, len)
          && EVP_EncryptFinal_ex(ctx, out + n1, &n2);
    EVP_CIPHER_CTX_free(ctx);
    return ok ? n1 + n2 : -1;
}

/* ── protobuf primitives ──────────────────────────────────────────────────── */

static uint64_t pb_varint(const uint8_t *b, int len, int *pos) {
    uint64_t v = 0; int sh = 0;
    while (*pos < len) {
        uint8_t c = b[(*pos)++];
        v |= (uint64_t)(c & 0x7F) << sh;
        if (!(c & 0x80)) break;
        sh += 7;
    }
    return v;
}

/* sint32 zigzag: used for Position.latitude_i / longitude_i */
static int32_t pb_zigzag(uint64_t n) {
    return (int32_t)((uint32_t)(n >> 1) ^ (uint32_t)(-(int32_t)(n & 1)));
}

/* IEEE-754 float from 4 LE bytes at pos (wire type 5) */
static float pb_float(const uint8_t *b, int pos) {
    uint32_t u; float f;
    memcpy(&u, b + pos, 4);
    memcpy(&f, &u,      4);
    return f;
}

/* skip one field value; returns false on malformed input */
static bool pb_skip(const uint8_t *b, int len, int *pos, uint32_t wt) {
    switch (wt) {
        case 0: pb_varint(b, len, pos); return true;
        case 1: if (*pos + 8 > len) return false; *pos += 8; return true;
        case 5: if (*pos + 4 > len) return false; *pos += 4; return true;
        case 2: {
            int sp = *pos;
            uint64_t sz = pb_varint(b, len, pos);
            if (*pos == sp || *pos + (int)sz > len) return false;
            *pos += (int)sz; return true;
        }
        default: return false;
    }
}

/* ── name tables ──────────────────────────────────────────────────────────── */

static const char *portnum_str(uint32_t p) {
    switch (p) {
        case   1: return "TEXT_MESSAGE";
        case   2: return "REMOTE_HARDWARE";
        case   3: return "POSITION";
        case   4: return "NODEINFO";
        case   5: return "ROUTING";
        case   6: return "ADMIN";
        case   8: return "WAYPOINT";
        case  10: return "DETECTION_SENSOR";
        case  34: return "PAXCOUNTER";
        case  64: return "SERIAL";
        case  65: return "STORE_FORWARD";
        case  66: return "RANGE_TEST";
        case  67: return "TELEMETRY";
        case  68: return "ZPS";
        case  69: return "SIMULATOR";
        case  70: return "TRACEROUTE";
        case  71: return "NEIGHBORINFO";
        case  72: return "TEXT_COMPRESSED";
        case  73: return "MAP_REPORT";
        case  74: return "AUDIO";
        case  75: return "PKI_ENCRYPTED_DM";
        default:  return NULL;   /* unknown → likely wrong key */
    }
}

static const char *hw_model_str(uint32_t m) {
    switch (m) {
        case  4: return "T-Beam";
        case  9: return "RAK4631";
        case 10: return "Heltec-V2.1";
        case 11: return "Heltec-V1";
        case 43: return "Heltec-V3";
        case 44: return "Heltec-WSL-V3";
        case 47: return "RP2040";
        case 48: return "Heltec-Tracker";
        case 49: return "Heltec-Paper";
        case 50: return "T-Deck";
        case 51: return "T-Watch-S3";
        case 65: return "Heltec-Capsule-V3";
        case 70: return "SenseCAP-Indicator";
        case 71: return "Tracker-T1000-E";
        case 74: return "RM900-Bandit";
        default: return NULL;
    }
}

static const char *role_str(uint32_t r) {
    switch (r) {
        case 0: return "CLIENT";
        case 1: return "CLIENT_MUTE";
        case 2: return "ROUTER";
        case 3: return "ROUTER_CLIENT";
        case 4: return "REPEATER";
        case 5: return "TRACKER";
        case 6: return "SENSOR";
        case 7: return "TAK";
        default: return "OTHER";
    }
}

static const char *routing_error_str(uint32_t e) {
    switch (e) {
        case 0: return "NONE (ACK)";
        case 1: return "NO_ROUTE";
        case 2: return "GOT_NAK";
        case 3: return "TIMEOUT";
        case 4: return "NO_INTERFACE";
        case 5: return "MAX_RETRANSMIT";
        case 6: return "NO_CHANNEL";
        case 7: return "TOO_LARGE";
        case 8: return "NO_RESPONSE";
        case 9: return "DUTY_CYCLE_LIMIT";
        default: return "UNKNOWN_ERROR";
    }
}

/* ── sub-message decoders ─────────────────────────────────────────────────── */

/* meshtastic.Position: lat/lon sint32 (*1e7, zigzag), alt int32 (metres) */
static void decode_position(const uint8_t *d, int len) {
    int32_t lat = 0, lon = 0, alt = 0;
    bool has_lat = false, has_lon = false, has_alt = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 1) { lat = pb_zigzag(v); has_lat = true; }
            else if (fn == 2) { lon = pb_zigzag(v); has_lon = true; }
            else if (fn == 3) { alt = (int32_t)v;   has_alt = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_lat && has_lon) {
        printf("  lat=%.6f  lon=%.6f", lat / 1e7, lon / 1e7);
        if (has_alt) printf("  alt=%dm", alt);
        printf("\n");
    } else {
        printf("  [no coordinates]\n");
    }
}

/* meshtastic.User (NodeInfo payload): node id, names, hardware model, role, public_key */
static void decode_user(const uint8_t *d, int len, uint32_t src_id) {
    char node_id[16] = {0}, long_name[64] = {0}, short_name[8] = {0};
    uint32_t hw = 0, role = 0;
    bool has_hw = false, has_role = false;
    uint8_t pkey[32]; bool has_pkey = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 1) {
                int n = (int)sz < 15 ? (int)sz : 15;
                memcpy(node_id, d + pos, n); node_id[n] = '\0';
            } else if (fn == 2) {
                int n = (int)sz < 63 ? (int)sz : 63;
                memcpy(long_name, d + pos, n); long_name[n] = '\0';
            } else if (fn == 3) {
                int n = (int)sz < 7 ? (int)sz : 7;
                memcpy(short_name, d + pos, n); short_name[n] = '\0';
            } else if (fn == 8 && sz == 32) {
                memcpy(pkey, d + pos, 32); has_pkey = true;
            }
            pos += (int)sz;
        } else if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 5) { hw   = (uint32_t)v; has_hw   = true; }
            else if (fn == 7) { role = (uint32_t)v; has_role = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }

    /* persist to node DB */
    char hw_str[24] = {0};
    if (has_hw) {
        const char *s = hw_model_str(hw);
        snprintf(hw_str, sizeof hw_str, "%s", s ? s : "");
    }
    node_upsert(src_id, long_name, short_name, hw_str, has_pkey ? pkey : NULL);

    printf("  id=%-12s  name=\"%s\"", node_id[0] ? node_id : "?", long_name);
    if (short_name[0]) printf("  short=\"%s\"", short_name);
    if (has_hw) {
        const char *s = hw_model_str(hw);
        if (s) printf("  hw=%s", s); else printf("  hw=%u", hw);
    }
    if (has_role) printf("  role=%s", role_str(role));
    if (has_pkey) {
        printf("  pkey=");
        for (int i = 0; i < 8; i++) printf("%02x", pkey[i]);
        printf("…");
    }
    printf("\n");
}

/* meshtastic.DeviceMetrics: battery%, voltage, channel/air utilisation, uptime */
static void decode_device_metrics(const uint8_t *d, int len) {
    uint32_t battery = 0, uptime = 0;
    float voltage = 0, chan_util = 0, air_util = 0;
    bool has_bat = false, has_volt = false, has_chan = false,
         has_air = false, has_up   = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 1) { battery = (uint32_t)v; has_bat = true; }
            else if (fn == 5) { uptime  = (uint32_t)v; has_up  = true; }
        } else if (wt == 5 && pos + 4 <= len) {
            float f = pb_float(d, pos); pos += 4;
            if      (fn == 2) { voltage  = f; has_volt = true; }
            else if (fn == 3) { chan_util = f; has_chan = true; }
            else if (fn == 4) { air_util  = f; has_air  = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_bat)  printf("  battery=%u%%", battery);
    if (has_volt) printf("  voltage=%.2fV", voltage);
    if (has_chan) printf("  chan_util=%.1f%%", chan_util);
    if (has_air)  printf("  air_util=%.1f%%", air_util);
    if (has_up)   printf("  uptime=%us", uptime);
    printf("\n");
}

/* meshtastic.EnvironmentMetrics: temperature (°C), humidity (%), pressure (hPa) */
static void decode_env_metrics(const uint8_t *d, int len) {
    float temp = 0, hum = 0, press = 0;
    bool has_temp = false, has_hum = false, has_press = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 5 && pos + 4 <= len) {
            float f = pb_float(d, pos); pos += 4;
            if      (fn == 1) { temp  = f; has_temp  = true; }
            else if (fn == 2) { hum   = f; has_hum   = true; }
            else if (fn == 3) { press = f; has_press = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_temp)  printf("  temp=%.1fC", temp);
    if (has_hum)   printf("  humidity=%.1f%%", hum);
    if (has_press) printf("  pressure=%.1fhPa", press);
    printf("\n");
}

static void decode_local_stats(const uint8_t *d, int len);
static void decode_power_metrics(const uint8_t *d, int len);

/* meshtastic.Telemetry: outer message dispatches to DeviceMetrics or EnvMetrics */
static void decode_telemetry(const uint8_t *d, int len) {
    bool printed = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 2) {
                printf("  [DeviceMetrics]");
                decode_device_metrics(d + pos, (int)sz);
                printed = true;
            } else if (fn == 3) {
                printf("  [EnvMetrics]");
                decode_env_metrics(d + pos, (int)sz);
                printed = true;
            } else if (fn == 4) {
                printf("  [LocalStats]");
                decode_local_stats(d + pos, (int)sz);
                printed = true;
            } else if (fn == 6) {
                printf("  [PowerMetrics]");
                decode_power_metrics(d + pos, (int)sz);
                printed = true;
            }
            pos += (int)sz;
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (!printed) printf("  [telemetry variant not decoded]\n");
}

/* meshtastic.Routing: field 3 is error_reason (0 = ACK / success) */
static void decode_routing(const uint8_t *d, int len) {
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if (fn == 3) {
                printf("  error=%s\n", routing_error_str((uint32_t)v));
                return;
            }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    /* field 3 absent → proto default 0 = NONE */
    printf("  error=NONE (ACK)\n");
}

/* meshtastic.NeighborInfo: field 4 is repeated Neighbor{node_id, snr} */
static void decode_neighborinfo(const uint8_t *d, int len) {
    int count = 0, pos = 0;
    printf("  neighbors:");
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 4) {
                uint32_t nb_id = 0; float snr = 0.0f; bool has_snr = false;
                const uint8_t *nd = d + pos; int nlen = (int)sz, np = 0;
                while (np < nlen) {
                    int nprev = np;
                    uint64_t ntag = pb_varint(nd, nlen, &np);
                    if (np == nprev) break;
                    uint32_t nwt = ntag & 7, nfn = (uint32_t)(ntag >> 3);
                    if (nwt == 0) {
                        uint64_t v = pb_varint(nd, nlen, &np);
                        if (nfn == 1) nb_id = (uint32_t)v;
                    } else if (nwt == 5 && np + 4 <= nlen) {
                        float f = pb_float(nd, np); np += 4;
                        if (nfn == 2) { snr = f; has_snr = true; }
                    } else if (!pb_skip(nd, nlen, &np, nwt)) break;
                }
                if (count < 6) {
                    printf(" %08x", nb_id);
                    if (has_snr) printf("(%.0fdB)", snr);
                }
                count++;
            }
            pos += (int)sz;
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (count > 6) printf(" +%d more", count - 6);
    printf("  [total=%d]\n", count);
}

/* meshtastic.Waypoint: id, name, description, lat_i/lon_i (sint32 ×1e-7), icon */
static void decode_waypoint(const uint8_t *d, int len) {
    uint32_t wid = 0, icon = 0;
    char name[64] = {0}, desc[128] = {0};
    int32_t lat = 0, lon = 0;
    bool has_lat = false, has_lon = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 1) wid  = (uint32_t)v;
            else if (fn == 4) { lat = pb_zigzag(v); has_lat = true; }
            else if (fn == 5) { lon = pb_zigzag(v); has_lon = true; }
            else if (fn == 6) icon = (uint32_t)v;
        } else if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 2) {
                int n = (int)sz < 63 ? (int)sz : 63;
                memcpy(name, d + pos, n); name[n] = '\0';
            } else if (fn == 3) {
                int n = (int)sz < 127 ? (int)sz : 127;
                memcpy(desc, d + pos, n); desc[n] = '\0';
            }
            pos += (int)sz;
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (wid) printf("  id=%u", wid);
    if (name[0]) printf("  name=\"%s\"", name);
    if (desc[0]) printf("  desc=\"%s\"", desc);
    if (has_lat && has_lon) printf("  lat=%.6f  lon=%.6f", lat / 1e7, lon / 1e7);
    if (icon) printf("  icon=0x%x", icon);
    printf("\n");
}

/* meshtastic.Paxcounter: wifi count, ble count, uptime_seconds */
static void decode_paxcounter(const uint8_t *d, int len) {
    uint32_t wifi = 0, ble = 0, uptime = 0;
    bool has_wifi = false, has_ble = false, has_up = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 1) { wifi   = (uint32_t)v; has_wifi = true; }
            else if (fn == 2) { ble    = (uint32_t)v; has_ble  = true; }
            else if (fn == 3) { uptime = (uint32_t)v; has_up   = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_wifi) printf("  wifi=%u", wifi);
    if (has_ble)  printf("  ble=%u",  ble);
    if (has_up)   printf("  uptime=%us", uptime);
    printf("\n");
}

/* meshtastic.StoreAndForward: rr enum (f1), stats sub-msg (f3), heartbeat sub-msg (f5) */
static void decode_store_forward(const uint8_t *d, int len) {
    static const char *rr_names[] = {
        "ERROR","ROUTER_HEARTBEAT","ROUTER_PING","ROUTER_PONG","ROUTER_BUSY",
        "CLIENT_PING","CLIENT_PONG","CLIENT_ABORT","SEND_HISTORY","CLIENT_HISTORY","HISTORY"
    };
    uint32_t rr = 0; bool has_rr = false;
    uint32_t period = 0, secondary = 0;
    uint32_t msgs_total = 0, msgs_saved = 0, msgs_max = 0;
    bool has_heartbeat = false, has_stats = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if (fn == 1) { rr = (uint32_t)v; has_rr = true; }
        } else if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 5) {
                const uint8_t *sd = d + pos; int slen = (int)sz, sp2 = 0;
                while (sp2 < slen) {
                    int prev2 = sp2;
                    uint64_t stag = pb_varint(sd, slen, &sp2);
                    if (sp2 == prev2) break;
                    uint32_t swt = stag & 7, sfn = (uint32_t)(stag >> 3);
                    if (swt == 0) {
                        uint64_t v = pb_varint(sd, slen, &sp2);
                        if      (sfn == 1) period    = (uint32_t)v;
                        else if (sfn == 2) secondary = (uint32_t)v;
                    } else if (!pb_skip(sd, slen, &sp2, swt)) break;
                }
                has_heartbeat = true;
            } else if (fn == 3) {
                const uint8_t *sd = d + pos; int slen = (int)sz, sp2 = 0;
                while (sp2 < slen) {
                    int prev2 = sp2;
                    uint64_t stag = pb_varint(sd, slen, &sp2);
                    if (sp2 == prev2) break;
                    uint32_t swt = stag & 7, sfn = (uint32_t)(stag >> 3);
                    if (swt == 0) {
                        uint64_t v = pb_varint(sd, slen, &sp2);
                        if      (sfn == 1) msgs_total = (uint32_t)v;
                        else if (sfn == 2) msgs_saved = (uint32_t)v;
                        else if (sfn == 3) msgs_max   = (uint32_t)v;
                    } else if (!pb_skip(sd, slen, &sp2, swt)) break;
                }
                has_stats = true;
            }
            pos += (int)sz;
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_rr) {
        const char *s = (rr < 11) ? rr_names[rr] : "UNKNOWN";
        printf("  rr=%s", s);
    }
    if (has_heartbeat) printf("  hb_period=%us  secondary=%u", period, secondary);
    if (has_stats) printf("  msgs_total=%u  saved=%u  max=%u", msgs_total, msgs_saved, msgs_max);
    printf("\n");
}

/* Telemetry.LocalStats (field 4 in Telemetry outer): utilisation + packet counters */
static void decode_local_stats(const uint8_t *d, int len) {
    uint32_t uptime = 0, tx = 0, rx = 0, online = 0, total = 0;
    float chan_util = 0, air_util = 0;
    bool has_up = false, has_chan = false, has_air = false;
    bool has_tx = false, has_rx = false, has_on = false, has_tot = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn == 1) { uptime = (uint32_t)v; has_up  = true; }
            else if (fn == 4) { tx     = (uint32_t)v; has_tx  = true; }
            else if (fn == 5) { rx     = (uint32_t)v; has_rx  = true; }
            else if (fn == 6) { online = (uint32_t)v; has_on  = true; }
            else if (fn == 7) { total  = (uint32_t)v; has_tot = true; }
        } else if (wt == 5 && pos + 4 <= len) {
            float f = pb_float(d, pos); pos += 4;
            if      (fn == 2) { chan_util = f; has_chan = true; }
            else if (fn == 3) { air_util  = f; has_air  = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has_up)   printf("  uptime=%us", uptime);
    if (has_chan)  printf("  chan_util=%.1f%%", chan_util);
    if (has_air)   printf("  air_util=%.1f%%", air_util);
    if (has_tx)    printf("  tx=%u", tx);
    if (has_rx)    printf("  rx=%u", rx);
    if (has_on)    printf("  online=%u", online);
    if (has_tot)   printf("  total=%u", total);
    printf("\n");
}

/* Telemetry.PowerMetrics (field 6 in Telemetry outer): voltage + current per channel */
static void decode_power_metrics(const uint8_t *d, int len) {
    float ch1v = 0, ch1i = 0, ch2v = 0, ch2i = 0, ch3v = 0, ch3i = 0;
    bool has[6] = {false,false,false,false,false,false};
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 5 && pos + 4 <= len) {
            float f = pb_float(d, pos); pos += 4;
            if      (fn == 1) { ch1v = f; has[0] = true; }
            else if (fn == 2) { ch1i = f; has[1] = true; }
            else if (fn == 3) { ch2v = f; has[2] = true; }
            else if (fn == 4) { ch2i = f; has[3] = true; }
            else if (fn == 5) { ch3v = f; has[4] = true; }
            else if (fn == 6) { ch3i = f; has[5] = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (has[0] || has[1]) printf("  ch1=%.2fV/%.0fmA", ch1v, ch1i * 1000);
    if (has[2] || has[3]) printf("  ch2=%.2fV/%.0fmA", ch2v, ch2i * 1000);
    if (has[4] || has[5]) printf("  ch3=%.2fV/%.0fmA", ch3v, ch3i * 1000);
    printf("\n");
}

/* meshtastic.RouteDiscovery (TRACEROUTE): packed fixed32 nodes, packed zigzag SNR×4 */
static void decode_traceroute(const uint8_t *d, int len) {
    uint32_t route[16], route_back[16];
    int32_t  snr_fwd[16], snr_back[16];
    int nfwd = 0, nback = 0, nsnrf = 0, nsnrb = 0;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            const uint8_t *blob = d + pos; int blen = (int)sz;
            if (fn == 1 || fn == 3) {
                uint32_t *arr = (fn == 1) ? route      : route_back;
                int      *cnt = (fn == 1) ? &nfwd      : &nback;
                for (int i = 0; i + 4 <= blen && *cnt < 16; i += 4)
                    memcpy(&arr[(*cnt)++], blob + i, 4);
            } else if (fn == 2 || fn == 4) {
                int32_t *arr = (fn == 2) ? snr_fwd : snr_back;
                int     *cnt = (fn == 2) ? &nsnrf  : &nsnrb;
                int bp = 0;
                while (bp < blen && *cnt < 16) {
                    int bprev = bp;
                    uint64_t v = pb_varint(blob, blen, &bp);
                    if (bp == bprev) break;
                    arr[(*cnt)++] = pb_zigzag(v);
                }
            }
            pos += blen;
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (nfwd > 0) {
        printf("  route:");
        for (int i = 0; i < nfwd; i++) {
            printf(" %08x", route[i]);
            if (i < nsnrf) printf("(%.1fdB)", snr_fwd[i] / 4.0f);
        }
        printf("\n");
    }
    if (nback > 0) {
        printf("  route_back:");
        for (int i = 0; i < nback; i++) {
            printf(" %08x", route_back[i]);
            if (i < nsnrb) printf("(%.1fdB)", snr_back[i] / 4.0f);
        }
        printf("\n");
    }
    if (nfwd == 0 && nback == 0) printf("  [empty route]\n");
}

/* meshtastic.MapReport: node summary broadcast (long_name, hw, firmware, position, counts) */
static void decode_map_report(const uint8_t *d, int len) {
    char long_name[64] = {0}, short_name[8] = {0}, firmware[16] = {0};
    uint32_t hw = 0, region = 0, preset = 0, online_nodes = 0;
    int32_t lat = 0, lon = 0;
    bool has_hw = false, has_region = false, has_preset = false;
    bool has_lat = false, has_lon = false, has_on = false;
    int pos = 0;
    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(d, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(d, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 1) {
                int n = (int)sz < 63 ? (int)sz : 63;
                memcpy(long_name, d + pos, n); long_name[n] = '\0';
            } else if (fn == 2) {
                int n = (int)sz < 7 ? (int)sz : 7;
                memcpy(short_name, d + pos, n); short_name[n] = '\0';
            } else if (fn == 4) {
                int n = (int)sz < 15 ? (int)sz : 15;
                memcpy(firmware, d + pos, n); firmware[n] = '\0';
            }
            pos += (int)sz;
        } else if (wt == 0) {
            uint64_t v = pb_varint(d, len, &pos);
            if      (fn ==  3) { hw      = (uint32_t)v;  has_hw     = true; }
            else if (fn ==  5) { region  = (uint32_t)v;  has_region = true; }
            else if (fn ==  6) { preset  = (uint32_t)v;  has_preset = true; }
            else if (fn ==  8) { lat = pb_zigzag(v);     has_lat    = true; }
            else if (fn ==  9) { lon = pb_zigzag(v);     has_lon    = true; }
            else if (fn == 11) { online_nodes = (uint32_t)v; has_on  = true; }
        } else if (!pb_skip(d, len, &pos, wt)) break;
    }
    if (long_name[0])  printf("  name=\"%s\"", long_name);
    if (short_name[0]) printf("  short=\"%s\"", short_name);
    if (has_hw) {
        const char *s = hw_model_str(hw);
        if (s) printf("  hw=%s", s); else printf("  hw=%u", hw);
    }
    if (firmware[0])    printf("  fw=%s", firmware);
    if (has_region)     printf("  region=%u", region);
    if (has_preset)     printf("  preset=%u", preset);
    if (has_lat && has_lon) printf("  lat=%.6f  lon=%.6f", lat / 1e7, lon / 1e7);
    if (has_on)         printf("  online=%u", online_nodes);
    printf("\n");
}

/* meshtastic.Data protobuf: extract portnum + payload, dispatch to sub-decoder.
   Returns false if portnum is unrecognised (wrong key / not Meshtastic). */
static bool decode_data_pb(const uint8_t *data, int len, uint32_t src_id) {
    uint32_t portnum = 0;
    const uint8_t *payload = NULL;
    int plen = 0, pos = 0;

    while (pos < len) {
        int prev = pos;
        uint64_t tag = pb_varint(data, len, &pos);
        if (pos == prev) break;
        uint32_t wt = tag & 7, fn = (uint32_t)(tag >> 3);
        if (wt == 0) {
            uint64_t v = pb_varint(data, len, &pos);
            if (fn == 1) portnum = (uint32_t)v;
        } else if (wt == 2) {
            int sp = pos;
            uint64_t sz = pb_varint(data, len, &pos);
            if (pos == sp || pos + (int)sz > len) break;
            if (fn == 2) { payload = data + pos; plen = (int)sz; }
            pos += (int)sz;
        } else if (!pb_skip(data, len, &pos, wt)) break;
    }

    const char *name = portnum_str(portnum);
    if (!name || (portnum == 0 && !payload)) return false;

    printf("  portnum=%-3u (%s)\n", portnum, name);
    if (!payload || plen == 0) return true;

    switch (portnum) {
        case  1: printf("  \"%.*s\"\n", plen, (const char *)payload); break;
        case  3: decode_position(payload, plen);              break;
        case  4: decode_user(payload, plen, src_id);          break;
        case  5: decode_routing(payload, plen);               break;
        case  8: decode_waypoint(payload, plen);              break;
        case 10: printf("  \"%.*s\"\n", plen, (const char *)payload); break;
        case 34: decode_paxcounter(payload, plen);            break;
        case 65: decode_store_forward(payload, plen);         break;
        case 66: printf("  \"%.*s\"\n", plen, (const char *)payload); break;
        case 67: decode_telemetry(payload, plen);             break;
        case 70: decode_traceroute(payload, plen);            break;
        case 71: decode_neighborinfo(payload, plen);          break;
        case 73: decode_map_report(payload, plen);            break;
        default: {
            int show = plen < 24 ? plen : 24;
            printf("  payload[%d]=", plen);
            for (int i = 0; i < show; i++) printf("%02x", payload[i]);
            if (plen > 24) printf("...");
            printf("\n");
        }
    }
    return true;
}

static void decode_meshtastic(const uint8_t *buf, uint16_t len) {
    if (len < MESH_HDR + 1) return;

    mesh_hdr_t h;
    parse_mesh_hdr(buf, &h);

    /* look up known name for src node */
    const char *src_name = NULL;
    node_rec_t *src_rec = node_find(h.src);
    if (src_rec && src_rec->long_name[0]) src_name = src_rec->long_name;

    char name_tag[68] = {0};
    if (src_name) snprintf(name_tag, sizeof name_tag, "  [%s]", src_name);

    if (h.dest == 0xFFFFFFFF)
        printf("  dest=broadcast   src=%08x  id=%08x  hops=%u/%u  ch=0x%02x%s%s%s\n",
               h.src, h.id, h.hop_limit, h.hop_start, h.channel_hash,
               h.want_ack ? "  ACK" : "", h.via_mqtt ? "  MQTT" : "", name_tag);
    else
        printf("  dest=%08x  src=%08x  id=%08x  hops=%u/%u  ch=0x%02x%s%s%s\n",
               h.dest, h.src, h.id, h.hop_limit, h.hop_start, h.channel_hash,
               h.want_ack ? "  ACK" : "", h.via_mqtt ? "  MQTT" : "", name_tag);

    if (h.hop_limit > h.hop_start) {
        printf("  [invalid hops — corrupted header]\n");
        return;
    }

    /* try all known PSKs in order */
    uint8_t plain[256];
    for (int ki = 0; ki < mesh_key_count; ki++) {
        int plen = aes_ctr(mesh_keys[ki], mesh_key_len[ki], h.id, h.src,
                              buf + MESH_HDR, len - MESH_HDR, plain);
        if (plen <= 0) continue;
        if (decode_data_pb(plain, plen, h.src)) return;
    }
    printf("  [encrypted / wrong key]\n");
}

/* ── LoRaWAN MAC decoder ─────────────────────────────────────────────────── */

static const char *lw_mtype_str(uint8_t t) {
    switch (t) {
        case 0: return "Join-Request";
        case 1: return "Join-Accept";
        case 2: return "Unconfirmed-Data-Up";
        case 3: return "Unconfirmed-Data-Down";
        case 4: return "Confirmed-Data-Up";
        case 5: return "Confirmed-Data-Down";
        case 6: return "Rejoin-Request";
        case 7: return "Proprietary";
        default: return "Unknown";
    }
}

/* EUI bytes are LE on wire; display reversed (big-endian / standard notation) */
static void print_eui(const uint8_t *b) {
    printf("%02X-%02X-%02X-%02X-%02X-%02X-%02X-%02X",
           b[7], b[6], b[5], b[4], b[3], b[2], b[1], b[0]);
}

static void decode_lorawan(const uint8_t *buf, uint16_t len) {
    if (len < 4) return;

    uint8_t mtype = (buf[0] >> 5) & 0x07;
    printf("  [LoRaWAN]  %s\n", lw_mtype_str(mtype));

    switch (mtype) {

    case 0: {
        /* Join Request: MHDR(1) + JoinEUI(8) + DevEUI(8) + DevNonce(2) + MIC(4) = 23 */
        if (len < 23) { printf("  [truncated]\n"); return; }
        printf("  JoinEUI="); print_eui(buf + 1);
        printf("  DevEUI=");  print_eui(buf + 9);
        uint16_t devnonce; memcpy(&devnonce, buf + 17, 2);
        printf("  DevNonce=0x%04X\n", devnonce);
        break;
    }

    case 1:
        /* Join Accept: encrypted with AppKey */
        printf("  [encrypted — need AppKey to decode]\n");
        break;

    case 2: case 3: case 4: case 5: {
        /* Data frame: MHDR(1) DevAddr(4) FCtrl(1) FCnt(2) FOpts(0-15) [FPort] [FRMPayload] MIC(4) */
        if (len < 12) { printf("  [truncated]\n"); return; }
        uint32_t devaddr; memcpy(&devaddr, buf + 1, 4);
        uint8_t  fctrl = buf[5];
        uint16_t fcnt;  memcpy(&fcnt, buf + 6, 2);
        uint8_t  fol   = fctrl & 0x0F;         /* FOpts length */
        bool     adr      = (fctrl >> 7) & 1;
        bool     ack      = (fctrl >> 5) & 1;
        bool     up       = !(mtype & 1);
        bool     adr_req  = up  && ((fctrl >> 6) & 1);
        bool     fpending = !up && ((fctrl >> 4) & 1);

        int fp = 8 + fol;   /* byte position of FPort (if present) */
        if (fp + 4 > (int)len) {
            printf("  DevAddr=%08X  [malformed: FOpts overrun packet]\n", devaddr);
            return;
        }
        bool has_port = (fp + 4 < (int)len);   /* at least FPort + MIC bytes present */
        int  fport    = has_port ? buf[fp] : -1;
        int  plen     = has_port ? (int)len - fp - 1 - 4 : 0;

        printf("  DevAddr=%08X  FCnt=%u", devaddr, fcnt);
        if (fol)      printf("  FOpts=%uB", fol);
        if (adr)      printf("  ADR");
        if (ack)      printf("  ACK");
        if (adr_req)  printf("  ADRACKReq");
        if (fpending) printf("  FPending");
        if (fport >= 0)
            printf("  FPort=%d  payload=%dB[encrypted]", fport, plen);
        else
            printf("  [no application payload]");
        printf("  MIC=%02X%02X%02X%02X\n",
               buf[len-4], buf[len-3], buf[len-2], buf[len-1]);
        break;
    }

    case 6: {
        /* Rejoin Request: Type(1) then layout depends on type */
        if (len < 19) { printf("  [truncated]\n"); return; }
        uint8_t rj_type = buf[1];
        if (rj_type == 1 && len >= 24) {
            printf("  Type=1  JoinEUI="); print_eui(buf + 2);
            printf("  DevEUI=");          print_eui(buf + 10);
        } else {
            printf("  Type=%u  DevEUI=", rj_type); print_eui(buf + 5);
        }
        printf("\n");
        break;
    }

    default: {
        int show = len < 24 ? len : 24;
        printf("  raw[%u]=", len);
        for (int i = 0; i < show; i++) printf("%02x", buf[i]);
        if (len > 24) printf("...\n"); else printf("\n");
        break;
    }

    }
}

/* ── init concentrator ─────────────────────────────────────────────────── */

static int init_concentrator(void) {
    /* board */
    struct lgw_conf_board_s board = {
        .lorawan_public = true,   /* sets multi-SF sync word to 0x34 (LoRaWAN) at lgw_start() */
        .clksrc         = 0,
        .full_duplex    = false,
        .com_type       = LGW_COM_SPI,
    };
    strncpy(board.com_path, SPI_DEV, sizeof board.com_path - 1);
    if (lgw_board_setconf(&board) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_board_setconf failed\n");
        return -1;
    }

    /* RF chain 0 — lower EU868 */
    struct lgw_conf_rxrf_s rf0 = {
        .enable            = true,
        .freq_hz           = RF0_FREQ_HZ,
        .rssi_offset       = -215.4,
        .rssi_tcomp        = { .coeff_a=0, .coeff_b=0, .coeff_c=20.41,
                               .coeff_d=2162.56, .coeff_e=0 },
        .type              = LGW_RADIO_TYPE_SX1250,
        .tx_enable         = false,
        .single_input_mode = false,
    };
    if (lgw_rxrf_setconf(0, &rf0) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_rxrf_setconf(0) failed\n");
        return -1;
    }

    /* RF chain 1 — upper EU868 */
    struct lgw_conf_rxrf_s rf1 = rf0;
    rf1.freq_hz = RF1_FREQ_HZ;
    if (lgw_rxrf_setconf(1, &rf1) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_rxrf_setconf(1) failed\n");
        return -1;
    }

    /* global multi-SF demodulator: enable SF5–SF12 */
    struct lgw_conf_demod_s demod = {
        .multisf_datarate = LGW_MULTI_SF_EN,
    };
    if (lgw_demod_setconf(&demod) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_demod_setconf failed\n");
        return -1;
    }

    /* multi-SF channels 0–7 */
    for (int i = 0; i < LGW_MULTI_NB; i++) {
        struct lgw_conf_rxif_s ifconf = {
            .enable   = true,
            .rf_chain = MULTISF_CHANS[i].rf_chain,
            .freq_hz  = MULTISF_CHANS[i].freq_offset,
        };
        if (lgw_rxif_setconf(i, &ifconf) != LGW_HAL_SUCCESS) {
            fprintf(stderr, "ERROR: lgw_rxif_setconf(%d) failed\n", i);
            return -1;
        }
        printf("  ch%d: %s\n", i, MULTISF_CHANS[i].label);
    }

    /* LoRa service channel 8 — Meshtastic BW250 SF11 */
    struct lgw_conf_rxif_s svc = {
        .enable    = true,
        .rf_chain  = MESHTASTIC_RF_CHAIN,
        .freq_hz   = MESHTASTIC_IF_HZ,
        .bandwidth = MESHTASTIC_BW,
        .datarate  = MESHTASTIC_SF,
    };
    if (lgw_rxif_setconf(8, &svc) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_rxif_setconf(8/Meshtastic) failed\n");
        return -1;
    }
    printf("  ch8: 869.525 MHz BW250 SF11 [MESHTASTIC]\n");

    /* ch9 FSK — explicitly disabled */
    struct lgw_conf_rxif_s fsk = { .enable = false };
    if (lgw_rxif_setconf(9, &fsk) != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_rxif_setconf(9/FSK) failed\n");
        return -1;
    }
    printf("  ch9: FSK disabled\n");

    return 0;
}

/* ── main ──────────────────────────────────────────────────────────────── */

int main(void) {
    signal(SIGINT,  sig_handler);
    signal(SIGTERM, sig_handler);

    printf("EU868 + Meshtastic Sniffer — Sencap M1 / SX1303\n");
    printf("=================================================\n");
    printf("Meshtastic: %u Hz BW250 SF11 (ch8)\n", MESHTASTIC_FREQ_HZ);
    printf("EU868 scan: 867.9–869.818 MHz BW125 multi-SF (ch0–ch7)\n\n");

    node_db_load();
    keys_load();
    printf("\nChannels:\n");

    if (init_concentrator() != 0) return EXIT_FAILURE;

    if (lgw_start() != LGW_HAL_SUCCESS) {
        fprintf(stderr, "ERROR: lgw_start() failed — check SPI and reset\n");
        return EXIT_FAILURE;
    }

    /*
     * lgw_start() programmed ch0–ch7 (multi-SF) to LoRaWAN 0x34 (PEAK1=6, PEAK2=8)
     * via lorawan_public=true.  Override only ch8 (service channel) to
     * Meshtastic 0x2B:  PEAK1 = 2×(0x2B>>4) = 4,  PEAK2 = 2×(0x2B&0x0F) = 22.
     */
    lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH0_PEAK1_POS, 4);
    lgw_reg_w(SX1302_REG_RX_TOP_LORA_SERVICE_FSK_FRAME_SYNCH1_PEAK2_POS, 22);

    printf("\nListening... (Ctrl+C to stop)\n\n");

    struct lgw_pkt_rx_s rxpkt[32];

    while (keep_running) {
        int nb = lgw_receive(32, rxpkt);
        if (nb < 0) {
            fprintf(stderr, "ERROR: lgw_receive() returned %d\n", nb);
            break;
        }
        for (int i = 0; i < nb; i++) {
            if (rxpkt[i].status != STAT_CRC_OK) continue;
            pkt_count++;
            print_packet(
                rxpkt[i].payload, rxpkt[i].size,
                rxpkt[i].freq_hz, rxpkt[i].datarate,
                rxpkt[i].rssi,    rxpkt[i].snr
            );
            if (is_meshtastic(rxpkt[i].freq_hz))
                decode_meshtastic(rxpkt[i].payload, rxpkt[i].size);
            else
                decode_lorawan(rxpkt[i].payload, rxpkt[i].size);
            fflush(stdout);
        }
        usleep(10000);
    }

    printf("Stopped — %llu packets received\n", (unsigned long long)pkt_count);
    lgw_stop();
    return EXIT_SUCCESS;
}
