# Proof-of-address extraction

The tagger and layout rules read fields from OCR words. Capture combines a
maximum of four frames; customer verification then checks the printed name,
holder-linked address and document age against the supplied customer.
This is text extraction and consistency checking, not document authenticity
verification.

Document dates need semantic and geometric evidence. A value below an explicit
`ACCOUNT DATE`, `STATEMENT DATE` or issue-date heading may belong to that column
even when a `DUE DATE` heading is immediately to its right. A generic `DATE`
transaction-table heading does not supply this evidence. Old issue dates stay
old; a recent payment date must not replace them to make a document acceptable.

Written ranges with repeated month names may share one explicit trailing year,
including when OCR loses the dash. Resolve that year on the original line before
reading partial tagger spans. A whole range tagged as a document date retains
both endpoints and uses its end for recency; a reversed period supplies no
trusted date. Never infer an unprinted year rollover to repair its order.

Field voting has deterministic tie breaks. Agreement that a required field is
missing does not end a capture after two frames: later frames may recover the
text, up to the existing four-frame limit. Unicode names are preserved, and
ASCII label matching keeps offsets into the original OCR text valid.

For validation, use only DEV while improving the scanner; `bench/README.md`
defines the held-out-data rules. An extraction-only comparison can reuse the
same DEV OCR words for both binaries and run `bench.suites.poa.capture_run`
and `score` unchanged. Report that scope explicitly: it does not remeasure
page detection, OCR, browser latency or real-document performance. The normal
end-to-end command is `bench/run.sh --suite poa --split dev --jobs 2`.

DEV extraction check, 23 October 2026: the 200 captures / 800 frozen OCR frames
from `e5c9cc7` were scored before and after these changes with the unchanged
PoA scorer. Blind key fields improved from 182/200 to 184/200; document dates
from 193/200 to 196/200. Genuine acceptance stayed 99/100 and each negative
class stayed 25/25 rejected. Single-frame key fields stayed 563/800. Mean
frames read rose from 2.83 to 2.85. The paired comparison reports no
statistically significant change at 95%; these are small DEV gains, not a
claim of state-of-the-art accuracy. TEST was not accessed for this change.
