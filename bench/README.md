# bench: the benchmark harness

One referee for every scanner in this repository: identity documents,
barcodes, proof of address and face. It builds what is stale, materialises
fixed, versioned test sets, measures accuracy and speed, writes one JSON
result per run, and compares two results with significance tests and a
verdict.

```sh
bench/run.sh                         # every suite on DEV, the full sets
bench/run.sh --quick                 # every suite on fixed DEV subsets (smoke test)
bench/run.sh --suite poa             # one suite (id, barcode, poa, face; or a comma list)
bench/run.sh --suite id --e2e        # also the browser end-to-end suite (demo/e2e/run.mjs)
bench/run.sh --split test            # TEST / lockbox: for reporting only, see below
bench/compare.py bench/results/baseline-<sha>.json bench/results/<sha>-<ts>.json
```

Options: `--split dev|test|both` (default `dev`), `--quick`, `--e2e`,
`--no-wasm` (skip the headless-Chrome timings), `--no-cache` (recompute every
per-item result), `--repeats N` (timing repeats; default 5, 2 with `--quick`,
capped at 3 for the OCR-heavy timings), `--jobs N` (parallel processes for the
accuracy passes; default logical CPUs - 2), `--skip-prepare` (trust the data on
disk without checking hashes).

Requirements: Rust stable (and wasm-pack for the wasm timings; the nightly
under `/tmp/rustup-nightly` for the multithreaded wasm build, see
`docscan/build-threads.sh`), `uv`, Node 20+ with `demo/node_modules`
installed (playwright-core) and Google Chrome at `/usr/bin/google-chrome`.
Data lives in `$BENCH_DATA` (default `/tmp/docscan-bench`; keep the default:
two sets record absolute paths in their JSON, so their hashes assume it).

## The rules

### DEV is for tuning; TEST is for reporting only

Every suite has a DEV split and a TEST split, generated from different seeds,
holders, identities and (for proof of address) different layouts and fonts:

| Suite | DEV (tune on this) | TEST (never tune on this) |
|---|---|---|
| id | `id_stills` (testdata/camera), `id_hard_dev`, `id_clips` | `id_hard_test` |
| barcode | `barcode_synth_dev`, `barcode_public_dev` | `barcode_synth_test`, `barcode_public_test` |
| poa | `poa_dev` | `poa_lockbox` (eval/LOCKBOX.md) |
| face | LFW View 1, docpairs DEV, CelebA-Spoof DEV, liveness DEV | LFW View 2, docpairs TEST, CelebA-Spoof TEST, liveness TEST |

**Anyone improving a scanner must not tune on TEST.** That means: do not run
`--split test` (or `both`) while developing; do not open, view, list, or read
the TEST files, their truth, or TEST results to decide what to change; do not
choose a threshold, a constant, a rule or a training example because of a
TEST outcome; and do not generate more data with a TEST seed. Measure every
change on DEV. TEST is run once a change is final, to report it, and its
numbers go into the change's description as they are, good or bad. If a TEST
run exposes a bug, it may be fixed once (as eval/LOCKBOX.md did), and the
second TEST run is reported beside the first, never instead of it.

Every TEST run appends a line to `bench/results/TEST_ACCESS.log` (time, commit,
suites, user). Commit that log with the result: it is how a reviewer sees how
often TEST was looked at.

### The regression rule

`bench/compare.py A.json B.json` (A the reference, B the change) prints every
metric's delta and a verdict. A change is acceptable only if:

- **no accuracy metric regresses beyond its 95% confidence interval**: the paired
  bootstrap interval of B - A over the same items lies wholly below zero (for
  a higher-is-better metric), and the delta exceeds twice the metric's
  recorded run-to-run noise (`bench/noise.json`: one difference between two
  runs of the same commit, so a single draw of the noise); and
