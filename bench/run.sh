#!/bin/sh
# The benchmark harness: one entry point for every scanner.
#
#   bench/run.sh [--suite all|id|barcode|poa|face[,..]] [--split dev|test|both] [--quick]
#                [--e2e] [--no-wasm] [--no-cache] [--repeats N] [--jobs N] [--skip-prepare]
#
# Builds what is stale (the native release examples; the wasm builds unless
# --no-wasm), sets up the pinned Python environment, materialises and verifies
# every dataset against bench/manifests/, runs the metrics and writes
# bench/results/<git-sha>-<timestamp>.json. See bench/README.md; compare two
# results with bench/compare.py A.json B.json.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
export BENCH_DATA="${BENCH_DATA:-/tmp/docscan-bench}"
SUITE=all SPLIT=dev QUICK="" WASM=1 PREPARE=1
PASS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --suite) SUITE="$2"; PASS="$PASS --suite $2"; shift 2 ;;
    --split) SPLIT="$2"; PASS="$PASS --split $2"; shift 2 ;;
    --quick) QUICK=1; PASS="$PASS --quick"; shift ;;
    --no-wasm) WASM=""; PASS="$PASS --no-wasm"; shift ;;
    --skip-prepare) PREPARE=""; shift ;;
    --e2e|--no-cache|--speed-only) PASS="$PASS $1"; shift ;;
    --repeats|--jobs|--out) PASS="$PASS $1 $2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$BENCH_DATA"

# 1. The pinned Python environment (generators and scorers), outside the repo.
VENV="$BENCH_DATA/venv"
STAMP="$VENV/.requirements.sha256"
WANT=$(sha256sum "$HERE/requirements.txt" | cut -d' ' -f1)
if [ ! -x "$VENV/bin/python" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
  echo "== python environment ($VENV)" >&2
  [ -x "$VENV/bin/python" ] || uv venv -q --python 3.12 "$VENV"
  uv pip install -q --python "$VENV/bin/python" -r "$HERE/requirements.txt"
  echo "$WANT" > "$STAMP"
fi
PY="$VENV/bin/python"

# Builds in this worktree are serialised: two runs at once must not both run
# wasm-pack, which empties pkg/ before writing it.
exec 9>"$ROOT/docscan/.bench-build.lock"
flock 9

# 2. Models and native binaries (cargo rebuilds only what changed).
[ -s "$ROOT/models/text-detection.rten" ] || "$ROOT/scripts/fetch-models.sh"
echo "== native build (release examples)" >&2
(cd "$ROOT/docscan" && cargo build --release --examples --quiet)

# 3. The wasm builds, when stale (any source newer than the .wasm).
stale() { # stale <wasm file>
  [ ! -f "$1" ] && return 0
  [ -n "$(find "$ROOT/docscan/src" "$ROOT/docscan/Cargo.toml" "$ROOT/docscan/Cargo.lock" -newer "$1" -type f 2>/dev/null | head -1)" ]
}
if [ -n "$WASM" ]; then
  if stale "$ROOT/docscan/pkg/docscan_bg.wasm"; then
    echo "== wasm build (single-threaded)" >&2
    (cd "$ROOT/docscan" && RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --release --target web --out-dir pkg >&2)
  fi
  if [ -z "$QUICK" ] && [ -d "${RUSTUP_HOME:-/tmp/rustup-nightly}" ] && stale "$ROOT/docscan/pkg-threads/docscan_bg.wasm"; then
    echo "== wasm build (multithreaded, nightly)" >&2
    (cd "$ROOT/docscan" && ./build-threads.sh >&2) || echo "multithreaded wasm build failed; measuring the single-threaded build only" >&2
  fi
fi

flock -u 9

# 4. Datasets: present and matching their manifests, or regenerated.
if [ -n "$PREPARE" ]; then
  echo "== datasets" >&2
  "$PY" "$HERE/data/prepare.py" --suite "$SUITE" --split "$SPLIT"
fi

# 5. Measure.
cd "$ROOT"
# shellcheck disable=SC2086
exec "$PY" "$HERE/bench.py" $PASS
