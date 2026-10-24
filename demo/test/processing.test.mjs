import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transformWithEsbuild} from 'vite';
const path=new URL('../src/processing.ts',import.meta.url).pathname;
const {code}=await transformWithEsbuild(readFileSync(path,'utf8'),path);
const {createProcessingSession}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
test('capture-ready is pending validation, correlated, metadata-only and emitted once',()=>{
 const events=[];const session=createProcessingSession('text','file',(type,detail)=>events.push({type,detail}));
 session.captured({inputCount:1});session.captured();session.stage('ocr');session.complete();session.fail(Error('late'));session.cancel();
 assert.equal(events.filter(e=>e.type==='docscan:capture-ready').length,1);
 assert.equal(events[0].detail.validation,'pending');assert.equal(events[0].detail.inputCount,1);
 assert.deepEqual(events.filter(e=>e.type==='docscan:processing').map(e=>e.detail.status),['captured','processing','complete']);
 assert.ok(events.every(e=>e.detail.operationId===session.id&&!('blob' in e.detail)));assert.equal(session.active(),false);
});
test('cancellation is terminal, including aborted inference',()=>{
 const events=[];const session=createProcessingSession('passport','camera',(_,detail)=>events.push(detail));
 session.captured();session.fail(new DOMException('cancelled','AbortError'));session.complete();session.stage('late');
 assert.equal(events.at(-1).status,'cancelled');assert.equal(events.filter(e=>e.status==='cancelled').length,1);
});
test('unstarted sessions emit nothing, while a stage-only operation terminates',()=>{
 const events=[];
 const unused=createProcessingSession('text','camera',(_,detail)=>events.push(detail));
 unused.cancel();unused.stage('late');assert.equal(events.length,0);
 const match=createProcessingSession('facedoc','camera',(_,detail)=>events.push(detail));
 match.stage('face_match');match.complete();
 assert.deepEqual(events.map(e=>e.status),['processing','complete']);
});
