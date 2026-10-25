import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { transformWithEsbuild } from 'vite';
const path = new URL('../src/text-engine.ts', import.meta.url).pathname;
const { code } = await transformWithEsbuild(readFileSync(path, 'utf8'), path);
const { textEngineFromUrl, textRequest, financialEngineFromUrl } = await import(`data:text/javascript,${encodeURIComponent(code)}`);

test('small-print deep link selects bounded detailed reading', () => {
  const image = {};
  const engine = textEngineFromUrl('?textEngine=ppocr_v6_tiny_detail');
  assert.equal(engine, 'ppocr_v6_tiny_detail');
  assert.deepEqual(textRequest(engine, image), { kind: 'text_v6', detail: true, image });
});
test('standard and unknown links preserve existing reader choices', () => {
  const image = {};
  assert.deepEqual(textRequest(textEngineFromUrl('?textEngine=ppocr_v6_tiny'), image), {kind:'text_v6',detail:false,image});
  assert.deepEqual(textRequest(textEngineFromUrl('?textEngine=unknown'), image), {kind:'text_page',image});
});

test('brightness comparison is an explicit opt-in and retains the standard reader', () => {
 const image = {};
 assert.equal(textEngineFromUrl('?textEngine=ppocr_v6_tiny_exposure'), 'ppocr_v6_tiny_exposure');
 assert.deepEqual(textRequest('ppocr_v6_tiny_exposure', image), { kind: 'text_v6', detail: false, exposureCompare: true, image });
});

test('financial reader default is separate and retains explicit ocrs selection',()=>{
 assert.equal(financialEngineFromUrl(''),'ppocr_v6_tiny');
 assert.equal(textEngineFromUrl(''),'ocrs');
 assert.equal(financialEngineFromUrl('?textEngine=ocrs'),'ocrs');
 assert.equal(financialEngineFromUrl('?textEngine=ppocr_v6_tiny_detail'),'ppocr_v6_tiny_detail');
 assert.equal(financialEngineFromUrl('?textEngine=ppocr_v6_tiny_exposure'),'ppocr_v6_tiny');
});
