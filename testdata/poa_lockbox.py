"""The proof-of-address LOCKBOX: documents nothing in training or development
has seen, rendered once, scored once (see eval/LOCKBOX.md).

Everything that varies between documents is new here:

* four layout families written only for the lockbox (`lb_fibre_invoice`,
  `lb_bank_letter`, `lb_retail_account`, `lb_water_board`; below);
* fonts no training page uses (Titillium Web, Oxygen, Hind, Arvo, Space Mono:
  SIL OFL, fetched by testdata/fetch_poa_fonts.sh into /tmp/docscan-poa/fonts),
  mixed with the system DejaVu / Liberation faces;
* holders drawn from first names and surnames that are not in poa_synth.py's
  lists, issuers from new invented roots and suffixes, street names from a new
  list;
* places: real South African towns and suburbs from GeoNames (CC BY 4.0, via
  docscan/src/poa/za_places.tsv) that are *not* among poa_synth.PLACES, so
  most lie outside the training distribution;
* its own generator seed.

Each document is also a verification case: it carries the known customer (the
name on their ID and the address they gave) and what the answer must be:

* `genuine`: the holder, at the holder's address, dated 0-88 days ago;
* `wrong_person`: someone else (another surname, or the same surname with a
  different first name and initial when the page prints one);
* `wrong_address`: the holder, but another house number or street name;
* `old`: the holder at the holder's address, dated 95-400 days ago;
* `issuer_decoy`: the holder, but the address given is the issuer's own
  (head office or branch) printed on the page.

The customer's address is written as a person types it: street suffixes
abbreviated or not, case changed, the suburb or province sometimes left out.

  .venv/bin/python poa_lockbox.py --out /tmp/docscan-poa/lockbox/docs --jobs 8
  .venv/bin/python poa_capture.py --docs /tmp/docscan-poa/lockbox/docs --out /tmp/docscan-poa/lockbox/frames --seed 9001
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import multiprocessing as mp
import random
import re
import time
from pathlib import Path

import poa_synth as S
from poa_synth import GREY, INK, LIGHT, WHITE, D, J, tint

ROOT = Path(__file__).resolve().parent
FONT_DIR = Path("/tmp/docscan-poa/fonts")
GAZETTEER = ROOT.parent / "docscan" / "src" / "poa" / "za_places.tsv"
TRAIN_PLACES = list(S.PLACES)  # what training and development use, before install() replaces it
_INSTALLED = False

# --------------------------------------------------------------------------- #
# New fonts, people, issuers, streets and places
# --------------------------------------------------------------------------- #

LB_FONTS = {
    "titillium": ("TitilliumWeb-Regular.ttf", "TitilliumWeb-Bold.ttf"),
    "oxygen": ("Oxygen-Regular.ttf", "Oxygen-Bold.ttf"),
    "hind": ("Hind-Regular.ttf", "Hind-Bold.ttf"),
    "arvo": ("Arvo-Regular.ttf", "Arvo-Bold.ttf"),
    "spacemono": ("SpaceMono-Regular.ttf", "SpaceMono-Bold.ttf"),
}

LB_FIRST_M = ["Andile", "Sizwe", "Mpumelelo", "Lethabo", "Tshiamo", "Oratile", "Bheki", "Zola", "Siphiwe", "Nkululeko",
              "Thulani", "Mxolisi", "Sello", "Mothusi", "Kgosi", "Tiisetso", "Dumisani", "Phumlani", "Wandile",
              "Kamogelo", "Koos", "Stefan", "Wikus", "Dewald", "Brendan", "Craig", "Ryan", "Imraan", "Shaun", "Vikesh",
              "Nirvan", "Junaid", "Tariq", "Zaid", "Ernst", "Gideon", "Lwando", "Ayabonga", "Bonolo", "Rorisang"]
LB_FIRST_F = ["Nomsa", "Thembeka", "Nandi", "Lungile", "Ntombi", "Zinhle", "Hlengiwe", "Keabetswe", "Tshegofatso",
              "Omphile", "Rethabile", "Itumeleng", "Mapula", "Dikeledi", "Carla", "Mariska", "Ilse", "Juanita", "Nadia",
              "Tanya", "Bronwyn", "Kirsty", "Natasha", "Shireen", "Nadira", "Rukshana", "Thirusha", "Kerisha", "Anisha",
              "Zubeida", "Faranaaz", "Gugu", "Siphokazi", "Unathi", "Amahle", "Wilma", "Hester", "Rochelle", "Jolene"]
LB_SURNAMES = ["Nxumalo", "Mabuza", "Magagula", "Hlongwane", "Radebe", "Mlambo", "Buthelezi", "Zwane", "Mnisi",
               "Maluleke", "Baloyi", "Chauke", "Rikhotso", "Ndou", "Mudau", "Sibiya", "Shange", "Kekana", "Mashaba",
               "Mokwena", "Sekgobela", "Ledwaba", "Rampedi", "Moloi", "Olivier", "Erasmus", "Lombard", "Engelbrecht",
               "Brink", "Vermeulen", "Potgieter", "le Roux", "de Villiers", "Murray", "Campbell", "Robertson",
               "Naicker", "Pather", "Munsamy", "Ramsamy", "Bhana", "Desai", "Cassim", "Salie", "Samuels", "Februarie",
               "Jantjies", "Cloete", "Booysen", "Stuurman", "Mthethwa", "Gxowa", "Tshabangu", "Makgoba", "Nhlapo"]
LB_ROOTS = ["Kgorelo", "Thulasi", "Mbekelo", "Sinovuyo", "Velani", "Hlumelo", "Tumisang", "Duduzo", "Nalomo", "Tsholo",
            "Umzelo", "Qoboza", "Mavelo", "Tlhatlo", "Zenkosi", "Kopanelo", "Bontle", "Ithemba", "Lusindiso", "Rethusa"]
LB_MUNI = ["Doringbult-Wes", "Kwanontuthu", "Ilitha Hills", "Mooiwatervlei", "Riethoek", "Bloubergvlei",
           "Rietspruit-Noord", "Mzimvubu Bay", "Sandkoppies", "Lekwa-Oos"]
LB_SUFFIX = {
    "utility_bill": ["Water Board", "Water Services", "Gas", "Solar Power", "Energy Co-op"],
    "bank_statement": ["Trust Bank", "Building Society", "Commercial Bank", "Private Bank"],
    "cellphone_account": ["Fibre", "Fibre Networks", "Broadband", "Internet"],
    "retail_account": ["Stores", "Home Stores", "Fashion", "Furnishers", "Outfitters"],
    "municipal_account": ["Municipality"],
}
LB_TAGLINE = {
    "utility_bill": ["Clean water for every home", "Water and sanitation services", "Your local water provider"],
    "bank_statement": ["Banking with heart", "Private and business banking", "Since 1962"],
    "cellphone_account": ["Fast. Uncapped. Yours.", "Fibre to the home", "Internet that keeps up"],
    "retail_account": ["Style for less", "Furnish your home", "Quality you can trust"],
    "municipal_account": ["Serving our community"],
}
LB_STREETS = ["Bokmakierie Street", "Umdoni Road", "Lourie Avenue", "Tambotie Crescent", "Blouberg Road",
              "Kingfisher Drive", "Msinsi Lane", "Witstinkhout Street", "Ixia Close", "Geelhout Avenue",
              "Mangrove Drive", "Klipspringer Road", "Dahlia Street", "Ingwe Road", "Rooibos Lane", "Marula Avenue",
              "Pelican Way", "Fynbos Crescent", "Hibiscus Street", "Duiker Road", "Yellowwood Drive", "Baobab Street",
              "Mountain View Road", "School Street", "Hospital Road", "Commissioner Street", "Rose Avenue",
              "Thabo Mbeki Drive", "Ou Kaapse Weg", "Tulbagh Street", "Kestrel Close", "Swallow Street"]
LB_ABBREV = {"Road": "Rd", "Street": "St", "Avenue": "Ave", "Drive": "Dr", "Crescent": "Cres", "Lane": "Ln",
             "Close": "Cl", "Way": "Wy"}

# Metro cities whose GeoNames postal entries name suburbs: a place sharing a
# code with one of these is printed as a suburb of it.
METROS = ["Johannesburg", "Pretoria", "Cape Town", "Durban", "Port Elizabeth", "East London", "Bloemfontein",
          "Pietermaritzburg", "Kimberley", "Polokwane", "Nelspruit"]
METRO_PRINT = {"Port Elizabeth": "Gqeberha", "Nelspruit": "Mbombela"}
# Other names of the metros themselves, which must not pass for a suburb.
NOT_SUBURBS = {"kaapstad", "tshwane", "ethekwini", "pietersburg", "gqeberha", "mbombela", "polokwane", "nelson mandela bay",
               "johannesburg central", "pretoria central", "durban central", "cape town central"}


def lb_places(rng: random.Random) -> list[tuple[str | None, str, str, str]]:
    """Real places from the GeoNames gazetteer that poa_synth.PLACES does not use."""
    used = {n.lower() for s, c, _, _ in TRAIN_PLACES for n in (s, c) if n}
    by_code: dict[str, list[tuple[str, str]]] = {}
    for line in GAZETTEER.read_text().splitlines():
        if line.startswith("#"):
            continue
        code, place, prov = line.split("\t")
        by_code.setdefault(code, []).append((place, prov))
    towns, suburbs = {}, {}
    for code, entries in sorted(by_code.items()):
        names = [e[0] for e in entries]
        metro = next((m for m in METROS if m in names), None)
        for place, prov in entries:
            if place.lower() in used or place.lower() in NOT_SUBURBS or place in METROS or place in METRO_PRINT.values() or not re.fullmatch(r"[A-Za-z' -]+", place):
                continue
            if len(place) > 18 or place.lower().startswith(("po ", "p.o")):
                continue
            if metro:
                suburbs.setdefault((place, metro), (prov, code))
            elif len(entries) <= 6:
                towns.setdefault(place, (prov, code))
    sub = sorted(suburbs.items())
    town = sorted(towns.items())
    rng.shuffle(sub)
    rng.shuffle(town)
    out = [(s, METRO_PRINT.get(m, m), prov, code) for (s, m), (prov, code) in sub[:70]]
    out += [(None, t, prov, code) for t, (prov, code) in town[:110]]
    return out


def install() -> None:
    """Points poa_synth's tables at the lockbox's own (once per process)."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    for k, (r, b) in LB_FONTS.items():
        S.FONTS[k] = (str(FONT_DIR / r), str(FONT_DIR / b))
    S.FIRST_M = [n for n in LB_FIRST_M if not S.forbidden_in(n)]
    S.FIRST_F = [n for n in LB_FIRST_F if not S.forbidden_in(n)]
    S.SURNAMES = [n for n in LB_SURNAMES if not S.forbidden_in(n)]
    S.ROOTS = LB_ROOTS
    S.MUNI_PLACES = LB_MUNI
    S.SUFFIX.update(LB_SUFFIX)
    S.TAGLINE.update(LB_TAGLINE)
    S.STREETS = LB_STREETS
    S.ABBREV = LB_ABBREV
    S.PLACES = lb_places(random.Random("lockbox-places:1"))
    S.make_person = make_person
    for r in LB_ROOTS + LB_MUNI:
        assert not S.forbidden_in(r), r
    for name, fn in LB_LAYOUTS.items():
        S.LAYOUT_FN[name] = fn
    S.LAYOUT_TYPES.update(LB_TYPES)
    S.LAYOUT_FONTS.update(LB_LAYOUT_FONTS)
    S.LAYOUT_DATE_STYLES.update(LB_DATE_STYLES)
    S.PERIOD_P.update(LB_PERIOD_P)


