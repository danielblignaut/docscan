# External document OCR development

The user-requested public-data loop adds external layouts to the existing
synthetic tests. These datasets are synthetic documents published by their
owners; they are not scraped personal financial records.

Sources:

- [Bankstatemently](https://github.com/bankstatemently/bank-statement-parsing-benchmark),
  MIT, revision pinned in `protocol.json`. Three DEV statements, all ten pages.
  Two further statements remain unfetched. Render at 144 dpi with the pinned
  PDFium version and use their PDF text layer as the transcription reference.
  This does **not** measure the publisher's transaction parsing benchmark,
  whose transaction truth is server-side. Word/token order is not scored.
- [FATURA v1](https://zenodo.org/records/8261508), Limam, Dhiaf and Kessentini,
  CC BY 4.0; publisher MD5/size plus local SHA-256 are checked. The fixed subset
  contains 400 TRAIN invoices (40 layouts) and 50 DEV invoices (five layouts).
  Five additional layouts stay reserved and unextracted. This custom separation
  is stricter than the publisher's shared DEV/TEST layouts but is not its
  leaderboard protocol. Downloading is not model training; no weights have yet
  been fitted on these documents.

No image, PDF, source text, model embeddings, or person-like field values are
committed. Local data and OCR caches are owner-private under
`/tmp/docscan-public-data` (override `DOCSCAN_PUBLIC_DATA`). The committed
manifests contain source revisions and hashes. `prepare.py` fetches only the
allowed bank statements and extracts only TRAIN/DEV FATURA entries. It excludes
OTHER (upstream OCR), TABLE (geometry only), and LOGO from text ground truth.

```sh
uv venv /tmp/docscan-public-data/venv
uv pip install --python /tmp/docscan-public-data/venv/bin/python -r experiments/public_documents/requirements.txt
/tmp/docscan-public-data/venv/bin/python experiments/public_documents/prepare.py
# Only when creating a new, versioned benchmark, before tuning:
/tmp/docscan-public-data/venv/bin/python experiments/public_documents/evaluate.py --freeze
# For existing benchmark: verify pinned content, score both shipped readers.
/tmp/docscan-public-data/venv/bin/python experiments/public_documents/evaluate.py \
  --binary docscan/target/release/examples/text_v6 --engine ppocr_v6_tiny \
  --report experiments/public_documents/results/ppocr-v6-baseline.json
/tmp/docscan-public-data/venv/bin/python experiments/public_documents/evaluate.py \
  --binary docscan/target/release/examples/text --engine ocrs_page \
  --report experiments/public_documents/results/ocrs-page-baseline.json
python3 -m unittest discover -s experiments/public_documents -p 'test_*.py'
```

Freeze and commit the referee separately from scanner changes. Evaluation
verifies every image/reference against `ocr-dev-v1.json`. It launches native
OCR on the full page, one process per page, at most two processes, each with
one RTen/Rayon thread, and a 180-second timeout. Failures yield empty readings
and stay in the denominator. Raw predictions stay local, cached by executable,
models, data manifest, and referee hashes. Reports contain only counts and IDs.
No speed claim is made from these process-level runs.

Metrics: Unicode NFKC/casefold/whitespace normalized exact field/page match,
and multiset whitespace-token precision and recall, with punctuation retained.
Amounts, dates and account-like numbers are not stripped or repaired by the
scorer. Repeated hallucinations cost precision. Bank pages have complete text
references; FATURA has only selected annotated regions. For FATURA, predicted
line centres determine region membership; annotations never guide recognition.
Region boundaries/line merges can affect scores and need auditing before
interpreting them as recognition errors. `BILL_TO` measures address-block text
recovery only; it does not measure semantic extraction or customer verification.
There is no full-page hallucination estimate for partially annotated invoices.
Samples share layouts and pages share statements; no independent-sample
significance or state-of-the-art claim follows from these DEV results.

The long-line regression is `node experiments/public_documents/wasm_long_line.mjs`
(after a wasm build). It reads the pinned synthetic bank page locally, asserts
that the long sentence survives, and reports only pass status, line count and
allocated wasm memory. An optional first argument selects an older package for
before/after reproduction. The old port rejects the whole page when a genuine
918×12-pixel terms line exceeds 3200 pixels at recognition height 48. Bounding
the resized width at 3200, as the Python reference already does, retains that
line without increasing the allocation limit. Extremely compressed text can
still misread; there is no promise of perfect long-line recognition.

Cache protocol v2 stages new predictions privately until model content and
modification metadata pass the end-of-run guard. Only a cache with a matching
validation marker is reusable; failed runs cannot poison a later run after
models are restored. `results/reviewed-cache-guard.json` confirms a full rerun
reproduced the final small-print scores under this guard.
