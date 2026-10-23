# Face liveness and verification on the device: research and the chosen pipeline

Written 2026-10-21, before building, and updated with what the measurements
showed (`face/RESULTS.md`). Licences matter as much as accuracy here: the
product may become commercial (a South African retailer), and face images
and templates are biometric special personal information under POPIA s.26.

## The two pointers

**arXiv 2606.26977v1 is not about faces.** It is *"CLIR: Liveness-Driven and
Structure-Aware Fuzzing for the Cranelift Compiler"* (Cao, Song, Yi, Chen, Xu,
He, Wang; 25 June 2026; CC BY 4.0). "Liveness" there is SSA variable liveness
in a compiler: a generator of valid Cranelift IR that tracks which values are
live, which found 24 bugs (21 confirmed, 9 fixed) at 75.1% backend coverage.
Nothing in it applies to biometric liveness; the identifier was probably
mistyped. If a face-liveness paper was meant, the closest 2026 work found is
listed under active liveness below.

**`face_verification_core`** (crates.io, v0.3.0, 2026-06-01, MIT OR
Apache-2.0, 69 downloads, no repository linked; source read on docs.rs):
- runtime: **tract-onnx** (pure Rust) behind a `runtime-tract` feature; without
  it only the deterministic logic builds and the host supplies an `Analyzer`;
  an optional axum server;
- models (all OpenCV Zoo or face-api.js exports): YuNet 2023mar (detector,
  640 × 640), **SFace 2021dec** (recogniser; ArcFace five-point alignment to
  112 × 112, L2-normalised), optional face-api.js 68-point landmarks, a
  MobileFaceNet expression model ("smile" from a mouth-width heuristic),
  MediaPipe hand pose (a finger-count step), an NSFW model; **no anti-spoofing
  model**;
- liveness: six still photos for six challenges (centred, smile, head turns,
  fingers, touch face); checks are distinct hashes, a face in each, embeddings
  within Euclidean 0.45 of the first, poses distinct and matching the step.
  No temporal or 3-D consistency: a set of six photos, or a deepfake, passes;
- wasm: recommended but its own roadmap says the wasm benchmarks are not done
  and that producing the inputs from raw images is still pending;
- no accuracy figures, model licences "to be documented".

Its useful contribution is the pointer to OpenCV Zoo's SFace and YuNet, whose
weights are permissively licensed. Its liveness design is the weak point this
work avoids: still photos with per-step pose checks prove nothing about 3-D.

## 1. Detection, dense landmarks and head pose on the device

| Model | Params / size | Output | Browser runtime | Licence (code / weights / data) | Notes |
|---|---|---|---|---|---|
| **MediaPipe BlazeFace short-range** | ~0.1 M, 224 KB tflite (fp16), 0.4 MB ONNX | box + 6 keypoints, 128 × 128 | rten (converted with tf2onnx; ops: Conv, Pad, MaxPool, Relu, Add, Reshape, Concat, Transpose), or MediaPipe tasks-vision | Apache-2.0 / **Apache-2.0** (model card) / Google's own | for faces within ~2 m; ~4 ms natively |
| **MediaPipe Face Mesh V2** (Face Landmarker) | 2.5 MB tflite, 4.9 MB ONNX | 478 points (468 + irises), x, y and a z learned from synthetic data; a face-presence score | rten (Conv, PRelu, Add, MaxPool, Pad, Reshape, Sigmoid) | Apache-2.0 / **Apache-2.0** (model card, 2022) / Google's own | fairness evaluated over 17 regions incl. Southern Africa; out of scope: yaw > 80°, recognition; ~16 ms natively |
| MediaPipe blendshapes | 0.9 MB tflite | 52 ARKit-style coefficients (blinks, smile) | rten (converted, runs) | Apache-2.0 | not needed: the eye aspect ratio from the mesh gives blinks |
| SCRFD (InsightFace) | 0.5–10 GF | box + 5 points | rten (runs) | MIT / **non-commercial** / WIDER FACE | avoid (weights licence) |
| YuNet (OpenCV Zoo) | ~75 k params, 0.2 MB | box + 5 points | rten (runs) | MIT / MIT / WIDER FACE (research) | a permissive alternative detector |
| 3DDFA-V2 / V3 | 3.3 M (V2) | 3DMM fit | ONNX | MIT / MIT / BFM basis **non-commercial**; V3 also needs nvdiffrast (NVIDIA NC) | avoid |
| SPIGA | — | 98 points | — | BSD-3 / trained on 300W, WFLW, COFW (academic) | not needed |

