# Liveness under production conditions

FARO Connect runs the face check twice: on the phone (the wasm engine, whatever
frames it has time for) and again on its server, which replays the frames the
phone uploaded (one every 100 ms, JPEG, at most 640 pixels) with its own
configuration (nine of twelve segments, a blink required). Docscan is advisory
there; TransUnion's liveness decides the sale. From 26 October to 6 November
2026, Connect recorded 12 server replays in production and 14 in dev:

| What failed (server replay) | Prod | Dev |
| --- | --- | --- |
| `blink`: none counted | 2 | 4 |
| Not completed: the ring short on the replay (threshold 1.0 then), so `identity` scored 0 | 4 | 2 |
| `antispoof`: 10th percentile 0.433 and 0.540 (means 0.70, 0.80), 0.709 in dev | 2 | 1 |
| `continuity`: 2 several-face frames (dev); a 5.9 s gap, a jump and 3 several-face frames (prod) | 1 | 1 |
| Engine never loaded: a 2 s plain selfie | 1 | 0 |

Every customer TransUnion answered for was approved (8 in prod); passing
replays scored the passive model at 0.86–0.998. On the phone, 9 of 20 runs
counted no blink. Only scores and metadata were used; no image was viewed.

The bench's liveness suite runs the synthetic clips at 30 fps with every
frame analysed, where a blink is never missed between frames. `run.py`
replays the same DEV clips under Connect's conditions:

| Condition | Frames | Config |
| --- | --- | --- |
| `server` | every 3rd of 30 fps (10 fps), JPEG 85 | coverage 0.75, blink required, identity 0.366 |
| `server_dim` | the same, every frame's luma × 0.55 plus sensor noise | the same |
| `browser` | every 7th (about 4 fps), JPEG 92 | coverage 0.75, no blink required |
| `native30` | every frame, 30 fps | the server's |

```sh
cd docscan && cargo build --release --example face
/tmp/docscan-bench/venv/bin/python experiments/face_liveness_robust/run.py run --cond server
/tmp/docscan-bench/venv/bin/python experiments/face_liveness_robust/run.py score --cond server
```

Skin tone is the clip generator's (nine tones, `face/synth/head.py`), in three
bands of three; the blinks are its rendered ones (four frames, 133 ms) before
the session finished. The clips do not answer "Blink your eyes": 12 of the 30
bona fide clips never blink and cannot pass a session that requires one, so
BPCER is also given over the 18 that do.

## Results (DEV; `results/`)

| | `server` before → after | `server_dim` before → after | `browser` | `native30` |
| --- | --- | --- | --- | --- |
| BPCER, clips that blink | 11/18 → **3/18** | 16/18 → **9/18** | 2/18 → 2/18 | 0/18 → 0/18 |
| BPCER, all bona fide | 23/30 → 15/30 | 28/30 → 21/30 | 3/30 → 3/30 | 1/30 → 1/30 |
| Blink recall | 7/18 → **15/18** | 5/18 → **15/18** | 3/18 → 5/18 | 7/18 → 17/18 |
| Blink recall, darkest band | 2/4 → 3/4 | 0/4 → 3/4 | 0/4 → 0/4 | 2/4 → 4/4 |
| `antispoof` failures (bona fide) | 1 → 1 | 23 → **8** | 1 → 1 | 1 → 1 |
| Flat attacks counting a blink | 3/35 → 2/35 | 3/35 → 0/35 | 2/35 → 2/35 | 6/35 → 8/35 |
| APCER, every species | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |

TEST (run once, after tuning; `results/test-*.json`): see the bottom of this file.

## Why

- **Blinks** were counted only near frontal (12°), against the centring frames'
  eye aspect ratio, which leaves under a second of a session to blink in, and
  at 10 fps the closing often falls between frames. The ratio is now judged
  against the person's own open eyes of the last 1.5 s, at any pose up to 45°,
  which follows the pose and the face; a dip must recover within 300 ms with
  the head turning at most 20°, which a print tilted or a slow change of pose
  does not do. When a blink is required and none has been seen, the finish
  asks for one instead of ending a session that cannot pass.
- **Anti-spoofing** in a dim room dips on turned frames, not frontal ones
  (DEV dim, lower quartile per 10° of turn: frontal 0.98, 20–40° 0.54–0.68,
  lowest for the darkest band). The 10th percentile at the equal-error point
  (0.711) failed 23 of 30 dim sessions. The median fails fewer, but lets a
  screen replay through (0.72 at 10 fps): rejected. The lower quartile at the
  calibrated balanced point (0.5) keeps every screen replay's quartile at or
  under 0.053 in every condition. Brightening the face before the model (gain
  to luma 110, at most 2.5×) did not help: it is the noise, not the level.
- **Coverage**: a segment skipped between two consecutive lit frames (a fast
  turn at 10 fps, or the phone's slower engine) is lit. Each lit frame still
  needs the full 14°, so a tilted print's ~10° gains nothing.
- **Continuity**: a bystander's face, far smaller than the customer's, no
  longer counts as a second face (in centring or in continuity).

## Not fixed here

- **Darkest skin in a dim room** still fails more often (DEV dim, darkest band
  7/8 vs light 9/13): three never pass centring ("Find better light", a face
  luma under 45), and the passive model still doubts some turned frames. Light
  in the store matters more than any threshold here.
- **Face match "unavailable"** (4 of 23 comparisons): the verifier
  requires exactly one face on each image. Which image had none or two is not
  logged. Counting a document's smaller faces away was rejected: a larger
  face behind a held-up card would then be the one compared.
- **Engine load**: the face models are 18.7 MB and the wasm 7 MB. Identity
  needs SFace templates from the centring frames, so the recogniser cannot
  yet load after the session starts without changing what the phone and the
  server compute.

## TEST

Run once after tuning (logged in `bench/results/TEST_ACCESS.log`): 40 bona fide
clips (24 that blink) and 70 attacks.

| | `server` before → after | `server_dim` before → after |
| --- | --- | --- |
| BPCER, clips that blink | 17/24 → **2/24** | 22/24 → **6/24** |
| BPCER, all bona fide | 33/40 → 18/40 | 38/40 → 22/40 |
| Blink recall | 7/24 → **22/24** | 7/24 → **22/24** |
| Blink recall, darkest band | 0/5 → 5/5 | 0/5 → 4/5 |
| `antispoof` failures (bona fide) | 1 → 0 | 27 → **10** |
| Flat attacks counting a blink | 10/45 → 6/45 | 8/45 → 7/45 |
| APCER, every species | 0 → 0 | 0 → 0 |

All 18 remaining `server` failures are a blink not seen: 16 clips that never blink, 2 whose blinks were missed.
