"""Render fictional South African proof-of-address (PoA) documents with word-level truth.

Every person and every issuer here is invented: holder names are random
combinations of common South African first names and surnames, issuers are
made-up names checked against a deny-list of real companies, and logos are
plain geometric shapes with initials. Only the places are real: PLACES is a
table of real suburbs/towns with their street postal codes (see POA.md).

The pages are for a word-level field tagger that runs on OCR output, so each
<id>.json lists every drawn occurrence of every ground-truth field as a span
with tight per-word pixel boxes. All field text is drawn through draw_parts /
draw_words / Page.flow, which compute the boxes from the same strings and
offsets that are drawn, so the spans cannot drift from the image. Decoys
(the issuer's own address, payment/branch addresses, due and payment dates,
meter, invoice, VAT and phone numbers) are drawn but are not in the spans.

Document i uses layout LAYOUTS[i % len(LAYOUTS)] and its own RNG seeded from
(seed, i), so any document is reproducible on its own and parallel runs over
index ranges give identical output.

Outputs in --out: <id>.png (RGB, 150 dpi) and <id>.json; with --debug also
<id>_boxes.png with the span boxes drawn. Also writes PLACES to
/tmp/docscan-poa/places.json.

Run: .venv/bin/python poa_synth.py [--count 40] [--seed 11] [--out /tmp/docscan-poa/synth]
     [--layouts util_band,bank_classic] [--today 2026-10-15] [--start-index 0] [--jobs 8] [--debug]
     [--procedural]

With --procedural every page is composed by lay_proc from independently placed,
styled and labelled blocks (header, holder, details, decoys, table, small print,
footer) instead of one of the fixed LAYOUTS; see POA.md.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import random
import re
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PLACES_JSON = Path("/tmp/docscan-poa/places.json")

# --------------------------------------------------------------------------- #
# Safety lists: nothing real, nothing personal
# --------------------------------------------------------------------------- #

REAL_COMPANIES = [
    "Eskom", "City Power", "Standard Bank", "FNB", "First National", "ABSA", "Nedbank", "Capitec", "Investec",
    "TymeBank", "Discovery", "Vodacom", "MTN", "Telkom", "Cell C", "Rain", "Old Mutual", "Sanlam", "Liberty",
    "Outsurance", "Momentum", "City of Cape Town", "City of Johannesburg", "City of Tshwane", "eThekwini",
    "Rand Water", "Umgeni", "Multichoice", "DStv",
]
REAL_COMPANY_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in REAL_COMPANIES) + r")\b", re.IGNORECASE)
# Strings that must never appear on a page: real people's names and document
# numbers from photographs used elsewhere in this project, kept here only as
# truncated SHA-256 digests so this public file does not carry them.
FORBIDDEN_NAME_DIGESTS = {'71849ff62b22ff87', '3c528da4f5278577', '5ba2e45ddc136cf8', '6337eafc0e697894', '4f315a78be465965'}
FORBIDDEN_CODE_DIGESTS = {'b9c64de4e23a989e', 'b0f327238a8c36dc', '7408d06d0a48347c', 'c918a89ea2ce5d3f', '4e21d6ab07aac872', 'bf7989f1f71358ac', '7292deeaa9fe30a8', '24328701f7a926d1'}
FORBIDDEN_NAME_LENGTHS = [6, 7, 8]
FORBIDDEN_CODE_LENGTHS = [5, 6, 7]


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _digest_hit(text: str, digests: set[str], lengths: list[int]) -> str | None:
    for n in lengths:
        for i in range(len(text) - n + 1):
            if _digest(text[i : i + n]) in digests:
                return text[i : i + n]
    return None


def forbidden_in(text: str) -> str | None:
    """The first forbidden string found in text (names anywhere; codes with separators ignored)."""
    up = text.upper()
    hit = _digest_hit(up, FORBIDDEN_NAME_DIGESTS, FORBIDDEN_NAME_LENGTHS)
    if hit:
        return hit
    squashed = re.sub(r"[\s\-./,]", "", up)  # a printed number split by separators still counts
    hit = _digest_hit(squashed, FORBIDDEN_CODE_DIGESTS, FORBIDDEN_CODE_LENGTHS)
    if hit:
        return hit
    m = REAL_COMPANY_RE.search(text)
    return m.group(0) if m else None


# --------------------------------------------------------------------------- #
# Places: real suburbs/towns and their street postal codes
# --------------------------------------------------------------------------- #

GP, WC, KZN, EC, FS, LP, MP, NW, NC = ("Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape", "Free State",
                                       "Limpopo", "Mpumalanga", "North West", "Northern Cape")

# (suburb or None for a town printed without one, city/town, province, street postal code)
PLACES: list[tuple[str | None, str, str, str]] = [
    ("Sandton", "Johannesburg", GP, "2196"), ("Rosebank", "Johannesburg", GP, "2196"),
    ("Parktown", "Johannesburg", GP, "2193"), ("Melville", "Johannesburg", GP, "2092"),
    ("Braamfontein", "Johannesburg", GP, "2001"), ("Marshalltown", "Johannesburg", GP, "2001"),
    ("Randburg", "Johannesburg", GP, "2194"), ("Orlando West", "Soweto", GP, "1804"),
    ("Hatfield", "Pretoria", GP, "0083"), ("Arcadia", "Pretoria", GP, "0083"), ("Brooklyn", "Pretoria", GP, "0181"),
    ("Waterkloof", "Pretoria", GP, "0181"), ("Lynnwood", "Pretoria", GP, "0081"), ("Sunnyside", "Pretoria", GP, "0002"),
    ("Lyttelton", "Centurion", GP, "0157"), ("Halfway House", "Midrand", GP, "1685"),
    (None, "Kempton Park", GP, "1619"), (None, "Benoni", GP, "1501"), (None, "Boksburg", GP, "1459"),
    (None, "Germiston", GP, "1401"), (None, "Edenvale", GP, "1610"), (None, "Springs", GP, "1559"),
    ("Rondebosch", "Cape Town", WC, "7700"), ("Newlands", "Cape Town", WC, "7700"), ("Claremont", "Cape Town", WC, "7708"),
    ("Observatory", "Cape Town", WC, "7925"), ("Woodstock", "Cape Town", WC, "7925"), ("Sea Point", "Cape Town", WC, "8005"),
    ("Green Point", "Cape Town", WC, "8005"), ("Gardens", "Cape Town", WC, "8001"), ("Muizenberg", "Cape Town", WC, "7945"),
    ("Wynberg", "Cape Town", WC, "7800"), ("Bellville", "Cape Town", WC, "7530"), ("Durbanville", "Cape Town", WC, "7550"),
    ("Khayelitsha", "Cape Town", WC, "7784"), ("Mitchells Plain", "Cape Town", WC, "7785"),
    ("Milnerton", "Cape Town", WC, "7441"), ("Somerset West", "Cape Town", WC, "7130"),
    (None, "Stellenbosch", WC, "7600"), (None, "Paarl", WC, "7646"), (None, "Worcester", WC, "6850"),
    (None, "Hermanus", WC, "7200"), (None, "Mossel Bay", WC, "6500"),
    ("Umhlanga", "Durban", KZN, "4319"), ("Morningside", "Durban", KZN, "4001"), ("Berea", "Durban", KZN, "4001"),
    ("Glenwood", "Durban", KZN, "4001"), ("Musgrave", "Durban", KZN, "4001"), ("Durban North", "Durban", KZN, "4051"),
    ("Westville", "Durban", KZN, "3629"), ("Pinetown", "Durban", KZN, "3610"), ("Amanzimtoti", "Durban", KZN, "4126"),
    (None, "Ballito", KZN, "4420"), (None, "Pietermaritzburg", KZN, "3201"), (None, "Hilton", KZN, "3245"),
    (None, "Richards Bay", KZN, "3900"), (None, "Newcastle", KZN, "2940"), (None, "Ladysmith", KZN, "3370"),
    ("Summerstrand", "Gqeberha", EC, "6001"), ("Walmer", "Gqeberha", EC, "6070"), ("Newton Park", "Gqeberha", EC, "6045"),
    ("Vincent", "East London", EC, "5247"), ("Berea", "East London", EC, "5241"), ("Quigney", "East London", EC, "5201"),
    ("Beacon Bay", "East London", EC, "5241"), (None, "Makhanda", EC, "6139"), (None, "Mthatha", EC, "5099"),
    (None, "Jeffreys Bay", EC, "6330"),
    ("Westdene", "Bloemfontein", FS, "9301"), ("Brandwag", "Bloemfontein", FS, "9301"), ("Willows", "Bloemfontein", FS, "9301"),
    ("Universitas", "Bloemfontein", FS, "9301"), ("Langenhoven Park", "Bloemfontein", FS, "9330"),
    (None, "Welkom", FS, "9459"), (None, "Bethlehem", FS, "9701"), (None, "Kroonstad", FS, "9499"),
    (None, "Sasolburg", FS, "1947"), (None, "Parys", FS, "9585"), (None, "Harrismith", FS, "9880"),
    ("Bendor", "Polokwane", LP, "0699"), (None, "Tzaneen", LP, "0850"), (None, "Thohoyandou", LP, "0950"),
    (None, "Louis Trichardt", LP, "0920"), (None, "Bela-Bela", LP, "0480"), (None, "Phalaborwa", LP, "1390"),
    (None, "Musina", LP, "0900"),
    ("Sonheuwel", "Mbombela", MP, "1200"), (None, "Mbombela", MP, "1200"), (None, "White River", MP, "1240"),
    (None, "eMalahleni", MP, "1035"), (None, "Middelburg", MP, "1050"), (None, "Secunda", MP, "2302"),
    (None, "Ermelo", MP, "2350"), (None, "Barberton", MP, "1300"), (None, "Hazyview", MP, "1242"),
    (None, "Standerton", MP, "2430"),
    (None, "Rustenburg", NW, "0299"), (None, "Potchefstroom", NW, "2531"), (None, "Mahikeng", NW, "2745"),
    (None, "Klerksdorp", NW, "2571"), (None, "Brits", NW, "0250"), (None, "Hartbeespoort", NW, "0216"),
    (None, "Vryburg", NW, "8601"), (None, "Lichtenburg", NW, "2740"),
    ("Belgravia", "Kimberley", NC, "8301"), (None, "Kimberley", NC, "8301"), (None, "Upington", NC, "8801"),
    (None, "Springbok", NC, "8240"), (None, "Kuruman", NC, "8460"), (None, "De Aar", NC, "7000"),
    (None, "Kathu", NC, "8446"),
]

STREETS = [
    "Jan Smuts Avenue", "Acacia Road", "Church Street", "Voortrekker Road", "Nelson Mandela Drive", "Main Road",
    "Protea Street", "Umgeni Road", "Oak Avenue", "Jacaranda Street", "Beach Road", "Station Road", "Market Street",
    "Long Street", "Victoria Road", "Kerk Street", "Hoof Street", "Dorp Street", "Pretorius Street", "Florida Road",
    "Walter Sisulu Street", "Steve Biko Road", "Oliver Tambo Drive", "Bree Street", "Loop Street", "Rivonia Road",
    "Louis Botha Avenue", "Marine Drive", "Mimosa Street", "Disa Avenue", "Aloe Crescent", "Kiepersol Street",
    "Ridge Road", "Hill Street", "Park Lane", "Valley Road", "Wattle Close", "Impala Street", "Kudu Avenue",
    "Eland Street", "Fig Tree Lane", "Moshoeshoe Street", "Albertina Sisulu Road", "Queen Street",
    "King Edward Road", "Vergenoeg Street", "Bloekom Avenue", "Sunbird Crescent", "Hadeda Lane", "Mopani Road",
]
ABBREV = {"Road": "Rd", "Street": "St", "Avenue": "Ave", "Drive": "Dr", "Crescent": "Cres", "Lane": "Ln", "Close": "Cl"}

# --------------------------------------------------------------------------- #
# People (random combinations; nobody real)
# --------------------------------------------------------------------------- #

FIRST_M = [
    "Sipho", "Thabo", "Mandla", "Bongani", "Sibusiso", "Themba", "Lwazi", "Kagiso", "Tshepo", "Neo", "Tumelo",
    "Katlego", "Pieter", "Johan", "Willem", "Hendrik", "Francois", "Gerhard", "Ruan", "Jaco", "Michael", "David",
    "John", "Peter", "Andrew", "James", "Mohammed", "Yusuf", "Ashwin", "Rajesh", "Pravin", "Siyabonga", "Lunga",
    "Xolani", "Vusi", "Musa", "Tebogo", "Kabelo", "Ofentse", "Riaan", "Ebrahim", "Faizal", "Clinton", "Luthando",
]
FIRST_F = [
    "Thandiwe", "Lerato", "Nomvula", "Zanele", "Nokuthula", "Ayanda", "Precious", "Palesa", "Naledi", "Refilwe",
    "Boitumelo", "Dineo", "Karabo", "Anika", "Elmarie", "Marike", "Annelie", "Liezel", "Sunette", "Chantelle",
    "Priya", "Kavitha", "Shanthi", "Fatima", "Ayesha", "Zainab", "Sarah", "Emma", "Megan", "Lindiwe", "Nosipho",
    "Busisiwe", "Yolanda", "Sindisiwe", "Asanda", "Khanyisile", "Masego", "Onalenna", "Nthabiseng", "Ronel",
    "Charlene", "Mbali", "Zodwa", "Lebogang", "Mpho",
]
SURNAMES = [
    "Nkosi", "Dlamini", "Mokoena", "Ndlovu", "Khumalo", "Zulu", "Mthembu", "Ngcobo", "Shabalala", "Mahlangu",
    "Sithole", "Mkhize", "Cele", "Gumede", "Xaba", "Mabaso", "Zungu", "Mbatha", "Ntuli", "Jali", "Makhaya", "Qwabe",
    "Molefe", "Motaung", "Mofokeng", "Letsoalo", "Sebola", "Masilo", "Modise", "Mothibi", "Phiri", "Tau", "Seleka",
    "van der Merwe", "Botha", "Pretorius", "du Plessis", "Venter", "Nel", "Coetzee", "Fourie", "van Wyk", "Steyn",
    "Kruger", "Swanepoel", "Marais", "Joubert", "du Toit", "Smit", "Visser", "Bezuidenhout", "Smith", "Williams",
    "Jones", "Brown", "Taylor", "Adams", "Wilson", "Naidoo", "Pillay", "Govender", "Reddy", "Moodley", "Chetty",
    "Singh", "Maharaj", "Padayachee", "Petersen", "Jacobs", "Hendricks", "Isaacs", "Abrahams", "Davids", "Arendse",
    "Daniels", "Patel", "Khan", "Moosa",
]
FIRST_M = [n for n in FIRST_M if not forbidden_in(n)]
FIRST_F = [n for n in FIRST_F if not forbidden_in(n)]
SURNAMES = [n for n in SURNAMES if not forbidden_in(n)]
assert len(FIRST_M) + len(FIRST_F) >= 60 and len(SURNAMES) >= 60

# --------------------------------------------------------------------------- #
# Issuers (invented)
# --------------------------------------------------------------------------- #

ROOTS = ["Umoya", "Khanyelo", "Tswelo", "Imvelo", "Nalendi", "Ravelo", "Zinathi", "Morenzi", "Qhamani", "Velaphi",
         "Amandlo", "Thebelo", "Sekhuni", "Lumelo", "Kgatelo", "Kwezilo", "Ondela", "Siphelo", "Karoolig", "Suidkus"]
MUNI_PLACES = ["Kwaggaskloof", "Witdoringvlei", "Silwerduin", "Mthonjeni Valley", "Klipdraai-Noord", "Inyathi Bay",
               "Rooiheuwel", "Tsiloane", "Bergvlei", "Umsinsi Heights"]
SUFFIX = {
    "utility_bill": ["Power", "Energy", "Utilities", "Electricity", "Water & Power"],
    "bank_statement": ["Bank", "Savings Bank", "Mutual Bank", "Community Bank"],
    "cellphone_account": ["Mobile", "Telecom", "Wireless", "Networks"],
    "lease_agreement": ["Property Rentals", "Estates", "Property Management", "Letting Agents", "Realty"],
    "insurance_statement": ["Assurance", "Insure", "Mutual", "Life", "Insurance"],
}
TAGLINE = {
    "utility_bill": ["Electricity and water services", "Powering homes since 1998", "Energy for every household"],
    "bank_statement": ["Banking made simple", "Your money, your way", "Personal banking"],
    "cellphone_account": ["Stay connected", "Mobile and data services", "Talk. Text. Data."],
    "lease_agreement": ["Residential letting and management", "Homes to rent", "Rental specialists"],
    "insurance_statement": ["Cover you can count on", "Short-term and life insurance", "Protecting what matters"],
    "municipal_account": ["Service delivery for all", "Working together for a better town", "Rates and services"],
}
for _r in ROOTS + MUNI_PLACES:
    assert not forbidden_in(_r), _r

COLOURS = [(0, 92, 151), (18, 120, 90), (160, 38, 50), (110, 50, 140), (215, 110, 20), (0, 128, 128),
           (40, 60, 110), (150, 110, 0), (70, 120, 30), (190, 50, 110), (25, 25, 25), (0, 105, 190)]

# --------------------------------------------------------------------------- #
# Fonts and drawing primitives
# --------------------------------------------------------------------------- #

DV, LB = "/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/truetype/liberation/"
FONTS = {
    "dejavu_sans": (DV + "DejaVuSans.ttf", DV + "DejaVuSans-Bold.ttf"),
    "dejavu_serif": (DV + "DejaVuSerif.ttf", DV + "DejaVuSerif-Bold.ttf"),
    "dejavu_mono": (DV + "DejaVuSansMono.ttf", DV + "DejaVuSansMono-Bold.ttf"),
    "lib_sans": (LB + "LiberationSans-Regular.ttf", LB + "LiberationSans-Bold.ttf"),
    "lib_serif": (LB + "LiberationSerif-Regular.ttf", LB + "LiberationSerif-Bold.ttf"),
    "lib_mono": (LB + "LiberationMono-Regular.ttf", LB + "LiberationMono-Bold.ttf"),
}
INK, GREY, LIGHT, WHITE = (25, 25, 30), (90, 90, 96), (150, 150, 155), (255, 255, 255)


@lru_cache(maxsize=None)
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    # BASIC layout: prefix widths add up exactly to what draw.text renders.
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=200000)
def _word_len(font, word: str) -> float:
    return font.getlength(word)


def tint(c: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Mix colour c with white: t=1 is c, t=0 is white."""
    return tuple(int(255 - (255 - v) * t) for v in c)


def _word_boxes(draw: ImageDraw.ImageDraw, full: str, start: int, part: str, x: float, y: float, font) -> list[dict]:
    words = []
    for m in re.finditer(r"\S+", part):
        k = start + m.start()
        xw = x + draw.textlength(full[:k], font=font)
        b = draw.textbbox((xw, y), m.group(), font=font)
        words.append({"text": m.group(), "box": [int(b[0]), int(b[1]), int(round(b[2])), int(round(b[3]))]})
    return words


def draw_parts(draw: ImageDraw.ImageDraw, xy: tuple[float, float], parts: list, font, fill, *,
               spans: list | None = None, texts: list | None = None, anchor: str = "l") -> tuple[float, float]:
    """Draw the concatenation of parts on one line; parts are str or (text, label).

    Every labelled part becomes a span whose word boxes come from the drawn
    string's own prefix widths. anchor: l(eft), r(ight) or c(entre) at xy[0].
    Returns (x_left, width).
    """
    parts = [(p, None) if isinstance(p, str) else p for p in parts]
    full = "".join(t for t, _ in parts)
    x, y = xy
    w = draw.textlength(full, font=font)
    x = x - w if anchor == "r" else x - w / 2 if anchor == "c" else x
    draw.text((x, y), full, font=font, fill=fill)
    if texts is not None:
        texts.append(full)
    k = 0
    for t, lab in parts:
        if lab and spans is not None and t.strip():
            assert t == t.strip(), repr(t)
            spans.append({"label": lab, "text": t, "words": _word_boxes(draw, full, k, t, x, y, font)})
        k += len(t)
    return x, w


