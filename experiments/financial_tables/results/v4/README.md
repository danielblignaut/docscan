# v4 results (append-only)

Scorer v4 output (the v2/v3 scoring rules). Files are named `<set>-<sha256 prefix of demo/src/financial-tables/*.ts>.json`
and never overwritten. `results/v2/`, `results/v3/` and `history/` are frozen (committed in d0d4a6b).

- `*-9241be0766d4.json` — an intermediate engine during the r6 fix (before the dual-column shortcut needed two
  nonzero amounts).
- `*-b8526b6ae659.json` — the hand-off engine. Cell and check results are the same as v3: main 464/464 cells and
  55/55 checks, stress 151/151 and 20/20, review 129/130 and 22/22, review3 101/101 and 15/15. Every set has
  0 false `consistent`, 0 unscored checks, 0 unexpected observations and 0 false income candidates. No
  fixture or gold changed in v4.
- `repro-after-b8526b6ae659/` — output of the r6 reproductions (`/tmp/ftrev3/q1.mjs`, `q2.mjs`) after the fix.