**Chosen:** BlazeFace short-range to find the face, Face Mesh V2 to track it
(each frame's crop comes from the last frame's landmarks, so the detector runs
only when the face is lost, and every sixth frame to count faces), both on
rten inside the same wasm as the rest of docscan. Head pose is a similarity
fit of MediaPipe's canonical face (468 vertices, Apache-2.0) to the predicted
3-D points (Horn's method). Every op in both models is one rten 0.26 already
implements, so neither onnxruntime-web nor tasks-vision was needed.

## 2. Active liveness

What vendors do:
- **FaceTec**: an oval that grows as the phone comes closer; perspective
  distortion between the far and near frames shows a 3-D face (a flat
  photo or screen does not distort that way) (FaceTec whitepaper).
- **iProov Flashmark**: the screen flashes a server-chosen colour sequence; the
  face must reflect it, a one-time code that cannot be replayed. The academic
  analogue is *Face Flashing* (Tang et al., NDSS 2018, arXiv 1801.01949: 98.8%).
- **Head-turn rings** (the Sumsub / Onfido / Apple Face ID enrolment pattern):
  turning the head round a circle; the ring both guides the user and makes
  the system see the face from many directions.

What makes a sweep a liveness test, not just a gesture test:
- **Rigid 3-D consistency.** A flat photo or screen, however it is moved or
  tilted, moves all its points by one homography between two views; a real
  head turning shows parallax (the nose moves against the cheeks and ears)
  that no homography explains. This is textbook two-view geometry
  (homography vs fundamental-matrix model selection, e.g. Torr's GRIC); no
  2023–2026 paper was found that packages it for head-turn liveness, so it is
  implemented here from first principles.
- **Do not trust the landmark model's z, or even its 2-D points, for this.**
  Face Mesh V2's z is a prior learned from synthetic data (its model card says
  so), and measured here, its 2-D points on a steeply tilted photo also drift
  towards where a *turning head's* points would be. The landmark-only
  homography residual separated a tilted print from a real head poorly
  (`face/RESULTS.md`). The fix used here re-finds each rigid point by its
  texture (normalised cross-correlation of a reference patch warped by the
  local homography), which follows the pixels, not the model's prior.
- **Blinks** (eye aspect ratio, Soukupová and Čech, CVWW 2016) and expression
  changes are cheap supporting signals; a printed photo cannot blink, but a
  video replay can.
- **Replays and injection.** A replayed video of a real person turning shows
  real parallax, so geometry alone cannot stop it: the passive model (screen
  moiré, bezels, colour cast) and capture-integrity checks have to. In the
  browser: virtual-camera names in `MediaStreamTrack.label` (OBS, ManyCam,
  v4l2loopback, …), frame timing from `requestVideoFrameCallback` (stalls,
  frames out of order), and, beyond this demo, a server-issued challenge
  (random ring start, Flashmark-style screen colours) and server-side
  re-verification of a few signed frames. A client-only check can always be
  patched by an attacker who controls the browser; CEN/TS 18099:2024
  (injection attack detection) and the forthcoming ISO/IEC 25456 set out how
  to evaluate this.
- Field reality: commercial PAD error rates rose about 4× in low light and 2×
  with auto-capture in a 2026 DHS evaluation (arXiv 2602.00109); LiveBugger
  (USENIX Security 2022, arXiv 2202.10673) found most commercial liveness APIs
  lacked deepfake detection. A-Live (arXiv 2606.05126, June 2026) uses phone
  IMU micro-motion, available in the browser as `DeviceMotionEvent`, a good
  next signal.

**Chosen:** a centring step, then a ring of 12 segments (8 for the quicker
returning-user pass) lit by the direction the face points, relative to the
user's own neutral pose (a phone's camera sits above the screen); then a
look-straight finish. Checks: ring coverage; texture parallax (3-D motion);
the passive model on near-frontal frames; continuity (no splice-like jumps,
gaps, extra faces, out-of-order timestamps); identity (the face after the
sweep matches the face before it); blinks counted (required only if asked);
and in the browser, capture integrity.

## 3. Passive face anti-spoofing

