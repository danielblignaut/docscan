# Cross-domain capture and verification research, 2026-10-24

This round connects imaging physics, document forensics, handwriting and biometric
quality. Published benchmark results are research leads, not measurements of
this repository or calibrated confidence in a submitted identity document.

The executable tracks are [originality detection](research-originality-detector.md),
[optics](research-optics-2026.md) and [identity science](research-identity-science-2026.md).
They retain frozen candidates and unsuccessful results. No TEST/lockbox results
are used to choose a change.

## What should compound, and what must remain separate

1. Preserve original bytes and capture pixels for forensic evidence. Enhancement
   for recognition belongs on a separate derived branch: removing moiré, flattening
   shading or normalizing colour can erase precisely the cues a recapture detector
   needs. Do not sum correlated OCR, sharpness and recapture measurements into an
   invented authenticity probability.
2. Evaluate image quality against downstream reading/verification errors and
   coverage. A better score on selected sharp frames is not an end-to-end gain
   if more legitimate users fail capture. Retain failed detections and rejected
   frames in the evaluation denominator.
3. Learn from physically distinct image formation processes. Vary illumination,
   reflectance, sensor noise, motion, printing and display sampling independently
   of the identity/document label. Split by source specimen/writer/session/device
   before making derivatives, so neighbouring frames cannot leak across splits.
4. Separate screen recapture, printed copy, content tampering, document issuer
   authenticity and live-person presentation. A negative result for one attack
   family does not establish an original, authentic document or a live person.
5. Use handwriting science for hypotheses about strokes and within-document
   consistency. Writer verification requires appropriate known-writer samples;
   slant, a font anomaly or a scanned signature alone does not identify a person.

These are design inferences connecting the sources below, not claims that the
papers establish a unified detector.

## Primary-source research leads

