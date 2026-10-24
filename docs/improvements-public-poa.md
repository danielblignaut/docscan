# Public POA date-range correction — 24 October 2026

This bounded DEV change addresses the shared-year range failure documented in
`experiments/public_poa/REPORT.md`. It changes date parsing and consistency only;
it does not change a model, scorer, acceptance threshold, vote weight, address
policy, or document-type classification. The external sample is one fictional
US identity in one bank-statement layout with three correlated variants. It is
not evidence of South African deployment accuracy or document authenticity.

## Failure and correction

An invented minimal example, `April 2 April 26, 2024`, reproduces the ambiguity:
the old scalar parser can read the interior `2 April 26` as a date in 2026.
With a printed dash, it instead misses the first endpoint. The new regression
failed against the original Rust implementation before the fix.

- `docscan/src/poa/verify.rs` resolves two written month/day endpoints sharing
  an explicit four-digit trailing year before trying scalar short-year dates.
  Both day-first and month-first forms work, with a separate dash or `to`, and
  with a dash lost by OCR. Each endpoint retains its own word offsets. Valid
  standalone two-digit years remain supported; no year rollover is inferred.
- `docscan/src/poa/mod.rs` reads the original line before a partial tagger span.
  A whole range tagged `DOC_DATE`, even if its span omits the dash, retains both
  period endpoints and uses the end as its document date. Keeping that date
  evidence prevents capture's existing rules fallback from replacing an old
  statement date with a recent transaction.
- `mod.rs` and `capture.rs` share a recency-date selection helper that abstains
  on a reversed period, including after frame voting. The contradictory fields
  remain inspectable; the blind field verifier reports the ordering failure.
- `rules.rs` adds an old-issue-date regression. Its extraction policy is
  unchanged: external ranges without the existing period/from-to labels still
  do not populate rules' period fields.

## Measured before and after

The unchanged external referee compares the original compatible binary snapshot
against the date fix on the same pinned sources, rendered pages, model bytes,
reference clocks, field mapping and negative customers.

- Image tagger exact fields: **10/27 → 13/27**. Period start improves **0/3 →
  3/3**; period end stays **3/3**. Clean and scanned each improve **4/9 → 5/9**;
  fax improves **2/9 → 3/9**. Holder remains 2/3, city 2/3, issuer 3/3; full
  street, postal code, full masked account and document type each remain 0/3.
- Rules exact fields stay **3/27**, all issuer matches. All other scored rules
  fields stay 0/3. Complete field sets and blind holder-plus-address remain
  **0/3** for both methods; blind verification still accepts 0/3.
- Image known-customer matching acceptance stays **3/3**. Wrong-person,
  wrong-house-number and old-document rejection each stay **3/3**, with 3/3
  paired matching acceptance plus rejection for each class and 3/3 stale-date
  evidence. No new negative acceptance occurs.
- Separate native-text diagnostic: tagger **1/9 → 3/9**, recovering both period
  endpoints; rules **1/9 → 1/9**. Matching acceptance improves **0/1 → 1/1**.
  Each negative stays rejected 1/1, while paired matching-and-rejection improves
  **0/1 → 1/1**. The old-date case now has stale-date evidence **0/1 → 1/1**,
  instead of rejection caused by the incorrect future date.
- The three reversed tagger image periods are gone. The native document date
  equals the parsed period end rather than an erroneous future date. The
  protocol does not independently score issue dates, so this is a diagnostic,
  not an additional exact-field success. All three image OCR word arrays and
  page dimensions are identical to baseline.

On the existing **200-capture / 800-frame cached DEV extraction harness**, every
metric and per-item outcome is unchanged: key fields **184/200**, document dates
**196/200**, genuine acceptance **99/100**, and each of wrong-person,
wrong-address, old and issuer-decoy rejection **25/25**. Single-frame key fields
remain **563/800**, genuine acceptance **334/400**, and each negative rejection
**100/100**. Mean frames read remains **2.85**. The unchanged paired comparator
reports **no change**, with its expected warning about uncommitted source.

These are bounded DEV observations. Improved known-customer verification does
not repair the remaining blind holder/address extraction failures.

## Validation and provenance

