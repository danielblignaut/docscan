# Document originality: pixel API and rejected periodicity shortcut

See [the scope and primary-source survey](../../docs/document-originality.md).
The Rust module reports unknown copy status and descriptive colour/transparency
statistics. The experiment rejects a generic chromatic-periodicity warning:
12/12 moiré surrogates and 12/12 benign security patterns cross the frozen
threshold; 24 other benign controls do not. This is **48 synthetic DEV
counterexamples/controls**, not a benchmark of real copies or genuine IDs.

No external document media, TEST/reserved data, personal IDs, pretrained weights
or GPU inference are used. Fixtures are original procedural graphics, with no
names or portraits. `source-notices.json` records primary publisher notice
hashes and metadata for possible future research data; no dataset was imported.

## Reproduce without changing the application

From the repository root, with Rust on PATH:

```sh
cargo test --locked --manifest-path experiments/document_originality/Cargo.toml \
  --target-dir /tmp/docscan-document-evidence-target -j2
```

The isolated crate uses `#[path]` to compile the exact
`docscan/src/document_evidence.rs`; the parent can add it to the main crate
without copying code. The standalone Cargo lock pins only its serde test
dependencies. No app manifest, generated contract or library wiring is changed.

Python requires NumPy; the run records its version in the freeze receipt. The
existing benchmark environment used here already has it installed:

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/document_originality -p 'test_*.py'
/tmp/docscan-bench/venv/bin/python experiments/document_originality/probe.py \
  --output /tmp/document-originality-reproduction.json
```

Choose a fresh output path for each run. Both report and freeze receipt are
created exclusively; interrupted runs retain an empty/incomplete report. The
historical report in `evidence/` must not be overwritten. Every fixture's pixel
hash, cohort, raw concentration/std and warning bit is retained. Protocol/source
hashes are checked after inference; tests run after the recorded measurement.

The candidate is independently written. It does **not** implement the
boundary-aware Fast Hough detector in the cited paper, nor does it reproduce
MIDV-Holo/DynAttack. It uses global chroma Fourier energy solely to test whether
a much cheaper shortcut is specific enough. No threshold tuning follows the
negative result. Runtime Rust never calls this candidate.

Seven Rust unit tests, four Python tests, Clippy with warnings denied, rustfmt,
an isolated WASM compile check and the complete 48-row evidence audit passed.
Work is bounded by at most
4096 sampled pixels in the production helper; no device-latency, WASM-parity,
real-copy accuracy or calibration claim is made.
