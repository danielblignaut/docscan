"""Face: recognition on LFW (10-fold accuracy, TAR @ FAR), ID photo vs live
face, passive anti-spoofing on CelebA-Spoof (AUC, APCER / BPCER / ACER),
active liveness on the synthetic clips (APCER per attack species, BPCER), and
native tracking time per frame.

Everything goes through the shipped on-device pipeline, natively
(`examples/face`, the Rust code the wasm runs): BlazeFace, Face Mesh V2,
five-point alignment, and the recogniser the demo ships. The shipped
configuration is read from the source, so changing it is measured, never
assumed: the recogniser from demo/src/face-models.ts (RECOGNISER), the live
threshold from docscan/src/face/mod.rs (THRESHOLDS), the document threshold
from demo/src/face-models.ts (DOC_THRESHOLD), and the liveness decision is
the session's own `passed` (its built-in thresholds).

Protocols (face/RESULTS.md, face/DATASETS.md):
- LFW: DEV = View 1 minus the pairs also in View 2 (2 442); TEST = View 2 (6 000
  pairs, its 10 folds). DEV has no official folds; its acc10 uses pair index
  mod 10. A face not found scores 0 similarity (a template of zeros), as
  face/eval/recognition.py.
- ID photo vs live: face/eval/document.py's renders; no face on the document
  scores -1.
- CelebA-Spoof: live probability (the two MiniFASNets' mean); a face not found
  is a rejection (score -1). Threshold 0.5, the session's.
- Liveness: one native session per clip at 30 fps; species = clip kind.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from lib.common import (ROOT, Cache, binary, binary_key, env1, log, m_info, m_latency, m_rate, m_stat, manifest, manifest_root, safe_digest,
                        sha256_file, sha256_json, taskset, timed_runs)

MODELS_DIR = ROOT / "models" / "face"
LIVENESS_CONFIG = {"guide": [0.5, 0.5, 0.38]}  # face/eval/liveness.py RUN_CONFIG
SPECIES = ["photo", "curved_photo", "screen", "video_2d", "partial"]


def shipped() -> dict:
    ts = (ROOT / "demo/src/face-models.ts").read_text()
    m = re.search(r'RECOGNISER\s*=\s*\{\s*file:\s*"([^"]+)",\s*name:\s*"([^"]+)",\s*kind:\s*"([^"]+)"', ts)
    doc_t = float(re.search(r"DOC_THRESHOLD\s*=\s*([0-9.]+)", ts).group(1))
    rs = (ROOT / "docscan/src/face/mod.rs").read_text()
    live_t = float(re.search(r'model:\s*"' + re.escape(m.group(2)) + r'",\s*threshold:\s*([0-9.]+)', rs).group(1))
    return {"file": m.group(1), "name": m.group(2), "kind": m.group(3), "live_threshold": live_t, "doc_threshold": doc_t}


def model_files(rec: dict) -> list[Path]:
    return [MODELS_DIR / f for f in ("face_detector.onnx", "face_landmarks_detector.onnx", "minifasnet.onnx", rec["file"])]


def face_cmd(rec: dict) -> list[str]:
    return [str(binary("face")), "--models", str(MODELS_DIR), "--recogniser", f"{rec['file']}:{rec['name']}:{rec['kind']}"]


# --------------------------------------------------------------------------- #
# Templates and anti-spoofing scores, cached per image
# --------------------------------------------------------------------------- #


def embed(paths: list[str], rec: dict, ctx, largest: bool = False) -> np.ndarray:
    """One template per image (zeros where no face), cached by (binary, models, image bytes)."""
    cache = Cache("face_embed", binary_key("face", models=model_files(rec)) + ("-largest" if largest else ""))
    shas = [sha256_file(Path(p)) for p in paths]
    todo = sorted({p for p, s in zip(paths, shas) if cache.get(s) is None})
    if todo:
        log(f"  face: {len(todo)} templates ({len(paths) - len(todo)} cached)")
        jobs = max(1, min(ctx.jobs, len(todo)))
        tmp = Path(tempfile.mkdtemp(prefix="bench-embed-"))
        (tmp / "list.txt").write_text("\n".join(todo) + "\n")

        def one(i):
            cmd = face_cmd(rec) + ["embed", str(tmp / "list.txt"), str(tmp / f"{i}.f32"), "--shard", f"{i}/{jobs}"] + (["--largest"] if largest else [])
            subprocess.run(cmd, check=True, env=env1(), capture_output=True)

        with ThreadPoolExecutor(jobs) as ex:
            list(ex.map(one, range(jobs)))
        k = 0
        for i in range(jobs):
            meta = json.loads((tmp / f"{i}.f32.json").read_text())
            raw = np.fromfile(tmp / f"{i}.f32", dtype="<f4")
            n = len(meta["items"])
            d = raw.size // n if n else 0
            for j, it in enumerate(meta["items"]):
                v = raw[j * d : (j + 1) * d] if it.get("found") else np.zeros(0, np.float32)
                cache.put(sha256_file(Path(todo[k])), {"found": bool(it.get("found")), "t": np.round(v, 6).tolist()})
                k += 1
        cache.save()
    vals = [cache.get(s) for s in shas]
    dim = max(len(v["t"]) for v in vals)
    return np.array([v["t"] if len(v["t"]) == dim else [0.0] * dim for v in vals], np.float32), np.array([v["found"] for v in vals])


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    na = np.maximum(np.linalg.norm(a, axis=1), 1e-12)
    nb = np.maximum(np.linalg.norm(b, axis=1), 1e-12)
    return (a * b).sum(1) / (na * nb)


def antispoof(paths: list[str], rec: dict, ctx) -> list[dict]:
    cache = Cache("face_antispoof", binary_key("face", models=model_files(rec)))
    shas = [sha256_file(Path(p)) for p in paths]
    todo = sorted({p for p, s in zip(paths, shas) if cache.get(s) is None})
    if todo:
        log(f"  face: anti-spoofing on {len(todo)} images ({len(paths) - len(todo)} cached)")
        jobs = max(1, min(ctx.jobs, len(todo)))
        tmp = Path(tempfile.mkdtemp(prefix="bench-fas-"))
        (tmp / "list.txt").write_text("\n".join(todo) + "\n")

        def one(i):
            subprocess.run(face_cmd(rec) + ["antispoof", str(tmp / "list.txt"), str(tmp / f"{i}.json"), "--shard", f"{i}/{jobs}"], check=True, env=env1(), capture_output=True)
            return json.loads((tmp / f"{i}.json").read_text())

        with ThreadPoolExecutor(jobs) as ex:
            parts = list(ex.map(one, range(jobs)))
        flat = [x for p in parts for x in p]
        for p, v in zip(todo, flat):
            cache.put(sha256_file(Path(p)), v)
        cache.save()
    return [cache.get(s) for s in shas]


# --------------------------------------------------------------------------- #


def lfw(ctx, rec: dict) -> tuple[dict, dict]:
    root = manifest_root(manifest("face_lfw"))
    img = lambda i: str(root / "images" / f"{i:05d}.jpg")  # noqa: E731
    pairs = {}
    if "dev" in ctx.splits:
        p = json.loads((root / "pairs_dev.json").read_text())
        pairs["dev"] = p[:600] if ctx.quick else p
    if "test" in ctx.splits:
        p = json.loads((root / "pairs_test.json").read_text())
        pairs["test"] = [x for x in p if x[3] in (1, 2)] if ctx.quick else p
    need = sorted({i for ps in pairs.values() for x in ps for i in x[:2]})
    emb, found = embed([img(i) for i in need], rec, ctx)
    row = {i: k for k, i in enumerate(need)}
    metrics, templates = {}, {"emb": emb, "row": row}
    t = rec["live_threshold"]
    for split, ps in pairs.items():
        a = emb[[row[x[0]] for x in ps]]
        b = emb[[row[x[1]] for x in ps]]
        s = cosine(a, b)
        y = np.array([x[2] for x in ps], bool)
        folds = np.array([x[3] for x in ps]) if split == "test" else np.arange(len(ps)) % 10 + 1
        raw = {"scores": s, "labels": y, "folds": folds}
        ids = safe_digest(sha256_json(ps))
        p = f"face.lfw_{split}"
        metrics[f"{p}.acc10"] = m_stat("kfold_acc", raw, desc="10-fold accuracy" + (" (View 2 folds)" if split == "test" else " (DEV: folds by pair index mod 10)"), ids_sha256=ids)
        raw2 = {"scores": s, "labels": y}
        metrics[f"{p}.tar_far1e-3"] = m_stat("tar_at_far", raw2, {"far": 1e-3}, desc="TAR at FAR 1e-3 (the split's own threshold)", ids_sha256=ids)
        metrics[f"{p}.tar_far1e-2"] = m_stat("tar_at_far", raw2, {"far": 1e-2}, desc="TAR at FAR 1e-2", ids_sha256=ids)
        metrics[f"{p}.tar_at_shipped"] = m_stat("tar_at_threshold", raw2, {"threshold": t}, desc=f"TAR at the shipped live threshold {t}", ids_sha256=ids)
        metrics[f"{p}.far_at_shipped"] = m_stat("far_at_threshold", raw2, {"threshold": t}, desc=f"FAR at the shipped live threshold {t}", better="lower", ids_sha256=ids)
    metrics["face.lfw.no_face"] = m_info(int((~found).sum()), desc=f"LFW images with no face found (of {len(need)})")
    return metrics, templates


def docpairs(ctx, rec: dict, templates: dict) -> dict:
    lroot = manifest_root(manifest("face_lfw"))
    metrics = {}
    t = rec["doc_threshold"]
    for split in ctx.splits:
        root = manifest_root(manifest(f"face_docpairs_{split}"))
        ps = json.loads((root / "pairs.json").read_text())
        if ctx.quick:
            ps = ps[:600] if split == "dev" else [x for x in ps if x.get("fold") in (1, 2)]
        demb, dfound = embed([str(root / x["doc"]) for x in ps], rec, ctx, largest=True)
        live_idx = [x["live"] for x in ps]
        missing = [i for i in live_idx if i not in templates["row"]]
        if missing:
            lemb, _ = embed([str(lroot / "images" / f"{i:05d}.jpg") for i in live_idx], rec, ctx)
        else:
            lemb = templates["emb"][[templates["row"][i] for i in live_idx]]
        s = cosine(demb, lemb)
        s[~dfound] = -1.0
        y = np.array([x["same"] for x in ps], bool)
        raw = {"scores": s, "labels": y}
        ids = safe_digest(sha256_json([x["doc"] for x in ps]))
        p = f"face.docface_{split}"
        metrics[f"{p}.tar_far1e-3"] = m_stat("tar_at_far", raw, {"far": 1e-3}, desc="ID photo vs live: TAR at FAR 1e-3", ids_sha256=ids)
        metrics[f"{p}.tar_far1e-2"] = m_stat("tar_at_far", raw, {"far": 1e-2}, desc="ID photo vs live: TAR at FAR 1e-2", ids_sha256=ids)
        metrics[f"{p}.tar_at_shipped"] = m_stat("tar_at_threshold", raw, {"threshold": t}, desc=f"ID photo vs live: TAR at the shipped DOC_THRESHOLD {t}", ids_sha256=ids)
        metrics[f"{p}.far_at_shipped"] = m_stat("far_at_threshold", raw, {"threshold": t}, desc=f"ID photo vs live: FAR at DOC_THRESHOLD {t}", better="lower", ids_sha256=ids)
        metrics[f"{p}.no_face"] = m_info(int((~dfound).sum()), desc="documents with no face found")
    return metrics


def celeba(ctx, rec: dict) -> dict:
    metrics = {}
    for split in ctx.splits:
        root = manifest_root(manifest(f"face_celeba_{split}"))
        labels = json.loads((root / "labels.json").read_text())
        n = len(labels) if not ctx.quick else {"dev": 500, "test": 1000}[split]
        paths = [str(root / f"{k:05d}.jpg") for k in range(n)]
        res = antispoof(paths, rec, ctx)
        s = np.array([x.get("real", -1.0) if x.get("found") else -1.0 for x in res])
        live = np.array([l == "live" for l in labels[:n]])
        raw = {"scores": s, "labels": live}
        ids = safe_digest(sha256_json(paths and [Path(p).name for p in paths]))
        p = f"face.antispoof_{split}"
        metrics[f"{p}.auc"] = m_stat("auc", raw, desc="CelebA-Spoof: AUC of the live probability", ids_sha256=ids)
        metrics[f"{p}.acer"] = m_stat("acer_at", raw, {"threshold": 0.5}, desc="CelebA-Spoof: ACER at 0.5 (the session's threshold)", better="lower", ids_sha256=ids)
        metrics[f"{p}.apcer"] = m_stat("apcer_at", raw, {"threshold": 0.5}, desc="CelebA-Spoof: APCER at 0.5 (all spoof types)", better="lower", ids_sha256=ids)
        metrics[f"{p}.bpcer"] = m_stat("bpcer_at", raw, {"threshold": 0.5}, desc="CelebA-Spoof: BPCER at 0.5", better="lower", ids_sha256=ids)
        metrics[f"{p}.no_face"] = m_info(int(sum(1 for x in res if not x.get("found"))), desc="images with no face found")
    return metrics


def liveness_run(clip: Path, rec: dict, cache: Cache) -> dict:
    key = sha256_file(clip)
    v = cache.get(key)
    if v is None:
        r = subprocess.run(face_cmd(rec) + ["liveness", str(clip), json.dumps(LIVENESS_CONFIG)], capture_output=True, text=True, env=env1())
        if r.returncode:
            raise RuntimeError(f"{clip}: {r.stderr[-500:]}")
        d = json.loads(r.stdout)
        res = d["result"]
        v = {"passed": bool(res["passed"]), "completed": bool(res["completed"]), "duration_ms": res.get("duration_ms"),
             "checks": {c["name"]: round(c["score"], 4) for c in res.get("checks", [])}, "ms_median": d.get("ms_median")}
        cache.put(key, v)
    return v


def clips_of(split: str, quick: bool) -> list[Path]:
    root = manifest_root(manifest(f"face_liveness_{split}"))
    clips = sorted(root.glob("*.y4m"))
    if quick:
        keep = []
        for kind in ["bona_fide"] + SPECIES:
            ks = [c for c in clips if c.stem.rsplit("_", 1)[0] == kind]
            keep += ks[: 6 if kind == "bona_fide" else 2]
        clips = keep
    return clips


def liveness(ctx, rec: dict) -> dict:
    cache = Cache("face_liveness", binary_key("face", models=model_files(rec)) + "-" + sha256_json(LIVENESS_CONFIG)[:8])
    metrics = {}
    for split in ctx.splits:
        clips = clips_of(split, ctx.quick)
        todo = [c for c in clips if cache.get(sha256_file(c)) is None]
        log(f"  face: liveness sessions on {len(todo)} clips ({len(clips) - len(todo)} cached)")
        with ThreadPoolExecutor(ctx.jobs) as ex:
            res = list(ex.map(lambda c: liveness_run(c, rec, cache), clips))
        cache.save()
        p = f"face.liveness_{split}"
        kinds = [c.stem.rsplit("_", 1)[0] for c in clips]
        bona = [(c.stem, r) for c, k, r in zip(clips, kinds, res) if k == "bona_fide"]
        metrics[f"{p}.bpcer"] = m_rate([s for s, _ in bona], [not r["passed"] for _, r in bona], desc="bona fide sessions rejected (BPCER)", better="lower")
        att_ids, att_ok = [], []
        apcers = {}
        for sp in SPECIES:
            xs = [(c.stem, r) for c, k, r in zip(clips, kinds, res) if k == sp]
            if not xs:
                continue
            metrics[f"{p}.apcer.{sp}"] = m_rate([s for s, _ in xs], [r["passed"] for _, r in xs], desc=f"'{sp}' attacks accepted (APCER for that species)", better="lower")
            apcers[sp] = metrics[f"{p}.apcer.{sp}"]["value"]
            att_ids += [s for s, _ in xs]
            att_ok += [r["passed"] for _, r in xs]
        metrics[f"{p}.apcer_all"] = m_rate(att_ids, att_ok, desc="attacks of every species accepted", better="lower")
        worst = max(apcers.values()) if apcers else 0.0
        metrics[f"{p}.acer_worst"] = m_info(round((worst + metrics[f"{p}.bpcer"]["value"]) / 2, 4), desc="(worst species APCER + BPCER) / 2")
        done = sorted(r["duration_ms"] / 1000 for _, r in bona if r["completed"] and r["duration_ms"])
        metrics[f"{p}.session_s_median"] = m_info(round(done[len(done) // 2], 2) if done else None, unit="s", desc="bona fide session, centred to done (median, s)")
    return metrics


def tracking_speed(ctx, rec: dict) -> dict:
    split = "dev"
    clips = [c for c in clips_of(split, True) if c.stem.startswith("bona_fide")][: 1 if ctx.quick else 3]
    repeats = min(ctx.repeats, 3)

    def once(cpu):
        out = {}
        for c in clips:
            r = subprocess.run(taskset(cpu) + face_cmd(rec) + ["liveness", str(c), json.dumps(LIVENESS_CONFIG)], capture_output=True, text=True, env=env1(), check=True)
            out[c.stem] = json.loads(r.stdout)["ms_median"]
        return out

    t = timed_runs(once, repeats)
    return {"face.speed.liveness_frame_ms": m_latency(t, desc=f"native, 1 thread, median of {repeats} runs: a liveness frame (detect when needed, mesh, "
                                                         "pose, quality, parallax, anti-spoofing / template on some frames), per-clip median")}


def run(ctx) -> dict:
    rec = shipped()
    metrics = {"face.shipped": m_info(rec, desc="the shipped recogniser and thresholds, read from the source")}
    if ctx.speed_only:
        return {**metrics, **tracking_speed(ctx, rec)}
    m, templates = lfw(ctx, rec)
    metrics.update(m)
    metrics.update(docpairs(ctx, rec, templates))
    metrics.update(celeba(ctx, rec))
    metrics.update(liveness(ctx, rec))
    metrics.update(tracking_speed(ctx, rec))
    return metrics