| Model | Size | Licence (code / weights / data) | Published |
|---|---|---|---|
| **MiniFASNetV1/V2/V1SE** (Minivision Silent-Face-Anti-Spoofing) | 0.41–0.44 M params, 0.08 GFLOPs, 80 × 80 | Apache-2.0 / **Apache-2.0** (in the repo) / proprietary | 97.8% TPR at FPR 1e-5 on Minivision's own set (their better model is not released); no public-benchmark numbers |
| light-weight-face-anti-spoofing (MobileNetV3) | small | MIT / trained on **CelebA-Spoof (non-commercial)** | CelebA-Spoof AUC 0.998, EER 2.26% (intra-dataset) |
| CDCN / CDCN++ (CVPR 2020, arXiv 2003.04092) | 2.3 M | repo licence unclear / — | OULU-NPU P1 ACER 0.2% |
| DeepPixBiS (ICB 2019, arXiv 1907.04047) | DenseNet-161 trunk | Idiap | OULU P1 ACER 0.42% |
| FLIP (ICCV 2023, arXiv 2309.16649) | CLIP ViT-B/16 | — | MCIO leave-one-out mean HTER 3.01%; too large for a phone |
| AENet (CelebA-Spoof paper, ECCV 2020) | ResNet-18 | trained on CelebA-Spoof | intra-dataset |

Intra-dataset numbers (OULU P1 ~0.2–0.4% ACER) are saturated; cross-dataset
HTERs of 3–30% are the realistic picture. **Chosen:** MiniFASNet, the only
small model with permissive weights, as one signal among several, not the
gate. Every public FAS dataset is non-commercial; the only clean route to a
better model is consented data of our own.

## 4. Face recognition, compact models

| Model | Params / MFLOPs | LFW / CFP-FP / AgeDB-30 | IJB-C TAR@1e-4 | Licence (weights) | Data |
|---|---|---|---|---|---|
| MobileFaceNet (arXiv 1804.07573) | 0.99 M / 439 | 99.55 / — / — | — | paper | MS-Celeb-1M (withdrawn) |
| InsightFace w600k_mbf | ~2 M / 450 | 99.70 / 98.00 / 96.58 | 95.02 | **non-commercial** | WebFace600K |
| InsightFace w600k_r50 | 43.6 M | 99.80 / 99.20 / 98.10 | 97.12 | **non-commercial** | WebFace600K |
| EdgeFace-XS γ0.6 / -S γ0.5 (arXiv 2307.01838) | 1.77 M / 154; 3.65 M / 306 | 99.73 / 94.71 / 96.08; 99.78 / 95.74 / 97.03 | 94.85; — | **CC BY-NC-SA 4.0** | WebFace260M subsets |
| SFace (OpenCV Zoo; arXiv 2205.12010) | MobileFaceNet-style, 38.7 MB fp32 | 99.40 (zoo; int8 99.32) | — | **Apache-2.0** | **undocumented** |
| GhostFaceNets | 0.5–2 width | up to 99.77 / 96.83 / 98.0 | — | MIT label | MS1MV2/V3 |
| AdaFace (R18–R100) | — | R100 mean 97.55 over 5 sets | 97.66 (WebFace12M) | MIT label | research-only data |
| FaceNet (facenet-pytorch, VGGFace2) | 23.5 M | 99.65 | — | MIT (port) | VGGFace2 (withdrawn) |
| dlib ResNet-29 | — | 99.38 | — | "public domain" | scraped |
| Synthetic-only training (DCFace, HSFace/Vec2Face, SDFR 2024 winners) | — | 98.3–98.9 LFW, 85–89 CFP-FP | 81 (SDFR) | mixed; generators trained on research data | — |

Quantisation: SFace 99.40 → 99.32 (int8) in the zoo; MobileFaceNet post-
training int8 99.45 → 99.36–99.48 (EasyQuant, arXiv 2006.16669); QuantFace
(arXiv 2206.10526) calibrates with synthetic faces.

**Chosen:** SFace, the only compact recogniser with permissively licensed
weights, its weights stored as int8 for a 9.9 MB download; InsightFace's `w600k_mbf` and
EdgeFace benchmarked alongside as the research-only reference. No model with
code, weights and data all commercially clean exists (see `face/MODELS.md`
for the paths to one).

## 5. Matching a live face to an identity document's photo

- **DocFace** (arXiv 1805.02283): a domain-specific matcher lifts TAR at FAR
  0.1% from 61.14% to 92.77% on private ID–selfie pairs. **DocFace+**
  (arXiv 1809.05620): 95.95% TAR@FAR 1e-4 vs 88.78% for an off-the-shelf
  InsightFace model, by fine-tuning a pair of domain networks.
