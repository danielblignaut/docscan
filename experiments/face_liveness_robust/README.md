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
- **Face match "unavailable"**: fixed, see "The real sequences" below.
- **Engine load**: the face models are 18.7 MB and the wasm 7 MB. Identity
  needs SFace templates from the centring frames, so the recogniser cannot
  yet load after the session starts without changing what the phone and the
  server compute.

## The real sequences

The 26 face sequences Connect retained (12 prod, 14 dev, 26 October to 6
November 2026) were replayed with the account owner's permission, on one
machine, through a copy of Connect's verifier (`native/docscan-verifier`: its
decoding, its policy of nine segments, a blink required and identity 0.366,
guide `[0.5, 0.5, 0.25]`, mirrored), at the engine Connect pins (`0526c5d`), at
`46cd6e1` (the changes above) and at this change. Ground truth for a genuine
person is TransUnion's liveness answer on the same capture: it passed 9 prod
and 1 dev customer; it answered with an error for one in each, and was not
asked for the rest (dev is mostly staff tests). Only counts and scores leave
that machine; no image was viewed or kept outside it. Replaying the old pin
reproduces Connect's stored scores wherever the policy has not changed since
(the earliest receipts were recorded at coverage 1.0).

| Server replay passes | Prod, TransUnion passed (9) | Prod, others (3) | Dev, TransUnion passed (1) | Dev, others (13) |
| --- | --- | --- | --- | --- |
| As recorded then | 4 | 1 | 1 | 7 |
| `0526c5d`, today's policy | 6 | 2 | 1 | 8 |
| `46cd6e1` | 8 | 2 | 1 | 11 |
| **This change** | **8** | 2 | 1 | **12** |

| Failed check, `0526c5d` → `46cd6e1` → this change | Prod | Dev |
| --- | --- | --- |
| `blink` | 3 → 0 → 0 | 4 → 1 → 1 |
| `antispoof` | 2 → 0 → 0 | 1 → 0 → 0 |
| `continuity` | 1 → 1 → 1 | 1 → 1 → **0** |
| not completed (a 2 s plain selfie, no engine on the phone) | 1 → 1 → 1 | 0 → 0 → 0 |

Scores on the completed genuine replays at this change: 3-D motion
0.064–0.111 (threshold 0.06: a thin margin, the one to watch), lower-quartile
live probability 0.564–0.999 (0.5), identity 0.783–0.970 (0.366), one to seven
blinks. What still fails:

- **Prod, TransUnion passed, `continuity`**: the landmark model loses the face
  for 5.7 s mid-sweep (the detector still boxes something on most frames,
  but the landmark model finds no face in any of the boxes), with two jumps. This is no
  evidence for 5.7 s, which is exactly what continuity refuses; not loosened.
  Its three "several faces" frames were detector false alarms (below) and are
  gone.
- **Dev, `blink`**: the person blinked once, looking up 28°, and the eyes came
  back to 0.81 of the open baseline within 300 ms (0.85 needed). Every
  variant that counts it (open at 0.80 or 0.75, 400–500 ms, or the last open
  frame as the baseline) also counts more blinks on flat attacks (DEV `server`
  2/35 → 4–13/35): not changed. The phone did not ask for a blink (Connect's
  browser config has `require_blink: false`); once it does, "Blink your eyes"
  holds the finish until one is seen.
- **Prod, not completed**: a 2 s plain selfie; it cannot sweep a ring.

### What changed

- **A face is a face the landmark model confirms.** In each continuity
  failure above the detector boxed something the landmark model, run on that
  box, finds no face in (presence ≤ 0.10 against 0.90–1.00 for the real face):
  a box below the chin on a turned head, a larger box half over the face.
  A frame's `faces` now counts only confirmed detections, a box overlapping the
  tracked face (IoU ≥ 0.3) being that face, still only those at least half the
  largest's width. When the face is lost, the most prominent *confirmed*
  detection is tracked, not the most prominent box.
- **Overlapping detector tiles give one box per face.** A still with a small
  face (a document) is searched in overlapping tiles, each finding the same
  face; the boxes were concatenated, so a document with one face reported two
  or four (IoU 0.88–0.96) and the comparison was "unavailable". They are now
  merged by the detector's own weighted suppression.
- **A photo on its side is turned.** With no confirmed face upright, `photo`
  tries the image turned a quarter each way, then upside down
  (`PhotoFace.rotation`). The other two "unavailable" documents were cards
  photographed sideways: the detector boxed something else upright, which the
  landmark model rejected. A photo still counts *every* confirmed face, of any
  size: a card held up in front of a larger face must not be compared as that
  face.

Face match on the same captures (document photo against the selfie,
threshold 0.356): "unavailable" 3/10 prod and 1/12 dev → **0**; all four now
compare at 0.52–0.61; the other 18 comparisons are unchanged to 1e-3.

On the synthetic DEV clips, every condition above: APCER 0 and BPCER
unchanged. Seven attack runs changed, each losing a one-frame "several faces"
(one is allowed, so it never decided anything) and one print lighting 5
segments instead of 4; all are still rejected. The face bench (`bench/run.sh
--suite face`) reports no change.

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
