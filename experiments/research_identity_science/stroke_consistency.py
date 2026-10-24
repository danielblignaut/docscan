"""One frozen, synthetic-only repeated-number forensic falsification experiment.

prepare writes the entire split and byte manifest before either arm is evaluated.
run verifies its frozen source/config, scores every row, then exclusively writes
private per-item and public aggregate outputs. No external images/fonts/models.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform

import numpy as np
import PIL
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
DEFAULT_PRIVATE = Path("/tmp/docscan-identity-science-v1")
# Independently authored polyline skeletons, no font files or sampled handwriting.
DIGITS = [
    [[(9, 5), (21, 5), (25, 10), (25, 37), (21, 42), (9, 42), (5, 37), (5, 10), (9, 5)]],
    [[(9, 13), (16, 5), (16, 42)], [(8, 42), (24, 42)]],
    [[(5, 11), (10, 5), (21, 5), (26, 12), (24, 19), (6, 41), (27, 41)]],
    [[(5, 6), (25, 6), (16, 22), (24, 25), (26, 34), (21, 41), (7, 41), (4, 37)]],
    [[(22, 43), (22, 5), (4, 30), (29, 30)]],
    [[(26, 5), (7, 5), (6, 23), (21, 23), (26, 29), (26, 36), (21, 42), (6, 42)]],
    [[(24, 5), (13, 5), (6, 15), (5, 34), (10, 42), (22, 42), (27, 34), (25, 25), (7, 25)]],
    [[(4, 6), (27, 6), (12, 43)]],
    [[(10, 5), (22, 5), (26, 12), (22, 20), (8, 27), (5, 34), (10, 42), (22, 42), (27, 34), (22, 26), (8, 19), (5, 12), (10, 5)]],
    [[(25, 24), (8, 24), (5, 17), (6, 10), (11, 5), (22, 5), (27, 12), (26, 32), (20, 42), (7, 42)]]
]
CELL_W, CELL_H, N = 40, 56, 10


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, obj):
    with path.open("x") as handle:
        json.dump(obj, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def now():
    return datetime.now(timezone.utc).isoformat()


def render(values, width, slant, ink=30, override=None):
    scale = 3
    image = Image.new("L", (CELL_W * N * scale, CELL_H * scale), 242)
    draw = ImageDraw.Draw(image)
    for index, digit in enumerate(values):
        w, s, color = width, slant, ink
        if override and index == override[0]:
            w, s, color = override[1:]
        for stroke in DIGITS[digit]:
            pts = [((index * CELL_W + x + 4 + s * (25 - y)) * scale,
                    (y + 4) * scale) for x, y in stroke]
            draw.line(pts, fill=color, width=max(1, round(w * scale)), joint="curve")
    return image.resize((CELL_W * N, CELL_H), Image.Resampling.LANCZOS)


def photo(image, profile, seed, condition="clean"):
    arr = np.asarray(image, dtype=float)
    if condition == "exposure":
        arr = arr * 0.61 + 7
    elif condition in ("shadow", "digit_change_shadow"):
        arr *= np.linspace(0.45, 0.95, arr.shape[1])[None, :]
    elif condition == "low_contrast":
        arr = 215 + (arr - 242) * 0.06
    image = Image.fromarray(np.uint8(np.clip(np.rint(arr), 0, 255)))
    blur = profile["blur"] + (0.9 if condition == "blur" else 0)
    image = image.filter(ImageFilter.GaussianBlur(blur))
    arr = np.asarray(image, dtype=float)
    arr += np.random.default_rng(seed).normal(0, profile["noise"], arr.shape)
    image = Image.fromarray(np.uint8(np.clip(np.rint(arr), 0, 255)))
    quality = 35 if condition == "jpeg" else profile["jpeg"]
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("L")


def source_hashes():
    return {name: digest((HERE / name).read_bytes()) for name in
            ("protocol.json", "stroke_consistency.py")}


def prepare(root: Path):
    # os.umask is set before any artifact creation, including snapshot/config.
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    cfg = read_json(HERE / "protocol.json")
    hashes = source_hashes()
    for name in hashes:
        (root / name).write_bytes((HERE / name).read_bytes())
    write_json(root / "design-freeze.json", {
        "at": now(), "source": hashes, "config": cfg,
        "python": platform.python_version(), "numpy": np.__version__, "pillow": PIL.__version__,
    })
    assert not set(cfg["train_devices"]) & set(cfg["dev_devices"])
    rows = []
    devices = sorted(cfg["train_devices"] + cfg["dev_devices"])
    for di, device in enumerate(devices):
        split = "TRAIN" if device in cfg["train_devices"] else "DEV"
        # Profile IDs are disjoint. Parameters sample overlapping nuisance ranges,
        # avoiding a class/split shortcut. These are simulated, not physical devices.
        rng = np.random.default_rng(cfg["seed"] + di * 1000)
        profile = {"blur": float(rng.uniform(0.05, 0.35)),
                   "noise": float(rng.uniform(0.3, 1.8)), "jpeg": int(rng.integers(70, 96))}
        for si in range(cfg["groups_per_device"]):
            group = f"{device}-{si:02d}"
            values = rng.integers(0, 10, N).tolist()
            width, slant = float(rng.uniform(1.8, 3.0)), float(rng.uniform(-0.10, 0.10))
            index = int(rng.integers(N))
            base = render(values, width, slant)
            for ci, condition in enumerate(cfg["benign"] + cfg["attacks"]):
                left, right = base, base
                changed = values.copy()
                changed[index] = (changed[index] + 1) % 10
                if condition in ("digit_change", "digit_change_shadow"):
                    right = render(changed, width, slant)
                elif condition == "local_weight":
                    right = render(values, width, slant, override=(index, width * 1.8, slant, 30))
                elif condition == "local_ink":
                    right = render(values, width, slant, override=(index, width, slant, 155))
                elif condition == "coherent_replacement":
                    left = right = render(changed, width, slant)
                elif condition == "legitimate_weight":
                    right = render(values, width * 1.55, slant)
                elif condition == "legitimate_calligraphy":
                    right = render(values, width, slant + 0.22)
                # identical_reprint is intentionally observationally identical
                # to a clean capture; no claimed physical print simulator.
                seed = cfg["seed"] + di * 100000 + si * 100 + ci
                left = photo(left, profile, seed)
                right = photo(right, profile, seed + 999999, condition)
                row = {"id": f"{group}-{condition}", "group": group, "device": device,
                       "split": split, "condition": condition, "attack": condition in cfg["attacks"],
                       "values": values, "profile": profile, "files": []}
                for side, im in (("left", left), ("right", right)):
                    path = root / f"{row['id']}-{side}.png"
                    im.save(path)
                    row["files"].append({"name": path.name, "sha256": digest(path.read_bytes())})
                rows.append(row)
    manifest = {"at": now(), "rows": rows, "source": hashes}
    write_json(root / "manifest.json", manifest)
    write_json(root / "data-freeze.json", {
        "at": now(), "manifest_sha256": digest((root / "manifest.json").read_bytes()),
        "source": hashes, "counts": dict(Counter(r["split"] for r in rows)),
        "status": "all data and labels frozen before inference"
    })
    print(json.dumps({"prepared": str(root), "counts": dict(Counter(r["split"] for r in rows))}))


def normalize(cell):
    """Estimate paper's illumination plane from the known empty glyph border."""
    y, x = np.indices(cell.shape)
    border = (x < 2) | (x >= CELL_W - 2) | (y < 2) | (y >= CELL_H - 2)
    design = np.stack([np.ones(cell.size), x.ravel(), y.ravel()], axis=1)
    coef = np.linalg.lstsq(design[border.ravel()], cell[border], rcond=None)[0]
    paper = (design @ coef).reshape(cell.shape)
    residual = paper - cell
    depth = float(np.percentile(residual, 95))
    if not np.isfinite(depth) or depth <= 0:
        raise ValueError("invalid normalization contrast")
    return np.clip(residual / depth, 0, 1), depth


