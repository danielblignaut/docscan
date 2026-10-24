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

## Results and decisions, 24 October 2026

The six complete v2 reports are in `results/london-v2-*.json`. All conditions
retain 51/51 genuine accepts in **both** splits at the unchanged shipped
thresholds. Below are false accepts out of **2,550 dependent impostor pairs**
per split; each entry is calibration / validation, not independent repetitions.
The original condition uses the live threshold 0.366; the two degraded portrait
conditions use document threshold 0.356, exactly as v1 did. `production-pair`
still means a still/live embedding proxy, not the complete document-verification
decision, including for the undegraded original condition.

| Variant | Original | Gray 384 | Gray 192 |
| --- | ---: | ---: | ---: |
| iris baseline | 12 / 12 | 12 / 13 | 11 / 5 |
| flip both sides | 16 / 11 | 10 / 11 | 8 / 4 |
| production-pair | 14 / 12 | 12 / 12 | 8 / 5 |
| contour | 9 / 11 | 8 / 11 | 5 / 5 |
| nose4 | 18 / 11 | 10 / 10 | 9 / 3 |
| inner-mouth | 9 / 12 | 6 / 12 | 7 / 5 |

**No production candidate selected.** Recognition is at a genuine-acceptance
ceiling on these same-session portraits. Small changes in correlated impostor
counts do not demonstrate a generalizable gain; nose4's original calibration
false accepts even rise from 12 to 18. Contour is a candidate for independently
authorized evaluation, not a new shipped alignment. No speed claim is made.
Baseline validation FAR is 0.471%, 0.510%, and 0.196% across the three conditions;
production-pair gives 0.471%, 0.471%, and 0.196%. Neither establishes a population
FAR of 0.1%. The research-calibrated results remain in the reports and have not
been copied into production.

The iris baseline, flip and production-pair reproduce every v1 TAR, FAR and
threshold exactly under v2. A fresh iris run with one worker matches the two-worker
run's complete metrics, checking the corrected cache partition in actual native
inference. The prior `f24ad10` missing-first/all-missing embedding fix also passes
all three native example regressions. No TEST/reserved data was opened or run.

The capture-quality diagnostic is deliberately separate: all 51 validation smile
references produce usable embeddings, but 49 have native quality score one.
Only 31/51 small validation document proxies have score one; applying a live
capture gate to those **still document** images would measure the wrong pipeline.
Neither count estimates multi-frame camera capture BPCER.

`results/pad-v2-baseline.json` reproduces the passive preview: zero rejected
genuine selfies out of five and zero accepted replay-video medians out of five,
at raw 0.59 and 0.78, with no missing/invalid frames. The 95% independent-binomial
interval for either error rate is [0%, 52.2%]; independence itself is unverified.

`results/active-replay-v1.json` processes 765 sampled frames from the full five
14.4–15.7-second replay clips. Zero sessions accept, but **all five stay in the
centering phase**, with 561 centering hints and 204 move-back hints. None enters
the sweep or collects passive/parallax samples. These are framing rejections,
not evidence that active PAD defeated a completed attack. Required parallax,
passive PAD, continuity, identity and coverage checks remain present with their
unchanged thresholds. Bona fide active BPCER remains unmeasurable.

`results/temporal-replay-v1.json` independently scores all 765 sampled replay
frames through passive PAD. **Zero frames** cross either raw threshold, no clip
has an accepted frame or median, and all 765 have valid detected scores. Thus the
three-frame result did not hide a transient crossing in this fixed sample. This
does not make 765 independent attack trials; unsampled frames, other devices and
other attacks remain untested. It supplies no temporal bona fide error rate.

Validation completed:

```sh
PATH=/home/dan/.cargo/bin:$PATH cargo build \
  --manifest-path docscan/Cargo.toml --release --locked --example face -j 2
PATH=/home/dan/.cargo/bin:$PATH cargo test \
  --manifest-path docscan/Cargo.toml --release --locked --lib --example face -j 2
/tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/public_face -p 'test_*.py' -v
git diff --exit-code f24ad10 -- docscan demo models bench
```

All **99 library + 3 native example + 18 Python referee tests** pass. Each of
the three prior London variants reproduces 54 rate/threshold fields exactly;
the one/two-worker runs match metrics and capture-quality counts. Binary and
scorer hashes, all model hashes, source/protocol digests and operating thresholds
are in the reports. Production code, model bytes, security thresholds, physical
checks and the shared `bench/` referee remain unchanged from `f24ad10`. This is
a referee/evidence improvement, **not a demonstrated production accuracy gain**.

## P2 provenance-only revision, 24 October 2026