def make_person(rng: random.Random) -> dict:
    """poa_synth.make_person, also keeping the middle name and the printed style."""
    female = rng.random() < 0.5
    first = rng.choice(S.FIRST_F if female else S.FIRST_M)
    surname = rng.choice(S.SURNAMES)
    middle = rng.choice([n for n in S.FIRST_F + S.FIRST_M if n != first])
    mid = middle[0]
    r = rng.random()
    title = "Dr" if r < 0.06 else ("Prof" if r < 0.075 else ("Mr" if not female else rng.choice(["Ms", "Mrs", "Mrs", "Miss"])))
    style = rng.choices(["title_full", "title_init", "init_dot", "full_mid", "couple", "title_inits", "full", "sur_first"],
                        [18, 22, 10, 12, 5, 12, 16, 5])[0]
    upper = rng.random() < 0.4
    sur = surname[0].upper() + surname[1:]
    sal = f"{title} {sur}"
    if style == "title_full":
        name = f"{title} {first} {surname}"
    elif style == "title_init":
        name = f"{title} {first[0]} {surname}"
    elif style == "init_dot":
        name = f"{first[0]}. {surname}"
    elif style == "full_mid":
        name = f"{first} {mid} {surname}"
    elif style == "couple":
        name = f"Mr & Mrs {first[0]} {surname}" if not female else f"Mr & Mrs {rng.choice(S.FIRST_M)[0]} {surname}"
        sal = f"Mr and Mrs {sur}"
    elif style == "title_inits":
        name = f"{title} {first[0]}{mid} {surname}"
        upper = upper or rng.random() < 0.5
    elif style == "sur_first":
        name = f"{sur}, {first[0]}{mid}"
    else:
        name = f"{first} {surname}"
    name = name.upper() if upper else name
    return {"first": first, "middle": middle, "surname": surname, "title": title, "printed": name, "salutation": sal,
            "style": style, "female": female}


