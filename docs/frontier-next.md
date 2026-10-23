# Next experiments toward stronger capture and extraction

Research checked on 2026-10-23. These are candidate experiments, not shipped
capabilities or claims that docscan matches published systems. Dataset,
operator support, memory, licensing and performance must be measured before
adoption. The benchmark DEV/TEST separation still applies.

| Candidate | Primary source | Experiment and acceptance evidence |
| --- | --- | --- |
| Lightweight multilingual OCR | [PaddleOCR PP-OCRv6](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv6/PP-OCRv6.en.md) describes tiny/small/medium models and ONNX-runtime measurements. | The tiny export now has a pinned optional Rust/wasm integration and fixed general-text DEV evidence in `experiments/ppocr_v6/`. Next, compare on broader general-text, ID and PoA DEV inputs before considering any default change. Measure cold download, peak wasm heap, phone p50/p95, exact numbers/names and false text on blank regions. Published CPU timings do not establish browser timings. |
| Layout and reading order | [RT-DocLayout](https://arxiv.org/abs/2606.23344) jointly predicts layout geometry and reading order. | Add a separately versioned DEV corpus of columns, tables and warped pages with word and line ground truth. Measure transcription separately from ordering. The current text reader deliberately exposes geometry but uses row order. |
| Cross-domain face PAD | [Primitive-driven compositional forensic prompting](https://arxiv.org/abs/2608.17351) evaluates a frozen ViT with learned prompts over open-world protocols. | First reproduce its reported protocol with permitted weights/data, then measure compact alternatives or distillation on disjoint cameras and attack media. No commercial training on research-only face datasets. Evaluate APCER at fixed BPCER; a higher AUC alone is insufficient. Browser feasibility is unproven. |
| Novel 3-D face attack evaluation | [Single-portrait Gaussian-head authenticity benchmark](https://arxiv.org/abs/2608.23984) studies reconstructed heads whose source image may be forged. | Add appropriate consented/generated DEV attacks to the threat evaluation. This is a distinct task from presentation-attack detection; do not turn its published accuracy into a docscan liveness claim. |

## Gaps that more code alone cannot settle

- A representative, consented real-device document collection is needed before
  synthetic PoA/general-text results support product-level accuracy claims.
  Include bill issuers/layouts held out by family, house and unit numbers,
  folded paper, glare, receipts, photocopies, and long documents.
- Face-to-document tests currently use synthetic document renderings. Real
  document portraits differ through age, print/scan degradation, lamination,
  duplicate ghost portraits and capture quality. Tune only on DEV identities,
  report TAR at stated FAR, and keep identity-disjoint final evaluation locked.
- Real camera/attack testing must cover prints, curved prints, screens, replay,
  injection and masks, and report outcomes across devices and relevant groups.
  A synthetic head sweep is useful for regressions, not certification.
- Physical phone latency/memory and camera autofocus must be measured on the
  intended Android/iOS hardware. Desktop headless Chrome is not that evidence.

Keep candidates behind explicit experiments until the unchanged referee shows
an improvement without a significant accuracy regression. Any latency trade
must be reported. Preserve the physical liveness check while investigating
additional cues; speculative patent interpretations do not establish clearance
or justify silently removing an existing defence.
