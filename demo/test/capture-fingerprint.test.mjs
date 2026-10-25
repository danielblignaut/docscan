import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadPureModule} from './load-pure-module.mjs';
const {fingerprintCapture}=await loadPureModule(new URL('../src/capture-fingerprint.ts',import.meta.url));
test('capture fingerprint is deterministic, dimensioned and sensitive to the analysed pixels',async()=>{
 const a={width:2,height:2,data:new Uint8ClampedArray(16)};
 const first=await fingerprintCapture(a);assert.deepEqual(await fingerprintCapture(a),first);assert.equal(first.sha256.length,64);
 a.data[0]=1;assert.notEqual((await fingerprintCapture(a)).sha256,first.sha256);
 await assert.rejects(fingerprintCapture({...a,data:new Uint8ClampedArray()}),/Invalid/);
});
