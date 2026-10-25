"""Label-speed v2 experiment runner (DEV only). See README.md.

    run.py freeze SNAP       pin the probe binary, models and snapshot receipt
    run.py profile SNAP      time split of the tiled reading (user photo + DEV)
    run.py accuracy SNAP     all 72 labelled DEV frames, every mode, 2 workers
    run.py user SNAP         the user's photo: every mode, cold and warm, 1 CPU
    run.py latency SNAP      DEV frames, paired alternating full vs candidates, 1 CPU
    run.py threads SNAP      the user's photo, full vs candidates, 2 threads on 2 CPUs

Every phase first verifies the frozen hashes (binary, models, receipt) and
records the runner's own hash; outputs are written once to SNAP/runs/ (never
overwritten). The probe's stdout holds decoded and printed values: they are
parsed in memory and only counts, rates, timings and opaque DEV frame ids
are written.

Candidates and the gate were declared before any candidate read a DEV frame
(no tuning: every candidate's parameters are the library's own):

- `once-tiles`: label_speed::read_lines, Detection::Tiles;
- `once-page`:  label_speed::read_lines, Detection::Page;
- `ppocr`, `ppocr-detail`: PP-OCRv6 tiny lines as rows (max side 960; 960+1600).

Gate (all 72 DEV frames and the user's photo), against the full reading:
no lost shown field (label + value), no more false fields, no fewer truth
label+value hits, no check-digit change on a kept field, no probe failure
(a failed frame keeps its truth fields in the denominator as misses), and
on the user's photo the report's five fields with identical label, value,
kind and check-digit result. Source (`both`/`barcode`/`text`) changes are
reported, not gated: the full reading's own source already varies between
runtimes (docs/performance-barcode.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(os.environ.get("LABEL_SPEED_DIR", "/tmp/docscan-label-speed-v2"))
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench")) / "barcode" / "synth_dev"
USER_IMAGE = Path(os.environ.get("USER_IMAGE", ""))
USER_REPORT = Path(os.environ.get("USER_REPORT", ""))
CPUS = os.environ.get("LABEL_SPEED_CPUS", "4,5").split(",")
CANDIDATES = ["once-tiles", "once-page", "ppocr", "ppocr-detail"]
MODES = ["full"] + CANDIDATES


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(s) -> str:
    return "".join(c for c in str(s or "").upper() if c.isalnum())


class Snap:
    def __init__(self, name: str):
        self.dir = ROOT / name
        self.bin = self.dir / "bin" / "label_speed_probe"
        self.models = self.dir / "models"

    def verify(self) -> dict:
        f = json.loads((self.dir / "freeze.json").read_text())
        assert sha(self.bin) == f["binary"], "probe binary changed since freeze"
        for name, h in f.get("binaries", {}).items():
            assert sha(self.bin.parent / name) == h, f"{name} changed since freeze"
        assert sha(self.dir / "receipt.json") == f["receipt"], "receipt changed since freeze"
        for m, h in f["models"].items():
            assert sha(self.models / m) == h, f"model {m} changed since freeze"
        return {"freeze": sha(self.dir / "freeze.json"), "runner": {p.name: sha(p) for p in sorted(HERE.glob("*.py")) + sorted(HERE.glob("*.mjs"))}}

    def write(self, phase: str, obj: dict) -> Path:
        (self.dir / "runs").mkdir(exist_ok=True)
        p = self.dir / "runs" / f"{phase}-{time.strftime('%Y%m%dT%H%M%S')}.json"
        with open(p, "x") as fh:  # never overwrite
            fh.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        print(json.dumps(obj, indent=1, sort_keys=True))
        return p

    def probe(self, paths: list[str], mode: str, *, repeat: int = 1, cpus: str | None = None, threads: int = 1, parity: bool = False) -> list[dict]:
        cmd = [str(self.bin), f"--models={self.models}", f"--mode={mode}", f"--repeat={repeat}"] + (["--parity"] if parity else [])
        if cpus is not None:
            cmd = ["taskset", "-c", cpus] + cmd
        env = {**os.environ, "RAYON_NUM_THREADS": str(threads), "RTEN_NUM_THREADS": str(threads)}
        r = subprocess.run(cmd + paths, capture_output=True, text=True, env=env, timeout=3600)
        if r.returncode != 0:
            # stderr can carry values in a panic message; report only its length.
            raise RuntimeError(f"probe failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
        return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]

    def robust(self, paths: list[str], mode: str, cpus: str) -> tuple[dict, list[str]]:
        """Every path's first reading; a failing chunk is retried frame by
        frame so one failure cannot hide the others. Failed paths returned."""
        try:
            return {o["path"]: o for o in self.probe(paths, mode, cpus=cpus)}, []
        except RuntimeError:
            out, failed = {}, []
            for p in paths:
                try:
                    out[p] = self.probe([p], mode, cpus=cpus)[0]
                except RuntimeError:
                    failed.append(p)
            return out, failed

    def shard(self, paths: list[str], mode: str) -> tuple[dict, list[str]]:
        chunks = [paths[i::len(CPUS)] for i in range(len(CPUS))]
        with ThreadPoolExecutor(len(CPUS)) as ex:
            outs = list(ex.map(lambda ic: self.robust(ic[1], mode, CPUS[ic[0]]) if ic[1] else ({}, []), enumerate(chunks)))
        res = {k: v for o, _ in outs for k, v in o.items()}
        return res, [p for _, f in outs for p in f]


def shown(fields: list[dict]) -> list[dict]:
    """What the demo shows: fields failing their check digit are dropped."""
    return [f for f in fields if f.get("check_digit_valid") is not False]


def key(f: dict) -> tuple:
    return (f.get("label"), norm(f.get("value")))


def compare(base: list[dict], cand: list[dict]) -> dict:
    b = {key(f): f for f in shown(base)}
    c = {key(f): f for f in shown(cand)}
    kinds = {k: f["kind"] for k, f in list(b.items()) + list(c.items())}
    by = lambda s: {k: sum(1 for x in s if kinds[x] == k) for k in sorted({kinds[x] for x in s})}
    kept = b.keys() & c.keys()
    return {"base": len(b), "cand": len(c), "lost": len(b.keys() - c.keys()), "gained": len(c.keys() - b.keys()),
            "lost_by_kind": by(b.keys() - c.keys()), "gained_by_kind": by(c.keys() - b.keys()),
            "check_changed": sum(1 for k in kept if b[k].get("check_digit_valid") != c[k].get("check_digit_valid")),
            "kind_changed": sum(1 for k in kept if b[k]["kind"] != c[k]["kind"]),
            "source_changed": sum(1 for k in kept if b[k]["source"] != c[k]["source"]),
            "both_to_other": sum(1 for k in kept if b[k]["source"] == "both" and c[k]["source"] != "both"),
            "other_to_both": sum(1 for k in kept if b[k]["source"] != "both" and c[k]["source"] == "both")}


def sums(cmp: list[dict]) -> dict:
    out = {k: sum(c[k] for c in cmp) for k in ("base", "cand", "lost", "gained", "check_changed", "kind_changed", "source_changed", "both_to_other", "other_to_both")}
    for kk in ("lost_by_kind", "gained_by_kind"):
        agg: dict[str, int] = {}
        for c in cmp:
            for k, n in c[kk].items():
                agg[k] = agg.get(k, 0) + n
        out[kk] = agg
    return out


def truth_score(rows: list[dict], res: dict) -> dict:
    """bench/suites/barcode.py's labelled metrics on the fields shown, plus
    false fields (shown values that are no truth field or code). A frame
    without a result (probe failure) keeps its truth fields as misses."""
    n = v = lv = false = 0
    for r in rows:
        fields = shown(res[r["path"]]["fields"]) if r["path"] in res else []
        truth_vals = {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}
        for f in r["fields"]:
            vals = [g for g in fields if norm(g.get("value")) == norm(f["value"])]
            n += 1
            v += bool(vals)
            lv += any((g.get("label") or None) == (f.get("label") or None) for g in vals)
        false += sum(1 for g in fields if norm(g.get("value")) not in truth_vals)
    return {"truth_fields": n, "value_hits": v, "label_value_hits": lv, "false_fields": false, "value": round(v / n, 4), "label_value": round(lv / n, 4)}


def truth_delta(rows: list[dict], full: dict, cand: dict) -> dict:
    """Truth fields the full reading lists with the right label and the
    candidate does not (lost), and the reverse (gained), by truth label; and
    the lost/gained shown fields split into truth-correct (label and value of
    a truth field), right value under a wrong label, and false (no truth
    value or code). A failed frame lists nothing."""
    out: dict = {"label_value_lost": {}, "label_value_gained": {}, "lost_split": {"correct": 0, "wrong_label": 0, "false": 0, "false_imei_luhn": 0},
                 "gained_split": {"correct": 0, "wrong_label": 0, "false": 0, "false_imei_luhn": 0}}
    for r in rows:
        a = shown(full[r["path"]]["fields"]) if r["path"] in full else []
        b = shown(cand[r["path"]]["fields"]) if r["path"] in cand else []
        hit = lambda fs, f: any(norm(g.get("value")) == norm(f["value"]) and (g.get("label") or None) == (f.get("label") or None) for g in fs)
        for f in r["fields"]:
            lab = f.get("label") or "unlabelled"
            if hit(a, f) and not hit(b, f):
                out["label_value_lost"][lab] = out["label_value_lost"].get(lab, 0) + 1
            if hit(b, f) and not hit(a, f):
                out["label_value_gained"][lab] = out["label_value_gained"].get(lab, 0) + 1
        truth_lv = {((f.get("label") or None), norm(f["value"])) for f in r["fields"]}
        truth_v = {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}
        ka, kb = {key(g): g for g in a}, {key(g): g for g in b}
        for name, diff, src in (("lost_split", ka.keys() - kb.keys(), ka), ("gained_split", kb.keys() - ka.keys(), kb)):
            for k in diff:
                g = src[k]
                if ((g.get("label") or None), k[1]) in truth_lv:
                    out[name]["correct"] += 1
                elif k[1] in truth_v:
                    out[name]["wrong_label"] += 1
                else:
                    out[name]["false"] += 1
                    out[name]["false_imei_luhn"] += g["kind"] == "imei" and g.get("check_digit_valid") is True
    return out


def false_by_kind(rows: list[dict], res: dict) -> dict:
    out: dict = {}
    for r in rows:
        truth_v = {norm(f["value"]) for f in r["fields"]} | {norm(c["text"]) for c in r["codes"]}
        for g in shown(res[r["path"]]["fields"]) if r["path"] in res else []:
            if norm(g.get("value")) not in truth_v:
                k = g["kind"] + ("_check_valid" if g.get("check_digit_valid") is True else "")
                out[k] = out.get(k, 0) + 1
    return out


def ocr_cost(res: dict) -> dict:
    s = [o["ocr_stats"] for o in res.values() if isinstance(o.get("ocr_stats"), dict)]
    out = {"ocr_ms_sum": round(sum(o["stages"]["ocr"] for o in res.values()), 1)}
    for k in ("detection_passes", "lines_recognised", "detect_ms", "recognise_ms"):
        if s and all(k in x for x in s):
            out[k] = round(sum(x[k] for x in s), 1)
    return out


def dev_rows() -> list[dict]:
    rows = [json.loads(l) for l in (DATA / "truth.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("fields")]
    for r in rows:
        r["path"] = str(DATA / r["image"])
    return rows


def med(xs):
    return round(statistics.median(xs), 1) if xs else None


def phase_freeze(s: Snap) -> None:
    p = s.dir / "freeze.json"
    if p.exists():
        raise SystemExit("already frozen")
    receipt = json.loads((s.dir / "receipt.json").read_text())
    obj = {"receipt": sha(s.dir / "receipt.json"), "models": receipt["models"], "head": receipt["head"], "patched": receipt.get("patched", False), "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if s.bin.exists():
        obj["binary"] = sha(s.bin)
        obj["binaries"] = {b.name: sha(b) for b in sorted(s.bin.parent.iterdir())}
    if (s.dir / "pkg").is_dir():
        sys.path.insert(0, str(HERE))
        from run_wasm import pkg_hash
        obj["wasm_pkg"] = pkg_hash(s.dir / "pkg")
    with open(p, "x") as fh:
        fh.write(json.dumps(obj, indent=1) + "\n")
    p.chmod(0o400)
    if s.bin.exists():
        s.bin.chmod(0o500)
    print(json.dumps(obj, indent=1))


def phase_profile(s: Snap) -> None:
    prov = s.verify()
    rows = dev_rows()
    sel = [r["path"] for r in rows if r["size"] == [720, 1280]][:4] + [r["path"] for r in rows if r["size"] == [1280, 720]][:4]
    out: dict = {"provenance": prov, "cpu": CPUS[0]}
    groups = {"dev_portrait_720x1280": sel[:4], "dev_landscape_1280x720": sel[4:]}
    if USER_IMAGE.is_file():
        groups = {"user": [str(USER_IMAGE)], **groups}
    for g, paths in groups.items():
        prof = s.probe(paths, "profile", repeat=2, cpus=CPUS[0])
        full = s.probe(paths, "full", repeat=2, cpus=CPUS[0])
        warm = [o for o in prof if o["iteration"] == 1]
        fw = [o for o in full if o["iteration"] == 1]
        st = [o["ocr_stats"] for o in warm]
        out[g] = {"frames": len(paths), "full_total_ms_median": med([o["total_ms"] for o in fw]), "full_ocr_ms_median": med([o["stages"]["ocr"] for o in fw]),
                  "replica_ocr_ms_median": med([o["stages"]["ocr"] for o in warm]),
                  **{k: med([x[k] for x in st]) for k in ("tiles", "level_ms", "detect_ms", "layout_ms", "recognise_ms", "lines_recognised", "rows_before_dedup", "rows_after_dedup", "words_detected")},
                  "replica_vs_full_fields": sums([compare(f["fields"], p["fields"]) for f, p in zip(fw, warm)])}
    s.write("profile", out)


def phase_accuracy(s: Snap) -> None:
    prov = s.verify()
    rows = dev_rows()
    paths = [r["path"] for r in rows]
    res, failed = {}, {}
    for m in MODES:
        res[m], failed[m] = s.shard(paths, m)
    out: dict = {"provenance": prov, "frames": len(rows), "workers": len(CPUS), "threads_per_worker": 1,
                 "failures": {m: len(f) for m, f in failed.items()}, "failed_frames": {m: [r["id"] for r in rows if r["path"] in failed[m]] for m in MODES}}
    out["full"] = {**truth_score(rows, res["full"]), **ocr_cost(res["full"]), "false_by_kind": false_by_kind(rows, res["full"])}
    for m in CANDIDATES:
        ok = [p for p in paths if p in res[m] and p in res["full"]]
        cmp = [compare(res["full"][p]["fields"], res[m][p]["fields"]) for p in ok]
        t = truth_score(rows, res[m])
        sm = sums(cmp)
        out[m] = {**t, **ocr_cost(res[m]), **sm, "false_by_kind": false_by_kind(rows, res[m]), "truth_delta": truth_delta(rows, res["full"], res[m]),
                  "frames_with_loss": [r["id"] for r in rows if r["path"] in ok and compare(res["full"][r["path"]]["fields"], res[m][r["path"]]["fields"])["lost"]],
                  "gate_dev": {"no_lost": sm["lost"] == 0, "false_not_more": t["false_fields"] <= out["full"]["false_fields"],
                               "truth_not_fewer": t["label_value_hits"] >= out["full"]["label_value_hits"], "no_check_change": sm["check_changed"] == 0,
                               "no_failure": not failed[m]}}
        out[m]["gate_dev"]["passed"] = all(out[m]["gate_dev"].values())
    for sub, sel in (("by_size", None),):
        agg = {}
        for size in sorted({tuple(r["size"]) for r in rows}):
            ps = [r for r in rows if tuple(r["size"]) == size]
            agg["x".join(map(str, size))] = {m: {**truth_score(ps, res[m]), "ocr_ms_sum": round(sum(res[m][r["path"]]["stages"]["ocr"] for r in ps if r["path"] in res[m]), 1)} for m in MODES}
        out[sub] = agg
    s.write("accuracy", out)


def report_fields() -> list[dict]:
    d = json.loads(USER_REPORT.read_text())
    return d["outcome"]["fields"]


def vs_report(fields: list[dict]) -> dict:
    """Flags only: the report's fields against a reading, by label and value."""
    rep = {(f.get("label"), norm(f["value"])): f for f in report_fields()}
    got = {key(f): f for f in shown(fields)}
    kept = rep.keys() & got.keys()
    return {"report_fields": len(rep), "listed": len(kept), "missing": len(rep.keys() - got.keys()), "extra": len(got.keys() - rep.keys()),
            "kind_same": all(rep[k]["kind"] == got[k]["kind"] for k in kept), "check_same": all(rep[k].get("check_digit_valid") == got[k].get("check_digit_valid") for k in kept),
            "source_same": sum(1 for k in kept if rep[k]["source"] == got[k]["source"])}


