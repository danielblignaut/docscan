# Native global exposure: parity, DEV outcome and cost

Harness for `docscan/src/exposure.rs`, the Rust port of the frozen
`global_exposure` arm (`../research_optics/global-contract-v1.json`). Findings,
the integration contract and the recommendation (explicit opt-in only):
[improvements-exposure.md](../../docs/improvements-exposure.md).

- `Cargo.toml`, `src/main.rs`: a dependency-free binary that includes
  `exposure.rs` by path, unchanged (`apply`, `time`, `table`).
- `wasm/`: the same file built for `wasm32-unknown-unknown` behind a raw ABI,
  driven by `wasm/run.mjs` in Node, for byte parity only.
- `tables.py`: regenerates the frozen inverse-sRGB, sRGB-encode and Gaussian
  tables in `exposure.rs` from the reference, checking monotonicity over every
  float32 in [0, 1].
- `evaluate.py` → `results-native-v1.json`: native and Python on every frozen
  DEV input, then fresh frozen-engine inference on every changed native output,
  scored with the unchanged scorers and denominators.
- `wasm_parity.py` → `wasm-parity-v1.json`: Python, native and wasm32
  (RGB and RGBA) byte and bit parity, DEV inputs and synthetic edge shapes.
- `timing.py` → `timing-native-v1.json`: in-process cost of `correct()` beside
  the Python arm. Run it alone on a quiet machine.

Same rules as `../research_optics`: only the authorized, already frozen DEV
inputs; no TEST; no data preparation; reports refuse overwrite; raw frames and
predictions stay in owner-private `/tmp/docscan-research-optics-native/`.