# --------------------------------------------------------------------------- #
# Layout families (lockbox only)
# --------------------------------------------------------------------------- #


def street_decoy(p, doc) -> str:
    """The kind of the issuer's address decoy: a street address when the case needs one."""
    if doc.get("need_street_decoy"):
        return p.rng.choice(["head_office", "branch"])
    return p.rng.choice(["head_office", "branch", "postal"])


def lay_lb_fibre_invoice(p, doc) -> None:
    """A fibre provider's invoice: title top left, issuer top right, a 'Bill to'
    card with a colour bar, a labels-over-values strip, services, the
    installation address, and the registered office above the footer."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 64, W - 64
    p.d.rectangle((0, 0, W, 12), fill=c)
    p.text(x0, 48 + J(p, 6), rng.choice(["INVOICE", "Tax Invoice", "Monthly invoice"]), p.f(44, True), c)
    s = 70
    nx = x1 - s - 16
    _, nw = p.text(nx, 52, [(iss["name"], "ISSUER")], p.f(30, True), INK, anchor="r")
    S.logo(p, x1 - s, 40, s, doc)
    p.text(nx, 92, iss["tagline"], p.f(16), GREY, anchor="r")
    p.text(nx, 116, f"{iss['web']}  |  {iss['tel']}", p.f(14), GREY, anchor="r")
    y = 190 + J(p, 10)
    # Bill-to card
    lab = rng.choice(["Bill to", "Billed to", "Customer", "Invoice to"])
    cw = 520
    p.d.rectangle((x0, y, x0 + 6, y + 200), fill=c)
    p.text(x0 + 24, y + 4, lab.upper() if rng.random() < 0.5 else lab, p.f(15, True), c)
    by = S.holder_block(p, x0 + 24, y + 34, doc, label=None, fs=20, line_h=29)
    p.d.rectangle((x0, y, x0 + 6, by), fill=c)
    # strip of labels over values, right
    sx = x0 + cw + 40
    cells = [("Invoice no", f"{rng.choice(['IN', 'FB', 'INV'])}{S.digits(rng, 7)}"),
             (rng.choice(["Invoice date", "Date", "Issued"]), S.date_parts(doc, doc["date"], "DOC_DATE")),
             (rng.choice(["Account", "Account no", "Customer no"]), [(doc["acc"], "ACCOUNT_NO")])]
    lf, vf = p.f(14), p.f(18, True)
    colw = (x1 - sx) / 3
    for k, (l, v) in enumerate(cells):
        cx = sx + k * colw
        p.text(cx, y + 4, l.upper(), lf, GREY)
        p.text(cx, y + 28, v, vf, INK)
    p.rule(sx, y + 62, x1, LIGHT)
    yy = y + 80
    if doc["period"]:
        p.text(sx, yy, S.period_parts(doc, rng.choice(["Service period ", "Billing period: ", "For "]), " to "), p.f(16), INK)
        yy += 30
    p.text(sx, yy, f"Due date {D(doc, doc['due'])}", p.f(16), INK)
    yy += 30
    p.text(sx, yy, f"Package: {rng.choice(['Uncapped 50/50 Mbps', 'Home 100 Mbps', 'Lite 25 Mbps', 'Pro 200/100 Mbps'])}", p.f(16), GREY)
    y = max(by, yy + 30) + 40
    ms = doc["money_style"]
    rows, raw = [], []
    for desc, base in rng.sample([("Monthly fibre subscription", 69900), ("Router rental", 9900), ("Static IP address", 4900),
                                  ("Installation (pro rata)", 25000), ("Voice line", 7900), ("Wi-Fi extender", 5900)], rng.randint(2, 5)):
        amt = int(base * rng.uniform(0.6, 1.4))
        rows.append([desc, "1", S.money(amt, ms)])
        raw.append((desc, "1", amt))
    tf, tfb = p.f(17), p.f(17, True)
    y = S.table(p, x0, y, x1 - x0, ["Service", "Qty", "Amount"], rows, [0.62, 0.14, 0.24], "lrr", tf, tfb, grid=(225, 225, 230))
    y = S.totals(p, x1 - 10, y + 15, doc, raw, tf, tfb, label_x=x1 - 430, show_due=False)
    y += 25
    if doc["twice"] or rng.random() < 0.4:
        p.text(x0, y, rng.choice(["Installation address", "Service address", "Line installed at"]), p.f(16, True), INK)
        lines, pr = S.address_lines(doc["addr"], rng, labelled=True, single=True, upper=False)
        doc["province_printed"] |= pr
        y = p.flow(x0, y + 28, x1 - x0, lines[0], p.f(16), INK) + 20
    y = S.small_print(p, x0, y + 10, x1 - x0, H - 260, doc, 13, rng.randint(1, 3))
    if doc["decoy"]:
        S.decoy_block(p, x0, H - 230, doc, street_decoy(p, doc), 14, heading=rng.choice(["Registered office", "Head office", "Our offices"]))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=False, colour=c)


def lay_lb_bank_letter(p, doc) -> None:
    """A bank's confirmation-of-address letter: centred letterhead, the date
    and branch at the top, the holder named in a sentence, the address in an
    indented block or within the sentence, and the head office in the footer."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 120, W - 120
    cx = W // 2
    S.logo(p, cx - 36, 46, 72, doc)
    p.text(cx, 132, [(iss["name"].upper() if rng.random() < 0.4 else iss["name"], "ISSUER")], p.f(30, True), c, anchor="c")
    p.text(cx, 172, iss["tagline"], p.f(16), GREY, anchor="c")
    p.rule(x0, 205, x1, c, 3)
    y = 240
    f, fb = p.f(19), p.f(19, True)
    lh = p.lh(f, 1.5)
    if doc["decoy"] and rng.random() < 0.6:
        yb = S.decoy_block(p, x1, y, doc, street_decoy(p, doc), 15, heading=rng.choice(["Branch", "Issuing branch", None]),
                           anchor="r", contacts=True)
        foot_decoy = False
    else:
        yb = y
        foot_decoy = doc["decoy"]
    dl = rng.choice(["Date: ", "", "Date of issue: "])
    p.text(x0, y, [dl, (D(doc, doc["date"]), "DOC_DATE")] if dl else [(D(doc, doc["date"]), "DOC_DATE")], f, INK)
    p.text(x0, y + lh, f"Our reference: {rng.choice(['CRA', 'AC', 'BR'])}/{S.digits(rng, 6)}", f, GREY)
    y = max(yb, y + 2 * lh) + lh
    p.text(x0, y, rng.choice(["TO WHOM IT MAY CONCERN", "To whom it may concern"]), fb, INK)
    y += lh * 1.6
    p.text(x0, y, rng.choice(["CONFIRMATION OF RESIDENTIAL ADDRESS", "CONFIRMATION OF ADDRESS", "PROOF OF RESIDENCE"]), fb, c)
    y += lh * 1.6
    inline = rng.random() < 0.45
    sent = ["We hereby confirm that", (doc["person"]["printed"], "HOLDER_NAME"),
            rng.choice(["holds", "is the holder of"]), rng.choice(["a cheque account", "a savings account", "an account"]),
            "number", (doc["acc"], "ACCOUNT_NO"), "with", (iss["name"], "ISSUER")]
    if inline:
        lines, pr = S.address_lines(doc["addr"], rng, labelled=True, single=True, upper=False)
        doc["province_printed"] |= pr
        sent += ["and that, according to our records, the account holder resides at"] + [x for x in lines[0] if x != " "]
        sent[-1] = (sent[-1][0] + ".", sent[-1][1]) if not isinstance(sent[-1], str) else sent[-1] + "."
        y = p.flow(x0, y, x1 - x0, sent, f, INK, lh) + lh * 0.5
    else:
        sent += ["and that the residential address on record is:"]
        y = p.flow(x0, y, x1 - x0, sent, f, INK, lh) + lh * 0.4
        y = S.holder_block(p, x0 + 60, y, doc, label=None, fs=19, name=False, line_h=lh) + lh * 0.4
    y = p.flow(x0, y, x1 - x0, [rng.choice([
        "This letter is issued at the request of the account holder, without any liability on the part of the bank or its officials, and is valid for three months from the date of issue.",
        "The information above is confirmed as it appears on our records on the date of this letter. The bank accepts no responsibility for any change after that date.",
    ])], f, INK, lh) + lh
    p.text(x0, y, "Yours faithfully", f, INK)
    y += lh * 2.8
    p.rule(x0, y, x0 + 360, INK)
    off = S.other_person(rng, doc)
    p.text(x0, y + 8, f"{off['first']} {off['surname']}", p.f(17, True), INK)
    p.text(x0, y + 34, rng.choice(["Branch Manager", "Client Service Consultant", "Relationship Manager"]), p.f(16), GREY)
    y += 90
    p.d.ellipse((x1 - 180, y - 150, x1 - 20, y + 10), outline=tint(c, 0.5), width=3)
    p.text(x1 - 100, y - 82, "BRANCH STAMP", p.f(14, True), tint(c, 0.6), anchor="c")
    S.small_print(p, x0, y + 30, x1 - x0, H - 150, doc, 12, 1)
    S.footer(p, doc, H - 100, x0, x1, 12, decoy_here=foot_decoy, centre=True)


