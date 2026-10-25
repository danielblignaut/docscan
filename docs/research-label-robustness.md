# Label robustness: one bounded round on Fast serial preservation

**Verdict: both pre-declared arms were rejected. Nothing is promoted, and no
integration patch is offered.** Neither arm raised correct label+value
fields over the two corpora combined, and each lost fields the Fast reader
had right. The Fast reader (`Scanner::labelled_fast_native`, PP-OCRv6 tiny)
stays as shipped in PR 10: an explicit opt-in profile, with Detailed as the
default. One measured round; nothing was tuned or re-run after it.

Method, files and provenance: [experiments/label_robustness](../experiments/label_robustness/README.md).
Aggregate evidence: `experiments/label_robustness/evidence/`.

All runs used a `git archive` snapshot of HEAD `0526c5de296b`, so other
agents' uncommitted edits were excluded, plus this experiment's probe and a
patch to the snapshot's `text_v6.rs` only. Builds were `--locked --release
-j2`; runs used 2 workers × 1 thread (CPUs 6 and 7), natively. Source, probe
binary, models and the stress gold were sha256-frozen before the measured
run, and every phase checked them. Corpora: the 72 labelled
`barcode_synth_dev` frames, plus a new fictional stress corpus. No TEST or
reserved data was used, and no value appears here or in the evidence. The
private user photo was not used (G7 not run): no `USER_IMAGE` /
`USER_REPORT` handoff was supplied.

## What Fast gets wrong with serials (pre-freeze diagnosis, DEV)

Snapshot `d0` (unpatched) reproduces the PR 10 numbers exactly: 268/296
correct label+value fields and 6 false fields. All 6 false fields are
text-kind `SN` fields. Of the 28 truth fields Fast misses:

| Class | Count | Labels |
| --- | --- | --- |
| Value absent from every OCR line (≥3 edits), bars decodable | 14 | 13 unlabelled codes, 1 SN |
| Value printed exactly in an OCR line (parse / association miss) | 9 | IMEI1 2, IMEI2 1, unlabelled 6 |
| **One edit from an OCR line** | **5** | **SN 5** (4 without a barcode) |

The serial failure mode is narrow. All 5 one-edit slips fall on an interior
character: 4 are digit substitutions inside an alphanumeric serial, 1 is an
insertion. None falls on the first or last character. They occur on easy and
medium frames at normal text sizes (em 20–32 px). Five of the six false
fields are these same slips, shown as wrong serials. A serial has no check
digit to catch them. This diagnosis guided which arms were chosen; it looked
at aggregate classes only, never at a single frame, and never at the one SN
that PR 10 named.

## Sources and the two arms (frozen before measurement)

- **Official pipeline geometry.** The pinned PP-OCRv6 tiny detector's
  `inference.yml` ([HF `PP-OCRv6_tiny_det_onnx@2ba1506`](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det_onnx/blob/2ba1506c0380b8f0b03dd142459aac66d4421f6c/inference.yml))
  sets DB `thresh 0.2`, `box_thresh 0.4` and `unclip_ratio 1.4`. `text_v6.rs`
  already uses these. The recogniser's config ([HF `PP-OCRv6_tiny_rec_onnx@2612ab3`](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx/blob/2612ab37152ae0a677521bae4e1e3d4fb4cf7c30/inference.yml))
  uses `image_shape [3, 48, 320]` with `CTCLabelDecode`. PaddleX's
  `OCRReisizeNormImg` ([processors.py](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/inference/models/text_recognition/processors.py))
  pads to at least 320 and caps width at 3200, which `text_v6.rs` matches.
  PaddleX's `get_rotate_crop_image` ([crop_image_regions.py](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/inference/pipelines/components/common/crop_image_regions.py))
  uses a cubic perspective crop with replicated borders and **no margin**,
  and it turns tall crops when h/w ≥ 1.5; `text_v6.rs` does the same. A
  crop-margin arm would therefore have departed from the official pipeline,
  and the diagnosis found no first- or last-character errors for a margin to
  fix. It was not chosen.
  One real divergence remains. The OCR pipeline ([pipeline.py](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/inference/pipelines/ocr/pipeline.py),
  [OCR.yaml](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/configs/pipelines/OCR.yaml))
  detects on a resized copy but crops recognition regions from the original
  image. Fast instead crops from the 1280-wide copy that `labelled_with`
  makes, while the app hands it photos up to 1920 wide
  (`demo/src/photo.ts`, `pixels(file, 1920)`).
- **CTC.** A CTC model gives every candidate string a likelihood through the
  forward recursion over the blank-extended labels (Graves, Fernández, Gomez
  and Schmidhuber, *Connectionist Temporal Classification*, ICML 2006). That
  paper also notes that best-path (greedy) decoding need not find the most
  probable labelling. Two CTC recognisers whose errors differ can therefore
  rescore each other's readings: an equal-weight sum of log-likelihoods,
  that is, a product of experts. Both recognisers were already in the repo:
  PP-OCRv6 tiny (Fast) and ocrs's `text-recognition.rten` (Detailed). The
  [original CTC paper](https://www.cs.toronto.edu/~graves/icml_2006.pdf) was subsequently checked by the parent against the author-hosted copy; no gate or candidate was changed. The model configuration links are commit-pinned. PaddleX `develop` links were fetched during the round but are mutable references; they are not frozen source receipts. The measured local code, models and binaries are pinned separately.

| Arm | What changes | Bound |
| --- | --- | --- |
| `a-fullres` | Recognition crops sampled from the frame as given rather than its 1280-wide copy (official crop source). Detection unchanged. | Frames ≤ 1280 wide read identically; crop ≤ 4 MP as before |
| `b-rescore` | Every horizontal line: PP-OCR greedy vs ocrs greedy on the same quad; the higher summed CTC log-likelihood wins, PP-OCR on ties. Skipped if a string falls outside the other alphabet; never changes a digit run that passes its check digit. | One extra ocrs line recognition per line |

The gate was declared in `run.py` before the run (G1–G7; summarised below).

## Results (one round; 0 probe failures; replica identical to Fast on 192/192 frames)

**DEV (72 frames, 296 truth fields, 122 serials)**

| Reading | Correct label+value | False | SN correct | SN false | Serial errors | Truth lost / gained vs Fast | Native ms (sum) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fast (baseline) | **268** | **6** | 116/122 | 6 | 12 | – | 37 952 |
| Detailed (comparator) | 216 | 22 | 91/122 | 21 | 52 | 53 lost / 1 gained | 235 567 (6.21×) |
| `a-fullres` | 269 | 5 | 117/122 | 5 | 10 | 0 / 1 SN | 37 916 (1.00×) |
| `b-rescore` | 267 | 7 | 115/122 | 7 | 14 | 1 SN / 0 | 56 750 (1.50×) |

**Stress (fictional, 30 specimens × 4 conditions = 120 frames, 480 truth fields, 196 serials)**

| Reading | Correct label+value | False | SN correct | SN false | Serial errors | Truth lost / gained vs Fast | Specimens better / worse | Native ms (sum) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fast (baseline) | **450** | **14** | 183/196 | 12 | 25 | – | – | 67 275 |
| Detailed | 381 | 35 | 155/196 | 31 | 72 | 74 lost / 5 gained | 1 / 25 | 488 824 (7.27×) |
| `a-fullres` | 449 | 15 | 182/196 | 13 | 27 | 2 SN / 1 SN | 0 / 1 | 88 121 (1.31×) |
| `b-rescore` | 449 | 15 | 183/196 | 12 | 25 | 1 IMEI2 + 1 SN / 1 SN | 1 / 2 | 101 009 (1.50×) |

Stress by condition, correct label+value /120 (false fields):

| Condition | Fast | Detailed | `a-fullres` | `b-rescore` |
| --- | --- | --- | --- | --- |
| clean | 119 (1) | 106 (7) | 118 (2) | 119 (1) |
| font (Liberation Sans/Serif/Mono, DejaVu Sans Mono) | 117 (2) | 106 (6) | 118 (1) | 117 (2) |
| blur (σ 1.6–2.2 px, JPEG 50–70) | 97 (8) | 79 (19) | 96 (9) | 96 (9) |
| perspective (28–38° tilt) | 117 (3) | 90 (3) | 117 (3) | 117 (3) |

No reading produced a false field that passes a check digit, and no kept
field changed its check result. The `a-fullres` costs differ between
corpora, 1.00× on DEV and 1.31× on stress, although the arm changes only
the 1920-wide frames. That spread is host noise; the field results are
deterministic.

## Gate outcome, and why each arm is rejected

| Gate | `a-fullres` | `b-rescore` |
| --- | --- | --- |
| G1 replica parity (both corpora) | pass | pass |
| G2 no Fast truth field lost | **fail** (2 SN on stress) | **fail** (1 SN DEV; 1 IMEI2 + 1 SN stress) |
| G3 false fields not more, none check-valid | **fail** (stress 15 vs 14) | **fail** (DEV 7 vs 6, stress 15 vs 14) |
| G4 net gain over both corpora; serial errors not more | **fail** (718 vs 718; stress serial errors 27 vs 25) | **fail** (716 vs 718; DEV serial errors 14 vs 12) |
| G5 no check change, no failure | pass | pass |
| G6 cost ≤ 2.0× Fast | pass (1.00× / 1.31×) | pass (1.50× / 1.50×) |
| G7 user photo | not run (no handoff) | not run |

- **`a-fullres`: rejected.** On DEV it looks like a free win: one serial
  recovered and one false serial removed, at no cost (only the 15 1920-wide
  frames can change, and 1 does). The held-out stress corpus reverses it. Of its 40
  1920-wide frames, 3 change: 2 correct serials are lost, 1 is gained, and
  1 false field is added. The net over both corpora is zero, with two
  correct fields lost, so the DEV gain does not generalise. One unverified
  hypothesis: a crop sampled at 1.5× is then point-sampled down to height
  48 without an anti-aliasing prefilter. The official pipeline's
  `cv2.resize` linear resize behaves the same way, so a fix would also
  depart from the official preprocessing. This round did not test it.
- **`b-rescore`: rejected.** ocrs's greedy reading differed from PP-OCR's on
  86% of DEV lines (299/347). The summed likelihood replaced 37 DEV lines and
  46 stress lines, and the net effect on fields was negative: a lost IMEI2 and
  two lost serials. It also cost 1.5× Fast. The product of experts does not
  rescue serials here. ocrs, which already reads worse than Fast on these
  labels (Detailed: 52 serial errors against 12), wins often enough to
  inject its own slips.

What this leaves standing: Fast keeps more serials than Detailed on both
corpora, held-out fictional stress included (DEV 116 vs 91, stress 183
vs 155), with far fewer false serials (6 vs 21; 12 vs 31). On
specimens it is worse than Detailed on only 1 of 30, against 25 where
Detailed is worse. Its remaining serial errors are mostly one interior
digit slip with no check digit to catch it. Neither a second crop source
nor a second recogniser's evidence fixed those without new losses.

## Limits

- Evidence is synthetic: the 72 DEV frames and a fictional corpus built
  from the same sticker generator (new seed 5150, four unseen fonts, blur
  and tilt beyond DEV's labelled caps). The real user photo was not
  re-checked.
- The arms were chosen after a DEV diagnosis, so DEV is not held out; the
  stress gold was frozen before any reader saw it and is the held-out check.
- Timings are native, 1 thread, on a shared host (load average about 9 on
  12 threads); wasm and browser cost were not measured (the parent owns
  runtime).
- Not tried, and not recommended from this round alone: anti-aliased crop
  resampling, beam or prefix search on PP-OCR alone, crop margins (no
  end-character errors found), a larger PP-OCRv6 recogniser (no pinned,
  sourced weights in the repo).
