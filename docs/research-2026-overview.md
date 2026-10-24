# Research and benchmark ledger — 24 October 2026

PR #2 was the only open docscan PR at the start of this request. It was merged
as `dd96ed0`, and its GitHub Pages deployment succeeded. This research branch
starts there. **The new experiments do not change application defaults, model
weights, identity/customer thresholds or liveness checks.** No new weights were
trained and no TEST/reserved data was accessed.

The targeted survey covers **49 distinct cited arXiv papers**, plus author
repositories, official releases and licensing notices. It includes 2024–2026
work and explicitly identified foundations, not a claim to exhaust all research.
Our own proposed mechanisms are labeled separately from exact paper reproductions.

| Area | Research and reproducible experiments | Measured outcome and decision |
| --- | --- | --- |
| General OCR, small print, restoration and layout | [Survey](research-2026-ocr.md), [all experiments](../experiments/research_ocr/README.md) | Native tiny-detector/small-recognizer detailed profile: bank recall **94.62→95.83%**, precision **96.93→97.76%**; invoice-region recall **87.36→91.99%**, precision **93.50→95.11%**. Best integration lead; 22.9 MB weights versus 6.2 MB, browser/device costs not yet measured. |
| ID/MRZ, geometry, deblur, glare and temporal capture | [Survey](research-2026-capture.md), [experiment](../experiments/research_capture/README.md) | Automatic contour rectification: correct passport accepts **1→4/12**, wrong accepts **2→1/18**. One wrong accept remains. Rotation and alternative margins can increase wrong accepts and were rejected. |
| QR/DataMatrix/PDF417/Aztec and 1D barcodes | [Survey and results](research-2026-capture.md) | Matrix-only retries: public recovery **214→217/262**, synthetic **624→629/818**; false-decode frames remain **5/277** and **1/300**. Keep as a bounded integration lead, not an unmeasured default switch. Unrestricted retries and replacement-decoder results remain visible. |
| Statement/bill classification and grounded address extraction | [Survey](research-2026-poa.md), [experiment](../experiments/research_poa/README.md) | Initial header classifier improves **142→185/200**, but falls **46→33/71** on frozen counterexamples, introducing 18 regressions. A stricter alternative improves some cases yet all still misclassify 19/23 ambiguous/unsupported pages. Raw selector recovers no complete annotated DEV blocks. **Do not integrate.** |
| Face-to-document matching and capture quality | [Survey and matching loop](research-2026-face.md), [experiment](../experiments/research_face/README.md) | Frozen gamma averaging: hardest validation genuine accepts **7→8/51**, impostors **0→0/2550**, but another operating point has **5→6** false accepts. Mixed, tiny changes on artificial degradation; no production promotion. |
| Passive and active liveness | [Survey and temporal loop](research-2026-face.md) | Four rules over 765 frames of five replay clips retain zero threshold crossings. New temporal variants raise attack margins and lack genuine challenge-following trials. No supported gain; keep existing defenses. |

## What was actually run

- Seven predeclared Python OCR configurations, four isolated Rust probes, each on
  the same 60 external DEV pages. Rust baselines reproduce every previous scored
  item. All four keep zero normalized CER on the twelve simple regression pages
  and no text on eight generated non-text probes. These are not real blank-page
  safety certification or independent validation.
- Two capture/barcode rounds: all 18 pinned MIDV frames and all 577 barcode DEV
  frames, with fixed truth-code denominators, per-item false accepts/decodes,
  timeouts and rejected candidates retained. One incomplete image-loader attempt
  is preserved; the corrected fallback keeps its frame in the denominator.
- Structured extraction on 200 captures/800 OCR frames and three correlated
  public variants, followed by 71 invented counterexamples and a frozen raw-block
  selector on 40 TRAIN invoices, all 50 DEV invoices and the three public variants.
- Temporal/quality fusion on five authorized replay clips, plus fresh photometric
  face matching on all 204 portraits, four conditions and 20,808 comparisons per
  arm. Pair counts share identities and derived media; they are not independent
  population samples. All 32 operating-point cells were independently audited.

No paper's headline accuracy is substituted for our measurements. Python versus
Rust geometry is reported separately. Recognition, ordering, semantic extraction,
verification, detection, capture quality and liveness efficacy are distinct tasks.
Neither a correctly read name nor a rejected noncompliant clip establishes identity
or document authenticity. Confidence scores are not calibrated correctness.

## Review and evidence

Programs/configurations were frozen before their measurements. Every candidate,
regression and failed setup is retained, with executable/model/source/input hashes.
Raw media, OCR strings, barcode payloads, embeddings and identity-indexed scores
remain owner-private outside git; published artifacts contain aggregate scores,
categorical outcomes, opaque IDs, source indices and provenance.

Independent review found an invalid-output masking bug: encoded `"0"` outcomes
were truthy. A mixed missing-output/false-accept regression demonstrated it;
explicit `"1"` comparison fixes it. All measured native outputs in those original
rounds were valid, so recorded totals are unaffected. A self-audit also hardened
model guards against same-named files in different directories; file hashes and
metadata confirm no model changed during the completed OCR runs. Historical
reports retain their original executed-source hashes rather than being rewritten.

## Next experiments worth prioritizing

1. Integrate the hybrid OCR recognizer behind an explicit profile only after
   browser operator/parity tests, cold-download and memory measurements, and phone
   p50/p95. Test independent layout families, amounts/names and real image capture
   conditions before considering it as a default.
2. Implement matrix-only barcode retries with a bounded budget, then rerun the
   unchanged DEV scorer and interleaved browser/native latency checks. Validate
   contour rectification against more negative frames and full capture clips.
3. For POA, distinguish document titles from organization names and quotations;
   require explicit conflict/unknown outcomes. Evaluate a country-neutral raw
   block separately from a jurisdiction's schema. The failed selector is a
   counterexample bank, not permission to retune and call the same set validation.
4. For face/liveness, prioritize independent document/selfie pairs, devices and
   real bona fide challenge sessions with appropriate use rights. Do not lower
   production thresholds to manufacture gains on these narrow research cohorts.

These are research leads and rejection decisions, **not evidence of SOTA**.
The data remain small, correlated and mostly synthetic/specimen-based; benchmarks
must broaden before claims about production accuracy or attack resistance.
