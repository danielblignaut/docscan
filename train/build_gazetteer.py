"""Build docscan's South African place gazetteer (postal code, place, province)
from GeoNames, for the proof-of-address checks (`docscan/src/poa/gazetteer.rs`).

Sources, both from GeoNames (https://www.geonames.org), licensed under
Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/):

- the postal-code dump, https://download.geonames.org/export/zip/ZA.zip
  (code, place name, latitude, longitude; it carries no province), and
- the gazetteer dump, https://download.geonames.org/export/dump/ZA.zip
  (every named feature with its first-order division, the province).

The province of a postal-code entry is taken from the GeoNames feature of the
same name nearest to it among the provinces docscan's coarse postal-code
ranges allow for that code (`verify::POSTAL_RANGES`); failing a named match,
from the nearest populated place in an allowed province; failing that, from
the nearest populated place at all. The South African Post Office's own code
list was not used: its terms of reuse are not stated.

A few official renames that the GeoNames postal dump predates are added as
aliases of the old name's entries (Gqeberha for Port Elizabeth, Polokwane for
Pietersburg, ...): these are public facts, listed in RENAMES below.

  python train/build_gazetteer.py --zip /tmp/geonames/ZA.txt --dump /tmp/geonames/dump/ZA.txt \
      --out docscan/src/poa/za_places.tsv
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path

ADMIN1 = {"03": "Free State", "02": "KwaZulu-Natal", "05": "Eastern Cape", "06": "Gauteng", "07": "Mpumalanga",
          "08": "Northern Cape", "09": "Limpopo", "10": "North West", "11": "Western Cape"}

# The coarse ranges of docscan/src/poa/verify.rs (POSTAL_RANGES), kept in step by hand.
RANGES = [
    (1, 299, ["Gauteng", "North West"]), (300, 399, ["North West", "Limpopo"]),
    (400, 499, ["Limpopo", "Mpumalanga", "North West"]), (500, 999, ["Limpopo"]),
    (1000, 1399, ["Mpumalanga", "Gauteng"]), (1400, 1899, ["Gauteng"]), (1900, 1999, ["Gauteng", "Free State"]),
    (2000, 2199, ["Gauteng"]), (2200, 2499, ["Mpumalanga"]), (2500, 2899, ["North West"]),
    (2900, 4599, ["KwaZulu-Natal"]), (4600, 4730, ["KwaZulu-Natal", "Eastern Cape"]), (4731, 6499, ["Eastern Cape"]),
    (6500, 8099, ["Western Cape"]), (8100, 8299, ["Western Cape", "Northern Cape"]), (8300, 8499, ["Northern Cape"]),
    (8500, 8699, ["Northern Cape", "North West"]), (8700, 8999, ["Northern Cape"]), (9300, 9699, ["Free State"]),
    (9700, 9999, ["Free State", "Northern Cape", "Eastern Cape"]),
]

# Official renames the postal dump predates: new name -> old name as GeoNames lists it.
RENAMES = {
    "Gqeberha": "Port Elizabeth", "Polokwane": "Pietersburg", "Mbombela": "Nelspruit", "Makhanda": "Grahamstown",
    "eMalahleni": "Witbank", "Mahikeng": "Mafikeng", "Mthatha": "Umtata", "Bela-Bela": "Warmbaths",
    "Mokopane": "Potgietersrus", "Modimolle": "Nylstroom", "Musina": "Messina", "Lephalale": "Ellisras",
    "Louis Trichardt": "Makhado", "Komani": "Queenstown", "Ginsberg": "King William's Town",
}


def allowed(code: str) -> list[str]:
    n = int(code)
    for lo, hi, provs in RANGES:
        if lo <= n <= hi:
            return provs
    return []


def dist(a, b) -> float:
    dlat = a[0] - b[0]
    dlon = (a[1] - b[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def key(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="/tmp/geonames/ZA.txt")
    ap.add_argument("--dump", default="/tmp/geonames/dump/ZA.txt")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docscan" / "src" / "poa" / "za_places.tsv"))
    args = ap.parse_args()

    by_name: dict[str, list] = defaultdict(list)  # name key -> [(lat, lon, province)]
    populated: list = []
    for line in open(args.dump, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        prov = ADMIN1.get(f[10])
        if not prov or f[6] not in ("P", "A", "L"):
            continue
        pt = (float(f[4]), float(f[5]), prov)
        for n in {f[1], f[2], *[a for a in f[3].split(",") if a]}:
            by_name[key(n)].append(pt)
        if f[6] == "P":
            populated.append(pt)

    rows = set()
    stats = defaultdict(int)
    for line in open(args.zip, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        code, place, lat, lon = f[1], f[2].strip(), float(f[9]), float(f[10])
        if len(code) != 4 or not code.isdigit():
            continue
        provs = allowed(code)
        here = (lat, lon)
        named = [p for p in by_name.get(key(place), []) if not provs or p[2] in provs]
        if named:
            prov = min(named, key=lambda p: dist(p, here))[2]
            stats["named"] += 1
        else:
            near = [p for p in populated if not provs or p[2] in provs] or populated
            prov = min(near, key=lambda p: dist(p, here))[2]
            stats["nearest"] += 1
        rows.add((code, place, prov))
    olds = defaultdict(list)
    for code, place, prov in rows:
        olds[place].append((code, prov))
    for new, old in RENAMES.items():
        for code, prov in olds.get(old, []):
            rows.add((code, new, prov))
            stats["renamed"] += 1
    out = Path(args.out)
    head = ("# South African postal codes, places and provinces, from GeoNames (www.geonames.org, CC BY 4.0);\n"
            "# built by train/build_gazetteer.py. Columns: code, place, province.\n")
    out.write_text(head + "".join(f"{c}\t{p}\t{v}\n" for c, p, v in sorted(rows)))
    print(f"{len(rows)} rows -> {out} ({dict(stats)})")


if __name__ == "__main__":
    main()