- **no speed metric regresses by more than 5%** (median per-item ratio B/A above
  1.05 after calibrating for the machine's speed at each run, with its
  bootstrap interval wholly above 1, and beyond twice the metric's noise), **unless an accuracy gain is explicit**: a speed regression is
  accepted only when some accuracy metric improved significantly *and* the
  change says so (pass `--accept-tradeoff`, and state the trade in the commit).

The verdict is `regressed` (exit status 1), `improved` or `no change`.
compare.py also warns when the referee changed (the bench code hash differs),
when a dataset changed (manifest hash), when the runs differ in `--quick`, and
when B was run with uncommitted changes. A scanner change must be judged by an
unchanged referee: **never change `bench/` in the same commit as a scanner**,
and never edit a manifest except to version a set deliberately (below).

Compare full runs with full runs. `--quick` results are smoke tests on
subsets; compare.py pairs them on shared items, but their intervals are wide.

### Hard to game

- Accuracy is scored on fixed items with exact ground truth; every metric that
  rewards accepting more is paired with one that punishes accepting wrongly
  (`accept_good` with `accepted_wrong` and `false_accept_bad`; `recall` with
  `false_decode_frames`; `genuine_accept` with `reject_<case>`; TAR with FAR).
- Each set is pinned by sha256 of every file; `run.sh` refuses data that does
  not match, and regenerates it from the repo's own generators and seeds.
- The shipped configuration is read from the source (the face recogniser,
  thresholds), so changing it is measured, never assumed.
- A hang or a crash cannot stall the referee: an item that prints nothing
  within its timeout (30 s for a barcode frame, 120-180 s for an OCR pass) is
  killed, one that kills its process (a panic) is noted, both are recorded as
  read-nothing, and the rest of the shard carries on.
- Results do not depend on `--jobs` or on which items share a process:
  Scanner::analyse remembers the orientation that last read (right for a live
  feed, wrong for a set of stills), so every ID still is scanned in a process
  of its own, and each clip's frames in order in one process. Two runs of the
  same binary give identical accuracy (bench/noise.json).
- Several harness runs may share `$BENCH_DATA` (one per worktree): caches are
  appended under a file lock and keyed by the binary's own bytes, so two
  binaries' results never mix, and temporary files are per process.
- Per-item outcomes are cached only by the bytes of the binary, the models and
  the item: any code change that changes a binary is re-measured in full.

## Layout

```
bench/
  run.sh               entry point: build, venv, data, measure
  bench.py             the driver: suites, result JSON, table
  compare.py           A vs B: deltas, significance, verdict
  report.py            run-to-run noise (noise.json) and BASELINE.md
  requirements.txt     the pinned Python environment (generators and scorers)
  lib/common.py        paths, hashing, manifests, sharded runs, caching, timing, metric records
  lib/stats.py         bootstrap, Mann-Whitney, LFW 10-fold, TAR@FAR, AUC, APCER/BPCER/ACER
  data/prepare.py      materialise and verify every set
  data/gen_id.py       the harder ID set
  data/gen_barcodes.py the synthetic multi-barcode set
  data/import_barcodes_public.py   zxing-cpp's real-world samples
  data/fetch_face.py   LFW, ID-photo pairs, CelebA-Spoof
  suites/{id,barcode,poa,face}.py  one module per scanner: run(ctx) -> metrics
  wasm/bench.mjs, wasm/worker.mjs  the wasm builds in headless Chrome
  manifests/*.json     one per set: files with sha256, generator, seed, licence
  results/             <git-sha>-<UTC time>[-quick].json, baseline-<sha>.json, TEST_ACCESS.log
  noise.json           per-metric run-to-run noise of the baseline
  BASELINE.md          the baseline table
```

## Metrics

Every metric has a kind. **rate**: a 0/1 outcome per item (stored, with the
item ids), the value its mean. **stat**: a statistic over per-item scores and
labels (stored), e.g. TAR @ FAR. **latency**: per-item median milliseconds
over repeated runs (stored). **info**: context, not judged. Names are
`<suite>.<set>.<metric>`; `better` says which direction is good.

**id** (`suites/id.py`; `examples/scan`, OCR on, the guide's crop, no expected
kind, as eval/eval.py):
`accept_good` (good frames accepted as the right kind), `false_accept_bad`
(bad frames accepted), `accepted_wrong` (good frames accepted with a wrong kind
or field), `fields_exact` (every field of every good frame, eval/eval.py's
normalisation), `mrz_pass` (passports: MRZ read with every check digit),
`by_kind` / `by_condition` (info); `clips.outcome_right` and
`clips.time_to_capture_s` (the fake-camera clips sampled at a fixed 4 fps,
captured at the second consecutive identical accepted reading with the outline
in view: deterministic); `speed.fast_ms` (outline, flatten, quality,
barcodes) and `speed.ocr_ms` (the OCR pass).

**barcode** (`suites/barcode.py`; `examples/scan --barcodes` and
`--labelled`): `recall` and `recall.<symbology>` (decodable truth codes read,
symbology and text exact), `all_codes` (frames with every decodable code
read), `false_decode_frames` (frames with a decode matching no truth),
`timeouts` (frames on which the decoder hung: no result within 30 s, counted
as nothing read; the baseline has one on DEV, a zxing-cpp sample that sends
rxing into an endless loop, which would freeze the browser's worker),
`crashes` (frames on which the decoder panicked, counted as nothing read; the
baseline has one on TEST, an rxing MaxiCode-detector panic, `min > max`, which in the
browser makes the call throw),
`precision` (judged unpaired: its items depend on the decoder),
`negatives_with_decode`, `labelled.value` / `labelled.label_value` /
`labelled.unread` (printed fields listed with the right value, and label;
fields whose bars are undecodable, read from print), `recall_by_condition`
(info); `speed.frame_ms`, `speed.labelled_ms`.

**poa** (`suites/poa.py`; eval/poa_capture_eval.py's two stages and
eval/poa_eval.py's scoring): per capture `genuine_accept`,
`reject_{wrong_person,wrong_address,old,issuer_decoy}`, `key_fields` (blind:
name, street, city, postal code and date all right), `field.<name>`;
`single.*` the same per single frame; `frames_read_mean` (info);
`speed.frame_ms` (one frame read: decode, outline, flatten, enhance, OCR,
rules, tagger) and `speed.capture_ms_est` (info: frame_ms x frames read).

**face** (`suites/face.py`; `examples/face`, the shipped recogniser and
thresholds read from demo/src/face-models.ts and docscan/src/face/mod.rs):
`lfw_{dev,test}.acc10` (10-fold accuracy; View 2's folds on TEST),
`.tar_far1e-3`, `.tar_far1e-2`, `.tar_at_shipped`, `.far_at_shipped`;
`docface_{dev,test}.*` (ID photo vs live face, the same statistics at
DOC_THRESHOLD); `antispoof_{dev,test}.auc`, `.acer`, `.apcer`, `.bpcer`
(CelebA-Spoof at 0.5, the session's threshold); `liveness_{dev,test}.bpcer`,
`.apcer.<species>`, `.apcer_all`, `.acer_worst` (info); `speed.liveness_frame_ms`.

**wasm** (`wasm/`; headless Chrome, the scanner in a module Worker as the demo
runs it): `wasm.single.*` for the single-threaded build (what GitHub Pages
serves) and `wasm.threadsN.*` for the multithreaded one (N = min(8, cores);
not in `--quick`): `barcodes_ms`, `id_fast_ms`, `id_ocr_ms`, `poa_page_ms`,
`face_track_ms`, each a per-image median of `repeats` calls after a warm-up,
on a small fixed DEV subset.

**e2e** (`--e2e`): `e2e.pass` (demo/e2e/run.mjs cases passing) and
`e2e.cases` (info: capture times from the clip's start, per-frame browser
timings). The cases need the clips under testdata/video (README, Test data).

### Speed, and the shared machine

Speed is measured in its own pass, never during the parallel accuracy runs:
one process at a time, pinned (`taskset`) to the logical CPU that was idlest
over half a second, with `RAYON_NUM_THREADS=1` **and `RTEN_NUM_THREADS=1`**
(rten keeps its own thread pool, sized to the physical cores, which
RAYON_NUM_THREADS alone does not limit: the README's earlier "one core" OCR
figures were in fact multithreaded), each item repeated and its median kept.
Every latency records the CPU, the repeats, the load average before and
after, and `calib_ms`: a fixed CPU-bound job (sha256 of 64 MiB in tmpfs) timed
on the same core before every repeat and after the last. compare.py divides
latency ratios by the ratio of the two runs' `calib_ms`, so a run on a busier
machine is not read as a slower scanner; it also warns when the runs' load
differed by more than a factor of two, because contention (a busy hyperthread
sibling, memory bandwidth) does not scale every workload alike. Other users' jobs load this machine (a 6-core, 12-thread Xeon E5-1650
v3); compare latencies measured at similar load, and look at the noise floor in
BASELINE.md before believing a small speed change.

## Datasets

All sets are materialised under `$BENCH_DATA` by `bench/data/prepare.py`
(run.sh calls it), verified file by file against `bench/manifests/<set>.json`.
Nothing here is committed: no image, video, dataset, face or template; the
manifests hold paths, hashes (written in a digit-free base-10 alphabet, see
`digest_encoding`, because the repository's privacy check greps for digit
runs), sizes, generator scripts with their hashes, arguments, seeds, package
versions and licences.

| Set | Split | What | Source / licence |
|---|---|---|---|
| `id_stills` | DEV | testdata/camera: 5 kinds x (6 good + 3 bad) stills, seed 7 | testdata/synth.py + augment.py; synthetic |
| `id_clips` | DEV | the browser tests' fake-camera clips (5 kinds 960x540, smart ID back 1280x720) | testdata/make_videos.py; synthetic |
| `id_hard_dev` / `_test` | DEV / TEST | 6 fictional holders x 5 kinds x (14 good + 4 bad conditions): tilt to 35 deg, sideways, upside down, small, 640-wide frames, blur, dim, overexposed, glare, shadow, JPEG 25-40; seeds 1000 / 2000 | bench/data/gen_id.py; synthetic |
| `barcode_synth_dev` / `_test` | DEV / TEST | 300 frames each, ~950 codes: 13 symbologies, modules 0.5-6 px, rotation to 360 deg, perspective, blur, low contrast, damage, inverted, 1-8 codes per frame, labelled stickers (labels above, below, left; unreadable bars), negatives; seeds 101 / 202 | bench/data/gen_barcodes.py; synthetic |
| `barcode_public_dev` / `_test` | DEV / TEST | zxing-cpp's test samples (640 images, 642 codes; phone photos, scans and clean symbols), split by payload | github.com/zxing-cpp/zxing-cpp @ 2c3dcfe, **Apache-2.0** |
| `poa_dev` | DEV | 200 captures x 4 frames of the 3 held-out layouts (README) | testdata/poa_*.py; synthetic; GeoNames CC BY 4.0 |
| `poa_lockbox` | TEST | 200 captures x 4 frames, 4 lockbox-only layouts (eval/LOCKBOX.md) | as above; fonts SIL OFL / UFL |
| `face_lfw` | DEV + TEST | 13 233 images; View 1 minus View 2 (2 442 pairs) and View 2 (6 000, 10 folds) | LFW via Hugging Face mirrors (pinned revisions); research use, no licence; never committed |
| `face_docpairs_dev` / `_test` | DEV / TEST | each LFW pair's first face printed on a fictional ID, captured (face/eval/document.py) | derived from LFW |
| `face_celeba_dev` / `_test` | DEV / TEST | 3 000 / 6 000 images (1 068 / 1 533 live), face/eval/antispoof.py's samples | CelebA-Spoof via Hugging Face; **non-commercial research only**; never committed |
| `face_liveness_dev` / `_test` | DEV / TEST | 80 / 110 clips: bona fide, photo, curved photo, screen replay, 2-D video, partial sweep | face/synth/clips.py; procedural heads, no real person |

Not used, and why: the Muenster BarcodeDB (non-commercial; its host no longer
answers and no archive holds the zip), the ArTe-Lab 1D sets (site offline, no
licence stated, not archived), the Dubská/Herout QR sets (host gone, no
licence, not archived), BarBeR (account and agreement needed; partly
decoder-generated truth); and for face, everything face/DATASETS.md lists as
needing a signed agreement.

Regenerating a set must reproduce its bytes; every set did on this machine
(the ID stills, clips and the proof-of-address frames also byte-for-byte equal
to the copies the earlier evals used). If one stops doing so (a new library
version, a changed generator, an upstream download that moved), `run.sh`
stops with an error rather than measure on different data. To version a set
deliberately: change its generator or seed, run
`bench/data/prepare.py --sets <name> --write-manifests`, and commit the new
manifest alone, with a new baseline measured on it.

## Adding a metric

1. In the suite's module, compute per-item outcomes and return them through
   the record constructors in `lib/common.py`: `m_rate(ids, oks, desc=...,
   better=...)` for anything that is a proportion of items; `m_stat(stat,
   raw, params, ...)` for a statistic over scores and labels (add the
   function to `lib/stats.py`'s `STATS` so compare.py can bootstrap it);
   `m_latency(timed_runs(...), ...)` for a time, measured in a separate
   pinned pass; `m_info` for context.
2. Name it `<suite>.<set>.<metric>`, say in `desc` exactly what is counted,
   and set `better`.
3. Keep items fixed: a metric whose denominator depends on the scanner's own
   output (like barcode `precision`) cannot be compared paired; pair it with
   one over fixed items.
4. A new metric changes the referee: commit it on its own, rerun the
   baseline (twice, for the noise), and update BASELINE.md and noise.json.

A new set: a generator or importer under `data/`, an entry in
`prepare.py`'s `SETS`, a manifest via `--write-manifests`, and a row above.

## Runtimes

On this machine (6 cores / 12 threads, shared with other users' jobs; see
BASELINE.md for the load during each run):

- `--quick`, all suites on DEV, nothing cached: about 6-8 minutes; again with
  unchanged binaries (accuracy cached, speed always remeasured): about 3
  minutes.
- Full DEV run, nothing cached: see BASELINE.md (dominated by proof-of-address
  OCR: 800 frames at ~10 s each single-threaded).
- Full `--split both` with `--e2e`: see BASELINE.md.

Per-item results are cached under `$BENCH_DATA/cache/` by the bytes of the
binary, the models and the item, so after a change to one scanner the others'
accuracy passes are skipped whenever their binaries come out identical.

## What is not measured, and why

- **Phones.** Every time here is this Xeon, natively or in headless Chrome.
  Real phones are slower (face/RESULTS.md estimates 2-4x the single-threaded
  browser figures); nothing here measures one.
- **Real documents and faces.** Every ID, barcode label and proof-of-address
  page is synthetic; the only real images are LFW and CelebA-Spoof faces and
  zxing-cpp's barcode photos. Real passports and a device label were checked by
  hand earlier (README) and cannot be in a shared benchmark.
- **Face benchmarks behind agreements** (CFP-FP, AgeDB, IJB-B/C, OULU-NPU,
  SiW, CASIA, Replay-*): not run, see face/DATASETS.md. Liveness APCER/BPCER
  is on synthetic clips only; CelebA-Spoof has no spoof-type labels, so its
  APCER is over all types.
- **Browser time-to-capture** is only in `--e2e` (a fake camera, timing-
  dependent); the default suite's clip metric samples clips at a fixed rate.
- **The multithreaded wasm build** needs a nightly toolchain; when it is
  missing or fails to build, only the single-threaded build is timed.
