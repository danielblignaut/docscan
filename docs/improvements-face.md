# Face: improvement log (DEV only)

Each row: the idea, the change, what it measured on DEV (the `bench/` face
suite, judged with `bench/compare.py` against the reference run; plus the
DEV-only exploration scripts where the bench has no metric), and whether it
was kept. TEST is run once at the end. The research behind the ideas is in
`docs/research-face.md`.

## Reference

**Current reference (2026-10-22):** `bench/run.sh --suite face` on DEV at
`5196114` (origin/main after the harness baseline), result
`bench/results/5196114514-20261022T164033Z.json` (not committed; copy in
`/tmp/docscan-face-work/REF2.json`). Same accuracy as the first reference
below; native liveness frame 81 ms (IQR 79–84; the machine was less loaded
than on 2026-10-21), wasm single-threaded `face_track_ms` 86.5 ms.

First reference (2026-10-21), `589ad5f`, load 38 → 58:

| Metric | Reference DEV |
|---|---|
| LFW acc10 / TAR@1e-3 / TAR at shipped / FAR at shipped | 99.63% / 99.41% / 99.41% / 0.06% |
| Doc photo TAR@1e-3 / TAR@1e-2 / TAR at DOC_THRESHOLD / FAR | 98.46% / 99.05% / 98.46% / 0.06% |
| CelebA-Spoof AUC / ACER@0.5 / APCER / BPCER | 85.76% / 21.62% / 32.66% / 10.58% |
| Liveness BPCER / APCER (every species) | 3.33% (1/30) / 0% |
| Native liveness frame (median, loaded machine) | 201 ms |

(In that run the single-threaded wasm timing failed with a 404 and a
900 s timeout, a harness problem since fixed on main.)

## Log

