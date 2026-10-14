# Document formats the scanner has to read

Confidence markers: **[verified]** = seen on an official specimen or an
authoritative spec; **[documented]** = stated by secondary sources that agree
with each other; **[unverified]** = our best guess, the synthetic corpus follows
it but a real document may differ. Treat every **[unverified]** item as a
parser that must be tolerant, and confirm it against a real card in the spike.

## 1. South African identity number (all SA documents)

`YYMMDD SSSS C A Z` — 13 digits. **[documented]**

| Digits | Meaning |
| --- | --- |
| 1–6 `YYMMDD` | Date of birth. No century digit: resolve with "not in the future" (≤ current YY → 20YY). |
| 7–10 `SSSS` | Sequence; `0000–4999` female, `5000–9999` male. |
| 11 `C` | Status: `0` SA citizen, `1` permanent resident, (`2` refugee, per Wikipedia/IRB). A permanent resident's number changes 1→0 on naturalisation. |
| 12 `A` | Formerly a race classifier; now `8` (or `9` historically). Do not validate beyond "digit". |
| 13 `Z` | Check digit — **standard Luhn mod 10** over the first 12 digits. |

Luhn exactly as used (equivalent formulations):

* Standard Luhn: append nothing; walking the first 12 digits from the **right**,
  double the 1st, 3rd, 5th… (i.e. digits 12, 10, 8, 6, 4, 2 counted from the left),
  subtract 9 from any doubled value > 9, sum all 12, `Z = (10 − sum mod 10) mod 10`.
* The equivalent recipe on Wikipedia ("National identification number" › South Africa › Validation): `A` = sum of digits 1,3,5,7,9,11; `B` = the number formed by
  digits 2,4,6,8,10,12 concatenated, × 2; `C` = sum of the digits of `B`;
  `Z = (10 − (A + C) mod 10) mod 10`.

