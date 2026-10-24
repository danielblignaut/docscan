import assert from 'node:assert/strict';
import {test,beforeEach,afterEach} from 'node:test';
import {readFileSync} from 'node:fs';
import {transformWithEsbuild} from 'vite';
const path=new URL('../src/scanner-client.ts',import.meta.url).pathname;
let {code}=await transformWithEsbuild(readFileSync(path,'utf8'),path);
code=code.replace('new URL("./worker.ts", import.meta.url)','"worker-test"');
const {ScannerClient}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
let workers, savedWorker, failNextInit=false;
class WorkerMock {
 posts=[];terminated=false;
 constructor(){workers.push(this);if(failNextInit){this.throwPost=true;failNextInit=false;}}
 postMessage(message){if(this.throwPost)throw Error('post failed');this.posts.push(message);}
 terminate(){this.terminated=true;}
 reply(message){this.onmessage({data:message});}
}
beforeEach(()=>{workers=[];failNextInit=false;savedWorker=globalThis.Worker;globalThis.Worker=WorkerMock;});
afterEach(()=>{globalThis.Worker=savedWorker;});
const ready={kind:'ready',ocr:false,tagger:false,loadMs:1,threads:1};
const request=()=>({kind:'barcodes',image:{data:new Uint8ClampedArray(4)},formats:[]});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('construction is inert and model-free decoding does not wait for the OCR client',async()=>{
 const fast=new ScannerClient(1,{loadModels:false}),ocr=new ScannerClient(1);
 assert.equal(workers.length,0);
 const f=fast.run(request()),s=ocr.run(request());s.catch(()=>{});
 assert.equal(workers.length,2);assert.equal(workers[0].posts[0].loadModels,false);assert.equal(workers[1].posts[0].loadModels,true);
 workers[0].reply(ready);await tick();
 assert.equal(workers[0].posts.length,2);assert.equal(workers[1].posts.length,1);
 workers[0].reply({kind:'result',id:workers[0].posts[1].id,result:['fast'],ms:1,memoryBytes:4});
 assert.deepEqual((await f).result,['fast']);assert.equal(fast.busy,false);assert.equal(ocr.busy,true);
 ocr.cancelPending();await assert.rejects(s,{name:'AbortError'});assert.equal(workers[1].terminated,true);
 fast.dispose();ocr.dispose();
});
test('cancelled work cannot block a new generation or publish a stale answer',async()=>{
 const client=new ScannerClient(1);const old=client.run(request());old.catch(()=>{});
 const before=workers[0];before.reply(ready);await tick();const oldId=before.posts[1].id;
 client.cancelPending();await assert.rejects(old,{name:'AbortError'});
 const current=client.run(request());const after=workers[1];after.reply(ready);await tick();
 before.reply({kind:'result',id:oldId,result:'stale'});assert.equal(client.busy,true);
 after.reply({kind:'result',id:after.posts[1].id,result:'current',ms:1,memoryBytes:4});
 assert.equal((await current).result,'current');assert.equal(client.busy,false);client.dispose();
});
test('post failures and unavailable workers settle pending requests',async()=>{
 const client=new ScannerClient(1);const work=client.run(request());workers[0].reply(ready);workers[0].throwPost=true;
 await assert.rejects(work,/post failed/);assert.equal(client.busy,false);client.dispose();
 globalThis.Worker=class{constructor(){throw Error('worker unavailable');}};
 const blocked=new ScannerClient(1);await assert.rejects(blocked.run(request()),/worker unavailable/);
 assert.equal(blocked.busy,false);blocked.dispose();
});
const watch=client=>{const events=[];client.onState=(state,error)=>events.push(error?[state,error.message]:[state]);client.onReady=r=>events.push(['ready',r.loadMs]);return events;};
test('an init error kills that worker and the next run starts a clean one',async()=>{
 const client=new ScannerClient(1);const events=watch(client);
 const first=client.run(request());const broken=workers[0];
 broken.reply({kind:'error',message:'models missing'});
 await assert.rejects(first,/models missing/);
 assert.equal(broken.terminated,true);assert.equal(client.busy,false);
 assert.deepEqual(events,[['loading'],['failed','models missing']]);
 const second=client.run(request());assert.equal(workers.length,2,'the retry starts a new worker');
 const retried=workers[1];
 retried.reply({...ready,loadMs:2});await tick();
 broken.reply({...ready,loadMs:99});broken.reply({kind:'error',message:'late'});
 const ids=retried.posts.filter(p=>p.kind!=='init').map(p=>p.id);assert.equal(ids.length,1);
 retried.reply({kind:'result',id:ids[0],result:'ok',ms:1,memoryBytes:4});
 assert.equal((await second).result,'ok');
 assert.deepEqual(events,[['loading'],['failed','models missing'],['loading'],['ready',2]]);
 client.dispose();assert.equal(events.length,4,'dispose reports nothing');
});
test('cancelling during init reports idle, not failed, and the next run loads again',async()=>{
 const client=new ScannerClient(1);const events=watch(client);
 const cancelled=client.run(request());const first=workers[0];
 client.cancelPending();await assert.rejects(cancelled,{name:'AbortError'});
 assert.equal(first.terminated,true);assert.deepEqual(events,[['loading'],['idle']]);
 first.reply(ready);first.reply({kind:'error',message:'late'});await tick();
 assert.deepEqual(events,[['loading'],['idle']],'the stopped worker is ignored');
 const next=client.run(request());const second=workers[1];second.reply(ready);await tick();
 second.reply({kind:'result',id:second.posts[1].id,result:'fresh',ms:1,memoryBytes:4});
 assert.equal((await next).result,'fresh');
 assert.deepEqual(events,[['loading'],['idle'],['loading'],['ready',1]]);
 client.dispose();
});
test('a failed init post or worker constructor reports failed and is retried',async()=>{
 const client=new ScannerClient(1);const events=watch(client);
 failNextInit=true;
 await assert.rejects(client.run(request()),/post failed/);
 assert.equal(workers[0].terminated,true);assert.equal(client.busy,false);
 globalThis.Worker=class{constructor(){throw Error('worker unavailable');}};
 await assert.rejects(client.run(request()),/worker unavailable/);assert.equal(client.busy,false);
 globalThis.Worker=WorkerMock;
 const ok=client.run(request());workers[1].reply(ready);await tick();
 workers[1].reply({kind:'result',id:workers[1].posts[1].id,result:'up',ms:1,memoryBytes:4});
 assert.equal((await ok).result,'up');
 assert.deepEqual(events,[['loading'],['failed','post failed'],['loading'],['failed','worker unavailable'],['loading'],['ready',1]]);
 client.dispose();
});
test('a crashed worker settles every request, reports failed once, and is replaced',async()=>{
 const client=new ScannerClient(1);const events=watch(client);
 const a=client.run(request()),b=client.run(request());const crashed=workers[0];crashed.reply(ready);await tick();
 crashed.onerror({message:'out of memory'});
 await assert.rejects(a,/out of memory/);await assert.rejects(b,/out of memory/);
 crashed.onerror({message:'again'});
 assert.deepEqual(events,[['loading'],['ready',1],['failed','out of memory']]);
 const ready2=client.ready;workers[1].reply(ready);assert.equal((await ready2).threads,1);
 client.dispose();
});
test('dispose during init settles requests without reporting a state',async()=>{
 const client=new ScannerClient(1);const events=watch(client);
 const work=client.run(request());client.dispose();
 await assert.rejects(work,/disposed/);await assert.rejects(client.ready,/disposed/);
 assert.deepEqual(events,[['loading']]);assert.equal(workers[0].terminated,true);assert.equal(workers.length,1);
});
