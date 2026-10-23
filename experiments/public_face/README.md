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
