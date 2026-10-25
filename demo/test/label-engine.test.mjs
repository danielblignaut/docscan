import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadPureModule} from './load-pure-module.mjs';
const {labelEngineFromUrl,labelRequest}=await loadPureModule(new URL('../src/label-engine.ts',import.meta.url));
const {mergeLabelReading}=await loadPureModule(new URL('../src/barcode-enrichment.ts',import.meta.url));
test('fast labels require an explicit reader choice; default requests remain compatible',()=>{
 const image={width:4,height:4};
 for(const search of ['', '?labelReader=unknown','?labelReader=detailed'])assert.equal(labelEngineFromUrl(search),'detailed');
 assert.equal(labelEngineFromUrl('?labelReader=fast'),'fast');
 assert.deepEqual(labelRequest('detailed',image),{kind:'labelled',image});
 assert.deepEqual(labelRequest('fast',image),{kind:'labelled',image,profile:'fast'});
});
test('enrichment records the reader without replacing original decoded codes',()=>{
 const original={kind:'barcodes',barcodes:[{text:'fictional',format:'qr'}],fields:[],meta:{captureMs:100}};
 const enriched=mergeLabelReading(original,{kind:'barcodes',fields:[],labelReader:'fast',meta:{}},2500);
 assert.equal(enriched.barcodes,original.barcodes);assert.equal(enriched.labelReader,'fast');assert.equal(enriched.meta.captureMs,100);
});