- The difficulty is the document side: a small, printed (often greyscale and
  laser-engraved, as on the SA smart ID card), halftoned photo under holograms
  and glare, often years older than the holder. There is no public ID–selfie
  dataset; vendors calibrate on their own.
- Quality assessment: OFIQ (BSI's reference implementation of ISO/IEC
  29794-5; code MIT, commercial use allowed) defines the individual measures;
  its unified score uses MagFace (MS1MV2-trained). CR-FIQA (CC BY-NC) and
  SER-FIQ (CC BY-NC-SA) are non-commercial; eDifFIQA has CC-BY-4.0 weights.

**Chosen:** the document's flattened image (from docscan's own document
capture) searched for its largest face at several scales; OFIQ-style
individual quality measures (size, pose, exposure, evenness, sharpness, eyes
open) computed from the landmarks; the same recogniser; and a separate,
lower threshold for document-to-live, set on a DEV split of synthetic ID-photo
renders of LFW pairs, because a printed ID photo of the same person scores
lower.

## The pipeline

```
camera frame (front camera, mirrored preview)
  └─ BlazeFace (when the face is lost, and every 6th frame)  ──┐
  └─ Face Mesh V2 on the tracked crop → 478 points, presence ◄─┘
       ├─ head pose (canonical-face fit)       → ring segment, hints
       ├─ quality (size, light, sharpness, eyes, pose)
       ├─ texture parallax vs the frontal reference → 3-D motion
       ├─ MiniFASNet pair on near-frontal frames → passive score
       └─ ArcFace 5-point alignment → SFace (int8 weights) → 128-d template
            (centre and finish phases: identity check, enrolment template)
browser: camera label, frame timing (requestVideoFrameCallback) → integrity
```

Everything runs in one wasm (docscan, Rust, rten) in a Web Worker; nothing
leaves the device; models are served from the app's own origin.


## 2026-10-23: verification boundaries and the remaining evidence gap

A sweep with missing anti-spoofing or recognition models previously omitted
those checks. It now reports both as required failures. Invalid templates
(empty, zero, non-finite, or different dimensions) cannot match; the demo
also checks model names before comparing embeddings. A successful liveness
session with a failed or missing face match now emits `passed: false` on the
verification completion event. These are acceptance-boundary corrections;
no recognition/PAD model or decision threshold changed in this correction.

The current [NIST identity-proofing guidance](https://pages.nist.gov/800-63-4/sp800-63a/ial-general/)
separates remote presentation-attack detection from sensor integrity and
injected-media protection. It requires standardized PAD performance testing;
a browser head-turn demonstration is not evidence that those requirements
are met. Our concrete corrections close fail-open paths but do not provide
sensor attestation or deepfake detection.

The next model-quality milestone needs representative real document/selfie
pairs and real presentation attacks across devices and demographics, with
independent evaluation. The existing DEV document pairs are synthetic
print/capture transforms of LFW; active-liveness clips are procedural heads.
The CelebA-Spoof metric is an image-level result at calibrated score 0.5;
it is not the session-level operating point (a higher score and a low
quantile across frames). Its model score remapping does not establish that
the score is a calibrated probability in the target deployment. Do not
present these benchmarks as production FAR, certified PAD, or frontier
performance. No TEST results were used to choose these corrections.

Regression checks: `cargo test --lib face::` under `docscan/`, and
`node --test demo/test/face-matching.test.mjs` from the root (Node 22.18+ for
native TypeScript stripping), followed by the unchanged DEV benchmark.


The recovered full DEV runs audit the preceding crop and session-default
experiment (parallax off, not the final shipped setting) with the unchanged referee: `5196114514` (same face
source and model configuration as `6070c92`/main) versus `8d801ae52d`.
`bench/compare.py` reports **improved**, with no significant regressions:
image-level PAD AUC 85.76% → 90.77% (paired 95% CI for the difference
+4.09 to +5.98 percentage points), APCER 32.66% → 24.43% (difference CI
−9.86 to −6.37 points), and ACER 21.62% → 17.32%. Recognition and synthetic
session outcomes are unchanged within their intervals. This supports the
measured improvement on DEV, while the remaining image-level attack
acceptance rate still prevents a strong deployment-security claim.
The geometric check's patent discussion remains a research concern, not
a legal clearance; no freedom-to-operate conclusion follows from these tests.


Final integration preserves the physical parallax check by default, alongside
the improved learned PAD. The full DEV comparison above is the historical
no-parallax ablation; it does not measure the final enabled-parallax default.
Final-config quick DEV evidence is recorded separately in `bench/results/`.
