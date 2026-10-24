# Identity science research and a frozen forensic probe — 24 October 2026

**Outcome: reject the measured candidate.** Illumination-normalized repeated-number
comparison recovers all 96 synthetic DEV exposure/shadow controls, but causes
26 new benign false flags and misses 43 alterations that the raw comparator
detected. Overall correctness increases **329→356/672** while security-relevant
behavior worsens. This is a useful counterexample to treating photographic
normalization as universally helpful. It supplies an executable synthetic
augmentation source and regression set, not an original-versus-copy detector.

Scope: research from merged `004fffc`, shared `improve/originality-optics-research`.
Only `experiments/research_identity_science/**` and this report were authored.
No commits, branches, PRs, delegated agents, production edits, production threshold
changes, or model calibration. No existing TEST/reserved files, truth, caches or
results were listed or read; no private face caches were needed. Raw/generated
pixels, strings, specimen metadata and scores remain owner-private outside git.
No person was identified, no sensitive attributes inferred, and no demographic
metadata used. Public research portraits below are source/provenance references,
not newly acquired biometric data.

The existing `bench/README.md` and `docs/research-2026-*` work informed the design.
The earlier gamma face candidate had mixed tiny gains; the temporal PAD rules
raised replay scores. Repeating those transformations on the same faces would
not establish a new independent capture benefit. The alternative allowed by the
brief—generated stroke/typography forensics—offers a falsifiable new experiment
without additional biometric exposure.

## What the evidence supports

All external technical claims below use primary papers, official evaluations,
or author/maintainer releases checked on **2026-10-24**. A paper's license, code
license, weight license, dataset terms and participant consent are separate facts.
Unknown rights are recorded as unknown; public accessibility is not permission.
[Pinned source notices](../experiments/research_identity_science/source-notices-lock.json)
retain exact revisions and hashes; full notice text stays private. Search-engine
summaries and third-party mirrors were not used as license authority.

### Face verification, quality, illumination and human comparison

