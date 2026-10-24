# Identity science: frozen stroke-consistency experiment

Research only; one candidate, no production changes. Read
[the report](../../docs/research-identity-science-2026.md) for primary sources,
artifact licenses, complete outcomes, and why the candidate was rejected.

The experiment compares raw paired-glyph RMS difference with illumination-plane
removal and ink-depth normalization at the same predeclared threshold, 0.12.
Both use the same contrast abstention rule. This is an independently implemented
synthetic falsification benchmark, not the application scanner, an OCR engine,
a handwriting identification system, or an original-document authenticity test.

All digits are generated from source-authored polylines; no third-party font,
portrait, handwriting, document, model, or biometric cache is loaded. The source
is covered by the repository's MIT license. The generated specimens are authored
synthetic research artifacts, kept private rather than published as a separately
licensed dataset. No trained weights exist. NumPy is BSD-3-Clause and Pillow uses
the HPND license; neither library supplies the glyph artwork.

`protocol.json` and `stroke_consistency.py` were frozen before generation.
`prepare` then writes every image, group assignment, intervention label and hash
to a complete private manifest before inference. There are 48 TRAIN and 48 DEV
specimens, each with 14 paired-field conditions: 672 pairs per split. All variants
of a specimen stay together; each simulated device belongs to one split only.
No model is fitted on TRAIN and neither threshold is tuned. Shared skeletons mean
this is not a holdout of font families or real writers.

Completed run uses Python 3.12.14, NumPy 2.5.4, Pillow 12.3.0, from the existing
benchmark virtualenv. Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  /tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/research_identity_science -v

# Safe read-only recheck of the retained, completed experiment:
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  /tmp/docscan-bench/venv/bin/python experiments/research_identity_science/audit.py
```

Original execution commands (refuse to overwrite existing data/results):

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  /tmp/docscan-bench/venv/bin/python experiments/research_identity_science/stroke_consistency.py prepare
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  /tmp/docscan-bench/venv/bin/python experiments/research_identity_science/stroke_consistency.py run
```

For an exact reproducibility rerun, pass a new outside-repo `--private-root` to
both commands and an unused private `--output` to `run`. This is not permission
to tune and overwrite v1. The manifest includes a timestamp, so compare frozen
row/image hashes and predictions rather than expecting the entire manifest's
hash to survive a new preparation time. The audit addresses the retained v1 run.

Private artifacts: `/tmp/docscan-identity-science-v1/`, directory mode 0700 and
files 0600. It contains 2,688 generated image crops, the full manifest, per-pair
predictions, source snapshots, and separate design/data/inference receipts.
Nothing in that directory belongs in git. The runner exclusively creates the
directory and report, checks every input hash before/after scoring, retains
every failure as a failure, and counts abstentions in the original denominators.
A preflight hash mismatch aborts without publishing partial metrics.

`aggregate-v1.json` contains only aggregate counts and provenance hashes.
`audit.py` independently reconstructs both scores using a pseudoinverse rather
than the runner's least-squares function, verifies decisions and all 30 aggregate
cells, disjoint groups/devices, permissions, and freeze ordering. Six unit tests
cover affine illumination, nulls, invalid geometry/nonfinite input, and denominator
and regression accounting. Both checks passed.

`source-notices-lock.json` pins author README/license texts, with notice bodies
outside git. The retained OFIQ `master` API failure was followed by successful
default-branch resolution; neither attempt acquired model files or data samples.

DEV: correct **329→356/672**, but **69 regressions**, **26 new benign false flags**,
and **43 newly clear attacks**. There are **48 abstentions per arm**, zero runtime
errors, and **96 recoveries**. TRAIN is also retained. **Gate failed: do not ship.**
