import assert from "node:assert/strict";
import { test } from "node:test";
import { cosine, documentMatch, matchEnrolments, verificationPassed } from "../src/face-types.ts";

const model = "sface_int8";
const enrolled = (template, name = model) => ({ id: "demo", label: "Demo", template, model: name, createdAt: "" });
const photo = (template, name = model) => ({ found: true, template, model: name });

test("malformed templates cannot match, including an identical shorter prefix", () => {
  for (const [a, b] of [[[], []], [[1], [1, 0]], [[1, 0], [1]], [[0], [0]], [[NaN], [1]], [[Infinity], [1]]]) {
    assert.ok(Number.isNaN(cosine(a, b)));
    assert.equal(matchEnrolments(a, model, [enrolled(b)], 0.356), null);
    assert.equal(documentMatch(a, model, photo(b), 0.356), null);
  }
});

test("equal-dimensional embeddings from different models are incompatible", () => {
  assert.equal(matchEnrolments([1, 0], model, [enrolled([1, 0], "other")], 0.356), null);
  assert.equal(documentMatch([1, 0], model, photo([1, 0], "other"), 0.356), null);
});

test("valid matching and mismatching templates preserve their decision", () => {
  assert.equal(documentMatch([1, 0], model, { ...photo([1, 0]), found: false }, 0.356), null);
  assert.equal(documentMatch([1, 0], model, photo([2, 0]), 0.356).matched, true);
  assert.equal(documentMatch([1, 0], model, photo([0, 1]), 0.356).matched, false);
  const match = matchEnrolments([1, 0], model, [enrolled([NaN, 0]), enrolled([0, 1]), enrolled([1, 0])], 0.356);
  assert.equal(match.matched, true);
  assert.equal(match.others.length, 1);
});

test("completion cannot report success after a failed or missing comparison", () => {
  const match = documentMatch([1, 0], model, photo([1, 0]), 0.356);
  assert.equal(verificationPassed(true, match), true);
  assert.equal(verificationPassed(false, match), false);
  assert.equal(verificationPassed(true, { ...match, matched: false }), false);
  assert.equal(verificationPassed(true, null), false);
});
