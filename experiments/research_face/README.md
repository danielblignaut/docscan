# Face research loop, 24 October 2026

Research-only, DEV-only. This directory owns its programs/configuration/results;
shipping code and the common benchmark referee remain unchanged. Primary-source
survey and decisions: `docs/research-2026-face.md`.

`protocol-v1.json` freezes four temporal fusion candidates before measurement.
The baseline data were already known: none of 765 sampled replay frames crossed
the raw shipped thresholds. This is explicitly **not a blinded experiment**.
The new question is whether temporal/quality fusion is feasible and whether it
raises attack margins; convex fusion cannot improve a zero-error attack-only set.
No second candidate search or threshold optimization follows the results.

The runner reuses the original frozen native inference, verifies source media,
model and derived-frame hashes against the original report, and freshly decodes
the five permitted videos for a capture blur diagnostic. It does not infer with
a concurrently rebuilt shared executable. The original executable hash and cache
hashes remain in provenance. These are **cached model inference + fresh pixel
processing**, not a new native model run. No compile is needed.

The central-half-frame sharpness proxy is intentionally cheap and local-browser
implementable, but is not face-localized or learned recognition utility. It can
measure screen/background edges. Its inadequacy is part of this feasibility
experiment, not a claim to reproduce a FIQA method.

Run with the existing local environment:

```sh
/tmp/docscan-bench/venv/bin/python -m unittest discover -s experiments/research_face -p 'test_*.py' -v
/tmp/docscan-bench/venv/bin/python experiments/research_face/temporal_quality.py
```

The runner snapshots itself and the config, writes a freeze receipt **before**
reading score arrays, and retains private per-frame/per-clip numeric results in
`/tmp/docscan-public-data/research-face/<config-and-runner-hash>/`. Source frames
stay in memory; no media, embeddings, identity-indexed scores or raw text goes
into git. Public JSON reports contain aggregates/denominators and hashes only.
Invalid inputs abort instead of changing denominators. Reruns refuse to overwrite
an existing report. Private caches are read-only; all new private output belongs
to this experiment. Unknown identity/device overlap precludes independent-trial
confidence claims. No actual active session, genuine temporal BPCER, rPPG ground
truth, or APCER at fixed BPCER is available in the owner preview.
