# Face liveness and verification: patent landscape (engineering notes)

> **Disclaimer.** This is engineering research by the developers, not a legal
> opinion. Nobody here is a patent attorney. Claim scope, validity,
> infringement and expiry can only be settled by a qualified patent attorney
> with the full file histories. **A freedom-to-operate review by a patent
> attorney is needed before any commercial use of this code**, in every
> country where it would be used. Expiry dates are Google Patents'
> "anticipated expiration" and can be wrong (term adjustments, lapsed fees,
> terminal disclaimers).

Written 2026-10-22/23 for the face pipeline in `docscan/src/face/` and the
demo's face screens. It records, for each technique the pipeline uses or
considered, the most relevant patents found, what their independent claims
cover (in plain words), how our approach compares, and the published prior
art. It also records independent development, with dates.

Sources: Google Patents (claims read on the pages linked below, 2026-10-22),
research by the project's agents (2026-10-21/22), and the papers cited.
**South Africa:** no South African family member was found for any of the
US patents below. One iProov patent *is* in force in South Africa:
ZA201704234B (§ 8).

Verdict labels:
- **no relevant patent found**;
- **near a claimed method: different because …**;
- **likely within a claim: not a default** (research-only, behind a flag, off
  by default), or flagged for a decision where it is already part of the
  pipeline.

## Summary

