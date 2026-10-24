# Capture and barcode research, 24 October 2026

This track evaluates preprocessing and decoder alternatives against the scanner at
`dd96ed0d193cbc5e2a316bd9234524a08a44dbfc`. It changes no shipping module,
acceptance rule, security threshold, model weight, shared scorer, or manifest.
All experiments are DEV only. It is a small engineering study, not a reproduction
of any paper's benchmark or a comparison with its leaderboard.

The runnable experiment is in [research_capture](../experiments/research_capture/).
Every candidate, including failures, is retained. Raw images, annotations, OCR
strings and barcode payloads remain outside git under the owner-private
`/tmp/docscan-research-capture/`; publishable evidence contains counts, outcome
bits, opaque identifiers, input hashes and provenance only.

## Protocol and scope

Read before implementation: `bench/README.md`, `experiments/public_id/README.md`,
`docs/research-id.md`, `docs/research-barcode.md`, `docs/improvements-barcode.md`,
the native `scan` example and the current localization/decoding paths.

- MIDV uses the existing `midv500-dev-v1.json`: 18 frames, 12 passports and six
  unsupported Estonian fronts. The latter are negative acceptance cases.
  Exact acceptance requires the correct kind and **all ten** MRZ fields,
  through the unchanged `experiments/public_id/score_id.py`.
- Barcode uses all 300 synthetic DEV frames (818 decodable truth codes) and
  277 public DEV frames (262 decodable truth codes). Manifest file counts also
  include truth files; they are not frame denominators. Use the unchanged
  `bench/suites/barcode.py` v2, including UPC-A/EAN-13 and Codabar normalization.
- Two workers maximum; a fresh native process per image; Rayon and RTen each
  limited to one thread. ID timeout 180 s, barcode timeout 30 s **per pass**.
  A combined barcode candidate can spend two such timeouts. Failed passes remain
  recorded; a successful other pass is retained in union candidates.
- `candidates.json`, runner hashes, model hashes, source snapshot and native
  executable are frozen before inference. `git archive` from the stated commit
  prevents interference from other agents' edits. Rust builds use `-j2` and an
  isolated target directory. Baseline flags are `--models=.../models`, no
  `--expect`, `SCAN_MAX_WIDTH=1280` for ID; add `--barcodes` and use
  `SCAN_MAX_WIDTH=100000` for barcode, matching the existing benchmark.
- Native scanner and ocrs models are identical across preprocessing candidates.
  Barcode ZXing-C++ is an explicitly separate decoder comparator, not a change
  to ID acceptance. Its full flags and installed binary hashes are retained.
- Accuracy-pass wall times include startup/model load and concurrent contention.
  **They are not speed claims**, do not include every preprocessing step, and
  cannot satisfy the main benchmark's interleaved native/WASM latency gate.
- The MIDV observations are clustered by only three physical source layouts,
  with two passport specimens. No field-level independence or significance claim.
  Barcode scorer confidence intervals describe this DEV set, not unseen devices.
  Labelled OCR, live capture, WASM latency and TEST were not evaluated here.

## Measured results and decisions

All trials completed on 2026-10-24. Round one froze at 14:05:04 UTC for ID;
the complete corrected barcode attempt froze at 14:13:21 UTC. The crop-margin
ablation froze at 14:17:53 UTC and the cached barcode selection loop at
14:19:07 UTC. Configuration and implementation hashes accompany the results.

### ID/capture

| Candidate | Correct accepts / 12 passports | Wrong accepts / 18 frames | Negative accepts / 6 fronts | Exact MRZ fields / 120 | Decision |
|---|---:|---:|---:|---:|---|
| Native raw baseline | 1 | 2 | 0 | 68 | Reference; prior result reproduced |
| Annotation-rectified control | 5 | 0 | 0 | 50 | Diagnostic control, not automatic localization |
| Raw rotated clockwise 90° | 2 | 3 | 0 | 60 | Reject: two new wrong-accept frames, one prior wrong fixed |
| Automatic contour quad + 3% margin | **4** | **1** | **0** | 78 | Carry forward for integration testing |
| Annotation-rectified + 5% margin | 5 | 1 | 0 | 86 | Reject: new wrong accept despite more correct fields |
| Automatic contour quad + zero margin | 2 | 3 | 0 | 82 | Reject: loses two correct accepts and adds two wrong accepts versus 3% |
| Automatic contour quad + 6% margin | 3 | 1 | 0 | 76 | Reject versus 3%: loses one correct accept |

