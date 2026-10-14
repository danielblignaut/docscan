"""Check the corpus: decode every expected barcode, validate MRZ and SA ID check digits.

Decodes with zxing-cpp (the same engine family the WASM spike can use), on
synth/*.png and camera/*.jpg, and on the last frame of every video/*.y4m when
--videos is given. Prints per-image results and a decode-rate summary, and
writes verify_report.json.

Run: .venv/bin/python verify.py [--videos]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import zxingcpp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth import sa_id_valid, validate_td3  # noqa: E402

ROOT = Path(__file__).resolve().parent

ZX_NAMES = {
    "QR Code": "QRCode", "Code 128": "Code128", "EAN-13": "EAN13", "Data Matrix": "DataMatrix",
    "PDF417": "PDF417", "Code 39": "Code39",
}


def decode(img: np.ndarray) -> set[tuple[str, str]]:
    found = zxingcpp.read_barcodes(img, try_rotate=True, try_downscale=True, try_invert=False)
    return {(ZX_NAMES.get(str(r.format), str(r.format)), r.text) for r in found if r.valid}


def expected(truth: dict) -> set[tuple[str, str]]:
    return {(b["format"], b["text"]) for b in truth.get("barcodes", [])}


def check_truth(truth: dict) -> list[str]:
    errs = []
    f = truth.get("fields", {})
    if "identity_number" in f and not sa_id_valid(f["identity_number"]):
        errs.append(f"bad SA ID Luhn {f['identity_number']}")
    if "mrz" in truth:
        res = validate_td3(truth["mrz"])
        errs += [f"MRZ check digit {k} invalid" for k, ok in res.items() if not ok]
        if any(len(line) != 44 for line in truth["mrz"]):
            errs.append("MRZ line not 44 chars")
        try:  # independent second opinion: the `mrz` package's TD3 checker
            from mrz.checker.td3 import TD3CodeChecker
            if not TD3CodeChecker("\n".join(truth["mrz"])):
                errs.append("mrz package rejects the MRZ")
        except ImportError:
            pass
    if "identity_number" in f:  # independent second opinion: the Wikipedia recipe
        n = f["identity_number"]
        odd = sum(int(n[i]) for i in range(0, 12, 2))
        even = sum(int(c) for c in str(int(n[1:12:2]) * 2))
        if (10 - (odd + even) % 10) % 10 != int(n[12]):
            errs.append("Wikipedia recipe disagrees on the check digit")
    return errs


def last_frame(path: Path) -> np.ndarray:
    head = path.open("rb").readline().decode()
    w = int(next(t[1:] for t in head.split() if t.startswith("W")))
    h = int(next(t[1:] for t in head.split() if t.startswith("H")))
    frame_bytes = w * h * 3 // 2
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(size - frame_bytes)  # the last frame's planes are the file's tail
        yuv = np.frombuffer(fh.read(frame_bytes), np.uint8).reshape(h * 3 // 2, w)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", action="store_true")
    args = ap.parse_args()
    report: dict = {"truth_checks": {}, "synth": {}, "camera": {}, "video": {}}
    truths = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / "synth").glob("*.json"))}

    print("== ground-truth check digits")
    for name, t in truths.items():
        errs = check_truth(t)
        report["truth_checks"][name] = errs or "ok"
        print(f"  {name:22s} {'OK' if not errs else errs}")

    def run(group: str, image: Path, truth: dict, extra: str = "", corners=None) -> tuple[int, int, int]:
        """Decode the raw image; with corners, also decode the image rectified to the document."""
        img = cv2.imread(str(image))
        want = expected(truth)
        got = decode(img)
        hit = want & got
        rect_hit: set = set()
        if corners is not None:
            W, H = truth["size"]
            M = cv2.getPerspectiveTransform(np.array(corners, np.float32),
                                            np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32))
            rect_hit = want & decode(cv2.warpPerspective(img, M, (W, H)))
        union = hit | rect_hit
        report[group][image.name] = {"expected": len(want), "decoded_raw": len(hit), "decoded_rectified": len(rect_hit),
                                     "missing_raw": sorted(f for f, _ in want - got), "extra_raw": sorted(f for f, _ in got - want)}
        if want:
            rect = f" rectified {len(rect_hit)}/{len(want)}" if corners is not None else ""
            print(f"  {image.name:40s} raw {len(hit)}/{len(want)}{rect} {extra}" + (f"  raw-missing={sorted(f for f, _ in want - got)}" if want - got else ""))
        return len(hit), len(want), len(union)

    print("== synth (clean)")
    tot = [0, 0]
    for name, t in truths.items():
        h, n, _ = run("synth", ROOT / t["image"], t)
        tot[0] += h; tot[1] += n
    synth_rate = tot[:]

    print("== camera")
    good, bad, good_r, bad_r = [0, 0], [0, 0], [0, 0], [0, 0]
    for meta_p in sorted((ROOT / "camera").glob("*.json")):
        meta = json.loads(meta_p.read_text())
        t = json.loads((ROOT / meta["source"]).read_text())
        # Rectify only frames whose corners are all inside the image (not the cropped ones).
        fw, fh = meta["frame"]
        c = meta["corners_tl_tr_br_bl"]
        inside = all(0 <= x < fw and 0 <= y < fh for x, y in c)
        h, n, u = run("camera", ROOT / meta["image"], t, f"[{meta['expect']}]", corners=c if inside else None)
        bucket, rb = (good, good_r) if meta["expect"] == "good" else (bad, bad_r)
        bucket[0] += h; bucket[1] += n
        rb[0] += u; rb[1] += n

    vid, vid_r = [0, 0], [0, 0]
    if args.videos:
        print("== video (last frame)")
        for vm in sorted((ROOT / "video").glob("*.json")) + sorted((ROOT / "video" / "hd").glob("*.json")):
            meta = json.loads(vm.read_text())
            t = json.loads((ROOT / meta["source"]).read_text())
            y4m = ROOT / meta["video"]
            frame = last_frame(y4m)
            out = y4m.parent / f"{y4m.stem}.lastframe.png"
            cv2.imwrite(str(out), frame)
            corners = meta["per_frame"][-1]["corners_tl_tr_br_bl"]
            if meta.get("document_rotated_90"):
                W, H = t["size"]
                t = {**t, "size": [H, W]}
            h, n, u = run("video", out, t, f"[{meta['size'][0]}x{meta['size'][1]}]", corners=corners)
            vid[0] += h; vid[1] += n
            vid_r[0] += u; vid_r[1] += n

    def pct(x: list[int]) -> str:
        return f"{x[0]}/{x[1]} ({100 * x[0] / x[1]:.0f}%)" if x[1] else "n/a"

    summary = {"synth": pct(synth_rate), "camera_good_raw": pct(good), "camera_good_raw_or_rectified": pct(good_r),
               "camera_bad_raw": pct(bad), "camera_bad_raw_or_rectified": pct(bad_r), "video_last_frame_raw": pct(vid), "video_last_frame_raw_or_rectified": pct(vid_r)}
    report["summary"] = summary
    print("== summary (barcodes decoded / expected)")
    for k, v in summary.items():
        print(f"  {k:30s} {v}")
    (ROOT / "verify_report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
