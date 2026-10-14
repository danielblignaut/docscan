#!/bin/sh
# The multithreaded wasm build, into pkg-threads/. Needs a nightly with
# rust-src; by default the one installed under /tmp so the user's own
# toolchains are untouched:
#   RUSTUP_HOME=/tmp/rustup-nightly CARGO_HOME=/tmp/cargo-nightly rustup-init --default-toolchain nightly -c rust-src -t wasm32-unknown-unknown
set -eu
cd "$(dirname "$0")"
export RUSTUP_HOME="${RUSTUP_HOME:-/tmp/rustup-nightly}"
export CARGO_HOME="${CARGO_HOME:-/tmp/cargo-nightly}"
export PATH="$CARGO_HOME/bin:$PATH"
export RUSTUP_TOOLCHAIN=nightly
export CARGO_TARGET_DIR=/tmp/docscan-threads-target
# Atomics alone no longer make the linker emit a shared, imported memory, nor
# export the TLS symbols wasm-bindgen's thread start-up needs: ask for them.
# Shared memory needs a declared maximum; the OCR models and a few frames fit in 2 GiB.
export RUSTFLAGS="-C target-feature=+atomics,+bulk-memory,+simd128 \
  -C link-arg=--shared-memory -C link-arg=--import-memory -C link-arg=--max-memory=2147483648 \
  -C link-arg=--export=__wasm_init_tls -C link-arg=--export=__tls_size \
  -C link-arg=--export=__tls_align -C link-arg=--export=__tls_base"
exec wasm-pack build --release --target web --out-dir pkg-threads --out-name docscan \
  -- --features threads -Z build-std=panic_abort,std
