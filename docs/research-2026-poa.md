# POA research and controlled DEV loops — 24 October 2026

**Experimental result:** a layout-restricted document-type classifier improves
capture type correctness from **142/200 to 185/200** on cached synthetic DEV
when the shipped first-picked-frame behavior is retained. It also changes the
three Synthesized bank-statement variants from **13/27 to 16/27** exact tagger
fields. The improvement is entirely document type. Full holder/address remains
**0/3**; this does not add US address support. Nothing is proposed for shipping
in this round.

The implementation, frozen configurations, per-item comparisons and tests are in
[`experiments/research_poa`](../experiments/research_poa/README.md). Native
extractors were rebuilt from an archived **dd96ed0** source tree with `-j2`
and a separate Cargo target. The baseline is native shipped Rust, not our Python
approximation. No shipping code, model, security threshold, common scorer, Cargo
file or example was edited. No TEST/reserved data was listed, decoded or run.
Existing research prose contains historical held-out results; those were
encountered while reading context, but were not used to choose these candidates.

**What we searched.** Public arXiv, primary papers and author-maintained
repositories/model cards, accessed **2026-10-24**, for 2024–2026 document KIE,
layout graphs, OCR propagation, constrained decoding and calibration. Search
results and third-party summaries were discovery aids only. The following
technical claims come from the linked primary sources. Papers, code, weights
and data have separate licenses: an open paper or MIT repository does not
establish permission to reuse all associated training data. No author was
contacted, agreement accepted, service called with documents, or model downloaded.

**Compact models and layout.**