def predict(left, right, cfg, candidate):
    if left.shape != (CELL_H, CELL_W * N) or right.shape != left.shape:
        raise ValueError("invalid paired-crop geometry")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("nonfinite pixels")
    scores = []
    for i in range(N):
        a, b = left[:, i * CELL_W:(i + 1) * CELL_W], right[:, i * CELL_W:(i + 1) * CELL_W]
        na, da = normalize(a)
        nb, db = normalize(b)
        if min(da, db) < cfg["minimum_contrast"]:
            return {"decision": "abstain", "score": None, "reason": "low_contrast"}
        if candidate:
            a, b = na, nb
        else:
            a, b = a / 255, b / 255
        scores.append(float(np.sqrt(np.mean((a - b) ** 2))))
    score = max(scores)
    return {"decision": "flag" if score >= cfg["threshold"] else "clear", "score": score}


def correct(row, arm):
    expected = "flag" if row["attack"] else "clear"
    return row[arm]["decision"] == expected


def aggregate(rows):
    result = {"pairs": len(rows), "benign": sum(not r["attack"] for r in rows),
              "attacks": sum(r["attack"] for r in rows)}
    for arm in ("baseline", "candidate"):
        result[arm] = {
            "correct": sum(correct(r, arm) for r in rows),
            "benign_clear": sum(not r["attack"] and r[arm]["decision"] == "clear" for r in rows),
            "false_flags": sum(not r["attack"] and r[arm]["decision"] == "flag" for r in rows),
            "attacks_flagged": sum(r["attack"] and r[arm]["decision"] == "flag" for r in rows),
            "attacks_clear": sum(r["attack"] and r[arm]["decision"] == "clear" for r in rows),
            "attack_non_detections": sum(r["attack"] and r[arm]["decision"] != "flag" for r in rows),
            "abstentions": sum(r[arm]["decision"] == "abstain" for r in rows),
            "errors": sum(r[arm]["decision"] == "error" for r in rows),
        }
    result["recovered"] = sum(not correct(r, "baseline") and correct(r, "candidate") for r in rows)
    result["regressed"] = sum(correct(r, "baseline") and not correct(r, "candidate") for r in rows)
    result["new_false_flags"] = sum(not r["attack"] and r["baseline"]["decision"] != "flag"
                                    and r["candidate"]["decision"] == "flag" for r in rows)
    result["new_clear_attacks"] = sum(r["attack"] and r["baseline"]["decision"] != "clear"
                                     and r["candidate"]["decision"] == "clear" for r in rows)
    return result


