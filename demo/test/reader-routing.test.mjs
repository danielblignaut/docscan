import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadPureModule} from './load-pure-module.mjs';
const {readerRoute,paddleThreadCount}=await loadPureModule(new URL('../src/reader-routing.ts',import.meta.url));
test('lightweight workflows cannot accidentally initialize full OCR models',()=>{
 assert.equal(readerRoute('barcodes','ocrs','ocrs','detailed'),'capture');
 assert.equal(readerRoute('items','ocrs','ocrs','fast'),'capture');
 assert.equal(readerRoute('labels','ocrs','ocrs','fast'),'paddle');
 for(const engine of ['ppocr_v6_tiny','ppocr_v6_tiny_detail','ppocr_v6_tiny_exposure'])assert.equal(readerRoute('text',engine,'ocrs','detailed'),'paddle');
 assert.equal(readerRoute('tables','ocrs','ppocr_v6_tiny','detailed'),'paddle');
});
test('identity, address and detailed readers retain the full document client regardless of other choices',()=>{
 for(const mode of ['smart_id','green_book','passport','auto','address','facedoc'])assert.equal(readerRoute(mode,'ppocr_v6_tiny','ppocr_v6_tiny','fast'),'documents');
 assert.equal(readerRoute('labels','ppocr_v6_tiny','ppocr_v6_tiny','detailed'),'documents');
 assert.equal(readerRoute('text','ocrs','ppocr_v6_tiny','fast'),'documents');
 assert.equal(readerRoute('tables','ppocr_v6_tiny','ocrs','fast'),'documents');
});

test('tiny OCR defaults to one thread but respects a bounded explicit override',()=>{
 assert.equal(paddleThreadCount(''),1);assert.equal(paddleThreadCount('?threads=2'),2);
 for(const search of ['?threads=Infinity','?threads=0','?threads=2.5','?threads=9999'])assert.equal(paddleThreadCount(search),1);
});