def draw_words(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, label: str | None = None,
               *, spans: list | None = None, texts: list | None = None, anchor: str = "l") -> tuple[float, float]:
    """Draw one string; with a label, record it as a span with per-word boxes."""
    return draw_parts(draw, xy, [(text, label)], font, fill, spans=spans, texts=texts, anchor=anchor)


class Page:
    """The canvas plus the span and text records for one document."""

    def __init__(self, w: int, h: int, rng: random.Random, fam: str, k: float = 1.0):
        self.w, self.h, self.rng, self.fam, self.k = w, h, rng, fam, k
        paper = rng.choice([(255, 255, 255), (253, 253, 250), (250, 251, 252)])
        self.img = Image.new("RGB", (w, h), paper)
        self.d = ImageDraw.Draw(self.img)
        self.spans: list[dict] = []
        self.texts: list[str] = []

    def f(self, size: float, bold: bool = False, fam: str | None = None):
        return load_font(FONTS[fam or self.fam][bool(bold)], max(9, round(size * self.k)))

    def text(self, x, y, parts, font, fill=INK, anchor="l"):
        if isinstance(parts, str):
            parts = [parts]
        return draw_parts(self.d, (x, y), parts, font, fill, spans=self.spans, texts=self.texts, anchor=anchor)

    def lh(self, font, extra: float = 1.32) -> int:
        return int(round(font.size * extra))

    def flow_lines(self, width, parts, font):
        toks = []
        for idx, p in enumerate(parts):
            t, lab = (p, None) if isinstance(p, str) else p
            toks += [(w, lab, idx) for w in t.split()]
        lines, cur, cur_w = [], [], 0.0
        space = font.getlength(" ")
        for tok in toks:
            tw = _word_len(font, tok[0])
            if cur and cur_w + space + tw > width:
                lines.append(cur)
                cur, cur_w = [tok], tw
            else:
                cur_w += (space if cur else 0) + tw
                cur.append(tok)
        if cur:
            lines.append(cur)
        return lines

    def flow(self, x, y, width, parts, font, fill=INK, line_h=None) -> float:
        """Word-wrap parts into width; a labelled part that wraps stays one span. Returns the next y."""
        line_h = line_h or self.lh(font)
        by_idx: dict[int, dict] = {}
        for line in self.flow_lines(width, parts, font):
            full = " ".join(w for w, _, _ in line)
            self.d.text((x, y), full, font=font, fill=fill)
            self.texts.append(full)
            k = 0
            for w, lab, idx in line:
                if lab:
                    if idx not in by_idx:
                        t = parts[idx][0]
                        by_idx[idx] = {"label": lab, "text": t, "words": []}
                        self.spans.append(by_idx[idx])
                    by_idx[idx]["words"] += _word_boxes(self.d, full, k, w, x, y, font)
                k += len(w) + 1
            y += line_h
        return y

    def flow_height(self, width, parts, font, line_h=None) -> int:
        return len(self.flow_lines(width, parts, font)) * (line_h or self.lh(font))

    def rule(self, x0, y, x1, fill=LIGHT, width=1, dash: int = 0):
        if dash:
            for x in range(int(x0), int(x1), dash * 2):
                self.d.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
        else:
            self.d.line([(x0, y), (x1, y)], fill=fill, width=width)


# --------------------------------------------------------------------------- #
# Values: dates, money, numbers, names, addresses
# --------------------------------------------------------------------------- #

MONTHS = [None, "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def minus_months(d: dt.date, n: int) -> dt.date:
    m = d.month - n
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


DATE_STYLES = ["d_month_y", "d_mon_y", "iso", "dmy_slash", "ymd_slash", "dmy_dot", "month_d_y", "d_mon_yy"]


def fmt_date(d: dt.date, style: str, lead0: bool = True, upper: bool = False) -> str:
    dd = f"{d.day:02d}" if lead0 else str(d.day)
    s = {
        "d_month_y": f"{dd} {MONTHS[d.month]} {d.year}",
        "d_mon_y": f"{dd} {MONTHS[d.month][:3]} {d.year}",
        "iso": d.isoformat(),
        "dmy_slash": f"{d.day:02d}/{d.month:02d}/{d.year}",
        "ymd_slash": f"{d.year}/{d.month:02d}/{d.day:02d}",
        "dmy_dot": f"{d.day:02d}.{d.month:02d}.{d.year}",
        "month_d_y": f"{MONTHS[d.month]} {d.day}, {d.year}",
        "d_mon_yy": f"{d.day:02d}-{MONTHS[d.month][:3]}-{d.year % 100:02d}",
    }[style]
    return s.upper() if upper else s


def money(cents: int, style: int = 0) -> str:
    neg = cents < 0
    r, c = divmod(abs(cents), 100)
    grp = f"{r:,}"
    s = [f"R {grp.replace(',', ' ')}.{c:02d}", f"R{grp.replace(',', ' ')}.{c:02d}", f"R{grp}.{c:02d}"][style]
    return ("-" + s) if neg else s


def digits(rng: random.Random, n: int, first_nonzero: bool = True) -> str:
    while True:
        s = "".join(rng.choice("0123456789") for _ in range(n))
        if first_nonzero and s[0] == "0":
            continue
        if not forbidden_in(s):
            return s


def group(s: str, sizes: list[int], sep: str = " ") -> str:
    out, k = [], 0
    for n in sizes:
        out.append(s[k:k + n])
        k += n
    if k < len(s):
        out.append(s[k:])
    return sep.join(x for x in out if x)


def account_number(rng: random.Random, dtype: str) -> str:
    style = rng.randrange(5)
    if dtype == "bank_statement":
        return [lambda: group(digits(rng, 10), [4, 4, 2]), lambda: digits(rng, 10), lambda: group(digits(rng, 11), [3, 4, 4]),
                lambda: digits(rng, 11), lambda: group(digits(rng, 10), [2, 4, 4], "-")][style]()
    if dtype == "insurance_statement":
        return [lambda: "POL-" + digits(rng, 8), lambda: "P" + digits(rng, 9), lambda: group(digits(rng, 10), [3, 3, 4]),
                lambda: "HC" + digits(rng, 7), lambda: digits(rng, 10)][style]()
    if dtype == "municipal_account":
        return [lambda: group(digits(rng, 12), [4, 4, 4]), lambda: digits(rng, 12), lambda: "ACC " + digits(rng, 8),
                lambda: group(digits(rng, 11), [2, 5, 4], "-"), lambda: digits(rng, 10)][style]()
    if dtype == "lease_agreement":
        return [lambda: "L" + digits(rng, 6), lambda: "LEASE-" + digits(rng, 5), lambda: "TEN" + digits(rng, 6),
                lambda: digits(rng, 7), lambda: "RA-" + digits(rng, 6)][style]()
    return [lambda: group(digits(rng, 10), [4, 4, 2]), lambda: "ACC-" + digits(rng, 7, False), lambda: digits(rng, 10),
            lambda: group(digits(rng, 10), [2, 4, 4], "-"), lambda: digits(rng, 9)][style]()


def phone(rng: random.Random, mobile: bool = False) -> str:
    if mobile:
        return f"0{rng.choice(['72', '73', '76', '79', '82', '83', '84'])} {digits(rng, 3, False)} {digits(rng, 4, False)}"
    if rng.random() < 0.3:
        return f"0860 {digits(rng, 3, False)} {digits(rng, 3, False)}"
    return f"0{rng.choice(['11', '12', '21', '31', '41', '43', '51', '15', '13', '18', '53'])} {digits(rng, 3)} {digits(rng, 4, False)}"


def make_person(rng: random.Random) -> dict:
    female = rng.random() < 0.5
    first = rng.choice(FIRST_F if female else FIRST_M)
    surname = rng.choice(SURNAMES)
    mid = rng.choice("ABCDEGJKLMNPSTZ")
    r = rng.random()
    title = "Dr" if r < 0.06 else ("Prof" if r < 0.075 else ("Mr" if not female else rng.choice(["Ms", "Mrs", "Mrs", "Miss"])))
    style = rng.choices(["title_full", "title_init", "init_dot", "full_mid", "couple", "title_inits", "full", "sur_first"],
                        [18, 22, 10, 12, 5, 12, 16, 5])[0]
    upper = rng.random() < 0.4
    sal = f"{title} {surname[0].upper() + surname[1:]}"
    if style == "title_full":
        name = f"{title} {first} {surname}"
    elif style == "title_init":
        name = f"{title} {first[0]} {surname}"
    elif style == "init_dot":
        name = f"{first[0]}. {surname}"
    elif style == "full_mid":
        name = f"{first} {mid} {surname}"
    elif style == "couple":
        name = f"Mr & Mrs {first[0]} {surname}" if not female else f"Mr & Mrs {rng.choice(FIRST_M)[0]} {surname}"
        sal = f"Mr and Mrs {surname[0].upper() + surname[1:]}"
    elif style == "title_inits":
        name = f"{title} {first[0]}{mid} {surname}"
        upper = upper or rng.random() < 0.5
    elif style == "sur_first":
        name = f"{surname}, {first[0]}{mid}"
    else:
        name = f"{first} {surname}"
    name = name.upper() if upper else name
    return {"first": first, "surname": surname, "title": title, "printed": name, "salutation": sal}


def other_person(rng: random.Random, doc: dict) -> dict:
    """A decoy person (consultant, broker) who never shares the holder's surname."""
    while True:
        q = make_person(rng)
        if q["surname"] != doc["person"]["surname"]:
            return q


def make_street(rng: random.Random) -> str:
    num = str(rng.randint(1, 999)) + (rng.choice("ABC") if rng.random() < 0.08 else "")
    st = rng.choice(STREETS)
    if rng.random() < 0.3:
        last = st.split()[-1]
        if last in ABBREV:
            st = st[: -len(last)] + ABBREV[last]
    return f"{num} {st}"


def make_address(rng: random.Random, exclude: set | None = None) -> dict:
    while True:
        sub, city, prov, code = rng.choice(PLACES)
        if not exclude or (sub, city) not in exclude:
            break
    return {"street": make_street(rng), "suburb": sub, "city": city, "province": prov, "postal_code": code}


def address_lines(a: dict, rng: random.Random, *, labelled: bool, single: bool = False,
                  upper: bool | None = None, province: str | None = None) -> tuple[list[list], bool]:
    """Lay out an address as lines of parts; returns (lines, province_printed).

    province: 'omit' | 'own' | 'after' (random when None, ~35% omit).
    Commas belong to the word they follow, so they sit inside the labelled part.
    """
    upper = rng.random() < 0.35 if upper is None else upper
    U = (lambda s: s.upper()) if upper else (lambda s: s)
    province = province or rng.choices(["omit", "own", "after"], [35, 35, 30])[0]
    L = (lambda lab: lab) if labelled else (lambda lab: None)
    items = [(U(a["street"]), L("STREET"))]
    if a["suburb"]:
        items.append((U(a["suburb"]), L("SUBURB")))
    city, prov, code = (U(a["city"]), L("CITY")), (U(a["province"]), L("PROVINCE")), (a["postal_code"], L("POSTAL_CODE"))
    if single:
        seq = items + [city] + ([prov] if province != "omit" else []) + [code]
        comma_before_code = rng.random() < 0.6
        parts = []
        for j, (t, lab) in enumerate(seq):
            last = j == len(seq) - 1
            nxt_is_code = j == len(seq) - 2
            t2 = t + ("," if not last and (not nxt_is_code or comma_before_code) else "")
            parts += [(t2, lab)] + ([" "] if not last else [])
        return [parts], province != "omit"
    lines = [[it] for it in items]
    code_mode = rng.choice(["own", "city", "city", "city_comma"])
    if province == "after":
        line = [(city[0] + ",", city[1]), " ", prov]
        if code_mode != "own":
            line[-1] = (prov[0] + ("," if code_mode == "city_comma" else ""), prov[1])
            line += [" ", code]
        lines.append(line)
        if code_mode == "own":
            lines.append([code])
    else:
        if code_mode == "own":
            lines.append([city])
            if province == "own":
                lines.append([prov])
            lines.append([code])
        else:
            lines.append([(city[0] + ("," if code_mode == "city_comma" else ""), city[1]), " ", code])
            if province == "own":
                lines.append([prov])
    return lines, province != "omit"


def decoy_address(rng: random.Random, holder: dict, kind: str) -> dict:
    a = make_address(rng, exclude={(holder["suburb"], holder["city"])})
    if kind == "postal":
        a["street"] = rng.choice(["PO Box ", "Private Bag X", "P.O. Box "]) + digits(rng, rng.randint(3, 5))
        a["suburb"] = None
    a["kind"] = kind
    return a


# --------------------------------------------------------------------------- #
# The document (all truth, chosen before drawing)
# --------------------------------------------------------------------------- #


def make_issuer(rng: random.Random, dtype: str) -> dict:
    while True:
        if dtype == "municipal_account":
            p = rng.choice(MUNI_PLACES)
            name = rng.choice([f"{p} Local Municipality", f"{p} Municipality", f"City of {p}", f"{p} Metropolitan Municipality"])
            legal = name
        else:
            name = f"{rng.choice(ROOTS)} {rng.choice(SUFFIX[dtype])}"
            legal = name + rng.choice([" (Pty) Ltd", " Limited", " Ltd", " (RF) (Pty) Ltd"])
        if not forbidden_in(name):
            break
    words = [w for w in re.split(r"[\s&-]+", name) if w and w[0].isupper() and w not in ("City", "of")]
    initials = "".join(w[0] for w in words[:2]) or name[:2].upper()
    site = re.sub(r"[^a-z]", "", name.lower().replace("municipality", "").replace("local", "").replace("metropolitan", ""))
    return {
        "name": name, "legal": legal, "initials": initials, "colour": rng.choice(COLOURS),
        "shape": rng.choice(["circle", "square", "triangle", "diamond", "rings", "bars"]),
        "tagline": rng.choice(TAGLINE[dtype]), "tel": phone(rng), "fax": phone(rng),
        "vat": "4" + digits(rng, 9, False), "reg": f"{rng.randint(1985, 2021)}/{digits(rng, 6, False)}/{rng.choice(['06', '07', '07', '10'])}",
        "web": f"www.{site}.co.za" if dtype != "municipal_account" else f"www.{site}.gov.za",
        "email": f"{rng.choice(['accounts', 'info', 'help', 'service'])}@{site}.co.za",
    }


def make_doc(rng: random.Random, layout: str, today: dt.date, doc_id: str, dtype: str | None = None) -> dict:
    dtype = dtype or LAYOUT_TYPES[layout]
    r = rng.random()
    if r < 0.03:
        age = -rng.randint(1, 10)
    elif r < 0.58:
        age = rng.randint(0, 90)
    else:
        age = rng.randint(91, 400)
    ddate = today - dt.timedelta(days=age)
    period = None
    if rng.random() < PERIOD_P[layout]:
        if rng.random() < 0.55:
            to = ddate.replace(day=1) - dt.timedelta(days=1)
            period = (to.replace(day=1), to)
        else:
            to = ddate - dt.timedelta(days=rng.randint(0, 5))
            period = (minus_months(to, 1) + dt.timedelta(days=1), to)
    person = make_person(rng)
    addr = make_address(rng)
    issuer = make_issuer(rng, dtype)
    style = rng.choice(LAYOUT_DATE_STYLES[layout]) if rng.random() < 0.7 else rng.choice(DATE_STYLES[:-1])
    if rng.random() < 0.02:
        style = "d_mon_yy"
    return {
        "id": doc_id, "layout": layout, "type": dtype, "today": today, "date": ddate, "age": age, "period": period,
        "person": person, "addr": addr, "issuer": issuer, "acc": account_number(rng, dtype),
        "date_style": style, "lead0": rng.random() < 0.7, "date_upper": rng.random() < 0.15,
        "money_style": rng.randrange(3), "decoy": rng.random() < 0.72, "extra_decoy": rng.random() < 0.35,
        "twice": rng.random() < 0.25, "province_printed": False, "decoys": [],
        "due": ddate + dt.timedelta(days=rng.choice([7, 10, 14, 21, 25, 30])),
    }


def D(doc: dict, d: dt.date) -> str:
    return fmt_date(d, doc["date_style"], doc["lead0"], doc["date_upper"])


def holder_parts(doc: dict) -> list:
    return [(doc["person"]["printed"], "HOLDER_NAME")]


def charges(rng: random.Random, dtype: str, n: int) -> list[tuple[str, str, int]]:
    pools = {
        "utility_bill": [("Electricity consumption", lambda: f"{rng.randint(180, 1400)} kWh", 180000),
                         ("Basic charge", lambda: "1 month", 25000), ("Network capacity charge", lambda: "1 month", 18000),
                         ("Water consumption", lambda: f"{rng.randint(6, 40)} kl", 60000), ("Sewerage", lambda: "1 month", 30000),
                         ("Refuse removal", lambda: "1 month", 22000), ("Service fee", lambda: "1 month", 6000),
                         ("Ancillary levy", lambda: "1 month", 4000), ("Demand charge", lambda: f"{rng.randint(2, 15)} kVA", 30000),
                         ("Meter reading fee", lambda: "1", 3000), ("Environmental levy", lambda: f"{rng.randint(180, 900)} kWh", 5000),
                         ("Streetlighting", lambda: "1 month", 4500)],
        "municipal_account": [("Property rates", lambda: "Monthly", 150000), ("Water", lambda: f"{rng.randint(5, 35)} kl", 70000),
                              ("Electricity", lambda: f"{rng.randint(200, 1100)} kWh", 160000), ("Refuse", lambda: "Monthly", 25000),
                              ("Sewer", lambda: "Monthly", 30000), ("Sundry charges", lambda: "1", 5000),
                              ("Fire services levy", lambda: "Monthly", 4000), ("Rebate - pensioner", lambda: "Monthly", -9000),
                              ("Interest on arrears", lambda: "1", 3500), ("Water - basic", lambda: "Monthly", 9000)],
        "cellphone_account": [("Monthly subscription", lambda: "1 month", 39900), ("Data bundle 10 GB", lambda: "1", 19900),
                              ("Out-of-bundle calls", lambda: f"{rng.randint(3, 90)} min", 9000), ("SMS", lambda: f"{rng.randint(1, 40)}", 2000),
                              ("Device instalment", lambda: f"{rng.randint(2, 24)}/24", 45000), ("Device insurance", lambda: "1 month", 9900),
                              ("Itemised billing", lambda: "1", 1500), ("Roaming data", lambda: f"{rng.randint(20, 900)} MB", 8000),
                              ("Voice bundle 250 min", lambda: "1", 14900)],
        "insurance_statement": [("Household contents", lambda: "Monthly", 32000), ("Buildings", lambda: "Monthly", 54000),
                                ("Motor vehicle", lambda: "Monthly", 98000), ("Funeral cover", lambda: "Monthly", 12000),
                                ("Policy fee", lambda: "Monthly", 4500), ("Portable possessions", lambda: "Monthly", 8000),
                                ("Personal liability", lambda: "Monthly", 2500), ("Roadside assist", lambda: "Monthly", 3900)],
        "lease_agreement": [("Monthly rental", lambda: "Monthly", 950000), ("Deposit (held in trust)", lambda: "Once", 1200000),
                            ("Lease administration fee", lambda: "Once", 120000), ("Parking bay", lambda: "Monthly", 45000),
                            ("Water and electricity deposit", lambda: "Once", 150000), ("Key deposit", lambda: "Once", 25000)],
    }
    pool = pools[dtype]
    rows = rng.sample(pool, min(n, len(pool)))
    return [(desc, q(), int(base * rng.uniform(0.35, 1.6)) if base > 0 else base) for desc, q, base in rows]


def transactions(rng: random.Random, doc: dict, n: int) -> list[tuple[dt.date, str, int]]:
    p = doc["period"] or (doc["date"] - dt.timedelta(days=30), doc["date"])
    span = max(1, (p[1] - p[0]).days)
    descs = [("Salary credit", 1500000), ("POS purchase Corner Cafe", -18000), ("ATM withdrawal", -100000),
             ("Debit order insurance", -42000), ("EFT payment rent", -650000), ("Prepaid electricity", -50000),
             ("Monthly account fee", -6900), ("Interest received", 1200), ("Cash deposit", 200000),
             ("Airtime purchase", -9900), ("POS purchase Fuel Stop", -70000), ("Transfer from savings", 300000),
             ("Debit order gym", -38000), ("POS purchase Pharmacy", -24000), (f"EFT to {rng.choice('ABDJKLMNPST')} {rng.choice([s for s in SURNAMES if s != doc['person']['surname']])}", -150000)]
    rows = []
    for _ in range(n):
        desc, base = rng.choice(descs)
        rows.append((p[0] + dt.timedelta(days=rng.randint(0, span)), desc, int(base * rng.uniform(0.3, 1.5))))
    return sorted(rows)


SMALL_PRINT = [
    "Payment is due on or before the due date shown. Late payment may result in interest being charged on the overdue "
    "amount and, where applicable, in the suspension of services until the account is brought up to date.",
    "If you believe any charge on this statement is incorrect, please contact {I} within 30 days of the statement date. "
    "Undisputed amounts must still be paid by the due date while a query is being resolved.",
    "{I} processes your personal information in accordance with the Protection of Personal Information Act, 2013 "
    "(POPIA). We use it only to administer your account and will not share it without a lawful reason.",
    "Please quote your account number as the reference on every payment so that it can be allocated correctly. "
    "Payments may take up to three working days to reflect.",
    "This document is a computer-generated statement and is valid without a signature. Keep it for your records; "
    "a copy can be requested from {I} at no charge once per month.",
    "Meter readings marked as estimated will be adjusted once an actual reading is obtained. Please ensure that the "
    "meter is accessible to our readers at all reasonable times.",
    "Changes to your contact details, banking details or postal address must be submitted in writing, together with "
    "a certified copy of your identity document.",
    "{I} is an authorised financial services provider. Complaints that are not resolved to your satisfaction may be "
    "referred to the relevant ombud, whose details are available on request.",
    "Amounts shown include value-added tax at the standard rate of 15% where applicable. A full tax invoice is "
    "available on request.",
    "Debit orders are collected on the date agreed in your mandate. If the collection is unsuccessful a fee may be "
    "levied and the amount will be presented again.",
    "Thank you for choosing {I}. We value your business and are committed to resolving any service query promptly "
    "and courteously.",
    "Arrangements to pay off arrears may be made at any of our offices. An arrangement is only valid once confirmed "
    "in writing by an authorised official.",
]


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #


def logo(p: Page, x: float, y: float, s: float, doc: dict, colour=None, ink=WHITE) -> None:
    iss = doc["issuer"]
    c = colour or iss["colour"]
    d, sh = p.d, iss["shape"]
    if sh == "circle":
        d.ellipse((x, y, x + s, y + s), fill=c)
    elif sh == "square":
        d.rounded_rectangle((x, y, x + s, y + s), radius=s * 0.18, fill=c)
    elif sh == "triangle":
        d.polygon([(x + s / 2, y), (x + s, y + s), (x, y + s)], fill=c)
    elif sh == "diamond":
        d.polygon([(x + s / 2, y), (x + s, y + s / 2), (x + s / 2, y + s), (x, y + s / 2)], fill=c)
    elif sh == "rings":
        d.ellipse((x, y, x + s, y + s), fill=c)
        d.ellipse((x + s * 0.12, y + s * 0.12, x + s * 0.88, y + s * 0.88), outline=tint(c, 0.4) if c != WHITE else (220, 220, 220), width=max(2, int(s * 0.05)))
    else:
        for k in range(4):
            hh = s * (0.35 + 0.65 * (k + 1) / 4)
            d.rectangle((x + k * s / 4, y + s - hh, x + (k + 0.78) * s / 4, y + s), fill=c)
        ink = c
        y += s + 4
        f = p.f(s * 0.3, True)
        p.d.text((x + s / 2, y), iss["initials"], font=f, fill=c, anchor="ma")
        return
    f = p.f(s * (0.36 if sh != "triangle" else 0.28), True)
    cy = y + s * (0.5 if sh != "triangle" else 0.68)
    p.d.text((x + s / 2, cy), iss["initials"], font=f, fill=ink if c != WHITE else iss["colour"], anchor="mm")


def holder_block(p: Page, x, y, doc: dict, *, label: str | None, fs: float, line_h=None, name_bold=True,
                 single=False, upper=None, province=None, label_font=None, anchor="l", name=True) -> float:
    """Holder name + address, all labelled spans. Returns the y below the block."""
    rng = p.rng
    fnt, fb = p.f(fs), p.f(fs, name_bold)
    line_h = line_h or p.lh(fnt, 1.3)
    if label:
        lf = label_font or p.f(fs * 0.8, True)
        p.text(x, y, label, lf, GREY, anchor=anchor)
        y += p.lh(lf, 1.4)
    if name:
        p.text(x, y, holder_parts(doc), fb, INK, anchor=anchor)
        y += line_h
    lines, printed = address_lines(doc["addr"], rng, labelled=True, single=single, upper=upper, province=province)
    doc["province_printed"] |= printed
    for line in lines:
        p.text(x, y, line, fnt, INK, anchor=anchor)
        y += line_h
    return y


def decoy_block(p: Page, x, y, doc: dict, kind: str, fs: float, *, heading: str | None = None, single=False,
                anchor="l", contacts=True, fill=GREY, width=None) -> float:
    a = decoy_address(p.rng, doc["addr"], kind)
    doc["decoys"].append(a)
    fnt = p.f(fs)
    lh = p.lh(fnt, 1.3)
    if heading:
        p.text(x, y, heading, p.f(fs, True), fill, anchor=anchor)
        y += lh
    lines, _ = address_lines(a, p.rng, labelled=False, single=single, upper=p.rng.random() < 0.3)
    for line in lines:
        if width and single:
            y = p.flow(x, y, width, line, fnt, fill, lh)
        else:
            p.text(x, y, line, fnt, fill, anchor=anchor)
            y += lh
    if contacts:
        iss = doc["issuer"]
        for t in p.rng.sample([f"Tel {iss['tel']}", f"VAT No {iss['vat']}", f"Reg No {iss['reg']}", iss["web"], f"Fax {iss['fax']}"],
                              p.rng.randint(2, 3)):
            p.text(x, y, t, fnt, fill, anchor=anchor)
            y += lh
    return y


def kv_rows(p: Page, x, y, rows: list, lf, vf, *, val_x=None, right=None, gap=None, fill=INK, lfill=GREY,
            colon=False, rule=None) -> float:
    """Label/value rows. A value is a str or a list of parts. right: right-align values at this x."""
    gap = gap or max(p.lh(lf, 1.5), p.lh(vf, 1.35))
    for lab, val in rows:
        p.text(x, y + (vf.size - lf.size) * 0.7, lab + (":" if colon else ""), lf, lfill)
        parts = [val] if isinstance(val, str) else val
        if right is not None:
            p.text(right, y, parts, vf, fill, anchor="r")
        else:
            p.text(val_x, y, parts, vf, fill)
        if rule:
            p.rule(x, y + gap - 6, right or (val_x + 300), fill=rule)
        y += gap
    return y


def date_parts(doc: dict, d: dt.date, label: str) -> list:
    return [(D(doc, d), label)]


def period_parts(doc: dict, prefix: str = "", sep: str = " - ") -> list:
    a, b = doc["period"]
    return ([prefix] if prefix else []) + [(D(doc, a), "PERIOD_FROM"), sep, (D(doc, b), "PERIOD_TO")]


def period_rows(p: Page, doc: dict, font, avail: float, label: str, sep: str = " - ",
                labels: tuple[str, str] = ("Period from", "Period to")) -> list:
    """One 'label: from - to' row if it fits in avail px, else separate from/to rows."""
    parts = period_parts(doc, sep=sep)
    text = "".join(x if isinstance(x, str) else x[0] for x in parts)
    if p.d.textlength(text, font=font) <= avail:
        return [(label, parts)]
    return [(labels[0], date_parts(doc, doc["period"][0], "PERIOD_FROM")), (labels[1], date_parts(doc, doc["period"][1], "PERIOD_TO"))]


def table(p: Page, x, y, w, headers: list[str], rows: list[list], fracs: list[float], aligns: str, f, fb, *,
          row_h=None, head_fill=None, head_ink=WHITE, shade=None, grid=None) -> float:
    row_h = row_h or p.lh(f, 1.75)
    cols = [x + w * sum(fracs[:k]) for k in range(len(fracs) + 1)]

    def cell_x(k, a):
        return cols[k] + 10 if a == "l" else cols[k + 1] - 10

    if head_fill:
        p.d.rectangle((x, y, x + w, y + row_h), fill=head_fill)
    for k, h in enumerate(headers):
        p.text(cell_x(k, aligns[k]), y + (row_h - fb.size) / 2, h, fb, head_ink if head_fill else INK, anchor=aligns[k])
    y += row_h
    if not head_fill:
        p.rule(x, y - 2, x + w, INK, 2)
    for j, row in enumerate(rows):
        if shade and j % 2 == 1:
            p.d.rectangle((x, y, x + w, y + row_h), fill=shade)
        for k, v in enumerate(row):
            if v:
                p.text(cell_x(k, aligns[k]), y + (row_h - f.size) / 2, v, f, INK, anchor=aligns[k])
        y += row_h
        if grid:
            p.rule(x, y, x + w, grid)
    return y


def totals(p: Page, xr, y, doc: dict, rows: list[tuple[str, str, int]], f, fb, *, label_x, due_label="Due date",
           show_due=True, box_colour=None) -> float:
    sub = sum(r[2] for r in rows)
    vat = round(sub * 0.15)
    lh = p.lh(f, 1.6)
    ms = doc["money_style"]
    items = [("Subtotal (excl. VAT)", money(sub, ms)), ("VAT @ 15%", money(vat, ms))]
    for lab, val in items:
        p.text(label_x, y, lab, f, GREY)
        p.text(xr, y, val, f, INK, anchor="r")
        y += lh
    if box_colour:
        p.d.rectangle((label_x - 12, y - 4, xr + 12, y + lh + 2), fill=box_colour)
    p.text(label_x, y, "Total due", fb, INK)
    p.text(xr, y, money(sub + vat, ms), fb, INK, anchor="r")
    y += lh
    if show_due:
        p.text(label_x, y, due_label, f, GREY)
        p.text(xr, y, D(doc, doc["due"]), f, INK, anchor="r")
        y += lh
    doc["total"] = sub + vat
    return y


def charge_rows(p: Page, doc: dict, n: int, with_prev=True) -> tuple[list[list], list]:
    rng = p.rng
    rows = charges(rng, doc["type"], n)
    ms = doc["money_style"]
    out = []
    if with_prev and rng.random() < 0.6:
        prev = rng.randint(20000, 300000)
        out.append(["Previous balance", "", money(prev, ms)])
        out.append([f"Payment received {D(doc, doc['date'] - dt.timedelta(days=rng.randint(12, 28)))} - thank you", "", money(-prev, ms)])
    out += [[d, q, money(c, ms)] for d, q, c in rows]
    return out, rows


NOTICES = [
    ("Important notice", "Our customer care centre will be closed on public holidays. Online services and the self-service line remain available at all times."),
    ("Go paperless", "Receive your statement by email instead of post. It is quicker, safer and better for the environment. Register on our website."),
    ("Did you know?", "You can view your balance, download previous statements and update your contact details on our website at any time."),
    ("Save on your bill", "Switching off geysers during peak hours and fixing leaking taps can reduce your monthly account noticeably."),
    ("Beware of fraud", "We will never ask for your PIN or password by phone or email. Report suspicious requests to our fraud line immediately."),
    ("Planned maintenance", "Scheduled maintenance may cause short interruptions in some areas. Notices are published at least 48 hours in advance."),
]


def history_chart(p: Page, x, y, w, doc: dict) -> float:
    rng, c = p.rng, doc["issuer"]["colour"]
    unit = {"utility_bill": "kWh", "municipal_account": "kl", "cellphone_account": "GB"}.get(doc["type"], "kWh")
    title = rng.choice(["Consumption history", "Usage history", "Your usage over the last months"])
    p.text(x, y, f"{title} ({unit})", p.f(17, True), INK)
    y += 34
    n = rng.randint(6, 12)
    ch = 120
    vals = [rng.uniform(0.35, 1.0) for _ in range(n)]
    bw = min(60, (w - 20) / n)
    lf = p.f(12)
    m = doc["date"].month
    p.rule(x, y + ch, x + bw * n + 10, GREY)
    for k, v in enumerate(vals):
        bx = x + 10 + k * bw
        p.d.rectangle((bx, y + ch - v * ch, bx + bw * 0.7, y + ch), fill=tint(c, 0.35 + 0.65 * (k == n - 1)))
        mon = MONTHS[(m - n + k - 1) % 12 + 1][:3]
        p.text(bx + bw * 0.35, y + ch + 4, mon, lf, GREY, anchor="c")
    return y + ch + 30


def notice_box(p: Page, x, y, w, doc: dict, height_only=False) -> float:
    head, body = p.rng.choice(NOTICES)
    f = p.f(15)
    h = 44 + p.flow_height(w - 30, [body], f)
    if height_only:
        return h
    c = doc["issuer"]["colour"]
    p.d.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=tint(c, 0.08), outline=tint(c, 0.35), width=2)
    p.text(x + 15, y + 10, head, p.f(16, True), c)
    p.flow(x + 15, y + 36, w - 30, [body], f, INK)
    return y + h + 20


