import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transformWithEsbuild} from 'vite';
const path=new URL('../src/exposure-comparison.ts',import.meta.url).pathname;
const {code}=await transformWithEsbuild(readFileSync(path,'utf8'),path);
const {compareExposure}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
const original=Object.freeze({engine:'ppocr_v6_tiny',text:'original 123',lines:Object.freeze([])});
function correction(overrides={}) {
 let freed=0,taken=0;
 const value={version:'frozen-global-exposure-v1',applied:true,changed:true,gain:4,background_p90:.1,
 take_rgba(){taken++;return new Uint8Array([9,10,11,255]);},free(){freed++;},...overrides};
 return {value,freed:()=>freed,taken:()=>taken};
}
test('alternative never selects, edits or merges the original reading',()=>{
 const c=correction(), alternative={...original,text:'alternative 128'};
 const result=compareExposure(original,()=>c.value,pixels=>{assert.equal(pixels[0],9);return alternative;});
 assert.equal(result.text,'original 123');assert.equal(result.lines,original.lines);
 assert.equal(result.exposure.alternative,alternative);assert.equal(result.exposure.ocrPasses,2);
 assert.equal(c.freed(),1);assert.equal(c.taken(),1);assert.equal(original.exposure,undefined);
});
test('clean no-op skips the second OCR and still frees the handle',()=>{
 const c=correction({applied:false,changed:false,gain:1,background_p90:.9});
 const result=compareExposure(original,()=>c.value,()=>assert.fail('unexpected OCR'));
 assert.equal(result.exposure.status,'unchanged');assert.equal(result.exposure.alternative,null);
 assert.equal(result.exposure.ocrPasses,1);assert.equal(c.taken(),0);assert.equal(c.freed(),1);
});
test('failed transform, version mismatch, invalid diagnostics and failed OCR preserve primary',()=>{
 for(const mode of ['factory','version','diagnostics','ocr','cleanup']) {
  const c=correction(mode==='version'?{version:'different'}:mode==='diagnostics'?{gain:NaN}:mode==='cleanup'?{free(){throw Error('cleanup failed');}}:{});
  const result=compareExposure(original,()=>{if(mode==='factory')throw Error('transform failed');return c.value;},()=>{if(mode==='ocr')throw Error('OCR failed');return {...original,text:'alternative'};});
  assert.equal(result.text,original.text);assert.equal(result.exposure.status,'failed');
  assert.equal(result.exposure.alternative,null);assert.ok(result.exposure.error);
  assert.equal(result.exposure.ocrPasses,['ocr','cleanup'].includes(mode)?2:1);
  if(!['factory','cleanup'].includes(mode)) assert.equal(c.freed(),1);
 }
});
