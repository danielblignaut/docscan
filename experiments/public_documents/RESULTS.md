# External OCR development iteration — 24 October 2026

Frozen inputs: 50 FATURA invoices, 560 annotated fields, 10 pages from three
Bankstatemently statements. Dataset/referee/model hashes accompany all reports.
TRAIN data is acquired separately (400 invoices) and has not been used to fit
weights. Reserved layouts and statements were not evaluated.

| Native reader | Bank token recall | Bank token precision | Invoice region token recall | Invoice region token precision | Exact invoice regions | Failed pages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| OCRS page, baseline | 85.56% | 89.07% | 88.80% | 90.70% | 351/560 | 0/60 |
| PP-OCRv6 tiny, baseline | 73.66% | 96.19% | 87.36% | 93.50% | 392/560 | 1/60 |
| PP-OCRv6 tiny, bounded long lines | 88.52% | 96.41% | 87.36% | 93.50% | 392/560 | 0/60 |

Only `bsb-001-p3` changes between the two PP-OCR runs: 392/418 reference tokens
are recovered where previously the page returned an error. All other 59 pages
have identical scored results. The failure is a genuine 918×12-pixel line in
small-print terms, not a table rule. At recognition height 48 it exceeds the
old 3200-pixel width guard. Horizontal resizing now caps the tensor width at
3200, matching the existing Python reference pipeline; memory bounds remain.
No acceptance or verification checks are relaxed. This optional general-text
engine is independent of ID and POA OCR.

Address-block text recovery (`BILL_TO`, only 10 regions): PP-OCR gets 134/146
reference tokens (91.78%) and OCRS 132/146 (90.41%). Neither has a fully exact
region under the strict whitespace/punctuation normalization. These are region
text measurements, **not customer-address extraction or POA verification**.
Source field labels, region boundaries and line grouping influence this metric.

The referee was audited before scanner tuning. OCRS returns coordinates in its
resized working page; PP-OCR returns original-input coordinates. Scoring maps
both back to the input before selecting annotation regions. Earlier uncorrected
geometry runs are discarded diagnostics, not baseline evidence. Both reported
baselines and the candidate use the same corrected referee. Executables are
copied before inference so a concurrent build cannot mix versions mid-run.

Validation:

- Regression first failed in native Rust and the previous single-thread wasm
  build with `text line is too long at recognition scale`.
- The corrected implementation passes all 99 Rust tests.
- The original 12-page synthetic DEV corpus stays at zero normalized character
  error, 100% word recall, zero extra words. This smaller/easier corpus is a
  regression check, not the external-data result.
- Five Python referee tests check repetitions, wrong amounts, failure
  denominators, spatial assignment and working-page coordinate conversion.

No headline SOTA or significance claim: source layouts are few and correlated;
these are synthetic PDFs/invoices, not diverse phone photographs. Bank scoring
uses PDF transcription and does not measure transaction parsing. Invoice truth
covers selected regions, so no full-page hallucination rate is available there.
No latency improvement or phone-performance claim follows from these runs.

## Predeclared model/resolution ablation

A separate Python/ONNX Runtime experiment measured **all four** declared modes
on the same 60 pages, using the same field scoring. It uses the reference
geometry pipeline, so its tiny-960 numbers differ from Rust's; these are
candidate-model results, not browser performance or a shipped change.

| Candidate | Bank recall / precision | Invoice-region recall / precision | Exact invoice regions |
| --- | --- | --- | ---: |
| tiny, 960-pixel cap | 91.25% / 96.71% | 86.55% / 93.35% | 382/560 |
| tiny, 1600-pixel cap | 94.69% / 96.90% | 86.55% / 93.35% | 382/560 |
| small, 960-pixel cap | 94.51% / 97.96% | 91.80% / 95.69% | 439/560 |
| small, 1600-pixel cap | 96.10% / 97.61% | 91.80% / 95.69% | 439/560 |

All runs complete 60/60 pages. The larger detector and recognizer total about
31 MB versus 6.2 MB for tiny, and require a different recognition dictionary.
They are **not integrated into the browser**. The next deployable experiment is
an explicit small-print profile using the existing tiny weights; keeping more
detector pixels can help without a second model download. No default change is
justified by these prototype results alone.

Reproduce with the existing `experiments/ppocr_v6/requirements.txt` environment,
plus `pypdfium2==5.14.0`, then run:

```sh
python experiments/public_documents/model_candidates.py \
  --report /private/model-candidates.json
```

The review also hardened spatial scoring: OCRS canvases expanded by deskew are
now explicitly rejected until an inverse transform is available. The saved
FATURA canvases have the expected unrotated dimensions. New native evaluator
runs require the executable to confirm its explicit model directory and verify
model hashes before/after the run. The saved runs used the recorded same-checkout
models; these guards prevent incorrect provenance in future cross-checkout runs.

## Rust small-print profile

The single 1600-pixel Rust pass improved aggregate bank recall to 91.06%, but
lost 94 matched tokens on the small-print terms page. That result is retained
in `ppocr-reviewed-detail.json`; it was not selected as the final profile.

The opt-in profile compares the standard and detailed passes and chooses the
complete reading with the larger sum of alphanumeric characters weighted by
mean emitted-symbol confidence. Ties keep the standard reading. It does not
merge text or consult reference truth. It is a text-coverage heuristic, not a
calibrated correctness score. Pages already within the standard detector limit
use one pass; larger pages use two. Both passes retain the existing region,
line-width and input-memory guards. Reported timings include both passes.

Actual Rust results (`ppocr-small-print.json`): **94.62% bank token recall,
96.93% precision**, 2497/2639 matched tokens, one exactly transcribed page,
0/60 failures. The standard profile remains **88.52% / 96.41%**. The terms
page retains all 392 tokens that the standard pass recovered. Seven bank pages
improve, two are unchanged, and one loses two matched tokens (198→196).
All 50 invoice scores remain unchanged. The 12-page synthetic DEV regression
still has zero normalized character errors, 100% word recall and no extra words.

This optional profile deliberately spends more compute and is labeled slower
in the demo. It does not replace the standard/default reader. No speedup,
phone latency, universal improvement or state-of-the-art claim is made.