| # | Date | Idea | Change | DEV delta | Kept |
|---|---|---|---|---|---|
| 1 | 2026-10-21 | Speed: parallax search without per-candidate allocations; grey image only over the window the searches sample | `parallax.rs` (commit `afa9a1d`) | Results identical (a DEV clip's parallax values equal to 1e-7; 3-D motion score 0.0928623 vs 0.0928624). Parallax measure time −30% (probe on a loaded machine: 390 → 275 ms-equivalents per call, vs `observe` ≈ 180). The bench's median frame time is dominated by frames without a parallax measure, so it is not expected to move much. | yes (bench confirmation pending, see below) |
| 2 | 2026-10-21 | FAS: crop box scale and calibrated decision | `antispoof.rs`: mesh box × 0.55 before the 2.7×/4.0× crops; live probability shifted in log-odds so the CelebA-Spoof DEV equal-error point (raw 0.78) is 0.5 (commit `f372425`) | Exploration (onnxruntime, same crops): AUC 0.859 → 0.910 (bootstrap CI of the gain [0.044, 0.061]); ACER at the DEV EER threshold 16.8% (vs 21.7% at 0.5 before). Liveness DEV with box 0.55 (rten, every frame): bona fide lowest sampled live probability ≥ 0.94 (completed sessions), screen replays ≤ 0.42 (9/10 ≤ 0.09), all 10 rejected; BPCER unchanged (the same 1/30 over-exposed clip). **Full bench run not finished (paused).** | pending bench |
| 2b | 2026-10-22 | The first bench verdict on row 2 | `a704a61` vs the 2026-10-22 reference: `bench/results/a704a61f33-20261022T220922Z.json` | AUC 85.76 → **90.77%** (+5.01 pt, CI [+4.09, +5.98]); ACER 21.62 → 16.59% (CI of the change [−6.32, −3.60]); APCER 32.66 → 16.61%; but **BPCER 10.58 → 16.57% (CI [+3.93, +8.15]): verdict `regressed`**. Moving 0.5 to the equal-error point trades genuine rejections for attacks, which the regression rule rightly refuses. | revised (row 3) |
| 3 | 2026-10-23 | Calibrate at the reference's BPCER instead of the EER; let the liveness session keep the EER operating point | `antispoof.rs`: 0.5 at raw 0.59, where DEV BPCER equals the uncalibrated model's at 0.5 (10.5% vs 10.6%; exploration APCER 24.0%); `SESSION_RAW_THRESHOLD` 0.78 (the EER) becomes the session's default `min_antispoof` (0.711 calibrated), so the liveness runs below are unchanged by the recalibration | see the final bench row | pending bench |
| 4 | 2026-10-22 | **Passive anti-spoofing across poses** (patent-clear; the coordinator's mechanism 4) | `liveness.rs`: anti-spoofing sampled every 250 ms over the whole sweep and finish (every pose, not only near-frontal frames), decided on the 10th percentile of the samples instead of the lowest near-frontal one (`antispoof_all_poses`, `antispoof_quantile`) | DEV clips (80) and an extra DEV-only set with fresh seeds (`clips_x`, 90 clips: 30 bona fide, 30 curved prints, 15 prints, 10 screens, 5 2-D videos), with the 3-D check off: bona fide decision score ≥ **0.801** (60 completed sessions), completed curved prints ≤ **0.378** (19 of 20), screens ≤ 0.010; the one exception, DEV `curved_photo_1208` (0.932, a print the model thinks live), is stopped by continuity. With the old frontal-minimum rule and no 3-D check, two `clips_x` curved prints (frontal minimum 0.519 and 0.681) would have passed. APCER 0/100 attacks, BPCER 1/60 (the over-exposed clip that never completes, as before). | yes |
| 5 | 2026-10-23 | **3-D motion check off by default** (patent review) | `planar_parallax` config, `PLANAR_PARALLAX_DEFAULT = false`; the homography-residual code stays, research-only (`face/PATENTS.md` § 1) | With row 4, no DEV or `clips_x` attack passes without it. Cost: the 3-D check was a second, physical line against prints the passive model believes (DEV `curved_photo_1208`), so a real print that fools MiniFASNet now meets only the ring, continuity and identity. Native frame median on the clips drops (no parallax measure): see the final bench row. | yes (flagged) |
| 6 | 2026-10-22 | **Self-occlusion / visibility** probe (patent-clear candidate; mechanism 1) | DEV-only probe (outside the repo): per turned frame, whether each frontal texture patch is still found near its landmark (local affine from the 10 nearest landmarks, search 0.16 IOD); points the mesh itself predicts hidden behind a nearer triangle compared with the rest | Visibility asymmetry correlated with the turn equally for a head and a curved print (+0.79 vs +0.81: foreshortening dominates at 20–28°). Mesh-predicted hidden points: texture still found 63–73% (heads) vs 62–87% (curved prints), per-frame gap upper-median 0.35–0.41 vs 0.26–0.40: overlapping. Not separating on these clips. | no |
| 7 | 2026-10-22 | "Model-consistent parallax" (measured residual field vs a fitted rigid head model's) | WIP code | dropped before measurement: reads on IBM US9898674 (conformance to a 3-D surface model) | no |
| 8 | 2026-10-23 | **Bench verdict for rows 1, 3, 4, 5 together** | `56aab32` vs the 2026-10-22 reference: `bench/results/56aab32a6f-20261022T232516Z.json` | **verdict `improved`**: CelebA-Spoof AUC 85.76 → **90.77%** (+5.01 pt, CI [+4.09, +5.98]); ACER 21.62 → **17.32%** (CI [−5.53, −3.10]); APCER 32.66 → **24.43%** (CI [−9.86, −6.37]); BPCER 10.58 → 10.21% (unchanged within CI). Liveness DEV unchanged: BPCER 1/30, APCER 0/50 for every species. LFW and document metrics identical. Native liveness frame **81 → 51 ms**; interleaved A/B (`bench/speed_ab.py --ref 5196114 --suite face`, `bench/results/speedab-51b4f8488a-vs-5196114514-20261023T000707Z.json`): **68 → 51 ms, −32.1% (CI [−33.8%, −21.1%])**, the parallax measure no longer running. wasm `face_track_ms` 86.5 → 85.1 ms (tracking alone, not the session: unchanged as expected). | yes |
| 9 | 2026-10-23 | Document-photo normalisation (DEV probe, same pipeline as `embed --largest`) | flip averaging; doc greyscale; live greyscale; de-halftone Gaussian blur σ 0.7 / 1.0 | TAR@1e-3 / @1e-2 (base 98.46 / 99.05%): flip 98.46 / 99.17; doc grey 98.22 / 98.69; both grey 98.10 / 99.05; live grey only 97.98 / 99.29; blur 0.7 97.98 / 99.05; blur 1.0 97.98 / 98.93. All within one or two pairs of the 842 genuine ones (the set is near its ceiling: 13 misses) or worse. | no |
| — | 2026-10-21 | FAS variants explored, not chosen | flip averaging; box 0.45/0.7/0.85; the detector's box; one model alone; multi-scale averages | flip: AUC +0.0016 (CI [−0.0002, 0.0035], not significant; doubles FAS cost); 0.45: AUC 0.902; 0.7: 0.894; detector box: 0.854; V2 alone 0.898, V1SE alone 0.885 (box 0.55); 0.55+0.7 averaged 0.910 | no |

### Exploration numbers behind row 2 (CelebA-Spoof DEV, 3 000 images, 1 068 live)

| Crop | AUC | ACER at 0.5 | best ACER (threshold) |
|---|---|---|---|
| mesh box × 1.0 (before) | 0.859 | 21.7% | 21.3% (0.56) |
| × 0.85 | 0.875 | 21.0% | 19.6% (0.71) |
| × 0.7 | 0.894 | 20.8% | 17.9% (0.88) |
| **× 0.55 (chosen)** | **0.910** | 19.0% | **16.2% (0.72); EER at 0.78** |
| × 0.45 | 0.902 | 17.7% | 17.3% (0.51) |
| BlazeFace box × 1.0 | 0.854 | 21.9% | 21.6% |

## Next

1. Bench rows 1, 3, 4, 5 together on DEV against the 2026-10-22 reference;
   speed with `bench/speed_ab.py`; merge if the verdict holds.
2. Document-photo variants (flip in the measured path, grey matching,
   de-halftone), then retune `DOC_THRESHOLD` on DEV if templates change.
3. Template aggregation / quality-aware frame choice for the liveness
   template.
4. TEST once, at the end.
