# v2 results (append-only)

Scorer v2 output. Files are named `<set>-<sha256 prefix of demo/src/financial-tables/*.ts>.json` and are never
overwritten with different content (a later differing run gets a `-n` suffix).

- `*-a91a63e7d246*` — intermediate runs during the review fixes (the review set's `-2` is after its gold
  gained three authored check expectations).
- `*-69574d5f9006.json` — the engine after the independent review fixes.
- `*-4f0eca9f6867.json` — the same engine plus `settings.perFile` in `projectFinancialReport` (no extraction
  change); this is the hand-off. Same numbers as above: main 464/464 cells,
  55/55 checks; stress 151/151, 20/20; review 129/130, 22/22. Every set has 0 false `consistent`, 0 unscored
  checks, 0 unexpected observations and 0 false income candidates.
- `repro-after-<hash>/` — output of the reviewer's reproductions (`/tmp/ftrev/r*.mjs`) after the fixes; the
  pre-fix output is in `../../history/v1-2026-10-25/repro-before/`.
