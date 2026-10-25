"""Label-robustness experiment runner (DEV + fictional stress only). See README.md.

    run.py freeze SNAP      pin probe binary, models, receipt and the stress gold
    run.py accuracy SNAP    every reading on DEV (72 frames) and stress (120)
    run.py user SNAP        the private user photo, only if USER_IMAGE and
                            USER_REPORT are set by the caller (never stored)

Every phase verifies the freeze first and records the runner's own hashes;
outputs are written once to SNAP/runs/ (exclusive create). The probe prints
values; they are parsed in memory and only counts, timings and opaque frame
or specimen ids are written.

Declared before the measured run (code, models and gold frozen first):

Readings: `fast` (the shipped `labelled_fast_native`, the baseline),
`detailed` (the shipped `labelled_native`, the comparator), `replica` (the
probe's re-implementation of `fast` through the patch's research entry point,
no change), and the two arms, nothing tuned:

- `a-fullres`: recognition crops sampled from the frame as the caller gave it
  (at most 1920 wide in the app) instead of from its 1280-wide copy, as the
  official PaddleOCR/PaddleX OCR pipeline crops from the original image.
  Detection is unchanged; frames up to 1280 wide read identically.
- `b-rescore`: each horizontal line's two readings, PP-OCRv6 tiny's greedy
  text and ocrs's recogniser's greedy text of the same quad, are scored by
  the sum of the two models' CTC log-likelihoods (forward algorithm, equal
  weights); the higher wins, PP-OCR on ties. Skipped when either string has
  a character outside the other model's alphabet. A replacement may not
  change a digit run that passes its check digit in the PP-OCR reading.

Corpora: DEV = the 72 labelled `barcode_synth_dev` frames (296 truth fields);
STRESS = `stress.py` seed 5150, 30 specimens x {clean, font, blur,
perspective} (120 frames, 480 truth fields), gold frozen before inference.

Gate, per arm, against `fast` (all must hold for "passes"):
G1 parity: `replica` fields identical to `fast` on every frame of both
   corpora (else the run is invalid, not just the arm);
G2 no lost truth: zero truth label+value hits of `fast` lost, either corpus;
G3 false fields not more than `fast`'s on either corpus, and no added false
   field passing a check digit;
G4 gain: label+value hits summed over both corpora strictly more than
   `fast`'s, and serial errors (SN truth fields not listed + false SN fields)
   not more on either corpus;
G5 no check-digit change on a kept field; no probe failure (a failed frame
   keeps its truth in the denominator as misses);
G6 cost: summed native total ms at most 2.0x `fast`'s on each corpus;
G7 the user photo (only when supplied): the report's fields with identical
   label, value, kind and check result (recorded as not run otherwise).
A passing arm is a candidate for the Fast profile only; it does not make
Fast the default reader.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(os.environ.get("LABEL_ROBUSTNESS_DIR", "/tmp/docscan-label-robustness"))
HERE = Path(__file__).resolve().parent
DEV = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench")) / "barcode" / "synth_dev"
STRESS = ROOT / "stress-5150"
USER_IMAGE = Path(os.environ.get("USER_IMAGE", ""))
USER_REPORT = Path(os.environ.get("USER_REPORT", ""))
CPUS = os.environ.get("LABEL_ROBUSTNESS_CPUS", "6,7").split(",")
ARMS = ["a-fullres", "b-rescore"]
MODES = ["fast", "detailed", "replica"] + ARMS


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


def shown(fields: list[dict]) -> list[dict]:
    """What the app shows: fields failing their check digit are dropped."""
    return [f for f in fields if f.get("check_digit_valid") is not False]


def key(f: dict) -> tuple:
    return (f.get("label"), norm(f.get("value")))


class Snap:
    def __init__(self, name: str):
        self.dir = ROOT / name
        self.bin = self.dir / "bin" / "label_robustness_probe"
        self.models = self.dir / "models"

    def verify(self) -> dict:
        f = json.loads((self.dir / "freeze.json").read_text())
        assert sha(self.bin) == f["binary"], "probe binary changed since freeze"
        assert sha(self.dir / "receipt.json") == f["receipt"], "receipt changed since freeze"
        for m, h in f["models"].items():
            assert sha(self.models / m) == h, f"model {m} changed since freeze"
        assert sha(STRESS / "gold-receipt.json") == f["stress_gold"], "stress gold changed since freeze"
        gold = json.loads((STRESS / "gold-receipt.json").read_text())
        assert sha(STRESS / "truth.jsonl") == gold["truth"], "stress truth changed"
        for rel, h in gold["files"].items():
            assert sha(STRESS / rel) == h, "stress frame changed"
        return {"freeze": sha(self.dir / "freeze.json"), "runner": {p.name: sha(p) for p in sorted(HERE.glob("*.py"))}}

    def write(self, phase: str, obj: dict) -> Path:
        (self.dir / "runs").mkdir(exist_ok=True)
        p = self.dir / "runs" / f"{phase}-{time.strftime('%Y%m%dT%H%M%S')}.json"
        with open(p, "x") as fh:
            fh.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        print(json.dumps(obj, indent=1, sort_keys=True))
        return p

    def probe(self, paths: list[str], mode: str, cpu: str) -> list[dict]:
        cmd = ["taskset", "-c", cpu, str(self.bin), f"--models={self.models}", f"--mode={mode}"] + paths
        env = {**os.environ, "RAYON_NUM_THREADS": "1", "RTEN_NUM_THREADS": "1"}
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=7200)
        if r.returncode != 0:
            # stderr can carry values in a panic message; report only its length.
            raise RuntimeError(f"probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
        return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]

    def robust(self, paths: list[str], mode: str, cpu: str) -> tuple[dict, list[str]]:
        try:
            return {o["path"]: o for o in self.probe(paths, mode, cpu)}, []
        except RuntimeError:
            out, failed = {}, []
            for p in paths:
                try:
                    out[p] = self.probe([p], mode, cpu)[0]
                except RuntimeError:
                    failed.append(p)
            return out, failed

    def shard(self, paths: list[str], mode: str) -> tuple[dict, list[str]]:
        chunks = [paths[i::len(CPUS)] for i in range(len(CPUS))]
        with ThreadPoolExecutor(len(CPUS)) as ex:
            outs = list(ex.map(lambda ic: self.robust(ic[1], mode, CPUS[ic[0]]) if ic[1] else ({}, []), enumerate(chunks)))
        return {k: v for o, _ in outs for k, v in o.items()}, [p for _, f in outs for p in f]


def truth_values(r: dict) -> set[str]:
    return {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}


def hit(fs: list[dict], f: dict) -> bool:
    return any(norm(g.get("value")) == norm(f["value"]) and (g.get("label") or None) == (f.get("label") or None) for g in fs)


def score(rows: list[dict], res: dict) -> dict:
    """Truth metrics on the fields shown. A frame without a result keeps its
    truth fields as misses. Serial errors: SN truth fields not listed with
    label and value, plus shown SN fields whose value is no truth value."""
    n = v = lv = false = sn_n = sn_hit = sn_false = false_checked = 0
    false_kind: dict = {}
    for r in rows:
        fs = shown(res[r["path"]]["fields"]) if r["path"] in res else []
        tv = truth_values(r)
        for f in r["fields"]:
            n += 1
            v += any(norm(g.get("value")) == norm(f["value"]) for g in fs)
            ok = hit(fs, f)
            lv += ok
            if f.get("label") == "SN":
                sn_n += 1
                sn_hit += ok
        for g in fs:
            if norm(g.get("value")) not in tv:
                false += 1
                k = g["kind"] + ("_check_valid" if g.get("check_digit_valid") is True else "")
                false_kind[k] = false_kind.get(k, 0) + 1
                false_checked += g.get("check_digit_valid") is True
                sn_false += g.get("label") == "SN"
    return {"truth_fields": n, "value_hits": v, "label_value_hits": lv, "false_fields": false, "false_by_kind": false_kind,
            "false_check_valid": false_checked, "sn_truth": sn_n, "sn_hits": sn_hit, "sn_false": sn_false,
            "serial_errors": (sn_n - sn_hit) + sn_false}


def delta(rows: list[dict], base: dict, cand: dict) -> dict:
    """Against the baseline: truth label+value hits lost / gained (by label);
    shown fields lost / gained split into correct, wrong label, false; kept
    fields whose kind or check result changed; frames identical."""
    out: dict = {"truth_lost": {}, "truth_gained": {}, "shown_lost": {"correct": 0, "wrong_label": 0, "false": 0},
                 "shown_gained": {"correct": 0, "wrong_label": 0, "false": 0, "false_check_valid": 0},
                 "check_changed": 0, "kind_changed": 0, "source_changed": 0, "frames_identical": 0}
    for r in rows:
        a = shown(base[r["path"]]["fields"]) if r["path"] in base else []
        b = shown(cand[r["path"]]["fields"]) if r["path"] in cand else []
        if r["path"] in base and r["path"] in cand and base[r["path"]]["fields"] == cand[r["path"]]["fields"]:
            out["frames_identical"] += 1
        for f in r["fields"]:
            lab = f.get("label") or "unlabelled"
            if hit(a, f) and not hit(b, f):
                out["truth_lost"][lab] = out["truth_lost"].get(lab, 0) + 1
            if hit(b, f) and not hit(a, f):
                out["truth_gained"][lab] = out["truth_gained"].get(lab, 0) + 1
        tlv = {((f.get("label") or None), norm(f["value"])) for f in r["fields"]}
        tv = truth_values(r)
        ka, kb = {key(g): g for g in a}, {key(g): g for g in b}
        for name, diff, src in (("shown_lost", ka.keys() - kb.keys(), ka), ("shown_gained", kb.keys() - ka.keys(), kb)):
            for k in diff:
                g = src[k]
                if ((g.get("label") or None), k[1]) in tlv:
                    out[name]["correct"] += 1
                elif k[1] in tv:
                    out[name]["wrong_label"] += 1
                else:
                    out[name]["false"] += 1
                    if name == "shown_gained":
                        out[name]["false_check_valid"] += g.get("check_digit_valid") is True
        for k in ka.keys() & kb.keys():
            out["check_changed"] += ka[k].get("check_digit_valid") != kb[k].get("check_digit_valid")
            out["kind_changed"] += ka[k]["kind"] != kb[k]["kind"]
            out["source_changed"] += ka[k]["source"] != kb[k]["source"]
    out["truth_lost_total"] = sum(out["truth_lost"].values())
    out["truth_gained_total"] = sum(out["truth_gained"].values())
    return out


def specimens(rows: list[dict], base: dict, cand: dict) -> dict:
    """Per stress specimen (all four conditions together): label+value hits
    minus false fields, candidate against baseline."""
    net: dict = {}
    for r in rows:
        s = r["specimen"]
        for res, sign in ((cand, 1), (base, -1)):
            sc = score([r], res)
            net[s] = net.get(s, 0) + sign * (sc["label_value_hits"] - sc["false_fields"])
    return {"improved": sum(1 for x in net.values() if x > 0), "worsened": sum(1 for x in net.values() if x < 0),
            "unchanged": sum(1 for x in net.values() if x == 0), "worsened_ids": sorted(s for s, x in net.items() if x < 0)}


def cost(res: dict) -> dict:
    tot = [o["total_ms"] for o in res.values()]
    out = {"total_ms_sum": round(sum(tot), 1)}
    st = [o["stats"] for o in res.values() if o.get("stats", {}).get("lines")]
    if st:
        for k in ("lines", "considered", "agreed", "skipped_vertical", "skipped_alphabet", "protected_check_digit", "replaced"):
            out[k] = sum(s[k] for s in st)
        out["ocrs_rec_ms_sum"] = round(sum(s["ocrs_rec_ms"] for s in st), 1)
        out["max_ocrs_lse_dev"] = max(s["max_ocrs_lse_dev"] for s in st)
    return out


def rows_of(corpus: str) -> list[dict]:
    d = DEV if corpus == "dev" else STRESS
    rows = [json.loads(l) for l in (d / "truth.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("fields")]
    for r in rows:
        r["path"] = str(d / r["image"])
    return rows


def phase_freeze(s: Snap) -> None:
    p = s.dir / "freeze.json"
    if p.exists():
        raise SystemExit("already frozen")
    receipt = json.loads((s.dir / "receipt.json").read_text())
    obj = {"receipt": sha(s.dir / "receipt.json"), "models": receipt["models"], "head": receipt["head"], "patched": receipt["patched"],
           "binary": sha(s.bin), "stress_gold": sha(STRESS / "gold-receipt.json"), "runner": {q.name: sha(q) for q in sorted(HERE.glob("*.py"))},
           "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(p, "x") as fh:
        fh.write(json.dumps(obj, indent=1) + "\n")
    p.chmod(0o400)
    s.bin.chmod(0o500)
    print(json.dumps(obj, indent=1))


def gate(dev: dict, st: dict, arm: str) -> dict:
    g = {}
    g["G1_parity"] = dev["replica"]["vs_fast"]["frames_identical"] == dev["frames"] and st["replica"]["vs_fast"]["frames_identical"] == st["frames"]
    g["G2_no_lost_truth"] = dev[arm]["vs_fast"]["truth_lost_total"] == 0 and st[arm]["vs_fast"]["truth_lost_total"] == 0
    g["G3_false_not_more"] = all(c[arm]["false_fields"] <= c["fast"]["false_fields"] and c[arm]["vs_fast"]["shown_gained"]["false_check_valid"] == 0 for c in (dev, st))
    g["G4_gain"] = (dev[arm]["label_value_hits"] + st[arm]["label_value_hits"] > dev["fast"]["label_value_hits"] + st["fast"]["label_value_hits"]
                    and all(c[arm]["serial_errors"] <= c["fast"]["serial_errors"] for c in (dev, st)))
    g["G5_checks_failures"] = all(c[arm]["vs_fast"]["check_changed"] == 0 and c["failures"][arm] == 0 for c in (dev, st))
    g["G6_cost"] = all(c[arm]["total_ms_sum"] <= 2.0 * c["fast"]["total_ms_sum"] for c in (dev, st))
    g["passed_dev_stress"] = all(g.values())
    return g


def phase_accuracy(s: Snap) -> None:
    prov = s.verify()
    out: dict = {"provenance": prov, "workers": len(CPUS), "threads_per_worker": 1, "cpus": CPUS}
    for corpus in ("dev", "stress"):
        rows = rows_of(corpus)
        paths = [r["path"] for r in rows]
        res, failed = {}, {}
        for m in MODES:
            t = time.time()
            res[m], failed[m] = s.shard(paths, m)
            print(f"{corpus} {m}: {len(res[m])} frames, {len(failed[m])} failed, {time.time() - t:.0f} s", file=sys.stderr)
        c: dict = {"frames": len(rows), "failures": {m: len(f) for m, f in failed.items()}}
        for m in MODES:
            c[m] = {**score(rows, res[m]), **cost(res[m])}
            if m != "fast":
                c[m]["vs_fast"] = delta(rows, res["fast"], res[m])
                c[m]["cost_over_fast"] = round(c[m]["total_ms_sum"] / c["fast"]["total_ms_sum"], 3)
        for m in ARMS:
            c[m]["vs_detailed"] = delta(rows, res["detailed"], res[m])
        group = "condition" if corpus == "stress" else "size"
        keyf = (lambda r: r["condition"]) if corpus == "stress" else (lambda r: "x".join(map(str, r["size"])))
        c[f"by_{group}"] = {g: {m: score([r for r in rows if keyf(r) == g], res[m]) for m in MODES}
                            for g in sorted({keyf(r) for r in rows})}
        if corpus == "stress":
            c["specimens"] = {m: specimens(rows, res["fast"], res[m]) for m in ARMS + ["detailed"]}
        out[corpus] = c
    out["gate"] = {m: gate(out["dev"], out["stress"], m) for m in ARMS}
    s.write("accuracy", out)


def phase_user(s: Snap) -> None:
    prov = s.verify()
    if not (USER_IMAGE.is_file() and USER_REPORT.is_file()):
        raise SystemExit("USER_IMAGE and USER_REPORT are not set: G7 not run")
    rep = {(f.get("label"), norm(f["value"])): f for f in json.loads(USER_REPORT.read_text())["outcome"]["fields"]}
    out: dict = {"provenance": prov, "image": "user photo (private)"}
    for m in ["fast"] + ARMS:
        o = s.probe([str(USER_IMAGE)], m, CPUS[0])[0]
        got = {key(f): f for f in shown(o["fields"])}
        kept = rep.keys() & got.keys()
        out[m] = {"report_fields": len(rep), "listed": len(kept), "missing": len(rep.keys() - got.keys()), "extra": len(got.keys() - rep.keys()),
                  "kind_same": all(rep[k]["kind"] == got[k]["kind"] for k in kept),
                  "check_same": all(rep[k].get("check_digit_valid") == got[k].get("check_digit_valid") for k in kept),
                  "total_ms": round(o["total_ms"], 1)}
    for m in ARMS:
        out[m]["G7_passed"] = out[m]["missing"] == 0 and out[m]["kind_same"] and out[m]["check_same"]
    s.write("user", out)


if __name__ == "__main__":
    phase, snap = sys.argv[1], Snap(sys.argv[2])
    {"freeze": phase_freeze, "accuracy": phase_accuracy, "user": phase_user}[phase](snap)