| Technique (where in the code) | Closest patents | Verdict |
|---|---|---|
| 3-D motion: texture points re-found, one homography fitted, a small residual means a flat spoof (`parallax.rs`, the `3d_motion` check) | NEC [US8860795B2](https://patents.google.com/patent/US8860795B2/en); IBM [US9898674B2](https://patents.google.com/patent/US9898674B2/en) | **likely within a claim** (NEC claim 1; IBM claims 10, 13, 16): **off by default since 2026-10-23**, research-only behind `Config::planar_parallax` (§ 1) |
| A rigid 3-D head model fitted to the motion (tried 2026-10-21 as "model-consistent parallax") | IBM US9898674B2 | **likely within a claim**: dropped (2026-10-22), never a default |
| The ring: segments lit when the head's yaw/pitch off neutral exceed a threshold; coverage decides (`liveness.rs`) | Google [US8542879B1](https://patents.google.com/patent/US8542879B1/en) (EP2680191), [US8798336B2](https://patents.google.com/patent/US8798336B2/en) | **near a claimed method**, arguably within claim 1 of US8542879: flagged for a decision, see § 2. Prior art: Frischholz & Werner 2003 |
| ID capture + liveness + document-photo match combined in one decision (demo flow) | iProov [US9621548B2](https://patents.google.com/patent/US9621548B2/en) (asserted in litigation) | **likely within a claim** when the passive check is part of the liveness decision: flagged, see § 3 |
| Passive anti-spoofing CNN on still crops (MiniFASNet) | none found that claims a generic CNN live/spoof classifier on a face crop | **no relevant patent found** |
| Screen colour flash / illumination reflection | iProov [US10133943B2](https://patents.google.com/patent/US10133943B2/en) and family | **likely within a claim**: not implemented |
| Distance / zoom perspective change | FaceTec "path parameters" family (litigated) | **avoid**: not implemented |
| IMU motion correlated with image motion | iProov [US10691934B2](https://patents.google.com/patent/US10691934B2/en); Yoti, Idemia families | **avoid**: not implemented |
| rPPG (pulse from skin colour) | Amazon [US9697414B2](https://patents.google.com/patent/US9697414B2/en) | **avoid as a default**: not implemented |
| Corneal / specular reflection of the screen | Idemia families | **avoid**: not implemented |
| Blink counting (eye aspect ratio), not required by default | many blink-liveness patents; prior art Pan 2007, Kollreider 2007/2009, Soukupová & Čech 2016 | **near**: counted only, not a gate by default |
| Oval guide with positioning hints over the live camera view | iProov ZA201704234B / [US9412169B2](https://patents.google.com/patent/US9412169B2/en) | **near a claimed method: different because** we show the real camera image, not an abstracted one, and show the captured frame (§ 8) |
| Capture integrity: virtual-camera names, frame timing (`FaceLiveness.tsx`) | injection-detection families (not exhaustively searched) | no specific claim found for these heuristics |

## 1. 3-D motion by a homography residual (`parallax.rs`)

**NEC US8860795B2**, "Masquerading detection system…", priority
2008-10-28, active, anticipated expiration **2031-09-22** (12th-year fee
paid 2026-04-08); US and CN family only; never litigated. **Claim 1** (read
2026-10-22): images of the object from a first and a second angle; feature
points detected in both and associated; the second image's points mapped
to the first by a **plane projective transformation** (a homography); and
"masquerading" decided **when the difference between the transformed and
the first points is at or below a threshold**.

**IBM US9898674B2**, "Spoof detection for facial recognition", priority
2015-12-10, active, to **2036-03-29**, US only. Claim 1: instructions to
reorient the head, feature points, displacements, fit to a 3-D surface
model, decision from conformance. **Claims 10 and 16** need no head-turn
instruction: at least four non-coplanar feature points, displacements
between images, whether they conform to a (3-D surface / planar) model,
decide from that. **Claims 12/13**: accept when the fit to the flat model
fails, reject when it conforms.

**Ours:** the `3d_motion` check re-finds ~60 textured points by
cross-correlation, fits one homography with RANSAC and requires the
residual to exceed 0.06 of the eye distance. That is NEC claim 1's test in
substance (with texture matching where NEC detects feature points) and IBM
claims 10/13 with a planar model. **Verdict: likely within a claim.** It was
the default before this review (built 2026-10-20 from Torr's model-selection
literature without knowledge of these patents).

Prior art cited against these ideas: plane-vs-general-motion model
selection, Torr 1998 ("Geometric motion segmentation and model selection",
Phil. Trans. R. Soc.) and GRIC (Torr 1999); Choudhury et al. 1999 (depth
from motion of facial points for person recognition); Bao et al. 2009
(optical flow of a planar vs 3-D face); De Marsico et al. ICB 2012 and Wang
et al. ICB 2013 (geometric invariants / 3-D structure from facial points
for liveness; both before IBM's 2015 priority, after NEC's 2008).

**Decision (2026-10-23):** the check is **off by default**
(`PLANAR_PARALLAX_DEFAULT = false` in `liveness.rs`); the code stays as
research-only behind `Config::planar_parallax`. It was the only geometric
defence against a print bent round a cylinder that completes the ring; its
place is taken by passive anti-spoofing decided across every pose of the
sweep (§ 9), which on the synthetic DEV clips and a further DEV-only set
stops every such print. That replacement is a single, learned signal: a
real print that fools the passive model now meets only the ring, continuity
and identity checks. An integrator with a licence or an attorney's
clearance can turn the check back on.

## 2. The ring (yaw/pitch magnitude against a threshold)

**Google US8542879B1**, "Facial recognition", priority 2012-06-26, active,
to **2032-06-26**, fees paid; EP2680191 validated in DE/GB/FR/NL. **Claim 1**
(read 2026-10-22): two face images; a liveness gesture detected from the
yaw and/or pitch of the second relative to the first; a **liveness score from
the yaw/pitch magnitude**; compared with a threshold; authentication denied
or not on that basis. Dependent claims 4–7 detect the turn from features
appearing or disappearing (one eye, an earlobe, the nose base). **US8798336B2**
(same family) claims a prompted predetermined gesture matched against the
detected yaw/pitch; reported likely lapsed (fees) in August 2026, unverified.

**Ours:** a segment lights when the head's direction off the user's own
neutral pose exceeds 14°; the session requires every segment. That is a
yaw/pitch magnitude compared with a threshold, used to decide. **Verdict:
near a claimed method, arguably within claim 1.** Prior art not cited
against the Google patent: **Frischholz & Werner 2003** ("Avoiding replay
attacks in a face recognition system using head-pose estimation", AMFG
2003: the user is asked to turn the head; the pose is estimated and checked).
Flagged for the FTO review; the ring is the product's interaction and was
not changed.

## 3. Liveness + identity document + match in one decision

**iProov US9621548B2**, "Online pseudonym verification and identity
validation", priority 2013-02, active, to **2033-02-17**. **Asserted** as a
counterclaim in FaceTec v. iProov (D. Nev. 2:21-cv-02252, pending). **Claim
1** (read 2026-10-22): the device's camera captures the user and an identity
document; the user imagery is analysed for presence and no replay, **based in
part on an analysis independent of facial movement**; the document's
biometric (photo) is located and compared with the user imagery; the
likelihood and the match quality together decide validation.

**Ours:** the demo captures the ID with the same phone camera, runs a
liveness session whose decision includes the passive (movement-independent)
anti-spoofing check, matches the session's template to the document photo
and shows both outcomes. **Verdict: likely within claim 1** for that combined
flow. Flagged for the FTO review (no South African member found).

## 4. Passive anti-spoofing CNN

MiniFASNet (Minivision, Apache-2.0) classifies 80 × 80 crops. No patent was
found claiming a generic CNN live/spoof classifier on a face crop; the
2026-10-21 changes (crop box scale, log-odds calibration of the score) are
ordinary model use. **No relevant patent found.**

## 5. Techniques considered and not implemented

- **Screen-light modulation** (iProov "Flashmark"): **US10133943B2**, to
  2033-02-17. Claim 1 (read 2026-10-22): modulate the device's illumination
  (the screen); detect frames whose reflected brightness changes in time with
  it; check the **spatial arrangement** of the changes against what a 3-D
  human face would give; combine. Prior art for screen-reflection liveness:
  Face Flashing (Tang et al., NDSS 2018, arXiv 1801.01949) is *later* than
  the 2013 priority. **Not implemented.**
- **Distance / zoom perspective change** (FaceTec "path parameters"):
  litigated; Jumio's four PTAB challenges failed in June 2026 (on appeal).
  **Not implemented.**
- **IMU-image correlation:** iProov **US10691934B2** (claim 1, read
  2026-10-22: device motion from the accelerometer/gyroscope compared with the
  feature-location changes a static 3-D head would show from the moving
  viewpoint), Yoti and Idemia families. Prior art: Li et al. ("Seeing your
  face is not enough: an inertial sensor-based liveness detection for face
  authentication", ACM CCS 2015), after the 2014 iProov priority. **Not implemented.**
- **rPPG:** Amazon **US9697414B2**, to 2032-01-17; claim 1 (read 2026-10-22):
  a recognised face, then a rate of coloration change matching a human heart
  rate grants access. **Not implemented.**
- **Corneal reflection of the screen:** Idemia families. **Not implemented.**

## 6. Blinks and expression

Blinks are counted (eye aspect ratio, Soukupová & Čech 2016) and required
only if the integrator asks. Blink liveness prior art: Pan et al. ICCV 2007,
Kollreider et al. 2007/2009. Not a default gate.

## 7. Recognition, alignment, document matching

ArcFace five-point alignment, CNN templates and cosine thresholds are
standard; no claim specific to them was found. The document-photo threshold
is a separate DEV-set threshold.

## 8. iProov ZA201704234B (in force in South Africa)

"Real-time visual feedback for user positioning with respect to a camera and
a display", iProov, priority **2014-11-21**, ZA publication 2019-06-26, about
2035. Family: US9412169B2, US10691934B2, WO2016079464, EP3221819, GB2532613,
AU, CA, CN, SG. The ZA claim text was not available online; its scope is
taken from the family's lead claim, **US9412169B2 claim 1** (read
2026-10-22): capture positioning imagery; turn it in real time into
**abstracted** imagery (a partial outline of the face plus anatomical
features inside it) that guides the user to the desired position **without
giving enough visual information to judge the aesthetic quality of their
appearance**; once in position, capture application imagery and pass it to
an application **without displaying it to the user**. (US10691934B2, the
continuation, claims the IMU-motion comparison of § 5.)

**Ours:** the face screens show the **real camera image** (mirrored), with
an oval guide, the ring and text hints ("Move closer", "Centre your face in
the oval"); a mesh outline may be drawn over the real image, but the user
always sees their own face as captured, and the results screen **shows** the
best captured frame. Two essential elements are absent: abstracted imagery
in place of the camera image, and not displaying the captured imagery.
**Verdict: near a claimed method: different because** the preview is the
real image, not an abstraction, and the captured frame is shown. Keep it
that way: replacing the preview with an outline-only avatar, or hiding the
captured image, would move towards this claim. The ZA claims should be
checked by an attorney against the family claim used here.

## 9. Independent development: mechanisms intended to avoid the claims above

Dated record of ideas developed here and their measured results (DEV
only; details in `docs/improvements-face.md`).

| Date | Mechanism | Claims it is meant to avoid | Status / result |
|---|---|---|---|
| 2026-10-21 | Faster texture-parallax search (same homography test) | — (speed only) | kept for the existing check |
| 2026-10-21 | "Model-consistent parallax": measured residual field against a rigid canonical head's predicted field | — | **dropped 2026-10-22**: reads on IBM US9898674 (conformance to a 3-D surface model) |
| 2026-10-22 | **Self-occlusion / visibility**: whether each frontal texture patch is still visible (cross-correlation at its landmark, local affine from neighbouring landmarks) as the head turns, including the points the face mesh itself predicts hidden behind a nearer triangle; no homography, no surface-model fit | NEC claim 1, IBM claims 10/13 | measured on 2 DEV + 10 extra DEV-only clips: heads and curved prints overlap (texture of mesh-predicted hidden points still found 63–73% vs 62–87%); not separating at 20–28° turns. Not adopted |
| 2026-10-22 | **Passive anti-spoofing across poses**: the passive model scored every 250 ms on every pose of the sweep and the finish, decided on the 10th percentile of the samples | uses no geometry, no illumination, no challenge | **adopted as the default 2026-10-23**: DEV + extra DEV-only clips, bona fide ≥ 0.80, completed curved prints ≤ 0.38 (one exception stopped by continuity), screens ≤ 0.01 |
| — | Random whole-face luminance watermark for timing / anti-replay only (no 3-D shape conclusion from the reflection) | iProov US10133943 (its claim needs the spatial-arrangement-vs-3-D-face step) | not built: cannot be measured on the synthetic clips |
| — | Passive capture-provenance statistics (frame-callback metadata consistency, duplicate frames, noise vs exposure) | injection-detection families | not built |