def verify(root):
    if root.is_symlink() or (root.stat().st_mode & 0o077):
        raise ValueError("artifact directory must be owner-private and not a symlink")
    freeze = read_json(root / "data-freeze.json")
    if source_hashes() != freeze["source"]:
        raise ValueError("source/config changed since freeze")
    if digest((root / "manifest.json").read_bytes()) != freeze["manifest_sha256"]:
        raise ValueError("manifest changed since freeze")
    rows = read_json(root / "manifest.json")["rows"]
    cfg = read_json(root / "protocol.json")
    groups, devices = {}, {}
    conditions = cfg["benign"] + cfg["attacks"]
    seen = set()
    for row in rows:
        assert row["id"] not in seen
        seen.add(row["id"])
        assert row["split"] in ("TRAIN", "DEV")
        assert row["device"] in cfg[row["split"].lower() + "_devices"]
        assert groups.setdefault(row["group"], row["split"]) == row["split"]
        assert devices.setdefault(row["device"], row["split"]) == row["split"]
        assert row["condition"] in conditions
        assert row["attack"] == (row["condition"] in cfg["attacks"])
        for file in row["files"]:
            path = root / file["name"]
            assert path.parent == root and not path.is_symlink()
            assert not path.stat().st_mode & 0o077
            assert digest(path.read_bytes()) == file["sha256"]
    for group in groups:
        assert Counter(r["condition"] for r in rows if r["group"] == group) == Counter(conditions)
    for split in ("TRAIN", "DEV"):
        assert sum(r["split"] == split for r in rows) == 48 * len(conditions)
    return cfg, rows, freeze


def run(root, output):
    if output.exists() or (root / "outcomes.json").exists():
        raise FileExistsError("Refusing to overwrite a completed run")
    cfg, rows, freeze = verify(root)
    write_json(root / "inference-start.json", {"at": now(), "freeze_sha256": digest((root / "data-freeze.json").read_bytes())})
    outcomes = []
    for row in rows:
        out = {k: row[k] for k in ("id", "group", "split", "condition", "attack")}
        try:
            images = [np.asarray(Image.open(root / f["name"]).convert("L"), dtype=float) for f in row["files"]]
            for arm in ("baseline", "candidate"):
                try:
                    out[arm] = predict(*images, cfg, candidate=arm == "candidate")
                except Exception as exc:
                    out[arm] = {"decision": "error", "reason": type(exc).__name__, "score": None}
        except Exception as exc:
            for arm in ("baseline", "candidate"):
                out[arm] = {"decision": "error", "reason": type(exc).__name__, "score": None}
        outcomes.append(out)
    verify(root)
    write_json(root / "outcomes.json", outcomes)
    report = {"version": cfg["version"], "at": now(), "private_root": str(root),
              "source": source_hashes(), "manifest_sha256": freeze["manifest_sha256"],
              "private_outcomes_sha256": digest((root / "outcomes.json").read_bytes()),
              "threshold": cfg["threshold"], "splits": {}}
    for split in ("TRAIN", "DEV"):
        selected = [r for r in outcomes if r["split"] == split]
        result = aggregate(selected)
        result["conditions"] = {c: aggregate([r for r in selected if r["condition"] == c])
                                for c in cfg["benign"] + cfg["attacks"]}
        report["splits"][split] = result
    dev = report["splits"]["DEV"]
    report["gate_passed"] = (dev["candidate"]["correct"] > dev["baseline"]["correct"]
                             and dev["regressed"] == 0 and dev["new_clear_attacks"] == 0
                             and dev["new_false_flags"] == 0)
    write_json(output, report)
    print(json.dumps({s: {k: v for k, v in report["splits"][s].items() if k != "conditions"}
                      for s in ("TRAIN", "DEV")}, indent=2))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "verify"))
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE)
    parser.add_argument("--output", type=Path, default=HERE / "aggregate-v1.json")
    args = parser.parse_args()
    root = args.private_root.absolute()
    repo = HERE.parent.parent
    if root == repo or repo in root.parents:
        raise ValueError("raw artifacts must be outside the repository")
    if args.command == "prepare":
        prepare(root)
    elif args.command == "run":
        run(root, args.output)
    else:
        _, rows, _ = verify(root)
        print(json.dumps({"verified_rows": len(rows)}))


if __name__ == "__main__":
    main()