def lay_lb_retail_account(p, doc) -> None:
    """A store account statement: the issuer's wordmark in colour, a summary
    strip of four cells, the holder block under it beside an 'at a glance'
    box, transactions at branches, and a tear-off slip with the name and
    address again and the accounts department's address."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 60, W - 60
    p.text(x0, 50, [(iss["name"], "ISSUER")], p.f(48, True), c)
    p.text(x0, 112, iss["tagline"], p.f(18), GREY)
    p.text(x1, 60, rng.choice(["ACCOUNT STATEMENT", "Store account", "Your statement"]), p.f(24, True), INK, anchor="r")
    y = 170
    ms = doc["money_style"]
    limit = rng.choice([500000, 800000, 1200000, 2000000])
    cells = [(rng.choice(["Statement date", "Date"]), S.date_parts(doc, doc["date"], "DOC_DATE")),
             (rng.choice(["Account number", "Account no"]), [(doc["acc"], "ACCOUNT_NO")]),
             ("Credit limit", S.money(limit, ms)), ("Minimum due", S.money(rng.randint(15000, 90000), ms))]
    cw = (x1 - x0) / 4
    p.d.rectangle((x0, y, x1, y + 84), fill=tint(c, 0.1))
    for k, (l, v) in enumerate(cells):
        cx = x0 + k * cw + 16
        p.text(cx, y + 12, l, p.f(15), GREY)
        p.text(cx, y + 42, v, p.f(19, True), INK)
        if k:
            p.d.line((x0 + k * cw, y + 10, x0 + k * cw, y + 74), fill=WHITE, width=3)
    y += 120
    by = S.holder_block(p, x0 + 10, y + J(p, 8), doc, label=rng.choice([None, "Account holder", "Statement for"]), fs=20)
    gx = 700
    p.d.rounded_rectangle((gx, y, x1, y + 210), radius=8, outline=tint(c, 0.5), width=2)
    p.text(gx + 18, y + 14, "Your account at a glance", p.f(17, True), c)
    rows = [("Opening balance", S.money(rng.randint(10000, 400000), ms)), ("Purchases", S.money(rng.randint(5000, 300000), ms)),
            ("Payments", S.money(-rng.randint(5000, 300000), ms)), ("Due by", D(doc, doc["due"]))]
    if doc["period"]:
        rows[3] = ("Period", S.period_parts(doc, "", " - "))
    S.kv_rows(p, gx + 18, y + 52, rows, p.f(15), p.f(16, True), right=x1 - 18, gap=38)
    y = max(by, y + 210) + 40
    branches = [f"{rng.choice(['Mall', 'Plaza', 'Centre', 'Junction'])} {pl[1]}" for pl in rng.sample(S.PLACES, 3)]
    rows = []
    for _ in range(rng.randint(4, 10)):
        d = doc["date"] - dt.timedelta(days=rng.randint(3, 40))
        amt = rng.randint(-150000, 250000)
        rows.append([S.fmt_date(d, "dmy_slash"), rng.choice(["Purchase", "Payment received", "Service fee", "Interest", "Club fee"]),
                     rng.choice(branches), S.money(amt, ms)])
    rows.sort()
    tf, tfb = p.f(16), p.f(16, True)
    y = S.table(p, x0, y, x1 - x0, ["Date", "Description", "Store", "Amount"], rows, [0.17, 0.3, 0.3, 0.23], "lllr", tf, tfb,
                head_fill=c, shade=tint(c, 0.06))
    y = S.small_print(p, x0, y + 30, x1 - x0, H - 330, doc, 12, rng.randint(1, 3))
    # tear-off slip
    ty = H - 300
    p.rule(x0, ty, x1, GREY, 1, dash=8)
    p.text(x0, ty + 8, "Detach and keep with your payment", p.f(13), GREY)
    ty += 40
    p.text(x0, ty, "PAYMENT SLIP", p.f(18, True), INK)
    if rng.random() < 0.7:
        S.holder_block(p, x0, ty + 34, doc, label=None, fs=16, line_h=23, name_bold=True, single=rng.random() < 0.5)
    else:
        p.text(x0, ty + 34, ["Account ", (doc["acc"], "ACCOUNT_NO")], p.f(16, True), INK)
    if doc["decoy"]:
        S.decoy_block(p, 700, ty, doc, street_decoy(p, doc), 14, heading=rng.choice(["Accounts department", "Send payments to", "Credit control"]),
                      contacts=False)
    p.text(x0, H - 50, [(iss["name"], "ISSUER"), f" is a registered credit provider NCRCP{S.digits(rng, 4)}  |  {iss['web']}"], p.f(12), GREY)


def lay_lb_water_board(p, doc) -> None:
    """A water board's account: a contact line above a colour band with the
    name, the account date and number in the band's right end, three
    columns (consumer, stand address, meter), a readings table, a usage
    chart and the board's address in the footer."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 56, W - 56
    contact_decoy = doc["decoy"] and rng.random() < 0.5
    if contact_decoy:
        a = S.decoy_address(rng, doc["addr"], street_decoy(p, doc))
        doc["decoys"].append(a)
        lines, _ = S.address_lines(a, rng, labelled=False, single=True, upper=False)
        p.text(x0, 30, lines[0] + [f"  |  Tel {iss['tel']}"], p.f(13), GREY)
    else:
        p.text(x0, 30, f"Tel {iss['tel']}  |  {iss['email']}", p.f(13), GREY)
    by = 64
    bh = 110
    p.d.rectangle((0, by, W, by + bh), fill=c)
    S.logo(p, x0, by + 18, 74, doc, colour=WHITE)
    p.text(x0 + 92, by + 22, [(iss["name"], "ISSUER")], p.f(34, True), WHITE)
    p.text(x0 + 92, by + 68, rng.choice(["WATER ACCOUNT", "Water and sanitation account", "Consumer account"]), p.f(17), WHITE)
    p.text(x1, by + 22, rng.choice(["Account date", "Date", "Billing date"]), p.f(15), WHITE, anchor="r")
    p.text(x1, by + 44, S.date_parts(doc, doc["date"], "DOC_DATE"), p.f(21, True), WHITE, anchor="r")
    y = by + bh + 36
    colw = (x1 - x0) / 3
    lab = rng.choice(["Consumer", "Account name", "Customer"])
    hy = S.holder_block(p, x0, y, doc, label=lab, fs=18, line_h=26, label_font=p.f(14, True))
    sx = x0 + colw + 10
    p.text(sx, y, rng.choice(["Account number", "Account no."]), p.f(14, True), GREY)
    p.text(sx, y + 22, [(doc["acc"], "ACCOUNT_NO")], p.f(18, True), INK)
    p.text(sx, y + 64, rng.choice(["Stand number", "Erf"]), p.f(14, True), GREY)
    p.text(sx, y + 86, f"{rng.randint(100, 9999)}", p.f(18), INK)
    if doc["twice"]:
        p.text(sx, y + 128, "Supply address", p.f(14, True), GREY)
        lines, pr = S.address_lines(doc["addr"], rng, labelled=True, single=False, upper=False)
        doc["province_printed"] |= pr
        yy = y + 150
        for line in lines:
            p.text(sx, yy, line, p.f(16), INK)
            yy += 23
    mx = x0 + 2 * colw + 20
    rows = [("Meter no", S.digits(rng, 8)), ("Previous", str(rng.randint(1000, 9000))), ("Current", str(rng.randint(9000, 9999)))]
    if doc["period"]:
        rows.append(("Reading from", S.date_parts(doc, doc["period"][0], "PERIOD_FROM")))
        rows.append(("Reading to", S.date_parts(doc, doc["period"][1], "PERIOD_TO")))
    my = S.kv_rows(p, mx, y, rows, p.f(14), p.f(16, True), right=x1, gap=30)
    y = max(hy, my, y + 260 if doc["twice"] else 0) + 30
    rows_, raw = S.charge_rows(p, doc, rng.randint(3, 6))
    tf, tfb = p.f(16), p.f(16, True)
    y = S.table(p, x0, y, x1 - x0, ["Item", "Units", "Amount"], rows_, [0.6, 0.18, 0.22], "lrr", tf, tfb,
                head_fill=tint(c, 0.25), head_ink=INK, grid=(220, 220, 225))
    y = S.totals(p, x1 - 10, y + 12, doc, raw, tf, tfb, label_x=x1 - 420)
    if y < H - 520:
        y = S.history_chart(p, x0, y + 20, 640, doc)
    S.small_print(p, x0, y + 20, x1 - x0, H - 140, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 90, x0, x1, 12, decoy_here=doc["decoy"] and not contact_decoy, colour=c)