The automatic proposal found a quadrilateral in 10/18 images and fell back to
the original image in eight. It added three correct accepts, lost none, and
removed one wrong accept without creating a new wrong-accept frame. The remaining
wrong accept is **not fixed** by this work. Do not describe 4/12 as production
accuracy or a complete solution. Six unsupported fronts are also insufficient
to establish broad false-accept safety.

The zero-margin ablation is a real no-op border; the initial helper otherwise
forces at least one pixel. The repeated crop is determined only by image
geometry, never by truth, text, layout ID or outcome. Width/aspect/area constants
and Canny settings remained frozen; round two changed only the predeclared
border margin. The 3% candidate was not an exact reproduction of a paper.

### Barcode

Cells are exact decodable-code hits and false-decode frames, with separate
fixed denominators. The two corpora are not pooled into a generalization claim.

| Candidate | Public hits / 262 | Public false frames / 277 | Synthetic hits / 818 | Synthetic false frames / 300 | Decision |
|---|---:|---:|---:|---:|---|
| Native baseline | 214 | 5 | 624 | 1 | Reference |
| Native + unrestricted 90° retry | 216 | 6 | 629 | 2 | Reject: new false frames on both corpora |
| Native + unrestricted half-scale retry | 218 | 5 | 630 | 5 | Reject: four new synthetic false frames |
| ZXing-C++ default HRI adapter | 214 | 15 | 522 | 39 | Retain; representation-incompatible comparator |
| Native + matrix-only 90° outputs | 216 | 5 | 629 | 1 | Candidate: five synthetic and two public gains |
| Native + matrix-only half-scale outputs | 217 | 5 | 624 | 1 | Candidate: three public gains |
| Native + both matrix-only outputs | **217** | **5** | **629** | **1** | Carry forward for bounded native implementation |
| ZXing-C++ with equivalent format/UPC normalization | 221 | 8 | 557 | 8 | Reject replacement: new false frames and baseline misses |

“Matrix-only” permits QR, DataMatrix, PDF417 and Aztec **additional retry
results**, retaining every original native decode. It changes neither native
checksums/error correction nor ID acceptance. This second loop is explicitly
**adaptive DEV tuning**, derived from round-one regressions, not an independent
validation set. Before scoring, the candidates and every cached prediction hash
were frozen. It runs the unchanged scorer on the complete cached predictions;
it does not rerun native inference or claim format-restricted runtime. The
combination has zero new false-decode frames and zero lost baseline truth codes
on either set. All original false frames remain.

The combined candidate's gains are QR on public DEV (56→59 / 63), and QR
(47→48 / 71), DataMatrix (43→44 / 66) and Aztec (16→19 / 40) on synthetic DEV.
PDF417 is unchanged: 10/12 public and **5/19 synthetic**, an unresolved gap.
All 1D results remain the baseline's because additional linear retries were
excluded. Every other symbology, all-code rate, precision and negative-frame
outcome is retained in the evidence, not just these improvements. No valid
complete candidate had an inference timeout or crash.

The initial ZXing adapter used its default human-readable text. That is not the
same representation the fixed importer uses: UPC-E can be expanded and Code39
Extended has a different format name. A separately declared adapter loop maps
only those equivalent representations using the **existing pinned importer's
conversion function**; it does not edit the scorer, alter arbitrary text, consult
truth to choose outputs, or conceal the initial numbers. HRI/ECI/GS1 semantics
still need auditing before any backend comparison can be called a complete
replacement comparison. The normalized comparator loses 10 baseline truth codes
on public DEV and 91 on synthetic DEV; aggregate public recall alone hides
these losses. It has six new public false frames (two old ones disappear) and
eight new synthetic false frames (the old one disappears).

### Harness correction, retention and handoff

The first barcode attempt froze at 14:08:29 UTC and completed 143 public-frame
records before aborting on the OpenCV 100×1-WebP loader error. It is retained
as **incomplete, not a benchmark verdict**, alongside its private raw outputs.
The v2 fallback uses PIL only when OpenCV cannot load an image, preserving
all 277+300 frames. No input was skipped, relabelled, regenerated or repaired.
The decoder extension-byte receipt was recorded after this aborted attempt and
before the valid v2 run; the aborted attempt froze only the installed version.

