# Face datasets: what was used, under which terms, and what was not run

Face images and templates are biometric special personal information under
POPIA s.26. **No face image, face video, template or dataset is committed to
this repository.** Public benchmark data was downloaded to `/tmp/face-data/`
on the evaluation machine only, used for local research evaluation, and
deleted afterwards. Only metrics are reported.

The synthetic clips and documents used for liveness, the e2e suite and the
document-to-live eval contain **no real person**: the heads are procedural
(`face/synth/head.py`: MediaPipe's Apache-2.0 canonical mesh with a texture
drawn from scratch), and the documents are `testdata/synth.py`'s fictional
ones. The only "real" faces in any eval are LFW's, inside the document eval,
and they stay in `/tmp`.

## Used (local evaluation only)

| Dataset | What for | Terms | Source used |
|---|---|---|---|
| **LFW** (Labeled Faces in the Wild; Huang et al. 2007) | Recognition: raw images through docscan's own detector, landmarks and alignment. DEV = View 1 (`pairsDevTrain` + `pairsDevTest`, minus the 758 pairs that also occur in View 2: 2 442 pairs), TEST = View 2 (`pairs.txt`, 6 000 pairs, 10 folds). Also the document-to-live eval. | No formal licence; images of public figures from news sites; the authors ask that results not be taken as evidence of suitability for commercial use. No agreement needed. | The UMass host no longer resolves and the scikit-learn figshare mirror returns 403 to scripts, so: Hugging Face `marcelohaps/lfw` (the original 250 × 250 images and the 10-fold `pairs.csv`) and `logasja/lfw` (`pairs/`, which carries View 1; matched to file names by MD5 of the JPEG bytes). |
| **lfw.bin, calfw.bin, cplfw.bin** (InsightFace evaluation packs: 112 × 112 crops pre-aligned by InsightFace's detector) | Recognition numbers comparable with published ones (same crops the papers use) | Inherit their source datasets' terms: LFW (above); CALFW / CPLFW (Zheng et al., LFW-derived, research use, no agreement) | Hugging Face `gaunernst/face-recognition-eval` |
| **CelebA-Spoof** (Zhang et al., ECCV 2020) | Passive anti-spoofing APCER/BPCER: DEV = 3 000 images sampled from two shards of the mirror's `valid` split (official train subjects), TEST = 6 000 sampled from the first eight shards of the official `test` split | **Non-commercial research and educational use only**; open download, no signature. Evaluating a model for a product that may become commercial sits at the edge of "research"; the numbers here are for orientation, not a product claim. | Hugging Face `Ar4ikov/celebA_spoof` (the official images, boxes and live/spoof labels; no spoof-type labels) |

## Not run

| Dataset | Why |
|---|---|
| **CFP-FP** (Sengupta et al. 2016) | Access by registration/request at cfpw.io; not signed. (A `cfp_fp.bin` mirror exists; using it would sidestep the request, so it was not.) |
| **AgeDB-30** (Moschoglou et al. 2017) | Not run: access requires a signed agreement (non-commercial; password by email). Same for the `agedb_30.bin` mirror. |
| **IJB-B / IJB-C** (NIST) | Not run: access requires a signed agreement. |
| **OULU-NPU, SiW, SiW-Mv2, CASIA-SURF, CASIA-FASD, Replay-Attack, Replay-Mobile, MSU-MFSD, Rose-Youtu, WMCA, 3DMAD** | Not run: access requires a signed agreement (EULAs from a permanent staff member, institutional email; non-commercial). |
| **XQLFW** (cross-quality LFW; MIT repo, LFW-derived) | Downloaded, not run for lack of time; a good next check for low-quality (document-like) faces. |
| **LCC-FASD** | Not run: no licence stated; partly scraped from YouTube. |
| **Kaggle / Hugging Face "anti-spoofing" sample sets** (Axon Data, UniqueData, UniDataPro, …) | Not run: CC BY-NC(-ND) samples of commercial datasets, people's faces, no research-evaluation basis worth relying on. |
| **DigiFace-1M, Microsoft Face Synthetics** | Not used for training: R-UDA licence forbids commercial use of the data or anything trained on it. |
| **FFHQ / StyleGAN faces, SFHQ** | Not used for test assets: non-commercial generator weights and data; SFHQ faces may resemble real people. |

## Real photos from the user

`/tmp/docscan-real-face/` did not exist during this work, so no real photos
of the user were evaluated.

## Public-data expansion (23 October 2026)

The earlier cleanup above describes the historical runs. The new bounded
research evaluation keeps temporary owner-private data under
`/tmp/docscan-public-data/` while the improvement loop is active. No photos,
videos, identity-indexed scores or templates are committed. Acquisition and
aggregate measurements are reproducible with
[`experiments/public_face`](../experiments/public_face/README.md).

| Dataset | Actual acquisition | Use and limitations |
|---|---|---|
| Face Research Lab London Set v5, DeBruine & Jones (2017), CC BY 4.0 | 204 frontal neutral/smile photos from the author's pinned `webmorphR.stim` release, 95.2 MB | Research-consented adults. 51 calibration / 51 validation identities; real matching pairs and synthetic grayscale/resolution stress. No biometric-commercial-consent inference, shipped training, cross-device claims, or TEST access. |
| Axon Labs public display-replay preview | Five genuine selfies and five replay videos, 163.8 MB; official owner HF revision and LFS SHA-256 pinned | Owner's public evaluation sample. Sample card tagged CC BY 4.0, full collection commercially licensed; source consent and evaluation statements preserved separately. Local passive-model evaluation only, no training or redistribution. Five media per class cannot establish frontier performance. |
| WFAS | Not acquired | Official InsightFace rules require a signed agreement and restrict usage to academic research. The paper's CC-source description does not supersede these terms. |
| SynthASpoof | Not acquired | Official project requires a request and expressly excludes product development under its CC BY-NC-SA research terms. |

The new still-photo benchmark contains no presentation attacks. The replay
preview contains no dynamic genuine challenge trials, so it cannot estimate
active-liveness BPCER. Do not convert either limitation into an apparently
perfect liveness result. Report passive per-video APCER/BPCER separately from
the session's physical parallax and challenge checks.
