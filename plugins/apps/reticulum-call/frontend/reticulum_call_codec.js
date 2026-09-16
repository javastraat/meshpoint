/**
 * Float32 PCM <-> Codec2 encoded bytes, via the vendored WASM encoder/
 * decoder (codec2/c2enc.js, codec2/c2dec.js -- Emscripten builds of the
 * real codec2 CLI tools, same WASM reticulum-meshchat itself vendors,
 * MIT, Liam Cottle).
 *
 * Deliberately simpler than reticulum-meshchat's own Codec2Lib: that
 * version round-trips every chunk through a WAV file and its own
 * vendored SOX build (encodeWAV -> Codec2Lib.audioFileToRaw() via SOX
 * -> runEncode(), and the mirror image on decode) purely to get from
 * "Float32 samples" to "headerless 16-bit PCM bytes" and back --
 * SOX's actual job there (resampling) is a no-op, since the
 * AudioWorklet processor already delivers 8 kHz samples, Codec2's own
 * required rate. Converting Float32 <-> 16-bit PCM directly (same math
 * as WavEncoder.floatTo16BitPCM(), just without ever writing a WAV
 * header) skips a whole extra WASM module (sox.wasm, ~650 KB) and a
 * full module-boot per audio chunk, with the same result. If real
 * interop with an actual Sideband/meshchat peer's exact wire format is
 * ever needed, re-check this against their protobuf-wrapped payload
 * shape first -- this plugin does not attempt to match it (see the
 * module docstring in reticulum_call_panel.js for the wire format this
 * uses instead).
 */
class ReticulumCallCodec {
    // Same set CallPage.vue itself offers -- bitrate/quality tradeoffs
    // baked into codec2 itself, nothing to configure beyond picking one.
    static MODES = ['3200', '2400', '1600', '1400', '1300', '1200', '700C', '450', '450PWB'];
    static DEFAULT_MODE = '1200';

    static _floatTo16BitPCM(float32Samples) {
        const buffer = new ArrayBuffer(float32Samples.length * 2);
        const view = new DataView(buffer);
        for (let i = 0; i < float32Samples.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Samples[i]));
            view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        return new Uint8Array(buffer);
    }

    static _int16PCMToFloat32(uint8Bytes) {
        const view = new DataView(uint8Bytes.buffer, uint8Bytes.byteOffset, uint8Bytes.byteLength);
        const length = Math.floor(uint8Bytes.byteLength / 2);
        const out = new Float32Array(length);
        for (let i = 0; i < length; i++) {
            out[i] = view.getInt16(i * 2, true) / 0x8000;
        }
        return out;
    }

    /** Float32 PCM samples (8 kHz mono, straight from the AudioWorklet)
     * -> Codec2-encoded bytes for *mode*. */
    static encode(mode, float32Samples) {
        const rawPcm = ReticulumCallCodec._floatTo16BitPCM(float32Samples);
        return new Promise((resolve, reject) => {
            const module = {
                arguments: [mode, 'input.raw', 'output.bit'],
                preRun: () => module.FS.writeFile('input.raw', rawPcm),
                postRun: () => {
                    try {
                        resolve(module.FS.readFile('output.bit', { encoding: 'binary' }));
                    } catch (e) {
                        reject(e);
                    }
                },
            };
            createC2Enc(module);
        });
    }

    /** Codec2-encoded bytes -> Float32 PCM samples (8 kHz mono), ready
     * for WavEncoder.encodeWAV() + AudioContext.decodeAudioData(). */
    static decode(mode, encodedBytes) {
        return new Promise((resolve, reject) => {
            const module = {
                arguments: [mode, 'input.bit', 'output.raw'],
                preRun: () => module.FS.writeFile('input.bit', new Uint8Array(encodedBytes)),
                postRun: () => {
                    try {
                        const raw = module.FS.readFile('output.raw', { encoding: 'binary' });
                        resolve(ReticulumCallCodec._int16PCMToFloat32(raw));
                    } catch (e) {
                        reject(e);
                    }
                },
            };
            createC2Dec(module);
        });
    }
}

window.ReticulumCallCodec = ReticulumCallCodec;