Redacted artifacts are under
[evidence](../experiments/research_capture/evidence/):
[id round one](../experiments/research_capture/evidence/id-round1.json),
[id margin ablation](../experiments/research_capture/evidence/id-round2.json),
[complete barcode round one](../experiments/research_capture/evidence/barcode-round1.json),
[barcode selection/adapter loop](../experiments/research_capture/evidence/barcode-round2.json),
[paired gains and regressions](../experiments/research_capture/evidence/paired-deltas.json),
[aborted attempt](../experiments/research_capture/evidence/aborted-barcode-attempt.json),
[audit](../experiments/research_capture/evidence/audit.json).
The preserved native executable is `/tmp/docscan-research-capture/bin/scan`;
its source-built SHA and the prior executable's SHA are in
[build provenance](../experiments/research_capture/evidence/build-and-decoder-pin.json).

Five procedural protocol tests pass. The source build used the pinned lockfile
with rustc 1.98.1. Before export, source, native binary, model and installed
ZXing implementation hashes were checked again. No TEST/reserved inference,
shipping module edits, commits, branch changes or PR operations occurred.

Recommended parent-owned integration work: independently implement and test the
contour proposal with a bounded single warp and explicit coordinate mapping;
then prototype matrix-format rotation/scale retries in a scratch native CLI.
Keep the measured native baseline and validators. Confirm the gains using the
main DEV referee, all negative cases and labelled scans, then run interleaved
native/WASM timing before proposing a shipping change. Broad 1D retries, larger
crop margins and an unconditional decoder replacement are not supported by
these measurements.

## Primary-source survey

All links below were checked on **2026-10-24**. Dates are publication/submission
metadata from primary pages; repository pages use the access date unless a tag
is named. A paper's publication license is not permission to use its weights or
training images. “Unverified” means no affirmative deployment permission was
established in this survey, not an assertion that the resource has no license.
No agreements were accepted, authors contacted, paid services called, or new
portrait data acquired. No model was trained or calibrated.

### Localization, rectification and restoration

