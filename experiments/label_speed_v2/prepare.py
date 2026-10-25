"""Prepares an immutable, owner-only snapshot for the label-speed experiment (DEV only).

    python3 experiments/label_speed_v2/prepare.py SNAP

Creates /tmp/docscan-label-speed-v2/SNAP (refuses if it exists):

- `src/docscan`: the committed crate at HEAD (`git archive`, so uncommitted
  edits in the worktree, including other agents', never reach the build),
  without the prebuilt `pkg*` directories;
- the two files this experiment owns, copied in: `docscan/src/label_speed.rs`
  (not declared in lib.rs; the probe includes it by path) and `probe.rs` as
  `docscan/examples/label_speed_probe.rs`; optionally
  `lib-integration.patch` applied to the snapshot's lib.rs (`--patched`), for
  the private wasm build;
- `models/`: read-only copies of the models the probe loads;
- `receipt.json`: HEAD, sha256 of every snapshot file, copied file and model.

It never edits the shared crate, a shared example, the manifest or lib.rs.
Binaries are frozen afterwards with `run.py freeze SNAP`.
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
ROOT = Path(os.environ.get("LABEL_SPEED_DIR", "/tmp/docscan-label-speed-v2"))
OWNED = {"docscan/src/label_speed.rs": "docscan/src/label_speed.rs",
         "experiments/label_speed_v2/probe.rs": "docscan/examples/label_speed_probe.rs"}
MODELS = ["text-detection.rten", "text-recognition.rten", "text-detection-page.onnx", "ppocr-v6-tiny-det.onnx", "ppocr-v6-tiny-rec.onnx"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    patched = "--patched" in sys.argv
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
    receipt: dict = {"head": head, "patched": patched, "copied": {}, "models": {}, "snapshot": {}}
    for rel_from, rel_to in OWNED.items():
        dst = src / rel_to
        shutil.copyfile(REPO / rel_from, dst)
        receipt["copied"][rel_to] = sha256(dst)
    if patched:
        patch = HERE / "lib-integration.patch"
        subprocess.run(["patch", "-d", str(src), "-p1", "--forward", "-i", str(patch)], check=True, capture_output=True)
        receipt["copied"]["lib-integration.patch"] = sha256(patch)
        api = src / "docscan" / "examples" / "label_speed_api.rs"
        shutil.copyfile(HERE / "api_check.rs", api)
        receipt["copied"]["docscan/examples/label_speed_api.rs"] = sha256(api)
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