- **Docling**, first submitted **2024-08-19**, revised **2024-12-09**:
  [paper](https://arxiv.org/abs/2408.09869v5),
  [author repository](https://github.com/docling-project/docling).
  Combines document layout analysis and table recognition in a local conversion
  pipeline. Its code is **MIT**; the repository explicitly sends users to each
  model's own license. It is a credible offline structure-extraction comparator,
  not a turnkey address verifier. A bounded CPU run is plausible, but downloads,
  model-specific licenses and page latency must be frozen first. Our header
  candidate borrows the idea of separating regions, not Docling algorithms or
  weights. There is no measured Docling result here.
- **GraphDoc / DRGG**, submitted **2025-02-04**, ICLR 2025:
  [paper](https://arxiv.org/abs/2502.02501v1),
  [author repository](https://github.com/yufanchen96/GraphDoc).
  Models spatial, hierarchy and reading-order relations, rather than isolated
  boxes. The repository lists **MIT** for code; its page images and enhanced
  annotations derive from DocLayNet under **CDLA-Permissive-1.0**. At inspection
  it offers the dataset but says model implementation is forthcoming: do not
  describe it as an immediately runnable compact extractor. We did not download
  its archive or access its splits. Our proposed use is a small independently
  implemented line/block graph, not a claimed DRGG reproduction.
- **KNN-former**, arXiv upload **2024-05-08**, actually **EACL 2023**:
  [paper](https://arxiv.org/abs/2405.06701v1),
  [author repository](https://github.com/miafei/knn-former).
  Local graph-neighborhood attention and one-to-one entity matching are relevant
  inductive biases. The linked repository currently contains dataset directions;
  its POI terms are **non-commercial research only**, including derived data.
  No reusable model/checkpoint license was established. Do not import its
  portraits or derived features into production training/calibration. Local
  geometry-only experiments on our synthetic data can test the idea without
  importing that dataset or reproducing the paper's training setup.
- **GraphRevisedIE**, arXiv upload **2024-10-02**, actually **Pattern Recognition
  August 2023**: [paper](https://arxiv.org/abs/2410.01160v1),
  [author repository, redirected from AYSP](https://github.com/caop-kie/GraphRevisedIE).
  Revises document graphs and combines text, geometry and visual features.
  Code is **MIT**; a separate license covering its business-license dataset and
  downloadable trained weights was not established. It is a useful compact
  architecture reference, not a ready inference substitution: training and
  tensor/backend compatibility remain work. No performance or parameter-count
  result is claimed on our data.
- **Reading Order Inference for Complex Document Layouts**, **2026-07-01**:
  [paper](https://arxiv.org/abs/2607.01018v1).
  Scores line-transition graphs using language-model signals and solves a
  constrained path cover. Its historical-manuscript task is not bank KIE.
  Model/data redistribution licenses and an executable author release were not
  verified, so no run is proposed as an exact reproduction. A geometry-only
  neighborhood baseline would be substantially easier to bound locally; adding
  two language-model passes before measuring that baseline is premature.

**Larger extraction and decoding alternatives.**

- **SmolDocling**, **2025-03-14**:
  [paper](https://arxiv.org/abs/2503.11576v1),
  [author model card](https://huggingface.co/docling-project/SmolDocling-256M-preview/raw/main/README.md).
  The 256M VLM emits DocTags with structure and locations. At access, card YAML
  says **CDLA-Permissive-2.0**, while its model-summary prose says **Apache 2.0**.
  Record this conflict rather than silently picking the favorable license.
  Its listed training datasets have separate terms, not covered by this card.
  **Granite-Docling-258M**, released **2025-09-17**, is the named successor:
  [author card](https://huggingface.co/ibm-granite/granite-docling-258M/raw/main/README.md)
  consistently states **Apache-2.0** for the model. This is the preferable
  future local VLM comparison after pinning a revision. At 258M parameters,
  two-byte weights alone imply roughly 516 MB, excluding runtime/activations;
  this arithmetic is not a measured browser memory or latency result. Neither
  model guarantees correct customer/issuer attribution merely by producing tags.
- **LayoutLMv3** and **Donut** are older baselines, not 2024–2026 inventions.
  [Microsoft's LayoutLMv3 README](https://github.com/microsoft/unilm/blob/master/layoutlmv3/README.md)
  states **CC BY-NC-SA 4.0** for that project; do not inherit the broader parent
  repository's license. It needs OCR plus layout/image features and a suitable
  KIE head, and is unsuitable as an assumed commercially deployable drop-in.
  [Donut's author repository](https://github.com/clovaai/donut) is **MIT**, and
  describes OCR-free image-to-sequence extraction plus synthetic generation.
  A specific checkpoint and all underlying dataset terms still need independent
  verification; repo licensing alone is insufficient. Both require substantially
  more model integration than a type-only postprocessor and were not run.
- **XGrammar**, **2024-11-22**, revised **2025-05-12**:
  [paper](https://arxiv.org/abs/2411.15100v3),
  [Apache-2.0 author code](https://github.com/mlc-ai/xgrammar).
  Grammar-constrained token masking reduces structural generation errors and
  decoding overhead. **XGrammar-2**, first **2026-01-07**, revised
  **2026-08-05**, adds dynamic dispatch and grammar reuse:
  [paper](https://arxiv.org/abs/2601.04426v4).
  These are runtime components, not weights or POA datasets. Our inference:
  use explicit nullable fields, typed dates and source-span references if a
  local generative extractor is later trialed; validate semantic consistency
  separately. Valid JSON cannot prove the right person, preserve a missed
  apartment, establish authenticity or justify changing acceptance thresholds.

**OCR propagation and confidence.**

- **OHRBench**, first **2024-12-03**, revised **2025-08-30**, ICCV 2025:
  [paper](https://arxiv.org/abs/2412.02592v4),
  [author repository](https://github.com/opendatalab/OHR-Bench).
  Separates semantic OCR corruption from formatting corruption and measures
  downstream RAG effects. This supports measuring order/grouping errors
  separately from character recovery, not transferring RAG scores to KIE.
  A comprehensive license for its source PDFs and all derivative artifacts was
  not verified here; no data was downloaded. Our lawful alternative is fixed
  perturbations of already eligible synthetic TRAIN/DEV words, with natural OCR
  and publisher text-layer diagnostics reported separately.
- **ConfBench**, **2026-08-03**:
  [paper and licensing appendix](https://arxiv.org/html/2608.01792v1),
  [author dataset](https://huggingface.co/datasets/amazon/ConfBench).
  Investigates confidence across document degradation, modalities and models.
  Its paper warns that calibration and error ranking measure different things.
  The dataset is **CC BY-NC-4.0**, inherited from RealKIE-FCC-Verified; the
  paper itself displays **CC BY-NC-SA-4.0**. Neither is production-training
  authorization. No model weights are granted by that dataset license.
  Borrow the evaluation design: Brier score, calibration error and error capture
  at a predeclared review budget on independent eligible groups. No calibration
  was fitted in this experiment, and no verbal confidence was treated as truth.
- **Beyond Accuracy: Understanding Model Confidence in KIE with Conformal
  Prediction**, accepted **2026-02-19**:
  [author-hosted paper](https://www.dfki.de/fileadmin/user_upload/import/17320_s10032-026-00572-y.pdf).
  Uses split conformal prediction for entity uncertainty. Model/code/data reuse
  licenses were not established from this paper, so this is conceptual only.
  Our inference: future calibration must use a disjoint TRAIN calibration
  partition grouped by document identity/layout, never the existing reserved
  set. Marginal coverage under exchangeability is not a per-field security
  guarantee under new banks, countries or OCR distributions.

**What data actually supports this experiment.**

- Existing manifest-pinned synthetic **200 DEV captures / 800 cached OCR frames**
  are selected through `eval/poa_extraction_dev.load_frozen_dev`. It validates
  frame bytes and only decodes OCR cache records whose hashes belong to DEV.
  Synthetic generation uses GeoNames **CC BY 4.0** attribution. Reuse measures
  extraction, not OCR quality or current engine speed.
- [Synthesized's sample bank statement](https://www.synthesized.io/sample-bank-statement),
  **CC BY 4.0**, is one fictional identity, one template and three correlated
  variants. The already frozen PDFs, renders, truth and validated OCR outputs
  are hash checked, and native extraction/known-customer checks are rerun.
  Native PDF text is a separate diagnostic. No independent issue-date truth
  or representable US state exists in this schema. Nine annotated fields per
  variant remain the denominator, including full street/apartment, full ZIP,
  full masked account and both period endpoints.
- [FATURA v1](https://zenodo.org/records/8261508), **2023-08-06**, **CC BY 4.0**:
  existing pinned custom split is **400 TRAIN / 50 DEV** invoices; other layouts
  remain reserved and untouched. Invoice `BILL_TO` regions can assess block text
  recovery, but are not independent decomposed holder/street/city truth and do
  not establish a supported POA document class. No training was performed and
  no invoice KIE score is invented here.
- [Bankstatemently's author repository](https://github.com/bankstatemently/bank-statement-parsing-benchmark),
  **MIT**, pinned locally to `2d8d31d68dcedbf9028b87f6c7df286f53a6c7de`:
  only the existing three DEV files / ten pages are eligible. Their text layers
  support OCR checks; transaction benchmark truth is server-side. No API key,
  upload or server scoring was used, and the other two files remain untouched.
  Future manually audited local header annotations need their own frozen
  protocol before claiming customer/address extraction. These ten pages were
  not added to the semantic denominator in this round.

**Frozen experiments and every outcome.**

Both initial candidates use the upper quarter of page geometry, retain lines
of at most twelve words, and fall back to shipped type when evidence is absent.
C1 applies the existing six-class substring vocabulary to those lines; C2
requires an unambiguous generic title phrase. No customer name, source-specific
string or filename is a feature. The initial capture experiment also uses a
strict majority of the shipped picked frames. All constants were fixed before
inference; both candidates remain in the artifacts.

- Shipped baseline: document type **142/200 captures**, **559/800 frames**.
- C1 + majority: **184/200**, with **42 recovered / 0 regressed**; frames
  **728/800**, **170 recovered / 1 regressed**. The regression is retained as
  `poa_00642:2`: bank statement becomes cellphone account.
- C2 + majority: **150/200**, **11 recovered / 3 regressed**; frames
  **592/800**, **33 recovered / 0 regressed**. Capture regressions are
  `poa_00479`, `poa_00600`, `poa_01172`: municipal becomes utility.
- C1 public tagger **13/27 → 16/27**, rules **3/27 → 6/27**: document type
  **0/3 → 3/3**, every other field unchanged. C2 gives **no public gain**.
  Neither produces any complete nine-field document or holder/address set.
- Separate native-text diagnostic: C1 tagger **3/9 → 4/9**, rules **1/9 → 2/9**;
  C2 unchanged. These are not additional image successes.

A second freeze tests attribution without retuning either classifier:

- C1 on the **shipped first picked frame**: **185/200**, **43 recovered / 0
  regressed**. Bank **35/62 → 55/62**, municipal **37/68 → 60/68**, utility
  **70/70 → 70/70**.
- C2 on the shipped first picked frame: **150/200**, **8 recovered / 0 regressed**.
- Majority voting alone: **142/200**, **3 recovered / 3 regressed**. Reject it as
  a purported general improvement. Its municipal regressions explain why C2's
  initial capture result was worse than its frame-level evidence suggested.

There are **0 false-bank predictions among 138 non-bank captures / 552 non-bank
frames** for both original candidates and the capture attribution ablations.
This is a narrow diagnostic: the synthetic set has only bank/municipal/utility
truth classes, not adversarially forged headers or the other three classes.
The lone frame regression means C1 is not regression-free overall.

Every existing frozen synthetic metric and per-item flag remains equal:
key fields **184/200**, single-frame **563/800**; genuine acceptance **99/100**,
single-frame **334/400**; wrong-person, wrong-address, old and issuer-decoy
rejection each **25/25**, single-frame **100/100**. Public matching acceptance
is **3/3**; wrong-person, changed-house-number and old-document rejection each
**3/3**, including paired matching-accept plus negative-reject **3/3**.
No issuer-decoy public example exists. Verification was rerun independently
with native binaries, then carried unchanged through type postprocessing;
these numbers do not validate a new integrated acceptance pipeline.

All 200 native capture and 800 frame decisions are valid. The initial parity
check flattened OCR line boundaries and matched 791/800 native types; the
attribution audit uses the actual shipped newline semantics and matches
**800/800**. This diagnostic correction does not alter a candidate. A later
runner guard also prevents failed native outputs earning null-field matches
or rejection credit. The first run and its original script are preserved;
the repeat and ten focused tests validate the correction. No confidence
interval is claimed for the single public identity, and no speed claim is made.

**Recommended next bounded loops — our suggestions, not paper reproductions.**

1. Keep C1 as an experimental comparator, with first-picked behavior. Before
   considering integration, freeze new eligible document groups and explicit
   hostile-header/body counterexamples. Measure the other document classes and
   the existing single-frame regression. Do not choose a new header cutoff from
   this round and silently replace its results.
2. Build a tiny line/block adjacency graph using normalized vertical gaps,
   horizontal overlap and explicit addressee labels. Return one contiguous
   customer block with word indices; preserve the original text and require
   a nullable answer when issuer/customer evidence conflicts. Evaluate block
   selection separately from parsing fields. Use FATURA TRAIN for any learned
   weights and disjoint DEV layouts for selection; do not pretend `BILL_TO`
   gives complete POA truth. Avoid digit-count hacks and surname dictionaries.
3. Preserve an experimental country-neutral address block with country evidence
   and separate raw postal text. Add a jurisdiction-specific schema only with
   an explicit product decision and independent data. Never convert a five-digit
   ZIP to four digits or map a US state into a South African province. Output
   schema coverage and abstention separately from exact supported-field accuracy.
4. Freeze the same words under original, geometry-reordered, and controlled
   OCR-corrupted inputs; compare exact fields, hallucinated nonempty values,
   block confusion and negative-customer checks. Keep recognition and extraction
   errors distinguishable. Do not repair names/addresses using held-out truth.
5. If resources permit, pin Granite-Docling or selected Docling components for
   a bounded local diagnostic. Keep source-span grounding and nullable schemas,
   cap image size/token budget, count truncations/timeouts as failures, and record
   model revision/license/memory before running. A neural model must beat the
   cheap layout baseline on the same inputs, not a different easier denominator.

Rejected for this round: production weight training on research-only portraits
or ConfBench; unlicensed KNN checkpoints; broad US-support claims; free-form VLM
address invention; external document APIs; server-side bank benchmark submission;
changing security thresholds; confidence fitted on this DEV report; and reporting
only the winning candidate. The evidence supports a cheap document-type research
lead, not a completed general POA extractor.

## Second bounded loop: hostile context and raw recipient blocks

**Recommendation: integrate none of these candidates.** This separately frozen
counterexample gate exposes new C1 regressions across all six supported classes.
C2 is more robust on supported pages, but still promotes ambiguous and unsupported
documents to supported types. The additional raw-block selector produces grounded
partial text and explicit nulls, but no complete annotated recipient blocks.
These results do not change or pool with the first-round benchmark above.

The original `protocol.json`, `candidates.py`, candidate freeze, scorers, reports,
and attribution results remain unchanged. New research code uses only
`experiments/research_poa/stress_*.py`. All authored probe text, OCR, source-index
outputs, freezes, per-item reports and run artifacts stay owner-private under
`/tmp/docscan-research-poa-stress-v2`. Nothing was committed, trained or downloaded;
no shipping sources were edited and no TEST/reserved content was accessed.

**Counterexample protocol.** Before inference, 71 invented DEV pages and their
semantic labels were frozen with the runner, original candidate/configuration,
native binary and model hashes. Freeze SHA-256:
`136982a2381a3af23f9b72d6e6a632874b70eb1da9cd8e3bfa1f1906a4c8e6c2`.
Each supported class has eight conditions: clean, misleading issuer organization,
misleading customer organization, quoted header transaction words, quoted body
transaction words, split heading, title below the header cutoff, and no explicit
title. All 15 unordered pairs of conflicting supported titles are independently
labelled `other`: these are coequal composite examples with no primary document.
There are also one blank and seven unsupported documents. Author-defined intent
is the reference, not the classifier's keyword count. These adversarial examples
are a designed falsification set, not a representative accuracy sample.

The baseline is the same archived native `poa_fields` rules classifier used in
the original research build; native tagger type and the newline-preserving
Python port agree on **71/71**. C1/C2 run unchanged on each page, without voting.
All 71 native outputs are valid. The original exact/recovered/regressed/false-bank
accounting functions are reused. All predictions and confusion matrices are in
`stress_report.json`; no failures or inconvenient examples were removed.

- Baseline: **46/71** exact; C1: **33/71**, **5 recovered / 18 regressed**;
  C2: **52/71**, **6 recovered / 0 regressed**.
- False-bank classifications among **63 non-bank** pages: baseline **5**, C1
  **8**, C2 **4**. These are type errors, not measured verifier acceptances.
- Clean, split-heading, below-cutoff, and absent-title conditions each score
  **6/6 for all three**. These are end-to-end outcomes with fallback: split or
  absent titles do not demonstrate successful explicit-title detection.
- Misleading issuer names, customer organization names, and quoted header words
  each score baseline **6/6**, C1 **0/6**, C2 **6/6**. These are all **18 C1
  regressions**: keyword frequency in an organization name or quotation can
  override the actual title and the stronger body evidence.
- Quoted body words score baseline **0/6**, C1 **5/6**, C2 **6/6**. C1's remaining
  failure is insurance: its keyword vocabulary does not recognize the generic
  insurance-statement heading, so it falls back to the mistaken body classifier.
- All **15 conflicting-title** pages score **0/15 for all three**. C2's ambiguity
  fallback preserves a supported baseline type; it is not an `other`/null answer.
- The blank and three plain unsupported pages score **4/4 for all three**.
  Two unsupported organization-name examples, one header quotation, and one body
  quotation score **0/4 for all three**. An explicit-title phrase inside a company
  name or quotation can trigger C2; a body quotation can survive via fallback.
- Per supported class (eight pages each), baseline scores **7/8** throughout;
  C1 scores **5/8** for bank, municipal, utility, cellphone and lease, and **4/8**
  for insurance; C2 scores **8/8** throughout. On `other`, all score **4/23**.

The predeclared integration gate rejects a candidate with any new regression,
unsupported/ambiguous promotion, or supported-class failure. Both fail. This
does not prove C2 worsens the baseline on unsupported pages—it preserves those
failures—but it does rule out presenting it as a robust title/ambiguity solution.
The 142 non-type invariance checks passed by construction. No customer acceptance
or security pipeline was integrated or evaluated on these invented pages.

**Separate raw-block policy.** A single additional mechanism was frozen before
its inference: explicit recipient labels plus geometric adjacency, with no
external model, expected customer name, postal rules or annotation inputs.
Freeze SHA-256:
`aa096eac6e97b20b1b840d13e1c6f6d020a9dc8be0a74a2bac91e4b68d9ba423`.
Recognized labels include bill-to, billed-to, invoice-to, sold-to, billing address,
customer/address, recipient and account holder. It takes the same-line suffix
and nearest vertically adjacent lines using fixed median-line-height gaps and
horizontal overlap/alignment. Multiple anchors or competing geometric branches
return conflict/null; missing labels, invalid geometry, empty adjacency and the
six-line limit also remain explicit null outcomes. Stop labels are fixed in code.
No constants or patterns were tuned after either freeze.

The bounded cohort is **one Instance0 invoice from each of 40 eligible TRAIN
layouts**, **all 50 DEV invoices**, and **all three Synthesized DEV variants**.
The other 360 TRAIN invoices were excluded by budget before inference. All 90
invoice images and annotations were verified against the acquisition manifest;
only their named TRAIN/DEV archive annotation members were opened. Existing
validated PP-OCR detail output serves DEV; the same pinned reader/models ran
40 TRAIN pages with two workers, one thread per runtime and 30-second timeouts.
There were **zero OCR failures**. TRAIN is a diagnostic cohort, not fitted data.

FATURA is eligible when it has `BILL_TO` or `BUYER` annotations. Their union is
the spatial reference, and their text is scored by the unchanged public-document
normalization/token referee. All eligible pages, including nulls and conflicts,
remain in those denominators. An invoice without recipient annotations is
unscored for accuracy and retained separately; it is not a true negative.

- TRAIN: **28/40 eligible**, **20 selected / 8 no-label nulls**; the 12
  ineligible pages also return no-label nulls. Complete block text **0/28** and
  exact source-index sets **0/28**. Text-token precision **212/213 (99.53%)**,
  recall **212/411 (51.58%)**. Selected indices overlap **213/213** with recipient
  regions, recovering **213/410** recipient-region source tokens.
- DEV: **50/50 eligible**, **31 selected / 18 no-label nulls / 1 conflict null**.
  Complete block text **0/50** and exact source-index sets **0/50**. Text-token
  precision **320/320 (100%)**, recall **320/725 (44.14%)**. Selected indices
  overlap **320/320** with recipient regions, recovering **320/734** region
  source tokens. OCR-token counts and annotated-text counts differ; neither
  denominator is substituted for the other.
- No selected token centre falls in an annotated seller region on TRAIN or DEV.
  This is a limited spatial observation, not proof of perfect attribution on
  partially annotated invoices or unfamiliar layouts.
- Synthesized: **3/3 no-label nulls**, **0/3** exact concatenated holder/address
  blocks and **0/30** reference tokens recovered. Precision has no selected-token
  denominator (the existing scorer encodes it as zero). No recipient-region
  annotations exist here, so no spatial score is claimed for these variants.

Every selected token retains its source reference. Synthesized uses the original
word-array index unchanged. FATURA supplies only OCR line boxes: canonical
whitespace tokens retain the source line index, token offset and character span,
and share the actual line box. Word boxes were not invented. Consequently the
FATURA spatial metric has line-centre resolution; it cannot resolve mixed
issuer/recipient text within one OCR line. Raw text and all index/null/conflict
outputs are preserved in `rawblock/raw.json`, with all categorical results in
`rawblock/report.json`.

High precision on partial blocks is insufficient: the frozen policy has
substantial missing-label coverage loss and omits parts of every annotated
recipient block it selects. The stop-label policy can omit contact information
included in FATURA's block annotation; that does not justify silently shortening
the reference. This is country-neutral raw selection research only, **not US
address validation, decomposed-field recovery or full-field POA acceptance**.
No security thresholds, original benchmarks or scoring rules changed.

**Validation and next decision.** All ten original research tests and ten new
grounding/null/conflict tests pass. Native/port parity, source/input hashes,
candidate freezes, append-only documentation and unchanged original tracked
research files are checked. No speed, significance or independent-identity
generalization claim follows from these designed and layout-correlated cohorts.
Keep C1/C2 and the raw selector as frozen research comparators. If work continues,
a separately declared mechanism must distinguish actual titles from organizational
names/quotations and handle conflicting evidence explicitly; a block selector
must improve complete coverage on independently frozen layouts while preserving
grounding and abstention. This loop supplies counterexamples, not permission to
retune against them and call the same DEV results validation.
