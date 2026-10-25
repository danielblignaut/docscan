# v3 results (append-only)

Scorer v3 output (v2's scoring rules). Files are named `<set>-<sha256 prefix of demo/src/financial-tables/*.ts>.json`
and never overwritten with different content (a later differing run gets a `-n` suffix).

- `*-2309b91b473b*`: the v3 engine before a final unused-parameter cleanup. `review3-2309b91b473b.json` is the
  review3 set's **first scored run**, kept unchanged. `-2` and `-3` follow the recorded gold corrections
  (`gold.goldChanges`).
- `*-0ccccd457514.json`: the hand-off engine.
  - main: 464/464 cells, 55/55 checks.
  - stress: 151/151 cells, 20/20 checks.
  - review: 129/130 cells, 22/22 checks.
  - review3: 101/101 cells, 15/15 checks.

  Every set has 0 false `consistent`, 0 unscored checks, 0 unexpected observations and 0 false income
  candidates. `receipt-0ccccd457514.sha256` hashes the source, tests, fixtures, these results and the docs.
- `repro-after-0ccccd457514/`: output of the r3 reproductions (`/tmp/ftrev2/p*.mjs`) after the fixes.
