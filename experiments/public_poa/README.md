# Public proof-of-address DEV experiment

Read [REPORT.md](REPORT.md) for the measured baseline, failure evidence and next
general fix; aggregate-only artifacts are under [results/](results/).

A tiny external semantic-extraction referee, separate from `bench/` and all
shipping code. This round uses **one fictional identity, one US bank-statement
layout and three correlated variants**. It is not a deployment benchmark,
authenticity check, training run or state-of-the-art claim. No TEST data is
accessed. No source documents, truth values or OCR text belong in this directory.

## Source and independent truth

Attribution: **Synthesized**, [sample library](https://www.synthesized.io/sample-documents)
and [bank statement](https://www.synthesized.io/sample-bank-statement),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The publisher identifies the people and institutions as fictional. Downloaded
JSON independently confirms `synthetic: true`, the licence, field values and
variant metadata. Only the four linked files were acquired: clean, scanned and
fax PDFs plus JSON truth; the two publisher pages were archived as provenance.
Each asset is pinned by SHA-256 in `source-pins.json`. Library HTML can change;
a reproduction correctly refuses changed bytes rather than silently repinning.

All PDFs are one page. The clean PDF has 159 text-layer words; the other two have
none, confirming the advertised distinction. Rasterisation uses PyMuPDF 1.26.7
at 150 DPI, RGB without alpha, keeping watermarks. The resulting image sizes are
1275 × 1650 for clean/scanned and 1275 × 1586 for fax. Only whole-page flat input
is measured; page detection, camera capture, voting across frames and browser
latency are outside scope.

`protocol.json` fixes the selection, reference clocks, mapping, normalisation,
denominators and negative checks. It was frozen with harness/source hashes,
PDF/render hashes, executable hashes and model hashes **before inference**.
All variants stay together in DEV. The single identity is the independent unit;
three variants do not support a meaningful confidence interval.

The nine annotated shipped fields are holder, full street including apartment,
city, postal code, issuer, full printed masked account, document type, and both
statement-period endpoints. Case, punctuation and whitespace normalise; spelling,
ZIP length, house number, unit and account masking do not. There is no separate
issue date in publisher truth: `document_date` is explicitly unscored, with only
its relationship to the period reported. The US state has no equivalent in the
shipped South African province enum; it is a schema coverage gap. Missing suburb
annotation is also not scored. These gaps are not null-field successes.

Failures, timeouts and empty/malformed output retain all nine field opportunities.
Failed reads cannot earn successful negative rejection. Customer checks use the
shipped `poa_capture` on each page's OCR words separately, with a known customer
from publisher truth. The synthetic negative customers change the entire name or
only the leading house number. The old case advances the reference clock without
altering the document. Paired matching-accept-and-negative-reject counts expose
reject-all behaviour. US acceptance is a diagnostic, not a requirement to accept
this document under South African policy. No issuer-decoy sample is available.

The clean PDF's text layer is run through the same extractors as a **separate
localisation diagnostic**. It retains publisher geometry and bypasses image OCR;
it is never pooled into the three-image denominator or called oracle-quality OCR.
`evidence.py` reports lexical truth visibility and missed fields without exporting
any source text. Its diagnostics are descriptive, not additional scored metrics.

## Reproduce

From the repository root (all raw files and predictions are owner-private):

```sh
umask 077
uv venv /tmp/docscan-public-data/poa-synthesized-v1/venv
uv pip install --python /tmp/docscan-public-data/poa-synthesized-v1/venv/bin/python \
  -r experiments/public_poa/requirements.txt
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s experiments/public_poa -v
/tmp/docscan-public-data/poa-synthesized-v1/venv/bin/python experiments/public_poa/harness.py prepare
/tmp/docscan-public-data/poa-synthesized-v1/venv/bin/python experiments/public_poa/harness.py freeze
/tmp/docscan-public-data/poa-synthesized-v1/venv/bin/python experiments/public_poa/harness.py evaluate
PYTHONDONTWRITEBYTECODE=1 python3 experiments/public_poa/evidence.py
```

`prepare` copies release executables into private storage; `freeze` pins their
bytes. The example embeds the repository model path at compile time, so models
are hash-checked there before and after evaluation. `evaluate` refuses to overwrite
a baseline; repeat runs require a separate `--data-root`. `aggregate` can rescore
saved outputs only with the original frozen referee. No cargo build modifies the
shared target directory in this experiment.

The initially supplied release executables were incompatible with the current
model (32 input features versus 50 required). The complete first run is retained
under `/tmp/docscan-public-data/poa-synthesized-v1`; it is not discarded or
presented as accuracy of a working scanner. A separate current-source build and
run are retained under `/tmp/docscan-public-data/poa-synthesized-current-v1`.
Both use identical referee, protocol, sources, renders and models. Only binary
pins differ. Build-to-HEAD correspondence is unverified for the old artifacts;
the current-source build has separate source-hash provenance.

To rebuild independently without conflicting with another agent's cargo work:

```sh
CARGO_TARGET_DIR=/tmp/docscan-public-data/poa-synthesized-v1/build-target \
  /home/dan/.cargo/bin/cargo build --manifest-path docscan/Cargo.toml --locked \
  --release --example poa --example poa_fields --example poa_capture -j 2
```

For a fresh data root, run `prepare`, replace its three `bin/` files with these
new executables **before `freeze`**, then `freeze` and `evaluate` with that root.
Never replace a binary after freezing or overwrite the failed first run.

## Candidate follow-up data

[InvoiceOCR-Synth](https://huggingface.co/datasets/alamgirqazi/invoice-ocr-synthetic/raw/main/README.md)
declares fictional synthetic content, CC BY 4.0 and 177 `utility_bill` template
base documents, each with three quality variants. Only its dataset card was
read: no Parquet/images downloaded. Template membership alone does not establish
that a record is a utility bill suitable as proof of address. A future protocol
must audit document class, customer/billing address semantics and printed-field
availability, pin the revision, and group complete file identities across quality
variants. Already cached Bankstatemently material was not added to this round.