Both are implemented (`synth.sa_id_check_digit`, and the second in `verify.check_truth`)
and agree; test vectors `9807055009087` (Wikipedia's example) and `8001015009087` are valid.

Sources: https://en.wikipedia.org/wiki/South_African_identity_card (ID number
section, citing IRB Canada RIR https://www.irb-cisr.gc.ca/en/country-information/rir/Pages/index.aspx?doc=454798),
https://en.wikipedia.org/wiki/National_identification_number (South Africa),
https://github.com/Ciciodean/sa-id-barcode-tool (`luhn_check_digit`).

## 2. SA smart ID card (2013–)

### Front **[verified on the DHA specimen]**

Header `REPUBLIC OF SOUTH AFRICA` / `NATIONAL IDENTITY CARD` (not "IDENTITY CARD"),
SA flag top-left, portrait on the **right**, signature under the portrait. Labels
(English, each followed by a colon, value on the next line):

`Surname:` `Names:` `Sex:` `Nationality:` `Identity Number:` `Date of Birth:` `Country of Birth:` `Status:`

Formats on the specimen: Sex `M`/`F`; Nationality `RSA`; Identity Number as 13
unbroken digits; Date of Birth `DD MON YYYY` upper case (`16 JUL 1969`); Country of
Birth `RSA` (a 3-letter code); Status `CITIZEN` (or `PERMANENT RESIDENT`).
**No MRZ on the front** (Regula: "a left-aligned portrait and no MRZ"; the
specimen confirms).

### Back **[verified on the DHA specimen]**

`Conditions:` text block top-left (issued by the Department of Home Affairs under
the Identification Act 68 of 1997), `Date of Issue: YYYY-MM-DD` top-right
(`2013-08-30`, ISO format on the specimen), a multi-layer `RSA` image with a
5-digit security number, the 9-digit card number, a ghost portrait, and two
barcodes along the bottom: a **Code 39** (left, smaller) and a large **PDF417**
(right). **No MRZ on the back either** — the card is not an ICAO TD1 document, so
the TD1 layout below is only for completeness.

### Code 39 **[documented]**

Encodes the 13-digit identity number only, no check character
(Wikipedia "Barcode Data"; Ciciodean tool; Regula: "readable if your solution supports Code 39 and PDF417").

### PDF417 **[documented field list; separator and date formats unverified]**

Wikipedia (citing DHA's smart-card page http://www.dha.gov.za/index.php/id-smart-card)
lists the content, in this order:

1. Surname
2. Names
3. Sex
4. Nationality
5. Identity number
6. Date of birth
7. Country of birth
8. Status (citizen / permanent resident)
9. Date of issue
10. 5-digit security number (the one shown with "RSA" in the multi-layer image)
11. 9-digit card number
12. the sequence `1234567890` repeated to fill the remaining capacity

* **Separator**: widely reported as `|` (pipe), plain text, unencrypted — the
  community test layout is `SURNAME|NAMES|SEX|NATIONALITY|ID|DOB|COUNTRY|STATUS|ISSUE|SECURITY|CARD|1234567890…`
  (https://github.com/Ciciodean/sa-id-barcode-tool). That tool states the exact
  byte layout is proprietary to DHA. **[unverified against a real card]**
* **Encryption**: none reported for the ID card — the content is visible-data
  plain text that commodity scanners decode (Regula: "The PDF417 code also stores
  visual data—name, gender, nationality, place of birth"). Contrast: the SA
  **driving licence** PDF417 *is* RSA-encrypted (Dynamsoft / b4x threads) — a
  different document, do not confuse them. **[documented]**
* **Date formats inside the PDF417**: not published anywhere we found.
  The synthetic corpus uses the card-face formats — `DD MON YYYY` for date of birth
  and date of issue (`14 MAR 1990`). A parser should accept `DD MON YYYY`,
  `YYYY-MM-DD`, `YYYYMMDD` and `DD/MM/YYYY`, and cross-check DOB against digits 1–6
  of the ID number. **[unverified]**
* **Sex**: `M`/`F` in our corpus; may be `MALE`/`FEMALE`. **[unverified]**
* A parser should split on `|`, take the first 11 fields, ignore the filler, and
  validate field 5 with Luhn.

## 3. SA green bar-coded ID book (1986–2013 issue, valid until 31 Mar 2028)

* **Barcode symbology: Code 39**, encoding the 13-digit ID number.
  **[documented]** — the BlinkID React Native issue titled "Scanning Code39
  (South African ID Book)" (https://github.com/BlinkID/blinkid-react-native/issues/47)
  is the only primary-ish source found; it agrees with the smart card's use of
  Code 39 for the same number. No source found says Code 128 or ITF for the book
  (Regula's "code 128" sentence refers to the SA *crew member certificate*).
* Wikipedia ("National identification number" › South Africa): the first page
  carries "the national identification number (also in barcoded format), name of
  bearer, district or country of birth, as well as a photograph". **[documented]**
* Exact layout and label wording (from general knowledge of the book, no specimen found **[unverified]**):
  bilingual Afrikaans/English labels, `I.D. No.` with the number printed as
  `YYMMDD SSSS CAZ`, the barcode near the top, portrait, then
  `VAN/SURNAME`, `VOORNAME/FORENAMES`,
  `GEBOORTEDISTRIK OF -LAND/DISTRICT OR COUNTRY OF BIRTH`,
  `GEBOORTEDATUM/DATE OF BIRTH` (`YYYY-MM-DD`), `DATUM UITGEREIK/DATE ISSUED`.
  Personal data on real books is often in a typewriter / handwritten-style font
  (Regula), so OCR of names from the book is harder than the barcode — read the ID
  number from the barcode and the printed digits and cross-check.

## 4. ICAO 9303 machine-readable zones

Source: ICAO Doc 9303, Part 3 (common specs, check digits) and Part 4 (TD3) /
Part 5 (TD1), 8th ed. 2021 — https://www.icao.int/publications/doc-series/doc-9303 .

### Character set and check digit **[verified: ICAO test vector passes in code]**

Characters `0-9`, `A-Z`, filler `<`. Values: digit = itself, `A`=10 … `Z`=35, `<`=0.
Check digit = Σ(value × weight) mod 10 with weights `7, 3, 1` repeating from the
first character of the field.

### TD3 (passport data page, 2 × 44)

Line 1:

| Pos | Field |
| --- | --- |
| 1–2 | Document code: `P` + type letter or `<` (`P<`; Korea uses `PM`, Luxembourg `PP`) |
| 3–5 | Issuing state (`ZAF`, `GBR`; `D<<` for Germany) |
| 6–44 | Name: `SURNAME<<GIVEN<NAMES`, spaces/hyphens → `<`, padded with `<`, truncated if long |

Line 2:

| Pos | Field | Check digit |
| --- | --- | --- |
| 1–9 | Document number (padded `<`) | 10 |
| 11–13 | Nationality | — |
| 14–19 | Date of birth `YYMMDD` | 20 |
| 21 | Sex `M` / `F` / `<` (`X` in newer docs) | — |
| 22–27 | Date of expiry `YYMMDD` | 28 |
| 29–42 | Personal number / optional data | 43 (`<` **or** `0` when the field is all `<`) |
| 44 | Composite over 1–10, 14–20, 22–43 | — |

Test vectors (all pass `synth.validate_td3`): ICAO Part 4's
`P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<` / `L898902C36UTO7408122F1204159ZE184226B<<<<<10`,
plus the five specimen MRZs in `specimens/specimens_truth.json`.

* **ZAF**: issuing state `ZAF`, nationality `ZAF`, 9-character document number
  (letter + 8 digits, e.g. `A09876543`). We put the holder's 13-digit SA ID number in
  positions 29–42 (personal number). **[unverified — ASSUMED; confirm on a real
  passport]** A reader should validate it with Luhn when it is 13 digits.
* **GBR**: issuing state `GBR`, 9-digit numeric document number, optional field
  empty with check digit `0` (the Norwegian specimen shows the same `<…<0`
  pattern; ICAO allows `<` too). **[unverified for GBR specifically]**
* The name in the MRZ is transliterated and may be truncated; it is not a
  reliable source of the full printed name.
* MRZ font: OCR-B (ISO 1073-2), size ≈ 10 characters per inch.

### TD1 (ID-1 card, 3 × 30) — not used by any of our documents

| Line | Pos | Field |
| --- | --- | --- |
| 1 | 1–2 | Document code (`I<`, `ID`, `AC`…) |
| 1 | 3–5 | Issuing state |
| 1 | 6–14 | Document number; 15 = its check digit (if the number is > 9 chars, 15 = `<` and the rest + check digit continue in 16–30) |
| 1 | 16–30 | Optional data 1 |
| 2 | 1–6, 7 | Date of birth, check digit |
| 2 | 8 | Sex |
| 2 | 9–14, 15 | Date of expiry, check digit |
| 2 | 16–18 | Nationality |
| 2 | 19–29 | Optional data 2 |
| 2 | 30 | Composite over line 1 pos 6–30, line 2 pos 1–7, 9–15, 19–29 |
| 3 | 1–30 | Name `SURNAME<<GIVEN<NAMES` |

The SA smart ID card has **no** MRZ (front or back), so a TD1 reader is only
needed for other countries' ID cards.

## 5. What the synthetic corpus asserts

`synth/<name>.json` holds the ground truth for every generated document. The
specific choices made where reality is unverified (PDF417 date format, Sex as
`M/F`, ZAF personal-number field, green-book labels) are flagged in each JSON's
`note` and above, so a test failing on a real document points at this file
first.
