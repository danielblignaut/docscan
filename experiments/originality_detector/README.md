# Experimental document recapture detector

Independent NumPy/OpenCV features, two regularized logistic heads, held-out
negative calibration, exportable JSON models, fixed-denominator evaluation, and
explicit abstention. This is an implemented **research detector**, not an issuer
originality check. Positive means `copy_indicated`; everything else is `unknown`.
`confidence` is always null. A model score is not a calibrated probability.

Read [the research report](../../docs/research-originality-detector.md) for results,
source-split caveats, the aborted first acquisition, and promotion restrictions.
No shipping Rust module is edited here. No third-party implementation or pretrained
weights were copied. No raw pixels, identities, features, per-item predictions,
trained weights or annotations belong in git.

## Reproduction

The existing benchmark environment has NumPy 2.5.4, OpenCV 5.0.0.93 (package
version) and Pillow 12.3.0. CPU only, OpenCV and BLAS one thread each. Use new output
directories: writes are exclusive and interrupted attempts must be retained.

```sh
PY=/tmp/docscan-bench/venv/bin/python
OPENBLAS_NUM_THREADS=1 "$PY" -m unittest discover -s experiments/originality_detector -p 'test_*.py'
OPENBLAS_NUM_THREADS=1 "$PY" experiments/originality_detector/fetch_train_only.py --output /tmp/originality-source-train-new
OPENBLAS_NUM_THREADS=1 "$PY" experiments/originality_detector/receipts.py /tmp/originality-source-train-new --seal
OPENBLAS_NUM_THREADS=1 "$PY" experiments/originality_detector/real_study.py --data /tmp/originality-source-train-new --output /tmp/originality-real-new
OPENBLAS_NUM_THREADS=1 "$PY" experiments/originality_detector/study.py --protocol experiments/originality_detector/protocol-small.json --output /tmp/originality-synthetic-new
```

`fetch_train_only.py` reads only the author's `screen_positive_train.lst` and
`screen_negative_train.lst` from Zenodo's baseline archive. Pixels are allowed
only by exact membership in those lists. It uses ZIP HTTP ranges for DLC and
512-byte TAR headers plus FTP REST for MIDV-2020. Source TEST lists and their
pixels/truth are not opened. Directory metadata is inspected to locate selected
members. FTP hashes freeze bytes received, not authenticated publisher identity.
Per-member ZIP CRC, local SHA-256, source receipts and pre/post inference guards
are retained. All raw artifacts use umask 077 and owner-private directories.

**Do not run `fetch_dlc.py` for an experiment.** It is retained as the historical
failed importer: its broad source-type selection was not verified against author
TRAIN splits. The original attempt was interrupted before decoding/inference,
quarantined and excluded from every result. `real_study.py` rejects its manifests.
The historical source snapshot and precise acquisition receipt remain private.
The CLI refuses execution; it cannot repeat the unsafe broad import.

## Experiment design

`protocol.json` fixes synthetic seeds, groups, nuisance conditions, fitting and
threshold settings. The importer separately fixes real-data policy before media
access. Four candidate feature sets plus constant abstention are retained:

- `chroma_frequency`: global red–green variation, gradients/high-pass residuals,
  and spectral concentration. This tests the weak cue implicated by the earlier
  rejected periodicity experiment, with learned weights rather than a hard rule.
- `texture_color`: adds achromatic texture, saturation, darkness and luminance
  spectrum to test whether chroma alone is the problem.
- `boundary_context`: adds separately measured inside/outside features and
  spectral overlap. Only the synthetic/full-frame experiment supports it;
  author-labelled patch data cannot evaluate document-boundary evidence.
- `native_patch_texture`: samples unresized document patches to avoid destroying
  fine recapture artifacts. In the real study every arm starts with the same
  author-centred 224-square, while this arm measures it before downsampling.
- `constant_unknown`: zero copy warnings, zero detected attacks, all abstentions.

The original full synthetic protocol has 60 fit, 60 calibration and 40 DEV specimens,
14 conditions each. Its interrupted runs are retained; the completed bounded
protocol (`protocol-small.json`) uses 24/16/20 groups with all 14 conditions. All derivatives of one specimen remain together; simulated
camera profile seeds are also separate. Graphics include security linework,
monochrome, legitimate halftones, looped handwriting-like marks, glare, dim light,
JPEG, chromatic/achromatic screen artifacts and print surrogates. `print_clean`
is deliberately byte-identical to `plain`: a method cannot distinguish the
history of identical observations. These are procedural surrogates, not a
validated physical renderer or a study of human signatures or biometrics.

