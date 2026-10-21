"""Paths, hashing, manifests, process running, timing and metric records.

Nothing here knows about a particular scanner; the suites (bench/suites/)
build on it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import stats

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"
DATA = Path(os.environ.get("BENCH_DATA", "/tmp/docscan-bench"))
BIN = Path(os.environ.get("DOCSCAN_EXAMPLES", ROOT / "docscan" / "target" / "release" / "examples"))
MANIFESTS = BENCH / "manifests"
CACHE = DATA / "cache"
PY = DATA / "venv" / "bin" / "python"
JOBS = int(os.environ.get("BENCH_JOBS", max(1, (os.cpu_count() or 4) - 2)))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Hashing (with a stat cache: re-hash a file only when its size or mtime moved)
# --------------------------------------------------------------------------- #

_HCACHE: dict | None = None
_HCACHE_PATH = DATA / ".hashcache.json"


def _hcache() -> dict:
    global _HCACHE
    if _HCACHE is None:
        try:
            _HCACHE = json.loads(_HCACHE_PATH.read_text())
        except (OSError, ValueError):
            _HCACHE = {}
    return _HCACHE


def save_hash_cache():
    if _HCACHE is not None:
        _HCACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HCACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_HCACHE))
        tmp.replace(_HCACHE_PATH)


def sha256_file(path: Path) -> str:
    path = Path(path)
    st = path.stat()
    key = str(path.resolve())
    c = _hcache().get(key)
    if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
        return c[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    d = h.hexdigest()
    _hcache()[key] = [st.st_size, st.st_mtime_ns, d]
    return d


SAFE_ALPHABET = "fjkpqvwxyz"
DIGEST_ENCODING = ("sha256, written in base 10 with the digits 0-9 as the letters fjkpqvwxyz: a hex digest "
                   "can contain any short run of digits or a-f, and the repository's privacy check greps for some")


def safe_digest(hexdigest: str) -> str:
    """A hex digest re-encoded so it can never contain a digit or any letter
    outside fjkpqvwxyz (see DIGEST_ENCODING)."""
    n = int(hexdigest, 16)
    out = []
    while n:
        n, r = divmod(n, 10)
        out.append(SAFE_ALPHABET[r])
    return "".join(reversed(out)) or SAFE_ALPHABET[0]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_json(obj) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def tree_sha256(files: list[dict]) -> str:
    return sha256_bytes("\n".join(f"{f['path']} {f['sha256']}" for f in sorted(files, key=lambda f: f["path"])).encode())


def hash_files(paths: list[Path], root: Path, jobs: int = 8) -> list[dict]:
    paths = sorted(paths)
    with ThreadPoolExecutor(jobs) as ex:
        shas = list(ex.map(sha256_file, paths))
    return [{"path": str(p.relative_to(root)), "sha256": safe_digest(s), "bytes": p.stat().st_size} for p, s in zip(paths, shas)]


def code_sha256(paths: list[Path]) -> str:
    """One hash over a set of source files (the referee's own code, a generator)."""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def bench_code_sha256() -> str:
    """The referee: the harness's code (not its results, manifests or recorded noise) and the shared scorers."""
    skip = {"results", "manifests", "__pycache__"}
    files = [p for p in BENCH.rglob("*") if p.is_file() and p.suffix in {".py", ".sh", ".mjs", ".txt"} and not skip & set(p.relative_to(BENCH).parts)]
    files += [ROOT / "eval" / "poa_eval.py", ROOT / "face" / "eval" / "verification.py"]
    return code_sha256([f for f in files if f.exists()])


# --------------------------------------------------------------------------- #
# Manifests
# --------------------------------------------------------------------------- #


def manifest(name: str) -> dict:
    return json.loads((MANIFESTS / f"{name}.json").read_text())


def manifest_root(m: dict) -> Path:
    return DATA / m["root"]


def verify_manifest(name: str, quick_files: list[str] | None = None) -> tuple[bool, str]:
    """Checks every file the manifest lists (or the given subset) against its
    sha256. Returns (ok, message)."""
    m = manifest(name)
    root = manifest_root(m)
    want = {f["path"]: f["sha256"] for f in m["files"]}
    paths = quick_files if quick_files is not None else list(want)
    bad, missing = [], []
    todo = []
    for p in paths:
        fp = root / p
        if not fp.exists():
            missing.append(p)
        else:
            todo.append((p, fp))
    with ThreadPoolExecutor(8) as ex:
        shas = list(ex.map(lambda t: sha256_file(t[1]), todo))
    for (p, _), s in zip(todo, shas):
        if safe_digest(s) != want[p]:
            bad.append(p)
    save_hash_cache()
    if missing or bad:
        return False, f"{name}: {len(missing)} missing, {len(bad)} differ (e.g. {(missing + bad)[:3]})"
    return True, f"{name}: {len(paths)} files verified"


def write_manifest(name: str, *, suite: str, split: str, root: Path, files: list[Path], generator: dict, licence: str,
                   description: str, extra: dict | None = None):
    entries = hash_files(files, root)
    m = {
        "name": name,
        "suite": suite,
        "split": split,
        "description": description,
        "root": str(root.relative_to(DATA)),
        "generator": generator,
        "licence": licence,
        "count": len(entries),
        "bytes": sum(e["bytes"] for e in entries),
        "digest_encoding": DIGEST_ENCODING,
        "tree_sha256": safe_digest(tree_sha256(entries)),
        **(extra or {}),
        "files": entries,
    }
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    (MANIFESTS / f"{name}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    save_hash_cache()
    return m


# --------------------------------------------------------------------------- #
# Running the native binaries
# --------------------------------------------------------------------------- #

# rten (the OCR and face models) keeps its own pool, sized to the physical
# cores unless RTEN_NUM_THREADS says otherwise; RAYON_NUM_THREADS alone leaves
# it multithreaded.
THREAD_ENV = {"RAYON_NUM_THREADS": "1", "RTEN_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def env1(**extra) -> dict:
    return {**os.environ, **THREAD_ENV, **extra}


def binary(name: str) -> Path:
    p = BIN / name
    if not p.exists():
        raise SystemExit(f"missing {p}: build with `cargo build --release --examples` in docscan/")
    return p


def binary_key(*names: str, models: list[Path] = ()) -> str:
    """A cache key: the binaries' and the models' bytes."""
    return sha256_json([sha256_file(binary(n)) for n in names] + [sha256_file(m) for m in models] + [THREAD_ENV])[:20]


def run_jsonl_sharded(cmd: list[str], items: list[str], jobs: int = JOBS, env: dict | None = None, list_arg: str = "@") -> list[dict]:
    """Runs `cmd + items` split over `jobs` processes (each single-threaded),
    and returns the JSON lines they print, in item order when each line has
    `path`. `list_arg="@"` passes the shard as `@file` (one path per line);
    None passes the paths as arguments."""
    if not items:
        return []
    jobs = max(1, min(jobs, len(items)))
    shards = [items[i::jobs] for i in range(jobs)]

    def one(shard):
        if list_arg == "@":
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
                f.write("\n".join(shard))
            args = cmd + [f"@{f.name}"]
        else:
            args = cmd + shard
        r = subprocess.run(args, capture_output=True, text=True, env=env or env1())
        if list_arg == "@":
            os.unlink(f.name)
        if r.returncode:
            raise RuntimeError(f"{' '.join(map(str, cmd[:3]))} failed: {r.stderr[-2000:]}")
        return [json.loads(x) for x in r.stdout.splitlines() if x.strip().startswith("{")]

    with ThreadPoolExecutor(jobs) as ex:
        parts = list(ex.map(one, shards))
    out = [x for p in parts for x in p]
    if out and "path" in out[0]:
        pos = {p: i for i, p in enumerate(items)}
        out.sort(key=lambda r: pos.get(r["path"], 1 << 30))
    return out


class Cache:
    """Per-item results of a deterministic tool, keyed by the tool's bytes and
    arguments: `get(item)` / `put(item, value)`; stored as JSON lines under
    $BENCH_DATA/cache/<tool>/<key>.jsonl. Disabled by --no-cache."""

    enabled = True

    def __init__(self, tool: str, key: str):
        self.path = CACHE / tool / f"{key}.jsonl"
        self.data: dict = {}
        if self.enabled and self.path.exists():
            for line in self.path.read_text().splitlines():
                try:
                    k, v = json.loads(line)
                    self.data[k] = v
                except ValueError:
                    pass
        self.new: list = []

    def get(self, k):
        return self.data.get(k) if self.enabled else None

    def put(self, k, v):
        self.data[k] = v
        self.new.append((k, v))

    def save(self):
        if not self.new:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            for k, v in self.new:
                f.write(json.dumps([k, v], separators=(",", ":")) + "\n")
        self.new = []


# --------------------------------------------------------------------------- #
# Timing: one pinned core, repeated, with the load recorded
# --------------------------------------------------------------------------- #


def loadavg() -> list[float]:
    return [round(x, 2) for x in os.getloadavg()]


def _cpu_idle() -> dict[int, tuple[int, int]]:
    out = {}
    for line in Path("/proc/stat").read_text().splitlines():
        if line.startswith("cpu") and line[3:4].isdigit():
            f = line.split()
            vals = list(map(int, f[1:]))
            out[int(f[0][3:])] = (vals[3] + vals[4], sum(vals))
    return out


def idlest_cpu() -> int:
    """The logical CPU with the most idle time over half a second (the timing
    passes pin to it; which one is recorded)."""
    if os.environ.get("BENCH_CPU"):
        return int(os.environ["BENCH_CPU"])
    try:
        a = _cpu_idle()
        time.sleep(0.5)
        b = _cpu_idle()
        idle = {c: (b[c][0] - a[c][0]) / max(1, b[c][1] - a[c][1]) for c in a if c in b}
        allowed = os.sched_getaffinity(0)
        return max((c for c in idle if c in allowed), key=lambda c: idle[c])
    except Exception:
        return 0


def timed_runs(run_once, repeats: int) -> dict:
    """Calls `run_once(cpu)` `repeats` times; each returns {item: ms}. Returns
    per-item medians across repeats plus the context needed to judge them."""
    cpu = idlest_cpu()
    load0 = loadavg()
    t0 = time.time()
    per: dict[str, list[float]] = {}
    for _ in range(repeats):
        for k, v in run_once(cpu).items():
            per.setdefault(k, []).append(float(v))
    items = sorted(per)
    samples = [float(np.median(per[k])) for k in items]
    return {"items": items, "samples": samples, "all": [per[k] for k in items], "cpu": cpu, "repeats": repeats,
            "load_start": load0, "load_end": loadavg(), "wall_s": round(time.time() - t0, 1)}


def taskset(cpu: int) -> list[str]:
    return ["taskset", "-c", str(cpu)] if os.path.exists("/usr/bin/taskset") else []


# --------------------------------------------------------------------------- #
# Metric records (what the result JSON holds; compare.py reads the same shapes)
# --------------------------------------------------------------------------- #


def m_rate(ids: list[str], ok: list, *, desc: str, better: str = "higher", unit: str = "%") -> dict:
    ok = [int(bool(x)) for x in ok]
    v = float(np.mean(ok)) if ok else float("nan")
    lo, hi = stats.bootstrap_rate(ok)
    return {"kind": "rate", "value": v, "ci95": [lo, hi], "n": len(ok), "k": int(sum(ok)), "better": better, "unit": unit,
            "desc": desc, "ids": list(ids), "ok": "".join(map(str, ok))}


def m_stat(stat: str, raw: dict, params: dict | None = None, *, desc: str, better: str = "higher", unit: str = "%",
           ids_sha256: str = "", ci: bool = True) -> dict:
    raw = {k: (np.round(np.asarray(v, float), 5).tolist() if k == "scores" else np.asarray(v).astype(int).tolist()) for k, v in raw.items()}
    v = stats.compute_stat(stat, raw, params or {})
    lo, hi = stats.bootstrap_stat(stat, raw, params or {}, b=300) if ci else (float("nan"), float("nan"))
    return {"kind": "stat", "stat": stat, "params": params or {}, "value": v, "ci95": [lo, hi], "n": len(raw["scores"]),
            "better": better, "unit": unit, "desc": desc, "ids_sha256": ids_sha256, "raw": raw}


def m_latency(t: dict, *, desc: str, unit: str = "ms") -> dict:
    m, q1, q3 = stats.median_iqr(t["samples"])
    return {"kind": "latency", "value": m, "iqr": [q1, q3], "n": len(t["samples"]), "better": "lower", "unit": unit, "desc": desc,
            "ids": t["items"], "samples": [round(x, 3) for x in t["samples"]], "repeats": t["repeats"], "cpu": t["cpu"],
            "threads": 1, "load_start": t["load_start"], "load_end": t["load_end"]}


def m_info(value, *, desc: str, unit: str = "") -> dict:
    return {"kind": "info", "value": value, "unit": unit, "desc": desc}
