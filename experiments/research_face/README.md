# Face research loop, 24 October 2026

Research-only, DEV-only. This directory owns its programs/configuration/results;
shipping code and the common benchmark referee remain unchanged. Primary-source
survey and decisions: `docs/research-2026-face.md`.

`protocol-v1.json` freezes four temporal fusion candidates before measurement.
The baseline data were already known: none of 765 sampled replay frames crossed
the raw shipped thresholds. This is explicitly **not a blinded experiment**.
The new question is whether temporal/quality fusion is feasible and whether it
raises attack margins; convex fusion cannot improve a zero-error attack-only set.
No second candidate search or threshold optimization follows the results.

The runner reuses the original frozen native inference, verifies source media,
model and derived-frame hashes against the original report, and freshly decodes
the five permitted videos for a capture blur diagnostic. It does not infer with
a concurrently rebuilt shared executable. The original executable hash and cache
hashes remain in provenance. These are **cached model inference + fresh pixel
processing**, not a new native model run. No compile is needed.

The central-half-frame sharpness proxy is intentionally cheap and local-browser
implementable, but is not face-localized or learned recognition utility. It can
measure screen/background edges. Its inadequacy is part of this feasibility
experiment, not a claim to reproduce a FIQA method.

Run with the existing local environment:

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover -s experiments/research_face -p 'test_*.py' -v
/tmp/docscan-bench/venv/bin/python experiments/research_face/temporal_quality.py
```

The runner snapshots itself and the config, writes a freeze receipt **before**
reading score arrays, and retains private per-frame/per-clip numeric results in
`/tmp/docscan-public-data/research-face/<config-and-runner-hash>/`. Source frames
stay in memory; no media, embeddings, identity-indexed scores or raw text goes
into git. Public JSON reports contain aggregates/denominators and hashes only.
Invalid inputs abort instead of changing denominators. Reruns refuse to overwrite
an existing report. Private caches are read-only; all new private output belongs
to this experiment. Unknown identity/device overlap precludes independent-trial
confidence claims. No actual active session, genuine temporal BPCER, rPPG ground
truth, or APCER at fixed BPCER is available in the owner preview.


## Second track: one bounded matching hypothesis

`matching_protocol_v1.json` freezes exactly one candidate against the historical
production-pair proxy: gamma 0.8/1.0/1.2 document embeddings, individually normalized,
equally averaged and normalized again, with the unflipped smile reference unchanged.
It retains original, gray384 and gray192, and adds a predeclared 96-pixel low-contrast
JPEG condition. Both production thresholds, 0.356 and 0.366, remain fixed. Both
51-person DEV halves keep their identities grouped; neither fits anything. No TEST.

The run froze at **2026-10-24 14:30:34.710631 UTC**. Private build source snapshots
reproduced the historical native executable exactly, allowing read-only reuse of
408 corresponding baseline/reference rows. Another 918 rows were inferred fresh
using one executable snapshot and at most two single-threaded native jobs. All four
conditions and both arms retain 51 genuine and 2,550 impostor pairs per split,
including no-detection rejections; the candidate requires all three views.

At document 0.356, hard96 TAR changes **3→4/51 calibration, 7→8/51 validation**;
FAR remains **0/2,550** in both. Easier conditions keep 51/51 TAR. The primary
predeclared descriptive criterion is met, but live 0.366 exposes an adverse gray384
calibration FAR change **5→6/2,550**. Hard96 genuine acceptance remains extremely
poor. This is a small source-specific result, not a production recommendation or
an independent-device/real-document/SOTA claim. Full conditions, actual FAR,
paired transitions, limitations and primary citations are appended to
[`docs/research-2026-face.md`](../../docs/research-2026-face.md).

New files owned by this track:

- `matching_photometric.py`: frozen runner, no threshold fitting or shared writes.
- `matching_protocol_v1.json`: candidate, degradation, denominator and decision rules.
- `matching_test.py`: nine synthetic correspondence/normalization/failure tests.
- `matching_audit.py`: independent retained-artifact accounting and float64 fusion check.
- `results/matching_photometric_v1.json`: all 32 aggregate operating-point cells.
- `results/matching_audit_v1.json`: passing hash/privacy/correspondence/accounting audit.

Validation (nine new tests plus 24 existing tests; no source captures used by tests):

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/research_face -p matching_test.py -v
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/public_face -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_face/matching_audit.py
```

Completed inference command (intentionally refuses to overwrite its frozen run or
report; use the audit above to recheck this completed run without new inference):

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/docscan-bench/venv/bin/python \
  experiments/research_face/matching_photometric.py \
  --binary /tmp/docscan-public-data/research-face/matching_build_v1/target/release/examples/face \
  --build-receipt /tmp/docscan-public-data/research-face/matching_build_v1/source_receipt.json
```

Biometric outputs, derived images, all pair scores and embeddings are owner-private
in `/tmp/docscan-public-data/research-face/matching_87e3a38cfcf61c818f8f/`. The full
source/build and run provenance are hashed in the aggregate report. Original
first-track files/reports, historical caches, shipping sources and weights remain
unchanged. No commits, training, calibration, new models or further candidate search.