LB_LAYOUTS = {"lb_fibre_invoice": lay_lb_fibre_invoice, "lb_bank_letter": lay_lb_bank_letter,
              "lb_retail_account": lay_lb_retail_account, "lb_water_board": lay_lb_water_board}
LB_TYPES = {"lb_fibre_invoice": "cellphone_account", "lb_bank_letter": "bank_statement",
            "lb_retail_account": "retail_account", "lb_water_board": "utility_bill"}
_NEW = ["titillium", "oxygen", "hind", "arvo", "spacemono"]
LB_LAYOUT_FONTS = {
    "lb_fibre_invoice": ["titillium", "oxygen", "hind", "lib_sans"],
    "lb_bank_letter": ["arvo", "oxygen", "dejavu_serif", "titillium"],
    "lb_retail_account": ["hind", "titillium", "oxygen", "dejavu_sans"],
    "lb_water_board": ["oxygen", "spacemono", "hind", "lib_sans"],
}
LB_DATE_STYLES = {
    "lb_fibre_invoice": ["d_mon_y", "dmy_slash", "iso"], "lb_bank_letter": ["d_month_y", "month_d_y"],
    "lb_retail_account": ["dmy_slash", "d_mon_y"], "lb_water_board": ["ymd_slash", "dmy_dot", "d_month_y"],
}
LB_PERIOD_P = {"lb_fibre_invoice": 0.7, "lb_bank_letter": 0.0, "lb_retail_account": 0.6, "lb_water_board": 0.7}
LAYOUT_ORDER = list(LB_LAYOUTS)

