# Native matrix retry experiment (DEV only)

This continues `experiments/research_capture`'s output-filtered proposal with
actual matrix-only native calls. Read `protocol.json` for the two variants,
predeclared timing selection, hard pass limit, whole-candidate timeout, and gates.
The existing `read_all` and shared scorers are unchanged.

Use the existing benchmark venv and already-materialised DEV data. `prepare.py`
creates an owner-only `/tmp/docscan-matrix-retry-v1`, refuses to overwrite the
candidate snapshot, and copies only the owned `barcode.rs` over committed source.
It creates the private example from `probe.rs`; it never edits a shared example,
Cargo manifest, library entry point, or benchmark scorer. Preserve the entire
existing trial before reproducing; do not replace its frozen results.

```sh
python3 experiments/matrix_retry/prepare.py
CARGO_TARGET_DIR=/tmp/docscan-matrix-retry-v1/target \
  /home/dan/.cargo/bin/cargo build --locked --release --example matrix_probe -j2 \
  --manifest-path /tmp/docscan-matrix-retry-v1/before/docscan/Cargo.toml
mkdir -p /tmp/docscan-matrix-retry-v1/bin
cp /tmp/docscan-matrix-retry-v1/target/release/examples/matrix_probe /tmp/docscan-matrix-retry-v1/bin/before
CARGO_TARGET_DIR=/tmp/docscan-matrix-retry-v1/target \
  /home/dan/.cargo/bin/cargo build --locked --release --example matrix_probe -j2 \
  --manifest-path /tmp/docscan-matrix-retry-v1/after/docscan/Cargo.toml
cp /tmp/docscan-matrix-retry-v1/target/release/examples/matrix_probe /tmp/docscan-matrix-retry-v1/bin/after
CARGO_TARGET_DIR=/tmp/docscan-matrix-retry-v1/target \
  /home/dan/.cargo/bin/cargo test --locked --release --lib barcode::tests -j2 \
  --manifest-path /tmp/docscan-matrix-retry-v1/after/docscan/Cargo.toml > /tmp/docscan-matrix-retry-v1/tests-final.log 2>&1
cat /tmp/docscan-matrix-retry-v1/tests-final.log
/tmp/docscan-bench/venv/bin/python -m unittest discover -s experiments/matrix_retry -p test_protocol.py -v
/tmp/docscan-bench/venv/bin/python experiments/matrix_retry/run.py accuracy
/tmp/docscan-bench/venv/bin/python experiments/matrix_retry/run.py latency
/tmp/docscan-bench/venv/bin/python experiments/matrix_retry/export.py
```

Run build, accuracy, and timing phases sequentially. Accuracy uses two workers;
timing uses one fixed CPU and four alternating-order repeats. The probe uses the
same native image decoder and RGBA-to-luminance conversion as `examples/scan`, at
original size, without loading unused OCR models. Internal milliseconds include
all decoding and retry transforms; wall milliseconds include process startup,
image loading and conversion. This is a focused native barcode comparison,
not a full main-harness, labelled/ID, browser or WASM shipping verdict.

The 30-second timeout applies once to the entire candidate. A killed candidate
is read-nothing even if its baseline stage would have decoded something. Failed
timing calls remain in the denominator and receive the full budget. Pass counts
refer to `read_all` invocations, each of which includes existing detector passes.
Counts are inferred from the separately measured deterministic baseline; for a
failed process they are upper bounds. The native synchronous function has no
wall-clock cancellation mechanism; bounded retry count is not a real-time bound.

`accuracy.json` and `latency.json` contain aggregates and opaque frame IDs. All
raw payloads, bytes, points, source filenames and inputs stay in private `/tmp`.
The unchanged scorer's precision IDs contain payload fragments; the exporter
hashes every metric ID. No TEST or reserved media/truth is read or listed.

The measured run retained its initial analysis and runner under private `/tmp`.
A post-run correction decodes the scorer's compact `"0"`/`"1"` outcome strings
before listing gained/lost IDs. Inference, score values, confidence intervals,
and latency did not change. `evidence/analysis-revision.json` records this
correction; the current runner includes its regression test. The frozen receipt
identifies the archived measured runner, and snapshots in `experiment-source/`
preserve it separately from subsequent analysis code.
