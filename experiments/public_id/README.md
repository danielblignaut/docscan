# Public identity-document DEV benchmark

This adds an external camera-data check to the synthetic ID benchmark. It is a
small **DEV subset**, not the published MIDV-500 benchmark and not a SOTA claim.
No training, weight fitting, threshold selection, or TEST reporting is implicit.

## Acquisition and terms

Publisher: Arlazarov, Bulatov, Chernov and Arlazarov, *MIDV-500*, Computer Optics
43(5), 818–824 (2019), DOI 10.18287/2412-6179-2019-43-5-818-824.
[Paper](https://arxiv.org/abs/1807.05786),
[publisher data](ftp://smartengines.com/midv-500/),
[publisher licence](ftp://smartengines.com/midv-500/license.txt),
[per-document provenance](ftp://smartengines.com/midv-500/documents.pdf).
The publisher distributes its work under **CC BY-SA 2.5**. Attribution and
share-alike requirements apply to redistributed adaptations; no images or text
values are committed here. Source documents are published specimens, printed,
laminated and captured with phones. Do not treat the licence of a downloader
(such as the MIT `midv500` package) as the licence of its dataset.

The three source specimens are Azerbaijan's passport (Government of Azerbaijan /
Twofortnights / Wikimedia Commons), Germany's new passport (German Federal
Ministry of the Interior / Lumu / Wikimedia Commons), and Estonia's ID (Estonian
Government / Bonus bon / Wikimedia Commons). The publisher's provenance records
cropping and removal of specimen markings. These are public specimen identities,
not scraped customers' identity documents. The preserved provenance PDF covers
those modifications and original links.

The loader requests only ZIP directory and selected member byte ranges over
anonymous FTP, checks ZIP CRC, and pins every extracted/derived file by SHA-256.
It never executes dataset contents. Dataset files live outside git, owner-private.
FTP is not transport authenticated: local hashes freeze the first acquisition,
not a cryptographic assertion about the publisher. The publisher's whole-archive
MD5 list is saved but cannot verify a partial fetch; do not claim otherwise.

```sh
uv run --with pillow --with numpy --with opencv-python-headless \
  python experiments/public_id/fetch_midv500.py
python3 experiments/public_id/fetch_midv500.py --verify
python3 experiments/public_id/evaluate.py \
  --binary /absolute/path/to/text_v6 --models /absolute/path/to/models \
  --output /tmp/docscan-public-data/midv500/results/v6-rectified.json
```

## Fixed protocol

`midv500-dev-v1.json` freezes 18 frames: three layouts × three Apple capture
conditions (table, clutter, hand) × frames 01 and 15. This is a bounded first
iteration, not a representative random sample. Full raw frames and ground-truth
rectified documents are both materialised. Rectified inputs deliberately isolate
OCR from localization: annotation-assisted rectification is not a deployed
scanner feature or an end-to-end result. Use `--input frame` for raw-camera OCR.

Entire source layouts `32_lva_passport` and `42_svk_id` are reserved for future
lockbox evaluation; **their archives, images and annotations are not fetched or
opened by this code**. No frame-level random split may mix the same physical
specimen across splits. There is no training split yet. Before a separate final
TEST evaluator is created, it must audit holder identities against all training
and DEV sources without exposing TEST images/outcomes to the developer. The
current reservation therefore guarantees layout/source-document separation;
cross-corpus identity separation is a required preflight, not a claimed fact.

The fixed metric is annotated **field-text recovery**, with Unicode NFKC,
casefold and whitespace normalization, word boundaries, exact punctuation and
diacritics. MRZ fields are also reported separately. Truth omits labels and other
printed text, so this scorer cannot give full-page CER or hallucination rate.
It must not be used as evidence of correct key/value association, verification,
or complete MRZ acceptance. More recall is not evidence of safer acceptance.
Fields/frames of one specimen are correlated; the 18 frames do not represent
18 independent identities. No significance claim over individual fields.

Freeze this referee and manifest in a separate commit before scanner changes.
Results record scorer, dataset, executable and model hashes and retain failures
as empty readings. Processes are isolated per frame and capped at two workers,
with RTen and Rayon each using one thread. Wall times include process startup;
use the main benchmark's interleaved timing protocol for speed claims.

## Other sources checked

- [DocXPand-25k](https://github.com/QuickSign/docxpand): MIT generator,
  **CC BY-NC-SA 4.0 dataset**, not production training data. The 18GB multipart
  release was not downloaded. Its PRADO source materials carry separate rights.
- [DLC-2021](https://zenodo.org/records/6586764): publisher licence says
  **CC BY-SA 2.5** with Generated Photos attribution. Synthetic document
  recaptures, not face liveness. HTTP range downloads work, but no images fetched
  in this iteration. Generated Photos provenance must stay attached to derivatives.
- MIDV-2020's current official access form requires a separate user action;
  no access agreement has been accepted on the user's behalf.

For `scan`, ignore the text-recovery summary (MRZ is emitted separately). Use
`score_id.py RESULTS --output SCORED` for structured acceptance: all ten MRZ
fields must match the source annotations and the document kind must be correct.
An accepted passport with even one incorrect field is an `accepted_wrong`, and
unsupported Estonian fronts form six negative acceptance cases. Both exact
acceptance and wrong acceptance are reported over fixed denominators. This
scorer is also frozen independently before scanner edits.

Post-review provenance guard (24 October): `scan`, `text`, and `text_v6` now
accept `--models=DIR` and confirm their canonical model directory in each
reading. The evaluator passes that path, rejects older CLIs that cannot confirm
it, snapshots the executable for all trials, and checks model hashes before and
after inference. Structured scoring rejects duplicate/missing trials rather
than letting duplicates increase its fixed denominator. The reviewed rerun
reproduced all per-item text and field outcomes; the original aggregates remain
alongside `eval/evidence/public-id-2026-10-24/reviewed-provenance.json`.
