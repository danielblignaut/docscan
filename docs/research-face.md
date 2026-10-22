# Face: research and the improvement plan (2026-10-21)

The starting point is `face/RESEARCH.md` (the original choices) and
`face/RESULTS.md` (their measurements). This file collects what was read for
the second round of improvements, the ideas it produced, their expected
effect and cost, and the order they were tried in. What each idea measured on
DEV, and whether it was kept, is in `docs/improvements-face.md`.

The referee is `bench/` (`bench/run.sh --suite face`): LFW View 1 (DEV),
document-photo pairs (DEV), CelebA-Spoof DEV (passive anti-spoofing at 0.5),
the synthetic liveness clips (DEV), and the native liveness frame time.

## What was read

### Passive anti-spoofing (FAS)

- **Survey of the state of the open models.** Every small FAS model with
  public weights is either MiniFASNet (Minivision, Apache-2.0 weights) or
  trained on a non-commercial dataset (CelebA-Spoof, OULU-NPU, SiW, CASIA-SURF:
  all research-only or behind an EULA). An independent 2026 comparison of
  open liveness models on a common wild set (axonlab.ai, "Best open-source face
  liveness detection models 2026") found none at iBeta level 1, MiniFASNet's
  BPCER the lowest of the open ones and its ACER high: the same picture as
  here.
- **Domain generalisation** (FLIP, arXiv 2309.16649; IADG, arXiv 2304.05640;
  the 2025 reinforcement-fine-tuning method, arXiv 2506.21895; the 2026 vision
  foundation-model benchmark, arXiv 2604.19196, and linear-probing benchmark,
  arXiv 2607.26993): the best cross-domain numbers come from CLIP/DINOv2-scale
  backbones (ViT-B, 86 M parameters and more). Distilling one into an
  80 × 80 student needs FAS training data, and all of it is non-commercial,
  so a distilled student would be research-only. Not pursued for the shipped
  path.
- **Flow augmentation and distillation for lightweight PAD** (arXiv
  2605.13108) and depth-supervised distillation: training-time ideas, same
  data problem.
- **Test-time ideas that need no training**: horizontal-flip averaging and
  multi-scale crop averaging (standard test-time augmentation; for FAS, the
  MiniFASNet pair is itself a two-scale ensemble), choosing the crop that
  matches the training distribution (the models were trained on boxes from
  Minivision's own detector, not on a mesh's extent), temporal fusion over
  several frames of a video (Multi-Frames Temporal Abnormal Clues, arXiv
  2208.04076; most video FAS uses the mean or a robust aggregate of frame
  scores), and calibrating the score so the decision threshold sits where the
  error rates balance.
- **Screen-flash / reflection liveness**: Face Flashing (Tang et al., NDSS
  2018, arXiv 1801.01949: random colours on the screen, the face's reflected
  light as the response, 98.8%); LiveScreen (chromatic eigenspace of the skin's
  response to small screen changes; 97.7% on smartphones); "Enhancing Mobile
  Face Anti-Spoofing ... under Screen Flash" (arXiv 2308.15346); specular
  and diffuse reflection under a white screen flash (arXiv 1907.12400). In
  the browser the page controls the screen colour and reads the camera, so
  it is feasible, but auto-exposure and white balance fight the response and
  it needs a dark-enough room; it cannot be measured by the current
  synthetic clips (they have no light response), so it is a design note, not
  a change here.

### Active liveness

- Rigid 3-D consistency: homography vs. fundamental-matrix model selection
  (Torr's GRIC); already implemented as texture parallax. Margins on the
  synthetic attacks were thin (`face/RESULTS.md` §3). Candidate strengthening:
  aggregate more turned frames (every turned frame, not every other one),
  use both parallax and the share of RANSAC outliers, and the angle
  dependence (parallax grows with the turn for a head, not for a plane).
- Blinks (eye aspect ratio; Soukupová and Čech, CVWW 2016) are counted;
  requiring one would add 1–2 s for users and stops only static prints, which
  the ring already stops.
- Injection / virtual cameras: CEN/TS 18099:2024; the demo checks camera
  names and frame timing. A-Live (arXiv 2606.05126) correlates IMU
  micro-motion with the image: `DeviceMotionEvent` in the browser.

### Recognition and the commercial licence gap

- Synthetic-data recognisers have closed most of the gap on LFW (VIGFace
  99.48, UIFace 99.38, MorphFace 99.35; the 2025 review arXiv 2510.17372),
  **but every such generator was itself trained on research-only face data**
  (WebFace4M/42M, CASIA-WebFace, FFHQ under CC BY-NC-SA), and the datasets
  are released under non-commercial terms (DigiFace-1M: R-UDA; Microsoft
  Face Synthetics: research use; CounterFace: forbids training). No
  commercially usable identity-labelled training set was found; FairFace
  (CC BY 4.0) has no identity labels. OpenCV's SFace training data is still
  undocumented (opencv_zoo#313 open, unanswered on 2026-10-21).
- So the licence gap cannot be closed by training here. What can be improved
  without a new model: template aggregation over several liveness frames,
  flip averaging, and quality-aware frame choice.

### ID photo vs. live

- DocFace / DocFace+ (arXiv 1805.02283, 1809.05620): domain-specific
  fine-tuning on private ID–selfie pairs; not possible without data.
- Test-time handling of the document side: print/halftone noise suppression
  before the recogniser, greyscale matching (an SA smart ID photo is grey; the
  live side can be compared in grey too), flip averaging (the product already
  does it for the document photo; the bench's `embed --largest` did not).

## Ideas, expected effect and cost, in the order tried

| # | Idea | Expected effect | Cost |
|---|---|---|---|
| 1 | FAS: crop box scale (0.55 of the mesh box was best on CelebA-Spoof DEV in round one) applied in the shipped code, with a calibrated decision so 0.5 is the balanced threshold | ACER at 0.5 down several points | none at run time |
| 2 | FAS: horizontal-flip averaging; multi-scale crop averaging | AUC up a little | 2× the FAS model (0.5 ms natively) |
| 3 | FAS: crop from the detector's box vs the mesh's | unknown | none |
| 4 | Liveness: robust multi-frame FAS fusion (low quantile rather than the minimum) | wider bona fide margin | none |
| 5 | Speed: parallax grey image over the face only, not the whole frame | lower liveness frame time | none |
| 6 | Speed: recognition templates only for frames that can be kept | fewer model runs | none |
| 7 | Document photo: flip averaging in the photo path the bench measures; grey/denoise normalisation | TAR at FAR 1e-3 up | 2× template on one still |
| 8 | Liveness margins: measure on an extra DEV-only synthetic set (new seeds) | evidence | CPU |