- **NIST FATE Quality / Specific Image Defect Detection**, live evaluation page,
  results dated 2026-10-02. Defect-specific assessment and an aggregate utility
  score answer different questions. Its pose measure charges failed detections
  a 45-degree error; excluding failures would improve the displayed error
  artificially. NIST's quality/discard analysis is also not a permission to
  delete unusable attempts from our application denominator. **Our inference:**
  retain an actionable vector—pose, saturation, blur, eye occlusion, exposure—and
  report recapture/abstention alongside fixed-threshold genuine and impostor
  decisions. Do not turn one sharpness scalar into probability of identity.
  [NIST FATE Quality](https://pages.nist.gov/frvt/html/frvt_quality.html).

- **AdaFace** (CVPR 2022; revised 2023) uses a quality-adaptive training margin;
  **MagFace** (CVPR 2021) learns an embedding whose magnitude relates to quality.
  These are learned representation properties. Taking the norm of the existing
  SFace output, especially after normalization, does not implement either method.
  **On the Burstiness of Faces in Set** (2025-06-25) supports diversity-aware
  aggregation and quality-aware generalized max-pooling; it does not show that
  three deterministic gamma views create independent identity evidence. Future
  experiments should cap redundant poses and preserve usable difficult views,
  with all attempts scored at existing 0.356/0.366 operating points. This is a
  proposed direction, not a measured improvement or paper reproduction.
  [AdaFace](https://arxiv.org/abs/2204.00964),
  [MagFace](https://arxiv.org/abs/2103.06627),
  [Burstiness](https://arxiv.org/abs/2506.20312).

- **OFIQ** provides explicit image properties/defects rather than a new identity
  recognizer. Its C++/ONNX implementation is a useful offline measurement
  reference, but its downloaded models have separate licenses. A full browser
  port needs operator, memory and timing checks; native/mobile support does not
  prove WASM viability. Our proposed low-cost capture diagnostics would be a
  separate implementation, not a claim to reproduce OFIQ scores.
  [Author project](https://github.com/BSI-OFIQ/OFIQ-Project),
  [component and model license policy](https://raw.githubusercontent.com/BSI-OFIQ/OFIQ-Project/f903e59e2fe1ac48418d253da8c17592464161d2/LICENSE.md).

- **Illumination robustness is task-dependent.** The face-normalization study
  by Yao/Nagahashi (2015) explicitly asks what should be normalized and compares
  illumination processing choices. Recognition utility is not preservation of
  forensic evidence: removing an ink-density difference can help matching while
  deleting a manipulation cue. Our frozen experiment below tests that distinction.
  Nothing here licenses new face training data or validates restoring detail
  lost to clipping, focus failure or JPEG compression.
  [Primary study](https://globals.ieice.org/en_transactions/information/10.1587/transinf.2014EDP7112/_p).

### Morphs, ghost portraits, reflectance and presentation attacks

- **NIST IR 8584** (2025-08-18) distinguishes single-image morph analysis from
  differential analysis against a known non-morphed capture. Trusted capture
  reduces the risk introduced by user-supplied photographs. An automated morph
  flag is a reason for investigation, not a definitive identity conclusion.
  **Our proposal:** compare the claimed person's consented live capture with
  the primary portrait, and, only on a supported issuer layout, compare the
  secondary/ghost portrait for consistency. Never use a stranger-search gallery.
  [NIST operational report](https://www.nist.gov/publications/considerations-implementing-morph-detection-operations),
  [NIST MORPH evaluation](https://pages.nist.gov/frvt/html/frvt_morph.html).

- A secondary portrait is an issuer-specific feature: official UK guidance
  explicitly discusses ghost images and separate optical/cryptographic checks.
  **Our inference:** agreement between two copied portraits establishes only
  internal agreement; both may contain the same morph. Small monochrome,
  halftoned, embossed or partially occluded secondary portraits also need
  separate benign controls and an explicit unavailable outcome. The ordinary
  face-matching threshold cannot be transferred to ghost portraits without a
  new independent protocol. No ghost-portrait algorithm was run here.
  [Official identity-checking guidance](https://www.gov.uk/government/publications/identity-proofing-and-verification-of-an-individual/how-to-prove-and-verify-someones-identity).

- **Face Flashing** (2018) uses randomized display illumination and measured
  response. This is a different observation from static highlights, which occur
  on paper, laminates, screens and skin. **Browser feasibility inference:** a
  camera/display challenge requires device-specific exposure/white-balance and
  timing evidence, real attack instruments, and bona fide sessions; an uploaded
  JPEG cannot supply it. Neither our procedural images nor the previous replay
  preview has synchronized challenge truth. No active efficacy claim follows.
  [Author paper](https://arxiv.org/abs/1801.01949).

- **Digital and Physical-World Attacks on Remote Pulse Detection** (2021-10-21)
  demonstrates artificial pulse signals, including on 3-D printed face masks.
  **Our inference:** estimating a plausible rPPG signal cannot establish
  liveness or bind a face to the current camera session. Pulse absence can also
  reflect poor acquisition. Do not extract health attributes or use this as a
  standalone acceptance rule. Temporal buffering, compression, motion and
  browser capture timing would need dedicated measurement even for a properly
  licensed local implementation. No physiology or pulse data was processed.
  [Attack study](https://arxiv.org/abs/2110.11525),
  [author rPPG-Toolbox](https://github.com/ubicomplab/rPPG-Toolbox).

### Calligraphy, graphonomics, ink and document typography

- **NIST IR 8282r1** (updated May 2021) describes comparability, natural variation,
  sufficient detail/complexity, manipulation and inconclusive conclusions in
  handwriting examination. A printed font or calligraphic style is not a unique
  writer identifier. **Our inference:** benchmark by writer/session/device,
  compare matched writing types, and include legitimate variations before
  claiming an anomaly detector. This study performs no writer identification,
  signature authentication, personality inference or diagnosis.
  [NIST program](https://www.nist.gov/programs-projects/forensic-handwriting-examination-and-human-factors),
  [full revised report](https://nvlpubs.nist.gov/nistpubs/ir/2021/NIST.IR.8282r1.pdf).

- **The lognormal handwriter** (2013) models strokes through overlapping velocity
  profiles; **Image-driven Robot Drawing with Rapid Lognormal Movements**
  (2025-07-03) combines sigma-lognormal trajectories with differentiable rendering.
  These motivate synthetic stroke formation—pen lifts, curvature, spacing,
  slant and width—rather than arbitrary pixel noise. **Our inference:** a still
  image cannot recover observed pen speed, pressure, stroke order or timing;
  a plausible synthesized trajectory is not evidence of the original writing
  action. Our polylines are deliberately simpler and are not fitted human
  kinematics or a reproduction of either paper.
  [Graphonomic primary study](https://pmc.ncbi.nlm.nih.gov/articles/PMC3867641/),
  [2025 robot-drawing paper](https://arxiv.org/abs/2507.03166).

- **Font forgery detection with a conditional random field** (ICDAR 2015) uses
  neighboring character/font consistency. This is a plausible manipulation cue,
  but legitimate emphasis and mixed typography can produce the same visual
  differences. Our experiment deliberately includes those benign controls; it
  does not train a CRF, recognize fonts, or authenticate a writer.
  [Primary paper](https://doi.org/10.1109/ICDAR.2015.7333827).

- **DocTamper** (CVPR 2023) offers a text-tampering framework; **TDOC** (2026-02-19)
  uses learned crop compatibility and crop-quality filtering to avoid trivial
  synthetic splicing artifacts. Both motivate measuring generation artifacts
  and source leakage, not trusting aggregate synthetic accuracy. TDOC's current
  author README describes the original CVPR Findings acceptance and ongoing
  extension/resubmission; it should not be presented as a finalized main-track
  result. Neither method was reproduced, downloaded as weights, or trained here.
  [DocTamper author release](https://github.com/qcf-568/DocTamper),
  [TDOC paper](https://arxiv.org/abs/2602.17322),
  [TDOC author release](https://github.com/Mohamed-Dhouib/TDOC).

- **Ink forensics needs more than RGB appearance.** The National Center for
  Forensic Science distinguishes microscopic/UV/IR examination from chemical
  characterization such as chromatography. Our synthetic gray-value intervention
  is therefore called an *ink-intensity alteration*, not identification of ink
  chemistry or ink age. Ordinary browser camera RGB cannot reproduce a spectral
  comparator or a destructive laboratory assay.
  [NCFS ink examination](https://ncfs.ucf.edu/research/chemical-evidence/ink/).

## Available assets and rights: code, data and weights separately

| Asset | Code / font terms checked | Data permission and actual availability | Weights / decision |
|---|---|---|---|
| This experiment | Repository MIT; new authored polyline generator, no imported font | All synthetic; generated locally now, owner-private; no third-party source data or publication license asserted | None. Immediately reproducible training-augmentation source, but no training performed |
| Noto Sans | [Author OFL notice](https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/OFL.txt): SIL OFL 1.1 | Font software publicly available; rendered documents are not required to inherit OFL. Preserve font notices and applicable reserved-name conditions | No model. Eligible future synthetic typography asset; font bytes were not downloaded here |
| FRLL London v5 | Author stimulus package notice is not a recognizer license | [Author release](https://github.com/debruine/webmorphR.stim/tree/fa8b78fda2d659bb74ce62fcd99c4407551d2a77): CC-BY, research consent for original/altered images. Existing private 204 portraits only referenced; no new media access | No weights. Could support bounded research verification; does not supply physical ID/selfie or challenge sessions, nor establish commercial biometric-training consent |
| AdaFace / MagFace | [AdaFace MIT](https://github.com/mk-minchul/AdaFace/blob/c60eaa786a42c03444f3df7096dbaf9d57ae010d/LICENSE); [MagFace Apache-2.0](https://github.com/IrvingMeng/MagFace/blob/99bae614ac2643b9694bf18e0c5645272ff6acfa/LICENSE) | README training tables name WebFace/MS1M-family sources; no new data permission established | Author checkpoints linked, but separate checkpoint/underlying data clearance not established. No download or production replacement |
| OFIQ | MIT with component exceptions in pinned license table | Evaluation data are not granted by the code license | Downloaded model terms are explicitly separate and not cleared here. Offline reference only |
| rPPG-Toolbox | [Responsible AI Source Code License v1.1](https://github.com/ubicomplab/rPPG-Toolbox/blob/b7500b848f84ad7f86e277b4612563b69f4f88f9/LICENSE), **not MIT**; use restrictions include identity/attribute inference | Dataset acquisition is separate; no pulse-reference dataset cleared/acquired | Pretrained models are linked, but a separate permissive grant was not verified. Do not import into identity verification on an assumed MIT grant |
| DocTamper | Inference/synthesis code available; no root LICENSE found/verified | Author README requires noncommercial institutional use and an application; original-provider rights retained | Model links exist; separate usable weight license unresolved. Excluded; no agreement/contact/download |
| TDOC / TDoc-2.8M | [Apache-2.0 code](https://github.com/Mohamed-Dhouib/TDOC/blob/c1597c96031786c7261f57bba113ace3010a3b54/LICENSE) | [Author card](https://huggingface.co/datasets/MohamedDhouib1/TDoc-2.8M/blob/ab5ae1cbe09a5f0dc5038ade77ea0ad718257f57/README.md) declares MIT, ~2.8M images / 7.44 TB. Source-document/subject rights still require review; synthetic edits do not clear underlying pages | Author Drive weights linked; no separate weight grant verified. No shards or weights downloaded; investigate generator on wholly authored documents instead |
| NIST SD19 / EMNIST | SD19 page identifies its reference recognition software as public domain; not a blanket grant for unrelated code | Official [SD19](https://www.nist.gov/srd/nist-special-database-19) and [EMNIST](https://www.nist.gov/itl/products-and-services/emnist-dataset) downloads exist. [NIST public-information terms](https://www.nist.gov/copyrights-disclaimers) have copyrighted-material exceptions; an EMNIST-specific standardized license was not verified | No weights. Prefer SD19's writer grouping for a future eligibility review; no forms/characters acquired, and no biometric identity training assumed |
| Sigma-lognormal / CRF-font studies | Paper access established; reusable author code license not verified in this review | No separately cleared experimental corpus acquired | No verified deployable weights. Conceptual stimulus only; our code is independent |

No author paper was treated as a grant to scrape portraits/documents. The IAM
author page failed to load (502); no mirror's license was substituted. The
DocTamper CVF PDF returned 403; its author repository supported the availability
and restriction findings. OFIQ's initial `master` API lookup failed (422), then
the default revision resolved and both notices were pinned; failures are retained.
The initial system Python lacked NumPy; the existing benchmark virtualenv was
used, without installing packages or changing any environment.

## Frozen executable benchmark

[Protocol](../experiments/research_identity_science/protocol.json),
[runner/generator](../experiments/research_identity_science/stroke_consistency.py),
[aggregate results](../experiments/research_identity_science/aggregate-v1.json),
[audit](../experiments/research_identity_science/audit.py),
[reproduction instructions](../experiments/research_identity_science/README.md).

One independently authored baseline and **one** candidate were specified before
inference. The baseline measures the largest per-glyph grayscale RMS difference
between two repeated ten-digit fields. The candidate first fits an illumination
plane to each glyph's empty border and divides the residual by its 95th-percentile
ink depth. Both use the same RMS threshold **0.12**, the same minimum ink contrast
**24/255**, and an explicit abstention if any cell lacks contrast. No threshold
search, model fitting or post-result adjustment was performed.

The equal numeric cutoff is an ablation convention, **not an equal calibrated
operating point**: normalization changes the score scale and removes information.
No production face or originality threshold is represented by this cutoff.

This is an **oracle-crop experiment**: the generator provides paired 40×56 cells,
not a detector or recognizer that found the repeated field. It tests visual
consistency, not OCR accuracy, issuer knowledge, camera tracking or the shipped
verifier. The ten digit skeletons are shared across splits. All styles and camera
profiles are generated; no claim of independent fonts, writers or physical
devices is made. The "calligraphy" control is synthetic slant, not natural
handwriting. Its negative outcome is a design warning, not a human-study result.

There are **96 distinct synthetic specimen keys**, with all fourteen variants
kept together. Four simulated devices own 48 TRAIN specimens; four different
simulated devices own 48 DEV specimens. This produces **672 pairs per split:
384 benign and 288 intervention-labelled attacks**. Device profiles vary blur,
noise and JPEG quality; their parameter ranges overlap across splits. TRAIN is
an unfitted diagnostic/exportable augmentation set, not a fitted calibration
cohort. Label generation and all bytes were frozen before either arm ran.

- Design freeze: **19:50:24.035 UTC** on 2026-10-24.
- Complete data freeze: **19:50:33.658 UTC**; inference starts **19:50:42.316 UTC**.
- Protocol SHA-256: `0b458f4aa4f42966a8e5e453983c3053dd35ec01b1917461753de2b49aab26d8`.
- Runner SHA-256: `32c5d8b24337d9ec8733ce6d1fd2da95f5c5cf7e2b8dfc35f376fee5bcfa0510`.
- Manifest SHA-256: `d518294d3544162c0db0e480a807328eeff4da4d8bbe7f98a55f4643b4ab2416`.

Every pair remains in the denominator. Missing/invalid output is an error;
low contrast is an abstention; neither earns a correct classification or attack
detection. Explicitly clear attacks are reported separately from non-detections
that could include errors/abstentions. No such attack abstentions occurred in
this run. There were no image/inference failures. Input integrity failure aborts
before a partial report can be published.

| Split / metric | Baseline | Candidate |
|---|---:|---:|
| TRAIN correct / 672 | 335 | 355 |
| TRAIN benign clear / 384 | 149 | 211 |
| TRAIN false flags / 384 | 187 | 125 |
| TRAIN attack detections / 288 | 186 | 144 |
| TRAIN attacks clear / 288 | 102 | 144 |
| TRAIN abstentions / 672 | 48 | 48 |
| DEV correct / 672 | 329 | 356 |
| DEV benign clear / 384 | 143 | 213 |
| DEV false flags / 384 | 193 | 123 |
| DEV attack detections / 288 | 186 | 143 |
| DEV attacks clear / 288 | 102 | 145 |
| DEV abstentions / 672 | 48 | 48 |

DEV correct rate rises **48.96%→52.98%**, but **96 recoveries / 69 regressions**
include **26 new benign false flags and 43 new clear attacks**. TRAIN has
**96 recoveries / 76 regressions**, including **34 new benign false flags and
42 new clear attacks**. Reporting only the lower total false-flag count would
hide the new blur errors and the lost ink-intensity evidence. The predeclared
no-regression/no-new-clear-attack gate fails. These counts are not production
FAR/TAR or PAD APCER/BPCER measurements.

Each DEV condition has 48 fixed cases:

| Condition | Truth | Baseline correct / 48 | Candidate correct / 48 | Interpretation |
|---|---|---:|---:|---|
| Clean | Benign | 48 | 48 | Clean oracle crops are easy |
| Exposure | Benign | 0 | 48 | Normalization removes global brightness nuisance |
| Shadow gradient | Benign | 0 | 48 | Border plane removes this designed linear shadow |
| Blur | Benign | 47 | 21 | 26 newly wrong flags; normalization amplifies residual shape differences |
| JPEG | Benign | 48 | 48 | Both tolerate this one compression range |
| Legitimate heavier field | Benign | 0 | 0 | Both incorrectly treat legitimate emphasis as suspicious |
| Legitimate calligraphic slant | Benign | 0 | 0 | Both fail to distinguish allowed style variation |
| Low contrast | Benign | 0 | 0 | Both abstain on all 48; none are silently deleted |
| One changed digit | Altered | 48 | 48 | Geometry mismatch retained |
| One changed digit under shadow | Altered | 48 | 48 | Geometry mismatch retained despite nuisance |
| One heavier digit | Altered | 47 | 47 | One miss retained by both |
| One ink-intensity change | Altered | 43 | 0 | Normalization removes the intervention's cue |
| Both fields replaced consistently | Altered | 0 | 0 | Internally consistent fabrication remains invisible |
| Identical-copy control | Copy | 0 | 0 | No physical originality evidence exists in paired crops |

The identical-copy control deliberately preserves the same signal distribution
as a clean pair; it is **not a simulated physical print/scan chain**. The coherent
replacement changes both copies together. Their misses demonstrate a structural
limit of this input, not a measured attack success rate against real documents.
Neither should be removed to make the candidate look better.

Six focused unit tests pass. A separate audit reconstructed **2,688 arm
predictions**, within 1e-12 numeric tolerance, and all **30 aggregate cells** from
the frozen pixels. It checked 96 specimen groups, eight split-disjoint devices,
all image/source/manifest/output hashes, freeze order and private permissions.
No per-glyph/pair independence confidence intervals are claimed; variants share
specimens, devices and skeletons. This is a designed stress corpus, not a population
sample. There is no native/WASM or phone performance claim.

Browser feasibility is analytical: fixed small grayscale crops, a three-parameter
plane fit, a percentile and RMS require no model download. A bounded worker
implementation is plausible, but localization/alignment and supported issuer
templates are missing. A browser port, mobile parity, latency, allocation and
memory measurements were not run. The current Python generator is an offline
augmentation tool, not a browser feature.

## What to train or collect next

1. **Train on nuisance variation without deleting the evidence being tested.**
   Keep independent channels for geometric mismatch, photometric mismatch and
   capture quality; fit a small classifier only on a new, explicitly frozen TRAIN
   corpus. Include legitimate emphasis, mixed fonts, rubber stamps, faded ink,
   variable pen width and compression as benign controls. Noto OFL fonts plus
   authored documents are an available next augmentation source. Do not recycle
   this DEV outcome into tuning and call the same cases fresh validation.

2. **For face utility, collect consented document/selfie sessions first.** Retain
   whole-identity, specimen, session and physical-device groups. Freeze independent
   genuine/impostor trials and both existing thresholds; charge failures and
   recaptures, report new false accepts individually, and evaluate burst selection
   against the same full attempt denominator. Existing FRLL stills support narrow
   photometric research, not real print-domain adaptation, device generalization,
   physiological PAD or ghost-portrait acceptance. No replacement model is cleared
   by the code-license table above.

3. **For physical originality and portrait ghosts, collect the missing observations.**
   Rights-cleared issuer specimens or fully synthetic templates need original,
   photocopy, reprint and screen presentations of the same content, across
   independent cameras/printers/screens and lighting. Include bona fide laminated,
   matte/glossy and worn documents; synchronize challenge timing where used.
   Ghost consistency also needs annotated primary/secondary regions and legitimate
   rendering differences. Consistency can add suspicion, never prove originality.

4. **For handwriting/graphonomics, group by writer, not page.** Natural variation
   needs multiple sessions, writing instruments, devices and matched character
   types, with explicit consent and eligible use terms. Time/pressure evidence
   requires actual pen trajectories; chemistry requires laboratory observations.
   No generated trajectory, static font or RGB intensity label can substitute.

The measured candidate remains frozen and rejected. Its useful deliverable is a
reproducible, rights-simple source of hard negatives and a demonstrated failure
mode for future fusion research. No shipping change is supported by this study.