def pay_box(p: Page, x, y, w, doc: dict) -> float:
    rng = p.rng
    f, fb = p.f(15), p.f(15, True)
    lh = p.lh(f, 1.45)
    p.text(x, y, rng.choice(["How to pay", "Payment options", "Ways to pay"]), p.f(17, True), INK)
    y += 30
    bank = f"{rng.choice(ROOTS)} Bank"
    p.text(x, y, f"EFT: {bank}  |  Branch code {digits(rng, 6)}  |  Account {digits(rng, 10)}", f, INK)
    y += lh
    p.text(x, y, ["Reference: ", (doc["acc"], "ACCOUNT_NO")], fb, INK)
    y += lh
    y = p.flow(x, y, w, [rng.choice(["Pay in cash at any of our walk-in centres or at participating retailers.",
                                     "Debit order: complete the mandate on our website. Card payments: call our payment line."])], f, GREY, lh)
    return y + 20


def extras(p: Page, x, y, w, max_y, doc: dict) -> float:
    """Fill free space with a usage chart, a notice and/or a payment box, as real bills do."""
    kinds = ["notice", "pay"] + (["chart"] if doc["type"] in ("utility_bill", "municipal_account", "cellphone_account") else [])
    if doc["type"] == "bank_statement":
        kinds = ["notice"]
    p.rng.shuffle(kinds)
    for k in kinds:
        need = {"chart": 200, "pay": 150, "notice": 150}[k]
        if y + need > max_y or p.rng.random() < 0.2:
            continue
        y = history_chart(p, x, y, w, doc) if k == "chart" else pay_box(p, x, y, w, doc) if k == "pay" else notice_box(p, x, y, min(w, 760), doc)
    return y


def small_print(p: Page, x, y, w, max_y, doc: dict, fs: float, n: int, fill=GREY, issuer_upper=False) -> float:
    rng = p.rng
    if max_y - y > 330 and doc["type"] != "lease_agreement":
        y = extras(p, x, y, w, max_y - 130, doc)
        n = max(n, 3)
    f = p.f(fs)
    lh = p.lh(f, 1.28)
    paras = rng.sample(SMALL_PRINT, n)
    if not any("{I}" in s for s in paras) and rng.random() < 0.7:
        paras[0] = next(s for s in SMALL_PRINT if "{I}" in s)
    iname = doc["issuer"]["name"].upper() if issuer_upper else doc["issuer"]["name"]
    for s in paras:
        parts = []
        chunks = s.split("{I}")
        for k, c in enumerate(chunks):
            if k:
                # punctuation straight after the name belongs to its last word
                m = re.match(r"^([.,;:]?)", c)
                parts.append((iname + m.group(1), "ISSUER"))
                c = c[len(m.group(1)):]
            if c.strip():
                parts.append(c.strip())
        if y + p.flow_height(w, parts, f, lh) > max_y:
            break
        y = p.flow(x, y, w, parts, f, fill, lh) + lh * 0.45
    return y


def footer(p: Page, doc: dict, y, x0, x1, fs, *, decoy_here: bool, colour=None, centre=False) -> None:
    iss = doc["issuer"]
    f = p.f(fs)
    lh = p.lh(f, 1.35)
    p.rule(x0, y - 8, x1, colour or LIGHT, 2 if colour else 1)
    legal_extra = iss["legal"][len(iss["name"]):]
    first = [(iss["name"] + ("" if legal_extra else ","), "ISSUER")] + ([legal_extra + ","] if legal_extra else [])
    parts = first + [f" Reg No {iss['reg']}  |  VAT No {iss['vat']}"]
    anchor, x = ("c", (x0 + x1) / 2) if centre else ("l", x0)
    p.text(x, y, parts, f, GREY, anchor=anchor)
    y += lh
    if decoy_here:
        a = decoy_address(p.rng, doc["addr"], p.rng.choice(["head_office", "postal"]))
        doc["decoys"].append(a)
        lines, _ = address_lines(a, p.rng, labelled=False, single=True, upper=False)
        head = "Head office: " if a["kind"] == "head_office" else "Postal address: "
        p.text(x, y, [head] + lines[0] + [f"  |  Tel {iss['tel']}"], f, GREY, anchor=anchor)
        y += lh
    p.text(x1, y, "Page 1 of 1", f, GREY, anchor="r")
    if not centre:
        p.text(x0, y, f"{iss['web']}  |  {iss['email']}", f, GREY)


def remittance(p: Page, doc: dict, y, x0, x1, fs, *, name=True) -> float:
    rng = p.rng
    f, fb = p.f(fs), p.f(fs, True)
    lh = p.lh(f, 1.45)
    p.rule(x0, y, x1, GREY, 1, dash=8)
    p.text(x0, y + 6, "Please detach and return this portion with your payment", p.f(fs * 0.85), GREY)
    y += lh + 10
    p.text(x0, y, "REMITTANCE ADVICE", fb, INK)
    y0 = y + lh
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]), ("Amount due", money(doc.get("total", 0), doc["money_style"])),
            ("Pay by", D(doc, doc["due"]))]
    kv_rows(p, x0, y0, rows, f, fb, val_x=x0 + 210)
    if name:
        p.text(x0 + 560, y0, holder_parts(doc), fb, INK)
    if doc["extra_decoy"]:
        a = decoy_address(rng, doc["addr"], "payment")
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=False)
        p.flow(x0 + 560, y0 + lh * (1.2 if name else 0), x1 - x0 - 560, ["Payments in person:"] + lines[0], f, GREY, lh)
    return y0 + 3 * lh


# --------------------------------------------------------------------------- #
# Layouts. Each draws into p using doc; positions jitter by J().
# --------------------------------------------------------------------------- #


def J(p: Page, n: int = 20) -> int:
    return p.rng.randint(-n, n)


