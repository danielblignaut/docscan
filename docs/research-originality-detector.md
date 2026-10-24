# Document recapture detector implementation and optical research

Research date: 24 October 2026. Implementation is confined to
[`experiments/originality_detector`](../experiments/originality_detector/README.md).
No Rust wiring, application acceptance rules, face thresholds, commits or PRs are
part of this work. The parent owns integration. This report distinguishes actual
measured evidence, primary-source findings, and unvalidated proposals.

## What is implemented

An independent CPU feature extractor, regularized logistic trainer, held-out
negative operating-threshold calibration, JSON model export, explicit
positive/unknown inference API, and fixed-denominator evaluator. No third-party
network architecture or pretrained weights were imported. Missing/invalid inputs
abstain and count as missed attacks. Scores are logits; **confidence stays null**.
A negative result never declares a document original. Paper/screen recapture,
issuer authenticity, content tampering, signature authorship and human identity
are separate claims.

Features compare chromatic and achromatic texture, residual energy at two blur
scales, spectral concentration, and optional document/background context.
Native-resolution patch statistics avoid losing fine patterns during resizing.
The source specifies all feature names, normalization, weights, bias and strict
threshold comparison. This is not a reproduction of LC&DF, the DLC ResNet model,
or the Fast Hough boundary detector. Every predeclared candidate is retained.

The first real-data arms use authors' labelled 224-square patches and are
**annotation-assisted**. A separate full-image automatic 3×3 patch-grid arm uses
only image dimensions to select patches, with fixed feature aggregation and its
own exported model and CLI. It needs neither annotations nor a document locator.
The real study is screen-only; no real print-copy training or original-ID
validation is claimed. Runtime opt-in is explicit for these unvalidated models.
See the experiment README for the export/integration contract.

## Source splits, acquisition and rights