All four runners now acquire one private executable snapshot before looking up
caches or running inference. London shares that same snapshot across every shard
and both production-pair passes. `artifacts.py` copies once, checks the source's
file identity/timestamps and SHA-256 before/after copying, checks the copy's
SHA-256, and rejects a copy race. Cache keys and reports use the acquired digest;
later rebuilds of the original path cannot change a running evaluation. The
temporary executable is owner-only, read/execute-only, and removed on exit.
Reports also record `artifact_guard_sha256` alongside the runner's scorer hash.

Models are neither copied nor rebuilt. Their full ONNX file set, hashes and file
identities/timestamps are checked at acquisition, around inference/cache use,
and before writing a report. Detected changes abort. New native outputs are
staged privately and only published as caches after successful native execution,
output validation and input verification; partial or changed-input runs do not
become cache hits. These checks detect concurrent changes; they are not a lock
against a malicious filesystem writer.

This revision changes provenance and cache publication only. Scoring, thresholds,
sampling, cache-key formulas, production code and model bytes are unchanged.
The historical reports keep their original binary/scorer hashes and metrics;
they have not been relabelled as new inference runs. Active/temporal cache keys
already include the scorer hash, so future runs naturally use new cache folders.
London/PAD keys retain their existing binary/model/protocol correspondence.

Validation: **24 Python tests pass** (the prior 18 plus six provenance tests,
with subcases). The production-pair regression failed before the fix: replacing
the original executable between simulated native passes changed the reported
digest. It now proves all four shard launches use one snapshot, the vectors
remain from the original executable, and both cache keys and the report retain
its digest. Additional cases cover all three replay/PAD entry points, source
replacement/in-place mutation during copying, corrupt copies/snapshots, model
replacement/mutation/addition/removal, and interrupted cache writes. Fixtures
are synthetic; no biometric test fixtures were added.

Read-only validation of existing private caches reproduced every metric and
capture-quality count in all six `london-v2-*.json` reports, including iris and
production-pair, after checking their cache keys, model hashes and manifest/
protocol digests. The PAD v2 baseline also matched every metric/count from its
keyed cache. Active and temporal replay reports matched their historical
provenance keys, cached summaries and derived-sampling hashes. AST comparisons
confirmed scoring, sampling, validation and cache-key functions were unchanged.
This verifies cached-result correspondence, not retroactive proof that an old
run could never have encountered the race. The executable currently at the
build path has a different digest from these reports; no new model inference or
build was needed, and no TEST data was accessed. Source media, templates and
per-media outputs remain outside git. No production accuracy or SOTA gain is
claimed.

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover \
  -s experiments/public_face -p 'test_*.py' -v
git diff --check -- experiments/public_face
```

## External-source review and the SOTA evidence gap

Reviewed official sources on 24 October 2026, without acquiring additional
biometric media or accepting an agreement:

- [Microsoft DigiFace-1M](https://github.com/microsoft/DigiFace1M) is synthetic,
  but its [official R-UDA license](https://github.com/microsoft/DigiFace1M/blob/main/LICENSE)
  restricts use to noncommercial research and excludes using the data or results
  to improve a commercial product/service. It was not acquired and does not
  supply real presentation attacks or camera capture trials.
- [NIST FRTE 1:1](https://pages.nist.gov/frvt/html/frvt11.html) reports verification
  on distinct mugshot, visa, border, kiosk, pose and ageing conditions at specified
  FMRs including 1e-5 and 1e-6. Our 102 same-session subjects, synthetic document
  degradation and small dependent impostor set cannot establish performance on
  those operating points or rank SFace against those submissions.
- [NIST's passive PAD evaluation, IR 8491](https://www.nist.gov/publications/face-analysis-technology-evaluation-fate-part-10-performance-passive-software-based)
  examines multiple presentation-attack instruments on sequestered imagery. It
  explicitly does not evaluate real-time challenge-response systems. Five owner
  replay previews cannot establish broad PAD effectiveness, and neither that
  report nor this experiment validates our active challenge.

The SOTA gap is **unquantified**, not zero: no comparable independently evaluated
real ID/selfie, cross-age/device/source, demographic, or challenge-following
bona fide/attack corpus was available within this task's permissions. The next
useful acquisition is an authorized paired collection with independent subjects,
devices and attack instruments, including real compliant challenge sessions,
with commercial development rights established separately if intended. Freeze
evaluation conditions and reserve subjects before development; do not turn these
preview results into production calibration. All source notices, media, derived
frames, templates and per-media scores remain private under the two authorized
`/tmp/docscan-public-data` directories. Only aggregate reports are committed.
