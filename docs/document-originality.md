# Document copy evidence and originality limits

**Current integration status:** the pixel assessment is wired into native/WASM
identity analysis and the demo's ID and face-document results (PRs #4 and #5).
The API and UI are present; the remaining gap is a sufficiently validated
original/copy decision. The subsequent [recapture detector implementation and
real-data experiment](research-originality-detector.md) supplies a runnable
full-image research classifier, but its false alarms and missed recaptures
prevent production promotion. Its score must not replace null confidence.

Research and implementation date: **2026-10-24**. This work adds
`docscan/src/document_evidence.rs` and the isolated
[`experiments/document_originality`](../experiments/document_originality/README.md)
study. It does not wire the module into scanners or change acceptance, identity,
face, liveness, OCR or security thresholds. The parent owns common
`DocumentResult`, file metadata, tampering assessment and UI integration.

**Result: no validated copy detector.** The pixel API exposes bounded,
descriptive measurements and an explicit unknown outcome. A candidate periodic
colour warning was rejected on procedural counterexamples before integration.
Neither successful OCR, a valid checksum, camera capture, nor absence of an
observed artifact proves physical originality or authentic document contents.

## Public Rust and serialization contract

```rust
pub fn assess_pixels(rgba: &[u8], w: usize, h: usize) -> CopyAssessment;

pub struct CopyAssessment {
    pub status: CopyStatus,
    pub is_copy: Option<bool>,
    pub confidence: Option<f32>,
    pub signals: Vec<CopySignal>,
    pub limitations: Vec<CopyLimitation>,
}
pub struct CopySignal {
    pub code: CopySignalCode,
    pub value: f32,
}
```

All types are public and derive `Debug`, `Clone`, `PartialEq` and
`serde::Serialize`; enums also derive `Copy` and `Eq`. Enum wire values use
snake_case. `CopyAssessment::default()` provides the same explicit unknown
state without pixel measurements. `CopyStatus` includes `unknown`,
`copy_indicated` and `original_indicated`; **only `unknown` is emitted by this
implementation**. The other variants reserve vocabulary for separately validated
evidence, not a promise that a detector exists.

`is_copy: null` means indeterminate; never coerce it to `false` or present it as
“original.” `confidence: null` means no calibrated confidence is available;
neither `0.0`, `0.5`, a colour fraction, nor a model logit is a substitute.
JSON serialization retains explicit nulls. A WASM caller using
`serde_wasm_bindgen` must select `serialize_missing_as_null(true)` if it needs
literal JavaScript nulls rather than that serializer's default undefined values.
This is a parent integration requirement, not a change made here.

An opaque grey pixel produces this subset of the full result:

```json
{
  "status": "unknown",
  "is_copy": null,
  "confidence": null,
  "signals": [
    { "code": "sampled_pixel_count", "value": 1.0 },
    { "code": "sampled_nonopaque_fraction", "value": 0.0 },
    { "code": "mean_rgb_range", "value": 0.0 },
    { "code": "near_achromatic_fraction", "value": 1.0 }
  ],
  "limitations": [
    "no_validated_copy_detector",
    "pixels_do_not_establish_physical_original",
    "metadata_unavailable_from_pixels",
    "tampering_not_assessed"
  ]
}
```

### Measurements, budget and input guards

Input is tightly packed 8-bit RGBA, exactly `w*h*4` bytes. Empty dimensions,
overflow, short buffers and trailing bytes return unknown, no signals, and
`invalid_rgba_dimensions_or_length`. The helper never reads invalid buffers.

The function reads an evenly spaced grid spanning both endpoints, up to 64
samples on each axis and **4,096 pixels total**, even for very thin images.
It uses no GPU, weights, external calls, image-sized allocations or decoding.
This is a work bound, not a measured phone/browser latency claim.

- `sampled_pixel_count`: sample count, including nonopaque pixels.
- `sampled_nonopaque_fraction`: fraction with alpha other than 255.
- `mean_rgb_range`: mean `max(R,G,B)-min(R,G,B)`, in byte levels, on opaque
  samples only. Not saturation in a perceptual colour space.
- `near_achromatic_fraction`: opaque-sample fraction with RGB range at most
  eight byte levels. Eight is a descriptive near-neutral tolerance, **not a
  copy threshold**. White paper, original monochrome forms and photocopies can
  all have high values. This quantity must not drive a copy warning.

Nonopaque samples are excluded from colour measurements; hidden RGB and
premultiplied alpha must not affect them. If none are opaque, both colour
signals are absent and `no_opaque_samples` is present. Nonopaque observations
add `nonopaque_samples_excluded_from_colour`. Subsampling adds
`spatial_sampling_may_miss_local_evidence`: this deterministic grid can alias,
miss local edits and include the background. It does not locate a document or
measure a hologram, print substrate, screen bezel or compression history.

Always retain `no_validated_copy_detector`,
`pixels_do_not_establish_physical_original`,
`metadata_unavailable_from_pixels` and `tampering_not_assessed`. They distinguish
absence of a detector from a detector that looked and found no issue.

### Parent integration

