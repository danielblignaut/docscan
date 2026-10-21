# Face liveness and verification: results

Measured 2026-10-21 on a shared 12-core Xeon (no GPU) that other sessions
loaded heavily for most of the day (load average 50–150 during the native
runs; 7–12 during the browser timings). Native runs are the same Rust code
the wasm runs (`docscan/examples/face.rs`, driven by `face/eval/*.py`).

**Protocol.** Every benchmark has a DEV split used for every choice
(thresholds, crop scales, alignment, quality gates) and a TEST split scored
once with everything frozen. TEST numbers are below DEV numbers wherever they
differ; that is reported, not tuned away. The datasets and their terms are in
`face/DATASETS.md`, the models and licences in `face/MODELS.md`.

## 1. Recognition

### LFW through docscan's own pipeline (the number that describes the product)

Raw LFW images → BlazeFace → Face Mesh V2 → five points (irises, nose tip,
mouth corners) → ArcFace-template alignment → model. A face was found in all
13 233 images. DEV = View 1 minus the 758 pairs that also occur in View 2
(2 442 pairs); TEST = View 2 (6 000 pairs, the standard 10 folds). The
deployment threshold is the DEV threshold at FAR = 1e-3, applied unchanged to
TEST. No flip test-time augmentation unless marked.

| Model (licence of weights) | TEST 10-fold accuracy | TEST TAR @ FAR 1e-3 | DEV TAR @ 1e-3 | DEV threshold | TEST FAR / FRR at it |
|---|---|---|---|---|---|
| **SFace, int8 weights (shipped; Apache-2.0, data undocumented)** | **99.52 ± 0.33%** | **99.03%** | 99.41% | 0.366 | 0.07% / 1.00% |
| SFace fp32 | 99.50 ± 0.34% | 99.07% | 99.41% | 0.363 | 0.10% / 0.97% |
| SFace int8, + flip | 99.55 ± 0.37% | 99.20% | 99.52% | 0.354 | 0.23% / 0.80% |
| w600k_mbf, MobileFaceNet (**non-commercial**) | 99.55 ± 0.17% | 99.40% | 99.64% | 0.231 | 0.20% / 0.57% |
| w600k_mbf, int8 weights | 99.58 ± 0.21% | 99.43% | 99.64% | 0.228 | 0.20% / 0.50% |
| EdgeFace-XS (**CC BY-NC-SA**) | 99.63 ± 0.27% | 99.50% | 99.17% | 0.363 | 0.03% / 0.90% |
| EdgeFace-XS, int8 weights | 99.65 ± 0.27% | 99.50% | 99.05% | 0.369 | 0.00% / 0.97% |
| EdgeFace-S (**CC BY-NC-SA**) | 99.78 ± 0.22% | 99.63% | 99.64% | 0.312 | 0.17% / 0.37% |
| w600k_r50, IResNet-50 (**non-commercial**, 174 MB) | 99.82 ± 0.19% | 99.73% | 99.76% | 0.200 | 0.13% / 0.27% |
| FaceNet VGGFace2 (94 MB) | 99.28 ± 0.43% | 97.07% | 95.72% | 0.555 | 0.07% / 5.67% |

The FAR at a fixed threshold rests on 3 000 impostor pairs, so 1e-3 is three
false accepts; treat the FAR column as ±0.1 points.

### The InsightFace evaluation crops (comparable with published numbers)

`lfw.bin`, `calfw.bin`, `cplfw.bin`: 112 × 112 crops pre-aligned by
InsightFace's own detector, the inputs the papers report on. 10-fold
accuracy and TAR @ FAR 1e-3 (TEST only: these sets have no separate DEV).

| Model | LFW | CALFW | CPLFW | Published LFW (source) |
|---|---|---|---|---|
| **SFace int8 (shipped)** | **99.63 ± 0.30** (99.37) | 94.80 (83.10) | 90.92 (71.30) | 99.40 fp32, 99.32 int8 (OpenCV Zoo) |
| SFace fp32 | 99.63 ± 0.32 (99.33) | 94.73 (83.13) | 90.62 (71.57) | 99.40 |
| SFace fp32 + flip | 99.67 ± 0.29 (99.40) | 94.75 (83.27) | 91.12 (72.97) | — |
| w600k_mbf | 99.60 ± 0.28 (99.30) | 95.45 (89.73) | 92.47 (79.17) | 99.70 (InsightFace model zoo) |
| w600k_mbf + flip | 99.65 ± 0.25 (99.50) | 95.60 | 92.70 | 99.70 |
| EdgeFace-XS | 99.75 ± 0.29 (99.53) | 95.22 | 91.85 | 99.73 (arXiv 2307.01838) |
| EdgeFace-S | 99.80 ± 0.21 (99.67) | 95.58 | 92.50 | 99.78 |
| w600k_r50 | 99.82 ± 0.20 (99.70) | 96.03 | 94.35 | 99.80 |

