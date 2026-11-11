// Mic processor: averages the input down to 16 kHz and posts 20 ms frames.
class Mic extends AudioWorkletProcessor {
  constructor(options){
    super();
    const {rate = 16000, frame = 320} = (options && options.processorOptions) || {};
    this.step = sampleRate / rate; this.frame = frame;
    this.pos = 0; this.acc = 0; this.n = 0; this.out = new Float32Array(frame); this.k = 0;
  }
  process(inputs){
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.n++; this.pos += 1;
      if (this.pos >= this.step) {
        this.pos -= this.step;
        this.out[this.k++] = this.acc / this.n; this.acc = 0; this.n = 0;
        if (this.k === this.frame) { this.port.postMessage(this.out.slice()); this.k = 0; }
      }
    }
    return true;
  }
}
registerProcessor('mic', Mic);