Attach the assessment to every ID document result, including unsuccessful
reads and each result in front/back flows. Prefer the captured/uploaded RGBA
before grayscale conversion, thresholding, enhancement or rectification; those
operations change the measurements. For no available pixels use the default
unknown assessment. Do not let copy fields influence the existing `accepted`
boolean, identity checks or security thresholds. Per-frame observations remain
correlated; repeated unknowns do not add evidence.

This module has no encoded-file input. File origin, byte-level parsing and
metadata must travel separately from the original upload; pixels decoded from a
PDF cannot reveal its producer, embedded signatures or revision structure.

## Research and data rights

Sources below are primary papers or author/publisher releases checked on
2026-10-24. Paper dates are distinguished from later arXiv upload dates. This is
a targeted survey, not a SOTA claim or reproduction of published accuracy.
No paper's headline score is used as our confidence. A code license, dataset
license, checkpoint license and rights in source assets are separate facts.
[`source-notices.json`](../experiments/document_originality/source-notices.json)
pins notices and the dataset record metadata read during this work.

**MIDV-Holo (ICDAR 2023).** The authors distribute artificial Utopia document
clips for hologram research. Their README states **CC BY-SA 2.5** and identifies
Generated Photos as the face source, encouraging its attribution. This is a
plausible specimen-based DEV source, not scraped personal IDs. Verification
needs registered video and known security features; generic reflectivity does
not prove the correct hologram. Keep the authors' and source-asset attribution
with any future derived research artifacts. No media was fetched here.
[Author release](https://github.com/SmartEngines/midv-holo),
[paper](https://doi.org/10.1007/978-3-031-41682-8_30).

**Weakly Supervised Training for Hologram Verification (ICDAR 2024).** Learns
holographic evidence from smartphone video with limited supervision. It is
relevant to localized, registered sequences, not a training-free still-image
boolean. We did not import code, download weights, reproduce the experiment or
establish a deployable checkpoint's independent rights.
[Paper](https://arxiv.org/abs/2404.17253),
[author code](https://github.com/EPITAResearchLab/pouliquen.24.icdar).

**Verification of Dynamic Holographic Behavior / MIDV-DynAttack (ICDAR 2025;
arXiv uploaded July 2026).** Adds dynamic attacks and evaluates expected hologram
appearance and variation. It exposes why detecting any shiny/dynamic patch is
insufficient. The implementation repository is **GPL-3.0**; none is copied into
docscan. Zenodo record **17079529** separately labels the dataset **CC BY-SA 4.0**.
Its metadata lists about 24.18 GB of video, 7.11 GB of crops and 14.08 MB of
tracking. Only record metadata was requested, using the API after the browser
fetch failed. The combined research pipeline also uses MIDV-Holo, whose own
notice remains applicable to its inputs.
[Paper](https://arxiv.org/abs/2607.06466),
[author code](https://github.com/EPITAResearchLab/pouliquen.25.icdar),
[publisher dataset record](https://zenodo.org/records/17079529).

**Temporal Modeling of Optically Variable Devices (ICDAR 2026; July 2026
preprint).** Models sequences rather than unordered frame evidence, addressing
swapping attacks through a span classifier or masked sequence modeling. Its
assumption of a secured acquisition channel is separate from document checks.
These learned, feature-specific methods require suitable videos and new model
validation; they do not justify a score in this weight-free pixel helper.
We did not establish reusable weight permissions or run this implementation.
[Paper](https://arxiv.org/abs/2607.06408),
[author release](https://github.com/EPITAResearchLab/pouliquen.26.icdar).

**Kunina, Sher and Nikolaev (Computer Optics 2023).** Looks for colour/moiré
patterns that cross a localized document boundary, with Fast Hough transforms.
That boundary condition helps distinguish capture artifacts from security
printing inside the document. Our independent hypothesis below deliberately
tests the cheaper global periodicity shortcut; it is **not** this algorithm.
The paper evaluates DLC-2021; that corpus's media license/splits were not
established here and no data was fetched.
[Publisher paper](https://computeroptics.ru/KO/Annot/KO47-4/470417.html).

**Chen et al. (Signal Processing 2022).** Models halftone distortions for
recapture/tamper localization using reference spectral relationships. A print
pattern is evidence about image formation, not proof that text was changed.
Trusted reference regions, printer/device variation and document type matter.
No code, weights or dataset from this work were used.
[Publisher paper](https://www.sciencedirect.com/science/article/pii/S0165168422002055).

### Feasible next DEV collection

The present test uses only original procedural graphics with no names, portrait
assets or identities. Its use requires no external dataset acquisition. For a
real pilot, author-published MIDV-Holo/DynAttack specimens are more appropriate
than arbitrary personal-ID scraping, subject to preserving each notice and
checking source-asset rights for the intended distribution/use.

Before importing media, establish a pinned TRAIN/DEV allowlist by whole specimen
and clip from the authors' split definitions. Inspect split configuration only;
do not inspect or fetch TEST/reserved samples. Keep all correlated captures and
derived crops of one specimen together. The large mixed `.tar.gz` bundles are
not a reason to ingest TEST to extract DEV: obtain a partitioned source or
perform a separate access-reviewed import. Nothing about the available
aggregate download grants an exception to this repository's lockbox rule.

A useful first local collection can instead use newly invented, visibly
fictional documents, with consented operators, captured once as printed
specimens and again as screen/print recaptures. Keep devices, illumination and
capture distance labeled; include legitimate grayscale originals, invoices,
bank-style statements, dense security linework, glossy stock and moiré-free
copies as counterexamples. Measure attack misses and bona fide false warnings
separately by device and specimen. Only after a frozen DEV study should an
independent calibration set be used to support a confidence field. Issuer
authenticity still needs a separate trust mechanism.

## Bounded experiment and rejection

Hypothesis: dominant chromatic periodicity can support a generic screen-copy
warning. Before execution, the protocol and candidate source were frozen and
hashed. The candidate uses Fourier power in R-G/B-G channels at periods 4–32
pixels; a conjugate frequency pair must hold at least 35% of total chromatic
power, with chromatic standard deviation at least four byte levels.

All **48 original synthetic DEV fixtures** were retained. The warning fired on
12/12 injected moiré-like patterns and **12/12 benign security-line patterns**,
and on 0/12 grey statement graphics and 0/12 colour-gradient controls. No real
recapture or bona fide identity document was measured. These are counterexample
counts, **not APCER/BPCER, calibrated probabilities or deployment accuracy**.
The surrogate positives are not physical presentation attacks.

Decision: reject this shortcut even as a copy warning. A cheap measure that also
flags legitimate patterned stock is not useful copy evidence. Do not fit the
threshold to these counterexamples and relabel them independent validation.
The rejected spectrum code remains only in the experiment; the Rust helper
contains no spectral detector or copy warning. Neither low chroma nor a quiet
spectrum proves originality, and neither establishes tampering.

Evidence: [frozen protocol](../experiments/document_originality/protocol.json),
[freeze receipt](../experiments/document_originality/evidence/periodicity-round1.json.freeze.json),
[all measured outcomes](../experiments/document_originality/evidence/periodicity-round1.json).

## Digital images, PDF metadata and bank statements

The broader request needs three separate outputs: copy assessment, observable
file metadata, and structured tampering assessment. **This pixel-only module
implements the first, with unknown status; it does not parse file metadata or
implement tamper detection.** Parent-owned integration must preserve that scope.

Recommended structured tampering fields are a status (`not_assessed`,
`inconclusive`, or evidence-supported `indicators_found`), nullable confidence,
individual findings with method and scope, and limitations. Avoid `is_tampered:
false` as the fallback for unsupported, missing or stripped evidence. A finding
must say what was observed, rather than convert a metadata anomaly into fraud.
This is a proposed integration contract, not a second exported Rust type here.

Metadata can describe declared capture time/device/software, image format and
dimensions, PDF producer/creator, page structure, and parser-observed revisions
or signatures. These are different from issuer-verified facts. In particular:

- Image metadata can be missing, stripped or rewritten. A camera tag cannot
  prove that the camera saw an original rather than a display or photocopy.
- JPEG artifacts, recompression and mixed font/image resources can arise from
  ordinary export, scanning or annotation. A basic metadata parser cannot turn
  them into a validated tampering verdict. Pixel decoding discards much of this
  evidence, so preserve original bytes separately with bounded parser limits.
- A bank-issued digital PDF can be legitimate without ever having a physical
  original. `is_copy` must not imply that such statements are unacceptable.
- Merely finding a signature dictionary is not cryptographic validation. If a
  parent parser checks signatures, distinguish integrity of covered bytes,
  coverage of later revisions, signer trust and issuer identity. Unsupported or
  unavailable verification remains explicit, not a green “signed” badge.
- OCR totals/date consistency and visible layout can flag a review question;
  consistent arithmetic and convincing appearance do not prove authenticity.

Those are scope constraints for a future evidence layer, not measured forensic
capabilities of this helper. No claim of detecting altered bank amounts,
copy-move, splicing, fake signatures, screen injection or synthetic PDFs is made.

## Validation and remaining work

The isolated crate includes the exact new Rust source by path, leaving
`lib.rs`, common types, UI and application manifests untouched. Seven Rust tests
cover malformed/overflowed dimensions, explicit null serialization, thin and
large-frame sampling bounds, neutral tolerance, transparent/partially transparent
pixels and non-inference of originality from grey/colour input. Four Python
tests verify the bounded candidate and its counterexample rejection.
Clippy with warnings denied, rustfmt, and an isolated `wasm32-unknown-unknown`
compile check also passed. An evidence audit recomputed all 48 fixture hashes,
warning bits, cohort denominators and numeric results, and verified the frozen
protocol/source hashes. WASM compilation is not browser execution or parity.

Parent integration must still test all native/WASM result paths and null
serialization. No application-wide build or accepted-document benchmark gain is
claimed by this scoped change. No TEST/reserved data access, trained/downloaded
weights, acceptance-threshold change, commits, branch changes or PR operations
were performed.
