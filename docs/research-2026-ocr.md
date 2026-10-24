# OCR research survey and experiments — 24 October 2026

This survey covers new papers and relevant earlier foundations. Paper results
are author-reported on their protocols, not measurements of docscan. The
experiments below use the unchanged public-document DEV scorer and all sixty
pinned development pages. No TEST/lockbox access, training or external uploads.

## Primary-source shortlist

| Work | Date/version checked | Mechanism relevant here | Decision |
| --- | --- | --- | --- |
| [PP-OCRv6](https://arxiv.org/abs/2606.13108), [official implementation](https://github.com/PaddlePaddle/PaddleOCR) | June 2026 | Compact detector/recognizer families, structural reparameterization and different recognition capacity across tiers. | Execute modular capacity experiments using already pinned official Apache-2.0 exports. Our asymmetric pairings are hypotheses, not a reproduction of the paper's reported end-to-end configuration. |
| [SVTRv2](https://arxiv.org/abs/2411.15858), [OpenOCR](https://github.com/Topdu/OpenOCR) | November 2024; revised July 2025, ICCV 2025 | Multi-size resizing and feature rearrangement improve CTC alignment; training-time semantic guidance need not add inference cost. | Strong candidate for a later independent recognizer comparison. Published STR word accuracy does not establish document-field accuracy. New export/dictionary/operator checks are required before adding another shipped model. |
| [A Free Lunch? Adapting PP-OCRv6 for Historical Text Recognition](https://arxiv.org/abs/2609.20064) | September 2026 | Heterogeneous pretraining and adaptation can matter more than training a compact architecture from scratch. | Prioritize pretrained capacity and measured domain failures. No claim that historical manuscript gains transfer to bank pages. A full fine-tuning run needs eligible line-level transcription labels, not partially annotated invoice pages treated as complete truth. |
| [SAHI](https://arxiv.org/abs/2202.06934), [author documentation](https://obss.github.io/sahi/guides/sliced-inference/) | 2022 foundation; current documentation inspected | Overlapping slices preserve small objects; mapped detections need duplicate suppression. | Test full-width overlapping strips for text. This is our adaptation to long lines, not an exact SAHI implementation or a claim about its object-detection benchmarks. |
| [ROI-Gated SAHI](https://arxiv.org/abs/2608.23923) | August 2026 | Foreground-gated refinements can avoid empty tiles, but the reported dense/sparse results are mixed. | Do not assume gating improves speed or accuracy on dense statements. Start with fixed strips and report all regressions before studying an adaptive gate. |
| [DocRes](https://arxiv.org/abs/2405.04408), [official code](https://github.com/ZZZHANG-jx/DocRes) | CVPR 2024 | One restoration model handles dewarping, shadows, enhancement, blur and binarization through task prompts. | Candidate for photographed-page restoration, not the clean-PDF transcription benchmark. Additional model/runtime and distorted-page provenance checks are needed; no default preprocessing added merely for cleaner-looking images. |
| [RT-DocLayout](https://arxiv.org/abs/2606.23344) | June 2026 | Joint layout regions, masks and reading-order prediction in a 33M-parameter model. | Keep layout ordering separate from recognition. Our current token-bag/field-region metrics cannot certify reading order; add independent ordering truth before evaluating this model. Published FPS is not browser FPS. |
| [Jina-OCR-v1](https://arxiv.org/abs/2609.03181) | September 2026 | GPU-oriented document parsing with speculative decoding and verifiable structural rewards. | Use its distinction between recognition and structural checks as evaluation guidance. Its 3B MoE decoder is not a drop-in for the current few-megabyte browser engine; do not spend local CPU time on an unqualified multi-billion-parameter port. |
| [CC-OCR v2](https://arxiv.org/abs/2605.03903v2) | May 2026; revised August 2026 | Document failures stratified by acquisition conditions and task, rather than one headline score. | Add device/condition strata before broad accuracy claims. Reading the paper is not permission to download arbitrary personal documents; any future corpus import needs source/rights and split review. |
| [On Calibration of Scene-Text Recognition Models](https://arxiv.org/abs/2012.12643) | 2020 foundation | Character/sequence confidence and correctness are different; calibration can change decoding behavior. | Treat decoder confidence as a heuristic only. Do not relabel the existing small-print selection score as probability of correctness or use it to relax verification. |

## Our predeclared hypotheses

1. **Asymmetric capacity:** a tiny detector with the small recognizer may recover
   more invoice names/numbers for less download than the full small pair. Test
   both asymmetric directions; do not assume recognition is always the bottleneck.
2. **Preserve scale without cutting text lines:** full-width horizontal strips
   might recover dense text without the large activation tensor of a high-resolution
   full page. Include the full-page pass, map coordinates, suppress overlapping
   detections, and score duplicate output through precision.
3. **Separate recognition from successful verification:** a token gain that
   changes a house number, name or acceptance outcome is not sufficient. These
   research readers are not wired into customer/identity verification.

`experiments/research_ocr/protocol.json` fixes seven modes before inference:
tiny/tiny, tiny/small, small/tiny, small/small at the standard cap; tiny/small
at the detailed cap; and sliced tiny/tiny and tiny/small. It also fixes slice
height, overlap, full-page precedence and overlap suppression. All outcomes,
including failures, are retained. No confidence/selection threshold is fitted
to the reference labels. Each mode runs in an isolated process with a timeout,
one ONNX Runtime thread, pinned model/config hashes and a post-run model guard.

The experiment is Python/ONNX Runtime, using the audited reference preprocessing.
It is not Rust/WebAssembly parity. Baseline figures therefore must be compared
within this runner, not subtracted from the different shipped Rust pipeline.
Raw text/boxes remain private in `/tmp/docscan-research-ocr`; git contains
aggregate counts, sample IDs, hashes and source code only. Native elapsed times
are descriptive under shared machine load; they are not a latency verdict.

Reproduce:

```sh
uv pip install --python /tmp/docscan-ppocr-v6/venv/bin/python -r experiments/research_ocr/requirements.txt
/tmp/docscan-ppocr-v6/venv/bin/python -m unittest discover -s experiments/research_ocr
/tmp/docscan-ppocr-v6/venv/bin/python experiments/research_ocr/run.py
```

The runner refuses to overwrite reports. To resume an interrupted batch, run
only an unmeasured predeclared `--mode`; keep completed and failed results.

## Measured outcome

All seven Python modes and four native configurations were measured, followed
by unchanged synthetic and non-text regressions. The tiny-detector/small-recognizer
hybrid is the strongest practical lead: native detailed bank recall/precision
**95.83% / 97.76%**, versus **94.62% / 96.93%** for the shipped detailed pipeline;
invoice-region recall/precision **91.99% / 95.11%**, versus **87.36% / 93.50%**.
It uses 22.9 MB of weights, not the 31.0 MB of the full small pair. No weights
were trained. Larger detection alone regressed invoices, and sliced detection's
extra recall came with a precision tradeoff. Full results, baselines, provenance,
negative outcomes and reproduction: [experiment report](../experiments/research_ocr/README.md).

The native baseline reproduces all prior scored items. Four configurations keep
zero normalized CER on the twelve synthetic regression pages and emit no text
on eight generated non-text pages. Browser memory/latency and independent
real-camera data remain integration gates; none of these results is SOTA proof.