def phase_user(s: Snap) -> None:
    prov = s.verify()
    if not (USER_IMAGE.is_file() and USER_REPORT.is_file()):
        raise SystemExit("set USER_IMAGE and USER_REPORT (private)")
    img = [str(USER_IMAGE)]
    out: dict = {"provenance": prov, "image": "user photo (private)", "cpu": CPUS[0]}
    fields = {}
    for m in MODES:
        cold = [s.probe(img, m, cpus=CPUS[0], parity=(m == "full"))[0] for _ in range(3)]
        warm = s.probe(img, m, repeat=6, cpus=CPUS[0])[1:]
        fields[m] = cold[0]["fields"]
        out[m] = {"cold_total_ms": [round(c["total_ms"], 1) for c in cold], "warm_total_ms_median": med([w["total_ms"] for w in warm]),
                  "warm_ocr_ms_median": med([w["stages"]["ocr"] for w in warm]), "models_ms_median": med([c["models_ms"] for c in cold]),
                  "ocr_stats": cold[0]["ocr_stats"] if isinstance(cold[0]["ocr_stats"], dict) else None,
                  "same_as_library": cold[0]["same_as_library"], "vs_report": vs_report(cold[0]["fields"]),
                  "stable_across_cold_runs": all(c["fields"] == cold[0]["fields"] for c in cold)}
        for k in ("ocr_stats",):
            if out[m][k]:
                out[m][k] = {kk: (round(v, 1) if isinstance(v, float) else v) for kk, v in out[m][k].items()}
    for m in CANDIDATES:
        out[m]["vs_full"] = compare(fields["full"], fields[m])
        out[m]["warm_speedup_vs_full"] = round(out["full"]["warm_total_ms_median"] / out[m]["warm_total_ms_median"], 2)
    s.write("user", out)


