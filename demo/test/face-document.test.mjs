import assert from "node:assert/strict";
import { test } from "node:test";
import { readDocumentFace } from "../src/face-document.ts";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
};

test("leaving while decoding document pixels prevents inference", async () => {
  const pixels = deferred();
  const controller = new AbortController();
  let calls = 0;
  const result = readDocumentFace("blob:document", () => pixels.promise, async () => { calls++; return { found: true }; }, controller.signal);
  controller.abort();
  pixels.resolve({});
  assert.equal(await result, null);
  assert.equal(calls, 0);
});

test("leaving during inference discards a late answer or rejection", async () => {
  for (const fail of [false, true]) {
    const inference = deferred();
    const controller = new AbortController();
    const result = readDocumentFace("blob:document", async () => ({}), () => inference.promise, controller.signal);
    await Promise.resolve();
    controller.abort();
    if (fail) inference.reject(new Error("worker failed after leaving"));
    else inference.resolve({ found: true });
    assert.equal(await result, null);
  }
});

test("an active read surfaces decoder and worker errors for retry", async () => {
  const signal = new AbortController().signal;
  const error = new Error("failed to read document");
  await assert.rejects(readDocumentFace("blob:document", async () => { throw error; }, async () => ({}), signal), error);
  await assert.rejects(readDocumentFace("blob:document", async () => ({}), async () => { throw error; }, signal), error);
  const face = { found: true };
  assert.equal(await readDocumentFace("blob:document", async () => ({}), async () => face, signal), face);
});
