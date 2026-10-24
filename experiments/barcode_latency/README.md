# Barcode photo latency experiment (DEV only)

Why the demo's barcode photo took ~22 s, and whether reading print only near
the bars (bounded ROI OCR) can cut it without losing fields. Verdict: it
cannot on the DEV labelled frames; the candidate is research only. Results and the
recommendation are in `docs/performance-barcode.md`; this directory holds the
probe, the runner and the aggregate evidence.

Everything private stays in the owner-only `/tmp/docscan-barcode-latency-v1`:
the HEAD source snapshot, binaries, the wasm package, per-frame outputs and the
decoded user photo. The probe prints decoded and printed values; `run.py` and
`run_wasm.py` parse them in memory and write only counts, rates, timings and
opaque DEV frame ids. No image, IMEI, serial, barcode value or TEST/reserved
frame is read into or written by this directory.

## Files

- `probe.rs`: native probe, copied into the snapshot as
  `examples/latency_probe.rs`. Modes: `raw` (`barcode::read_all`), `full`
  (`labelled_native`'s stages, re-timed; `--parity` checks the fields are
  byte-identical to `labelled_native`), `roi` (planned crops read in tiles) and
  `mosaic` (planned crops packed onto shared 600 × 800 canvases, one detection
  pass per canvas). It includes `docscan/src/label_regions.rs` by `#[path]`.
- `prepare.py`: snapshots the committed crate at HEAD (`git archive`) and copies
  in the two owned files, with a sha256 receipt.
- `run.py`: `user`, `calibrate`, `freeze`, `evaluate`, `latency` phases.
  Variants, the selection rule and the promotion gate are declared at the top.
- `run_wasm.py` + `wasm_probe.mjs`: single-threaded wasm in Node, cold (fresh
  process) and warm.
- `lib-integration.patch`: the `Scanner::labelled_near_bars(_native)` entry
  point applied to a private copy of `lib.rs` for the wasm build. Research
  only and **not applied**: the candidate failed its gate, the shared `lib.rs`
  is not edited and `label_regions.rs` is not declared in it.
- `test_run.py`: unit tests of the runner's comparison and scoring.
- `evidence/`: the aggregate JSON results (`calibration`, `frozen`,
  `evaluation`, `user`, `wasm`, `latency`), `report-parity.json` (the
  one-shot private comparison with the user's 22 s browser report: flags only)
  and `provenance.json` (HEAD, file, model and binary sha256). `wasm.json` is
  the one completed wasm run; it shared the host with other load (see the doc).

## Reproduce

```sh
python3 experiments/barcode_latency/prepare.py
E=/tmp/docscan-barcode-latency-v1
CARGO_TARGET_DIR=$E/target cargo build --locked --release --example latency_probe -j2 \
  --manifest-path $E/src/docscan/Cargo.toml
mkdir -p $E/bin && cp $E/target/release/examples/latency_probe $E/bin/
# Private wasm candidate: a copy of the snapshot with the patch applied.
cp -a $E/src $E/src-cand && cp docscan/src/label_regions.rs $E/src-cand/docscan/src/
patch -d $E/src-cand -p1 < experiments/barcode_latency/lib-integration.patch
(cd $E/src-cand/docscan && CARGO_BUILD_JOBS=2 CARGO_TARGET_DIR=$E/target-wasm \
  RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir $E/pkg-cand)
CARGO_TARGET_DIR=$E/target cargo test --locked --release --lib label_regions -j2 \
  --manifest-path $E/src-cand/docscan/Cargo.toml
PY=/tmp/docscan-bench/venv/bin/python
$PY -m unittest discover -s experiments/barcode_latency -p test_run.py
$PY -I experiments/barcode_latency/run.py calibrate   # accuracy, 2 workers
$PY -I experiments/barcode_latency/run.py freeze      # refuses if already frozen
$PY -I experiments/barcode_latency/run.py evaluate    # accuracy, 2 workers
export USER_IMAGE=/path/to/private/photo.jpg            # never committed
$PY -I experiments/barcode_latency/run.py user        # timing, one CPU, nothing else running
$PY -I experiments/barcode_latency/run_wasm.py        # timing, one CPU
$PY -I experiments/barcode_latency/run.py latency     # timing, one CPU
```

Run accuracy and timing phases separately; timing phases pin one CPU
(`BARCODE_LATENCY_CPU`, default 3) and set `RAYON_NUM_THREADS=1`. The DEV data
is the benchmark's materialised `barcode_synth_dev` (`BENCH_DATA`, default
`/tmp/docscan-bench`), its 72 labelled frames only; calibration reads the even
index, the held-out evaluation the odd index.