| Field | Primary source | Transfer to docscan | Boundary |
| --- | --- | --- | --- |
| Face photography and quality | [NIST FATE Quality](https://pages.nist.gov/frvt/html/frvt_quality.html) | Track actionable blur, exposure and pose defects and evaluate discard-versus-error trade-offs | Quality is not liveness or identity; failures must remain counted |
| Face image specification | [ISO/IEC 29794-5:2025 abstract](https://committee.iso.org/cms/live/live/en/sites/isoorg/contents/data/standard/08/10/81005.html) | Keep capture-quality measurements separate from recognition | The public abstract concerns individual images, not pair/sequence verification; the full standard was not purchased |
| Handwriting and human error | [NIST handwriting human-factors project](https://www.nist.gov/programs-projects/forensic-handwriting-examination-and-human-factors), [IR 8282r1](https://nvlpubs.nist.gov/nistpubs/ir/2021/NIST.IR.8282r1.pdf) | Matched writing types, natural variation, blind assessment and explicit inconclusive outcomes | Generated fonts do not validate forensic writer identification |
| Selective confidence | [Calibrated Selective Classification](https://arxiv.org/abs/2208.12084) | Measure confidence within the subset receiving a decision, plus coverage and out-of-domain errors | A model logit or synthetic accuracy is not a calibrated physical-copy probability |
| Illumination/reflectance | [Joint shadow removal and intrinsic decomposition, AAAI 2025](https://ojs.aaai.org/index.php/AAAI/article/view/33151) | Factor lighting changes from document appearance; test bounded illumination correction | Learned restoration can alter evidence; no imported weights or published-score substitution |
| Portrait restoration | [Structure-Guided Diffusion, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Yu_Structure-Guided_Diffusion_Models_for_High-Fidelity_Portrait_Shadow_Removal_ICCV_2025_paper.html) | Useful training/degradation hypotheses and identity-preservation tests | Generative inpainting is not adopted as a verification preprocessing default |
| Physical face forensics | [Specular Reflection Inconsistency, ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/1de15773f510ec4edd1b3a105d979667-Abstract-Conference.html) | Reflectance/light consistency may complement spatial/frequency cues | Deepfake detection and physical presentation attacks are different targets; no zero-shot validity claim |
| Temporal illumination | [rPPG under extreme lighting, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Shao_Remote_Photoplethysmography_in_Real-World_and_Extreme_Lighting_Scenarios_CVPR_2025_paper.html) | Study temporal lighting interference before treating periodic colour as physiology | Pulse-like variation alone is not a liveness decision; no medical inference |
| Paired biometric training | [Paired-Sampling Contrastive Framework, ICCV Workshops 2025](https://openaccess.thecvf.com/content/ICCV2025W/FAS2025/html/Balykin_Paired-Sampling_Contrastive_Framework_for_Joint_Physical-Digital_Face_Attack_Detection_ICCVW_2025_paper.html) | Pair genuine/attack examples so content identity does not become a shortcut | Code, weights and training data rights require separate checks |
| Document recapture | [DLC-2021 author paper](https://www.mdpi.com/2313-433X/8/7/181), [LC&DF author implementation](https://github.com/chenlewis/LC-DF-For-DPAD) | Learn recapture cues against security-texture counterexamples | Laminated specimens are not issuer-authenticated passports; publication variants and checkpoint provenance differ |
| Paired document shadows | [SSD-DIS, Scientific Data 2026](https://doi.org/10.1038/s41597-026-07204-4) | Candidate clean/shadow/mask curriculum including multilingual and handwritten documents | Source metadata describes filtering; verify the dataset's own license and split before importing |

## Training-data progression

Start with controlled synthetic ablations to detect label leakage and reproduce
implementation errors, then test on author-released physical captures. Add
matched negative controls: originals with security patterns, legitimate grayscale
scans, printer halftones, low light, JPEG blocks, mixed fonts, scanner OCR text
layers and benign revisions. Include realistic attacks without those obvious
artifacts. A detector must not learn that all colour documents are originals or
that all grayscale/edited files are fraudulent.

For any new corpus, record publisher URL and revision, data/code/weight licenses
separately, asset hashes, source specimen and acquisition device/session, attack
family and derivation parent. Freeze TRAIN, calibration and DEV membership before
inference. Use labels for the actual experimental target—e.g. screen recapture—
rather than relabelling every attack image 'tampered'. Evaluate held-out devices
and specimen groups, group-level uncertainty, false alarms, misses, abstention
and coverage. Real bank provenance needs independent issuer/cryptographic
validation; training on plausible-looking statements does not supply it.

The current public digital-file inspector preserves these distinctions, but is
not itself a learned recapture or issuer-authenticity model. Experimental detector
promotion and measured gains are reported in the track reports above.

## Completed measurements in this round

| Track | Observed result | Decision |
| --- | --- | --- |
| Barcode image/camera workflow | All eight codes read through home upload, camera-to-file import and denied-camera import; live GitHub Pages checked | Merged and deployed in PR #6; decoder policy unchanged |
| Handwriting-inspired repeated-number comparison | 329→356 correct of 672 DEV pairs, but 26 new benign flags and 43 newly missed alterations | Reject normalization candidate; retain generated stress data and baseline/candidate evidence |
| Global exposure (Python reference) | Dark invoice recall 84.73→85.48%, bank recall 89.12→89.66%; 28 exact invoice regions lost and bank precision declines; 60 clean pages unchanged | Only a manual experimental ordinary-OCR alternative merits implementation testing; no default/ID promotion |
| Local illumination | Correct camera accepts 1→3/12, but two new wrong-accept frames despite unchanged wrong-accept total | Reject for acceptance integration |
| Burst selection | Bank recall 65.29→5.23%; primarily motion-blurred pages selected; one genuine camera accept lost | Reject selection rule |

These exploratory datasets have few independent layout/specimen groups. The
exposure study's cluster intervals do not establish a population improvement or
phone latency guarantee. None of these results validates original-versus-copy
classification. The copy-detector report separately records real and simulated
training, effective sample sizes, acquisition mistakes and any promotion block.

## Real recapture implementation and promotion boundary

The final automatic detector takes a whole RGB image, samples a deterministic
3×3 grid of native 224-square patches, aggregates fixed texture/color features,
and applies an exported trained linear model. It requires no document annotations.
Training/evaluation and JSON export are runnable locally; explicit experimental
opt-in is required. It emits a possible screen-recapture indication or abstains,
never an original-document verdict or a calibrated confidence probability.

On the final device-separated DEV cohort it detects **9/24 screen recaptures**
and falsely flags **2/48 first captures**, with **61/72 abstentions** and no
runtime failures. The positives represent only six physical specimens. These
figures do not justify replacing the production nulls or claiming a general
copy detector. Print copies, genuine issuer originals and unseen devices remain
unvalidated. The final model artifacts and raw images remain private; code,
receipts, aggregate evidence and reproduction commands are retained.

The [detector report](research-originality-detector.md) records the acquisition
history, including an initial import quarantined before image inference because
source-held-out membership was uncertain, and a failed crop-coordinate attempt
that produced no trained models. The replacement uses exact author-TRAIN-list
membership and verifies the sealed acquisition receipts. Those mistakes remain
visible; they are not erased by a later successful run.
