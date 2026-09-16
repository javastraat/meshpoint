/*
 * AudioWorklet processor -- captures mic input in 4096-sample chunks and
 * posts each chunk (already downsampled to 8 kHz, Codec2's expected rate)
 * to the main thread. Loaded via audioContext.audioWorklet.addModule(),
 * never as a plain <script> -- registerProcessor() below only exists
 * inside an AudioWorkletGlobalScope. The `typeof` guard makes an
 * accidental normal-script load a silent no-op instead of a
 * ReferenceError, in case anything ever loads this file the wrong way.
 *
 * Ported from reticulum-meshchat's assets/js/codec2-emscripten/
 * processor.js (MIT, Liam Cottle) -- logic unchanged.
 */
if (typeof registerProcessor !== 'undefined') {
    class ReticulumCallAudioProcessor extends AudioWorkletProcessor {
        constructor() {
            super();
            this.bufferSize = 4096;
            this.sampleRate = 8000;
            this.inputBuffer = new Float32Array(this.bufferSize);
            this.bufferIndex = 0;
        }

        process(inputs) {
            const input = inputs[0];
            if (input.length > 0) {
                const inputData = input[0];
                for (let i = 0; i < inputData.length; i++) {
                    if (this.bufferIndex < this.bufferSize) {
                        this.inputBuffer[this.bufferIndex++] = inputData[i];
                    }
                    if (this.bufferIndex === this.bufferSize) {
                        const downsampled = this._downsample(this.inputBuffer, this.sampleRate);
                        this.port.postMessage(downsampled);
                        this.bufferIndex = 0;
                    }
                }
            }
            return true;
        }

        _downsample(buffer, targetSampleRate) {
            if (targetSampleRate === this.sampleRate) return buffer;
            const ratio = this.sampleRate / targetSampleRate;
            const newLength = Math.round(buffer.length / ratio);
            const result = new Float32Array(newLength);
            let offsetResult = 0;
            let offsetBuffer = 0;
            while (offsetResult < result.length) {
                const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
                let accum = 0;
                let count = 0;
                for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
                    accum += buffer[i];
                    count++;
                }
                result[offsetResult] = accum / count;
                offsetResult++;
                offsetBuffer = nextOffsetBuffer;
            }
            return result;
        }
    }

    registerProcessor('reticulum-call-audio-processor', ReticulumCallAudioProcessor);
}
