# Face research: temporal evidence, quality and efficient models

Research date: **2026-10-24**. Baseline: `dd96ed0`. Scope: local docscan,
`experiments/research_face/**` and this report only. No production face code,
threshold, calibration, common scorer, Cargo file or example was changed.
No new agents, dataset access agreements, paid services or author contact.

**Outcome: no production change supported.** A frozen temporal/quality experiment
ran on the five authorized DEV replay videos: all four candidates retain 0/5
attack crossings at both existing raw thresholds, but both new block-based rules
raise the replay score in every clip relative to a framewise lower quantile.
This is a negative feasibility/utility result, not evidence of improved PAD.
Genuine temporal BPCER and active efficacy remain unavailable.

The useful new research directions are FaceLiVTv2's efficient inference,
representation burst suppression, explicit compression quality, and rigorous
separation of capture quality from spoof evidence. Model/data rights and the
absence of real challenge-following bona fide DEV videos block stronger claims.

## Evidence and access discipline

Read `bench/README.md`, `docs/research-face.md`, `docs/improvements-face.md`, the
public-face README, evaluator and provenance helpers, prior aggregate reports,
and the relevant native quality/PAD interfaces, and `face/MODELS.md`. The existing six alignment
experiments are context, not rerun or selected here. No TEST/reserved media,
truth, caches or results were opened. No new portrait inference, validation-set
selection, calibration, model fitting or synthetic seed search was performed.

Searches covered arXiv/public internet for 2024–2026 efficient recognition,
ID/selfie domain shift, quality and fusion, PAD generalization, temporal/rPPG and
active challenges. Secondary search hits were discovery leads only: technical
claims below refer to papers or author/maintainer releases. This is a targeted
survey, not a claim to exhaust the literature. Dates distinguish first preprint
from revision/publication; a day is not invented where only a month is known.
All URLs below were checked on **2026-10-24**. Some CVF direct opens returned 403;
the primary CVF indexed paper/abstract supplied the cited document findings.

[Source-notice lock](../experiments/research_face/source-notices-lock.json)
records immutable repository/card revisions, exact raw URLs and hashes. Complete
notices stay locally under `/tmp/docscan-public-data/research-face/source-notices/`.
No copied paper text, photos, videos or embeddings are included in git.

A code license, a checkpoint's stated license, a dataset's use terms and a
participant's consent are four separate facts. A permissive repository or model
card does not establish consent for commercial biometric training. An arXiv
article license is not a model/data license. Unknown rights below mean
**unresolved**, not implicitly permissive and not a blanket legal conclusion.

## Evaluation data and existing inference assets

