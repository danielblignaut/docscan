"""Prepares the private, owner-only barcode-latency experiment (DEV only).

Snapshots the committed `docscan` crate at HEAD into
/tmp/docscan-barcode-latency-v1/src (git archive, so concurrent edits in the
worktree cannot leak into the build), then copies in the two files this
experiment owns: `docscan/src/label_regions.rs` (not declared in lib.rs; the
probe includes it by path) and `probe.rs` as `examples/latency_probe.rs`.
Writes a sha256 receipt of everything it copied and of the models. It never
edits the shared crate, a shared example, the manifest or lib.rs.

    python3 experiments/barcode_latency/prepare.py
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
EXP = Path(os.environ.get("BARCODE_LATENCY_DIR", "/tmp/docscan-barcode-latency-v1"))
OWNED = {"docscan/src/label_regions.rs": "docscan/src/label_regions.rs",
         "experiments/barcode_latency/probe.rs": "docscan/examples/latency_probe.rs"}
MODELS = ["text-detection.rten", "text-recognition.rten"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    os.umask(0o077)
    src = EXP / "src"
    if not src.exists():
        EXP.mkdir(mode=0o700, parents=True, exist_ok=True)
        src.mkdir()
        archive = subprocess.run(["git", "-C", str(REPO), "archive", "HEAD", "docscan"], check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
        for d in ("pkg", "pkg-threads"):
            shutil.rmtree(src / "docscan" / d, ignore_errors=True)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    receipt = {"head": head, "copied": {}, "models": {}, "snapshot": {}}
    for rel_from, rel_to in OWNED.items():
        dst = src / rel_to
        shutil.copyfile(REPO / rel_from, dst)
        receipt["copied"][rel_to] = sha256(dst)
    for m in MODELS:
        receipt["models"][m] = sha256(REPO / "models" / m)
    for p in sorted((src / "docscan").rglob("*")):
        if p.is_file():
            receipt["snapshot"][str(p.relative_to(src))] = sha256(p)
    (EXP / "source-receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"prepared {EXP} at {head[:12]}: {len(receipt['snapshot'])} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
