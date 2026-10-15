"""Fake-webcam clips of proof-of-address pages for Chrome's --use-file-for-fake-video-capture.

Reuses make_videos.make: the page starts out of frame and out of focus, slides
and rotates in, then holds still (sub-pixel hand tremor and sensor noise only)
for the last --hold seconds. Unlike the ID clips, the frame is portrait (a phone
held upright, 1080x1920 by default), the page is not rotated, and the held pose
is about 0.88 of the frame width with at most 6 deg of tilt.

For each --ids document this writes <outdir>/<id>.y4m (yuv420p) and <id>.json:
make_videos' timeline and per-frame corners, plus the absolute path of the
source truth and a copy of that truth (the synth set usually lives in /tmp).

Run: .venv/bin/python make_poa_videos.py [--ids poa_00003 poa_00005] [--synth /tmp/docscan-poa/synth]
     [--size 1080x1920] [--fps 15] [--seconds 6] [--hold 3.5] [--outdir video/poa]
Then: chrome --use-fake-device-for-media-stream --use-file-for-fake-video-capture=video/poa/<id>.y4m
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import make_videos

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", nargs="+", default=["poa_00003", "poa_00005"])
    ap.add_argument("--synth", default="/tmp/docscan-poa/synth")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--hold", type=float, default=3.5)
    ap.add_argument("--outdir", default=str(ROOT / "video" / "poa"))
    ap.add_argument("--seed", type=int, default=200)
    args = ap.parse_args()
    W, H = map(int, args.size.split("x"))
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    synth = Path(args.synth).resolve()
    for i, doc_id in enumerate(args.ids):
        truth_path = synth / f"{doc_id}.json"
        truth = json.loads(truth_path.read_text())
        meta = make_videos.make(doc_id, (W, H), args.seconds, args.hold, args.fps, seed=args.seed + i,
                                doc_path=synth / f"{doc_id}.png", source=str(truth_path), out_dir=out,
                                rotate_portrait=False, held_width=0.88, max_tilt=(6, 6, 4))
        meta.update({"id": doc_id, "layout": truth["layout"], "document_type": truth["document_type"],
                     "source_truth": truth})
        (out / f"{doc_id}.json").write_text(json.dumps(meta) + "\n")
        size_mb = (out / f"{doc_id}.y4m").stat().st_size / 1e6
        print(f"video: {out / doc_id}.y4m {W}x{H} {args.fps} fps {size_mb:.0f} MB "
              f"({truth['layout']}, {truth['fields']['document_date']}, held width {meta['final_pose_deg']['width_frac']:.2f})")


if __name__ == "__main__":
    main()
