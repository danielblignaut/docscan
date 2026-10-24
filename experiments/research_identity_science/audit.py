"""Read-only audit: independent score/count reconstruction from frozen pixels."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = Path("/tmp/docscan-identity-science-v1")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recompute(pair, arm, cfg):
    # Independent design-matrix pseudoinverse, versus runner's lstsq.
    yy, xx = np.indices((56, 40))
    border = (xx < 2) | (xx > 37) | (yy < 2) | (yy > 53)
    mat = np.c_[np.ones(2240), xx.ravel(), yy.ravel()]
    pinv = np.linalg.pinv(mat[border.ravel()])
    diffs = []
    for index in range(10):
        transformed = []
        for im in pair:
            cell = im[:, index * 40:(index + 1) * 40]
            paper = (mat @ (pinv @ cell[border])).reshape(56, 40)
            residual = paper - cell
            contrast = np.quantile(residual, .95)
            if contrast < cfg["minimum_contrast"]:
                return "abstain", None
            transformed.append(np.clip(residual / contrast, 0, 1) if arm == "candidate" else cell / 255)
        diffs.append(np.linalg.norm(transformed[0] - transformed[1]) / np.sqrt(2240))
    score = float(max(diffs))
    return "flag" if score >= cfg["threshold"] else "clear", score


def main():
    os.umask(0o077)
    report = read(HERE / "aggregate-v1.json")
    cfg = read(ROOT / "protocol.json")
    manifest = read(ROOT / "manifest.json")
    outcomes = read(ROOT / "outcomes.json")
    assert len(outcomes) == len(manifest["rows"]) == 1344
    assert report["manifest_sha256"] == sha(ROOT / "manifest.json")
    assert report["private_outcomes_sha256"] == sha(ROOT / "outcomes.json")
    for name, value in report["source"].items():
        assert value == sha(HERE / name) == sha(ROOT / name)
    design = read(ROOT / "design-freeze.json")
    freeze = read(ROOT / "data-freeze.json")
    start = read(ROOT / "inference-start.json")
    assert design["at"] < freeze["at"] < start["at"] < report["at"]
    assert start["freeze_sha256"] == sha(ROOT / "data-freeze.json")
    for path in [ROOT, *ROOT.rglob("*")]:
        assert not path.is_symlink() and path.stat().st_mode & 0o077 == 0
    mappings = [{}, {}]
    for row, out in zip(manifest["rows"], outcomes, strict=True):
        for field in ("id", "group", "split", "condition", "attack"):
            assert row[field] == out[field]
        for mapping, key in zip(mappings, (row["group"], row["device"]), strict=True):
            assert mapping.setdefault(key, row["split"]) == row["split"]
        pair = []
        for file in row["files"]:
            path = ROOT / file["name"]
            assert path.parent == ROOT and file["sha256"] == sha(path)
            pair.append(np.asarray(Image.open(path), dtype=float))
        for arm in ("baseline", "candidate"):
            decision, score = recompute(pair, arm, cfg)
            assert decision == out[arm]["decision"]
            assert score is None if out[arm]["score"] is None else abs(score - out[arm]["score"]) < 1e-12
    checked = 0
    for split in ("TRAIN", "DEV"):
        rows = [r for r in outcomes if r["split"] == split]
        all_cells = [(rows, report["splits"][split])]
        all_cells += [([r for r in rows if r["condition"] == cond], cell)
                      for cond, cell in report["splits"][split]["conditions"].items()]
        for subset, cell in all_cells:
            assert cell["pairs"] == len(subset)
            assert cell["attacks"] == sum(r["attack"] for r in subset)
            assert cell["benign"] == len(subset) - cell["attacks"]
            flags = {}
            for arm in ("baseline", "candidate"):
                a = cell[arm]
                flags[arm] = [r[arm]["decision"] == ("flag" if r["attack"] else "clear") for r in subset]
                assert a["correct"] == sum(flags[arm])
                for key, attack, decision in (("attacks_flagged", True, "flag"),
                    ("attacks_clear", True, "clear"), ("false_flags", False, "flag"), ("benign_clear", False, "clear")):
                    assert a[key] == sum(r["attack"] == attack and r[arm]["decision"] == decision for r in subset)
                assert a["abstentions"] == sum(r[arm]["decision"] == "abstain" for r in subset)
                assert a["errors"] == sum(r[arm]["decision"] == "error" for r in subset)
                assert a["attack_non_detections"] == cell["attacks"] - a["attacks_flagged"]
            assert cell["recovered"] == sum(b and not a for a, b in zip(flags["baseline"], flags["candidate"]))
            assert cell["regressed"] == sum(a and not b for a, b in zip(flags["baseline"], flags["candidate"]))
            assert cell["new_false_flags"] == sum(not r["attack"] and r["baseline"]["decision"] != "flag" and r["candidate"]["decision"] == "flag" for r in subset)
            assert cell["new_clear_attacks"] == sum(r["attack"] and r["baseline"]["decision"] != "clear" and r["candidate"]["decision"] == "clear" for r in subset)
            checked += 1
    print(json.dumps({"passed": True, "pairs": len(outcomes), "arm_predictions": 2 * len(outcomes),
                      "aggregate_cells": checked, "groups": len(mappings[0]), "devices": len(mappings[1]),
                      "private_permissions": "passed", "freeze_order": "passed", "score_tolerance": 1e-12}))


if __name__ == "__main__":
    main()
