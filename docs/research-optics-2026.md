# Optics research and frozen DEV experiment — 24 October 2026

Research-only scope: `experiments/research_optics/**` and this document, based on
merged `004fffc8401def04fabaffebc69d704249d84022`. No shipping change, Rust build,
new weight, training, TEST/reserved access, commit, branch, PR or subagent.
The requested brief read-only review of the parent's barcode import UI found no
concrete P1/P2; it is separate from these optics experiments.

## Primary-source findings and decisions

The following sources were checked on 2026-10-24. Paper findings are the authors'
results; the three inexpensive mechanisms below are our engineering hypotheses,
not reproductions of those methods. No downloaded paper image is benchmark truth.

**Radiometric linearization.** The [ICC sRGB definition](https://registry.color.org/rgb-registry/srgb)
and [W3C transfer functions](https://www.w3.org/TR/css-color/)
define the piecewise display-code/linear-light conversion. [Debevec and Malik,
SIGGRAPH 1997](https://www.pauldebevec.com/Research/HDR) recover camera response
from multiple exposures. Our inverse-sRGB operation assumes a display encoding:
it does **not** undo an unknown phone ISP, recover RAW, infer exposure time or
recover a saturated character. Scalar exposure multiplication is best tested in
linear light, while retaining that limitation. Existing JPEG quantization,
denoising and local tone mapping remain irreversible. No HDRShop implementation
or license is imported into our independent arithmetic.

**White balance.** [Finlayson and Trezzi, Shades of Gray, 2004](https://library.imaging.org/cic/articles/12/1/art00008)
derive gray-world/max-RGB assumptions and their generalization. A blue security
background, colored bill or large portrait can violate neutral-scene assumptions.
Decision: do not apply an uncalibrated per-channel gray-world correction. Both
tested corrections multiply all channels equally at a pixel, preserving linear
chromatic ratios until clipping. This is not a guarantee of preserved ink color
or skin appearance; color-fidelity and recognition outcomes still need measurement.

**Specular glare and polarization.** [Nayar, Fang and Boult, IJCV 1997](https://cave.cs.columbia.edu/old/publications/pdfs/Nayar_IJCV97.pdf)
use color and polarization observations to separate reflection components.
Single RGB saturation lacks those observations: clean white paper is often
bright, while glare can erase text. [Rodin and Orlov, 2019](https://arxiv.org/abs/1911.05189)
combine luminance and stroke information for document glare. Our conservative
bright-island heuristic is only a diagnostic/ranking feature. It never fills a
region, claims a glare-free document or overrides validation. A polarizer is an
acquisition experiment with separate angle/light controls, not a software filter
that can be applied to a stored JPEG. It may also change hologram appearance.

The [author's 2020 follow-up release](https://github.com/RodinDmitry/glare)
has an [Apache-2.0 repository notice](https://raw.githubusercontent.com/RodinDmitry/glare/master/README.md)
and links an external dataset. That notice is not automatically an audited rights
chain for every external document or released checkpoint. No archive or image
from it was acquired; review archive-specific terms/provenance before proposing
it as production training data.

**Motion blur, MTF and burst selection.** [Delbracio and Sapiro, 2015](https://arxiv.org/abs/1505.02731v2)
aggregate different observed Fourier spectra in a burst. The useful principle is
that camera motion can suppress different frequencies in different frames. Our
seven-pixel line-spread kernel is a controlled motion-blur stressor, not a measured
lens/sensor MTF or a camera-shake distribution. A gradient-energy proxy can rank
noise, border edges and sharp backgrounds above text, so it must be judged by
actual reads and wrong accepts. We test selection of one observed frame; no
deconvolution, Fourier synthesis or deblurred text is treated as ground truth.

**Exposure fusion.** [Mertens, Kautz and Van Reeth, 2007](https://jankautz.com/publications/exposure_fusion.pdf)
blend exposures with quality weights and pyramids without recovering radiance.
[Hasinoff et al., HDR+, 2016](https://research.google/pubs/burst-photography-for-high-dynamic-range-and-low-light-imaging-on-mobile-cameras/)
instead use constant, deliberately low-exposure RAW bursts with alignment and
noise reduction. Both require actual observed diversity. Generating three gamma
views of one clipped frame provides none. Moving fingers, shifted text and
rolling shutter can make a fused character wrong even if the image looks cleaner.
Decision: establish safe single-frame selection before image fusion; retain
per-frame provenance and require alignment/error checks before a future fusion
experiment. Browser RGB frames cannot be called HDR+ RAW acquisitions.

**Dewarping.** [UVDoc's author implementation](https://github.com/tanguymagne/UVDoc)
predicts grids, permitting resampling of observed content rather than text
generation. Its [code is MIT](https://raw.githubusercontent.com/tanguymagne/UVDoc/main/LICENSE);
its [dataset recipe](https://raw.githubusercontent.com/tanguymagne/UVDoc-Dataset/main/README.md)
lists separately sourced textures, DTD backgrounds and generated textures. A
software LICENSE does not settle every underlying asset or weight grant. No
model/data downloaded. A future grid experiment needs local Jacobian/fold checks,
sampling-resolution bounds and exact-character scoring; source coordinates must
remain recoverable. The prior contour-rectification work already addresses a
cheaper planar case; this experiment does not repeat it or use annotation crops.

**Shadow removal.** [BEDSR-Net, CVPR 2020](https://openaccess.thecvf.com/content_CVPR_2020/html/Lin_BEDSR-Net_A_Deep_Shadow_Removal_Network_From_a_Single_Document_CVPR_2020_paper.html)
estimates background information. [Zhang et al., CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/papers/Zhang_Document_Image_Shadow_Removal_Guided_by_Color-Aware_Background_CVPR_2023_paper.pdf)
specifically address spatially varying background colors. These motivate testing
background/illumination estimates, while warning that white-page assumptions
confuse colored designs with shadows. Our dilate/blur illumination field is an
independent classical approximation, not either neural method. No learned
restoration output supplies transcription labels.

Recent work continues this distinction. [Gao et al., DICNet, 2025](https://www.mdpi.com/1999-4893/18/8/468)
learn illumination correction with a shadow mask; the inspected
[author README](https://raw.githubusercontent.com/gdpinntit/Document-Image-Shadow-Removal-based-on-Illumination-Correction/main/README.md)
still promises code after publication, so a deployable implementation/weight
license was not established. [DocShaDif, June 2026](https://www.sciencedirect.com/science/article/abs/pii/S0020025526001970)
uses conditional diffusion and gradient regularization. Neither visual quality
nor gradient regularization proves exact-character fidelity. No checkpoint,
restored image or paper accuracy is substituted for this benchmark's truth.

## Three frozen hypotheses

1. **Global exposure:** estimate a coarse linear-luminance background; only when
   its 90th percentile is below 0.55, multiply RGB by `min(4, 0.85/p90)`. Avoid
   touching well-exposed pages. This tests exposure correction, not gamma search.
2. **Local illumination:** use the same downsampled background, with a 25-pixel
   dilation and Gaussian sigma 9. Enable if globally dark or `p10/p90 < 0.65`;
   bilinearly resize `clip(0.85/background, 1, 4)` to the original grid. This
   interpolates a smooth gain field, never upscales source text.
3. **Burst selection:** select the maximum normalized gradient-energy score,
   modulated by exposure and a conservative clipped-island penalty. Select only
   original observed pixels, without OCR/confidence/truth selection. Tie goes to
   the first frame. A chosen failed frame stays a failure; no successful fallback.

All constants and functions are in [optics.py](../experiments/research_optics/optics.py)
and frozen by hash before inference. The
[protocol](../experiments/research_optics/protocol.json) predeclares the data,
conditions, three arms, selection gate and timing. No threshold search follows
the results. Reusing known DEV makes this an exploratory study, not held-out
confirmation. No previous gamma-face or small-recognizer experiment is rerun.

## Data, grouping and unchanged referees

All 60 existing public OCR DEV pages are retained: ten pages of three
Bankstatemently statements and 50 invoices of five FATURA layouts. Effective
TRAIN is explicitly **empty**; no weights, gains or thresholds are fitted.
Existing FATURA TRAIN images/annotations are not accessed. All pages and variants
of each statement/template/specimen stay DEV. All 18 existing MIDV frames of
three specimens and their Apple capture sessions stay DEV. No device is split
between TRAIN and DEV; independent-device generalization is not established.

The runner opens only existing explicit DEV allowlists; it never lists upstream
data directories, opens dataset archives, calls preparation or touches reserved
items. Existing rendered pages are read and verified, not rewritten. PDF text,
invoice references, source images, real camera frames and every derived pixel
input are hash-checked. The private freeze precedes all fresh inference.

Public OCR conditions are clean, dark, shadow, glare and motion blur. Dark is
linear exposure 0.18 with seeded Poisson/read noise; shadow is a fixed smooth
0.18–0.88 multiplicative field; glare is additive elliptical light of peak 1.4
with sensor-range clipping; motion blur is a fixed horizontal seven-tap PSF.
These are simplified physical stressors applied to already encoded images, not
a calibrated camera simulation. They preserve the underlying known transcription;
lost/clipped characters remain missed, never removed from truth.

The existing tiny/tiny standard native OCR probe is copied into the private run.
Its source hash must match `docscan/src/text_v6.rs`, and binary/model hashes must
match the prior build receipt. The current baseline is **not** the earlier
small-recognizer proposal. Camera evaluation uses the preserved native capture
baseline from the prior research with unchanged models and flags. Both arms use
the same binary/weights; the historical baseline results are explicitly checked.
No Rust compilation or modification of a shared target occurs.

The existing `public_documents/evaluate.py` scores normalized exact text and
multiset tokens with punctuation/numbers retained. Every arm/condition has
**2,639 bank truth tokens, 3,196 invoice truth tokens and 560 invoice regions**.
FATURA only annotates selected fields: precision cannot measure hallucination
outside those regions. Bank token counts do not establish ordering or semantic
verification. The existing `public_id/score_id.py` requires the correct passport
kind and all ten MRZ fields for exact acceptance: **12 positive, six negative,
120 MRZ-field slots** for every camera arm. Check-digit validity alone does not
count as a correct accept.

Synthetic burst trials retain one burst per page, using its dark/glare/blur views;
the starting condition is cyclically permuted by the specimen hash, not outcomes.
These are dependent simulations, not new captures. The nine real bursts each use
the two already allowed frames per MIDV specimen/session: six positive and three
negative bursts. Burst results are separate from the fixed 18-frame results.
They do not establish live stopping policy or acquisition time.

Six procedural non-text images check spurious text. They are not personal data,
document attacks or a broad false-positive corpus. Timeouts, malformed output,
native failures and empty readings remain in the original denominators. Camera
abstentions are unchanged scanner rejects; empty OCR is only an empty reading,
not a calibrated quality rejection.

## Results

**Decision: no default or ID-acceptance integration is supported.** Only the
global-exposure arm is supportable as an **experimental, explicit opt-in
ordinary-OCR utility for parent implementation and re-evaluation**, with the
original evidence/reading retained. It is not a proven accuracy upgrade.
Local illumination and burst selection remain rejected. The fixed run froze
at **19:53:48 UTC** and finished at **19:59:42 UTC** on 24 October 2026. It made
**472 unique native inferences**, with **zero failures**. Exact pixel duplicates
within the same engine share an output, while all **900 document trials, 54
camera trials and 18 non-text trials** retain their original denominators.
Every historical clean OCR scored row reproduces exactly. Accuracy wall time
was 354.68 seconds under at most two workers; it is not a speed comparison.

[Complete results](../experiments/research_optics/results-v1.json) retain all
30 source/condition/arm cells, exact-region gains/losses, empty readings,
transform coverage, false output and hashes.
[Independent audit](../experiments/research_optics/audit-v1.json) passes all
30 cells, three camera arms, 472 prediction hashes and private permissions.

### Document transcription

Cells are **token recall / precision (%)**. Denominators are unchanged within
each source. Global and local give identical dark-image pixels because both
hit the same gain cap; they are not independent confirmations of a method.

| Source / condition | Baseline | Global exposure | Local illumination |
| --- | ---: | ---: | ---: |
| Bank / clean | 88.52 / 96.41 | 88.52 / 96.41 | 88.52 / 96.41 |
| Bank / dark | 89.12 / 96.04 | 89.66 / 94.79 | 89.66 / 94.79 |
| Bank / shadow | 88.25 / 96.20 | 88.25 / 96.20 | 90.34 / 95.78 |
| Bank / glare | 77.30 / 93.02 | 77.30 / 93.02 | 77.30 / 93.02 |
| Bank / motion blur | 3.45 / 8.05 | 3.45 / 8.05 | 3.45 / 8.05 |
| Invoice / clean | 87.36 / 93.50 | 87.36 / 93.50 | 87.36 / 93.50 |
| Invoice / dark | 84.73 / 92.90 | 85.48 / 93.40 | 85.48 / 93.40 |
| Invoice / shadow | 87.61 / 93.87 | 87.61 / 93.87 | 87.45 / 93.73 |
| Invoice / glare | 79.54 / 90.66 | 79.54 / 90.66 | 79.54 / 90.66 |
| Invoice / motion blur | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |

Both candidates leave **all 60 clean pages pixel-identical**, with no clean
regression. All 60 dark pages change. Only local illumination changes the 60
shadow pages. Neither changes any glare/blur input. Correction does not recover
the severe motion-blur stratum: OCR still emits text but almost none of it is
right. This is a simulated stress level, not the prevalence of camera failure.

Dark invoices improve **359→368/560** exact regions, comprising **37 gained and
28 lost** regions, with token-count gains on 24 pages and losses on 16. The
headline improvement hides those character/field regressions. Shadow invoices
under local correction improve **385→390/560** exact regions (13 gained, eight
lost), while token recall and precision both decline. Clean/glare/blur exact
invoice regions remain **392/316/0** of 560 respectively. Bank pages have zero
full-page exact matches in every cell. One dark bank page reads nothing in the
baseline; correction reads text, but aggregate bank precision declines. No
acceptance decision is derived from these OCR token scores.

### Real camera acceptance

| Arm | Exact passport accepts / 12 | Wrong accepts / 18 | Unsupported-front accepts / 6 | Exact MRZ fields / 120 | Abstentions / 18 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1 | 2 | 0 | 68 | 15 |
| Global exposure | 1 | 2 | 0 | 69 | 15 |
| Local illumination | 3 | 2 | 0 | 70 | 13 |

Global correction changes five of 18 camera inputs and creates no new wrong
accept, but adds **no correct accept**. Local correction changes all 18 and
adds two correct accepts, losing none. Crucially, **both local wrong accepts are
new frames**; both previous wrong accepts disappear. An unchanged total of two
therefore does not establish non-regression. Reject local correction for scanner
integration under the predeclared no-new-wrong-accept gate. Six negative fronts
cannot certify population false-accept safety. Both baseline errors remain
unresolved by global correction.

### Burst selection and glare diagnosis

Image-only burst selection improves invoice recall **48.75→76.56%** and precision
**71.96→89.11%**, but loses **41** previously exact regions while gaining 121.
Bank recall collapses **65.29→5.23%**, precision **82.05→11.89%**. The selector
chooses motion blur on **eight of ten bank pages**; a thumbnail gradient proxy
does not preserve OCR-scale character information. It chooses glare/dark/blur
on 41/6/3 invoice pages and glare/blur on 2/8 bank pages. Do not tune the selector
on this failure and call the same set independent validation.

On nine real camera bursts, first-frame versus selected-frame exact accepts are
**1→0/6** positive bursts; wrong accepts **2→1/9**; negative accepts **0→0/3**;
MRZ fields **47→31/60**; abstentions **6→8/9**. One correct accept is lost, no
correct accept is gained, and one wrong accept disappears. Neither selection
path has a native failure. **Reject this selector.** A lower wrong-accept count
with worse genuine recovery is not a successful capture improvement.

The glare heuristic flags **21/60 clean pages** but only **12/60 additive-glare
pages**; it also flags 20/60 blur pages and none of the dark/shadow pages.
On procedural labels these are 35% clean false positives and 20% glare-frame
coverage. This is not segmentation accuracy or real-camera glare calibration.
White margins, printed geometry and thumbnail statistics defeat the heuristic;
its unit-test white-sheet success did not predict document-level utility. It
must not be used for recapture rejection, originality or acceptance.

All three arms emit no text on the six non-text controls. That limited result
does not negate the substantial wrong OCR on blur/glare or the new camera wrong
accepts. All failed/empty/abstaining cases remain counted.

### Timing and integration disposition

The separate [timing runner](../experiments/research_optics/timing.py) measures
three alternating-order paired repetitions on the predeclared first dark page
from each of eight source groups, one pinned CPU, no parallel accuracy workload.
It records preprocessing and total native-process cost, calibration brackets,
failures and full per-pair data. Timing is descriptive native feasibility, not
the main benchmark's speed verdict or phone/WASM latency. All 96 timed native
calls complete without failure. The [timing artifact](../experiments/research_optics/timing-v1.json)
records **global exposure median paired ratio 1.0207×**, with a descriptive
whole-group bootstrap interval **0.9963–1.1111×**. Pooled baseline/candidate
median wall times are **1293.4/1381.3 ms**, including PNG save and process startup;
these pooled medians are not the median of paired ratios. Global preprocessing
alone is **63.2 ms** median. The interval does not establish a ≤5% cost bound.
Local illumination is **1.0284× [1.0063, 1.0815]**, with 67.9 ms preprocessing;
its acceptance regressions already reject it regardless of speed. Selector
per-frame timing remains in the artifact; its accuracy failure is decisive.

### Requested global-only uncertainty and parent handoff

After the frozen run, the parent specifically requested uncertainty and an opt-in
assessment. [global_review.py](../experiments/research_optics/global_review.py)
performs **no new inference and no parameter/gate change**. It resamples whole
statements/layouts, keeping all pages and reference regions together. The
[complete paired report](../experiments/research_optics/global-review-v1.json)
exports every one of the 60 dark pages: baseline/candidate counts, exact-region
gains/losses by label/index, unmatched predictions, precision change and failures.
No OCR strings or field values are exposed. All other conditions are verified
pixel-identical for global exposure.

The dark-bank recall difference is **+0.531 percentage points**, with descriptive
cluster interval **[+0.131, +2.368]**; precision is **−1.248 pp [−4.274, +0.895]**.
For invoices, recall is **+0.751 pp [−0.140, +2.387]**, precision **+0.503 pp
[−0.303, +1.170]**, exact regions **+1.607 pp [−1.429, +3.968]**. There are only
**three statement and five layout groups**; these bootstrap intervals are
discrete, unstable exploratory descriptions, not population significance or
independent-device guarantees. They do not justify a confident accuracy-gain
claim. In particular, invoice intervals include no gain.

On dark pages, global correction loses matched tokens on **two of ten bank
pages** and **16 of 50 invoice pages**. It reduces token precision on **five bank
and 17 invoice pages**. **24 invoice pages lose at least one exact region**, even
where a page's net token count improves; 28 exact regions are lost overall.
Using any exact-region loss, token loss, extra unmatched prediction or precision
loss as a regression, **seven bank and 24 invoice pages** regress in at least
one way. These overlapping counts must not be added. The page-level artifact
names all of them without exposing text. Native camera acceptance is unchanged
at **one correct/two wrong**, with one additional correct MRZ field; 18 frames
do not establish safety.

**Narrow recommendation:** a manual experimental brightness option for ordinary
OCR is feasible to implement and independently measure: one bounded scalar
transform, no added model, a clean no-op, modest native cost and a small dark-page
recall signal. It must retain the original capture and reading; activating it
does not certify the transformed reading as more correct. This is **not** a
recommendation for default preprocessing, an automatic retry/union selector, or
an ID/biometric acceptance profile. A production ID profile remains unsupported.
The parent must rerun the actual native/browser implementation and relevant
negative/acceptance metrics before any shipping decision. No browser parity,
phone latency or ≤5% speed claim is inferred from Python.

[Exact numerical contract](../experiments/research_optics/global-contract-v1.json):
use `optics.preprocess(rgb, "global_exposure")` only. The background thumbnail
is resized in **encoded RGB before** inverse-sRGB; this detail matters to parity.
Use the 512-pixel cap, INTER_AREA, 25×25 centered dilation, Gaussian sigma 9,
linear-interpolated p90, strict `p90 < 0.55` gate, scalar gain capped at four and
piecewise sRGB re-encoding with ties-to-even rounding. The full source image is
never resized. The local arm, glare mask and burst ranker are explicitly excluded.
No acceptance thresholds or field validators change.

## Training-data plan and licensing boundaries

**New author-published lead, added to the plan only:** [SSD-DIS, Scientific Data,
2 May 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13342580/) describes 12,224
aligned shadow/clean/mask triples, including handwriting and multilingual
documents, with Blender-derived shadows. The authors report removing images
containing faces, identification numbers, addresses, signatures or phone numbers;
this is their screening statement, not our inspection. The source mixes author
photography with Creative Commons web sources. The article is **CC BY-NC-ND 4.0**.

The dataset's own [DataCite DOI metadata](https://api.datacite.org/dois/10.6084/m9.figshare.29401811)
independently declares **CC BY 4.0**, rather than the article's license; the exact
metadata subset/hash is retained in
[ssd-dis-metadata.json](../experiments/research_optics/ssd-dis-metadata.json).
Direct Figshare metadata returned HTTP 403, so archive README/version and
per-source permissions remain unaudited. The
[author code repository](https://github.com/Jane54542/SSD-DIS) supplies synthesis
instructions but no affirmative code license was found. No weights were audited.
This is a promising shadow/calligraphy stress source after provenance review;
dataset metadata does not erase upstream source restrictions or establish
person/device grouping. No dataset image, archive, partition listing or code
was downloaded or run, and the current frozen benchmark is unchanged.

No training was performed. A practical next training set should teach a bounded
illumination/quality predictor, not a generator that guesses glyphs. Keep the
original reference text and per-pixel correspondence. Use three separate ledgers:
source-code license/revision; image/font/document license and provenance;
checkpoint license/training provenance. A permissive code license never fills
the other two entries.

- **Already usable synthetic sources:** author's
  [Bankstatemently MIT release](https://raw.githubusercontent.com/bankstatemently/bank-statement-parsing-benchmark/main/LICENSE)
  and [FATURA v1, Limam/Dhiaf/Kessentini](https://zenodo.org/records/8261508),
  recorded CC BY 4.0 in the existing acquisition manifest. Retain the exact
  pinned release and attribution; existing DEV must never enter training.
  FATURA's already separated TRAIN layouts are a possible training source, with
  incomplete field labels respected. They were not opened in this run.
- **Real-camera validation:** keep the existing author-published
  [MIDV-500 specimens](https://arxiv.org/abs/1807.05786v4), CC BY-SA 2.5 under the
  retained publisher notice and per-document provenance. These are laminated
  public specimens with real photography, not real customer IDs. Keep source
  specimen, all device sessions and every recapture together; preserve applicable
  attribution/share-alike when distributing adaptations. Nothing is redistributed.
- **New procedural training:** generate invented text, clean numerical fields,
  narrow punctuation, diacritics and serif/sans fonts with pinned redistribution
  permission. Apply exposure in linear light, shot/read noise, spatial illuminants,
  veiling/specular light with a recorded clipping mask, PSFs whose sampled MTF is
  retained, JPEG compression and coordinate-only warps. Include clean white paper,
  color blocks, thin/faded ink, crossed strokes and blank margins as negative
  quality controls. Freeze whole invented identities, layouts, font families,
  physical paper/lamination specimens and simulated camera configurations before
  generation; never randomly split frames/patches of one specimen.
- **Photography collection proposal:** author-created fictional sheets with known
  text; real devices, fixed distance/pose and measurable exposures; matte versus
  laminate; crossed/parallel polarizer acquisition when hardware exists; moving
  glare, shadows and controlled blur. Record camera response assumptions,
  exposure/white-balance locks and sequence timestamps. Entire physical sheet
  and device family stay in one partition. Any new collection is future work,
  not an acquisition performed or permission inferred here.
- **Handwriting/calligraphy:** dotted letters, fine joins and faint pen strokes
  are particularly important counterexamples for background estimation and
  sharpening. Use writer-authorized text/pen trajectories or independently drawn
  procedural strokes with exact character identities. Synthetic calligraphy
  fonts cannot certify real writer recognition. Do not silently repair spelling,
  names or digit strings. No handwriting corpus/license was cleared or downloaded.
- **Human identification/biometrics:** this study evaluates no face identity,
  skin-tone invariance, PAD, rPPG or writer identity. Improved document OCR cannot
  justify altering face/PAD thresholds. A separate consented, rights-cleared
  person/device/session-grouped study must measure TAR and actual FAR plus
  abstentions before applying these transforms to biometric matching. No real
  biometric training set or face-swap generator is proposed as implicitly cleared.

For original-versus-copy research, lighting quality must remain a nuisance
variable: glossy originals and laminated copies can both glare, while either can
be photographed sharply. These diagnostics are not proof of originality, a
physical document, a live person or authenticity. A training design needs
paired physical originals/prints/screens under the same acquisition conditions,
specimen/device separation and explicit unknown outcomes. No originality gain
is inferred from these OCR/quality measurements.

## Reproduction and evidence

Run the commands in [the experiment README](../experiments/research_optics/README.md).
Only code and aggregate JSON are placed in git. Source photographs, OCR strings,
reference text, per-specimen camera outcomes and immutable executable/model
snapshots stay under owner-private `/tmp/docscan-research-optics/`. No media,
biometric template, restored text or person-like field value is committed.

The initial nine procedural tests cover transfer-function round-trip, clean
no-op, bounded gain/black pixels, white-paper glare false positives, diagnostic
nonmutation, blur contrast loss, deterministic perturbations, denominator
retention on failure and missing-camera rejection. The separate audit verifies
all prediction/input hashes, permissions, frozen denominators, aggregate scores
and paired burst regressions. Latency remains a local native feasibility study;
the main bench, independent devices and phone/WASM timing are integration gates.
