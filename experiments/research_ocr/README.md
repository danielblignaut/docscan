# Modular OCR and sliced detection research

Primary-source survey: [OCR research](../../docs/research-2026-ocr.md).
All results are DEV only. No application source, default, model artifact or
verification threshold is changed by this experiment.

Three separately frozen rounds were run:

1. `protocol.json`: seven Python/ONNX Runtime model-capacity and strip-detection
   configurations on all 50 FATURA invoices and ten Bankstatemently pages.
2. `native-protocol.json`: four isolated native probes, using the shipped Rust
   text pipeline and either the existing recognizer or the official small one.
   Detection stays tiny. Tiny probes reproduce **every original scored row**.
3. `negative-protocol.json`: all four native configurations on the unchanged
   twelve synthetic regression pages and eight generated non-text pages.

The hybrid is our hypothesis, inspired by PP-OCRv6's modular architecture;
strips are our adaptation of sliced inference to preserve complete text lines.
Neither experiment reproduces a paper's complete training/evaluation protocol.

## Results: native Rust, comparable within this table

| Recognizer / profile | Bank token recall | Bank token precision | Invoice-region token recall | Invoice-region precision | Exact invoice regions |
| --- | ---: | ---: | ---: | ---: | ---: |
| tiny / standard | 88.52% | 96.41% | 87.36% | 93.50% | 392/560 |
| small / standard | 89.16% | 97.03% | 91.99% | 95.11% | 428/560 |
| tiny / detailed | 94.62% | 96.93% | 87.36% | 93.50% | 392/560 |
| small / detailed | **95.83%** | **97.76%** | **91.99%** | **95.11%** | **428/560** |

All four complete 60/60 pages. The detailed hybrid matches 2529/2639 bank tokens
and 2940/3196 invoice-region tokens. Its weights total 22,939,968 bytes, versus
6,243,229 for tiny/tiny and 31,039,890 for the full small pair. This is a download
size comparison, not a speed claim. No new weights were trained.

All four have zero normalized CER, full word recall and zero extra words on the
12 simple regression pages. They return no text on all eight generated non-text
pages. These limited probes do not establish real-world hallucination safety.

The native probes snapshot `docscan/src/text_v6.rs`. Only the small recognizer's
pinned dictionary, class count and corresponding size bounds differ; detection,
crops, geometry, CTC and detailed-mode selection remain identical. They compile
against the exact Cargo-fingerprint-selected dependency rlibs. Source, dictionary,
model and executable hashes accompany the reports. This is **native feasibility
on the same DEV data**, not held-out confirmation or a browser integration.

## Python reference comparisons

| Detector / recognizer / mode | Bank recall / precision | Invoice-region recall / precision | Exact regions |
| --- | --- | --- | ---: |
| tiny / tiny / 960 | 91.25% / 96.71% | 86.55% / 93.35% | 382/560 |
| tiny / small / 960 | 92.27% / 97.44% | 92.46% / 95.82% | 445/560 |
| tiny / small / 1600 | 95.57% / 97.64% | 92.46% / 95.82% | 445/560 |
| small / tiny / 960 | 92.80% / 96.15% | 84.36% / 91.95% | 346/560 |
| small / small / 960 | 94.51% / 97.96% | 91.80% / 95.69% | 439/560 |
| tiny / tiny / strips | 93.14% / 96.20% | 86.55% / 93.35% | 382/560 |
| tiny / small / strips | 94.32% / 97.00% | 92.46% / 95.82% | 445/560 |

All seven complete 60/60 pages. Larger detection alone regresses invoices;
strips add some bank recall but reduce precision relative to the corresponding
full-page mode. Neither is selected as a universal replacement. Geometry differs
between this reference and Rust, so compare **within** each table, not across them.

## Provenance correction and reproducibility

Review caught that a basename-keyed guard could collapse detector/recognizer
files both named `inference.onnx`. Future guards use complete paths. Original
reports remain unchanged. `results/artifact-guard-audit.json` verifies all model,
config and card hashes and confirms their modification/change timestamps predate
the protocol materialization; no actual model mutation affected these results.
A regression test changes only the detector and verifies detection by the guard.

Raw predictions, generated images, source snapshots and binaries stay private
under `/tmp/docscan-research-ocr`; git holds only scores, hashes and programs.
Native probe creation preserves an already matching executable. A changed source
or corrupted existing probe fails rather than replacing historical evidence.
All runner output paths refuse to overwrite a report; fresh output directories
permit independent reruns without replacing committed results.

```sh
uv pip install --python /tmp/docscan-ppocr-v6/venv/bin/python -r experiments/research_ocr/requirements.txt
# Existing pinned models/data and native text_v6 release dependencies are required.
/tmp/docscan-ppocr-v6/venv/bin/python -m unittest discover -s experiments/research_ocr
/tmp/docscan-ppocr-v6/venv/bin/python experiments/research_ocr/run.py --output-dir /tmp/ocr-new-python-results
/tmp/docscan-ppocr-v6/venv/bin/python experiments/research_ocr/build_native_probe.py
/tmp/docscan-ppocr-v6/venv/bin/python experiments/research_ocr/run_native.py --output-dir /tmp/ocr-new-native-results
/tmp/docscan-ppocr-v6/venv/bin/python experiments/research_ocr/check_regression.py --output /tmp/ocr-new-regression.json
```

The original result hashes refer to their executed runner revisions; subsequent
changes only harden artifact guards and offer independent output paths. Model
selection remains untrained. The best next integration experiment is the hybrid
recognizer with the unchanged tiny detector, followed by independent distorted
layouts and device tests. Its broader dictionary and larger weights require
explicit API/model provenance, lazy download, WASM parity, memory and phone
latency gates. No production promotion or SOTA claim follows from these small,
correlated development sets; incomplete invoice labels cannot measure full-page
hallucinations, customer verification, table semantics or reading order.

Final review also caught that fresh report paths still reused old raw-output
folders. Each mode and regression run now allocates an exclusive owner-private
folder under `DATA/runs`, records its receipt/path/hashes, and publishes reports
with exclusive creation. Interrupted or concurrent reruns cannot replace prior
raw predictions or reports. The full sixty-page baseline rerun in
`results/independent-rerun-audit.json` reproduces every scored row and summary
with a separate raw directory; original evidence remains intact.