def phase_latency(s: Snap) -> None:
    prov = s.verify()
    rows = dev_rows()
    picks = []
    for size in ([720, 1280], [1280, 720], [1920, 1080], [640, 480]):
        picks += [r for r in rows if r["size"] == size][1::2][:3]
    paths = [r["path"] for r in picks]
    modes = os.environ.get("LATENCY_MODES", "full,once-tiles,once-page").split(",")
    res: dict = {}
    for rep in range(2):
        order = modes if rep % 2 == 0 else list(reversed(modes))
        for m in order:
            for o in s.probe(paths, m, repeat=2, cpus=CPUS[0]):
                if o["iteration"] == 1:
                    res.setdefault(m, {}).setdefault(o["path"], []).append(o["total_ms"])
    per = {m: {p: statistics.median(v) for p, v in d.items()} for m, d in res.items()}
    out: dict = {"provenance": prov, "frames": len(paths), "cpu": CPUS[0], "frame_ids": [r["id"] for r in picks],
                 "ms_median": {m: med(list(per[m].values())) for m in modes}}
    for m in modes[1:]:
        ratio = [per[m][p] / per["full"][p] for p in paths]
        out[m] = {"over_full_median": round(statistics.median(ratio), 3), "over_full_max": round(max(ratio), 3), "over_full_min": round(min(ratio), 3)}
    s.write("latency", out)