# --------------------------------------------------------------------------- #
# Cases and customers
# --------------------------------------------------------------------------- #

CASES = ["genuine"] * 4 + ["wrong_person", "wrong_address", "old", "issuer_decoy"]  # 50% genuine, 12.5% each negative


def typed_street(street: str, rng: random.Random) -> str:
    """A street as a customer types it: the suffix abbreviated or spelled out."""
    words = street.split()
    full = {v: k for k, v in LB_ABBREV.items()}
    last = words[-1]
    if rng.random() < 0.45:
        if last in LB_ABBREV:
            words[-1] = LB_ABBREV[last]
        elif last in full:
            words[-1] = full[last]
    return " ".join(words)


def typed_case(s: str | None, rng: random.Random, mode: str) -> str | None:
    if s is None:
        return None
    return s.upper() if mode == "upper" else s.lower() if mode == "lower" else s


def typed_address(a: dict, rng: random.Random) -> dict:
    mode = rng.choices(["as_is", "upper", "lower"], [70, 20, 10])[0]
    out = {
        "street": typed_case(typed_street(a["street"], rng), rng, mode),
        "suburb": typed_case(a["suburb"], rng, mode) if a.get("suburb") and rng.random() > 0.15 else None,
        "city": typed_case(a["city"], rng, mode),
        "province": a["province"] if rng.random() < 0.7 else None,
        "postal_code": a["postal_code"] if rng.random() < 0.95 else None,
    }
    return out


