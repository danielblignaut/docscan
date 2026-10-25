# Label speed v2: complete label readings, faster (DEV only)

Whether the full labelled reading (`Scanner::labelled`, ~24 s single-threaded
wasm on the user's 720 × 1280 photo) can be made faster **for the whole
frame**, without the bounded-ROI cropping that `experiments/barcode_latency`
rejected. Results and the recommendation: `docs/improvements-label-speed-v2.md`.

Everything private stays in the owner-only `/tmp/docscan-label-speed-v2`:
source snapshots, binaries, the wasm package, model copies, run outputs and
the decoded user photo (written to a temporary file per run and deleted).
The probe prints decoded and printed values; the runners parse them in memory
and write only counts, rates, timings, flags and opaque DEV frame ids. No
image, IMEI, serial, barcode value or TEST/reserved frame is read into or
written by this directory.

## Files

- `probe.rs` → snapshot `examples/label_speed_probe.rs`. Modes `full`
  (`labelled_native`'s stages re-timed; `--parity` checks byte-identical
  fields), `profile` (per-tile time split of the tiled reading), `once-tiles`,
  `once-page` (`docscan/src/label_speed.rs`, included by `#[path]`), `ppocr`,
  `ppocr-detail` (the existing `PaddleTextScanner`).
- `prepare.py SNAP [--patched]`: an immutable snapshot of the committed crate
  at HEAD (`git archive`; other agents' uncommitted edits never reach it), the
  owned files copied in, read-only model copies, a sha256 receipt; `--patched`
  applies `lib-integration.patch` to the snapshot's `lib.rs` (for wasm).
- `run.py`: `freeze` (pins binary / wasm package / models / receipt; refuses
  twice), `profile`, `accuracy`, `user`, `latency`, `threads`. Every phase
  verifies the freeze first, records the runner hashes, and writes
  `SNAP/runs/<phase>-<time>.json` with exclusive create (never overwritten).
  Candidates and the gate are declared in its docstring.
- `run_wasm.py` + `wasm_probe.mjs`: the patched single-threaded package in
  Node 24, `labelled` / `labelled_once` / `labelled_fast`, cold (fresh
  process) and warm.
- `lib-integration.patch`: `Scanner::load_label_reader`, `labelled_fast`,
  `labelled_once` (+ `_native`), sharing a private `labelled_with`. **Not
  applied** to the shared `lib.rs`.
- `api_check.rs` → patched snapshot `examples/label_speed_api.rs`: the
  patch's public `labelled_fast_native` (`run.py api`), compared in memory
  with the probe's `ppocr` mode; also checks an unloaded reader errors.
- `test_run.py`: unit tests of comparison, truth scoring (failed frames stay
  in the denominator) and the truth attribution of lost fields.
- `evidence/`: the aggregate JSON copied from the private runs.

## Reproduce

```sh
PY=/tmp/docscan-bench/venv/bin/python
E=/tmp/docscan-label-speed-v2
python3 experiments/label_speed_v2/prepare.py s2
(cd $E/s2/src/docscan && CARGO_TARGET_DIR=$E/target cargo build --locked --release --example label_speed_probe -j2)
mkdir -p $E/s2/bin && cp $E/target/release/examples/label_speed_probe $E/s2/bin/
$PY -I experiments/label_speed_v2/run.py freeze s2
$PY -m unittest discover -s experiments/label_speed_v2 -p test_run.py
$PY -I experiments/label_speed_v2/run.py accuracy s2          # 72 DEV frames, 2 workers (CPUs 4,5), 1 thread each
export USER_IMAGE=/path/to/private/photo.jpg USER_REPORT=/path/to/private/report.json   # never committed
$PY -I experiments/label_speed_v2/run.py user s2              # timing: 1 CPU, nothing else of ours running
$PY -I experiments/label_speed_v2/run.py latency s2           # paired, alternating order
$PY -I experiments/label_speed_v2/run.py threads s2           # 1 vs 2 threads
# Private wasm candidate
python3 experiments/label_speed_v2/prepare.py s3 --patched
(cd $E/s3/src/docscan && CARGO_BUILD_JOBS=2 CARGO_TARGET_DIR=$E/target-wasm \
  RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir $E/s3/pkg)
(cd $E/s3/src/docscan && CARGO_TARGET_DIR=$E/target cargo test --locked --release --lib label_speed -j2)
$PY -I experiments/label_speed_v2/run.py freeze s3
$PY -I experiments/label_speed_v2/run_wasm.py s3 user
$PY -I experiments/label_speed_v2/run_wasm.py s3 dev
```

`LABEL_SPEED_CPUS` (default `4,5`) picks the pinned CPUs; `RTEN_NUM_THREADS`
and `RAYON_NUM_THREADS` are both set (RTen sizes its own pool from the
former, ocrs's recognition uses rayon's). DEV data: the benchmark's
materialised `barcode_synth_dev` (`BENCH_DATA`, default `/tmp/docscan-bench`),
its 72 labelled frames.

## Run log (honest provenance)

- `s1`: build failed (missing trait import); discarded, never run.
- `s2` accuracy was run twice; the second run added the truth attribution
  (runner edited between runs, same frozen binary); aggregates are identical.
- `s2` `user`: a private diagnosis script was started on CPUs 4–5 during the
  phase and killed within about a minute; the full reading's **warm** median
  (19.5 s) is contaminated and not used — its cold runs (9.5 s, matching
  `docs/performance-barcode.md`) are. Field results are unaffected.
- `run.py` gained wasm-package freezing after the `s2` runs; each run records
  the runner hashes it actually used.
- `s3`: the patched wasm package (no native probe). `s4`: patched, with the
  probe and `label_speed_api`; `api` (73/73 identical), `threads`, and a
  cross-check that `s2` and `s4` `ppocr` fields are identical (72/72).
- `s4` `profile` ran but could not write its output (runs directories had
  been made read-only after the evidence copy); not used, not repeated.
- Watcher loops that used `pgrep -f` matched themselves; they were stopped and
  ran nothing but `sleep`.
- The host carried other users' load (load average ~6–23 on 12 threads)
  throughout: timings are indicative, ratios paired where stated.