rten reproduces the published accuracies (within ±0.1 point, SFace above its
zoo figure because these crops are InsightFace-aligned). CFP-FP, AgeDB-30 and
IJB-B/C were **not run** (signed agreements; see `face/DATASETS.md`).

**Against "state of the art for on-device models":** the shipped SFace
reaches 99.52% on LFW through the full on-device pipeline and 99.63% on the
standard crops, at the ≥ 99.5% bar, **like for like with MobileFaceNet-class
compact models** (MobileFaceNet 99.55, w600k_mbf 99.70, EdgeFace-XS 99.73,
same protocol). It is clearly weaker on the harder cross-pose set (CPLFW
90.9% vs 92.5% for w600k_mbf and 94.4% for R50; TAR @ 1e-3 71% vs 79–87%),
and IJB-C, the benchmark that separates compact models today, could not be
run. The best compact models measured (EdgeFace-S 99.78/99.80) are
non-commercial.

## 2. Passive anti-spoofing (MiniFASNet) on CelebA-Spoof

Through docscan's own detection and landmarks; a face was found in every
image. DEV = 3 000 images from two shards of the official training subjects,
TEST = 6 000 from the first eight shards of the official test split. The crop
box scale (relative to the mesh's box) and the threshold were chosen on DEV.
"Live probability" is the mean of the two models' softmax.

| Box scale | DEV AUC | DEV ACER at DEV EER threshold |
|---|---|---|
| 1.2 | 0.848 | 22.8% |
| 1.0 (what the liveness session uses) | 0.858 | 22.0% |
| 0.85 | 0.873 | 20.2% |
| 0.7 | 0.893 | 18.2% |
| **0.55 (chosen)** | **0.908** | **16.6%** (threshold 0.78) |
| 0.42 | 0.895 | 17.3% |

| TEST (6 000 images; 1 533 live) | APCER | BPCER | ACER | AUC |
|---|---|---|---|---|
| box 0.55, DEV threshold 0.78 | 32.6% | 13.8% | **23.2%** | 0.858 |
| box 0.55, threshold 0.5 | 51.5% | 5.3% | 28.4% | |
| box 1.0, threshold 0.5 (the session's setting) | 49.2% | 7.8% | 28.5% | 0.842 |

TEST is well below DEV (AUC 0.858 vs 0.908): the box-scale choice partly fit
DEV's subjects. **This is a cross-dataset result** (MiniFASNet was trained on
Minivision's own data, never on CelebA-Spoof) and is not comparable with
CelebA-Spoof's published intra-dataset numbers (e.g. the MobileNetV3 of
light-weight-face-anti-spoofing, trained on CelebA-Spoof: AUC 0.998, EER
2.26%; AENet in the CelebA-Spoof paper), nor with OULU-NPU protocol numbers
(CDCN++ 0.2% ACER intra-dataset), which could not be run. It is consistent
with published cross-dataset FAS results (HTER 10–30% for small models).
**Not state of the art, and the reason is data**: every FAS dataset that would
let us train or fine-tune is non-commercial. The liveness session therefore
does not rely on the passive model alone.

The session still uses box 1.0 / threshold 0.5, the setting its synthetic
DEV and TEST were run with; moving to box 0.55 / 0.78 is the next change,
to be validated on fresh (real, consented) data rather than by re-scoring
the synthetic TEST.

## 3. Active liveness (synthetic clips; not comparable with published numbers)

`face/synth/clips.py` renders every clip from procedural heads (no real
person; 480 × 640, 30 fps). Bona fide: centre, turn the head round a full
circle (random start, direction, radius 21–28°, 3.6–5.2 s, distance, light,
background, skin tone), look straight; some blink. Attacks: a **printed
photo** tilted round the circle as far as it takes (up to ~75°); the same
print **bent round a cylinder**; a **phone screen replaying** a bona fide
sweep (bezel, sub-pixel moiré, colour cast, reflection), zoomed so the face
fills the oval; a **2-D face video** injected full frame (the photo warped
by a turning plane's homography); and a real head that turns only half way
(**partial**). DEV and TEST use disjoint seeds (identities, motions, lights,
backgrounds). Each clip runs through the Rust session at 30 fps.

| | DEV | **TEST** |
|---|---|---|
| Bona fide accepted | 29/30 (BPCER 3.3%) | **40/40 (BPCER 0%)** |
| Printed photo accepted | 0/15 | **0/20** |
| Curved photo | 0/10 | **0/15** |
| Screen replay | 0/10 | **0/15** |
| 2-D video injection | 0/10 | **0/10** |
| Partial sweep | 0/5 | **0/10** |
| APCER (worst species) / BPCER / ACER | 0% / 3.3% / 1.7% | **0% / 0% / 0%** |
| Session time, centred to done (median) | 6.3 s | 6.5 s |

What stopped each attack on TEST: printed photo, 2-D video and partial sweep
never completed the ring (a tilted print reads as at most ~10° of head turn
to the landmark model, so the ring itself is a defence); curved photo 12 not
completed, 3 by 3-D motion; screen replay 13 by the passive model, 2 not
completed. Margins on TEST: bona fide 3-D motion 0.076–0.099 (threshold
0.06), curved photos up to **0.064** (one would have passed 3-D motion had it
completed the ring); screen replays' lowest-frame live probability up to
**0.468** (threshold 0.5); bona fide down to 0.656. These margins are thin and
the clips are synthetic: **no SOTA claim is made here**. The one DEV
rejection is a render overexposed past the "too bright" gate (34% of the face
saturated).

Not covered: 3-D masks and real-time 3-D deepfakes (geometrically correct by
construction; need passive and injection defences), a replay on a large
screen held far away, real people.

## 4. Document photo to live face (synthetic ID-photo renders of LFW pairs)

Each LFW pair's first image printed as an ID photo (greyscale, high-contrast,
halftoned for the SA smart ID card; desaturated colour for the passport),
under holographic guilloche lines, an emblem and glare, pasted into
`testdata/synth.py`'s fictional smart ID front or passport page, then
"captured" (downscaled to 800–1300 px, blurred, noised, JPEG 60–88). The
document goes through docscan's photo path (multi-scale detection, largest
face, landmarks, alignment, template); the second image is the live side.
DEV = View 1 (2 442 pairs), TEST = View 2 (6 000). A face was found on every
document.

