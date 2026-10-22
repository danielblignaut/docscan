# Proof of address: research and ideas

What the literature and our own measurements suggest for the two problems of
the proof-of-address reader: **blind extraction does not generalise** (89%
key fields on DEV against 24% on the lockbox's unseen layout families), and
**OCR is slow** (about 3 s a frame natively on one core, 26 s single-threaded
in wasm, and a capture reads about three frames). Each idea is listed with
its expected effect, its cost, and what happened when it was tried
(`docs/improvements-poa.md` has the measurements).

## Why the tagger overfits

The training data comes from one generator (`testdata/poa_synth.py`) whose
world is small: 111 places, 50 streets, about 90 first names and 80
surnames, 20 issuer roots, 6 + 8 fonts. The tagger hashes each word's text,
so it can learn that `Acacia` is a street and `Nkosi` a name, and the DEV
layouts share that vocabulary and those fonts with training. The lockbox's
failures fit that reading: "TO WHOM IT MAY CONCERN" or a street word taken
as the name, the issuer's or a branch's place taken as the holder's, new
street names joined to the name.

The literature says the same about real benchmarks. VRDU (Wang et al.,
KDD 2023, [arXiv:2211.15421](https://arxiv.org/abs/2211.15421)) is the
clearest measurement of unseen-template generalisation: LayoutLMv3, the
leaderboard leader on CORD and FUNSD, drops from 89.8 F1 on mixed templates to
62.6 on unseen ones (Registration Forms, 200 training documents), and every
model loses 13-27 points. FormNet ([arXiv:2203.08411](https://arxiv.org/abs/2203.08411)),
whose attention is biased by *relative* position and which builds
graph-local "super-tokens", generalises best (77.3). DocILE
([arXiv:2302.05658](https://arxiv.org/abs/2302.05658)) found 100k synthetic
documents from 100 seed layouts helped little on unseen layout clusters:
synthetic data helps only as far as its *layout diversity* reaches. Its
RoBERTa without layout beat a LayoutLMv3 trained from scratch on little data:
learned absolute-layout embeddings can hurt.

## Ideas, by expected effect

### Accuracy and generalisation

| # | Idea | Source | Expected effect | Cost |
|---|---|---|---|---|
| A1 | **Vocabulary randomisation**: train on pages whose names, streets, places and issuers come from pools hundreds to thousands wide (names and roots partly generated from syllables, places from the shipped GeoNames gazetteer), so word identity stops predicting the label | domain randomisation (Tobin et al., [arXiv:1703.06907](https://arxiv.org/abs/1703.06907)); DocILE's lesson | large on unseen vocabulary; may cost a little on DEV, whose vocabulary training memorised | a wrapper generator; OCR of new pages (~1 h on 3 cores per 1 000 pages) |
| A2 | **New layout families**: letters naming the holder in a sentence under "To whom it may concern", window envelopes with a return address above the holder, label: value pages, branch addresses, right-hand panels, a holder named only in the salutation | VRDU, DocILE: diversity of layouts is what transfers | large on letter-like and decoy-heavy pages | generator work |
| A3 | **Layout-agnostic features**: gazetteer membership (a word or bigram is a known place; a 4-digit known code; a place *consistent* with a code on its line or the two below), a suffix after the word (a street name), a numbered street line, a title before the word, distance to the next postal-code line below in its column and to a title line above, issuer cues near (Tel, VAT, PO Box, www, branch), holder cues, a sentence word before it, an all-capitals line, font-height rank, "content word" (not an ordinary bill word, place, title or suffix) | FormNet, LAMBERT; our own error analysis | medium-large: these carry over to new layouts by construction | Rust features (one definition, `features.rs`), retrain |
| A4 | **Relative 2-D attention bias** (BROS/LAMBERT/TILT style): a learned per-head, per-layer bias for every pair of words' log-bucketed (dx, dy) offset, in units of the page's median text height, instead of (or beside) absolute box coordinates | BROS [arXiv:2108.04539](https://arxiv.org/abs/2108.04539), LAMBERT [arXiv:2002.08087](https://arxiv.org/abs/2002.08087), FormNet | medium: the model learns "the line under the name" rather than "200 px from the top" | ~3.5 k parameters; standard ONNX ops (Sub, Log, Floor, Clip, Gather) |
| A5 | **Word-identity dropout**: hide a word's own hash (keep its shape and trigrams) for 15-30% of words in training | pNLP-Mixer [arXiv:2202.04350](https://arxiv.org/abs/2202.04350), character-aware embeddings; "Noisy Text Data: Achilles' Heel of BERT" | small-medium on unseen names and streets | a training flag |
| A6 | Drop the absolute box projection altogether | DocILE's RoBERTa vs LayoutLMv3 | uncertain: absolute position does carry information (the issuer is at the top) | a training flag |
| A7 | **DEV-G**, a generalisation set of held-out families, fonts and vocabulary, to choose between changes that DEV (same generator, same vocabulary) cannot tell apart | VRDU's unseen-template split; DocILE's zero-shot clusters | better decisions | 300 pages, OCR'd once |
| A8 | Decoding constraints: the holder name and the address as one block; spans in an issuer block excluded; one holder per page | PICK/CRF decoding; SPADE | small-medium; the current span repair already does part of it | Rust post-processing |
| A9 | Self-training on unlabelled synthetic variants (pseudo-labels from the current model, kept where the validators agree) | Noisy Student [arXiv:1911.04252](https://arxiv.org/abs/1911.04252); QueryForm | small for synthetic-to-synthetic; large with real unlabelled pages, which we do not have | moderate |
| A10 | A small graph network over OCR boxes (k-nearest neighbours, relative-geometry edges) before the transformer | FormNetV2 [arXiv:2305.02549](https://arxiv.org/abs/2305.02549), Doc2Graph [arXiv:2208.11168](https://arxiv.org/abs/2208.11168) | overlaps A4 | moderate |
| A11 | Distil from an LLM teacher on real pages (LMDX-style prompts: 75 F1 on VRDU unseen templates with no training) | LMDX [arXiv:2309.10952](https://arxiv.org/abs/2309.10952) | the largest real-world lever | needs real proof-of-address pages with consent: out of scope here |

### Verification

| # | Idea | Expected effect | Cost |
|---|---|---|---|
| V1 | Confusion-aware matching of short surnames (weighted edit distance with OCR's own confusions: 0/O, 1/l/I, 5/S, 8/B, rn/m), instead of exact match for four letters or fewer | fewer genuine rejections from a slip in a short surname | small |
| V2 | The name and the address found on different frames: link them across frames by position on the flattened page | fewer genuine rejections | small-medium |
| V3 | Unit and complex lines above the street; joint holders | robustness | small |

### Speed

| # | Idea | Source | Expected effect | Cost |
|---|---|---|---|---|
| S1 | **Batch recognition by line width**: ocrs groups lines of similar width into one batch, but `ocr_page` hands it 16 lines at a time in reading order, so most groups hold one to three lines; sorting all lines by width first gives full batches of equal width | ocrs `recognize_text` | 10-30% of recognition, no accuracy change | trivial |
| S2 | Detect on the whole page in one pass instead of 3 × 3 overlapping 600 × 800 tiles (the tiles cover the page about twice) | — | up to half of detection | the detection model has a fixed input shape: needs our own call into it |
| S3 | Detection at a lower resolution, recognition at full resolution | two-stage OCR | detection ~2× faster | accuracy risk on small print |
| S4 | **Skip lines that cannot hold a field** (dense tables of amounts, small print paragraphs) by their geometry before recognition | ROI OCR | 20-40% of recognition | accuracy risk: the tagger reads context; verification searches the whole page |
| S5 | Reuse frame 1's OCR in later frames: re-recognise only the lines the tagger tagged (holder, address, date), mapped through the two pages' alignment | Smart Engines' per-field multi-frame fusion ([arXiv:1910.04107](https://arxiv.org/abs/1910.04107)) | frames 2-4 at a fraction of the cost | moderate |
| S6 | Early exit: stop reading frames once verification is decisive | — | fewer frames read | small |
| S7 | int8 dynamic quantisation of the detection and recognition models (rten supports `DynamicQuantizeLinear`, `MatMulInteger`, `ConvInteger`; 1.5-3× for small models natively; rten does not use wasm's relaxed-SIMD dot products yet) | rten docs/quantization.md | 1.5-2× natively, less in wasm; accuracy to be measured | a conversion script |
| S8 | Check the wasm build uses `simd128` (a native-to-wasm ratio near 10× suggests it might not) | rten | up to 2-4× in wasm | a build flag |

## Datasets

All training and evaluation data here is synthetic. FUNSD (non-commercial),
XFUND (CC BY-NC-SA), SROIE (no licence), DocILE (research access) and VRDU
(licence unclear) were considered only as evaluation ideas, not as training
data for shipped weights; CORD (CC BY 4.0) is commercially usable but is
Indonesian receipts, a different domain. None was downloaded.

## What DEV-G showed

DEV-G (`testdata/poa_wide.py --split devg`, see `docs/improvements-poa.md`)
reproduces the lockbox's failure without looking at it: the committed tagger
reads all five key fields right on **6.3%** of its camera pages (12.3% when
the same pages are "read" by the synthetic-OCR model instead of the real
OCR), against 89% on DEV; genuine customers were accepted on **34.7%** of
recent pages. Two different causes:

- **The tagger** takes street suffixes (`Grove`, `SINGEL`), headings
  (`CERTIFICATE OF RESIDENCE`), places (`Kaapstad`) and a branch consultant's
  name for the holder, and often tags no city or postal code at all.
- **OCR on unfamiliar fonts runs words together**, and verification was
  brittle to it: `MRLS NDLAMTHIVENDLE`, `Mr MHizuhle`, `Miss D.Sacoor`,
  `MPFARISENIBHLOPHE`, `MsSHiophe`, `17klipLane`, `54 FETHADLROAD`,
  `September 16.2026`; titles read `Kr`, `Nrs`, `Mi`; initials read as
  digits (`L2`). These are the lockbox report's "an OCR slip in a short
  surname" in more forms, and a real phone camera will produce them too.
  Matching them (V3-V5) moved genuine acceptance on DEV-G from 34.7% to
  52.9% with every negative still rejected, and changes nothing on DEV.
