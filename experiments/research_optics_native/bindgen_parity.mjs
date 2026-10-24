// Exercise the actual wasm-bindgen wrapper against the native reference, using procedural pixels only.
// Build the harness with cargo build --release --manifest-path experiments/research_optics_native/Cargo.toml.
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import init,{Scanner} from '../../docscan/pkg/docscan.js';
await init({module_or_path:readFileSync(new URL('../../docscan/pkg/docscan_bg.wasm',import.meta.url))});
const binary=process.argv[2]??new URL('./target/release/exposure',import.meta.url).pathname;
const dir=mkdtempSync(join(tmpdir(),'docscan-bindgen-exposure-'));
const scanner=new Scanner();
try{
 for(const [w,h,level] of [[1024,768,40],[513,701,40],[400,300,188],[512,512,255]]){
  const rgb=Buffer.alloc(w*h*3),rgba=new Uint8Array(w*h*4);
  for(let i=0;i<w*h;i++){
   for(let c=0;c<3;c++)rgb[i*3+c]=rgba[i*4+c]=Math.min(255,Math.max(0,level+((i+c)%7)-3));
   rgba[i*4+3]=(i*37)&255;
  }
  const header=Buffer.alloc(8);header.writeUInt32LE(w,0);header.writeUInt32LE(h,4);
  const input=join(dir,`${w}-${h}.raw`),out=input+'.out';
  writeFileSync(input,Buffer.concat([header,rgb]));
  const reference=JSON.parse(execFileSync(binary,['apply',input,out],{encoding:'utf8'}));
  const before=rgba.slice(),preview=scanner.exposure_preview(rgba,w,h);
  try{
   assert.equal(preview.version,reference.version);assert.equal(preview.applied,reference.applied);
   assert.equal(preview.changed,reference.changed);assert.equal(preview.gain,reference.gain);
   assert.equal(preview.background_p90,reference.background_p90);
   const pixels=preview.take_rgba();assert.equal(preview.take_rgba().length,0);
   if(reference.applied){
    const expected=readFileSync(out).subarray(8);
    assert.equal(pixels.length,rgba.length);
    for(let i=0;i<w*h;i++){
     for(let c=0;c<3;c++)assert.equal(pixels[i*4+c],expected[i*3+c]);
     assert.equal(pixels[i*4+3],rgba[i*4+3]);
    }
   }else assert.equal(pixels.length,0);
   assert.deepEqual(rgba,before);
  }finally{preview.free();}
 }
 console.log('PASS wasm-bindgen/native parity: four procedural shapes, exact bytes/diagnostics, alpha retained, input unchanged, take-once ownership');
}finally{scanner.free();rmSync(dir,{recursive:true,force:true});}