def phase_threads(s: Snap) -> None:
    prov = s.verify()
    if not USER_IMAGE.is_file():
        raise SystemExit("set USER_IMAGE")
    img = [str(USER_IMAGE)]
    cpus = ",".join(CPUS[:2])
    out: dict = {"provenance": prov, "cpus": cpus, "threads": 2}
    for m in os.environ.get("LATENCY_MODES", "full,once-tiles,once-page").split(","):
        warm = s.probe(img, m, repeat=6, cpus=cpus, threads=2)[1:]
        one = s.probe(img, m, repeat=6, cpus=CPUS[0], threads=1)[1:]
        out[m] = {"warm_ms_median_2threads": med([w["total_ms"] for w in warm]), "warm_ms_median_1thread": med([w["total_ms"] for w in one]),
                  "fields_same_1_vs_2": warm[0]["fields"] == one[0]["fields"]}
    s.write("threads", out)


def phase_api(s: Snap) -> None:
    """The patch's public `labelled_fast_native` against the probe's measured
    `ppocr` mode, on all 72 DEV frames (and the user's photo when set): the
    fields must be identical. Also: an unloaded reader errors."""
    prov = s.verify()
    paths = [r["path"] for r in dev_rows()] + ([str(USER_IMAGE)] if USER_IMAGE.is_file() else [])
    r = subprocess.run(["taskset", "-c", CPUS[0], str(s.bin.parent / "label_speed_api"), f"--models={s.models}"] + paths,
                       capture_output=True, text=True, env={**os.environ, "RAYON_NUM_THREADS": "1", "RTEN_NUM_THREADS": "1"}, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"api check failed ({r.returncode}, {len(r.stderr)} bytes of stderr)")
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    api = {o["path"]: o["fields"] for o in lines if "path" in o}
    probe = {o["path"]: o["fields"] for o in s.probe(paths, "ppocr", cpus=CPUS[0])}
    same = [p for p in paths if api.get(p) == probe.get(p)]
    s.write("api", {"provenance": prov, "frames": len(paths), "user_photo_included": USER_IMAGE.is_file(),
                    "identical_fields": len(same), "different": len(paths) - len(same),
                    "unloaded_errors": next(o["unloaded_errors"] for o in lines if "unloaded_errors" in o)})


if __name__ == "__main__":
    phase, snap = sys.argv[1], Snap(sys.argv[2])
    {"freeze": phase_freeze, "profile": phase_profile, "accuracy": phase_accuracy, "user": phase_user, "latency": phase_latency, "threads": phase_threads, "api": phase_api}[phase](snap)
