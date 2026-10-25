# Label robustness: one bounded round on Fast serial preservation (DEV + fictional stress)

Whether one generic, bounded change to the Fast label reader
(`Scanner::labelled_fast_native`, PP-OCRv6 tiny) keeps more printed serials
without new false fields. Results and the verdict:
`docs/research-label-robustness.md`. One measured round; nothing was tuned
after it.

Everything private stays in the owner-only `/tmp/docscan-label-robustness`:
source snapshots, binaries, model copies, the stress corpus and its gold, and
run outputs. The probe prints decoded and printed values; the runners parse
them in memory and write only counts, timings and opaque frame or specimen
ids. No image, IMEI, serial or barcode value, and no TEST or reserved frame,
is read into or written by this directory. The user photo is read only if
the caller sets `USER_IMAGE` and `USER_REPORT`; no path is recorded.

## Files

- `diag.py` + `diag.rs`: the **pre-freeze diagnosis** (unpatched snapshot
  `d0`): classifies every DEV truth field the Fast reading misses. It ran
  before the arms were chosen, and informed the choice.
- `text_v6-candidates.patch`: applied to a snapshot's `src/text_v6.rs` only.
  Adds `PaddleTextScanner::dictionary` and `read_native_research` (detection
  as `read_native`; optional crop source; optional per-line rescoring hook).
  `read_native` itself is unchanged. **Not applied** to the shared crate.
- `probe.rs` → snapshot `examples/label_robustness_probe.rs`. Modes `fast`
  and `detailed` (the shipped APIs), `replica` (the patch with no change,
  for parity), `a-fullres`, `b-rescore` (the two arms; see `run.py`).
- `stress.py`: the fictional stress corpus (seed 5150, 30 specimens × clean,
  font, blur, perspective = 120 frames, 480 truth fields), its gold hashed
  and made read-only before any reader saw it.
- `prepare.py SNAP [--patched] [--probe=diag.rs]`: an immutable snapshot of
  the committed crate at HEAD (`git archive`), read-only model copies, a
  sha256 receipt.
- `run.py`: `freeze`, `accuracy`, `user`. The arms, corpora and gate are
  declared in its docstring; every phase verifies the freeze (binary,
  models, receipt, the stress gold and every stress frame) first.
- `test_run.py`: unit tests of the scoring (failed frames stay in the
  denominator; serial errors count misses and false serials).
- `evidence/`: the aggregate JSON copied from the private runs.

## Reproduce

```sh
PY=/tmp/docscan-bench/venv/bin/python
E=/tmp/docscan-label-robustness
# Diagnosis (pre-freeze)
python3 experiments/label_robustness/prepare.py d0 --probe=diag.rs
(cd $E/d0/src/docscan && CARGO_TARGET_DIR=$E/target cargo build --locked --release --example label_robustness_probe -j2)
cp $E/target/release/examples/label_robustness_probe $E/d0/target-bin
$PY -I experiments/label_robustness/diag.py d0
# Stress gold (frozen on write), then the measured snapshot
$PY -I experiments/label_robustness/stress.py $E/stress-5150
python3 experiments/label_robustness/prepare.py s1 --patched
(cd $E/s1/src/docscan && CARGO_TARGET_DIR=$E/target cargo build --locked --release --example label_robustness_probe -j2 \
  && CARGO_TARGET_DIR=$E/target cargo test --locked --release --example label_robustness_probe -j2)
mkdir -p $E/s1/bin && cp $E/target/release/examples/label_robustness_probe $E/s1/bin/
$PY -I experiments/label_robustness/run.py freeze s1
$PY -m unittest discover -s experiments/label_robustness -p test_run.py
$PY -I experiments/label_robustness/run.py accuracy s1      # 2 workers (CPUs 6,7), 1 thread each
# Optional, private: USER_IMAGE=… USER_REPORT=… $PY -I experiments/label_robustness/run.py user s1
```

`LABEL_ROBUSTNESS_CPUS` (default `6,7`) picks the pinned CPUs;
`RTEN_NUM_THREADS` and `RAYON_NUM_THREADS` are 1. DEV data: the benchmark's
materialised `barcode_synth_dev` (`BENCH_DATA`, default `/tmp/docscan-bench`).

## Run log (honest provenance)

- `d0`: unpatched HEAD `0526c5d` with `diag.rs`; `diag.py` ran twice (the
  second run added the by-size / character-class breakdown; same binary,
  identical totals). Fast reproduced 268/296 and 6 false fields.
- `t1`: a trial build of the patched snapshot, used only to compile, run the
  probe's unit tests, and smoke-run each mode on two DEV frames (timings,
  rescoring counters and replica-vs-fast hashes; no accuracy looked at). It
  was not frozen and its outputs are not used.
- `stress-5150`: generated once, gold frozen on write (`gold-receipt.json`).
  Three low-resolution previews were viewed privately to check that the
  conditions render, then deleted.
- `s1`: the measured snapshot. One `accuracy` round
  (`evidence/s1-accuracy-20261025T171928.json`), 0 probe failures, replica
  identical to Fast on all 192 frames. Its runs directory was created
  group-readable (the runner sets no umask) inside the owner-only `s1`; the
  output was made read-only after the copy. No arm was re-run or tuned.
- `user` (G7) was not run: no private handoff was supplied.
- The build target directory was seeded with a copy of
  `/tmp/docscan-label-speed-v2/target` (compiled dependencies only; cargo
  rebuilt the crate from each snapshot).
- The host carried other load (load average about 9 on 12 threads):
  timings are indicative, field results deterministic.