The real study is **screen-only**. Source TRAIN rows are internally separated by
whole specimen, phone and display model. Calibration shares the training phone
but holds out specimens. No real print classifier or original verdict is claimed.
The absent print head is fixed at logit -40 rather than trained from nonexistent
positives. The 18 existing MIDV-500 DEV frames are a separate negative-only check
in the synthetic-model study; they never train or calibrate a classifier.

For each trained head, the threshold is the larger of log(9) and the maximum
held-out bona-fide calibration logit; decisions use strict `>`. This gives zero
observed calibration false warnings, **not** a false-positive-rate guarantee or
probability calibration. The two-head synthetic rule is an OR and must be
assessed jointly. No thresholds, weights or candidate selection depend on DEV.
Every candidate is reported, even fitting/feature failures. Failure means unknown
and remains an attack miss or negative abstention in its original denominator.
Correlated frames do not create independent identities. Binomial zero-error
bounds on group counts are descriptive and share-device dependence remains.

## Model/input integration contract

`detector.py` defines feature version `optics-features-v1` and the exact ordered
51-name feature vector. JSON exports contain feature names, selected indices,
training means/scales, two weight rows/biases, thresholds, scope, provenance and
`deployment_validated: false`. No pickle, GPU dependency or opaque model runtime.

For a real-study model call `assess_patch(model, rgb_uint8, [cx, cy],
allow_experimental=True)`. It uses an in-bounds 224×224 native RGB crop, no warp,
then the exported scaler and dot product. The full-frame synthetic models use
`assess(model, rgb_uint8, quad, allow_experimental=True)`. Context/native-document
variants require a valid convex four-corner polygon; global variants do not.
Transparent, too-small, nonfinite or unsupported inputs abstain. The CLI rejects
nonopaque alpha. To inspect a real model:

```sh
"$PY" experiments/originality_detector/detector.py /private/run/native_patch_texture.model.json /private/image.jpg --centre '[640,960]' --allow-experimental
```

Without explicit experimental opt-in, these unvalidated model exports abstain.
This is an integration safeguard, not the measured operating policy: evaluation
runs the real positive/unknown decisions with experimental mode enabled. Always
serialize `is_copy: null` for unknown; never turn a low score into `false` or
"original". Retain `confidence: null`. Screen-only models must be labelled screen
recapture indicators, not generic authenticity or print-copy detectors. Parent
Rust wiring requires feature parity, a validated localizer and independent real
false-positive/capture-device evidence before promotion.


## Full-image automatic detector

The separate automatic candidate requires **only RGB pixels**, not document
annotations. `automatic.py` implements a frozen 3×3 grid of native 224-square
patches and the featurewise 75th-percentile aggregation. `automatic_study.py`
trains/exports two predeclared operating points on the identical sealed real
cohort, preserving all failures and full DEV denominators.

```sh
OPENBLAS_NUM_THREADS=1 "$PY" experiments/originality_detector/automatic_study.py --data /tmp/originality-source-train-new --output /tmp/originality-automatic-new
"$PY" experiments/originality_detector/automatic.py /private/run/automatic_strict.model.json /private/image.jpg --allow-experimental
```

The model schema adds `input_protocol: rgb_grid_3x3_native224_q75` and an exact
`grid` descriptor. Call `automatic.assess(model, rgb_uint8,
allow_experimental=True)` for measured research behavior. Without opt-in it
abstains, and invalid/small/nonopaque inputs return unknown/null. The print head
is disabled; this is a screen-recapture indicator. There is no original verdict
or calibrated confidence. The parent may port this deterministic transform and
linear model only with the result's stated scope/limitations and parity checks.

**Source coordinate correction:** the author's TRAIN-list x/y are patch left/top.
The historic frozen import field named `centre` contains those unchanged numbers.
The corrected annotation-assisted runner explicitly adds 112 to call the
centre-based API. This historical naming is not a license to reinterpret source
rows silently; the crop-reference hash and failed first fitting run are retained.


Final repeated runs reproduce every recorded per-item decision/score and fitted
numeric parameter exactly. The full-image CLI agrees with the recorded result
on the first frozen DEV record. Nineteen focused tests pass. See
`evidence/automatic-v2-final.json`, `evidence/real-v3-final.json`, and
`evidence/validation.json`. The strict automatic model detects 9/24 real attacks
with 2/48 false warnings; it is a research result, not a production promotion.
