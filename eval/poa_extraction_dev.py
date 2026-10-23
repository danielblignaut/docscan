"""Repeat the October PoA extraction comparison on frozen, manifest-pinned DEV OCR.

No set/split option is provided. Only poa_dev manifest members are opened,
and only cache entries keyed to their frame hashes are decoded. The selected
OCR records must match the recorded digest. TEST is never loaded.

  /tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py --validate-only
  DOCSCAN_EXAMPLES=/path/to/reference/docscan/target/release/examples \\
    /tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py \\
    --source-revision=e5c9cc7 --out=/tmp/before.json
  /tmp/docscan-bench/venv/bin/python eval/poa_extraction_dev.py \\
    --source-revision=1c2bb4c --out=/tmp/after.json
  /tmp/docscan-bench/venv/bin/python bench/compare.py /tmp/before.json /tmp/after.json

Requires the existing frozen poa_ocr cache under BENCH_DATA (default
/tmp/docscan-bench), DEV files, the tagger model and the supplied poa_capture
binary. It does not generate data, rerun OCR, or measure latency.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))
from lib.common import DATA, bench_code_sha256, binary, manifest, manifest_root, safe_digest, sha256_json  # noqa: E402
from suites import poa  # noqa: E402

CACHE_KEY = "dc79fff5b208264102ee"
RECORDS_DIGEST = "xkvwzqkpvxjjvyffqwqkqqzyyqzkzvyxypjpvvvyzxkjzjvpqyqwxqzvwpypykxkpqykjxzpwwqjw"
SOURCE_REVISION = "e5c9cc75f8c27f1fdc6378073f326412e9de86d4"
ENTRY_KEY = re.compile(r'^\s*\[\s*"([a-f0-9]{64})"\s*,')


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_dev():
    m = manifest("poa_dev")
    if m["split"] != "dev" or m["root"] != "poa/dev":
        raise SystemExit("Refusing a manifest that is not the pinned PoA DEV set")
    root = manifest_root(m)
    members = {f["path"]: f for f in m["files"]}

    def pinned(relative: str) -> Path:
        # No directory traversal or unmanifested files, including extra JSONs
        # someone may have left beside the generated DEV captures.
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or relative not in members:
            raise SystemExit(f"Not a pinned DEV member: {relative}")
        target = root / relative
        if safe_digest(file_sha(target)) != members[relative]["sha256"]:
            raise SystemExit(f"DEV hash mismatch: {relative}")
        return target

    caps, truths, frame_paths = [], {}, {}
    for relative in sorted(members):
        if not (relative.startswith("frames/") and relative.endswith(".json")):
            continue
        cap = json.loads(pinned(relative).read_text())
        truths[cap["id"]] = json.loads(pinned(f"docs/{cap['id']}.json").read_text())
        for frame in cap["frames"]:
            path = pinned(f"frames/{Path(frame['image']).name}")
            frame["path"] = str(path)
            frame_paths[file_sha(path)] = str(path)
        caps.append(cap)
    if len(caps) != 200 or len(frame_paths) != 800:
        raise SystemExit("Expected exactly the original 200 DEV captures / 800 frames")

    cache = DATA / "cache" / "poa_ocr" / f"{CACHE_KEY}.jsonl"
    records = {}
    # Cache files can contain other splits. Inspect only the entry key first;
    # do not decode any image's OCR record unless its hash belongs to DEV.
    with cache.open() as source:
        for line in source:
            match = ENTRY_KEY.match(line)
            if match and match[1] in frame_paths:
                key, value = json.loads(line)
                records[key] = value
    if set(records) != set(frame_paths):
        raise SystemExit("Frozen OCR cache is incomplete; no new OCR will be generated")
    digest = safe_digest(sha256_json(sorted(records.items())))
    if digest != RECORDS_DIGEST:
        raise SystemExit("Frozen DEV OCR records differ from the comparison's input")
    pages = {frame_paths[key]: value for key, value in records.items()}
    return m, caps, truths, pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="Check DEV manifest and frozen OCR without running inference")
    parser.add_argument("--source-revision", help="Revision used to build DOCSCAN_EXAMPLES/poa_capture; recorded as a caller assertion")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.validate_only and (not args.out or not args.source_revision):
        parser.error("--out and --source-revision are required for inference")
    m, caps, truths, pages = load_frozen_dev()
    print(f"Validated {len(caps)} DEV captures and {len(pages)} frozen OCR frames", flush=True)
    if args.validate_only:
        return
    load_start = os.getloadavg()
    out = poa.capture_run(caps, truths, pages)
    meta = {
        "git_sha": args.source_revision,
        "source_revision_is_caller_assertion": True,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "args": {"suite": "poa", "split": "dev", "quick": False, "extraction_only": True},
        "git_dirty": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines(),
        "load_start": load_start,
        "binaries": {"poa_capture": safe_digest(file_sha(binary("poa_capture")))},
        "models": {"models/poa-tagger.onnx": safe_digest(file_sha(poa.TAGGER))},
        "bench_code_sha256": safe_digest(bench_code_sha256()),
        "manifests": {"poa_dev": {"tree_sha256": m["tree_sha256"], "split": "dev"}},
        "evaluation_scope": "Extraction and customer verification on identical frozen DEV OCR; no OCR, page-detection or latency rerun",
        "frozen_ocr": {"source_revision": SOURCE_REVISION, "cache_key": CACHE_KEY, "selected_records_sha256": RECORDS_DIGEST},
    }
    args.out.write_text(json.dumps({"meta": meta, "metrics": poa.score("dev", caps, truths, out)}, indent=1) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