Native tests cover explicit and lost separators, both written date orders,
fully written endpoints, legitimate short years, word offsets, leap dates,
explicit cross-year ranges, missing years, partial endpoint spans, a whole
native-text date span with its separator omitted, old/future/reversed ranges,
old issue dates beside recent payment dates, and capture voting with an old
range beside a recent transaction. No source identity or source truth values
are regression fixtures.

All **33 POA Rust tests** pass. The frozen external referee's **eight tests**
pass, including failed-read denominators and reject-all paired accounting. No referee or protocol file was
edited. TEST/reserved data was not opened or evaluated.

The separate build target is
`/tmp/docscan-public-data/poa-date-fix-target`. Raw documents, text, predictions,
binary snapshots and detailed build evidence stay outside git in
`/tmp/docscan-public-data/poa-date-fix-v3`. The existing compatible baseline and
the first incompatible-binary run remain intact in their original directories.

Two additional candidate setup/build records are retained, not overwritten:
`poa-date-fix-v1` is a setup failure (a concurrent unrelated Rust edit stopped
the candidate copy, but the shell continued and froze the initially prepared
incompatible binaries). It yielded 0/27 fields for both methods and no valid
customer decisions, not a candidate accuracy result; the cached DEV command
also failed on the model feature-width mismatch. `poa-date-fix-v2` used the
correct candidate binaries and completed both evaluations, but its full-source
provenance was limited by concurrent `text_v6.rs` edits. The final v3 rebuild
follows the parent's explicit hold on Rust edits. All 41 recorded Rust/example/
Cargo inputs stayed unchanged through that build; the gazetteer matches the
baseline and build commit. Its base is `7064285e7a462aeec588350278265512d4612495`
plus these uncommitted POA changes. The final pre-inference freeze SHA-256 is
`2e41aea2a8bae7bb7941a0004e70a8e71c1ea0fb1dc1936ae726b552b4558a23`.
The frozen harness itself was unchanged through all rounds.

Reproduction commands, run from the repository root:

```sh
CARGO_TARGET_DIR=/tmp/docscan-public-data/poa-date-fix-target \
  /home/dan/.cargo/bin/cargo test --manifest-path docscan/Cargo.toml \
  --locked --release --lib poa:: -j2
CARGO_TARGET_DIR=/tmp/docscan-public-data/poa-date-fix-target \
  /home/dan/.cargo/bin/cargo build --manifest-path docscan/Cargo.toml \
  --locked --release --example poa --example poa_fields --example poa_capture -j2
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s experiments/public_poa -v
```

For extraction-only DEV comparison, run `eval/poa_extraction_dev.py` with
`DOCSCAN_EXAMPLES` pointing first at the frozen compatible baseline's `bin/`
and then at the new run's `bin/`. It validates and reads only the pinned 200 DEV
captures and 800 cached OCR frames. The output files are
`/tmp/docscan-public-data/poa-date-fix-dev-before.json` and
`/tmp/docscan-public-data/poa-date-fix-dev-after.json`; use the unchanged
`bench/compare.py` for the paired comparison. This does not rerun OCR, camera
capture, page detection, browser latency or mobile performance.

For the external round, follow the existing `experiments/public_poa/README.md`
workflow in a fresh data root. Copy the already pinned public sources, run
`prepare`, replace its three executable copies with the isolated release build
before `freeze`, then run `evaluate` and `evidence.py` with that same
`--data-root`. Never overwrite a completed round or replace frozen binaries.

## Remaining scope and risks

The change does not address five-digit US postal-code coverage, apartment
preservation, holder/city span selection, masked accounts confused with balances,
or utility keywords in transactions overriding the bank-statement heading.
No country policy was broadened. Missing US-state representation and missing
independent issue-date/suburb truth remain unscored coverage gaps.

Shared-year inference requires two written month/day endpoints and an explicit
four-digit final year. No new support is claimed for shorthand with only one
month, attached range delimiters, multiline ranges or two-digit shared years. Ambiguous
cross-year text without both years is not repaired. Reversed periods deliberately
withhold recency evidence even if another extracted date looks plausible, which
can reject a genuine document whose endpoint was misread. An absent endpoint
cannot support an ordering check. This is a surgical parsing change, not a
complete semantic treatment of every unlabeled transaction date.

The three external variants are one independent identity, not three independent
documents; no confidence interval or general accuracy claim is warranted. The
external protocol has no issuer-decoy example. Existing DEV synthetic checks
cover that negative class, but neither experiment validates real documents.
