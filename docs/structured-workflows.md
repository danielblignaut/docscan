# Structured scan workflows

The browser now provides separate reader choices for printed device labels and
financial tables. Existing identity, face and proof-of-address acceptance rules
are unchanged by these additions.

## Fast labels

Detailed remains the default; select **Fast** on the barcode, device-label or
item card, or use `labelReader=fast`. It reads the full image with PP-OCRv6 tiny,
then uses the existing label association and check-digit logic. Raw codes appear
before background text reading. Stopping or failing that reading preserves the
codes. The export records `labelReader` and the experimental limitation.

The full DEV comparison and retained rejected candidates are in
[the speed report](improvements-label-speed-v2.md). The Fast reader gained 53
correct label/value fields and lost one serial-number field across 72 synthetic
DEV images. Its strict preservation gate failed; this is an optional reader,
not a calibrated automatic selector. No GPU or quantisation speedup is claimed.

## Item sessions and GS1

`mode=items` keeps decoding while staff pan. It retains at most six views and
20 MiB of JPEGs, releases the camera on Finish, then reads labels in those views.
Photo/PDF imports use the existing ten-page limit. Retained views contribute once
to the reconstructed identifier rows, even after OCR enrichment. Identical
original SHA-256/page references do not count as independent observations.

The UI shows indexed and unindexed IMEIs, identity anchors, contested values,
weak associations, missing values and bounded-history losses. Outlines explicitly
group observations; they do not prove a package's authenticity or quantity.
Product codes shared by multiple packages never establish stock counts.

GS1 parsing uses a pinned Apache-2.0 syntax dictionary. Only successfully parsed
fields feed structured identifiers. Missing required AIs, unsupported rules and
invalid payloads remain visible. Digital Links are parsed locally and never
fetched. DataBar's ambiguous `]e0` form is retained raw. See
[GS1](gs1.md) and [grouping](item-grouping.md).

## Financial tables

`mode=tables` defaults to PP-OCRv6 tiny, with ocrs and a detailed PP-OCR option
available. PDF native text is still separate, untrusted evidence; the displayed
tables come from rendered pixels and OCR. Every extracted cell has source boxes
and text indices. Changing date order, decimal separator or currency reprocesses
retained OCR without another image read.

Files are separate accounts unless the caller explicitly supplies
`sameAccountFiles`; the UI offers an unchecked same-account confirmation for
multiple statement files. Potential duplicate statements remain visible and do
not supply additional recurring-income evidence. Credit-card sign conventions,
missing pages, unread amounts and resource truncation cannot establish a complete
independent reconciliation. Incomplete metadata inspection is displayed separately
from a page that could not be rendered or read.

Amounts use exact decimal arithmetic. CSV guards spreadsheet formulas. Checks
only assess extracted numbers; they do not authenticate a bank, employer,
document or income. The authored fixtures and review counterexamples exercise
behaviour, not real-world accuracy. See [financial extraction](financial-tables.md).

## Browser reproduction

Use a Python virtual environment with
`pip install -r demo/e2e/feature-fixtures-requirements.txt` and the system
DejaVu Sans font. Run `python demo/e2e/generate-feature-fixtures.py`, build the
single and optional threaded WASM packages, then build the demo. The fixtures
contain only invented identifiers and financial documents.

- `node demo/e2e/document-features.mjs`: actual GS1 decoders, multi-item image and
  camera pan, manual outlines, table cells, CSV/JSON and preview cleanup.
- `DOCSCAN_FEATURE_CASES=tables DOCSCAN_FINANCIAL_ENGINE=ocrs DOCSCAN_BENCHMARK_ONLY=1 node demo/e2e/document-features.mjs`:
  diagnostic OCR comparison, keeping all expected numeric cells in the denominator.
- `demo/e2e/fast-labels.mjs`: private input paths from `DOCSCAN_PERF_IMAGE` and
  `DOCSCAN_EXPECTED_REPORT`; compares values by digest and logs only aggregate
  counts/timings. `DOCSCAN_URL` chooses a running production preview or Pages.

Browser table reports are written into a fresh `/tmp/docscan-feature-browser-*`
directory. The initial paired browser check recovered 29/48 numeric cells at the
correct row and column with ocrs, and 48/48 with PP-OCRv6 tiny, across one invented
invoice, statement and payslip. This is a three-fixture integration result, not
an estimate of performance on real financial documents.

## Final integrated build checks

The final production browser run passed actual GS1 DataMatrix/Code128 decoding,
image and camera item flows, manual boundaries, all 48 numeric cells at the
correct positions across three fictional financial documents, CSV/JSON export,
and cleanup. Fast labels preserved all five private-photo values in 2.700 s
(single thread) and 3.142 s (two threads); raw codes took 0.238/0.257 s. Fast
model-download failure retained the codes and requested profile, and retry
succeeded without switching readers. Host load makes these descriptive timings.

All 216 frontend unit tests passed (two browser-only checks are skipped there);
139 Rust tests passed. The single and threaded packages and TypeScript/Vite
build passed. Source/build hashes and aggregates are retained in
[`final-browser-v1.json`](../experiments/feature_integration/final-browser-v1.json).
An initial final-test attempt hit the preview while Vite was rebuilding and
failed navigation before inference; the successful run began after the build
finished. Earlier measurements remain recorded separately.
