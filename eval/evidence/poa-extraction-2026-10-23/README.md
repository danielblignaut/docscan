# PoA extraction DEV evidence

This compares the recovered PoA work at `e5c9cc7` with the extraction fixes
committed in `1c2bb4c`. **Before is the existing recovered WIP**, including
`5600741` and `ea2a0e8`; it is not main, the original scanner, or a competing
product. Both runs use the same 200 DEV captures and 800 frozen OCR frames.
No TEST data or reports were consulted.

The `before.json` and `after.json` metrics come from the unchanged
`bench/suites/poa.py` scorer and contain per-item outcomes. These are real
extraction runs, not a copy of a headline score. The before timestamp is the
saved extraction output's completion time; the original full DEV OCR run's
provenance is recorded separately under `frozen_ocr`. After was measured from
the working tree before committing; its `git_sha`/`git_dirty` retain that fact,
and `source_revision` identifies the resulting source commit. No model or
benchmark thresholds changed.

| Metric | Before | After |
| --- | ---: | ---: |
| All blind key fields correct | 182/200 | 184/200 |
| Document date correct | 193/200 | 196/200 |
| Genuine captures accepted | 99/100 | 99/100 |
| Each negative class rejected | 25/25 | 25/25 |
| Single-frame key fields correct | 563/800 | 563/800 |
| Mean frames read | 2.83 | 2.85 |

All remaining accuracy metrics are unchanged. The paired 95% intervals include
zero: key fields +1.0 percentage point, CI [0, 2.5]; document date +1.5 points,
CI [0, 3.5]. `bench/compare.py` reports **no statistically significant change**.
The small gains do not establish state-of-the-art performance. This check does
not rerun page detection, OCR, or browser latency and cannot establish real
customer-document accuracy or document authenticity.

## Reproduce

Use the pinned Python environment at `/tmp/docscan-bench/venv`. The dedicated
script accepts no dataset/split parameter; it verifies only manifest-listed
`poa_dev` files, selects OCR records by their DEV frame hashes, and validates
the selected records' digest before running inference. Its default cache is
`/tmp/docscan-bench/cache/poa_ocr/dc79fff5b208264102ee.jsonl`. The cache is local
and is not bundled in git. Missing or altered records fail closed; the script
never silently reruns OCR or substitutes a different cache.

The JSON provenance records the frozen OCR binary/model hashes and the selected
records' digest. Digests use the benchmark's letter encoding (see
`bench/lib/common.py`). BENCH_DATA may relocate the cache and DEV data together.

```sh
/tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py --validate-only
```

Build `poa_capture` at each source revision in its worktree, with
`CARGO_BUILD_JOBS=2 cargo build --release --example poa_capture`. Then run the
script from this evidence checkout, pointing DOCSCAN_EXAMPLES at the built
reference or changed binary. `--source-revision` is explicitly a caller
assertion; the script records the binary's actual digest as well.

```sh
DOCSCAN_EXAMPLES=/path/to/before/docscan/target/release/examples \
  /tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py \
  --source-revision=e5c9cc7 --out=/tmp/poa-before.json
DOCSCAN_EXAMPLES=/path/to/after/docscan/target/release/examples \
  /tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py \
  --source-revision=1c2bb4c --out=/tmp/poa-after.json
/tmp/docscan-bench/venv/bin/python bench/compare.py \
  /tmp/poa-before.json /tmp/poa-after.json --only poa.dev --all
```

The committed evidence can be compared without running inference:

```sh
/tmp/docscan-bench/venv/bin/python bench/compare.py \
  eval/evidence/poa-extraction-2026-10-23/before.json \
  eval/evidence/poa-extraction-2026-10-23/after.json --only poa.dev --all
```
