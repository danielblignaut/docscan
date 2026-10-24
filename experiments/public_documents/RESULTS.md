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
