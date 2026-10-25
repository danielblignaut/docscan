"""Immutable, owner-only snapshot for the label-robustness experiment (DEV only).

    python3 experiments/label_robustness/prepare.py SNAP [--patched] [--probe=diag.rs]

Creates $LABEL_ROBUSTNESS_DIR/SNAP (default /tmp/docscan-label-robustness;
refuses if it exists):

- `src/docscan`: the committed crate at HEAD (`git archive`: uncommitted
  edits in the worktree, including other agents', never reach the build),
  without the prebuilt `pkg*` directories;
- `probe.rs` (or `--probe=FILE` from this directory: `diag.rs` for the
  pre-freeze diagnosis) copied in as `docscan/examples/label_robustness_probe.rs`;
- `--patched`: `text_v6-candidates.patch` applied to the snapshot's
  `src/text_v6.rs` only (adds the candidate read entry points; the shipped
  `read_native` path is untouched, which the `parity` phase checks);
- `models/`: read-only copies of the models the probe loads;
- `receipt.json`: HEAD, sha256 of every snapshot file, copied file and model.

It never edits the shared crate, a shared example, the manifest or lib.rs.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("LABEL_ROBUSTNESS_DIR", "/tmp/docscan-label-robustness"))
MODELS = ["text-detection.rten", "text-recognition.rten", "ppocr-v6-tiny-det.onnx", "ppocr-v6-tiny-rec.onnx"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    patched = "--patched" in sys.argv
    probe_src = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--probe=")), "probe.rs")
    if len(args) != 1:
        raise SystemExit(__doc__)
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    snap = ROOT / args[0]
    if snap.exists():
        raise SystemExit(f"{snap} exists: snapshots are immutable")
    src = snap / "src"
    src.mkdir(parents=True)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "HEAD", "docscan"], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    for d in ("pkg", "pkg-threads"):
        shutil.rmtree(src / "docscan" / d, ignore_errors=True)
    receipt: dict = {"head": head, "patched": patched, "probe_source": probe_src, "copied": {}, "models": {}, "snapshot": {}}
    probe = src / "docscan" / "examples" / "label_robustness_probe.rs"
    shutil.copyfile(HERE / probe_src, probe)
    receipt["copied"]["docscan/examples/label_robustness_probe.rs"] = sha256(probe)
    if patched:
        patch = HERE / "text_v6-candidates.patch"
        subprocess.run(["patch", "-d", str(src), "-p1", "--forward", "-i", str(patch)], check=True, capture_output=True)
        receipt["copied"]["text_v6-candidates.patch"] = sha256(patch)
    (snap / "models").mkdir()
    for m in MODELS:
        dst = snap / "models" / m
        shutil.copyfile(REPO / "models" / m, dst)
        dst.chmod(0o400)
        receipt["models"][m] = sha256(dst)
    for p in sorted((src / "docscan").rglob("*")):
        if p.is_file():
            receipt["snapshot"][str(p.relative_to(src))] = sha256(p)
    (snap / "receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"prepared {snap} at {head[:12]}: {len(receipt['snapshot'])} files, patched={patched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
