# Public face evaluation loop

This is a separate **research-only evaluation**, not a commercial face-training
corpus. Only aggregate reports and programs belong in git. Photos, derived
portraits, identity-indexed scores, and embeddings stay owner-private under
`/tmp/docscan-public-data/face-london` and must not be published.

Source: [Face Research Lab London Set v5](https://doi.org/10.6084/m9.figshare.5047666.v5),
DeBruine, Lisa; Jones, Benedict (2017), CC BY 4.0. The downloader takes only
102 neutral and 102 smiling front photographs from [the author's repository](https://github.com/debruine/webmorphR.stim/tree/fa8b78fda2d659bb74ce62fcd99c4407551d2a77),
pinned by git revision and blob hash, then records SHA-256 per image. The
Figshare API returned HTTP 403 on this machine. This author-maintained release
is publicly accessible without registration or a signed agreement. The source
README documents participant consent for research using original and altered
images. Copyright permissions do not establish consent for commercial biometric
training. No weights or shipped thresholds may be learned from this experiment.

```sh
python3 experiments/public_face/fetch.py
/tmp/docscan-bench/venv/bin/python experiments/public_face/evaluate.py \
  --binary /path/to/release/examples/face --variant iris --jobs 2 \
  --report experiments/public_face/results/baseline.json
```

The versioned referee first hashes identities to split 51 calibration / 51
validation subjects. All poses and derived media of a person remain in one
split; neither split is the repository's TEST lockbox. No model is trained.
Each neutral portrait is compared with all smiling portraits in its split:
51 genuine and 2,550 impostor pairs. Thresholds at empirical FAR 0.001 and
0.01 are chosen only on calibration identities, then frozen for validation.
Missing faces are rejections, never removed from the denominator. Report both
TAR and actual FAR; the impostor pairs share identities and are dependent.
This tiny dataset cannot certify a 0.001 population false-match rate.

Three predeclared conditions: original, grayscale 384-pixel JPEG with mild blur,
and grayscale 192-pixel JPEG with stronger blur/compression. These are printed
portrait stress proxies, not real captured documents. Single session/source;
there is no device, source, or age generalization evidence. Ablations use the
existing native flags (`flip`, `contour`, `nose4`, `inner-mouth`) and remain
unshipped unless independently justified with eligible data and regression checks.

## Liveness acquisition findings (23 October 2026)

- [WFAS official rules](https://github.com/deepinsight/insightface/blob/master/challenges/cvpr23-fas-wild/README.md):
  academic-only; download requires a signed agreement by email. Not acquired.
  The paper's statement about Creative Commons source photos is not a grant to
  commercially use the released corpus.
- [SynthASpoof official license](https://github.com/meilfang/SynthASpoof):
  CC BY-NC-SA, expressly excludes product development; requires access request.
  Not acquired. Synthetic images do not remove those restrictions.
- [CelebA-Spoof official terms](https://mmlab.ie.cuhk.edu.hk/projects/CelebA/CelebA_Spoof.html):
  noncommercial research only and no redistribution. Existing legacy DEV
  observations do not establish permission to train commercial weights.
- FRLL has no spoof attacks or videos. APCER, APCER at fixed BPCER, and real
  active-liveness effectiveness **cannot be estimated** from these portraits.
  Do not relabel a manipulated photo as evidence of a real presentation attack.

The existing procedural liveness DEV remains available to detect regressions,
with physical parallax enabled. The next external PAD benchmark needs an
explicitly authorized consented attack collection with identity, device and
attack-type metadata, or a dataset whose official terms actually permit the
intended use. No access gates are bypassed and no author is contacted here.

## Owner-provided replay preview

The [Axon Labs public display-replay preview](https://huggingface.co/datasets/AxonData/Display_replay_attacks/tree/f5560f659e185ded62c2f09ff502426b0588406e)
contains five genuine selfies and five real replay videos (164 MB), with a
CC BY 4.0 dataset-card tag. The [owner's official repository](https://github.com/axonlab-data/face-anti-spoofing-dataset)
states that its samples feature consenting participants; the [owner's liveness card](https://huggingface.co/datasets/AxonData/liveness-detection-dataset)
explicitly describes publicly available samples for evaluation. The full corpus
requires a commercial license. This experiment uses the preview for local
research evaluation only; no redistributed media, trained weights or calibration.
The dataset-card tag is not asserted to clear commercial biometric training.

```sh
/tmp/docscan-bench/venv/bin/python experiments/public_face/pad_sample.py fetch
/tmp/docscan-bench/venv/bin/python experiments/public_face/pad_sample.py evaluate \
  --binary /path/to/release/examples/face \
  --report experiments/public_face/results/pad-baseline.json
```

Before measuring, fix three positions at 25%, 50%, 75% of each attack clip;
resize its long side to 960 pixels and take median passive live score per video.
Keep one score per genuine selfie. Missing detections reject. Report APCER
and BPCER at both existing raw operating points without any tuning. Five cases
per class have 20 percentage-point steps; identity correspondence and device
metadata are missing. The original selfie/video distinction is a confound.
There is no valid independent calibration cohort, so APCER at fixed BPCER
is **not estimable** here. Active session accuracy is also not measured: these
clips contain no dynamic bona fide trials following the challenge. Physical
parallax remains on in production.

The `production-pair` variant combines the two runs: flip-averaged neutral/document
portrait (the still-photo path) against an unflipped smiling reference (the live
frame path). It remains a **proxy**: no capture quality rejection or multi-frame
session aggregation is modeled. The `iris` baseline is explicitly a native
unflipped-embedding protocol, not the exact end-to-end production decision.

## Referee audit, 24 October 2026

Version 2 makes embedding caches depend on the shard count and verifies each
shard's expected row count. Version 1 could reuse half the dataset when switching
from two workers to one. Non-finite, zero, or low-presence mesh templates reject;
missing comparisons use a rejection sentinel below every cosine threshold.
Reports now include accepted counts and the scorer digest. The identity split,
images, degradation conditions and shipped thresholds are unchanged.

PAD version 2 keys inference by **all** model hashes and the actual frame hashes,
checks output length before grouping, and rejects non-finite/out-of-range scores.
It preserves the predeclared three-frame median (one missing frame alone does not
reject a whole video). It adds exact two-sided 95% binomial intervals: even zero
errors in five cases gives an upper bound of 52.2%, **assuming independent trials**,
which the preview's missing identity/device metadata cannot establish. This is
sample-size context, not a certification bound. Original v1 results are preserved;
v2 results must be labelled separately, not silently substituted.

Run the referee regressions with:

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/public_face -p 'test_*.py' -v
```

## Next comparison and active replay protocols (predeclared)

The next London run compares the existing `iris`, `flip`, `production-pair`,
`contour`, `nose4`, and `inner-mouth` embedding protocols on exactly the existing
DEV portraits and conditions. All six are reported, including negative results;
none is selected for shipping from this research-only set. TAR and FAR at the
unchanged shipped thresholds are primary. Research calibration remains confined
to the 51 calibration identities. There is no TEST/reserved access, new
augmentation search, threshold adjustment, or model fitting.

`active_replay.py` measures the five authorized replay clips through the native
active session at **default settings**, with no guide or security overrides.
It sequentially decodes each clip, takes every third source frame, resizes the
long side to at most 960 pixels (even dimensions), converts through YUV420 and
retains the nominal source frame rate divided by three. It aborts on a truncated
decode, inconsistent native decision, missing trace, or absent required physical
check. Cache keys include source/model/binary/scorer hashes and sampling settings.
Derived clips are temporary, owner-private, and removed after each trial; all
per-clip traces remain under the private preview folder.

```sh
/tmp/docscan-bench/venv/bin/python experiments/public_face/active_replay.py \
  --binary docscan/target/release/examples/face \
  --report experiments/public_face/results/active-replay-v1.json
```

This is an **attack-only session observation**, not active-liveness accuracy.
Report completion, entry into the sweep, which checks actually collected samples,
and framing/quality hints alongside attack acceptance. A rejection before any
parallax/PAD measurement says nothing about those checks' effectiveness. Original
clips were not recorded following this ring challenge. Bona fide active BPCER and
APCER at fixed BPCER remain unavailable. No experiment disables physical checks.

After the active-session run showed all five clips stopped at centering (no
passive/parallax samples), a separate temporal passive diagnostic was declared
before examining temporal scores. `temporal_replay.py` evaluates **every third
frame of every full replay clip**, at the same maximum 960-pixel long side as the
three-frame preview. It reports all frame crossings at the two unchanged raw
thresholds, clips with any crossing, and clips whose median crosses. An any-frame
crossing is an attack-opportunity diagnostic, **not** a production acceptance
rule. There are still only five attack trials, not hundreds of independent ones;
no temporal bona fide trials or active BPCER are available. No unfavorable frame
is omitted, no crop is selected, and PNG frames are deleted after inference.

```sh
/tmp/docscan-bench/venv/bin/python experiments/public_face/temporal_replay.py \
  --binary docscan/target/release/examples/face \
  --report experiments/public_face/results/temporal-replay-v1.json
```

The London evaluator also reports counts of native quality scores equal to one,
grouped by split, pose and condition. This is a diagnostic of individual frames,
not capture BPCER or a new eligibility rule. The still-photo path does not apply
the live capture gate; its small document-photo proxies must not be rejected for
failing a live-camera requirement. Actual camera capture still needs a timed
sequence, guide compliance, continuity and the physical checks.