| Model | TEST TAR @ FAR 1e-2 | TEST TAR @ 1e-3 | DEV threshold @ 1e-3 | TEST FAR / FRR at it |
|---|---|---|---|---|
| **SFace int8 (shipped)** | 98.87% (smart ID 98.73, passport 99.00) | **98.20%** | **0.356** (the demo's `DOC_THRESHOLD`) | **0.03% / 2.10%** |
| w600k_mbf (non-commercial) | 99.40% | 98.33% | 0.229 | 0.20% / 1.20% |

Not comparable with DocFace/DocFace+ (private ID–selfie sets: 95.95% TAR @
FAR 1e-4 for DocFace+). The simulated print loses less than a real card's
laser engraving and has no age gap beyond LFW's own; expect real ID photos
to score lower. Calibrate on real, consented document–selfie pairs.

## 5. Browser performance (headless Chrome, wasm, this machine)

| | Single-threaded wasm (`?threads=1`, as on GitHub Pages) | Multithreaded (8 threads, cross-origin isolated) |
|---|---|---|
| Liveness frame, median (detect when needed + mesh + pose + quality + texture parallax + anti-spoofing / template on some frames) | **92–103 ms** (p90 175–184 ms) | 75–76 ms (p90 143–148 ms) |
| Frames analysed per second | ~8–10 | ~11–13 |
| Bona fide e2e clip, centred to done | 9.6 s (the clip's own 2 s hold + 6 s sweep) | 9.5 s |
| Wasm heap after a session | 86 MB | 101–104 MB |
| Face models download | 18.7 MB (0.4 + 4.9 + 3.5 + 9.9), cached in the Cache API | same |

Natively (one core, unloaded) the detector takes ~4 ms, the mesh ~16 ms and
SFace ~20 ms. On a mid-range phone, expect roughly 2–4× the single-threaded
browser figures (an estimate, **not measured**): 4–8 analysed frames per
second, which still lights a 12-segment ring at a natural turning speed, but
a slow phone would need the user to turn more slowly.

## 6. End to end (`demo/e2e/run.mjs`, fake camera)

17/17 cases pass: the 13 existing ones, plus

| Case | Result |
|---|---|
| `face-liveness-bona-fide`: synthetic head sweeps the ring | pass: 12/12 segments lit, `docscan:liveness` (with a 128-d template) and `docscan:complete` once each, results screen with the best frame, camera released, outline grey → green → done |
| `face-liveness-photo-attack`: a flat print tilted round | fail as required (ring incomplete, 3-D motion 0.01); camera released |
| `face-id-enrol-then-verify`: full ring, Enrol (IndexedDB), then Face ID's 8-segment ring | both sessions pass; matched, similarity 0.999 at threshold 0.366 (same synthetic identity, so the similarity only shows the plumbing) |
| `face-abandon`: Back to home mid-session | camera released, no frame analysed after |

Chrome's fake camera is named `fake_device_0`, which the virtual-camera check
flags; the face cases pass `?allowVirtualCamera=1`, which records the flag
without failing on it.

## 7. Iteration log (DEV only)

| # | Change | Measured on DEV | Kept |
|---|---|---|---|
| 1 | 3-D motion = homography residual of the **landmarks** between the frontal reference and turned frames (canonical cm) | trial clips: bona fide 1.18, tilted print **0.62**, curved print 0.88: the landmark model's face prior bends a tilted print's points towards a turned head's | replaced |
| 2 | Re-find each rigid point by **texture** (NCC, patch warped by the local homography) | bona fide 0.109, print 0.069 (still close) | built on |
| 3 | Second search around the matches' own homography + RANSAC refit | bona fide 0.082, print **0.017**, 2-D video 0.007, curved 0.053 | yes |
| 4 | First DEV run (parallax ≥ 0.03, live prob ≥ 0.5) | APCER 20% (curved), screen 10%, **BPCER 20%** (6 heads never passed centring) | — |
| 5 | Quality gates: "too dark" on absolute luma rejected dark skin; evenness, face size and brightness too strict | BPCER 20% → **3.3%** | yes (a fairness fix as much as an accuracy one) |
| 6 | Parallax threshold 0.03 → **0.06** (gap between curved prints ≤ 0.051 and heads ≥ 0.080) | curved APCER 20% → 0% | yes |
| 7 | Anti-spoofing decided on the **lowest** sampled frame instead of the mean | screen APCER 10% → 0%, BPCER unchanged (one clip decided it: an overfitting risk, checked on TEST: 0/15 screens passed, closest 0.468) | yes |
| 8 | Weight quantisation: onnxruntime `quantize_dynamic` | LFW 65% (SFace), 50% (mbf) on rten: rten 0.26's `ConvInteger` path diverges from onnxruntime's (cosine 0.09–0.97 per image) | no |
| 9 | Weight-only int8 (int8 weights + `DequantizeLinear`, float32 maths) | cosine ≥ 0.9993 to fp32; LFW 99.52 vs 99.50 | yes (shipped, 9.9 MB) |
| 10 | Alignment points: irises / eye-contour centres / nose point 4 / inner mouth corners (SFace int8, DEV TAR @ 1e-3) | 99.41 / 99.52 / 99.41 / 99.29: one or two pairs apart, inside noise | kept irises (no change) |
| 11 | Flip test-time augmentation (SFace int8) | DEV TAR @ 1e-3 99.41 → 99.52; doubles template time | not by default |
| 12 | MiniFASNet crop box scale on CelebA-Spoof DEV | AUC 0.848 (1.2) → 0.908 (0.55) | reported; not yet in the session (see §2) |
| 13 | Pose: canonical-face fit reads frontal faces 4.2° down (LFW median) | pitch offset +4.2° | yes |

## What blocked SOTA claims

- **Datasets**: CFP-FP, AgeDB-30, IJB-B/C and every presentation-attack
  benchmark except CelebA-Spoof require signed agreements; CelebA-Spoof is
  non-commercial. Liveness could only be measured on synthetic clips, which
  cannot support a published-style claim.
- **Licences**: the best compact recognisers (EdgeFace, InsightFace's packs)
  and anything trained on CelebA-Spoof are non-commercial; the shipped SFace
  has permissive weights but undocumented training data. No public FAS data
  allows commercial training, so the passive model cannot be improved here.
- **Compute**: no GPU; training or fine-tuning a recogniser or FAS model on
  a licensed dataset was out of reach on 12 shared CPU cores in this session
  (and no such dataset was available anyway).
