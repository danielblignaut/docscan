# Browser checks, 2026-10-23

These are headless Chrome regressions using synthetic camera clips and pages,
not real-phone, real-customer or certified security tests. The original
standalone `docscan` E2E expectations were retained.

`face-poa-single-thread.json`: final combined Rust pipeline (physical parallax
ON and improved passive PAD), six checks pass: two PoA captures, genuine face,
photo attack rejection, enrollment followed by verification, and camera exit.
The old municipal PoA fixture explicitly allows one OCR character to differ;
it read `76 Hill St` for `476 Hill St`. A passing E2E verdict does not establish
exact house-number accuracy.

`id-single-thread-initial.json`: passport and camera exit pass; the two-sided
smart-ID clip timed out at 90 seconds while another browser check also ran.
`id-original-component-baseline.json`: the original IdCapture component from
main, with the same current wasm/models, passes that clip in 37.2 seconds.
`id-candidate-retry.json`: the changed component passes in 56.3 seconds on a
separate run. Both show repeated green/grey resets before capture. The stable
front segment is only 2.2 seconds, while a single front OCR takes about 4.5
seconds. This is timing-sensitive evidence, not a demonstrated new scanner
regression; no acceptance threshold or timeout was loosened to make it pass.

`demo/e2e/text.mjs` also passed on both 1 and 2 wasm threads before the optional
PP-OCRv6 integration: small-print photo upload, current model loading despite
stale unversioned cache, hands-free capture, exactly one completion event,
released tracks, and cancellation while OCR is pending. Its fixtures are the
12-page synthetic DEV corpus from `eval/text_eval.py`. Later model-specific
checks are recorded separately.

The separately versioned v2 smart-ID E2E fixture repeats only the existing
held pixels (front 20 s/back 12 s). Original arrival frames, the v1 fixture,
benchmark manifests, capture acceptance and the 90 s timeout remain unchanged.
`id-v2-fixture.json` records source/output hashes and timeline;
`id-v2-single-thread.json` passes in 26.2 s, with both sides cross-checked.
This fixes test pacing for a slow reader, not scanner accuracy.

Final optional-model and navigation checks:

- `DOCSCAN_TEXT_ENGINE=ppocr_v6_tiny node e2e/text.mjs`: all four checks pass.
- Same with `DOCSCAN_TEST_THREADS=2`: all four pass.
- `node e2e/text.mjs` (default ocrs, one thread): all four pass.

The fourth check opens a barcode camera while a photo read is pending. It
observes the text worker response before verifying the newer camera remains.
A build with the original App component from `71d3869` fails that assertion;
`f15bcd5` passes it. The controller cancels publication on scanner navigation
and browser history changes, and disposes discarded result image URLs.

Representative final camera reads, on this desktop under shared load:

| Reader | Threads | Reader time | Allocated wasm memory |
| --- | ---: | ---: | ---: |
| PP-OCRv6 tiny | 1 | 5.41 s | 119,668,736 bytes |
| PP-OCRv6 tiny | 2 | 3.71 s | 123,928,576 bytes |
| ocrs page | 1 | 23.47 s including enhancement | 199,098,368 bytes |

These are smoke observations on the synthetic camera clip, not an interleaved
speed benchmark, total browser RAM, or phone measurements. Images/arrival
frames can differ between captures; no statistically established speedup is
claimed. Native exact-text accuracy uses the separate fixed 12-page corpus.