The measured data are the [Axon Labs display-replay public preview](https://huggingface.co/datasets/AxonData/Display_replay_attacks/tree/f5560f659e185ded62c2f09ff502426b0588406e),
with a **CC-BY-4.0 dataset-card tag**, not a license to the full commercial corpus.
The [owner repository](https://github.com/axonlab-data/face-anti-spoofing-dataset/blob/e0c8bf8d0b3419806825bbc319575c05a17ca240/README.md)
states participant consent; its [evaluation card](https://huggingface.co/datasets/AxonData/liveness-detection-dataset/blob/c28f25c20328748b77c794853134e009df3b36fa/README.md)
describes public evaluation samples. Use here is local research evaluation only;
no commercial training-consent inference and no redistribution. Reuse of all
five existing attacks was fixed before this run; five still selfies were not
used as substitutes for videos.

FRLL is the [DeBruine/Jones London Set v5](https://doi.org/10.6084/m9.figshare.5047666.v5)
(2017), CC-BY-4.0, with research participant consent documented by the
[author release](https://github.com/debruine/webmorphR.stim/tree/fa8b78fda2d659bb74ce62fcd99c4407551d2a77).
It was context only in this loop; no portraits or embeddings were opened.
The repository's procedural DEV is generated test data, not a study of live
human physiology. No newly accessed LFW, CelebA-Spoof or gated PAD data were used.

The original inference used the shipped BlazeFace, mesh and MiniFASNet assets;
all model hashes, including the original directory's SFace model, are recorded
and verified. This task added no model weights. Existing inventory is
[`face/MODELS.md`](../face/MODELS.md): MediaPipe model cards and MiniFASNet's
[author release](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/tree/b6d5f04ad78778917853b25c778acef6d5626d15)
record Apache-2.0 assets, with unpublished training provenance. SFace is also
listed there as Apache-2.0 weights with unresolved training provenance; its
presence in the hash inventory does not mean recognition was run in this loop.
We do not treat these inherited model-license records as new clearance of
training consent. The experiment itself has no trained weights/data license.

## Recent research and feasibility

### Efficient recognition and document/selfie shift

| Primary source and date | Evidence relevant to docscan | Code, weights and data | Local-browser assessment / decision |
| --- | --- | --- | --- |
| [EdgeFace](https://arxiv.org/abs/2307.01838v2), first 2023-07-04, revised 2024-01-12; [author release](https://github.com/otroshi/edgeface/tree/ce86851cfc37979a9cd2558598d0e9bc592cbba3) | Hybrid CNN/Transformer with low-rank linear layers; the paper's XS model has 1.77M parameters. Useful compact-model comparator, not new evidence about this app's low-FAR operating point. | Code LICENSE is BSD-3-Clause; the [official Idiap XS checkpoint card](https://huggingface.co/Idiap/EdgeFace-XS-GAMMA) explicitly states **CC-BY-NC-SA-4.0**, separately pinned in the source lock. Paper training uses WebFace; this survey does not establish commercial data rights. Do not substitute a third-party export's permissive label for the author weight terms. | Potentially small enough for local inference, but operator export, quantization, peak memory and mobile browser timing remain untested. No weights downloaded or promoted. |
| [FaceLiVT](https://arxiv.org/abs/2506.10361v1), 2025-06-12; [FaceLiVTv2](https://arxiv.org/abs/2604.09127v1), 2026-04-10; [author repo](https://github.com/novendrastywn/FaceLiVT/tree/d99d86607c7c05540c74e815e5a88847f7e667db) | Linear attention and reparameterized local/global interaction; v2 uses Lite MHLA and RepMix. The reported mobile-latency improvements are the authors' hardware/protocol results, not a WASM speed prediction. | Repo BSD-3-Clause plus separate InsightFace MIT notice. [Author weight card](https://huggingface.co/novendrastywn/FaceLiVT/blob/cec8aee5341fb4fede121a960a418b9e6163cc5c/README.md) states CC-BY-SA-4.0 in its body, although YAML metadata is malformed/missing. Repo identifies Glint360K training and optional WebFace4M/12M. [InsightFace policy](https://github.com/deepinsight/insightface/tree/c6c3af7bd2d0a0bf4b78c78437357f3521aa5d52) restricts its provided training data/models to noncommercial research. The differing declarations do not resolve the downstream training/consent question. | Best new architecture candidate for a **future isolated export/latency study**. Reparameterize first; establish numerical equivalence before INT8 and browser profiling. No checkpoint loading, production replacement or use of London portraits to tune quantization here. |
| [xEdgeFace](https://arxiv.org/abs/2504.19646v1), 2025-04-28; [full paper](https://arxiv.org/html/2504.19646v1) | Compact cross-spectral adaptation across thermal/NIR/visible domains. Relevant analogy for separating acquisition domains, but a spectral gap is not the printed-ID/selfie gap. | Paper CC-BY-NC-ND; that does not license weights. A release/checkpoint-specific grant was not verified (a guessed author-repo URL returned 404). Paired heterogeneous training data require separate permission; none acquired. | Adaptation could retain a compact inference backbone, but still needs eligible paired data. Do not claim exact reproduction or transfer its numbers to ID verification. |
| [Moussa et al., Face-swapping based Data Augmentation for ID Document and Selfie Face Verification](https://openaccess.thecvf.com/content/WACV2025W/SynRDinBAS/papers/Moussa_Face-swapping_based_Data_Augmentation_for_ID_Document_and_Selfie_Face_WACVW_2025_paper.pdf), WACV Workshops, **February 2025** (day not established) | Document-style banks plus face swapping augment training; experiments include proprietary real-world ID/selfie data and skin-tone analysis. Stronger domain motivation than merely adding more landmark variants. | No cleared deployable weights, reusable proprietary pairs or dataset license were established from the paper. Public article access is not a face-data grant; synthetic outputs do not erase generator/training restrictions. | Training-time method, not a preprocessing filter. Rejected for this loop: no eligible paired production-training data or generator-rights chain. Inspired suggestion: consented document capture stress evaluation, not face-swapping London research portraits into production training. |

### Face quality and fusion

| Primary source and date | Evidence | Rights / inference practicality | Decision |
| --- | --- | --- | --- |
| [On the Burstiness of Faces in Set](https://arxiv.org/abs/2506.20312v1), 2025-06-25; [method](https://arxiv.org/html/2506.20312v1) | Repeated attributes/frames can dominate set representations. Self-similarity and generalized max-pooling suppress bursts; quality-aware GMP counters the tendency to overweight unusual low-quality frames. | Paper uses an arXiv distribution license; no released model/data grant verified. Its learned quality/recognition components are not reproduced. Dense GMP needs an inverse over the set, unlike a small bounded streaming buffer. | Inspired our cheap equal-time-block ablation. **Not QA-GMP**: time bins do not identify representation similarity, and PAD scores are not identity embeddings. A useful next FR experiment is a fixed time/pose diversity cap, once real eligible sequences exist. |
| [Deep Learning-based Compression Detection for explainable FIQA](https://arxiv.org/abs/2501.03619v1), 2025-01-07, associated with FAIRBIO/ICPR 2024; [OFIQ](https://github.com/BSI-OFIQ/OFIQ-Project/tree/f903e59e2fe1ac48418d253da8c17592464161d2) | EfficientNetV2 learns JPEG/JPEG2000 artifact severity from PSNR/SSIM labels. Explains why recognition utility is richer than one sharpness scalar. | OFIQ code is MIT with component exceptions. [License table](https://github.com/BSI-OFIQ/OFIQ-Project/blob/f903e59e2fe1ac48418d253da8c17592464161d2/LICENSE.md) explicitly puts downloaded model terms in separate model directories; model licenses/training consent were not cleared here. | Could provide actionable capture diagnostics; full C++/ONNX pipeline and model costs need browser profiling. Our Laplacian proxy is **not** this trained method. Do not discard blurry attack frames and thereby make attacks look more live. |
| [ViTNT-FIQA](https://arxiv.org/abs/2601.05741v1), 2026-01-09; [author code](https://github.com/gurayozgur/ViTNT-FIQA/tree/4e9cdd60fe7e1da0cb0f4eebf827f660fe64d957) | Single-pass, training-free quality from the stability of normalized patch embeddings between ViT blocks. | Code CC-BY-NC-SA-4.0. The documented pretrained backbone is AdaFace ViT-Base trained on WebFace4M; code permission does not clear those weights/data. | Concrete incompatibility: current SFace CNN interface exposes final embeddings, not intermediate ViT patch tokens. Rejected as a drop-in cheap quality calculation; changing backbones is a separate experiment. |

Established methods explain useful boundaries rather than substitute for recent work:
[AdaFace](https://arxiv.org/abs/2204.00964v2) (2022-04-03; revised 2023-02-16)
uses a quality-adaptive **training loss** and feature-norm proxy;
[MagFace](https://arxiv.org/abs/2103.06627v4) (2021-03-11; revised 2021-07-26)
learns a magnitude/quality relationship. Their author code is respectively
[MIT](https://github.com/mk-minchul/AdaFace/tree/c60eaa786a42c03444f3df7096dbaf9d57ae010d)
and [Apache-2.0](https://github.com/IrvingMeng/MagFace/tree/99bae614ac2643b9694bf18e0c5645272ff6acfa);
checkpoint tables identify CASIA-WebFace/WebFace or MS1M-family training. No
independent commercial checkpoint/consent clearance was established here.
**An arbitrary SFace embedding norm is not validated MagFace quality**, and
L2-normalized vectors have already lost magnitude information.

[MobileFaceNets](https://arxiv.org/abs/1804.07573v4) (2018-04-20; revised
2018-06-15) supplies the compact CNN precedent; the paper's training uses refined
MS-Celeb-1M. Architecture portability is useful, but any particular redistributed
checkpoint needs its own rights review; InsightFace-distributed models retain
its research-only policy. [ElasticFace](https://arxiv.org/abs/2109.09416v4)
(2021-09-20; revised 2022-03-21) randomizes margins **during training**. No code,
weight or training-data license was independently verified for it in this
survey. Neither method is an inference-time threshold adjustment; retraining
on the restricted portraits is rejected.

### PAD generalization, temporal physiology and active evidence

| Primary source and date | What it establishes | Rights / deployment assessment | Current decision |
| --- | --- | --- | --- |
| [FSFM](https://arxiv.org/abs/2412.12032v3), first 2024-12-16, revised 2025-04-06, CVPR 2025; [author project](https://fsfm-3c.github.io/) | Masked facial reconstruction and instance discrimination learn transferable representations; downstream PAD is evaluated across domains. Paper's default uses ViT-B/16 and VGGFace2 pretraining. | [Author model card](https://huggingface.co/Wolowolo/fsfm-3c) explicitly CC-BY-NC-4.0. Separate code grant not established here. VGGFace2 and downstream PAD data are not cleared for commercial training in this work. Larger browser budget than the current tiny PAD pair; no measured WASM cost. | Research reference, not production swap or teacher to distill on restricted data. Do not repeat the earlier blanket claim that *every* new PAD method has the same backbone or restrictions. Audit artifacts individually. |
| [Optimal Transport-Guided Source-Free Adaptation for FAS](https://arxiv.org/abs/2503.22984v1), 2025-03-29, CVPR 2025 | Prototype-based adaptation allows a lightweight or training-free adaptor without changing the base network. | No deployable checkpoint/data license verified from the paper. Adaptation still consumes target-domain evidence; “training-free” does not mean no fitting, no contamination or consent requirements. | Rejected for the five-case preview: no independent target-domain adaptation cohort. Optimizing on validation/TEST or live attacker-supplied inputs would be a different, unsupported threat model. |
| [PCGAN / Domain-generalizable FAS with Patch-based Multi-tasking and Artifact Pattern Conversion](https://arxiv.org/abs/2604.09018v1), 2026-04-10 | Artifact/identity disentangling and patch tasks target domain shift and partial attacks. | No verified public weight grant or eligible training corpus in this survey. Requires training; no evidence that its runtime/export fits this browser. | Useful stimulus for a future **partial-attack** stress axis; not an instant replacement and not reproduced. |
| [RhythmMamba](https://arxiv.org/abs/2404.06483v2), first 2024-04-09, revised 2025-02-24, AAAI 2025; [author repo](https://github.com/zizheng-guo/RhythmMamba/tree/1533ad21cb4ae0d31e9dbb9afb0b1eefbed54aed) | State-space temporal modeling captures long-range periodic rPPG with linear complexity. Throughput claims are GPU results, not browser results. | Code MIT; pretrained files are present, but no separate weight/data clearance established. README explicitly asks users to obtain PURE/MMPD from authors; no request made. PyTorch/Mamba dependencies are not an established WASM export path. | Rejected here: no pulse-reference video, no bona fide active cohort, no export validation. Heart-rate estimation performance does not establish replay resistance. |
| [Benchmarking Joint Face Spoofing and Forgery Detection with Visual and Physiological Cues](https://arxiv.org/abs/2208.05401v2), first 2022-08-10, revised **2024-01-08** | Combines appearance and physiological branches with normalization and joint training, rather than declaring any periodic signal live. | No cleared weights/data grant established here. Two streams and temporal buffers increase deployment work. | Supports using physiology only as one evidence channel. Not reproduced; no physiological ground truth exists in our procedural clips or still portraits. |
| [A-Live](https://arxiv.org/abs/2606.05126v1), 2026-06-03; [full paper](https://arxiv.org/html/2606.05126v1) | Uses **IMU-only** neuromuscular micro-motion features with a compact classifier on commodity devices. It is not camera-to-IMU synchronization. | No public reproducible classifier/data license verified. Paper distribution license is not a software/weights grant. Browser sensor availability, permissions, rate and timing need device testing. | Important correction to `docs/research-face.md`'s earlier interpretation. A human holding a screen with a replay does not by itself bind that face to the human. Our clips contain no IMU, so no measurement is possible. Reported >99.5% is not face-PAD efficacy here. |
| [Face Flashing](https://arxiv.org/abs/1801.01949v2), first 2018-01-06, revised 2018-08-22 | Randomized illumination challenges elicit light responses, addressing freshness rather than relying solely on visual realism. Established mechanism retained because it directly motivates active acquisition. | No cleared implementation/weights/data license verified. Browser display/camera timing, automatic exposure/white balance, ambient light and accessibility must be measured; no local latency claim. | Keep as a proposed capture experiment. Existing procedural clips lack a captured light response; owner replays lack the challenge trace. Neither can certify challenge-response efficacy. |

## Frozen experiment actually run

Artifacts:
[protocol](../experiments/research_face/protocol-v1.json),
[runner](../experiments/research_face/temporal_quality.py),
[tests](../experiments/research_face/test_temporal_quality.py),
[complete aggregate result](../experiments/research_face/results/temporal-quality-v1.json).

The runner snapshot/config receipt was written at **2026-10-24 14:04:24 UTC**,
before the new score arrays were processed. Baseline outcomes were already known;
this is explicitly not a blinded comparison. There is one candidate batch and no
post-result parameter search. All candidates, including unfavorable shifts, remain.

Hypothesis, inspired by burst suppression and explicit quality assessment: give
equal influence to fixed temporal blocks, with a small positive sharpness weight
inside each block, to avoid one high-density period dominating an aggregate.
**This is our own ablation, not a reproduction** of GMP, ViTNT, OFIQ or a published
PAD method. Equal time bins only resist sampling-density imbalance; they do not
remove a repeated pose that persists across multiple seconds. Fixed-frame-rate
preview clips are weak evidence for the motivating variable-rate scenario.

Fixed original sampling: every third source frame, long side at most 960 pixels.
Retain the final partial block; no selected crops, clips, frames or scores.
At nominal source timestamps `i/fps`, group into one-second blocks. The cheap
quality proxy uses central 50% of the image, resized to 112×112 grayscale, with
`q = max(0.05, LaplacianVariance / (LaplacianVariance + 100))`. These are
predeclared engineering constants, not learned or calibrated face-quality values.
The central crop can contain screen edges/background; that is a reason to reject
it as a production FIQA substitute. PAD still uses the original complete frame.

Four candidates, all computed on the same scores:

- Framewise median (earlier temporal diagnostic reference).
- Framewise 10th percentile (lower-tail reference, **not an exact active session**).
- Mean score in each block, then the 10th percentile over blocks.
- Positive-quality-weighted mean in each block, then the same 10th percentile.

Quantiles use NumPy's linear convention. Missing/invalid frames retain rejection
score −1 and positive weight, preserving their place in the denominator.
Thresholds stay raw 0.59 and 0.78, the existing passive/session-component values.
Raw offline quantiles do not claim equivalence to the production calibrated
session decision, whose timing, framing and physical checks are absent here.

The native inference cache is from the earlier frozen temporal run, **not** the
shared binary observed during this task. Its executable hash begins `f6d9f302…`;
the currently shared executable had different bytes. The runner re-decodes all
five source videos, verifies source hashes, every sampled PNG-equivalent hash,
combined frame hash, all four model hashes, row counts and the original published
aggregate. Cache-file hashes and original report/executable provenance are
recorded. This is cached model inference plus fresh quality processing, not fresh
native inference. No source build or shared-build contamination is involved.

| Candidate | Clips crossing 0.59 | Clips crossing 0.78 | Maximum clip score | Score rises vs frame q10 |
| --- | ---: | ---: | ---: | ---: |
| Frame median | 0/5 | 0/5 | 0.064788 | 5/5 |
| Frame q10 | 0/5 | 0/5 | 0.009900 | reference |
| Block mean → q10 | 0/5 | 0/5 | 0.018513 | 5/5 |
| Block quality mean → q10 | 0/5 | 0/5 | 0.018493 | 5/5 |

Exactly **765/765 sampled frames**, **78 blocks**, minimum **3 frames/block**,
**0 missing**, **0 invalid**. Per-clip frame counts are 144, 151, 156, 158, 156
in the original frozen manifest order. Per-frame scores, weights, timestamps,
source hashes, block sizes and all per-clip outcomes stay in the owner-private
`per-clip.json` path and digest recorded in the aggregate result. There are **five
attack trials**, not 765 independent trials; identity/device overlap is unknown.
No significance or population FAR/APCER claim is justified.

Both new rules increase the score on all five attacks relative to frame q10;
the maximum increase is 0.008613 (block mean) and 0.008593 (quality-weighted).
These are adverse score shifts, not decision regressions at the frozen thresholds.
No candidate has an accuracy gain. Quality weighting barely changes the maximum
compared with unweighted blocks. Zero attack errors were already known: positive
weighted means/quantiles stay inside their inputs' range, so they cannot improve
this attack count. A property test verifies that convex-range constraint.

Five tests passed: missing/invalid scores keep their denominators, partial blocks
remain, dense duplicate sampling does not reweight whole blocks, convex fusion
cannot exceed its maximum, and malformed temporal inputs abort. A deterministic
counterexample demonstrates that quality weighting **can raise** an attack score;
this matters even though it causes no crossings in the preview.

**Decision:** reject both block variants for production promotion. Retain the
prototype as a negative-control experiment. There are zero bona fide temporal
trials, so genuine BPCER, ROC operating-point selection and APCER at fixed BPCER
are null. The five real selfies are stills, not five active trials. The procedural
heads have no real physiology, sensor exposure response or human challenge
compliance; they can test mechanics but cannot fill those gaps. No procedural
run was needed to make a shipping regression claim because nothing was shipped.

## Own suggestions and rejected alternatives

1. **Prioritize measurement readiness before more passive fusion.** For a future
   authorized capture collection, record timestamps, face-track coverage, pose-bin
   occupancy, challenge presentation/response timing and which physical checks
   actually received samples. Missing evidence should be separately observable
   from spoof evidence. Keep identity/device/session splits fixed in advance.
   Do not optimize a rejection rule on the five early-centering replay failures.

2. **Recognition-only temporal diversity experiment.** Freeze one representative
   per time/pose bin and compare normalized uniform fusion with a fixed
   quality-plus-diversity weighting. Keep full capture denominators and compare
   genuine acceptance **and** false matches at unchanged thresholds. This follows
   the burstiness warning without claiming QA-GMP reproduction. Duplicating one
   still must never manufacture independent capture evidence. The available
   single-session portraits cannot establish real temporal benefit.

3. **Document/selfie stress matched to acquisition.** Separately vary printed
   halftone/security overlay, optical blur, JPEG and age/capture-domain differences
   in an authorized DEV protocol; retain original and degraded pair results.
   Use document-side diagnostics for document photos rather than the live-camera
   gate. No training or production quantization calibration on FRLL, CelebA or
   LFW research portraits. The WACV 2025 paper motivates domain coverage, not
   permission to generate a commercial training set from them.

4. **rPPG readiness, not a heartbeat acceptance rule.** A later diagnostic could
   compare fixed cheek/forehead traces with nuisance/background traces, retain
   timestamps and exposure changes, and return “insufficient signal” when data
   are inadequate. The governing hypothesis is that periodic camera/display
   artifacts and replayed physiological signals can confound a pulse detector;
   a heartbeat-like spectrum alone does not establish freshness. This is our
   proposed negative-control design, not a measured finding from this run.
   Pulse-reference, consented bona fide and replay trials are needed before any
   physiology-based security claim. Static portraits/procedural heads fail this
   feasibility requirement, so no synthetic “heart-rate accuracy” is reported.

5. **An isolated FaceLiVTv2 export investigation is more useful than alignment
   variant seven.** Resolve weight/data rights first; pin checkpoint/code,
   reparameterize, compare float embeddings, then freeze INT8 configuration and
   measure download size, load time, memory and actual browser latency. Use an
   eligible calibration source and an unchanged referee. This work neither loads
   those checkpoints nor proposes changing the existing recognizer threshold.

6. **Challenge freshness remains distinct from PAD appearance.** A future capture
   study can predeclare a randomized visual challenge and synchronized response
   observations. Do not equate a real human holding a device (A-Live), a realistic
   face (recognition), a sharp image (FIQA), or a pulse-like signal (rPPG) with
   successful active face verification. Preserve the current physical checks.

Explicitly rejected in this track: tuning security thresholds; disabling physical
parallax; selecting the best alignment from dependent tiny FAR changes; selecting
only sharp attack frames; reusing heldout outcomes for adaptation; treating
SFace norm as MagFace quality; a ViT-only metric on a CNN; fine-tuning face-swap or
PAD weights on restricted research portraits; interpreting a permissive code
license as cleared training consent; rPPG on static/synthetic heads; accepting an
attack-only result as active BPCER/APCER evidence; reporting GPU FLOPs as browser
speed; cloud/paid liveness APIs; contacting authors or acquiring gated datasets.

No proposal currently meets the evidence needed for a shipping face-code change.
The next meaningful security comparison needs a consented, permitted, real
challenge-following DEV cohort with device/session metadata, including bona fide
trials and attacks under the **same** acquisition protocol. That collection is a
proposal only; no external acquisition or outreach was initiated.


## Second face track: fixed photometric matching experiment, 24 October 2026

This appendix is a separate **matching** experiment. The preceding first-track
survey, protocol, temporal results and decisions remain unchanged. No production
files, weights, thresholds, shared referee or historical results were edited;
no commits, subagents, TEST runs, threshold fitting or calibration were performed.

**Outcome:** a small, condition-specific descriptive signal at the fixed document
threshold, with an adverse false-accept change at the other fixed threshold.
The sole candidate meets the predeclared document-threshold criterion, but gains
only one genuine accept per DEV split on an extremely damaging artificial
condition. It is **not selected for production**. The hard condition still rejects
47/51 calibration and 43/51 validation genuine comparisons with the candidate.
There is no independent-document/device evidence, statistical superiority claim,
SOTA comparison or population-FAR guarantee.

### Hypothesis and primary-source basis

[Jonientz et al., compression detection for explainable FIQA, 7 January 2025](https://arxiv.org/abs/2501.03619v1)
describe compression-related loss of recognition utility and a trained artifact
detector. This motivates retaining compression as an explicit stress axis; it does
not establish that gamma correction repairs lost detail. [Wang, On the Burstiness
of Faces in Set, 25 June 2025](https://arxiv.org/html/2506.20312v1) studies aggregation
and quality-aware generalized max-pooling, including the problem of redundant
views. It motivates testing aggregation carefully, rather than assuming multiple
views are independent evidence. Neither paper is reproduced here. No FIQA model,
QA-GMP weighting, attention module, new recognizer or paper checkpoint was used.

Our engineering hypothesis was that **uniform averaging of three normalized
photometric document embeddings** could stabilize matching after print degradation
without increasing actual FAR. Gamma values 0.8, 1.0 and 1.2 are fixed engineering
constants, not fitted quality estimates. Deterministic transformations of one
portrait add no independent capture information and can reinforce shared errors.
This is a falsifiable local stress experiment, not evidence for the papers' methods.

The source remains [DeBruine and Jones, Face Research Lab London Set v5](https://doi.org/10.6084/m9.figshare.5047666.v5),
CC BY 4.0, from the [pinned author release](https://github.com/debruine/webmorphR.stim/tree/fa8b78fda2d659bb74ce62fcd99c4407551d2a77).
Its source README documents signed research consent for original and altered
images. All 204 existing neutral/smile portraits of 102 people were used for local
research only; this is not a commercial training permission or real-document dataset.
No new external portrait collection was acquired.

### Frozen design and exact correspondence

- [Predeclared protocol](../experiments/research_face/matching_protocol_v1.json).
- [Runner](../experiments/research_face/matching_photometric.py),
  [nine synthetic regressions](../experiments/research_face/matching_test.py), and
  [independent artifact audit](../experiments/research_face/matching_audit.py).
- [All aggregate results](../experiments/research_face/results/matching_photometric_v1.json)
  and [audit result](../experiments/research_face/results/matching_audit_v1.json).

The private freeze receipt was written at **2026-10-24 14:30:34.710631 UTC**, before
any new portrait inference or historical embedding-cache reads. The run completed
at **14:33:18.720211 UTC**. Protocol SHA-256:
`e0818c498c68ac46bc19d469964c9f67fe7c9b1151472775c7e89058e41d835d`.
Runner SHA-256:
`b1156e32ce78ea266f2a51695c560349278876886891b6461a9f94e3afcbbc2b`.
Previous baseline results were known, including the 51/51 genuine ceiling on the
original and two earlier degradation conditions. This was not a blinded study.
No candidate or degradation search followed these results.

The unchanged SHA-256 identity ordering keeps the first 51 people in the existing
`calibration` split and the next 51 in `validation`. Those names are retained for
correspondence only: **neither split fits anything**. All images and derived views
of an identity stay together. Every neutral/document portrait is compared with
all 51 original smiling references in its split: **51 genuine and 2,550 dependent
impostor pairs per condition and arm**. Labels follow identity keys, not diagonals
or file order. There are 20,808 comparisons per arm over the four conditions,
41,616 across both arms; scoring them at two thresholds does not create more trials.

Baseline is the earlier `production-pair` embedding proxy: native iris alignment,
flip-averaged document/still embedding, unflipped original smiling reference.
It does not model a complete production session, guide, capture-quality gate or
liveness decision. As in the historical evaluator, face selection uses the native
center-face path; no independent end-to-end equivalence claim is made.

The **three print-degradation levels**, plus original control, were fixed before
inference. All transformations affect the neutral/document side only:

| Condition | Fixed generation |
| --- | --- |
| original | Existing original JPEG; no print transform |
| document_gray | LANCZOS to 384×384, RGB→gray→RGB, Gaussian blur 0.4, JPEG quality 65 |
| document_small | LANCZOS to 192×192, RGB→gray→RGB, Gaussian blur 0.7, JPEG quality 45 |
| document_hard96 | LANCZOS to 96×96, RGB→gray→RGB, Gaussian blur 0.9, contrast 0.4 about pixel value 127.5, rounded/clipped uint8, JPEG quality 25 |

The runner regenerates the two prior degradations in memory and requires exact
byte equality with their existing private files. The harder condition was included
up front because the historical ceiling was already known. It was intentionally
not made easier after observing the very low genuine acceptance.

For the one candidate, decode each condition's input, transform each RGB channel
with `round(255 * (pixel/255)^gamma)`, and encode the two non-unit gamma views as
lossless PNGs. Unit gamma reuses the exact baseline image/embedding. Each view is
independently detected, aligned and flip-averaged; each vector is L2-normalized,
the three are equally averaged in order 0.8, 1.0, 1.2, and the mean is normalized.
The original unflipped smile embedding is shared by both arms. **All three views
must be usable**. Missing detections, mesh presence below 0.5, nonfinite presence,
zero/nonfinite vectors or a zero/nonfinite aggregate reject; no view or identity
is removed from scoring. No live-camera quality gate is imposed on document photos.

Both existing production operating points are reported for every condition:
**document cosine ≥0.356** is primary, **live cosine ≥0.366** is secondary. This
includes applying the document operating point to the original control; the earlier
report used live 0.366 there. The runner checks that both constants still equal the
source values. It never calls the existing research threshold-fitting function.
The six historical baseline split/condition rate-and-count records reproduce
exactly under their original mapping (original live; degraded document).

### Results at document threshold 0.356 (primary)

| Condition | Split | Baseline TAR | Gamma TAR | Baseline actual FAR | Gamma actual FAR |
| --- | --- | ---: | ---: | ---: | ---: |
| original | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 20/2,550 (0.784%) | 19/2,550 (0.745%) |
| original | validation | 51/51 (100.000%) | 51/51 (100.000%) | 14/2,550 (0.549%) | 14/2,550 (0.549%) |
| document_gray | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 12/2,550 (0.471%) | 12/2,550 (0.471%) |
| document_gray | validation | 51/51 (100.000%) | 51/51 (100.000%) | 12/2,550 (0.471%) | 12/2,550 (0.471%) |
| document_small | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 8/2,550 (0.314%) | 8/2,550 (0.314%) |
| document_small | validation | 51/51 (100.000%) | 51/51 (100.000%) | 5/2,550 (0.196%) | 4/2,550 (0.157%) |
| document_hard96 | calibration | 3/51 (5.882%) | 4/51 (7.843%) | 0/2,550 (0.000%) | 0/2,550 (0.000%) |
| document_hard96 | validation | 7/51 (13.725%) | 8/51 (15.686%) | 0/2,550 (0.000%) | 0/2,550 (0.000%) |

The frozen descriptive criterion required a hard96 TAR improvement in **both**
splits with no FAR increase, and no TAR loss/FAR increase on any easier condition
at 0.356. It is met. Hard96 gains are **one recovered genuine pair per split**,
1.961 percentage points each, with no genuine accept→reject transitions. This
small count change on one source does not establish a reliable generalization gain.
Original and both earlier print conditions remain at the genuine ceiling. The
impostor reductions are one pair in original calibration and one in 192 validation.

### Results at live threshold 0.366 (secondary, unchanged)

| Condition | Split | Baseline TAR | Gamma TAR | Baseline actual FAR | Gamma actual FAR |
| --- | --- | ---: | ---: | ---: | ---: |
| original | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 14/2,550 (0.549%) | 14/2,550 (0.549%) |
| original | validation | 51/51 (100.000%) | 51/51 (100.000%) | 12/2,550 (0.471%) | 11/2,550 (0.431%) |
| document_gray | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 5/2,550 (0.196%) | 6/2,550 (0.235%) |
| document_gray | validation | 51/51 (100.000%) | 51/51 (100.000%) | 7/2,550 (0.275%) | 7/2,550 (0.275%) |
| document_small | calibration | 51/51 (100.000%) | 51/51 (100.000%) | 6/2,550 (0.235%) | 6/2,550 (0.235%) |
| document_small | validation | 51/51 (100.000%) | 51/51 (100.000%) | 2/2,550 (0.078%) | 2/2,550 (0.078%) |
| document_hard96 | calibration | 2/51 (3.922%) | 2/51 (3.922%) | 0/2,550 (0.000%) | 0/2,550 (0.000%) |
| document_hard96 | validation | 6/51 (11.765%) | 7/51 (13.725%) | 0/2,550 (0.000%) | 0/2,550 (0.000%) |

This operating point exposes an unfavorable result: gray384 calibration false
accepts rise **5→6/2,550 (0.196%→0.235%)**. Original calibration also swaps one
previous false accept out and a different false accept in, leaving its count at
14. Those paired transitions remain in the report. Hard96 calibration has **no
TAR gain at 0.366**; validation gains one pair. These outcomes rule out describing
the candidate as uniformly better, even though the primary descriptive criterion
was satisfied. Zero hard96 false accepts accompanies very poor genuine acceptance;
it cannot certify a population FAR or justify the degradation as a security filter.

### Complete accounting, provenance and practicality

All original and mild-condition probes/references are usable. Hard96 baseline
has **2 calibration / 3 validation unusable probes**. Gamma 0.8 has 3/3, gamma
1.2 has 2/2, and the all-view candidate has **3/3**. Thus the candidate loses one
additional calibration probe to usability; that probe was already a genuine
rejection at both thresholds. All missing comparisons remain in the 51/2,550
counts. No reference is missing. Per-identity arrays and matrices remain private.

The shared executable initially differed from the historical binary. An unmodified
snapshot of the current Rust source, lockfile and two required compile-time text
assets was built privately with `cargo build --release --locked --example face -j 2`.
The initial source-copy omitted the two text assets; the first build failed before
inference, then copying those unchanged assets completed it. The build receipt
retains that preparation failure and every source hash. The successful build
reproduced the historical executable **byte-for-byte**:
`f6d9f3020a4cfb43a2b687327d8f13eece7fea29df122cc4ede95ca7ca2954f1`.
The shared build was never modified.

`public_face/artifacts.py` acquired one owner-private executable snapshot for the
whole run and verified model file identities/hashes around cache use and fresh
inference. The report retains every ONNX hash: detector, landmark detector,
`sface_int8.onnx` (recognizer string `sface_int8.onnx:sface_int8:sface`) and
`minifasnet.onnx`. The latter was guarded but not used: inference explicitly passes
`--no-antispoof`. No new models or weights were downloaded or trained. Existing
model provenance is inherited, not newly certified by this experiment.

Exact source hashes, generated-row hashes, binary/model hashes, shard count and
row order allowed **408 relevant existing baseline/reference rows** to be read
from immutable historical caches. **918 rows received fresh native inference**:
102 hard96 baselines and 408 portraits at each of the two additional gammas.
This totals 1,326 input/view rows, representing the same 204 source photographs;
there are not 1,326 independent captures. Both arms use the same exact executable.
Every new native output was staged, validated and verified before publication.
No historical cache, protocol file or report was rewritten.

The native pool was limited to two jobs, each with one RTEN/Rayon thread; NumPy
and BLAS were also limited to one thread. Fresh stage wall times were **7.982 s**
(hard96 baseline), **39.802 s** (gamma 0.8) and **40.420 s** (gamma 1.2). Historical
cache reads took 0.198/0.167 s. These are recorded batch diagnostics including
verification on this shared host, not an equal-work baseline-versus-candidate
latency benchmark or browser performance claim. Native processing does not measure
camera latency, WASM performance or device peak memory.

Implementation practicality: a gamma lookup and three-vector average are cheap,
but this exact candidate makes **three detector/landmark passes and six recognizer
passes per document**, versus one detector/landmark pass and two recognizer passes
for the flip baseline. The smile path is unchanged. This analytical work increase
is substantial compared with recovering one of 51 genuine pairs per split. No
latency/memory claim or optimization is inferred from the cached baseline timings.

**Nine new matching regressions and all 24 existing public-face referee/provenance
tests pass (33 total).** Tests cover permuted references and gamma-row ordering,
duplicate/incomplete/cross-split correspondence, normalization before/after fusion,
zero/nonfinite/overflow/cancelling vectors, missing-first/all-missing native rows,
low/nonfinite mesh presence, missing-reference denominators, unit-gamma identity
and exact cache compatibility. The separate read-only audit passes all **32
arm/condition/split/threshold cells**, checks private permissions and all recorded
input/output hashes, reconstructs fusion independently in float64, and verifies
every stored pair score and its identity label. Aggregate artifacts contain no
portrait, embedding, identity-indexed score or source identity key.

**Decision:** retain this one candidate as a modest positive local matching result
with explicit secondary regressions; do not promote it. No parameter search follows.
A future decision would require independently authorized real document/selfie DEV
captures with device/session grouping and measured browser cost. This task acquires
none of those data and makes no independent-device, age, document, PAD or SOTA claim.