def lay_util_band(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    bh = 170 + J(p, 15)
    p.d.rectangle((0, 0, W, bh), fill=c)
    logo(p, 70 + J(p, 10), 35, bh - 70, doc, colour=WHITE)
    nx = 70 + bh - 40
    p.text(nx, 42 + J(p, 8), [(iss["name"], "ISSUER")], p.f(46, True), WHITE)
    p.text(nx, 108, iss["tagline"], p.f(20), tint(WHITE, 1))
    p.text(W - 70, bh - 58, rng.choice(["TAX INVOICE", "ACCOUNT", "STATEMENT"]), p.f(28, True), WHITE, anchor="r")
    y = bh + 30
    if doc["decoy"] and rng.random() < 0.6:
        decoy_block(p, W - 70, y, doc, "head_office", 16, anchor="r")
        decoy_in_footer = False
    else:
        decoy_in_footer = doc["decoy"]
    # window envelope position
    hx, hy = 100 + J(p), 300 + J(p)
    label = rng.choice([None, None, "Customer", "Account holder"])
    by = holder_block(p, hx, hy, doc, label=label, fs=23)
    # account details box
    bx, byy, bw = 690 + J(p, 10), 470 + J(p, 10), 470
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Bill date", "Invoice date", "Statement date"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    lf, vf = p.f(17), p.f(18, True)
    if doc["period"]:
        rows += period_rows(p, doc, vf, bw - 30 - p.d.textlength("Billing period", font=lf) - 25, "Billing period", " to ")
    rows += rng.sample([("Meter number", digits(rng, 11)), ("Invoice number", f"INV{digits(rng, 8)}"),
                        ("Due date", D(doc, doc["due"])), ("Tariff", rng.choice(["Domestic", "Homepower 2", "Residential"]))], 2)
    lf, vf = p.f(17), p.f(18, True)
    gap = p.lh(vf, 1.7)
    p.d.rectangle((bx, byy, bx + bw, byy + 50 + gap * len(rows)), outline=c, width=2)
    p.d.rectangle((bx, byy, bx + bw, byy + 40), fill=tint(c, 0.15))
    p.text(bx + 15, byy + 9, "Account details", p.f(19, True), c)
    kv_rows(p, bx + 15, byy + 55, rows, lf, vf, right=bx + bw - 15, gap=gap)
    y = max(by, byy + 50 + gap * len(rows)) + 40
    if doc["twice"]:
        y = holder_block(p, 100, y, doc, label="Supply address", fs=18, name=False, single=True) + 20
    rows_, raw = charge_rows(p, doc, rng.randint(3, 9))
    tf, tfb = p.f(18), p.f(18, True)
    y = table(p, 70, y, W - 140, ["Description", "Quantity", "Amount"], rows_, [0.6, 0.2, 0.2], "lrr", tf, tfb,
              head_fill=c, shade=tint(c, 0.08))
    y = totals(p, W - 80, y + 15, doc, raw, tf, tfb, label_x=W - 520, box_colour=tint(c, 0.15))
    fy = H - (90 if decoy_in_footer else 70)
    if y < H - 470 and rng.random() < 0.7:
        small_print(p, 70, y + 25, W - 140, H - 330, doc, 13, rng.randint(2, 3))
        remittance(p, doc, H - 300, 70, W - 70, 17)
    else:
        small_print(p, 70, y + 25, W - 140, fy - 30, doc, 13, rng.randint(2, 4))
    footer(p, doc, fy, 70, W - 70, 13, decoy_here=decoy_in_footer)


def lay_util_sidebar(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    sw = 300 + J(p, 15)
    p.d.rectangle((0, 0, sw, H), fill=c)
    logo(p, 45, 60, 110, doc, colour=WHITE)
    y = p.flow(45, 200, sw - 70, [(iss["name"], "ISSUER")], p.f(34, True), WHITE)
    y = p.flow(45, y + 10, sw - 70, [iss["tagline"]], p.f(16), WHITE)
    y += 60
    p.text(45, y, "Contact us", p.f(18, True), WHITE)
    y += 32
    for t in [f"Tel {iss['tel']}", iss["email"], iss["web"]]:
        sz = 15
        while sz > 10 and p.d.textlength(t, font=p.f(sz)) > sw - 60:
            sz -= 1
        p.text(45, y, t, p.f(sz), WHITE)
        y += 24
    y += 30
    if doc["decoy"]:
        p.text(45, y, rng.choice(["Head office", "Our offices", "Walk-in centre"]), p.f(18, True), WHITE)
        a = decoy_address(rng, doc["addr"], "head_office")
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, upper=False)
        y += 30
        for line in lines:
            y = p.flow(45, y, sw - 70, line, p.f(15), WHITE, 22)
        y += 20
        if doc["extra_decoy"]:
            p.text(45, y, "Postal address", p.f(18, True), WHITE)
            a = decoy_address(rng, doc["addr"], "postal")
            doc["decoys"].append(a)
            lines, _ = address_lines(a, rng, labelled=False, upper=False)
            y += 30
            for line in lines:
                y = p.flow(45, y, sw - 70, line, p.f(15), WHITE, 22)
    y += 30
    p.text(45, y, f"VAT No {iss['vat']}", p.f(14), WHITE)
    p.text(45, y + 22, f"Reg No {iss['reg']}", p.f(14), WHITE)
    mx = sw + 50
    p.text(mx, 70 + J(p, 10), rng.choice(["Electricity account", "Your utility bill", "Water & electricity account"]), p.f(34, True), c)
    p.text(mx, 125, rng.choice(["Tax invoice", "Monthly statement"]), p.f(20), GREY)
    # holder top-right
    label = rng.choice(["Customer", "Customer details", None, "Account holder"])
    hx = W - 70
    holder_block(p, hx, 200 + J(p), doc, label=label, fs=20, anchor="r")
    lf, vf = p.f(17), p.f(18, True)
    rows = [("Customer account", [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Date of issue", "Bill date", "Statement date"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    if doc["period"]:
        rows += [("Reading from", date_parts(doc, doc["period"][0], "PERIOD_FROM")),
                 ("Reading to", date_parts(doc, doc["period"][1], "PERIOD_TO"))]
    rows += [("Meter number", group(digits(rng, 11), [4, 4, 3])), ("Payment due", D(doc, doc["due"]))]
    y = kv_rows(p, mx, 200 + J(p, 10), rows, lf, vf, val_x=mx + 210)
    y = max(y, 480) + 30
    # meter readings mini-table
    prev_r = rng.randint(10000, 90000)
    used = rng.randint(150, 1200)
    tf, tfb = p.f(16), p.f(16, True)
    y = table(p, mx, y, W - 70 - mx, ["Meter", "Previous", "Current", "Units"],
              [[digits(rng, 8), str(prev_r), str(prev_r + used), f"{used} kWh"]], [0.31, 0.23, 0.23, 0.23], "lrrr", tf, tfb,
              head_fill=tint(c, 0.2), head_ink=INK)
    y += 30
    rows_, raw = charge_rows(p, doc, rng.randint(4, 11))
    tf, tfb = p.f(17), p.f(17, True)
    y = table(p, mx, y, W - 70 - mx, ["Charges", "Units", "Amount"], rows_, [0.6, 0.18, 0.22], "lrr", tf, tfb,
              shade=tint(c, 0.07), grid=(225, 225, 228))
    y = totals(p, W - 80, y + 15, doc, raw, tf, tfb, label_x=W - 470)
    small_print(p, mx, y + 30, W - 70 - mx, H - 100, doc, 13, rng.randint(2, 4))
    p.rule(mx, H - 70, W - 70, LIGHT)
    p.text(mx, H - 58, [(iss["name"], "ISSUER"), f"  |  {iss['web']}"], p.f(13), GREY)
    p.text(W - 70, H - 58, "Page 1 of 1", p.f(13), GREY, anchor="r")


def lay_util_minimal(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    x0, x1 = 90 + J(p, 10), W - 90
    up = rng.random() < 0.5
    iname = iss["name"].upper() if up else iss["name"]
    doc["issuer_printed"] = iname
    p.text(x0, 70, [(iname, "ISSUER")], p.f(32, True), INK)
    p.text(x1, 76, rng.choice(["TAX INVOICE", "Tax Invoice"]), p.f(24, True), INK, anchor="r")
    y = 120
    if doc["decoy"]:
        a = decoy_address(rng, doc["addr"], rng.choice(["head_office", "postal"]))
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=up)
        p.text(x0, y, lines[0], p.f(15), GREY)
        y += 22
        p.text(x0, y, f"Tel {iss['tel']}   VAT No {iss['vat']}", p.f(15), GREY)
    p.rule(x0, 175, x1, INK, 1, dash=4)
    hy = 260 + J(p)
    by = holder_block(p, x0 + 10, hy, doc, label=None, fs=21, name_bold=False, upper=up or None)
    lf, vf = p.f(16), p.f(17)
    rows = [("Tax invoice date", date_parts(doc, doc["date"], "DOC_DATE")),
            ("Account no", [(doc["acc"], "ACCOUNT_NO")]), ("Invoice no", digits(rng, 7))]
    if doc["period"]:
        rows += period_rows(p, doc, vf, x1 - 880, "Period", " - ", ("From", "To"))
    rows.append(("Due date", D(doc, doc["due"])))
    y2 = kv_rows(p, 700, hy, rows, lf, vf, val_x=880, colon=True)
    y = max(by, y2) + 30
    if rng.random() < 0.45:
        p.text(x0, y, [f"Dear ", (doc["person"]["salutation"], "HOLDER_NAME"), ","], p.f(18))
        y += 34
        y = p.flow(x0, y, x1 - x0, ["Please find your account for the period below. Thank you for your prompt payment."], p.f(17)) + 16
    p.rule(x0, y, x1, INK, 1, dash=4)
    rows_, raw = charge_rows(p, doc, rng.randint(3, 10))
    tf, tfb = p.f(17), p.f(17, True)
    y = table(p, x0, y + 10, x1 - x0, ["DESCRIPTION", "QTY", "AMOUNT"], rows_, [0.6, 0.18, 0.22], "lrr", tf, tfb)
    p.rule(x0, y + 4, x1, INK, 1, dash=4)
    y = totals(p, x1 - 10, y + 20, doc, raw, tf, tfb, label_x=x1 - 420)
    small_print(p, x0, y + 30, x1 - x0, H - 110, doc, 13, rng.randint(2, 4), issuer_upper=up)
    p.rule(x0, H - 80, x1, INK, 1, dash=4)
    extra = iss["legal"][len(iss["name"]):]
    p.text(x0, H - 68, [(iname, "ISSUER"), (extra.upper() if up else extra) + f"  Reg No {iss['reg']}"], p.f(13), GREY)
    p.text(x1, H - 68, "Page 1/1", p.f(13), GREY, anchor="r")


def lay_bank_classic(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 80, W - 80
    ls = 95
    logo(p, x1 - ls, 60 + J(p, 8), ls, doc)
    p.text(x1 - ls - 20, 70, [(iss["name"], "ISSUER")], p.f(36, True), c, anchor="r")
    p.text(x1 - ls - 20, 118, iss["tagline"], p.f(16), GREY, anchor="r")
    y = 60 + ls + (55 if iss["shape"] == "bars" else 25)
    if doc["decoy"]:
        y = decoy_block(p, x1, y, doc, "branch", 15, heading=rng.choice(["Branch", "Your branch", "Branch details"]),
                        anchor="r", contacts=False)
        p.text(x1, y, f"Branch code {digits(rng, 6)}  |  Tel {iss['tel']}", p.f(15), GREY, anchor="r")
    hy = 270 + J(p)
    by = holder_block(p, x0 + 20, hy, doc, label=None, fs=21)
    y = max(by, y + 30) + 40
    title = rng.choice(["STATEMENT OF ACCOUNT", "Bank Statement", "ACCOUNT STATEMENT"])
    p.text(x0, y, title, p.f(28, True), INK)
    y += 50
    p.rule(x0, y, x1, c, 3)
    y += 15
    lf, vf = p.f(16), p.f(18, True)
    # From/To columns
    cols = [("Account number", [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Statement date", "Date of issue"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    if doc["period"]:
        cols += [("From", date_parts(doc, doc["period"][0], "PERIOD_FROM")), ("To", date_parts(doc, doc["period"][1], "PERIOD_TO"))]
    cols.append(("Statement no", str(rng.randint(1, 240))))

    def width(lab, val):
        vt = val if isinstance(val, str) else "".join(v if isinstance(v, str) else v[0] for v in val)
        return max(p.d.textlength(lab, font=lf), p.d.textlength(vt, font=vf))

    while len(cols) > 2 and sum(width(*c) for c in cols) + 30 * (len(cols) - 1) > x1 - x0:
        cols.pop()
    ws = [width(*c) for c in cols]
    gap = (x1 - x0 - sum(ws)) / max(1, len(cols) - 1)
    cx = x0
    for (lab, val), wv in zip(cols, ws):
        p.text(cx, y, lab, lf, GREY)
        p.text(cx, y + 26, val, vf, INK)
        cx += wv + gap
    y += 70
    p.rule(x0, y, x1, c, 1)
    y += 25
    acc_type = rng.choice(["Cheque account", "Savings account", "Current account", "Transaction account"])
    p.text(x0, y, f"{acc_type}  -  {rng.choice(['Gold', 'Classic', 'Everyday', 'Prestige'])}", p.f(18, True), INK)
    y += 40
    ms = doc["money_style"]
    bal = rng.randint(100000, 3000000)
    tx = transactions(rng, doc, rng.randint(8, 22))
    rows = [["", "Opening balance", "", money(bal, ms)]]
    for d, desc, amt in tx:
        bal += amt
        rows.append([fmt_date(d, "dmy_slash") if ms == 1 else fmt_date(d, "d_mon_y"), desc, money(amt, ms), money(bal, ms)])
    rows.append(["", "Closing balance", "", money(bal, ms)])
    tf, tfb = p.f(16), p.f(16, True)
    y = table(p, x0, y, x1 - x0, ["Date", "Description", "Amount", "Balance"], rows, [0.17, 0.43, 0.2, 0.2], "llrr", tf, tfb,
              shade=tint(c, 0.06), grid=(230, 230, 232))
    y += 30
    small_print(p, x0, y, x1 - x0, H - 120, doc, 13, rng.randint(2, 4))
    footer(p, doc, H - 90, x0, x1, 13, decoy_here=doc["decoy"] and doc["extra_decoy"], colour=c)


def lay_bank_modern(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    bh = 210 + J(p, 15)
    p.d.rectangle((0, 0, W, bh), fill=c)
    logo(p, x0, 50, 80, doc, colour=WHITE)
    p.text(x0 + 100, 62, [(iss["name"], "ISSUER")], p.f(38, True), WHITE)
    p.text(x0, 150, rng.choice(["Your monthly statement", "Account statement", "Statement"]), p.f(24), WHITE)
    dlab = rng.choice(["Statement date", "Issued", "Date"])
    p.text(x1, 70, dlab, p.f(16), WHITE, anchor="r")
    p.text(x1, 94, date_parts(doc, doc["date"], "DOC_DATE"), p.f(22, True), WHITE, anchor="r")
    if doc["period"]:
        p.text(x1, 150, period_parts(doc, "Period: ", " - "), p.f(18), WHITE, anchor="r")
    # boxed holder panel
    py = bh + 40 + J(p, 10)
    pw = 560
    ph = 260
    p.d.rounded_rectangle((x0, py, x0 + pw, py + ph), radius=14, fill=tint(c, 0.07), outline=tint(c, 0.4), width=2)
    label = rng.choice(["Account holder", "Name", None])
    holder_block(p, x0 + 25, py + 22, doc, label=label, fs=20)
    # account panel
    ax = x0 + pw + 30
    p.d.rounded_rectangle((ax, py, x1, py + ph), radius=14, outline=tint(c, 0.4), width=2)
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]), ("Account type", rng.choice(["Everyday", "Savings", "Cheque"])),
            ("Branch code", digits(rng, 6)), ("Customer ref", digits(rng, 9))]
    kv_rows(p, ax + 20, py + 25, rows, p.f(16), p.f(17, True), right=x1 - 20, gap=52)
    y = py + ph + 35
    ms = doc["money_style"]
    open_b = rng.randint(50000, 2500000)
    tx = transactions(rng, doc, rng.randint(6, 17))
    mi = sum(a for _, _, a in tx if a > 0)
    mo = sum(a for _, _, a in tx if a < 0)
    cards = [("Opening balance", open_b), ("Money in", mi), ("Money out", mo), ("Closing balance", open_b + mi + mo)]
    cw = (x1 - x0 - 3 * 20) / 4
    for k, (lab, v) in enumerate(cards):
        cx = x0 + k * (cw + 20)
        p.d.rounded_rectangle((cx, y, cx + cw, y + 90), radius=10, fill=tint(c, 0.12))
        p.text(cx + 15, y + 14, lab, p.f(15), GREY)
        p.text(cx + 15, y + 44, money(v, ms), p.f(22, True), INK)
    y += 125
    rows = []
    bal = open_b
    for d, desc, amt in tx:
        bal += amt
        rows.append([fmt_date(d, "d_mon_y"), desc, money(amt, ms), money(bal, ms)])
    tf, tfb = p.f(16), p.f(16, True)
    y = table(p, x0, y, x1 - x0, ["Date", "Transaction", "Amount", "Balance"], rows, [0.16, 0.44, 0.2, 0.2], "llrr", tf, tfb,
              head_fill=c, shade=tint(c, 0.06))
    y += 30
    small_print(p, x0, y, x1 - x0, H - 130, doc, 12, rng.randint(2, 4))
    footer(p, doc, H - 95, x0, x1, 13, decoy_here=doc["decoy"], centre=rng.random() < 0.5)


def lay_muni_rates(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 80, W - 80
    # crest
    cx = W // 2
    p.d.ellipse((cx - 55, 40, cx + 55, 150), fill=tint(c, 0.15), outline=c, width=4)
    p.d.polygon([(cx - 30, 70), (cx + 30, 70), (cx + 30, 105), (cx, 130), (cx - 30, 105)], fill=c)
    p.d.text((cx, 95), doc["issuer"]["initials"], font=p.f(22, True), fill=WHITE, anchor="mm")
    p.text(cx, 165, [(iss["name"], "ISSUER")], p.f(34, True), c, anchor="c")
    y = 215
    if doc["decoy"]:
        a = decoy_address(rng, doc["addr"], rng.choice(["head_office", "postal"]))
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=False)
        p.text(cx, y, ["Civic Centre, " if a["kind"] == "head_office" else ""] + lines[0], p.f(15), GREY, anchor="c")
        y += 24
        p.text(cx, y, f"Tel {iss['tel']}  |  {iss['email']}  |  VAT No {iss['vat']}", p.f(15), GREY, anchor="c")
        y += 24
    y += 20
    p.d.rectangle((x0, y, x1, y + 44), fill=c)
    p.text(x0 + 15, y + 10, rng.choice(["MUNICIPAL ACCOUNT / TAX INVOICE", "RATES AND SERVICES ACCOUNT", "CONSOLIDATED ACCOUNT"]),
           p.f(20, True), WHITE)
    y += 60
    # two-column "Account details" grid
    lf, vf = p.f(16), p.f(18)
    lab_w = 230
    gx = x0 + 10
    rh = p.lh(vf, 1.45)
    top = y
    p.text(gx, y, "Account holder", lf, GREY)
    p.text(gx + lab_w, y, holder_parts(doc), p.f(18, True), INK)
    y += rh + 4
    p.text(gx, y, "Postal address", lf, GREY)
    lines, pr = address_lines(doc["addr"], rng, labelled=True)
    doc["province_printed"] |= pr
    for line in lines:
        p.text(gx + lab_w, y, line, vf, INK)
        y += rh
    y += 4
    if doc["twice"]:
        p.text(gx, y, rng.choice(["Property address", "Supply address", "Service address"]), lf, GREY)
        lines, pr = address_lines(doc["addr"], rng, labelled=True, single=True, upper=False, province="omit")
        p.flow(gx + lab_w, y, 330, lines[0], vf, INK, rh)
        y += rh * (1 + int(p.d.textlength("".join(t if isinstance(t, str) else t[0] for t in lines[0]), font=vf) > 330)) + 4
    left_end = y
    rx = x0 + 650
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Date of issue", "Account date", "Statement date"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    if doc["period"]:
        rows += [("Billing period", period_parts(doc, sep=" - "))]
    rows += [("Erf / Stand no", f"{rng.randint(100, 9999)}"), ("Municipal valuation", money(rng.randint(30000000, 400000000), 0)),
             ("Due date", D(doc, doc["due"]))]
    if doc["period"]:
        y2 = top
        for lab, val in rows:
            p.text(rx, y2, lab, lf, GREY)
            if lab == "Billing period":
                p.text(rx + 200, y2, [val[0]], p.f(17), INK)
                y2 += rh - 6
                p.text(rx + 200, y2, ["to ", val[2]], p.f(17), INK)
            else:
                p.text(rx + 200, y2, val if isinstance(val, list) else [val], p.f(17), INK)
            y2 += rh
    else:
        y2 = kv_rows(p, rx, top, rows, lf, p.f(17), val_x=rx + 200, gap=rh)
    y = max(left_end, y2) + 10
    p.d.rectangle((x0, top - 14, x1, y), outline=tint(c, 0.5), width=2)
    p.d.line((rx - 20, top - 14, rx - 20, y), fill=tint(c, 0.5), width=2)
    y += 35
    rows_, raw = charge_rows(p, doc, rng.randint(4, 10))
    tf, tfb = p.f(17), p.f(17, True)
    y = table(p, x0, y, x1 - x0, ["Service", "Basis", "Amount"], rows_, [0.58, 0.2, 0.22], "lrr", tf, tfb,
              head_fill=tint(c, 0.25), head_ink=INK, grid=(220, 220, 225))
    y = totals(p, x1 - 10, y + 15, doc, raw, tf, tfb, label_x=x1 - 430)
    if y < H - 460 and rng.random() < 0.6:
        small_print(p, x0, y + 25, x1 - x0, H - 320, doc, 13, rng.randint(1, 3))
        remittance(p, doc, H - 290, x0, x1, 16)
    else:
        small_print(p, x0, y + 25, x1 - x0, H - 110, doc, 13, rng.randint(2, 4))
    footer(p, doc, H - 80, x0, x1, 13, decoy_here=False, centre=True)


def lay_muni_grid(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 60, W - 60
    logo(p, x0, 50, 90, doc)
    p.text(x0 + 110, 55, [(iss["name"].upper(), "ISSUER")], p.f(30, True), INK)
    doc["issuer_printed"] = iss["name"].upper()
    p.text(x0 + 110, 100, iss["tagline"], p.f(17), GREY)
    if doc["decoy"]:
        a = decoy_address(rng, doc["addr"], "postal")
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=True)
        p.text(x0 + 110, 126, lines[0], p.f(15), GREY)
    y = 175
    lf, vf, vb = p.f(13, True), p.f(18), p.f(18, True)
    cell = lambda x, yy, w, h: p.d.rectangle((x, yy, x + w, yy + h), outline=INK, width=1)  # noqa: E731
    gw = x1 - x0
    # row 1: four small cells
    labels = [("ACCOUNT NUMBER", [(doc["acc"], "ACCOUNT_NO")]),
              (rng.choice(["DATE OF ISSUE", "ACCOUNT DATE"]), date_parts(doc, doc["date"], "DOC_DATE")),
              ("DUE DATE", D(doc, doc["due"])), ("ERF NUMBER", str(rng.randint(100, 20000)))]
    cw = gw / 4
    for k, (lab, val) in enumerate(labels):
        cell(x0 + k * cw, y, cw, 70)
        p.d.rectangle((x0 + k * cw + 1, y + 1, x0 + (k + 1) * cw - 1, y + 22), fill=tint(c, 0.15))
        p.text(x0 + k * cw + 8, y + 5, lab, lf, INK)
        p.text(x0 + k * cw + 8, y + 32, val, vb, INK)
    y += 70
    # row 2: holder cell (big) + period/valuation cells
    hh = 250
    cell(x0, y, gw * 0.55, hh)
    p.d.rectangle((x0 + 1, y + 1, x0 + gw * 0.55 - 1, y + 22), fill=tint(c, 0.15))
    p.text(x0 + 8, y + 5, rng.choice(["NAME AND POSTAL ADDRESS", "ACCOUNT HOLDER", "OWNER / OCCUPIER"]), lf, INK)
    holder_block(p, x0 + 15, y + 36, doc, label=None, fs=18, line_h=28)
    rx, rw = x0 + gw * 0.55, gw * 0.45
    sub = [("BILLING PERIOD", period_parts(doc, sep=" - ") if doc["period"] else "Monthly"),
           ("MUNICIPAL VALUATION", money(rng.randint(30000000, 400000000), 0)),
           ("DEPOSIT HELD", money(rng.randint(50000, 300000), 0))]
    sh = hh / 3
    for k, (lab, val) in enumerate(sub):
        cell(rx, y + k * sh, rw, sh)
        p.d.rectangle((rx + 1, y + k * sh + 1, rx + rw - 1, y + k * sh + 22), fill=tint(c, 0.15))
        p.text(rx + 8, y + k * sh + 5, lab, lf, INK)
        p.text(rx + 8, y + k * sh + 36, val, p.f(17), INK)
    y += hh
    if doc["twice"]:
        cell(x0, y, gw, 64)
        p.d.rectangle((x0 + 1, y + 1, x1 - 1, y + 22), fill=tint(c, 0.15))
        p.text(x0 + 8, y + 5, "PROPERTY / SUPPLY ADDRESS", lf, INK)
        lines, pr = address_lines(doc["addr"], rng, labelled=True, single=True, upper=True)
        doc["province_printed"] |= pr
        p.text(x0 + 10, y + 32, lines[0], p.f(17), INK)
        y += 64
    y += 30
    rows_, raw = charge_rows(p, doc, rng.randint(5, 10))
    tf, tfb = p.f(16), p.f(16, True)
    rows_ = [[r[0].upper(), r[1], r[2]] for r in rows_]
    y = table(p, x0, y, gw, ["DESCRIPTION", "UNITS", "AMOUNT"], rows_, [0.6, 0.18, 0.22], "lrr", tf, tfb,
              head_fill=INK, grid=(200, 200, 200))
    ty = y
    y = totals(p, x1 - 10, ty + 15, doc, raw, tf, tfb, label_x=x1 - 420, box_colour=tint(c, 0.15))
    if doc["decoy"] and doc["extra_decoy"]:
        y = max(y, decoy_block(p, x0, ty + 15, doc, "payment", 14, heading="PAY AT:", contacts=False) + 10)
    small_print(p, x0, y + 30, gw, H - 100, doc, 12, rng.randint(2, 4), issuer_upper=True)
    p.rule(x0, H - 70, x1, INK)
    p.text(x0, H - 60, [(iss["name"].upper(), "ISSUER"), f"   VAT REG {iss['vat']}"], p.f(13), GREY)
    p.text(x1, H - 60, "PAGE 1 OF 1", p.f(13), GREY, anchor="r")


def lay_cell_invoice(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    bh = 130 + J(p, 10)
    p.d.rectangle((0, 0, W, bh), fill=c)
    p.d.polygon([(W * 0.62, 0), (W, 0), (W, bh), (W * 0.55, bh)], fill=tint(c, 0.75))
    logo(p, x0, 25, bh - 50, doc, colour=WHITE)
    p.text(x0 + bh - 30, 38, [(iss["name"], "ISSUER")], p.f(40, True), WHITE)
    p.text(x1, 48, rng.choice(["TAX INVOICE", "Tax invoice"]), p.f(30, True), WHITE, anchor="r")
    y = bh + 30
    # customer top-right
    label = rng.choice(["Customer", "Bill to", "Account holder"])
    by = holder_block(p, 700, y + 10 + J(p, 10), doc, label=label, fs=19)
    lf, vf = p.f(16), p.f(17, True)
    dl = rng.choice(["Invoice date", "Tax invoice date", "Bill date"])
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]), (dl, date_parts(doc, doc["date"], "DOC_DATE")),
            ("Invoice number", f"{rng.choice(['INV', 'TI', ''])}{digits(rng, 9)}"), ("Cellphone number", phone(rng, True))]
    y2 = kv_rows(p, x0, y + 10, rows, lf, vf, val_x=x0 + 200)
    if doc["decoy"]:
        y2 = decoy_block(p, x0, y2 + 15, doc, rng.choice(["head_office", "postal"]), 14,
                         heading=rng.choice(["Registered office", "Head office", "Correspondence"]), contacts=True)
    y = max(by, y2) + 30
    if doc["period"]:
        # From / To columns
        p.d.rectangle((x0, y, x1, y + 70), fill=tint(c, 0.1))
        cols = [("Billing period", None), ("From", "PERIOD_FROM"), ("To", "PERIOD_TO"), ("Payment due", None)]
        cw = (x1 - x0) / 4
        vals = [rng.choice(["Monthly", "30 days", "Post-paid"]), D(doc, doc["period"][0]), D(doc, doc["period"][1]), D(doc, doc["due"])]
        for k, ((lab, slab), v) in enumerate(zip(cols, vals)):
            p.text(x0 + 15 + k * cw, y + 10, lab, p.f(15), GREY)
            p.text(x0 + 15 + k * cw, y + 34, [(v, slab)] if slab else v, p.f(18, True), INK)
        y += 100
    p.text(x0, y, rng.choice(["Summary of charges", "Your charges this month", "Account summary"]), p.f(22, True), c)
    y += 40
    rows_, raw = charge_rows(p, doc, rng.randint(3, 9))
    tf, tfb = p.f(17), p.f(17, True)
    y = table(p, x0, y, x1 - x0, ["Item", "Usage", "Amount (incl. VAT)" if rng.random() < 0.3 else "Amount"], rows_,
              [0.58, 0.2, 0.22], "lrr", tf, tfb, shade=tint(c, 0.07), grid=(225, 225, 228))
    y = totals(p, x1 - 10, y + 15, doc, raw, tf, tfb, label_x=x1 - 430)
    small_print(p, x0, y + 30, x1 - x0, H - 110, doc, 13, rng.randint(2, 4))
    footer(p, doc, H - 80, x0, x1, 13, decoy_here=False)


def lay_lease_letter(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 110, W - 110
    cx = W // 2
    logo(p, cx - 40, 50, 80, doc)
    p.text(cx, 145, [(iss["name"], "ISSUER")], p.f(32, True), c, anchor="c")
    y = 190
    if doc["decoy"]:
        a = decoy_address(rng, doc["addr"], "head_office")
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=False)
        p.text(cx, y, lines[0], p.f(15), GREY, anchor="c")
        y += 24
    p.text(cx, y, f"Tel {iss['tel']}  |  {iss['email']}  |  {iss['web']}", p.f(15), GREY, anchor="c")
    y += 30
    p.rule(x0, y, x1, c, 2)
    y += 50 + J(p, 10)
    f, fb = p.f(19), p.f(19, True)
    lh = p.lh(f, 1.45)
    show_block = rng.random() < 0.6
    p.text(x1, y, f"Our ref: {rng.choice(['LA', 'RL', 'LS'])}/{digits(rng, 5)}", f, GREY, anchor="r")
    if show_block:
        y = holder_block(p, x0, y, doc, label=None, fs=19, name_bold=False) + lh
    else:
        y += lh * 2
    p.text(x0, y, ["Dear ", (doc["person"]["salutation"], "HOLDER_NAME"), ","], f)
    y += lh * 1.6
    p.text(x0, y, rng.choice(["RE: CONFIRMATION OF RESIDENTIAL LEASE", "CONFIRMATION OF TENANCY", "LEASE CONFIRMATION LETTER"]), fb)
    y += lh * 1.5
    lines, pr = address_lines(doc["addr"], rng, labelled=True, single=True, upper=False)
    doc["province_printed"] |= pr
    start = D(doc, doc["date"] + dt.timedelta(days=rng.randint(5, 30)))
    sent = (["This letter confirms that a residential lease agreement was entered into between", (iss["name"], "ISSUER"),
             "as managing agent for the landlord, and", (doc["person"]["printed"], "HOLDER_NAME"),
             rng.choice(["residing at", "(the Tenant), residing at", "of"])] + lines[0] +
            [f". The lease commences on {start} for a period of {rng.choice([6, 12, 12, 24])} months, under lease reference",
             (doc["acc"], "ACCOUNT_NO"), "."])
    # punctuation directly after a labelled part: merge into the part
    merged = []
    for part in sent:
        if isinstance(part, str) and part.startswith((".", ",")) and merged and not isinstance(merged[-1], str):
            merged[-1] = (merged[-1][0] + part[0], merged[-1][1])
            part = part[1:].strip()
            if not part:
                continue
        merged.append(part)
    y = p.flow(x0, y, x1 - x0, merged, f, INK, lh) + lh * 0.6
    y = p.flow(x0, y, x1 - x0, [rng.choice([
        "The tenant has paid the deposit in full and the account is in good standing. Rental is payable monthly in advance on or before the first day of each month.",
        "Rental is payable monthly in advance. The deposit is held in an interest-bearing trust account as required by the Rental Housing Act.",
    ])], f, INK, lh) + lh * 0.8
    rows_, raw = charge_rows(p, doc, rng.randint(3, 5), with_prev=False)
    tf, tfb = p.f(17), p.f(17, True)
    y = table(p, x0, y, x1 - x0, ["Item", "Frequency", "Amount"], rows_, [0.56, 0.2, 0.24], "lrr", tf, tfb,
              head_fill=tint(c, 0.2), head_ink=INK, grid=(220, 220, 225))
    y += lh
    p.text(x0, y, ["Signed on ", (D(doc, doc["date"]), "DOC_DATE"), f" at {rng.choice([pl[1] for pl in PLACES if pl[1] != doc['addr']['city']])}"], f)
    y += lh * 2.5
    p.rule(x0, y, x0 + 380, INK)
    p.rule(x1 - 380, y, x1, INK)
    agent = other_person(rng, doc)
    p.text(x0, y + 8, f"{agent['first']} {agent['surname']}, Rental Consultant", p.f(16), GREY)
    p.text(x1 - 380, y + 8, "Tenant", p.f(16), GREY)
    y += 60
    small_print(p, x0, y, x1 - x0, H - 110, doc, 12, rng.randint(1, 2))
    footer(p, doc, H - 80, x0, x1, 13, decoy_here=False, centre=True)


def lay_insure_stmt(p: Page, doc: dict) -> None:
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 80, W - 80
    p.d.rectangle((0, 0, 24, H), fill=c)
    logo(p, x0, 60, 75, doc)
    p.text(x0 + 95, 64, [(iss["name"], "ISSUER")], p.f(36, True), INK)
    p.text(x0 + 95, 112, iss["tagline"], p.f(17), c)
    y = 190
    p.text(x0, y, rng.choice(["POLICY SCHEDULE", "Premium statement", "Annual policy statement"]), p.f(30, True), c)
    y += 60
    lf, vf = p.f(16), p.f(18, True)
    rows = [("Policy number", [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Date of issue", "Statement date", "Schedule date"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    if doc["period"]:
        rows += period_rows(p, doc, vf, 690 - 30 - (x0 + 200), "Period of cover", " to ", ("Cover from", "Cover to"))
    rows += [("Payment method", rng.choice(["Debit order", "EFT", "Stop order"])), ("Debit day", str(rng.choice([1, 15, 20, 25, 28])))]
    broker = other_person(rng, doc)
    rows.append(("Broker", f"{broker['first']} {broker['surname']}"))
    y2 = kv_rows(p, x0, y, rows, lf, vf, val_x=x0 + 200)
    # boxed panel right
    px, pw = 690 + J(p, 10), 470
    lab = rng.choice(["Policyholder", "Insured", "Policy holder details"])
    p.d.rectangle((px, y - 10, px + pw, y + 28), fill=c)
    p.text(px + 15, y - 2, lab, p.f(18, True), WHITE)
    hb = holder_block(p, px + 15, y + 45, doc, label=None, fs=18, line_h=28)
    ph = hb + 15 - (y - 10)
    p.d.rectangle((px, y - 10, px + pw, y - 10 + ph), outline=c, width=2)
    y = max(y2, y - 10 + ph) + 30
    if doc["twice"]:
        p.text(x0, y, "Risk address:", lf, GREY)
        lines, pr = address_lines(doc["addr"], rng, labelled=True, single=True, upper=False)
        doc["province_printed"] |= pr
        p.text(x0 + 140, y - 1, lines[0], p.f(17), INK)
        y += 45
    if doc["decoy"]:
        y = decoy_block(p, x0, y, doc, "branch", 14, heading=f"Broker office: {broker['surname']} & Associates", contacts=False) + 25
    rows_, raw = charge_rows(p, doc, rng.randint(3, 8), with_prev=False)
    tf, tfb = p.f(17), p.f(17, True)
    rows2 = [[d, "" if d in ("Policy fee", "Roadside assist") else money(rng.randint(500000, 300000000), 0), a] for d, _, a in rows_]
    y = table(p, x0, y, x1 - x0, ["Section", "Sum insured", "Monthly premium"], rows2, [0.46, 0.27, 0.27], "lrr", tf, tfb,
              head_fill=c, shade=tint(c, 0.07))
    y = totals(p, x1 - 10, y + 15, doc, raw, tf, tfb, label_x=x1 - 430, due_label="Next collection")
    small_print(p, x0, y + 30, x1 - x0, H - 120, doc, 13, rng.randint(2, 4))
    footer(p, doc, H - 90, x0, x1, 13, decoy_here=doc["decoy"] and doc["extra_decoy"], colour=c)


def lay_util_slip(p: Page, doc: dict) -> None:
    """A5 landscape: a folded half-sheet account slip."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 60, W - 60
    p.d.rectangle((0, 0, W, 90), fill=c)
    logo(p, x0, 15, 60, doc, colour=WHITE)
    p.text(x0 + 75, 25, [(iss["name"], "ISSUER")], p.f(32, True), WHITE)
    p.text(x1, 34, rng.choice(["ACCOUNT", "STATEMENT", "TAX INVOICE"]), p.f(22, True), WHITE, anchor="r")
    y = 125
    by = holder_block(p, x0 + 10, y + J(p, 10), doc, label=rng.choice([None, "Customer"]), fs=19, line_h=27)
    lf, vf = p.f(15), p.f(16, True)
    rows = [("Account", [(doc["acc"], "ACCOUNT_NO")]), (rng.choice(["Bill date", "Date"]), date_parts(doc, doc["date"], "DOC_DATE"))]
    if doc["period"]:
        rows += period_rows(p, doc, vf, x1 - 760, "Period", " - ", ("From", "To"))
    rows.append(("Due", D(doc, doc["due"])))
    y2 = kv_rows(p, 650, y, rows, lf, vf, val_x=760)
    y = max(by, y2) + 15
    rows_, raw = charge_rows(p, doc, rng.randint(3, 5), with_prev=False)
    tf, tfb = p.f(15), p.f(15, True)
    y = table(p, x0, y, x1 - x0, ["Description", "Qty", "Amount"], rows_, [0.6, 0.18, 0.22], "lrr", tf, tfb,
              row_h=27, head_fill=tint(c, 0.25), head_ink=INK)
    y = totals(p, x1 - 10, y + 8, doc, raw, tf, tfb, label_x=x1 - 400, show_due=False)
    small_print(p, x0, y + 10, x1 - x0 - 450, H - 60, doc, 11, 1)
    p.d.line((0, H - 3, W, H - 3), fill=(220, 220, 220), width=3)  # the fold
    footer_parts = [(iss["name"], "ISSUER"), f"  |  Tel {iss['tel']}"]
    if doc["decoy"]:
        a = decoy_address(rng, doc["addr"], "postal")
        doc["decoys"].append(a)
        lines, _ = address_lines(a, rng, labelled=False, single=True, upper=False)
        footer_parts += ["  |  "] + lines[0]
    p.text(x0, H - 40, footer_parts, p.f(12), GREY)


LAYOUTS = ["util_band", "util_sidebar", "util_minimal", "bank_classic", "bank_modern", "muni_rates", "muni_grid",
           "cell_invoice", "lease_letter", "insure_stmt", "util_slip"]
LAYOUT_FN = {name: globals()["lay_" + name] for name in LAYOUTS}
LAYOUT_TYPES = {
    "util_band": "utility_bill", "util_sidebar": "utility_bill", "util_minimal": "utility_bill",
    "bank_classic": "bank_statement", "bank_modern": "bank_statement", "muni_rates": "municipal_account",
    "muni_grid": "municipal_account", "cell_invoice": "cellphone_account", "lease_letter": "lease_agreement",
    "insure_stmt": "insurance_statement", "util_slip": "utility_bill",
}
LAYOUT_FONTS = {
    "util_band": ["dejavu_sans", "lib_sans"], "util_sidebar": ["lib_sans", "dejavu_sans"],
    "util_minimal": ["dejavu_mono", "lib_mono"], "bank_classic": ["dejavu_serif", "lib_serif"],
    "bank_modern": ["lib_sans", "dejavu_sans"], "muni_rates": ["lib_serif", "dejavu_serif", "lib_sans"],
    "muni_grid": ["lib_sans", "dejavu_sans", "lib_mono"], "cell_invoice": ["dejavu_sans", "lib_sans"],
    "lease_letter": ["lib_serif", "dejavu_serif"], "insure_stmt": ["lib_sans", "dejavu_serif"],
    "util_slip": ["dejavu_sans", "lib_sans", "dejavu_mono"],
}
LAYOUT_DATE_STYLES = {
    "util_band": ["d_mon_y", "iso", "dmy_slash"], "util_sidebar": ["d_month_y", "d_mon_y"],
    "util_minimal": ["iso", "ymd_slash", "dmy_dot"], "bank_classic": ["d_month_y", "d_mon_y"],
    "bank_modern": ["d_mon_y", "month_d_y"], "muni_rates": ["dmy_slash", "ymd_slash", "iso"],
    "muni_grid": ["ymd_slash", "dmy_slash", "iso"], "cell_invoice": ["d_mon_y", "d_month_y", "dmy_slash"],
    "lease_letter": ["d_month_y", "month_d_y"], "insure_stmt": ["d_month_y", "dmy_dot", "iso"],
    "util_slip": ["dmy_slash", "d_mon_y"],
}
PERIOD_P = {"util_band": 0.85, "util_sidebar": 0.8, "util_minimal": 0.6, "bank_classic": 0.95, "bank_modern": 0.9,
            "muni_rates": 0.7, "muni_grid": 0.75, "cell_invoice": 0.85, "lease_letter": 0.0, "insure_stmt": 0.5,
            "util_slip": 0.6}
SIZES = {"util_slip": (1240, 877)}

# --------------------------------------------------------------------------- #
# Procedural layouts (--procedural): pages composed from independently placed,
# styled and labelled blocks, so a tagger cannot learn where a layout puts a field.
# --------------------------------------------------------------------------- #

PROC_M = 40  # page margin
PROC_TOP_LIMIT = 1010  # the holder, details and boxes end above this; the body gets the rest
PROC_TYPES = {"utility_bill": 26, "bank_statement": 18, "municipal_account": 16, "cellphone_account": 14,
              "insurance_statement": 14, "lease_agreement": 8}
PROC_TITLES = {
    "utility_bill": ["TAX INVOICE", "Tax invoice", "Electricity account", "Statement of account", "ACCOUNT",
                     "Water & electricity account"],
    "bank_statement": ["Bank statement", "ACCOUNT STATEMENT", "Statement of account", "Monthly statement"],
    "municipal_account": ["MUNICIPAL ACCOUNT", "Rates and services account", "Consolidated account", "TAX INVOICE"],
    "cellphone_account": ["TAX INVOICE", "Monthly bill", "Account statement", "Your bill"],
    "insurance_statement": ["Premium statement", "POLICY SCHEDULE", "Policy statement", "Statement of cover"],
    "lease_agreement": ["Rental statement", "TENANT STATEMENT", "Statement of account", "Rent invoice"],
}
PROC_HOLDER_LABELS = ["Account holder", "Customer", "Deliver to", "Addressee", "Name and address", "Client", "Member"]
PROC_GRID_LABELS = [("Name", "Address"), ("Account holder", "Postal address"), ("Customer", "Address"),
                    ("Client name", "Physical address"), ("Member", "Residential address"), ("Name", "Postal address")]
PROC_ACC_LABELS = {
    "default": ["Account number", "Account no", "Acc no", "Account #", "Customer number", "Account", "Account no.",
                "Customer account", "Account reference"],
    "bank_statement": ["Account number", "Account no", "Acc no", "Account #", "Account", "Account no."],
    "insurance_statement": ["Policy number", "Policy no", "Policy #", "Policy", "Contract number"],
    "lease_agreement": ["Lease reference", "Tenant ref", "Lease no", "Tenant account", "Account number"],
}
PROC_DATE_LABELS = ["Statement date", "Date issued", "Invoice date", "Issue date", "Bill date", "Date", "Tax invoice date",
                    "Date of issue", "Account date", "Document date", "Issued"]
PROC_PERIOD_LABELS = ["Statement period", "Billing period", "Period", "For the period", "Service period"]
PROC_FROM_TO = [("From", "To"), ("Period from", "Period to"), ("Start date", "End date"), ("Opening date", "Closing date")]
PROC_DUE_LABELS = ["Due date", "Payment due", "Pay by", "Due by", "Payment due date"]


class ProcReroll(Exception):
    """A procedural page that could not be composed; render_one tries the next attempt."""


def text_w(p: Page, parts, font) -> float:
    parts = [parts] if isinstance(parts, str) else parts
    return p.d.textlength("".join(t if isinstance(t, str) else t[0] for t in parts), font=font)


def font_h(font) -> int:
    a, d = font.getmetrics()
    return a + d


def fit_font(p: Page, text: str, size: float, maxw: float, bold=True, fam=None, floor: float = 14):
    """The largest font <= size whose rendering of text is at most maxw wide."""
    while size > floor and text_w(p, text, p.f(size, bold, fam)) > maxw:
        size -= 1
    return p.f(size, bold, fam)


def with_end(parts: list, ch: str) -> list:
    """parts with ch appended to the last part (a labelled part keeps its label, as the spans allow)."""
    last = parts[-1]
    return parts[:-1] + [last + ch if isinstance(last, str) else (last[0] + ch, last[1])]


class Block:
    """A display list in block coordinates: built and measured first, then placed, then drawn."""

    def __init__(self, p: Page):
        self.p, self.items, self.w, self.h = p, [], 0.0, 0.0

    def _grow(self, x1, y1):
        self.w, self.h = max(self.w, x1), max(self.h, y1)

    def text(self, x, y, parts, font, fill=INK, anchor="l") -> float:
        parts = [parts] if isinstance(parts, str) else parts
        w = text_w(self.p, parts, font)
        x0 = x - w if anchor == "r" else x - w / 2 if anchor == "c" else x
        assert x0 > -1.5, (x0, parts)
        self.items.append(["text", x, y, parts, font, fill, anchor])
        self._grow(x0 + w, y + font_h(font))
        return w

    def flow(self, x, y, width, parts, font, fill=INK, lh=None) -> float:
        lh = lh or self.p.lh(font)
        lines = self.p.flow_lines(width, parts, font)
        mw = max(text_w(self.p, " ".join(t for t, _, _ in ln), font) for ln in lines)
        self.items.append(["flow", x, y, width, parts, font, fill, lh])
        self._grow(x + mw, y + (len(lines) - 1) * lh + font_h(font))
        return y + len(lines) * lh

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1, radius=0):
        self.items.append(["rect", x0, y0, x1, y1, fill, outline, width, radius])
        self._grow(x1, y1)

    def logo(self, x, y, s, doc, colour=None, ink=WHITE):
        self.items.append(["logo", x, y, s, doc, colour, ink])
        self._grow(x + s, y + s * (1.45 if doc["issuer"]["shape"] == "bars" else 1))

    def embed(self, other: "Block", dx, dy):
        for it in other.items:
            it = list(it)
            it[1] += dx
            it[2] += dy
            if it[0] == "rect":
                it[3] += dx
                it[4] += dy
            self.items.append(it)
        self._grow(other.w + dx, other.h + dy)

    def draw(self, x, y):
        p = self.p
        for it in self.items:
            k = it[0]
            if k == "text":
                p.text(x + it[1], y + it[2], it[3], it[4], it[5], anchor=it[6])
            elif k == "flow":
                p.flow(x + it[1], y + it[2], it[3], it[4], it[5], it[6], it[7])
            elif k == "rect":
                box = (x + it[1], y + it[2], x + it[3], y + it[4])
                if it[8]:
                    p.d.rounded_rectangle(box, radius=it[8], fill=it[5], outline=it[6], width=it[7])
                else:
                    p.d.rectangle(box, fill=it[5], outline=it[6], width=it[7])
            else:
                logo(p, x + it[1], y + it[2], it[3], it[4], colour=it[5], ink=it[6])


def boxed(p: Page, inner: Block, *, pad, outline=None, fill=None, width=2, radius=0) -> Block:
    b = Block(p)
    b.rect(0, 0, inner.w + 2 * pad, inner.h + 2 * pad, fill=fill, outline=outline, width=width, radius=radius)
    b.embed(inner, pad, pad)
    return b


class Board:
    """Occupied rectangles of one page; a block goes where it touches none of them."""

    def __init__(self, W, H, x0, x1):
        self.W, self.H, self.x0, self.x1 = W, H, x0, x1
        self.rects: list[tuple[float, float, float, float]] = []

    def add(self, x0, y0, x1, y1):
        self.rects.append((x0, y0, x1, y1))

    def free(self, x, y, w, h, gap, y_max) -> bool:
        if x < self.x0 - 0.5 or x + w > self.x1 + 0.5 or y < PROC_M or y + h > y_max:
            return False
        return not any(x < c + gap and a < x + w + gap and y < d + gap and b < y + h + gap for a, b, c, d in self.rects)

    def place(self, blk: Block, cands: list, *, y_max=PROC_TOP_LIMIT, gap=26, push=320):
        """Try each (slot, x, y) candidate, pushing down in 6 px steps; draw at the first free spot."""
        for slot, x, y in cands:
            x = min(max(x, self.x0), self.x1 - blk.w)
            for dy in range(0, push, 6):
                if self.free(x, y + dy, blk.w, blk.h, gap, y_max):
                    blk.draw(x, y + dy)
                    self.add(x, y + dy, x + blk.w, y + dy + blk.h)
                    return slot, x, y + dy
        return None

    def bottom(self, x0=-1e9, x1=1e9) -> float:
        return max([r[3] for r in self.rects if r[0] < x1 and x0 < r[2]] or [PROC_M])


# ---- header ---------------------------------------------------------------- #


def proc_header(p: Page, doc: dict, kind: str, decoy_side: bool) -> tuple[str, Board, float, str | None]:
    """Draw the header; returns (tag, board, y below the header, sidebar side or None)."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c, t = iss["colour"], doc["type"]
    iname = doc.get("issuer_printed", iss["name"])
    title = rng.choice(PROC_TITLES[t])
    title = title.upper() if rng.random() < 0.2 else title
    has_logo = rng.random() < 0.65
    if kind == "side":
        sw = int(W * rng.uniform(0.20, 0.28))
        side = rng.choice("lr")
        sx = 0 if side == "l" else W - sw
        p.d.rectangle((sx, 0, sx + sw, H), fill=c)
        pad = rng.randint(28, 40)
        ix, inner = sx + pad, sw - 2 * pad
        y = rng.randint(45, 80)
        if has_logo:
            s = rng.randint(70, 105)
            logo(p, ix, y, s, doc, colour=WHITE)
            y += s * (1.45 if iss["shape"] == "bars" else 1) + 25
        fs = rng.uniform(22, 40)
        while fs > 16 and max(text_w(p, w_, p.f(fs, True)) for w_ in iname.split()) > inner:
            fs -= 1
        y = p.flow(ix, y, inner, [(iname, "ISSUER")], p.f(fs, True), WHITE)
        if rng.random() < 0.6:
            y = p.flow(ix, y + 6, inner, [iss["tagline"]], p.f(15), WHITE)
        y += rng.randint(40, 70)
        p.text(ix, y, rng.choice(["Contact us", "Get in touch", "Enquiries", "Customer care"]), p.f(18, True), WHITE)
        y += 32
        for tx in rng.sample([f"Tel {iss['tel']}", iss["email"], iss["web"], f"Fax {iss['fax']}"], 3):
            p.text(ix, y, tx, fit_font(p, tx, 15, inner, False, floor=10), WHITE)
            y += 24
        if decoy_side:
            for k in range(2 if doc["extra_decoy"] else 1):
                kind_ = rng.choice(["head_office", "branch"]) if k == 0 else "postal"
                head = {"head_office": rng.choice(["Head office", "Our offices"]), "branch": rng.choice(["Walk-in centre", "Branch"]),
                        "postal": "Postal address"}[kind_]
                y += 30
                p.text(ix, y, head, p.f(17, True), WHITE)
                y += 28
                a = decoy_address(rng, doc["addr"], kind_)
                doc["decoys"].append(a)
                lines, _ = address_lines(a, rng, labelled=False, upper=rng.random() < 0.3)
                for line in lines:
                    y = p.flow(ix, y, inner, line, p.f(15), WHITE, 22)
        y += 30
        for tx in [f"VAT No {iss['vat']}", f"Reg No {iss['reg']}"]:
            p.text(ix, y, tx, fit_font(p, tx, 14, inner, False, floor=10), WHITE)
            y += 22
        assert y < H - PROC_M, "sidebar overflow"
        x0, x1 = (sw + rng.randint(40, 60), W - rng.randint(45, 75)) if side == "l" else (rng.randint(45, 75), W - sw - rng.randint(40, 60))
        board = Board(W, H, x0, x1)
        ty = rng.randint(50, 80)
        tf = p.f(rng.uniform(26, 34), True)
        right = rng.random() < 0.4
        tx0, tw = p.text(x1 if right else x0, ty, title, tf, c, anchor="r" if right else "l")
        bottom = ty + font_h(tf)
        board.add(tx0, ty, tx0 + tw, bottom)
        if rng.random() < 0.6:
            sub = rng.choice(["Monthly statement", "Please keep for your records", "Page 1 of 1", "Original tax invoice"])
            sf = p.f(18)
            sx0, sw_ = p.text(x1 if right else x0, bottom + 8, sub, sf, GREY, anchor="r" if right else "l")
            board.add(sx0, bottom + 8, sx0 + sw_, bottom + 8 + font_h(sf))
            bottom += 8 + font_h(sf)
        return f"hdrSide{side.upper()}", board, bottom, side

    x0, x1 = rng.randint(50, 90), W - rng.randint(50, 90)
    board = Board(W, H, x0, x1)
    tf = p.f(rng.uniform(20, 30), True)
    tw = text_w(p, title, tf)
    if kind == "band":
        bh = rng.randint(110, 190)
        p.d.rectangle((0, 0, W, bh), fill=c)
        board.add(0, 0, W, bh)
        side = "l" if rng.random() < 0.75 else "r"
        s = min(rng.randint(56, 100), int((bh - 34) / (1.45 if iss["shape"] == "bars" else 1)))
        lw = s + 20 if has_logo else 0
        nf = fit_font(p, iname, rng.uniform(22, 40), x1 - x0 - lw - tw - 60)
        tag_f = p.f(17)
        show_tag = bh - font_h(nf) - font_h(tag_f) > 50 and rng.random() < 0.6
        nh = font_h(nf) + (font_h(tag_f) + 8 if show_tag else 0)
        ny = (bh - nh) / 2
        if side == "l":
            if has_logo:
                logo(p, x0, (bh - s * (1.45 if iss["shape"] == "bars" else 1)) / 2, s, doc, colour=WHITE)
            p.text(x0 + lw, ny, [(iname, "ISSUER")], nf, WHITE)
            if show_tag:
                p.text(x0 + lw, ny + font_h(nf) + 8, iss["tagline"], tag_f, WHITE)
            p.text(x1, rng.choice([ny, bh - font_h(tf) - 22]), title, tf, WHITE, anchor="r")
        else:
            if has_logo:
                logo(p, x1 - s, (bh - s * (1.45 if iss["shape"] == "bars" else 1)) / 2, s, doc, colour=WHITE)
            p.text(x1 - lw, ny, [(iname, "ISSUER")], nf, WHITE, anchor="r")
            if show_tag:
                p.text(x1 - lw, ny + font_h(nf) + 8, iss["tagline"], tag_f, WHITE, anchor="r")
            p.text(x0, rng.choice([ny, bh - font_h(tf) - 22]), title, tf, WHITE)
        return "hdrBand", board, bh, None

    if kind == "plain":
        side = rng.choice("lrc")
        y = rng.randint(45, 80)
        s = rng.randint(60, 95)
        sh = s * (1.45 if iss["shape"] == "bars" else 1)
        ncol = rng.choice([c, c, INK])
        tag_f = p.f(16)
        show_tag = rng.random() < 0.5
        if side == "c":
            cx = (x0 + x1) / 2
            if has_logo:
                logo(p, cx - s / 2, y, s, doc)
                board.add(cx - s / 2, y, cx + s / 2, y + sh)
                y += sh + 12
            nf = fit_font(p, iname, rng.uniform(22, 40), x1 - x0 - 100)
            nx, nw = p.text(cx, y, [(iname, "ISSUER")], nf, ncol, anchor="c")
            board.add(nx, y, nx + nw, y + font_h(nf))
            y += font_h(nf) + 6
            if show_tag:
                tx, tw_ = p.text(cx, y, iss["tagline"], tag_f, GREY, anchor="c")
                board.add(tx, y, tx + tw_, y + font_h(tag_f))
                y += font_h(tag_f) + 6
            if rng.random() < 0.7:
                y += 8
                tx, tw_ = p.text(cx, y, title, tf, INK, anchor="c")
                board.add(tx, y, tx + tw_, y + font_h(tf))
                y += font_h(tf)
            bottom = y
        else:
            lw = s + 18 if has_logo else 0
            nf = fit_font(p, iname, rng.uniform(22, 40), x1 - x0 - lw - tw - 80)
            nh = font_h(nf) + (font_h(tag_f) + 6 if show_tag else 0)
            ny = y + max(0, (sh - nh) / 2) if has_logo else y
            if side == "l":
                if has_logo:
                    logo(p, x0, y, s, doc)
                nx, nw = p.text(x0 + lw, ny, [(iname, "ISSUER")], nf, ncol)
                if show_tag:
                    p.text(x0 + lw, ny + font_h(nf) + 6, iss["tagline"], tag_f, GREY)
                p.text(x1, y + 4, title, tf, INK, anchor="r")
                board.add(x0, y, nx + nw + 10 + (text_w(p, iss["tagline"], tag_f) if show_tag else 0), y + max(sh if has_logo else 0, nh))
                board.add(x1 - tw, y + 4, x1, y + 4 + font_h(tf))
            else:
                if has_logo:
                    logo(p, x1 - s, y, s, doc)
                nx, nw = p.text(x1 - lw, ny, [(iname, "ISSUER")], nf, ncol, anchor="r")
                if show_tag:
                    p.text(x1 - lw, ny + font_h(nf) + 6, iss["tagline"], tag_f, GREY, anchor="r")
                p.text(x0, y + 4, title, tf, INK)
                tgw = text_w(p, iss["tagline"], tag_f) if show_tag else 0
                board.add(min(nx, x1 - lw - tgw) - 10, y, x1, y + max(sh if has_logo else 0, nh))
                board.add(x0, y + 4, x0 + tw, y + 4 + font_h(tf))
            bottom = board.bottom()
        if rng.random() < 0.5:
            bottom += 16
            p.rule(x0, bottom, x1, rng.choice([c, LIGHT, INK]), rng.choice([1, 2, 3]))
            board.add(x0, bottom, x1, bottom + 3)
        return f"hdrPlain{side.upper()}", board, bottom, None

    # boxed logo + name
    side = rng.choice("lr")
    y = rng.randint(40, 70)
    s = rng.randint(52, 84)
    sh = s * (1.45 if iss["shape"] == "bars" else 1)
    pad = rng.randint(14, 22)
    nf = fit_font(p, iname, rng.uniform(22, 36), x1 - x0 - tw - 2 * pad - s - 16 - 100)
    tag_f = p.f(15)
    show_tag = rng.random() < 0.6
    nh = font_h(nf) + (font_h(tag_f) + 6 if show_tag else 0)
    inner = Block(p)
    inner.logo(0, max(0, (nh - sh) / 2), s, doc)
    ny = max(0, (sh - nh) / 2)
    inner.text(s + 16, ny, [(iname, "ISSUER")], nf, rng.choice([c, INK]))
    if show_tag:
        inner.text(s + 16, ny + font_h(nf) + 6, iss["tagline"], tag_f, GREY)
    fill = tint(c, 0.08) if rng.random() < 0.5 else None
    blk = boxed(p, inner, pad=pad, outline=c, fill=fill, width=rng.choice([1, 2, 3]), radius=rng.choice([0, 0, 10]))
    bx = x0 if side == "l" else x1 - blk.w
    blk.draw(bx, y)
    board.add(bx, y, bx + blk.w, y + blk.h)
    ty = y + rng.choice([0, (blk.h - font_h(tf)) / 2])
    if side == "l":
        p.text(x1, ty, title, tf, rng.choice([c, INK]), anchor="r")
        board.add(x1 - tw, ty, x1, ty + font_h(tf))
    else:
        p.text(x0, ty, title, tf, rng.choice([c, INK]))
        board.add(x0, ty, x0 + tw, ty + font_h(tf))
    return f"hdrBox{side.upper()}", board, y + blk.h, None


# ---- holder block ---------------------------------------------------------- #


def proc_addr_lines(p: Page, doc: dict, font, maxw: float) -> list[list]:
    rng = p.rng
    single, upper = rng.random() < 0.2, rng.random() < 0.3
    lines, printed = address_lines(doc["addr"], rng, labelled=True, single=single, upper=upper)
    if single and text_w(p, lines[0], font) > maxw:
        lines, printed = address_lines(doc["addr"], rng, labelled=True, single=False, upper=upper)
    doc["province_printed"] |= printed
    return lines


def proc_holder(p: Page, doc: dict, kind: str, maxw: float, anchor: str = "l") -> Block:
    """kind: plain | panel | grid. Always drawn once built (it sets province_printed)."""
    rng, c = p.rng, doc["issuer"]["colour"]
    fs = rng.uniform(17, 24)
    fnt, fb = p.f(fs), p.f(fs, rng.random() < 0.7)
    lh = p.lh(fnt, rng.uniform(1.22, 1.4))
    name = [(doc["person"]["printed"], "HOLDER_NAME")]
    if kind == "grid":
        ln, la = rng.choice(PROC_GRID_LABELS)
        if rng.random() < 0.2:
            ln, la = ln.upper(), la.upper()
        lf = p.f(fs * rng.uniform(0.75, 0.9), rng.random() < 0.4)
        lab_w = max(text_w(p, ln, lf), text_w(p, la, lf)) + rng.randint(20, 50)
        lines = proc_addr_lines(p, doc, fnt, maxw - lab_w - 40)
        b = Block(p)
        dy = (fnt.size - lf.size) * 0.7
        b.text(0, dy, ln, lf, GREY)
        b.text(lab_w, 0, name, fb)
        y = lh + rng.randint(4, 12)
        b.text(0, y + dy, la, lf, GREY)
        for line in lines:
            b.text(lab_w, y, line, fnt)
            y += lh
        if rng.random() < 0.5:
            return boxed(p, b, pad=rng.randint(14, 22), outline=tint(c, 0.5), width=rng.choice([1, 2]))
        return b
    label = rng.choice(PROC_HOLDER_LABELS + [None] * 4)
    lf = p.f(fs * rng.uniform(0.72, 0.85), True)
    strip = kind == "panel" and label is not None and rng.random() < 0.5
    lines = proc_addr_lines(p, doc, fnt, maxw - 50)
    rows = ([] if label is None or strip else [(label, lf, GREY)]) + [(name, fb, INK)] + [(ln_, fnt, INK) for ln_ in lines]
    bw = max(text_w(p, r[0], r[1]) for r in rows)
    b = Block(p)
    y = 0.0
    for parts, f, fill in rows:
        b.text(bw if anchor == "r" else 0, y, parts, f, fill, anchor=anchor)
        y += p.lh(f, 1.45) if f is lf else lh
    if kind != "panel":
        return b
    pad = rng.randint(16, 26)
    out = Block(p)
    radius = rng.choice([0, 8, 14])
    fill = tint(c, 0.07) if rng.random() < 0.5 else None
    top = 0
    width = max(b.w + 2 * pad, rng.uniform(320, 460) if rng.random() < 0.5 else 0)
    if strip:
        sf = p.f(17, True)
        top = font_h(sf) + 16
        width = max(width, text_w(p, label, sf) + 2 * pad)
    out.rect(0, 0, width, top + b.h + 2 * pad, fill=fill, outline=tint(c, rng.choice([0.4, 1.0])), width=2, radius=radius)
    if strip:
        out.rect(0, 0, width, top, fill=c, radius=0)
        out.text(pad, 8, label, sf, WHITE)
    out.embed(b, pad + (width - 2 * pad - b.w if anchor == "r" else 0), top + pad)
    return out


# ---- details block --------------------------------------------------------- #


def proc_extra_rows(rng: random.Random, doc: dict) -> list[tuple[str, str]]:
    t = doc["type"]
    pool = [(rng.choice(["Reference", "Our ref", "Document no"]), f"{rng.choice(['REF', 'DOC', ''])}{digits(rng, 7)}")]
    if t != "bank_statement":
        pool += [(rng.choice(["Invoice number", "Invoice no", "Tax invoice no"]), f"{rng.choice(['INV', 'TI', ''])}{digits(rng, 8)}"),
                 ("Customer VAT no", "4" + digits(rng, 9, False))]
    pool += {
        "utility_bill": [("Meter number", digits(rng, 11)), ("Tariff", rng.choice(["Domestic", "Homepower 2", "Residential"]))],
        "bank_statement": [("Branch code", digits(rng, 6)), ("Account type", rng.choice(["Cheque", "Savings", "Everyday"])),
                           ("Statement no", str(rng.randint(1, 240)))],
        "municipal_account": [("Erf / Stand no", str(rng.randint(100, 20000))),
                              ("Municipal valuation", money(rng.randint(30000000, 400000000), 0))],
        "cellphone_account": [("Cellphone number", phone(rng, True)), ("Price plan", rng.choice(["Smart 200", "Flexi 1 GB", "Top Up 100"]))],
        "insurance_statement": [("Payment method", rng.choice(["Debit order", "EFT", "Stop order"])),
                                ("Debit day", str(rng.choice([1, 15, 20, 25, 28])))],
        "lease_agreement": [("Unit", f"Unit {rng.randint(1, 60)}"), ("Monthly rental", money(rng.randint(400000, 1800000), 0))],
    }[t]
    rows = rng.sample(pool, min(len(pool), rng.randint(1, 3)))
    if t != "bank_statement" and rng.random() < 0.7:
        rows.insert(rng.randint(0, len(rows)), (rng.choice(PROC_DUE_LABELS), D(doc, doc["due"])))
    return rows


def proc_details_data(p: Page, doc: dict) -> dict:
    rng, t = p.rng, doc["type"]
    up, colon = rng.random() < 0.15, rng.random() < 0.35

    def L(s):
        return (s.upper() if up else s) + (":" if colon else "")

    acc_l = rng.choice(PROC_ACC_LABELS.get(t, PROC_ACC_LABELS["default"]))
    date_l = rng.choice(PROC_DATE_LABELS + (["Schedule date"] if t == "insurance_statement" else []))
    rows = [(L(acc_l), [(doc["acc"], "ACCOUNT_NO")]), (L(date_l), date_parts(doc, doc["date"], "DOC_DATE"))]
    if rng.random() < 0.3:
        rows.reverse()
    per = None
    if doc["period"]:
        fl, tl = rng.choice(PROC_FROM_TO)
        pl = rng.choice(PROC_PERIOD_LABELS + (["Period of cover"] if t == "insurance_statement" else []))
        per = {"label": L(pl), "parts": period_parts(doc, sep=rng.choice([" - ", " to "])),
               "split": [(L(fl), date_parts(doc, doc["period"][0], "PERIOD_FROM")),
                         (L(tl), date_parts(doc, doc["period"][1], "PERIOD_TO"))]}
    return {"rows": rows, "period": per, "extras": [(L(a), v) for a, v in proc_extra_rows(rng, doc)],
            "acc_l": acc_l, "date_l": date_l}


def det_rows(det: dict, combined: bool, plain: bool = False) -> list:
    rows = list(det["rows"])
    if det["period"]:
        rows += [(det["period"]["label"], det["period"]["parts"])] if combined else list(det["period"]["split"])
    rows += det["extras"]
    if plain:  # grid cells and column headings carry no colon
        rows = [(lab.rstrip(":"), v) for lab, v in rows]
    return rows


def proc_kv(p: Page, doc: dict, det: dict, maxw: float, groups: int = 1, stretch: bool = False) -> Block | None:
    rng, c = p.rng, doc["issuer"]["colour"]
    lf, vf = p.f(rng.uniform(15, 18)), p.f(rng.uniform(16, 19), rng.random() < 0.6)
    mode = rng.choice(["col", "right"]) if groups > 1 or stretch else rng.choice(["col", "col", "right", "stack"])
    box = rng.random() < 0.4
    pad = rng.randint(14, 20) if box else 0
    title = rng.choice(["Account details", "Account summary", "Statement details", "Your account", "Invoice details"]) \
        if box and rng.random() < 0.7 else None
    gw = (maxw - 2 * pad) if groups == 1 else (maxw - 2 * pad - 50) / 2
    for combined, m in [(True, mode), (False, mode), (False, "stack")]:
        rows = det_rows(det, combined)
        lab_w = max(text_w(p, r[0], lf) for r in rows)
        val_w = max(text_w(p, r[1], vf) for r in rows)
        w = max(lab_w, val_w) if m == "stack" else lab_w + (28 if m == "col" else 40) + val_w
        if w <= gw:
            mode = m
            break
    else:
        return None
    if mode == "right":
        w = max(w, min(gw, rng.uniform(320, 480)))
    if groups > 1 or stretch:  # an across block spans the column
        w = max(w, min(gw, (maxw - 2 * pad - 50 * (groups - 1)) / groups))
        if mode == "col":
            lab_w = max(lab_w, w - val_w - 28) if rng.random() < 0.5 else lab_w
    gap = max(p.lh(lf, 1.5), p.lh(vf, 1.35)) if mode != "stack" else font_h(lf) + 4 + p.lh(vf, 1.5)
    rules = mode != "stack" and rng.random() < 0.3
    inner = Block(p)
    per_group = -(-len(rows) // groups)
    for g in range(groups):
        gx = g * (w + 50)
        y = 0.0
        for lab, val in rows[g * per_group:(g + 1) * per_group]:
            if mode == "stack":
                inner.text(gx, y, lab, lf, GREY)
                inner.text(gx, y + font_h(lf) + 4, val, vf)
            else:
                inner.text(gx, y + (vf.size - lf.size) * 0.7, lab, lf, GREY)
                if mode == "col":
                    inner.text(gx + lab_w + 28, y, val, vf)
                else:
                    inner.text(gx + w, y, val, vf, anchor="r")
                if rules:
                    inner.rect(gx, y + gap - 7, gx + w, y + gap - 6, fill=(225, 225, 228))
            y += gap
    if not box:
        return inner
    b = Block(p)
    tw_ = max(inner.w, text_w(p, title, p.f(19, True)) if title else 0)
    th = (font_h(p.f(19, True)) + 18) if title else 0
    b.rect(0, 0, tw_ + 2 * pad, th + inner.h + 2 * pad, outline=c, width=2, radius=rng.choice([0, 10]))
    if title:
        b.rect(1, 1, tw_ + 2 * pad - 1, th, fill=tint(c, 0.15))
        b.text(pad, 9, title, p.f(19, True), c)
    b.embed(inner, pad, th + pad)
    return b


def proc_grid(p: Page, doc: dict, det: dict, maxw: float, across: bool) -> Block | None:
    rng, c = p.rng, doc["issuer"]["colour"]
    lf, vf = p.f(rng.uniform(12, 14), rng.random() < 0.6), p.f(rng.uniform(16, 18), True)
    up, strip = rng.random() < 0.5, rng.random() < 0.5
    pad = 10
    for combined in (True, False):
        cells = [(lab.upper() if up else lab, v) for lab, v in det_rows(det, combined, plain=True)]
        cw = max(max(text_w(p, lab, lf), text_w(p, v, vf)) for lab, v in cells) + 2 * pad
        ncols = rng.choice([3, 4]) if across else 2
        while ncols > 1 and ncols * cw > maxw:
            ncols -= 1
        if ncols * cw <= maxw and (ncols >= 2 or not combined):
            break
    else:
        return None
    if across:
        cw = maxw / ncols
    lab_h = font_h(lf) + 8
    ch = lab_h + 10 + font_h(vf) + pad
    line = rng.choice([INK, tint(c, 0.6), GREY])
    b = Block(p)
    for k, (lab, v) in enumerate(cells):
        x, y = (k % ncols) * cw, (k // ncols) * ch
        if strip:
            b.rect(x, y, x + cw, y + lab_h, fill=tint(c, 0.15))
        b.rect(x, y, x + cw, y + ch, outline=line, width=1)
        b.text(x + pad, y + 4, lab, lf, INK if strip else GREY)
        b.text(x + pad, y + lab_h + 6, v, vf)
    return b


def proc_row(p: Page, doc: dict, det: dict, maxw: float, justify: bool) -> Block | None:
    rng, c = p.rng, doc["issuer"]["colour"]
    lf, vf = p.f(rng.uniform(14, 16)), p.f(rng.uniform(16, 19), rng.random() < 0.7)
    cols = det_rows(det, rng.random() < 0.3, plain=True)
    ws = [max(text_w(p, lab, lf), text_w(p, v, vf)) for lab, v in cols]
    gap = rng.randint(36, 60)
    band, rules = rng.random() < 0.45, rng.random() < 0.6
    bp = 10 if band else 0
    if max(ws) > maxw - 2 * bp:
        return None
    lines, cur, cur_w = [], [], 0.0
    for col, w in zip(cols, ws):
        if cur and cur_w + gap + w > maxw - 2 * bp:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur_w += (gap if cur else 0) + w
        cur.append((col, w))
    lines.append(cur)
    lh = bp + font_h(lf) + 6 + font_h(vf) + bp
    b = Block(p)
    width = maxw if justify else max(sum(w for _, w in ln) + gap * (len(ln) - 1) for ln in lines) + 2 * bp
    y = 0.0
    for ln in lines:
        if band:
            b.rect(0, y, width, y + lh, fill=tint(c, 0.1))
        elif rules:
            b.rect(0, y, width, y + 2, fill=c)
        sp = (width - 2 * bp - sum(w for _, w in ln)) / (len(ln) - 1) if justify and len(ln) > 1 else gap
        x = bp
        for (lab, v), w in ln:
            b.text(x, y + bp + (4 if rules and not band else 0), lab, lf, GREY)
            b.text(x, y + bp + font_h(lf) + 6 + (4 if rules and not band else 0), v, vf)
            x += w + sp
        y += lh + (8 if rules and not band else 0) + 10
    return b


def proc_inline(p: Page, doc: dict, det: dict, maxw: float) -> Block:
    rng = p.rng
    f = p.f(rng.uniform(16, 19))
    lh = p.lh(f, 1.4)
    acc, dd = (doc["acc"], "ACCOUNT_NO"), (D(doc, doc["date"]), "DOC_DATE")
    sents = [rng.choice([["Account number", acc], ["Your account number is", acc], [det["acc_l"] + ":", acc],
                         ["This statement is for account", acc]]),
             rng.choice([["Issued on", dd], ["This statement is dated", dd], [det["date_l"] + ":", dd], ["Date issued:", dd]])]
    if doc["period"]:
        fr, to = (D(doc, doc["period"][0]), "PERIOD_FROM"), (D(doc, doc["period"][1]), "PERIOD_TO")
        sents.append(rng.choice([["Statement for the period", fr, "to", to], ["This account covers the period", fr, "to", to],
                                 ["Charges for the period", fr, "-", to], ["Billing period:", fr, "to", to]]))
    rng.shuffle(sents)
    if doc["type"] != "bank_statement" and rng.random() < 0.6:
        sents.append([rng.choice(["Payment is due by", "Please pay by", "Amount payable by"]), D(doc, doc["due"])])
    width = min(maxw, rng.uniform(min(maxw, 420), maxw))
    b = Block(p)
    y = 0.0
    if rng.random() < 0.4:
        hf = p.f(18, True)
        b.text(0, 0, rng.choice(["Account information", "About this statement", "Your account"]), hf)
        y += p.lh(hf, 1.6)
    if rng.random() < 0.5:  # one paragraph
        parts = [x for s in sents for x in with_end(s, ".")]
        b.flow(0, y, width, parts, f, INK, lh)
    else:
        dot = rng.random() < 0.4
        for s in sents:
            y = b.flow(0, y, width, with_end(s, ".") if dot else s, f, INK, lh) + 4
    return b


# ---- other top blocks ------------------------------------------------------ #


def proc_decoy_box(p: Page, doc: dict, *, border: bool, maxw: float, align: str = "l") -> Block:
    rng, iss, c = p.rng, doc["issuer"], doc["issuer"]["colour"]
    kind = rng.choice(["head_office", "postal", "branch"])
    a = decoy_address(rng, doc["addr"], kind)
    doc["decoys"].append(a)
    fs = rng.uniform(14, 16)
    f, fb = p.f(fs), p.f(fs + 1, True)
    lh = p.lh(f, 1.3)
    heading = rng.choice({"head_office": ["Head office", "Contact us", "Our offices", "Registered office"],
                          "postal": ["Postal address", "Correspondence", "Contact us"],
                          "branch": ["Walk-in centre", "Branch", "Customer service centre"]}[kind])
    lines, _ = address_lines(a, rng, labelled=False, single=rng.random() < 0.25, upper=rng.random() < 0.3)
    contacts = rng.sample([f"Tel {iss['tel']}", iss["email"], iss["web"], f"VAT No {iss['vat']}", f"Fax {iss['fax']}"],
                          rng.randint(1, 3))
    rows = ([(heading, fb)] if border or rng.random() < 0.5 else []) + [(ln_, f) for ln_ in lines] + [(t_, f) for t_ in contacts]
    inner_max = maxw - (40 if border else 0)
    b = Block(p)
    if all(text_w(p, r, fn) <= inner_max for r, fn in rows):
        bw = max(text_w(p, r, fn) for r, fn in rows)
        y = 0.0
        for r, fn in rows:
            b.text(bw if align == "r" else 0, y, r, fn, INK if fn is fb else GREY, anchor=align)
            y += lh
    else:
        y = 0.0
        for r, fn in rows:
            y = b.flow(0, y, inner_max, r if isinstance(r, list) else [r], fn, INK if fn is fb else GREY, lh)
    if not border:
        return b
    return boxed(p, b, pad=rng.randint(14, 20), outline=tint(c, 0.5), fill=tint(c, 0.05) if rng.random() < 0.4 else None,
                 width=rng.choice([1, 2]), radius=rng.choice([0, 8]))


def proc_amount_box(p: Page, doc: dict, total: int) -> Block:
    rng, c = p.rng, doc["issuer"]["colour"]
    b = Block(p)
    lf, bf, sf = p.f(16), p.f(rng.uniform(24, 30), True), p.f(15)
    if doc["type"] == "bank_statement":
        b.text(0, 0, rng.choice(["Closing balance", "Available balance"]), lf, GREY)
        b.text(0, font_h(lf) + 6, money(rng.randint(10000, 3000000), doc["money_style"]), bf, INK)
    else:
        b.text(0, 0, rng.choice(["Amount due", "Total amount due", "Please pay"]), lf, GREY)
        b.text(0, font_h(lf) + 6, money(total, doc["money_style"]), bf, INK)
        y = font_h(lf) + 6 + font_h(bf) + 10
        b.text(0, y, f"{rng.choice(PROC_DUE_LABELS)}: {D(doc, doc['due'])}", sf, INK)
        if rng.random() < 0.5:
            paid = D(doc, doc["date"] - dt.timedelta(days=rng.randint(12, 28)))
            b.text(0, y + p.lh(sf, 1.5), f"Payment received {paid} - thank you", sf, GREY)
    return boxed(p, b, pad=rng.randint(16, 22), fill=tint(c, rng.choice([0.08, 0.15])), radius=rng.choice([0, 10]),
                 outline=tint(c, 0.4) if rng.random() < 0.5 else None)


# ---- the page ------------------------------------------------------------- #


def lay_proc(p: Page, doc: dict) -> str:
    """Compose one procedural page; returns its layout id proc_<holder>_<details>_<style>_<header>."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c, t = iss["colour"], doc["type"]
    up_issuer = rng.random() < 0.12
    if up_issuer:
        doc["issuer_printed"] = iss["name"].upper()
    hdr_kind = rng.choices(["band", "plain", "side", "box"], [26, 28, 22, 24])[0]
    decoy_at = rng.choices(["hdr", "box", "footer"], [40, 30, 30])[0] if doc["decoy"] else None
    hdr_tag, board, hdr_bottom, sidebar = proc_header(p, doc, hdr_kind, decoy_side=decoy_at == "hdr" and hdr_kind == "side")
    x0, x1 = board.x0, board.x1
    colw = x1 - x0
    y_top = hdr_bottom + rng.randint(25, 50)

    # the table rows are chosen first so an "amount due" box can quote the total
    if t == "bank_statement":
        raw, rows_ = None, None
    else:
        rows_, raw = charge_rows(p, doc, rng.randint(3, 8), with_prev=t != "insurance_statement")
    total = sum(r[2] for r in raw) + round(sum(r[2] for r in raw) * 0.15) if raw else 0

    if decoy_at == "hdr" and hdr_kind != "side":
        blk = proc_decoy_box(p, doc, border=False, maxw=colw * 0.45, align=rng.choice("lr"))
        right = not hdr_tag.endswith("R")
        if hdr_kind == "band":
            cands = [("hdr", x1 - blk.w if right else x0, hdr_bottom + 20)]
        else:
            cands = [("hdr", x1 - blk.w if right else x0, PROC_M + 10)]
        if not board.place(blk, cands, gap=20, push=400):
            doc["decoys"].pop()
            decoy_at = "footer"

    # holder and details
    opts = {"win": 16, "R": 16, "midL": 14, "panel": 18, "grid": 14}
    if sidebar:
        opts["side"] = 20
        if sidebar == "l":
            del opts["win"]
    hv = rng.choices(list(opts), list(opts.values()))[0]
    if hv == "win":
        hside = "l"
    elif hv == "R":
        hside = "r"
    elif hv == "side":
        hside = "r" if sidebar == "l" else "l"
    elif hv == "midL":
        hside = "l"
    else:
        hside = "l" if rng.random() < (0.55 if hv == "panel" else 0.7) else "r"
    kind = {"panel": "panel", "grid": "grid"}.get(hv, "plain")
    anchor = "r" if hside == "r" and kind == "plain" and rng.random() < 0.5 else ("r" if kind == "panel" and hside == "r" and rng.random() < 0.3 else "l")

    det = proc_details_data(p, doc)
    dplaces = ["L", "R", "across"] if hv == "midL" else ["L", "R", "under", "across"]
    dplaces = [d for d in dplaces if not (d == "L" and hside == "l" and hv != "midL") and not (d == "R" and hside == "r" and hv != "midL")]
    dplace = rng.choice(dplaces)
    dstyle = rng.choices(["kv", "grid", "row", "inline"], [32, 22, 24, 22])[0]
    holder_pos = None

    def build_details(place, style, maxw):
        if style == "kv":
            if place == "across":
                return proc_kv(p, doc, det, maxw, groups=2) or proc_kv(p, doc, det, maxw, stretch=True)
            return proc_kv(p, doc, det, maxw)
        if style == "grid":
            return proc_grid(p, doc, det, maxw, across=place == "across")
        if style == "row":
            return proc_row(p, doc, det, maxw, justify=place == "across")
        return proc_inline(p, doc, det, maxw)

    def place_details():
        nonlocal dplace
        order = [dplace] + [d for d in dplaces if d != dplace] + ["across"]
        for place in order:
            if place == "under" and holder_pos is None:
                continue
            if place == "across":
                maxw = colw
            elif place == "under":
                hx, hy, hw, hh = holder_pos
                maxw = (x1 - hx) if hside == "l" else (hx + hw - x0)
                maxw = min(maxw, colw * (0.62 if dstyle in ("kv", "grid") else 1.0))
            elif holder_pos is not None:
                hx, hy, hw, hh = holder_pos
                maxw = (hx - x0 - 40) if place == "L" else (x1 - hx - hw - 40)
                maxw = min(maxw, colw * 0.62)
            else:
                maxw = colw * 0.55
            if maxw < 260:
                continue
            blk = build_details(place, dstyle, maxw)
            if blk is None:
                blk = proc_kv(p, doc, det, maxw)
                if blk is None:
                    continue
            j = rng.randint(0, 30)
            if place == "across":
                cands = [("Across", x0, board.bottom(x0, x1) + rng.randint(26, 50))]
                y_max = PROC_TOP_LIMIT + 120
            elif place == "under":
                hx, hy, hw, hh = holder_pos
                cands = [("Under", hx if hside == "l" else hx + hw - blk.w, hy + hh + rng.randint(26, 50))]
                y_max = PROC_TOP_LIMIT
            elif place == "L":
                cands = [("L", x0 + j, y_top + rng.randint(0, 40))]
                y_max = PROC_TOP_LIMIT
            else:
                cands = [("R", x1 - blk.w - j, y_top + rng.randint(0, 40))]
                y_max = PROC_TOP_LIMIT
            got = board.place(blk, cands, y_max=y_max)
            if got:
                dplace = place
                return got
        raise ProcReroll("details do not fit")

    def place_holder():
        nonlocal hv
        maxw = colw * (0.62 if hv not in ("midL",) else 0.75)
        blk = proc_holder(p, doc, kind, maxw, anchor)
        j = rng.randint(0, 40)
        if hv == "win":
            cands = [("Win", max(x0, rng.randint(90, 140)), max(y_top, rng.randint(230, 330)))]
        elif hv == "midL":
            cands = [("MidL", x0 + j, board.bottom(x0, x1) + rng.randint(30, 60))]
        elif hv == "side":
            cands = [("Side", x1 - blk.w - j if hside == "r" else x0 + j, y_top + rng.randint(0, 50))]
        else:
            base = {"R": "R", "panel": "Panel", "grid": "Grid"}[hv] + ("" if hv == "R" else hside.upper())
            cands = [(base, x1 - blk.w - j if hside == "r" else x0 + j, y_top + rng.randint(0, 60))]
        got = board.place(blk, cands)
        if not got:
            low = {"plain": "Low", "panel": "PanelLow", "grid": "GridLow"}[kind]
            got = board.place(blk, [(low, x0, board.bottom(x0, x1) + 30)], y_max=PROC_TOP_LIMIT + 200, push=400)
        if not got:
            raise ProcReroll("holder does not fit")
        return got

    if hv == "midL":
        dslot = place_details()
        if rng.random() < 0.4:  # a coloured section strip between the details and the holder
            sf = p.f(rng.uniform(17, 20), True)
            sb = Block(p)
            sb.rect(0, 0, colw, font_h(sf) + 18, fill=rng.choice([c, tint(c, 0.2)]))
            sb.text(14, 9, rng.choice(["Customer details", "ACCOUNT HOLDER", "Your details", "Addressed to"]), sf,
                    WHITE if sb.items[0][5] == c else INK)
            board.place(sb, [("strip", x0, board.bottom(x0, x1) + 26)], y_max=PROC_TOP_LIMIT)
        hslot = place_holder()
    else:
        hslot = place_holder()
        r = board.rects[-1]
        holder_pos = (r[0], r[1], r[2] - r[0], r[3] - r[1])
        dslot = place_details()

    if decoy_at == "box":
        blk = proc_decoy_box(p, doc, border=True, maxw=min(460, colw * 0.45))
        cands = [("box", x1 - blk.w, y_top), ("box", x0, y_top), ("box", x0, board.bottom(x0, x1) + 30)]
        if not board.place(blk, cands, y_max=PROC_TOP_LIMIT + 60):
            doc["decoys"].pop()
            decoy_at = "footer"
    if rng.random() < 0.45:
        blk = proc_amount_box(p, doc, total)
        board.place(blk, [("amt", x1 - blk.w, y_top), ("amt", x0, y_top), ("amt", x1 - blk.w, board.bottom(x0, x1) + 30)],
                    y_max=PROC_TOP_LIMIT, push=240)

    # body
    y = board.bottom(x0, x1) + rng.randint(30, 55)
    foot_y = H - (100 if decoy_at == "footer" else 82)
    rem = sidebar is None and colw >= 950 and t != "bank_statement" and rng.random() < 0.35
    body_end = (H - 300) if rem else foot_y - 30
    tf, tfb = p.f(rng.uniform(15, 18)), p.f(rng.uniform(15, 18), True)
    row_h = p.lh(tf, rng.uniform(1.6, 1.9))
    totals_h = 4 * p.lh(tf, 1.6) + 15
    if doc["twice"] and t not in ("bank_statement", "cellphone_account") and y + 200 + 6 * row_h + totals_h < body_end:
        y = holder_block(p, x0, y, doc, label=rng.choice(["Supply address", "Property address", "Service address", "Risk address"]
                                                       if t == "insurance_statement" else ["Supply address", "Property address", "Service address"]),
                         fs=17, name=False, single=True) + 20
    if rng.random() < 0.2 and y + 160 + 6 * row_h + totals_h < body_end:
        sf = p.f(18)
        p.text(x0, y, ["Dear ", (doc["person"]["salutation"], "HOLDER_NAME"), ","], sf)
        y += 34
        y = p.flow(x0, y, colw, [rng.choice(["Please find your account below. Thank you for your prompt payment.",
                                             "Thank you for being a valued customer. Your statement for this period follows."])],
                   sf) + 16
    if rng.random() < 0.5:
        p.text(x0, y, rng.choice(["Summary of charges", "Account summary", "Details of this account", "Transactions",
                                  "Your charges this period"]) if t != "bank_statement" else rng.choice(["Transactions", "Transaction history"]),
               p.f(rng.uniform(18, 22), True), rng.choice([c, INK]))
        y += 40
    head = rng.choice(["fill", "tint", "rule"])
    hkw = {"fill": dict(head_fill=c), "tint": dict(head_fill=tint(c, 0.22), head_ink=INK), "rule": {}}[head]
    shade = tint(c, 0.07) if rng.random() < 0.5 else None
    grid = (225, 225, 228) if rng.random() < 0.5 else None
    upper_heads = rng.random() < 0.25
    U = (lambda hs: [h_.upper() for h_ in hs]) if upper_heads else (lambda hs: hs)
    ms = doc["money_style"]
    if t == "bank_statement":
        n_fit = int((body_end - 60 - y) // row_h) - 3
        bal = rng.randint(100000, 3000000)
        tx = transactions(rng, doc, max(3, min(rng.randint(8, 26), n_fit)))
        rows = [["", "Opening balance", "", money(bal, ms)]]
        tx_style = rng.choice(["dmy_slash", "d_mon_y"])
        for d, desc, amt in tx:
            bal += amt
            rows.append([fmt_date(d, tx_style), desc, money(amt, ms), money(bal, ms)])
        rows.append(["", "Closing balance", "", money(bal, ms)])
        y = table(p, x0, y, colw, U(["Date", "Description", "Amount", "Balance"]), rows, [0.18, 0.42, 0.2, 0.2], "llrr", tf, tfb,
                  row_h=row_h, shade=shade, grid=grid, **hkw)
    else:
        n_fit = int((body_end - totals_h - 80 - y) // row_h) - 1
        if len(rows_) > n_fit:  # drop the previous-balance pair, then charges, so the table fits
            n_prev = len(rows_) - len(raw)
            if n_prev:
                rows_ = rows_[n_prev:]
            while len(rows_) > max(2, n_fit):
                rows_.pop()
                raw.pop()
        if t == "insurance_statement":
            rows2 = [[d, "" if d in ("Policy fee", "Roadside assist") else money(rng.randint(500000, 300000000), 0), a] for d, _, a in rows_]
            y = table(p, x0, y, colw, U(["Section", "Sum insured", "Monthly premium"]), rows2, [0.46, 0.27, 0.27], "lrr", tf, tfb,
                      row_h=row_h, shade=shade, grid=grid, **hkw)
        else:
            hs = rng.choice([["Description", "Quantity", "Amount"], ["Item", "Usage", "Amount"], ["Charges", "Units", "Amount"],
                             ["Service", "Basis", "Amount (incl. VAT)"]])
            y = table(p, x0, y, colw, U(hs), rows_, [0.58, 0.19, 0.23], "lrr", tf, tfb, row_h=row_h, shade=shade, grid=grid, **hkw)
        y = totals(p, x1 - 10, y + 15, doc, raw, tf, tfb, label_x=x1 - min(430, colw * 0.5),
                   due_label="Next collection" if t == "insurance_statement" else rng.choice(PROC_DUE_LABELS),
                   box_colour=tint(c, 0.15) if rng.random() < 0.5 else None)
    small_print(p, x0, y + 30, colw, body_end, doc, rng.choice([12, 13]), rng.randint(3, 7), issuer_upper=up_issuer)
    if rem:
        remittance(p, doc, H - 290, x0, x1, 16)
    footer(p, doc, foot_y, x0, x1, 13, decoy_here=decoy_at == "footer", colour=c if rng.random() < 0.4 else None,
           centre=rng.random() < 0.3)
    dtag = {"L": "L", "R": "R", "under": "Under", "across": "Across"}[dplace]
    return f"proc_addr{hslot[0]}_details{dtag}_{dstyle}_{hdr_tag}"


PERIOD_P["proc"] = 0.75
LAYOUT_DATE_STYLES["proc"] = DATE_STYLES[:-1]
LAYOUT_FONTS["proc"] = list(FONTS)
LAYOUT_FN["proc"] = lay_proc


# --------------------------------------------------------------------------- #
# Build, check, save
# --------------------------------------------------------------------------- #


def build(seed: int, index: int, layout: str, today: dt.date, attempt: int) -> tuple[Image.Image, dict, list[str]]:
    rng = random.Random(f"poa:{seed}:{index}:{attempt}")
    doc_id = f"poa_{index:05d}"
    dtype = rng.choices(list(PROC_TYPES), list(PROC_TYPES.values()))[0] if layout == "proc" else None
    doc = make_doc(rng, layout, today, doc_id, dtype)
    W, H = SIZES.get(layout, (1240, 1754))
    p = Page(W, H, rng, rng.choice(LAYOUT_FONTS[layout]), k=rng.uniform(0.94, 1.06))
    layout = LAYOUT_FN[layout](p, doc) or layout  # a procedural page returns its composed layout id
    a = doc["addr"]
    period = doc["period"]
    recent = doc["date"] >= minus_months(today, 3)
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
        "age_days": doc["age"], "recent": recent, "future_dated": doc["age"] < 0,
        "decoy_addresses": [{k: d[k] for k in ("kind", "street", "suburb", "city", "province", "postal_code")} for d in doc["decoys"]],
        "spans": p.spans,
    }
    return p.img, truth, p.texts


def check(img: Image.Image, truth: dict, texts: list[str] | None = None) -> str | None:
    blob = json.dumps(truth, ensure_ascii=False) + "\n".join(texts or [])
    bad = forbidden_in(blob)
    if bad:
        return f"forbidden string {bad!r}"
    W, H = img.size
    labels = {s["label"] for s in truth["spans"]}
    for need in ("HOLDER_NAME", "STREET", "CITY", "POSTAL_CODE", "DOC_DATE", "ISSUER", "ACCOUNT_NO"):
        assert need in labels, (truth["id"], need)
    if truth["fields"]["statement_period"]:
        assert {"PERIOD_FROM", "PERIOD_TO"} <= labels, truth["id"]
    assert ("PROVINCE" in labels) == truth["fields"]["province_printed"], truth["id"]
    boxes = [w["box"] for s in truth["spans"] for w in s["words"]]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                raise AssertionError((truth["id"], "overlapping span words", a, b))
    for s in truth["spans"]:
        assert s["words"] and " ".join(w["text"] for w in s["words"]) == " ".join(s["text"].split()), s
        for w in s["words"]:
            x0, y0, x1, y1 = w["box"]
            assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, (truth["id"], s["label"], w)
    return None


def render_one(job: tuple) -> tuple[str, float]:
    seed, index, layouts, today, out, debug = job
    t0 = time.perf_counter()
    layout = layouts[index % len(layouts)]
    for attempt in range(25):
        try:
            img, truth, texts = build(seed, index, layout, today, attempt)
        except ProcReroll as e:
            problem = str(e)
            continue
        problem = check(img, truth, texts)
        if not problem:
            break
    else:
        raise RuntimeError(f"poa_{index:05d}: {problem}")
    out = Path(out)
    img.save(out / f"{truth['id']}.png", compress_level=1)
    (out / f"{truth['id']}.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False) + "\n")
    if debug:
        dbg = img.copy()
        d = ImageDraw.Draw(dbg)
        colours = {"HOLDER_NAME": (230, 0, 0), "STREET": (0, 150, 0), "SUBURB": (0, 160, 200), "CITY": (0, 0, 230),
                   "PROVINCE": (200, 0, 200), "POSTAL_CODE": (240, 140, 0), "DOC_DATE": (255, 0, 120),
                   "PERIOD_FROM": (120, 60, 0), "PERIOD_TO": (60, 120, 0), "ISSUER": (0, 200, 120), "ACCOUNT_NO": (130, 0, 255)}
        lf = load_font(FONTS["dejavu_sans"][1], 10)
        for s in truth["spans"]:
            col = colours[s["label"]]
            for w in s["words"]:
                d.rectangle(w["box"], outline=col, width=1)
            b = s["words"][0]["box"]
            d.text((b[0], b[1] - 11), s["label"], font=lf, fill=col)
        dbg.save(out / f"{truth['id']}_boxes.png", compress_level=1)
    return truth["id"], time.perf_counter() - t0


def write_places() -> None:
    PLACES_JSON.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"suburb": s, "city": c, "province": p, "postal_code": code} for s, c, p, code in PLACES]
    PLACES_JSON.write_text(json.dumps(rows, indent=1) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="/tmp/docscan-poa/synth")
    ap.add_argument("--layouts", default=",".join(LAYOUTS))
    ap.add_argument("--today", default="2026-10-15")
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--procedural", action="store_true",
                    help="compose every page procedurally (layout ids proc_<holder>_<details>_<style>_<header>)")
    args = ap.parse_args()
    layouts = ["proc"] if args.procedural else [x.strip() for x in args.layouts.split(",") if x.strip()]
    for x in layouts:
        assert x in LAYOUT_FN, f"unknown layout {x}; choose from {LAYOUTS}"
    today = dt.date.fromisoformat(args.today)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    write_places()
    jobs = [(args.seed, i, layouts, today, args.out, args.debug) for i in range(args.start_index, args.start_index + args.count)]
    t0 = time.perf_counter()
    if args.jobs > 1:
        with mp.Pool(args.jobs) as pool:
            res = list(pool.imap_unordered(render_one, jobs, chunksize=4))
    else:
        res = [render_one(j) for j in jobs]
    dt_ = time.perf_counter() - t0
    per = sum(r[1] for r in res) / max(1, len(res))
    print(f"wrote {len(res)} documents to {args.out} in {dt_:.1f} s ({per:.3f} s/page per worker); places -> {PLACES_JSON}")


if __name__ == "__main__":
    main()