The decisive source is the authors' [DLC-2021 paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC9323793/)
and [baseline/data release](https://zenodo.org/records/6792397).
The paper distinguishes laminated mock specimens, grayscale/color paper copies
and screen recaptures. It also identifies complex security printing and
compression as false-positive causes, and explains why lighting complicates
color-copy evidence. Those observations motivate counterexamples, not a
calibrated confidence score.

Record 6792397 contains `or.zip` (18,818,074,180 bytes), `cg.zip`
(15,039,057,125), and `experimental_baseline.zip` (88,403,129).
[Part 2](https://zenodo.org/records/6466770) is a split ZIP: eight 4,293,918,720-byte
`.z01`–`.z08` parts and `re.zip` (4,170,685,785).
[Part 3](https://zenodo.org/records/6466764) is another split ZIP for color copies.
These are archives, not TRAIN/DEV partitions. HTTP Range supports fetching
selected members with CRC checks, without transferring every media payload.
Metadata/source hashes are in `source-notices.json`.

The baseline archive's actual `screen_positive_train.lst` has 19,543 rows, from
Spain, Latvia and Russia; `screen_negative_train.lst` has 25,980 rows referencing
MIDV-2020. Only these TRAIN lists are read. Neither source TEST-list contents nor
source TEST pixels/truth are admitted to the final experiment. The former article
word “validation” is insufficient to override the released `*_test.lst` split.
No author checkpoint is used, because its exposure and independent weight rights
were not established for this protocol.

[MIDV-2020's author README](ftp://smartengines.com/midv-2020/readme.txt) describes
1,000 mock documents with unique invented fields and generated faces, and maps
clip numbers to capture phones and conditions. Its `clips.tar` is an uncompressed
10,303,651,840-byte archive. The importer reads 512-byte TAR headers and skips
unselected payloads using FTP REST; only exact source-TRAIN-list image members
are fetched. FTP transport is unauthenticated: SHA-256 pins bytes received, not
the identity of the upstream publisher. No access agreement was accepted.

DLC and MIDV data each state **CC BY-SA 2.5** and identify **Generated Photos**
as their face source; those notices and attribution remain with private research
artifacts. Code licensing is separate: this implementation is independently
written in the existing repository; external neural code was not copied.
Learned weights are private research artifacts pending a separate derivative-
weight redistribution review, not presumed MIT/BSD because a code repository is.
Original procedural fixtures contain no external assets, identities, portrait
photos, fonts or human signatures. Images, annotations, features, per-item
scores and weights stay outside git in owner-private directories.

### Acquisition audit and corrections

The first attempt, `/tmp/docscan-originality-dlc-v1`, selected broader DLC types
before checking the baseline TRAIN definitions. It was interrupted and
quarantined when the possible source-held-out overlap was identified. It wrote
**126 images and 64 annotations (27,445,650 bytes)** across selected types; images were not decoded or
inferred. One Albania annotation structure was read to inspect the format.
The private `ABORTED.json` records each written path and byte count, and preserves
the executed importer. This attempt cannot honestly be described as having
verified exclusion of source-held-out acquisition. It is excluded from every
metric. No docscan bench TEST/reserved directory, media, truth or results were
accessed. The legacy importer's CLI is now disabled; its shared range helpers
remain usable by the corrected importer.

A replacement source-TRAIN-only selection (`source-train-v2`) completed but was
not inferred: its DEV contained just four positive frames from two clips. Its
policy and data remain intact. A larger metadata-only selection (`v3`) briefly
included Latvia's source TRAIN rows after a parent suggestion. When the parent
corrected that instruction, indexing was stopped **before its media directory
was created**; no Latvia pixels/truth were downloaded. Its receipts are retained.
The final `v4` selection uses **Spain and Russia only**, internally expanding
positive DEV specimens from 06–07 to 04–07 and holding MacBook/Philips displays
out from Lenovo TRAIN. Existing reserved layouts remain excluded. Source-verified
negative images are reused from sealed v2, byte hashes checked again, without
changing their labels, centres or split. No candidate scores informed expansion.

An independent preflight found that the original replacement manifest did not
bind all selection receipts. The corrected flow seals the selection hash,
author TRAIN-list bytes/hashes, notices, original acquisition helper sources,
policy, member map and raw manifest. MIDV README/license bytes also match the
separately pinned primary-source notice registry. Before reading pixels, the evaluator
verifies all linked receipts and every row's source membership, patch centre,
label, specimen, split, phone, display and selected archive member. Mutation
regression tests cover these checks. The v2 shared-helper snapshot was recorded afterward and is not independently
proven as acquisition-time code; v4 saves its helper snapshots before media
access. Final runs hash imported helpers and re-verify the sealed receipt and
notice registry at finalization. The original manifests are retained;
`sealed-manifest.json` is the canonical new linked receipt. Two full-size synthetic runs were interrupted before training while source/audit
fixes were made; freezes and partial work remain private. A smaller 24/16/20-group
run was declared before outcomes to bound CPU cost, retaining every condition
and candidate.

## Final real-data protocol

All images are from author-designated screen TRAIN files, internally split for
this new study. The cohort is not the paper's reported benchmark and must not be
compared to its headline accuracy.

The final sealed Spain/Russia cohort has:

- TRAIN: eight screen frames from four specimens/four clips and 32 bona-fide
  frames from 16 specimens/clips. Samsung S10; Lenovo attack displays.
- Calibration: 16 bona-fide frames from eight separate specimens/clips,
  Samsung S10. No positive calibration rows.
- DEV: 24 screen frames from six specimens/12 clips and 48 bona-fide frames
  from 24 specimens/clips. iPhone XR; MacBook/Philips attack displays.
- Four eligible positive clips had fewer than two source-TRAIN-labelled frames.
  Their omission is frozen from metadata before model inference. For each image
  with multiple source TRAIN patch rows, the importer deterministically retains
  the last listed patch. Within a selected clip it takes the lexicographically
  first and midpoint available image. No image was selected from a prediction.

- Positive specimens 00–03 belong to TRAIN; 04–07 to DEV. Negative specimen
  assignments follow the author's phone mapping and remain disjoint. All frames
  and derived patches of each identity/specimen stay together. Capture phones
  and screen models are disjoint between TRAIN and DEV. Calibration shares the
  TRAIN phone but no specimens. Frames within a clip are not independent trials.
- Eligible positive clips with fewer than two author-labelled TRAIN frames
  are recorded as missing before acquisition, not removed after scoring.
  Other count reductions from theoretical combinations are availability limits.
- Frozen arms: constant unknown, chroma/frequency logistic, texture/color
  logistic and native-patch logistic. The boundary arm requires full-document
  localization and is excluded by protocol from this patch-only real study.
- Threshold per head is `max(log(9), largest calibration-negative logit)` and
  uses strict `>`. This is an operating rule with zero observed calibration
  warnings, not probability calibration or a guaranteed population error rate.
  The absent real print head is explicitly disabled. No DEV threshold tuning.
- Failures preserve denominators and are reported separately. All models freeze
  before DEV scoring; all candidate metrics and pairwise regressions are retained.


### Corrected author-coordinate semantics

The first real fitting attempt produced no learned models because one TRAIN
patch failed its bounds guard. Inspection of the author's `screen_train.py`
showed that the source coordinates are **left/top**, not centres. The frozen
receipt field historically named `centre` retains the exact source numbers;
`source_patch_features` now explicitly converts them to the API centre by adding
112 on both axes. No image, source row, split or threshold changed. The source
reference hash and failed run are retained. This is a preprocessing correction,
not a threshold selected from DEV outcomes. No padding or invented pixels is used.

### Automatic full-image protocol

Before its inference, a separate arm freezes a 3×3 Cartesian grid with centres
`linspace(112, width-112, 3)` × `linspace(112, height-112, 3)`. Each patch is native
224×224 RGB. The featurewise 75th percentile of nine patch vectors, linear
quantile interpolation, is the image feature. The model uses only the twelve
native texture/color columns. Image labels and author ROI coordinates do not
enter patch placement or aggregation. This is weak frame-level supervision;
patches can contain background, and no content-location guarantee is implied.

Two operating points are frozen before automatic inference: the original strict
floor plus calibration maximum, and the calibration maximum alone. Both use
strict `>`; neither logit is presented as a probability. All automatic models
freeze before DEV scoring and both results are retained. The latter operating
point is a separately declared experiment, not a post-DEV threshold adjustment.
The same sealed 40 TRAIN / 16 calibration / 72 DEV records are used.

## Measured results

### Bounded synthetic study and real negative transfer

Completed protocol: 24 fit / 16 calibration / 20 DEV procedural specimens, each
with all 14 conditions; 280 DEV images comprise 120 copy surrogates and 160
negative controls. The separate transfer check retains all 18 existing MIDV-500
DEV negatives (three physical specimens). No new real data is mixed into these
synthetic models' training or calibration.

| Synthetic-trained arm | Synthetic detections / 120 | Synthetic false warnings / 160 | Synthetic abstentions / 280 | Real negative false warnings / 18 | Real failures / 18 |
|---|---:|---:|---:|---:|---:|
| constant_unknown | 0 | 0 | 280 | 0 | 0 |
| chroma_frequency | 10 | 2 | 268 | 0 | 0 |
| texture_color | 13 | 1 | 266 | 0 | 0 |
| boundary_context | 42 | 0 | 238 | 16 | 2 |
| native_patch_texture | 0 | 5 | 275 | 0 | 2 |

**Reject synthetic-model promotion.** The boundary model looks best on invented
optics but falsely warns on all 16 real frames whose context extraction succeeds;
the two context failures remain abstentions in the denominator. All three real
specimens incur false warnings. Synthetic camera-profile separation does not
establish real-device generalization. Other synthetic arms also add false
warnings on synthetic negatives, and the native-patch arm recovers no attacks.
The byte-identical clean-copy/plain fixtures expose the impossibility of
recovering physical history from identical pixels.

### Real annotation-assisted arms

The corrected source-origin conversion fits all three candidate models. There
are no acquisition, feature or inference failures in this completed run.
Every arm uses the same 72 DEV frames (24 attacks, 48 negatives).

| Arm | Detected attacks / 24 | False warnings / 48 | Abstentions / 72 |
|---|---:|---:|---:|
| constant_unknown | 0 | 0 | 72 |
| chroma_frequency | 1 | 0 | 71 |
| texture_color | 1 | 1 | 70 |
| native_patch_texture | 1 | 1 | 70 |

The chroma/frequency arm adds one detection with no observed new false warning
relative to constant abstention, but misses/abstains on 23/24 attacks. The two
larger feature arms also flag a real negative. This is limited feasibility
evidence, not a general detector or a promotion claim. Even zero errors among
24 negative specimens has a one-sided 95% binomial upper bound of about 11.7%
under independent-group assumptions; shared devices further weaken that
interpretation. Eight calibration-negative specimens cannot establish a low
population false-positive rate (corresponding zero-error bound about 31.2%).

### Automatic full-image results

All 72 DEV frames are scored with no feature/inference failures. The fixed
strict arm detects **9/24** recaptures, falsely warns on **2/48** bona-fide
captures, and abstains on **61/72** frames. It detects at least one frame for
five of the six attack specimens. The two false warnings affect two distinct
negative specimens, one in each document type. Screen detections are four of
twelve MacBook frames and five of twelve Philips frames.

The separately predeclared calibration-only arm detects **14/24** but falsely
warns on **14/48**, affecting 11/24 negative specimens; it abstains on **44/72**.
Its zero calibration false warnings fail to transfer to held-out devices.
**Reject this operating point.** The strict arm also has two false-positive
regressions relative to constant abstention and is not production-ready.

The strict screen threshold is 2.1972245773362196 on an uncalibrated logit;
the calibration-only screen threshold is -0.5375781808224889. Neither means a
confidence percentage. Both preserve null confidence and never emit an original
verdict. Automatic training has only four positive specimens; six positive DEV
specimens, two document types and one held-out capture-phone model cannot
establish real-world attack coverage. Source-corpus, compression, resolution and
background correlations remain possible confounders despite the phone/display
separation. No new threshold is selected from these DEV outcomes.

### Handoff and limits

The usable handoff is a **research full-image detector**, trainer/evaluator and
export contract, not a validated production policy. `automatic.assess` needs
opaque RGB pixels only. JSON exports select twelve native features from the
ordered 51-feature schema, with means, scales, a 2×12 weight matrix, biases,
thresholds, grid descriptor, source hashes and scope. The absent print head is
disabled. The final strict model is under the owner-private
`/tmp/docscan-originality-automatic-v2/automatic_strict.model.json`; no weights
are included in git. Parent Rust wiring can reproduce the deterministic grid,
feature transform and linear scores, retaining experimental opt-in and the
explicit limitations. Browser/phone latency, quantization and Rust/WASM feature
parity are not measured here.

Promotion requires independent real negatives and recaptures with more identities,
phone/display/printer devices and capture conditions, enough calibration groups
to measure the intended false-warning rate, and acceptance/localization/runtime
validation. Print copies, issuer authenticity, face identity and signature
verification remain outside this real model's demonstrated scope.

All historical attempts and candidates are retained. Aggregate evidence lives in
`experiments/originality_detector/evidence/`; `attempts-and-errata.json` records
interrupted imports, the coordinate correction and the historical stale split
note. The canonical final reports derive counts from actual selected records.

## Broader primary-source research and decisions

**LC&DF and texture interference.** The [IEEE September 2026 publication page](https://signalprocessingsociety.org/index.php/publications-resources/ieee-open-journal-signal-processing/2026/09/display-recaptured-document-image-detection-under-texture-interference)
describes separate local chromaticity and discriminative-frequency branches,
attention and a moiré-aware adapter. This directly addresses confusion with
legitimate document texture. The [author repository](https://github.com/chenlewis/LC-DF-For-DPAD)
currently names the WIFS 2025 predecessor. It declares BSD-3-Clause for code,
with an inherited copyright notice, and links checkpoints on Baidu. A separate
checkpoint/data license and reproducible correspondence to the 2026 paper were
not verified; no weights were downloaded. Our linear ablations test related
cues, not the authors' architecture or reported performance.

**SRDID162.** The [author FMAG/M2FM release](https://github.com/chenlewis/FMAG-with-MMFM)
explicitly labels DM as training data and SRDID162 as testing data. Therefore
SRDID162 is not imported for this tuning task. The separate dataset/weight rights
were not established either. An open code link is not a data-use permission.

**Holograms and lighting.** [MIDV-Holo's author release](https://github.com/SmartEngines/midv-holo)
contains fictional Utopia specimens, several attack constructions, two phones
and five lighting conditions. Its notice states CC BY-SA 2.5 with Generated
Photos attribution. [Weakly supervised hologram verification](https://github.com/EPITAResearchLab/pouliquen.24.icdar)
uses a specific video protocol and localized security features. [MIDV-DynAttack](https://zenodo.org/records/17079529)
adds dynamic attacks under a separate CC BY-SA 4.0 dataset notice; the associated
implementation is separately GPL-3.0. These works motivate registered,
feature-specific temporal evidence. Glare or any shiny moving patch alone is
not evidence of the correct security feature. No hologram media or weights were
imported here.

**Photography and print optics.** Penn State University Press's [halftone guidance](https://www.psupress.org/books/author_resources/author_digsub/halftones.html)
explains that legitimate printed photographs contain periodic dots and can
produce moiré when scanned. That is why a periodicity-only warning is not
specific to fraudulent copying. Our negative controls include benign halftones
and security linework; common blur, noise, JPEG and illumination nuisance affect
both classes. Independent, real printer/paper/lighting data are still needed.
Restoration or demoire preprocessing can erase the very evidence being measured;
copy assessment should use the original capture, with OCR enhancement separate.
The latter is an engineering inference, not a measured result of this study.

**Calligraphy, signatures and human factors.** NIST's [handwriting examination report](https://www.nist.gov/publications/forensic-handwriting-examination-and-human-factors-improving-practice-through-systems-0)
emphasizes examination errors, human factors and careful communication of
conclusions. Our looped-stroke fixtures test texture confusion only. They do not
learn writer identity, validate signatures or infer handwriting authorship.
Human-signature training would need separate rights, writer-disjoint splits,
forgery labels and false-attribution measurements. None is claimed here.

**Human identification and biometrics.** NIST's [face quality defect evaluation](https://www.nist.gov/publications/face-analysis-technology-evaluation-fate-part-11-face-image-quality-vector-assessment)
and [face-quality evaluation report](https://pages.nist.gov/frvt/reports/quality/frvt_quality_report.pdf)
support evaluating lighting, focus and other capture defects separately from
identity comparison. Apple's [face capture quality guidance](https://developer.apple.com/documentation/vision/selecting-a-selfie-based-on-capture-quality)
likewise describes ranking captures of the same person. A document recapture
indicator is neither a face match nor face liveness. This study performs no
biometric matching/training and does not turn photo quality into identity
confidence. A later device-diverse, consented document/selfie study is a separate
experiment, not an implication of improved document texture classification.


## Final verification

Nineteen focused tests pass, including source receipt mutation, unchanged
fixed denominators after failures, identity/phone leakage, top-left coordinate
conversion, deterministic annotation-free grid placement and null-confidence
semantics. After the provenance fixes, full annotation-assisted and automatic
runs reproduce **all per-item predictions and all fitted numeric parameters
exactly**. The automatic CLI matches its recorded first-DEV-frame result.
Sealed receipts, source notices and media hashes pass final checks; raw artifact
directories are mode 0700. No Rust, WASM, browser or device-latency validation is
claimed. Final aggregates are `evidence/automatic-v2-final.json` and
`evidence/real-v3-final.json`; `evidence/validation.json` records comparisons.
