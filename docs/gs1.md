# Structured GS1 decoding

Barcode results retain their raw payload and AIM symbology identifier. The demo
extracts GS1 application identifiers directly from explicit GS1 element strings,
human-readable `(AI)value` strings and uncompressed Digital Link URLs. It never
follows a URL, looks up a product or uploads the barcode.

The decoder retains Code 128 FNC1 separators and GS1 AIM markers. Ordinary
numeric Code 128 data is not guessed to be GS1. Human-readable AI notation is
labelled separately: its presence does not establish a GS1 carrier.

## Data and checks

The parser uses 541 AI definitions generated from the official GS1 syntax
dictionary, pinned at `scripts/gs1/source.json`. GTIN, SSCC, lot, serial, expiry,
weights, amounts and cellular identifiers (8040/8041 IMEI/IMEI2) are available
without OCR where encoded. Values remain strings so leading zeros are retained.

The validation scope is deliberately explicit: component lengths/character
sets, selected checksums and calendar rules. Other dictionary linters are
reported in `uncheckedRules`; there is no claim of full GS1 conformance,
registration, ownership or issuer authenticity. Required related AIs missing
from one barcode give an `incomplete` status because other carriers on the same
item may hold them. Normalized `identifiers` are exposed only for parsed results;
invalid, unsupported and incomplete results retain observations without promoting
them to normalized identifiers. Incompatible or repeated AIs are reported; conflicting identifiers are
not silently selected.

Only predefined-length element strings are split without FNC1. Variable-length
and non-predefined fields require separators when followed by another field.
Numeric-looking substrings inside lot/serial values are never guessed to be
new AIs. Unknown AIs produce an unsupported result with the raw barcode retained.

Dates preserve the two-digit year and day-zero/end-of-month designation; no
century or freshness verdict is invented. Scaled quantities use decimal strings.
Numeric currency codes are extracted but not verified against an issuer.

Digital Link path qualifiers must follow the dictionary ordering. Duplicate AI
values, invalid percent escapes and invalid query attributes are reported.
Compressed Digital Links are not supported. URI parsing does not trust the host,
resolve the link or establish that the resource exists.

Input is capped at 8,192 characters and 128 fields. Fields retain source offsets
where applicable; URI query offsets are `-1` because decoding changes positions.
Reports expose errors and parsing limitations alongside fields.

## Reproduce

```sh
python3 scripts/gs1/generate.py
node --test demo/test/gs1.test.mjs
cargo test --manifest-path docscan/Cargo.toml --lib gs1_fnc1 -j2
```

The native regression decodes procedural GS1-128 bars with an internal FNC1,
and a plain Code 128 whose literal payload resembles an AIM prefix. Tests also
cover Digital Link, missing separators, malformed dates, checksums, ambiguous
carrier context and bounded inputs.

Sources: [GS1 syntax dictionary](https://github.com/gs1/gs1-syntax-dictionary),
[GS1 application identifiers](https://www.gs1.org/gs1-application-identifiers).
The dictionary is Apache-2.0, copyright GS1 AISBL; the full licence is retained
in `scripts/gs1/LICENSE` and served in `demo/public/licenses/gs1.txt`.

DataBar (`]e0`) is not currently interpreted: rxing can use that identifier for both bare GTIN and element-string formats. These readings remain raw codes rather than guessed GS1 fields.
