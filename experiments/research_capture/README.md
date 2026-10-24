# Capture research prototypes (DEV only)

Scope and citations: [research report](../../docs/research-2026-capture.md).
These wrappers transform images and call an unchanged native scanner. They do
not implement a shipping scanner, change acceptance, train models, or access
TEST. Every corpus file is verified against its existing DEV manifest.

## Reproduce from a fresh private workspace

Use `/tmp/docscan-bench/venv/bin/python` (the existing benchmark environment).
The scripts intentionally refuse to overwrite a frozen trial. Preserve/archive
an existing `/tmp/docscan-research-capture` before a new reproduction; do not
silently replace its artifacts. The source revision is pinned in `prepare.py`.
Models must already exist in the repository's ignored `models/` directory.

```sh
python3 experiments/research_capture/prepare.py
PATH=/home/dan/.cargo/bin:$PATH \
CARGO_TARGET_DIR=/tmp/docscan-research-capture/target \
/home/dan/.cargo/bin/cargo build --locked --release --example scan -j2 \
  --manifest-path /tmp/docscan-research-capture/source/docscan/Cargo.toml
/tmp/docscan-bench/venv/bin/python experiments/research_capture/pin_build.py
/tmp/docscan-bench/venv/bin/python experiments/research_capture/run.py id
```

`prepare.py` snapshots committed source with `git archive`; it never changes a
branch or writes a shipping file. The preexisting native executable is preserved
as `bin/preexisting-scan`. The rebuilt example is copied to `bin/scan` by the
runner. Models are copied and hashed before/after inference, and the ID CLI must
confirm the exact model directory. All descendants of the scratch workspace
are created with owner-only permissions.

`run.py barcode` is retained as the **original unsuccessful harness attempt**.
It stopped at public DEV index 141: OpenCV cannot load a valid 100×1 WebP.
Its frozen configuration, completed raw records and failure log are preserved.
Use `run_barcode_v2.py barcode` for the complete experiment. This version only
adds a PIL RGB→BGR fallback when OpenCV fails; it does not change candidates,
scoring, truth, or successful image loads. Initialize its workspace after ID:

```sh
python3 - <<'PY'
from pathlib import Path
import shutil
root = Path('/tmp/docscan-research-capture')
work = root / 'barcode-v2'
work.mkdir(exist_ok=False)
shutil.copytree(root / 'bin', work / 'bin')
shutil.copytree(root / 'models', work / 'models')
shutil.copy2(root / 'snapshot.json', work / 'snapshot.json')
PY
/tmp/docscan-bench/venv/bin/python experiments/research_capture/run_barcode_v2.py barcode
/tmp/docscan-bench/venv/bin/python experiments/research_capture/run_id_round2.py
/tmp/docscan-bench/venv/bin/python experiments/research_capture/run_barcode_round2.py
```

Run the suites sequentially so there are at most two active frame workers.
The second ID round is a separately frozen automatic-crop padding ablation,
conditioned only on round-one DEV results. `run_id_round2.py` records the hash of
those source results. Neither runner is to be pointed at TEST or reserved data.

## Artifacts and interpretation

- `candidates.json`: initial hypotheses, exact parameters and promotion gates.
- `candidates-barcode-v2.json`: same barcode candidates with the loader correction.
- `candidates-id-round2.json`: two predeclared automatic-crop margin candidates.
- `candidates-barcode-round2.json`: format-scoped cached retries and a separately
  declared adapter normalization; no extra decoder inference.
- `run.py`, `run_barcode_v2.py`, `run_id_round2.py`: isolated experiment drivers;
  common scorers are imported from the pinned source snapshot without edits.
- `zxing_worker*.py`: optional ZXing-C++ 3.1.1 comparator, isolated per image.
- `test_protocol.py`: procedural tests of pin checks, freeze overwrite rejection,
  geometry fallback and timeout accounting; no dataset media read.
- `evidence/`: redacted results, every per-item outcome and reproducibility hashes.
  Raw outputs, images, truth and payload strings remain in private `/tmp`.

ID positive and negative denominators remain 12 and six. Barcode decodable-code
and frame denominators differ and are both retained. A retry union is tested on
every image; it is not selected using truth or restricted to known failures.
The timeout field means any attempted pass timed out, including a retry whose
other pass succeeded. There is no change to docscan's ID acceptance validator.
The separate decoder's output is a barcode candidate, never an ID acceptance.

The initial ZXing comparator intentionally exposes its default HRI output. It
can differ from the benchmark's payload representation (especially UPC-E).
Report that limitation explicitly: representation mismatch is not evidence of
a physically wrong barcode reading. The unchanged scorer still counts it as
an exact-payload failure; any adapter correction must be separately declared.

The primary half-scale and rotation experiments preserve all barcode baseline
reads, so per-code recall cannot fall, but **false decodes can increase**. Runtime
can also double. Recorded process wall times exclude parts of preprocessing and
are diagnostic only. Shipping promotion requires main-harness DEV checks,
labelled/ID compatibility and interleaved CPU/WASM timing under parent
coordination; this first track does not touch shared shipping modules.

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/research_capture -p test_protocol.py -v
```

`export_evidence.py` validates immutable receipts and exports only sanitized
records; it refuses an existing evidence directory. The local measured export
also records `build-and-decoder-pin.json` (compiler, command, package-file and
binary hashes) captured before the complete barcode run. `summarize.py` computes
paired changes from the redacted evidence. Barcode metric IDs are SHA-256 of the
unchanged scorer's item IDs; frame IDs start with the dataset name plus the
zero-based truth-row index. This preserves pairing without publishing payloads
(which the original precision metric includes in its IDs).

The separately normalized ZXing comparator uses only pinned importer's UPC
conversion and the Code39Extended name alias. Original default-HRI results stay
published. It is still a native comparator with residual HRI/ECI/GS1 semantics
to audit, not an end-to-end shipping replacement benchmark.

Final verification of retained local trials:

```sh
/tmp/docscan-bench/venv/bin/python experiments/research_capture/pin_build.py --check
/tmp/docscan-bench/venv/bin/python experiments/research_capture/verify_evidence.py
```

On a fresh reproduction, run `export_evidence.py` only into a fresh owned
`evidence/` directory, then `summarize.py`; retain the previous export separately.
The two initial freeze receipts and aborted-attempt export refer to the original
failed `run.py barcode` run. Reproducing only the corrected protocol need not
recreate that known harness failure; retain its historical evidence and report
the new run separately rather than replacing it.