**Tropin et al., Advanced Hough-based method (2021-06-18).** Edge and color
boundary evidence plus projective constraints make a relevant on-device
localization design. [Paper](https://arxiv.org/abs/2106.09987).
The tested largest-contour homography is our own deliberately simple control;
it does **not** reproduce this algorithm's contrast ranking. No author weights
are required for a classical implementation. Implementation code license was
not established; independently implement the algorithm rather than copying
unlicensed code. MIDV data terms are discussed separately below.

**DocRes (CVPR 2024; arXiv 2024-05-07).** A task-prompted restoration model
covers geometric correction, deblurring, shadows, appearance and binarization.
[Paper](https://arxiv.org/abs/2405.04408),
[author code](https://github.com/ZZZHANG-jx/DocRes),
[inference](https://raw.githubusercontent.com/ZZZHANG-jx/DocRes/master/inference.py),
[data instructions](https://github.com/ZZZHANG-jx/DocRes/blob/master/data/README.md).
Code: MIT. Author weights are linked, but a separate weight-rights and complete
training-data audit was not established here; data include Doc3D, TDD, RealDAE
and others with separate terms. The implementation has a CPU path as well as
CUDA; dewarping also needs MBD weights. Neither RTen export/operator support nor
browser memory/latency is measured. Defer integration; evaluate exact text and
wrong acceptance before any visually attractive restoration.

**DvD (2025-05-28; revised 2025-10-09; SIGGRAPH Asia 2025).** Diffusion predicts
coordinate mappings rather than directly generating document pixels.
[Paper](https://arxiv.org/abs/2505.21975),
[author repository](https://github.com/hanquansanren/DvD).
Code: AGPL-3.0; independent weight and AnyPhotoDoc6300 dataset permission not
established here. This is a useful design distinction for preserving content,
but not a guarantee of OCR correctness. Iterative PyTorch inference, license
compatibility and WASM export are gates. No model or corpus downloaded.

**Axis-Aligned Document Dewarping (2025-07-20; revised 2025-11-14; AAAI 2026).**
Axis alignment is used in training, preprocessing and evaluation.
[Paper](https://arxiv.org/abs/2507.15000),
[author repository](https://github.com/chaoyunwang/AADD).
As accessed, the repository contains a README and says full code/models are
coming soon. Code, weights and data permission are consequently unverified for
reproduction. Our quarter-turn experiment is **research-inspired**, not AADD.
Its negative result says nothing about the full paper method.

**TADoc (2025-08-09 preprint; publisher page dated 2026-08-25).** Predicts
intermediate dewarping states and proposes Document Layout Similarity.
[Paper](https://arxiv.org/abs/2508.06988),
[publisher](https://journals.sagepub.com/doi/10.3233/FAIA250803).
Its “time” represents restoration steps, **not fusion of camera frames**.
Code/weight permission was not established. Training uses Doc3D/UVDoc, whose
permissions must be checked independently; the article's CC BY-NC license is
not a model license. Reported GPU throughput is not our browser runtime.
Defer pending artifacts, licensing and bounded CPU inference.

**SyntheticDoc (2026-09-14; ECCV 2026).** Physically rendered documents with
geometric and illumination supervision offer a route to testing warp and glare
failure modes without acquiring real ID portraits.
[Paper](https://arxiv.org/abs/2609.15503),
[author code](https://github.com/tanguymagne/SyntheticDoc),
[data documentation](https://raw.githubusercontent.com/tanguymagne/SyntheticDoc/main/DATASET.md),
[dataset DOI](https://doi.org/10.3929/ethz-c-000801994).
Code: MIT. Dataset/asset license and released weight permission remain unverified;
source pages include arXiv documents, whose rights are separate. No samples were
opened. Prefer an independently generated, rights-cleared procedural training
set if this direction proceeds; physics rendering is an offline expense.

### Glare, quality and temporal evidence

**Fast Glare Detection (2019-10-24).** Uses luminance and stroke histograms with
a CNN to distinguish glare from bright document backgrounds.
[Paper](https://arxiv.org/abs/1911.05189).
Code, weights and dataset reuse permission were not established. Our suggestion
is a low-cost text-region quality mask, not a reproduction of its network.
Saturation alone should not discard clean white paper or authorize acceptance.

**DocHR14K / L2HRNet (2025-04-19).** Highlight-location priors and a Laplacian
pyramid network with a diffusion component target reflected document glare.
[Paper](https://arxiv.org/abs/2504.14238).
Public deployable code, weight and dataset licenses were not verified. The
reported restoration metrics are not ID exact-field metrics. Reject immediate
use in identity acceptance: inference cost and recovered-character correctness
must be measured. Prefer recapture or an unsaturated observed frame over
inventing pixels where the sensor clipped all evidence.

**Bulatov et al., next integrated result modelling (2019-10-09).** Combines
per-character alternatives and models whether another frame will change the
result. [Paper](https://arxiv.org/abs/1910.04107).
No deployable weight artifact or implementation license was established; MIDV
benchmark use is separate from licensing a recognizer. A future implementation
can fuse aligned character evidence and keep provenance by frame. Identical
wrong strings across correlated frames must not be counted as independent
confirmation. Current two-frame-per-sequence DEV data cannot validate a real
stopping policy or time-to-capture claim.

**Handheld Video Document Scanning (2024-11-01).** An on-device page-turn model
separates stable page capture from movement in handheld video.
[Author paper](https://arxiv.org/abs/2411.00576).
Code, weights and PUCIT data license not established here. It concerns multipage
capture, not MRZ character fusion. Research-inspired extension: use geometry
stability and text-scale focus to decide when to pay for OCR, while retaining
the original capture acceptance validator. Requires licensed DEV sequences,
with a frozen exposure/quality policy, before an experiment can be meaningful.

### ID and MRZ constraints

**ICAO Doc 9303, eighth edition (2021), Parts 3 and 4.**
[Common specifications](https://www.icao.int/publications/documents/9303_p3_cons_en.pdf),
[TD3 specifications](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf).
The fixed TD3 structure and positional alphabets constrain OCR. Check digits
cover specified fields; they do not prove every name/field is correct or prove
document authenticity. These are specifications, not model/data licenses.
The existing scanner's checks and its all-ten-field scorer stay unchanged.
A future MRZ-band crop must preserve full lines and fillers and must not tune
its decoder or reject rules to TEST or to a desired acceptance count.

**MobileMRZNet (publisher dated 2024-08-30; PDF issue says June 2024).**
A BlazeFace-derived detector targets mobile MRZ extraction.
[Publisher](https://dergipark.org.tr/en/pub/bajece/article/1416404),
[paper PDF](https://dergipark.org.tr/en/download/article-file/3646577).
The paper reports a small model and multi-frame recognition improvement;
neither is a measured result here. Author weight/code permissions and its
Turkish-ID data rights were not established. A portrait detector architecture
is not permission to reuse restricted portraits for MRZ or production training.
Consider a dedicated detector only after artifact/license verification.

**HED-MRZ (ICDAR 2024; publisher 2024-09-11).** Semantic segmentation with direct
and transposed Fast Hough transforms aims for a compact MRZ detector.
[Publisher paper](https://link.springer.com/chapter/10.1007/978-3-031-70546-5_21).
Code/weight license and training-data deployment rights remain unverified. A
small checkpoint does not establish low inference cost: custom transform layers
need RTen/ONNX/WASM feasibility checks. Do not promise speed from parameter
count. No purchase or author request was made.

**Eberdorfer / Brandmayr (2026-06-19, author preprint).** Separates MRZ detection,
rectification, line splitting and MRZ-adapted CTC recognition.
[Author deposit](https://zenodo.org/records/20764183).
Useful architectural evidence for measuring each stage independently. The
private target-domain numbers cannot be compared with our 12 passports, and
private fine-tuning data cannot be reproduced here. Code, weight and source-data
licenses were not established. No model copied, fitted or calibrated.

### Barcode detection and decoding

**BarBeR (ICPR 2024; EAAI 2025 study, volume May 2025).**
[Author repository](https://github.com/Henvezz95/BarBeR),
[publisher study](https://doi.org/10.1016/j.engappai.2025.110259).
It distinguishes localization from decoding and covers learned and classical
methods. Repository license: AGPL-3.0. Do not inherit dataset/weight rights from
that license; access and reuse remain outside this task, consistent with the
existing benchmark's access-agreement exclusion. Localization mAP alone cannot
select a decoder for exact payload recovery. No BarBeR data were fetched.

**BaFaLo (CAIP 2025).** Two-branch lightweight segmentation combines local detail
and global context for low-resolution barcode localization.
[Author implementation](https://github.com/Henvezz95/BarBeR/tree/main/BaFaLo),
[author-hosted paper](https://www.iris.unimore.it/retrieve/4221139d-f106-4214-abcf-bc4b4d69d46d/2025CAIP.pdf).
Code lives in the AGPL-3.0 BarBeR repository; separately usable weights and data
permissions not established. CPU measurements on the authors' devices do not
predict this WASM application's latency. Candidate for a licensed crop proposal
stage after profiling, not an immediate replacement for the decoder.

**Piecewise constant level-set semi-blind deconvolution (2026-05-31).** Uses an
augmented-Lagrangian/ADMM approach for blurred linear barcode signals.
[Author paper](https://arxiv.org/abs/2606.01156).
No learned model is required by the formulation; released implementation and
experimental-data licenses were not established. Do not equate numerical signal
reconstruction with exact end-to-end decoding across QR, DataMatrix and PDF417.
Bounded scan-line restoration is an interesting later fallback; unconstrained
iteration is not appropriate for every live frame. Our half-scale experiment
is not a reproduction of this algorithm.

**ZXing-C++ v3.1.1.** The authoritative implementation supports local-average
binarization, rotations, inversion and a downscale pyramid, and defaults to
multiple matching scan lines for linear codes.
[Reader options](https://github.com/zxing-cpp/zxing-cpp/blob/v3.1.1/core/src/ReaderOptions.h),
[dispatch/pyramid](https://github.com/zxing-cpp/zxing-cpp/blob/v3.1.1/core/src/ReadBarcode.cpp),
[PDF417 reader](https://github.com/zxing-cpp/zxing-cpp/blob/v3.1.1/core/src/pdf417/PDFReader.cpp),
[DataMatrix detector](https://github.com/zxing-cpp/zxing-cpp/blob/v3.1.1/core/src/datamatrix/DMDetector.cpp),
[license](https://github.com/zxing-cpp/zxing-cpp/blob/v3.1.1/LICENSE).
Code: Apache-2.0; no model weights/training data. The measured Python binding
executes native code; it is not a browser build. Our rotation and half-scale
retries are inspired by these search strategies but reuse docscan/rxing. A new
backend needs byte/ECI semantics, geometry mapping, WASM size and latency checks.

**rxing 0.9.3**, the lockfile-pinned native baseline, is Apache-2.0 and includes
ZXing-derived readers. [Maintainer repository](https://github.com/rxing-core/rxing).
No learned weights. Its exact behavior here is docscan's existing per-format
search and rescue pipeline, not the latest upstream default. Keep native
validation and deduplication while experimenting with crops; increased search
can increase false readings, especially for weakly checked linear symbols.

**Other authoritative implementations.**
[quirc](https://github.com/dlbeer/quirc),
[ISC license](https://raw.githubusercontent.com/dlbeer/quirc/master/LICENSE):
small C QR-only decoder; cannot replace DataMatrix/PDF417/1D support.
[libdmtx](https://github.com/dmtx/libdmtx),
[BSD-style two-condition license](https://raw.githubusercontent.com/dmtx/libdmtx/master/LICENSE):
Data Matrix specialist; candidate only if its exact-format gap justifies an
additional bounded decoder. [ZBar](https://github.com/mchehab/zbar): LGPL-2.1
code, useful QR/linear coverage but not a drop-in full-format replacement.
None requires learned weights. These were surveyed, not benchmarked; runtime,
linking/license obligations and per-format error behavior must be measured
before adding another shipped implementation.

## Data and model provenance

MIDV acquisition is unchanged from
[the existing protocol](../experiments/public_id/README.md):
[author paper](https://arxiv.org/abs/1807.05786),
[publisher license](ftp://smartengines.com/midv-500/license.txt),
[specimen provenance](ftp://smartengines.com/midv-500/documents.pdf).
The publisher states CC BY-SA 2.5; source specimen attribution/modifications
remain in its provenance. FTP hashes pin the acquisition, not authenticated
publisher identity. Reserved layouts were not acquired or inspected. No portraits
were extracted, trained on or used to calibrate production weights.

Public barcode data are the existing Apache-2.0 ZXing-C++ samples at
`2c3dcfeffa7878950a58c1703c86774a428b0c91`; synthetic data use the existing
seed-101 DEV manifest. Because the public samples originate with ZXing-C++, its
performance on them is not an independent external generalization estimate.
Neither corpus was regenerated or extended.

The native baseline loads only the two already downloaded ocrs `.rten` models.
[Author model card](https://huggingface.co/robertknight/ocrs) identifies
CC BY-SA 4.0 and HierText/synthetic training;
[author training repository](https://github.com/robertknight/ocrs-models) and
[ocrs runtime](https://github.com/robertknight/ocrs) distinguish model terms from
the MIT/Apache runtime. Frozen local hashes, not a mutable download URL, identify
our actual artifacts. No replacement or fine-tuned weights are introduced.

## Our follow-up algorithms and rejection gates

These are engineering proposals informed by the sources, not exact reproductions.

1. Rank document quads with edge support **and** contrast across the border,
   preserve original-resolution pixels for a single final warp, and include a
   quiet margin. Measure wrong-quad rate as well as end-to-end acceptance.
   A largest-contour proposal can select a page interior or background rectangle;
   it must earn integration through exact-field recovery without extra wrong accepts.
2. Run a document-orientation or MRZ-band proposal before full-page OCR. Preserve
   original-source pixel evidence, use bounded rotations, and retain the existing
   validator. Do not make “first checksum passes” the success metric.
3. For barcodes, estimate module scale and retry only selected candidate regions
   at a useful scale. Preserve QR quiet zones, DataMatrix L-borders and PDF417
   start/stop structure. Map coordinates back to the source and retain per-pass
   evidence. Measure every symbology and false decodes; aggregate recall alone
   must not hide a DataMatrix/PDF417 or short-1D regression.
4. Select frames by text-scale sharpness and unsaturated stroke evidence after
   alignment. Only fuse character distributions across the same tracked region;
   reset on document changes. Compare best-frame selection with fusion. This
   requires a new licensed DEV video protocol before thresholds or stop rules
   can be evaluated; the present sparse frames cannot support it.
5. Use independently rendered MRZ strings and barcode symbols for future
   controlled blur/glare/scale stress tests. Record generators and seeds before
   trials. Never use reserved identities, restricted portraits, or restoration
   outputs as production ground truth.

Defer learned dewarping/highlight networks with unresolved artifact rights or
unmeasured browser inference. Reject pixel-generating restoration as an identity
acceptance shortcut, unconstrained iterative deconvolution per live frame,
provider OCR calls, and test-time weight fitting. Paper-dataset accuracy, mAP,
PSNR, SSIM, GPU FPS and character accuracy are incomparable with our exact-field
acceptance and exact barcode payload denominators.