def id_name(person: dict, rng: random.Random) -> str:
    """The name as an ID prints it: forenames then surname, upper case."""
    names = [person["first"]] + ([person["middle"]] if rng.random() < 0.65 or person["style"] in ("full_mid", "title_inits", "sur_first") else [])
    return " ".join(names + [person["surname"]]).upper()


def other_name(person: dict, rng: random.Random, same_surname: bool) -> str:
    while True:
        female = rng.random() < 0.5
        first = rng.choice(S.FIRST_F if female else S.FIRST_M)
        if first[0] == person["first"][0] or first == person["middle"]:
            continue
        middle = rng.choice(S.FIRST_F + S.FIRST_M)
        if middle[0] in (person["first"][0], person["middle"][0]):
            continue
        surname = person["surname"] if same_surname else rng.choice(S.SURNAMES)
        if not same_surname and surname[:3].lower() == person["surname"][:3].lower():
            continue
        return f"{first} {middle} {surname}".upper()


def other_number(num: str, rng: random.Random) -> str:
    digits = re.match(r"\d+", num).group(0)
    while True:
        n = str(rng.randint(1, 999))
        # Not a one-digit slip of the true number: a wrong address, not an OCR test.
        if n != digits and not (len(n) == len(digits) and sum(a != b for a, b in zip(n, digits)) == 1):
            return n + num[len(digits):]


