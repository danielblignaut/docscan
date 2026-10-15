"""The proof-of-address DEV set: documents of the layouts held out of training
(util_sidebar, bank_modern, muni_grid, rendered by poa_synth.py with its
default seed), each turned into a verification case with a known customer,
as poa_lockbox.py does for the lockbox.

The holder's first name, middle initial and printed style are recovered by
replaying poa_synth's RNG for the document; a middle name is then chosen
from the training name lists to fit the initial. Cases (seeded by --seed):
100 genuine (dated 0-88 days ago), 25 wrong person and 25 wrong address (of
other recent documents), 25 older than three months, and 25 whose customer
gave the issuer's own street address printed on the page.

  .venv/bin/python poa_dev_claims.py --synth /tmp/docscan-poa/synth --out /tmp/docscan-poa/dev/docs
  .venv/bin/python poa_capture.py --docs /tmp/docscan-poa/dev/docs --out /tmp/docscan-poa/dev/frames --seed 4242
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

import poa_lockbox as L
import poa_synth as S

FALLBACK = dict(zip("ABCDEGJKLMNPSTZ", ["Anna", "Ben", "Carel", "Dawid", "Erika", "Grace", "Jan", "Kim", "Lulama",
                                         "Maria", "Nandi", "Paul", "Sam", "Tom", "Zinzi"]))
HELD = {"util_sidebar", "bank_modern", "muni_grid"}


def person_of(truth: dict, seed: int) -> dict | None:
    """The holder as poa_synth drew them, by replaying the document's RNG."""
    index = int(truth["id"].split("_")[1])
    for attempt in range(25):
        rng = random.Random(f"poa:{seed}:{index}:{attempt}")
        captured = {}
        orig = S.make_person

        def spy(r):
            captured["state"] = r.getstate()
            return orig(r)

        S.make_person = spy
        try:
            doc = S.make_doc(rng, truth["layout"], dt.date.fromisoformat(truth["today"]), truth["id"])
        finally:
            S.make_person = orig
        p = doc["person"]
        if p["printed"] != truth["fields"]["holder_name"]:
            continue
        r = random.Random()
        r.setstate(captured["state"])
        female = r.random() < 0.5
        r.choice(S.FIRST_F if female else S.FIRST_M)
        r.choice(S.SURNAMES)
        mid = r.choice("ABCDEGJKLMNPSTZ")
        x = r.random()
        if x >= 0.075 and female:
            r.choice(["Ms", "Mrs", "Mrs", "Miss"])
        style = r.choices(["title_full", "title_init", "init_dot", "full_mid", "couple", "title_inits", "full", "sur_first"],
                          [18, 22, 10, 12, 5, 12, 16, 5])[0]
        names = sorted(n for n in S.FIRST_F + S.FIRST_M if n[0] == mid and n != p["first"]) or [FALLBACK[mid]]
        middle = random.Random(f"middle:{truth['id']}").choice(names)
        return {"first": p["first"], "middle": middle, "surname": p["surname"], "style": style}
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synth", default="/tmp/docscan-poa/synth")
    ap.add_argument("--out", default="/tmp/docscan-poa/dev/docs")
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--synth-seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    truths = [json.loads(p.read_text()) for p in sorted(Path(args.synth).glob("poa_*.json"))]
    truths = [t for t in truths if t["layout"] in HELD]
    rng.shuffle(truths)
    recent = [t for t in truths if t["recent"] and 0 <= t["age_days"] <= 88]
    old = [t for t in truths if not t["recent"] and t["age_days"] >= 95]
    decoyed = [t for t in recent if any(d["kind"] in ("head_office", "branch") for d in t["decoy_addresses"])]
    plan = [(t, "issuer_decoy") for t in decoyed[:25]]
    used = {t["id"] for t, _ in plan}
    rest = [t for t in recent if t["id"] not in used]
    plan += [(t, "genuine") for t in rest[:100]] + [(t, "wrong_person") for t in rest[100:125]] + [(t, "wrong_address") for t in rest[125:150]]
    plan += [(t, "old") for t in old[:25]]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for t, case in plan:
        person = person_of(t, args.synth_seed)
        assert person, t["id"]
        doc = {"person": person, "addr": t["fields"]["address"],
               "decoys": [d for d in t["decoy_addresses"] if d["street"] and not d["street"].upper().startswith(("PO ", "P.O", "PRIVATE"))]}
        t = {**t, "person": person, "case": case, "expect_accept": case == "genuine",
             "customer": L.customer_for(doc, case, random.Random(f"dev-customer:{args.seed}:{t['id']}"))}
        (out / f"{t['id']}.json").write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
        png = out / f"{t['id']}.png"
        if not png.exists():
            png.symlink_to(Path(args.synth) / f"{t['id']}.png")
    print(f"{len(plan)} DEV cases -> {out}")


if __name__ == "__main__":
    main()
