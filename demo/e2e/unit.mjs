// Checks of the page's pure helpers (src/types.ts), without a browser:
// node e2e/unit.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { transformWithEsbuild } from "vite";

const path = new URL("../src/types.ts", import.meta.url).pathname;
const { code } = await transformWithEsbuild(readFileSync(path, "utf8"), path);
const { crossCheck, readingKey } = await import(`data:text/javascript,${encodeURIComponent(code)}`);

const id = (value) => ({ value, luhn_valid: true, date_valid: true });
const front = (value) => ({ result: { kind: "za_smart_id_front", accepted: true, printed: { id_number: id(value), surname: "TESTERSON", names: "ZANELE" } } });
const back = (value, viaCode39 = false) => ({
  result: viaCode39
    ? { kind: "za_smart_id_back", smart_id_barcode: null, id_barcode: id(value) }
    : { kind: "za_smart_id_back", smart_id_barcode: { id_number: id(value) }, id_barcode: null },
});

assert.deepEqual(crossCheck([front("9003141234083"), back("9003141234083")]), { front: "9003141234083", back: "9003141234083", match: true });
// A mismatch is reported, whichever barcode the back's number came from.
assert.deepEqual(crossCheck([front("9003141234083"), back("8001015009087")]), { front: "9003141234083", back: "8001015009087", match: false });
assert.equal(crossCheck([front("9003141234083"), back("8001015009087", true)]).match, false);
// A front whose number was not read never matches.
assert.equal(crossCheck([{ result: { kind: "za_smart_id_front", printed: {} } }, back("9003141234083")]).match, false);
// Only both sides together are cross-checked.
assert.equal(crossCheck([front("9003141234083")]), null);
// Readings without the names do not match readings with them.
const book = (names) => ({ kind: "za_green_book", accepted: true, printed: { id_number: id("7511025731083"), surname: "VAN DER SPECIMEN", names } });
assert.notEqual(readingKey(book(null)), readingKey(book("JOHANNES PIETER")));
console.log("unit: ok");
