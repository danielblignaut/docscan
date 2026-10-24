# Frozen optics DEV experiment

Research and decisions: [research-optics-2026.md](../../docs/research-optics-2026.md).
No shipping source, referee, threshold or weight changes; no Rust build.

Requires the already authorized public DEV artifacts, original pinned tiny OCR
probe and capture baseline described in the report. The runner never fetches
data or prepares any dataset. It fails on changed provenance rather than silently
rebuilding. All new media/raw results/snapshots stay owner-private outside git.

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-ppocr-v6/venv/bin/python -m unittest discover -s experiments/research_optics -p 'test_*.py'
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-ppocr-v6/venv/bin/python experiments/research_optics/run.py --output /tmp/optics-new-results.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-ppocr-v6/venv/bin/python experiments/research_optics/timing.py --results /tmp/optics-new-results.json --output /tmp/optics-new-timing.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-ppocr-v6/venv/bin/python experiments/research_optics/audit.py --results /tmp/optics-new-results.json --output /tmp/optics-new-audit.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/docscan-ppocr-v6/venv/bin/python experiments/research_optics/global_review.py --results /tmp/optics-new-results.json --output /tmp/optics-new-global-review.json
```

Every accuracy run allocates a fresh private directory and freezes all inputs,
assets, source hashes and choices before inference. Reports refuse overwrite.
Timing must follow accuracy, without another accuracy workload running; it pins
one allowed CPU and alternates adjacent baseline/candidate order for three repeats.
It includes preprocessing, PNG save and process startup but excludes input loading
equally. Calibration brackets and failures remain visible. It is not the official
main bench latency gate and does not measure acquisition, browser or mobile cost.

`audit.py` is read-only with respect to evidence. It verifies the fixed 900
document-arm rows, 54 camera-arm rows and 18 non-text rows, including no-op arms
that share the same content-hashed native result. Unique prediction reuse is only
within the current frozen run and engine, never from a failed historical cache.
There is no fallback from a failed selected frame or any output-based selection.

The parent's requested post-run global-only assessment is in `global-review-v1.json`:
all 60 dark-page paired counts, exact-region regressions and whole-statement/layout
bootstrap intervals. It changes no inference or frozen threshold. The sole narrow
handoff is `global-contract-v1.json`, an experimental explicit opt-in ordinary-OCR
utility for independent native/browser evaluation. It is not a default or automatic
ID-acceptance recommendation. Local illumination and burst selection are rejected.

Dependencies are the existing research environment: Python 3.12, NumPy, Pillow,
OpenCV headless and PDFium. Exact installed versions accompany the freeze/results.
No new dependencies are installed. The independent arithmetic and procedural
degradations introduce no third-party code or weights; data/weight provenance
remains separate from code licensing.
