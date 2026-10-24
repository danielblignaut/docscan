import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { transformWithEsbuild } from 'vite';
const path = new URL('../src/document-review.ts', import.meta.url).pathname;
const {code}=await transformWithEsbuild(readFileSync(path,'utf8'),path);
const {comparePdfText,documentEvidence,unknownCopyAssessment}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
const page=text=>({index:0,status:'complete',text:{status:'checked',truncated:false,items:[{text}]}});
test('matching text is agreement, never an authenticity verdict',()=>{
 const r=comparePdfText(page('Balance 100.00'),'balance 100.00');
 assert.equal(r.nativeTokenCoverage,1);assert.equal(r.isTampered,null);
 assert.equal(documentEvidence([],[]).authenticity.isAuthentic,null);
});
test('an altered amount is retained as a discrepancy without asserting fraud',()=>{
 const r=comparePdfText(page('Balance 100.00'),'Balance 900.00');
 assert.deepEqual(r.numericDisagreements,{nativeOnly:['100.00'],ocrOnly:['900.00']});assert.equal(r.isTampered,null);
});
test('missing, truncated and region OCR cannot masquerade as agreement',()=>{
 assert.equal(comparePdfText(undefined,'text').status,'not_available');
 assert.equal(comparePdfText({...page('text'),status:'incomplete'},'text').status,'not_comparable');
 assert.equal(comparePdfText(page('text'),'text',false).status,'not_comparable');
 assert.equal(comparePdfText(page('text'),'').nativeTokenCoverage,null);
});
test('repeated native text and excessive inputs retain conservative accounting',()=>{
 assert.equal(comparePdfText(page('100 100'),'100').nativeTokenCoverage,.5);
 assert.equal(comparePdfText(page('x'.repeat(100001)),'x').status,'not_comparable');
 const copy=unknownCopyAssessment();assert.equal(copy.is_copy,null);assert.equal(copy.confidence,null);
});
