# External POA DEV baseline — 24 October 2026

The compatible current-source tagger recovered **10/27 annotated fields**;
rules recovered **3/27**. Neither recovered all fields or a complete holder/address
on any of the three images. All three image processes completed successfully.
This is one fictional US identity and one layout rendered three ways, so the
counts demonstrate specific coverage gaps, not population accuracy.

All repository changes for this task are new files under `experiments/public_poa/`.
No shipping code was changed, no commit was made, no TEST data was accessed, and
nothing was trained. Raw downloads, independent truth, rendered pages, OCR words,
predictions and binary copies remain in owner-private directories under
`/tmp/docscan-public-data/`.

## Aggregate results

The nine fixed fields are defined in `protocol.json`; each gets three opportunities.

- **Tagger:** holder 2/3; full street 0/3; city 2/3; postal code 0/3; issuer 3/3;
  full masked account 0/3; document type 0/3; period start 0/3; period end 3/3.
  Clean and scanned each scored 4/9; fax scored 2/9. Full field sets: 0/3.
- **Rules:** issuer 3/3, every other scored field 0/3. Each variant scored 1/9.
  Full field sets: 0/3.
- **Blind holder plus full address:** 0/3 for both methods. The blind field
  verifier also accepted 0/3 for both methods.
- **Known-customer verification:** matching accepted 3/3; wrong-person rejected
  3/3; wrong-house-number rejected 3/3; old rejected 3/3. Each negative has 3/3
  paired matching acceptance plus negative rejection, and the old cases have
  stale-date evidence 3/3. These are single-page checks on unchanged OCR words;
  no cross-variant capture voting is included.
- **Clean PDF text-layer diagnostic, separate denominator:** rules 1/9 and
  tagger 1/9. Matching customer accepted 0/1. Each negative rejected 1/1, but
  paired matching-accept-and-reject is 0/1 for each, and stale-date evidence is
  0/1. Those negative rejections therefore do not demonstrate discrimination
  or correct old-date reasoning in this diagnostic.

The first run using the supplied release artifacts failed on all three inputs:
`input "feats" is invalid: expected dim 2 to have size 50 but got 32`.
Both methods retain 0/27 in that failed artifact run because the combined example
never emitted a JSON reading. Verification has 0/3 valid decisions per case,
0/3 credited rejections, and 3/3 failed/no-decision entries. This measures an
artifact incompatibility, not scanner accuracy. It is retained alongside the
compatible run in `results/stale-binaries-baseline.json`.

## What failed, and evidence

The normalised literal holder, full street, city, postal code, issuer and full
masked account were **all present in all three OCR texts**. Every failed scored
lexical field therefore had its exact truth string available somewhere in the
OCR output. This localises those failures to extraction/selection or word layout,
rather than absent text recognition. It does not imply that all document OCR is
perfect, or that text presence proves correct holder association.

1. **Address extraction is tied to South African postcodes.** Rules require a
   valid four-digit code (`docscan/src/poa/rules.rs`, `postal_in` and
   `address_block`); tagger span selection also filters to four digits
   (`docscan/src/poa/mod.rs`, `fields_from_spans`). All three correct five-digit
   US codes were ignored. Other four-digit text, originating from transaction
   dates or the year, was selected as a postcode and given a South African
   province. Rules selected transaction text as an address in two variants.
   This is an unsupported-locale/selection defect; do not “fix” it by truncating
   the true ZIP or pretending the US state is a South African province.
2. **Holder and apartment selection fail despite legible text.** The tagger
   dropped part of the apartment from every full street, and missed the holder
   and exact city in fax. Native text-layer input still failed these fields,
   so better OCR alone is insufficient; layout and span boundaries matter.
3. **Masked account is confused with balances.** Rules missed it throughout.
   The tagger selected a monetary balance in two image variants, nothing in the
   other, and only the unmasked tail in the text-layer diagnostic. The frozen
   scorer requires the full independently annotated printed mask, not tail-only
   success. Rules' `account_number` requires particular account-label forms;
   tagger account selection lacks sufficient semantic discrimination here.
4. **Document class is contaminated by transaction content.** Both methods
   classified every bank statement, including native-text input, as a utility
   bill. `document_type` in `docscan/src/poa/mod.rs` counts whole-page keywords
   and resolves ties by candidate order. Utility-related transaction content
   competes with bank summary terms; the document heading carries no special
   priority. This code inspection explains the observed confusion without
   requiring an OCR hypothesis.
5. **A shared-year date range becomes an impossible period.** The tagger emitted
   a period start after its end in all three images. The start's year comes
   from reading the right-hand day as a two-digit year for the left date.
   Code inspection points to `span_date` expanding the incomplete first span
   to its line, where `verify::find_dates` accepts a day/month/two-digit-year
   subsequence across the range boundary. The native-text tagger omits the range
   separator from its date span and instead places this future date
   into `document_date`, rejecting even the matching customer as future-dated.
   The image customer checks succeed because they use the correct period end;
   they do not validate the erroneous start. Rules require explicit period/from-to
   labels for period extraction, leaving both endpoints unfilled here.

## Next general fix

Prioritise **semantic parsing of shared-year date ranges and period consistency**:
recognise range separators and repeated month names before interpreting a
short-year date, propagate an explicit common year only within that range, and
prevent a reversed period from silently supplying a trusted date. Preserve the
existing distinction between statement/issue dates and transaction/payment dates.
This addresses a failure reproduced with native text and image OCR, without
memorising the sample's identity, layout or date.

A future implementation should get its own change and regression cases using
new invented ranges, including two fully written dates, shared years, legitimate
two-digit years, old statements with recent transactions, and future/reversed
periods. Re-run this unchanged DEV referee and existing POA DEV checks. No such
implementation or efficacy claim is part of this round.

Separate follow-ups are country-aware address abstention, full-unit preservation,
account-label versus amount discrimination, and heading-aware document typing.
This US sample does not justify relaxing South African acceptance policy.

## Provenance and verification

- Publisher: [Synthesized bank-statement sample](https://www.synthesized.io/sample-bank-statement),
  fictional synthetic test data, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  JSON and publisher-page claims were verified; clean PDF text-layer presence
  and scan/fax absence were checked. Four data assets total: 384,903 bytes;
  no invoice Parquet or additional document corpus downloaded.
- Initial freeze: `5bf5ff1c67724c028e4d8435ac2f81c0625a50f3f0cfb14242fb221209dd99fa`.
  Compatible-run freeze: `5d744a863f160d2dc28c9cabdf0cde1f87ca1905b614103b2af24acfcc89f25b`.
  Referee, protocol, source, rendered-input and model hashes match between runs;
  only executable pins and run metadata differ. Both freezes preceded inference.
- Compatible binaries were built with `--locked --release` in a separate target
  directory. Source hashes were unchanged through compilation; compiler version,
  source file hashes and command are in `results/current-build-provenance.json`.
  The generic freeze record's artifact-provenance note is conservative boilerplate;
  this separate build record establishes provenance for the compatible run.
- Eight referee unit tests passed, including malformed output, process failure,
  timeout, missing-read denominator preservation, no rejection credit on failure,
  exact ZIP/unit/mask checks and reject-all paired accounting. Python/JSON parsing
  passed. Both end-to-end harness runs and both post-run evidence exports completed.
- `results/current-baseline.json` is the aggregate baseline;
  `results/current-evidence.json` records per-variant failure categories without
  source text. The old artifact run has equivalent retained files.

There is no independently annotated issue date, US-state representation in the
province enum, issuer-decoy challenge, broader identity/layout diversity, or
real-document validation. These are explicit gaps, not inferred correct fields.
