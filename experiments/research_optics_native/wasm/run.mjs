// node run.mjs MODULE.wasm DIR: for each DIR/*.raw (u32le w, u32le h, RGB),
// runs exposure.rs's wasm32 build and writes DIR/*.wasm-out (same format,
// only when applied) and one JSON line per file. No timing is measured.
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [module, dir] = process.argv.slice(2);
const { instance } = await WebAssembly.instantiate(readFileSync(module), {});
const x = instance.exports;
for (const name of readdirSync(dir).filter((n) => n.endsWith('.raw')).sort()) {
  const data = readFileSync(join(dir, name));
  const w = data.readUInt32LE(0);
  const h = data.readUInt32LE(4);
  const len = data.length - 8;
  for (const rgba of [0, 1]) {
    const pixels = rgba ? Buffer.alloc(w * h * 4) : data.subarray(8);
    if (rgba) for (let i = 0; i < w * h; i++) {
      data.copy(pixels, i * 4, 8 + i * 3, 11 + i * 3);
      pixels[i * 4 + 3] = (i * 37) & 255;
    }
    const n = pixels.length;
    const ptr = x.alloc(n);
    new Uint8Array(x.memory.buffer, ptr, n).set(pixels);
    const status = x.run(ptr, n, w, h, rgba);
    x.free(ptr, n);
    const out = new Uint8Array(x.memory.buffer, x.out_ptr(), x.out_len());
    let alphaKept = true;
    let rgbOut = null;
    if (out.length) {
      if (rgba) {
        rgbOut = Buffer.alloc(w * h * 3);
        for (let i = 0; i < w * h; i++) {
          rgbOut[i * 3] = out[i * 4]; rgbOut[i * 3 + 1] = out[i * 4 + 1]; rgbOut[i * 3 + 2] = out[i * 4 + 2];
          if (out[i * 4 + 3] !== ((i * 37) & 255)) alphaKept = false;
        }
      } else rgbOut = Buffer.from(out);
    }
    if (rgbOut) {
      const header = Buffer.alloc(8);
      header.writeUInt32LE(w, 0); header.writeUInt32LE(h, 4);
      writeFileSync(join(dir, name.replace(/\.raw$/, rgba ? '.wasm-rgba-out' : '.wasm-out')), Buffer.concat([header, rgbOut]));
    }
    console.log(JSON.stringify({ name, rgba: !!rgba, status, p90: x.p90(), gain: x.gain(), alpha_kept: alphaKept }));
  }
}