def customer_for(doc: dict, case: str, rng: random.Random) -> dict:
    person, addr = doc["person"], doc["addr"]
    name = id_name(person, rng)
    address = typed_address(addr, rng)
    if case == "wrong_person":
        same = rng.random() < 0.4 and person["style"] != "couple"
        name = other_name(person, rng, same)
    elif case == "wrong_address":
        num, street = addr["street"].split(" ", 1)
        if rng.random() < 0.5:
            wrong = f"{other_number(num, rng)} {street}"
        else:
            while True:
                st = rng.choice(S.STREETS)
                if st.split()[0] != street.split()[0]:
                    break
            wrong = f"{num} {st}"
        address = typed_address({**addr, "street": wrong}, rng)
    elif case == "issuer_decoy":
        decoy = next(d for d in doc["decoys"] if d["kind"] in ("head_office", "branch"))
        address = typed_address(decoy, rng)
    return {"name": name, "address": address}


def build_lb(seed: int, index: int, today: dt.date, attempt: int):
    rng = random.Random(f"lockbox:{seed}:{index}:{attempt}")
    layout = LAYOUT_ORDER[index % len(LAYOUT_ORDER)]
    case = CASES[(index // len(LAYOUT_ORDER)) % len(CASES)]
    doc_id = f"lbx_{index:05d}"
    doc = S.make_doc(rng, layout, today, doc_id)
    age = rng.randint(95, 400) if case == "old" else rng.randint(0, 88)
    ddate = today - dt.timedelta(days=age)
    doc.update(date=ddate, age=age, due=ddate + dt.timedelta(days=rng.choice([7, 10, 14, 21, 25, 30])))
    if doc["period"]:
        if rng.random() < 0.55:
            to = ddate.replace(day=1) - dt.timedelta(days=1)
            doc["period"] = (to.replace(day=1), to)
        else:
            to = ddate - dt.timedelta(days=rng.randint(0, 5))
            doc["period"] = (S.minus_months(to, 1) + dt.timedelta(days=1), to)
    if case == "issuer_decoy":
        doc["decoy"] = True
        doc["need_street_decoy"] = True
    W, H = S.SIZES.get(layout, (1240, 1754))
    p = S.Page(W, H, rng, rng.choice(S.LAYOUT_FONTS[layout]), k=rng.uniform(0.94, 1.06))
    S.LAYOUT_FN[layout](p, doc)
    if case == "issuer_decoy" and not any(d["kind"] in ("head_office", "branch") for d in doc["decoys"]):
        raise S.ProcReroll("no street decoy")
    a = doc["addr"]
    period = doc["period"]
    truth = {
        "id": doc_id, "layout": layout, "document_type": doc["type"], "size": [W, H], "today": today.isoformat(),
        "fields": {
            "holder_name": doc["person"]["printed"],
            "address": {k: a[k] for k in ("street", "suburb", "city", "province", "postal_code")},
            "province_printed": doc["province_printed"],
            "document_date": doc["date"].isoformat(),
            "statement_period": {"from": period[0].isoformat(), "to": period[1].isoformat()} if period else None,
            "issuer": doc.get("issuer_printed", doc["issuer"]["name"]),
            "account_number": doc["acc"],
            "document_type": doc["type"],
        },
        "issuer_canonical": doc["issuer"]["name"],
        "age_days": doc["age"], "recent": doc["date"] >= S.minus_months(today, 3), "future_dated": doc["age"] < 0,
        "decoy_addresses": [{k: d[k] for k in ("kind", "street", "suburb", "city", "province", "postal_code")} for d in doc["decoys"]],
        "person": {k: doc["person"][k] for k in ("first", "middle", "surname", "style")},
        "case": case,
        "expect_accept": case == "genuine",
        "customer": customer_for(doc, case, random.Random(f"lockbox-customer:{seed}:{index}")),
        "spans": p.spans,
    }
    return p.img, truth, p.texts


def render_one(job) -> str:
    seed, index, today, out = job
    install()
    for attempt in range(40):
        try:
            img, truth, texts = build_lb(seed, index, today, attempt)
        except (S.ProcReroll, StopIteration):
            continue
        try:
            problem = S.check(img, truth, texts)
        except AssertionError as e:
            problem = str(e)
        if not problem:
            break
    else:
        raise RuntimeError(f"lbx_{index:05d}: {problem}")
    out = Path(out)
    img.save(out / f"{truth['id']}.png", compress_level=1)
    (out / f"{truth['id']}.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False) + "\n")
    return truth["id"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7331)
    ap.add_argument("--today", default="2026-10-15")
    ap.add_argument("--out", default="/tmp/docscan-poa/lockbox/docs")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()
    install()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    today = dt.date.fromisoformat(args.today)
    jobs = [(args.seed, i, today, str(out)) for i in range(args.count)]
    t0 = time.perf_counter()
    with mp.Pool(args.jobs) as pool:
        ids = list(pool.imap_unordered(render_one, jobs, chunksize=2))
    print(f"wrote {len(ids)} lockbox documents to {out} in {time.perf_counter() - t0:.1f} s ({len(S.PLACES)} places)")


if __name__ == "__main__":
    main()
