"""Proof-of-address pages with a far wider vocabulary and more layout families than
poa_synth.py, for training the field tagger to read *context* rather than memorise
the generator's world; and DEV-G, a generalisation set of held-out families,
fonts and vocabulary.

poa_synth.py draws from 111 places, 50 streets, ~90 first names, ~80 surnames and
20 issuer roots, so a tagger trained on it learns that "Acacia" is a street and
"Nkosi" a name. Here every value is drawn from pools hundreds to thousands wide
(names and street and issuer roots partly generated from syllables, places from
the GeoNames gazetteer docscan ships), and six new layout families are added to
poa_synth's own (letters that name the holder inside a sentence under "To whom it
may concern", window envelopes with a return address above the holder, label:
value pages, statements with a branch address, right-hand panels, a holder named
only in the salutation and the remittance slip).

Every pool and family is split in two by a hash of its value: `--split train`
draws only from the train half, `--split devg` only from the held-out half, with
held-out fonts and two held-out families (`w_branch`, `w_certify`), so DEV-G
measures what a page of new layout, font, people, streets and places does. None
of this uses the lockbox's generator, families, fonts or seeds
(eval/LOCKBOX.md); its five fonts are excluded by name.

Output is poa_synth.py's: <id>.png + <id>.json with the same truth and spans, so
poa_augment.py and train/build_dataset.py work unchanged.

  .venv/bin/python poa_wide.py --split train --count 3000 --start-index 20000 --jobs 4 --out /tmp/docscan-poa-work/wide
  .venv/bin/python poa_wide.py --split devg --count 300 --start-index 90000 --jobs 4 --out /tmp/docscan-poa-work/devg

Fonts: fetch_wide_fonts.sh (SIL OFL 1.1, from github.com/google/fonts) into
/tmp/docscan-poa-work/fonts. Places: docscan/src/poa/za_places.tsv (GeoNames, CC BY 4.0).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import multiprocessing as mp
import random
import re
import time
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

import poa_synth as S

ROOT = Path(__file__).resolve().parent.parent
TSV = ROOT / "docscan" / "src" / "poa" / "za_places.tsv"
FONT_DIR = Path("/tmp/docscan-poa-work/fonts")
LOCKBOX_FONTS = ("TitilliumWeb", "Oxygen", "Hind", "Arvo", "SpaceMono")


def held_out(s: str) -> bool:
    """One fifth of every pool is DEV-G's, by a hash of the value."""
    return hashlib.sha256(("wide:" + s.lower()).encode()).digest()[0] % 5 == 0


def split_pool(pool: list[str], split: str) -> list[str]:
    out = [x for x in dict.fromkeys(pool) if held_out(x) == (split == "devg")]
    return [x for x in out if not S.forbidden_in(x)]


# --------------------------------------------------------------------------- #
# Names: common South African first names and surnames, and generated ones
# --------------------------------------------------------------------------- #

FIRST_M = """Sipho Thabo Mandla Bongani Sibusiso Themba Lwazi Kagiso Tshepo Neo Tumelo Katlego Pieter Johan Willem Hendrik
Francois Gerhard Ruan Jaco Michael David John Peter Andrew James Mohammed Yusuf Ashwin Rajesh Pravin Siyabonga Lunga Xolani
Vusi Musa Tebogo Kabelo Ofentse Riaan Ebrahim Faizal Clinton Luthando Sizwe Mthunzi Andile Ayabonga Bheki Dumisani Jabulani
Khaya Lindani Lucky Lungile Mzwandile Nhlanhla Njabulo Phumlani Sandile Sbusiso Simphiwe Siphiwe Thulani Wandile Zakhele
Zola Mlungisi Mxolisi Sello Lesego Thapelo Tshepiso Karabo Mpho Tlotlo Oratile Kgosi Kamogelo Bonolo Lefa Molefi Puleng
Rethabile Teboho Thato Motlatsi Hlompho Lehlohonolo Nkululeko Ntokozo Sakhile Tumi Jan Koos Danie Wynand Stefan Christo
Gert Marius Deon Hennie Schalk Louis Charl Theuns Wessel Dirk Brendan Craig Gareth Grant Kevin Mark Neil Shaun Trevor
Warren Wayne Dylan Ryan Jason Liam Ethan Nathan Joshua Daniel Matthew Imran Zaid Tariq Rashid Anwar Goolam Nadeem Riyaad
Shaheed Waseem Kumaran Suresh Dinesh Vishal Kiran Navin Prakash Sanjay Devan Kreason Nikhil Tshilidzi Mpfariseni Rudzani
Ndivhuwo Fhatuwani Khathutshelo Vhutshilo Hlulani Tiyani Nyiko Xihlamariso Rhulani Masingita Langa Sabelo Mondli Velile
Mthokozisi Mduduzi Muzi Sifiso Thokozani Bafana Zweli Mongezi Luvuyo Siyamthanda Lubabalo Mawande Aphiwe Athenkosi""".split()
FIRST_F = """Thandiwe Lerato Nomvula Zanele Nokuthula Ayanda Precious Palesa Naledi Refilwe Boitumelo Dineo Karabo Anika Elmarie
Marike Annelie Liezel Sunette Chantelle Priya Kavitha Shanthi Fatima Ayesha Zainab Sarah Emma Megan Lindiwe Nosipho Busisiwe
Yolanda Sindisiwe Asanda Khanyisile Masego Onalenna Nthabiseng Ronel Charlene Mbali Zodwa Lebogang Mpho Ntombi Nomsa
Nompumelelo Thembeka Zinhle Hlengiwe Gugu Nonhlanhla Sibongile Thobeka Nandi Amahle Lwandile Zintle Siphokazi Nolwazi
Bongiwe Phindile Ntombizodwa Zandile Keabetswe Kelebogile Tshegofatso Goitseone Itumeleng Mmathapelo Dimakatso Mamello
Nthati Lineo Puleng Relebohile Tsholofelo Kgomotso Dikeledi Mapula Mantwa Johanna Maria Elsabe Riana Carina Hanlie Marlene
Mariska Lize Christelle Nadia Jolene Bianca Michelle Nicole Lauren Jessica Kirsten Kelly Natasha Samantha Claire Rachel Tanya
Leigh Robyn Candice Nazeema Shireen Ruwayda Faranaaz Nafisa Raeesa Thasneem Yasmin Sumaya Anisha Kamini Nirasha Pooja
Rakhee Sharmila Vanessa Deshni Reshma Tshilidzi Mashudu Rendani Ndivhuwo Livhuwani Ntsako Hlamalani Tsakani Nyeleti
Rirhandzu Khensani Vutomi Nomthandazo Thuli Sizakele Xoliswa Noluthando Nosisa Babalwa Unathi Anathi Lisakhanya Ziyanda""".split()
SURNAMES = """Nkosi Dlamini Mokoena Ndlovu Khumalo Zulu Mthembu Ngcobo Shabalala Mahlangu Sithole Mkhize Cele Gumede Xaba
Mabaso Zungu Mbatha Ntuli Jali Makhaya Qwabe Molefe Motaung Mofokeng Letsoalo Sebola Masilo Modise Mothibi Phiri Tau Seleka
Botha Pretorius Venter Nel Coetzee Fourie Steyn Kruger Swanepoel Marais Joubert Smit Visser Bezuidenhout Smith Williams Jones
Brown Taylor Adams Wilson Naidoo Pillay Govender Reddy Moodley Chetty Singh Maharaj Padayachee Petersen Jacobs Hendricks Isaacs
Abrahams Davids Arendse Daniels Patel Khan Moosa Buthelezi Zwane Mhlongo Hadebe Majola Ngubane Msimang Nxumalo Ngema Kubheka
Mthethwa Biyela Shezi Mtshali Mavuso Mnguni Sibiya Masondo Mazibuko Radebe Hlongwane Mokwena Maluleke Baloyi Chauke Mathebula
Shirinda Ngobeni Rikhotso Nemavhola Ramavhunga Mudau Netshitenzhe Tshabalala Mogale Maseko Moloi Sekgobela Ramaphosa Mabuza
Moeketsi Lekota Ralebitso Nthite Mokhothu Thulo Lebona Mohapi Matsepe Mashaba Magagula Tshwane Makgoba Mphahlele Ledwaba
Moropane Kekana Ramokgopa Masemola Mokgadi Mabena Skosana Masango Mlambo Nhlapo Kunene Mdlalose Mncube Gwala Zuma Mabuyakhulu
Ndaba Mfeka Mkhwanazi Sokhela Gcabashe Vilakazi Mdletshe Ntanzi Mbele Hlophe Langa Mnisi Nyathi Ncube Moyo Dube Sibanda
Mpofu Gumbo Mutasa Chikwanha Mwale Banda Tembo Mbeki Sisulu Mxenge Qoboza Mqhayi Jabavu Matthews Grobler Erasmus Olivier
Lombard Theron Cronje Du Preez Engelbrecht Vermeulen Viljoen Jansen Snyman Louw Meyer Muller Schoeman Strydom Potgieter
Rossouw Wessels Hattingh Burger Barnard Pienaar Bosman Brink Conradie De Beer De Klerk De Villiers Du Plessis Du Toit
Ferreira Geldenhuys Gouws Human Jordaan Kotze Labuschagne Le Roux Liebenberg Lourens Malan Mostert Nieuwoudt Oosthuizen
Prinsloo Roux Scholtz Spies Steenkamp Terblanche Uys Van Aswegen Van Der Merwe Van Niekerk Van Rensburg Van Wyk Van Zyl
Vorster Wolmarans Cloete Adonis Fortuin Booysen Februarie Jacobus Jantjies Klaasen Lottering Ruiters Samuels Solomons
September Swartz Willemse Africa Plaatjies Gamieldien Salie Kamaar Hassiem Jaffer Kader Parker Ross Scott Stewart Thomson
Walker White Wright Young Allen Baker Bell Campbell Clarke Collins Cooper Edwards Evans Fisher Green Hall Harris Hill Hughes
Jackson Johnson King Lee Lewis Martin Mitchell Moore Morgan Murphy Nelson Phillips Roberts Robinson Rogers Turner Ward Watson
Naicker Moonsamy Ramsamy Pather Perumal Subramoney Govindsamy Rajah Ramdass Sewpersad Maharaj Bhana Desai Joshi Parbhoo
Dawood Ismail Mahomed Omar Suliman Bux Essop Cassim Laher Mayet Sacoor Vawda""".split()
SURNAMES = [s.replace("Van Der", "van der").replace("Van ", "van ").replace("De ", "de ").replace("Du ", "du ").replace("Le ", "le ")
            for s in " ".join(SURNAMES).replace("Du Preez", "Du_Preez").replace("De Beer", "De_Beer").replace("De Klerk", "De_Klerk")
            .replace("De Villiers", "De_Villiers").replace("Du Plessis", "Du_Plessis").replace("Du Toit", "Du_Toit").replace("Le Roux", "Le_Roux")
            .replace("Van Aswegen", "Van_Aswegen").replace("Van Der Merwe", "Van_Der_Merwe").replace("Van Niekerk", "Van_Niekerk")
            .replace("Van Rensburg", "Van_Rensburg").replace("Van Wyk", "Van_Wyk").replace("Van Zyl", "Van_Zyl").replace("_", " ").split(" ")]
# (the split above broke the multi-word surnames on spaces again; rebuild them)
_multi = ["du Preez", "de Beer", "de Klerk", "de Villiers", "du Plessis", "du Toit", "le Roux", "van Aswegen", "van der Merwe",
          "van Niekerk", "van Rensburg", "van Wyk", "van Zyl", "Janse van Rensburg", "van den Berg", "van Heerden", "van Staden",
          "de Jager", "de Wet", "le Grange", "van Tonder", "van der Walt"]
SURNAMES = [s for s in SURNAMES if s and s not in ("van", "der", "de", "du", "le", "Van", "Der", "De", "Du", "Le")
            and s[0].isupper()] + _multi

ONSETS_NGUNI = ["", "b", "bh", "d", "dl", "dz", "f", "g", "h", "hl", "j", "k", "kh", "l", "m", "mb", "mf", "mh", "mp", "mth",
                "n", "nd", "ndl", "ng", "nh", "nj", "nk", "nq", "ns", "nt", "nts", "ntsh", "nz", "ny", "p", "ph", "q", "s",
                "sh", "t", "th", "ts", "tsh", "v", "w", "x", "y", "z", "zw", "gc", "ngc", "kg", "ts", "tl", "r"]
VOWELS = ["a", "a", "a", "e", "e", "i", "i", "o", "o", "u", "u"]
AFR_ROOTS = ["Brand", "Berg", "Klop", "Vos", "Wol", "Rood", "Groen", "Kloot", "Hof", "Steen", "Vlok", "Bloem", "Kuyp", "Mey",
             "Oost", "West", "Nort", "Sny", "Wit", "Swart", "Hout", "Kemp", "Lamp", "Rens", "Stry", "Brits", "Ger", "Hay", "Gro"]
AFR_ENDS = ["er", "man", "berg", "ster", "se", "s", "en", "hof", "dal", "huis", "ing", "aar", "ert", "out", "ijn", "ie"]


def gen_word(rng: random.Random, syl: tuple[int, int] = (2, 4)) -> str:
    s = "".join(rng.choice(ONSETS_NGUNI) + rng.choice(VOWELS) for _ in range(rng.randint(*syl)))
    return s[0].upper() + s[1:]


def gen_surname(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.6:
        return gen_word(rng, (2, 4))
    if r < 0.85:
        w = rng.choice(AFR_ROOTS) + rng.choice(AFR_ENDS)
        return (rng.choice(["van ", "de ", "du ", "van der ", ""]) if rng.random() < 0.25 else "") + w
    return gen_word(rng, (2, 3)) + rng.choice(["son", "ley", "ton", "ford", "well", "by"])


# --------------------------------------------------------------------------- #
# Streets and issuers: word roots of many kinds, and generated ones
# --------------------------------------------------------------------------- #

STREET_ROOTS = """Acacia Protea Jacaranda Mimosa Disa Aloe Kiepersol Wattle Fig Mopani Bloekom Marula Baobab Yellowwood Stinkwood
Ironwood Wild Olive Karee Kameeldoring Witstinkhout Coral Tree Erica Fynbos Strelitzia Agapanthus Arum Clivia Freesia Gardenia
Hibiscus Lavender Magnolia Oleander Plumbago Rose Lily Daisy Jasmine Orchid Peach Plum Apricot Lemon Orange Pecan Walnut
Chestnut Cedar Cypress Pine Oak Elm Ash Willow Poplar Maple Palm Sunbird Hadeda Weaver Hornbill Kingfisher Heron Ibis Eagle
Falcon Kestrel Owl Robin Swallow Starling Hoopoe Lourie Flamingo Pelican Impala Kudu Eland Springbok Gemsbok Steenbok Duiker
Rhebok Nyala Bushbuck Zebra Buffalo Leopard Cheetah Jackal Meerkat Dassie Otter Pangolin Granite Quartz Marble Agate Jasper
Onyx Garnet Amber Silver Gold Copper Iron Diamond Ridge Hill Valley River Lake Bay Beach Harbour Dune Cliff Forest Meadow Spring
Fountain Kloof Vlei Rant Kop Berg Dal Rivier Bron Main Station Church Market Long Short High Low Park School Mill Bridge
Railway Mission Hospital Court Library College Factory Quarry Dam Canal Victoria Albert Queen King Prince Duke Regent Jubilee
Union Republic Freedom Liberty Unity Harmony Hope Faith Grace Mercy Pioneer Settler Trek Voortrekker Kerk Hoof Dorp Bree Loop
Kort Lang Nuwe Ou Mark Wes Oos Noord Suid Bosch Rand Heuwel Vallei Fontein Kruis Malan Smuts Hertzog Kruger Retief Uys Tambo
Sisulu Luthuli Biko Mandela Hani Sobukwe Mbeki Ngoyi Makeba Masekela Plaatje Tutu Mxenge Mhlaba Joseph Jabavu Dube Seme
Gandhi Naicker Dadoo Kathrada Moosa Albertina Charlotte Lilian Helen Ruth Beyers Naude Moshoeshoe Shaka Cetshwayo Dingane
Hintsa Sekhukhune Makhado Mampuru Langalibalele Dinuzulu Sandile Maqoma Ntsikana Umgeni Umbilo Umlazi Tugela Pongola Vaal
Orange Limpopo Olifants Crocodile Sabie Komati Gamtoos Breede Berg Kowie Keiskamma Buffels Mooi Klip Sand Modder Riet Hartbees
Swartkops Kromme Bot Palmiet Liesbeek Black Salt Doring Groot Klein Cradock Somerset Graaff Grahamstown Durban Natal Eastern
Western Northern Southern Central Coastal Marine Ocean Sea Shore Point Lighthouse Anchor Tide Coral Shell Reef Wave""".split()
STREET_SUFFIXES = (["Street"] * 18 + ["Road"] * 14 + ["Avenue"] * 10 + ["Drive"] * 7 + ["Crescent"] * 6 + ["Lane"] * 5 + ["Close"] * 5
                   + ["Way"] * 4 + ["Place"] * 3 + ["Boulevard"] * 2 + ["Terrace"] * 2 + ["Circle"] * 2 + ["Court"] * 2
                   + ["Rylaan", "Straat", "Weg", "Laan", "Singel", "Grove", "Walk", "Row", "Square", "Highway", "Loop", "Link"])
ABBREV = {"Road": "Rd", "Street": "St", "Avenue": "Ave", "Drive": "Dr", "Crescent": "Cres", "Lane": "Ln", "Close": "Cl",
          "Place": "Pl", "Boulevard": "Blvd", "Terrace": "Tce", "Court": "Ct", "Highway": "Hwy"}
COMPLEXES = """Silver Oaks|Protea Gardens|Sunset Villas|Riverside Estate|Acacia Court|Park Mews|Oak Ridge|The Willows|Ocean View|
Hillcrest Manor|Fountain Square|Golden Gate|Mountain View|Palm Grove|Seaview Heights|Jacaranda Park|Eagle Nest|Sunbird Close|
Harbour Lights|Kingfisher Place|Marula Lodge|Bushveld Estate|Vineyard Court|Bluegum Village|Lakeside|Highlands|Fernwood|
Rosewood|Cedar Lodge|Ivy House""".replace("\n", "").split("|")
BIZ_ROOTS = """Lumo Kwanda Amandla Ithemba Lesedi Pula Kopano Tirelo Masedi Bophelo Thuso Kgotso Imbali Ilanga Inkanyezi Isibane
Umthombo Umzila Zenzele Vukani Siyakha Phakama Akhona Sakhisizwe Masiphile Tsela Leseli Botho Bokamoso Tshwaragano Nala Moya
Karoo Highveld Lowveld Bushveld Drakensberg Boland Overberg Kalahari Namaqua Zululand Transkei Garden Route Wild Coast
Southern Cross Blue Crane Fish Eagle Baobab Protea Aloe Sunbird Springbok Kudu Impala Granite Summit Horizon Meridian Pinnacle
Keystone Cornerstone Beacon Compass Harbour Anchor Lighthouse Frontier Pioneer Heritage Legacy Unity Liberty Vista Crest Apex
Sterling Capital Union Trust Alliance Premier Prime First Metro Coastal Inland National Continental Atlas Orion Nova Zenith""".split()
BIZ_KIND = {
    "utility_bill": ["Power", "Energy", "Utilities", "Electricity", "Water", "Water Board", "Gas", "Solar", "Light and Power", "Water Services"],
    "bank_statement": ["Bank", "Savings Bank", "Mutual Bank", "Community Bank", "Bank Limited", "Finance", "Building Society", "Co-operative Bank"],
    "cellphone_account": ["Mobile", "Telecom", "Wireless", "Networks", "Connect", "Fibre", "Broadband", "Internet", "Comms"],
    "lease_agreement": ["Property Rentals", "Estates", "Property Management", "Letting Agents", "Realty", "Homes", "Properties", "Rentals"],
    "insurance_statement": ["Assurance", "Insure", "Mutual", "Life", "Insurance", "Cover", "Underwriters", "Risk"],
    "store_account": ["Stores", "Retail", "Furnishers", "Outfitters", "Clothing", "Home Store", "Trading"],
}
TOWN_WORDS = ["Local Municipality", "Municipality", "Metropolitan Municipality", "District Municipality"]


# --------------------------------------------------------------------------- #
# Places: the gazetteer docscan ships (GeoNames), a suburb with a nearby town
# --------------------------------------------------------------------------- #

def load_places() -> list[tuple[str, str, str]]:
    rows = []
    for line in TSV.read_text().splitlines():
        if line.startswith("#"):
            continue
        code, place, prov = line.split("\t")
        rows.append((code, place, prov))
    return rows


# Metros and big towns and the street-code ranges of their suburbs (SAPO's
# regional numbering: Pretoria 00-01xx, Johannesburg 20-21xx, ...).
CITIES = [("Pretoria", 1, 199), ("Johannesburg", 2000, 2199), ("Cape Town", 7400, 8099), ("Durban", 4000, 4099),
          ("Gqeberha", 6000, 6099), ("East London", 5200, 5299), ("Bloemfontein", 9300, 9399), ("Pietermaritzburg", 3200, 3209),
          ("Polokwane", 699, 760), ("Mbombela", 1200, 1209), ("Kimberley", 8300, 8309), ("Soweto", 1800, 1899),
          ("Ekurhuleni", 1400, 1699), ("Centurion", 140, 170)]


def build_places(split: str) -> list[tuple[str | None, str, str, str]]:
    rows = [r for r in load_places() if held_out(r[1]) == (split == "devg") and not S.forbidden_in(r[1])]
    out = []
    for code, place, prov in rows:
        if len(place) > 26 or not re.match(r"^[A-Za-z][A-Za-z '\-]+$", place):
            continue
        n = int(code)
        city = next((c for c, lo, hi in CITIES if lo <= n <= hi and c.lower() != place.lower()), None)
        if city and hash_pick("s" + place, 10) < 8:
            out.append((place, city, prov, code))
        else:
            out.append((None, place, prov, code))
    # About half the addresses print a suburb, as poa_synth's do.
    return out + [x for x in out if x[0]] * 4


def hash_pick(s: str, n: int) -> int:
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:4], "big") % n


# --------------------------------------------------------------------------- #
# Fonts (variable fonts drawn at weight 400 and 700)
# --------------------------------------------------------------------------- #

DEVG_FONTS = ("SourceSerif4", "Manrope", "Bitter", "CourierPrime", "Asap")


def wide_fonts(split: str) -> dict[str, tuple[str, str]]:
    fonts = {}
    for f in sorted(FONT_DIR.glob("*.ttf")):
        name = f.stem
        if any(name.startswith(x) for x in LOCKBOX_FONTS):
            continue
        fam = name.replace("-VF", "").replace("-Regular", "").replace("-Bold", "")
        if (fam in DEVG_FONTS) != (split == "devg"):
            continue
        if name.endswith("-VF"):
            fonts[fam] = (f"{f}#400", f"{f}#700")
        elif name.endswith("-Regular") and (FONT_DIR / f"{fam}-Bold.ttf").exists():
            fonts[fam] = (str(f), str(FONT_DIR / f"{fam}-Bold.ttf"))
    if split == "train":
        fonts.update({k: v for k, v in S.FONTS.items()})
    return fonts


_orig_load_font = S.load_font


def _set_weight(f: ImageFont.FreeTypeFont, wght: float) -> None:
    axes = f.get_variation_axes()
    vals = []
    for a in axes:
        nm = a.get("name")
        nm = nm.decode() if isinstance(nm, bytes) else str(nm)
        vals.append(max(a["minimum"], min(a["maximum"], wght)) if "eight" in nm or nm.lower() == "wght" else a["default"])
    f.set_variation_by_axes(vals)


@lru_cache(maxsize=None)
def load_font2(path: str, size: int) -> ImageFont.FreeTypeFont:
    if "#" not in path:
        return _orig_load_font(path, size)
    file, wght = path.split("#")
    f = ImageFont.truetype(file, size, layout_engine=ImageFont.Layout.BASIC)
    try:
        _set_weight(f, float(wght))
    except OSError:
        pass
    return f


# --------------------------------------------------------------------------- #
# Wider values
# --------------------------------------------------------------------------- #

def install(split: str) -> None:
    """Swaps poa_synth's pools for the wide ones of `split`."""
    S.load_font = load_font2
    S.FIRST_M = split_pool(FIRST_M, split)
    S.FIRST_F = split_pool(FIRST_F, split)
    S.SURNAMES = split_pool(SURNAMES, split)
    S.PLACES = build_places(split)
    S.STREETS = []  # make_street is replaced
    S.ROOTS = split_pool(BIZ_ROOTS, split)
    S.MUNI_PLACES = [p for _, p, _, _ in S.PLACES if " " not in p][:400]
    S.FONTS.clear()
    S.FONTS.update(wide_fonts(split))
    globals()["SPLIT"] = split
    S.make_person = make_person
    S.make_street = make_street
    S.make_issuer = make_issuer
    S.make_doc = make_doc
    S.SMALL_PRINT = S.SMALL_PRINT  # unchanged


SPLIT = "train"


def first_name(rng: random.Random, female: bool) -> str:
    if rng.random() < 0.35:
        n = gen_word(rng, (2, 4))
        if not held_out(n) == (SPLIT == "devg"):
            n = gen_word(rng, (2, 4))
        return n
    return rng.choice(S.FIRST_F if female else S.FIRST_M)


def surname(rng: random.Random) -> str:
    if rng.random() < 0.4:
        for _ in range(5):
            s = gen_surname(rng)
            if held_out(s) == (SPLIT == "devg") and not S.forbidden_in(s):
                return s
    return rng.choice(S.SURNAMES)


def make_person(rng: random.Random) -> dict:
    female = rng.random() < 0.5
    first = first_name(rng, female)
    sn = surname(rng)
    mid = rng.choice("ABCDEGHJKLMNPRSTVWZ")
    r = rng.random()
    title = "Dr" if r < 0.05 else ("Prof" if r < 0.06 else ("Adv" if r < 0.07 else ("Mr" if not female else rng.choice(["Ms", "Mrs", "Mrs", "Miss"]))))
    style = rng.choices(["title_full", "title_init", "init_dot", "full_mid", "couple", "title_inits", "full", "sur_first", "two_given", "sur_comma_full"],
                        [16, 20, 9, 11, 5, 11, 15, 5, 6, 2])[0]
    upper = rng.random() < 0.4
    sal = f"{title} {sn[0].upper() + sn[1:]}"
    second = first_name(rng, female)
    if style == "title_full":
        name = f"{title} {first} {sn}"
    elif style == "title_init":
        name = f"{title} {first[0]}{'.' if rng.random() < 0.3 else ''} {sn}"
    elif style == "init_dot":
        name = f"{first[0]}. {sn}" if rng.random() < 0.6 else f"{first[0]}.{mid}. {sn}"
    elif style == "full_mid":
        name = f"{first} {mid} {sn}"
    elif style == "couple":
        other = first_name(rng, not female)[0]
        name = rng.choice([f"Mr & Mrs {other if female else first[0]} {sn}", f"{first} & {first_name(rng, not female)} {sn}",
                           f"Mr {first[0]} & Mrs {other} {sn}"])
        sal = f"Mr and Mrs {sn[0].upper() + sn[1:]}"
    elif style == "title_inits":
        name = f"{title} {first[0]}{mid} {sn}"
        upper = upper or rng.random() < 0.5
    elif style == "sur_first":
        name = f"{sn}, {first[0]}{mid}"
    elif style == "two_given":
        name = f"{first} {second} {sn}"
    else:
        name = f"{sn}, {first}"
    name = name.upper() if upper else name
    # The forenames as the holder's ID gives them: the second one printed in full, or its initial.
    middle = second if style == "two_given" else mid
    return {"first": first, "middle": middle, "surname": sn, "title": title, "printed": name, "salutation": sal}


def street_root(rng: random.Random) -> str:
    for _ in range(6):
        r = rng.random()
        if r < 0.55:
            w = rng.choice(STREET_ROOTS)
        elif r < 0.8:
            w = gen_word(rng, (2, 4))
        elif r < 0.9:
            w = f"{rng.choice(STREET_ROOTS)} {rng.choice(STREET_ROOTS)}"
        else:
            w = f"{first_name(rng, rng.random() < 0.5)} {surname(rng)}"
        if held_out(w) == (SPLIT == "devg") and not S.forbidden_in(w):
            return w
    return w


def make_street(rng: random.Random) -> str:
    num = str(rng.choices([rng.randint(1, 99), rng.randint(100, 999), rng.randint(1000, 9999)], [55, 38, 7])[0])
    if rng.random() < 0.07:
        num += rng.choice("ABCD")
    sfx = rng.choice(STREET_SUFFIXES)
    st = f"{street_root(rng)} {sfx}"
    if rng.random() < 0.3 and sfx in ABBREV:
        st = st[: -len(sfx)] + ABBREV[sfx]
    if rng.random() < 0.05:
        st = f"{rng.choice(['Upper', 'Lower', 'Old', 'New', 'North', 'South', 'East', 'West'])} {st}"
    return f"{num} {st}"


def make_issuer(rng: random.Random, dtype: str) -> dict:
    while True:
        if dtype == "municipal_account":
            p = rng.choice(S.MUNI_PLACES)
            name = rng.choice([f"{p} {rng.choice(TOWN_WORDS)}", f"City of {p}", f"{p} Municipality", f"Greater {p} Municipality"])
            legal = name
        else:
            r = rng.random()
            root = rng.choice(S.ROOTS) if r < 0.6 else gen_word(rng, (2, 3)) if r < 0.85 else f"{rng.choice(S.ROOTS)} {rng.choice(S.ROOTS)}"
            name = f"{root} {rng.choice(BIZ_KIND[dtype])}"
            legal = name + rng.choice([" (Pty) Ltd", " Limited", " Ltd", " (RF) (Pty) Ltd", " Inc", " NPC", ""])
        if not S.forbidden_in(name) and len(name) < 40:
            break
    words = [w for w in re.split(r"[\s&-]+", name) if w and w[0].isupper() and w not in ("City", "of", "Greater")]
    initials = "".join(w[0] for w in words[:rng.choice([2, 2, 3])]) or name[:2].upper()
    site = re.sub(r"[^a-z]", "", name.lower().replace("municipality", "").replace("local", "").replace("metropolitan", ""))[:18]
    tld = rng.choice([".co.za", ".co.za", ".com", ".org.za", ".net"]) if dtype != "municipal_account" else ".gov.za"
    return {
        "name": name, "legal": legal, "initials": initials, "colour": rng.choice(S.COLOURS + [(rng.randint(0, 200), rng.randint(0, 200), rng.randint(0, 200))]),
        "shape": rng.choice(["circle", "square", "triangle", "diamond", "rings", "bars"]),
        "tagline": rng.choice(S.TAGLINE.get(dtype, S.TAGLINE["utility_bill"])), "tel": S.phone(rng), "fax": S.phone(rng),
        "vat": "4" + S.digits(rng, 9, False), "reg": f"{rng.randint(1965, 2023)}/{S.digits(rng, 6, False)}/{rng.choice(['06', '07', '07', '08', '10', '21'])}",
        "web": f"www.{site}{tld}", "email": f"{rng.choice(['accounts', 'info', 'help', 'service', 'queries', 'billing'])}@{site}{tld}",
    }


_orig_make_doc = S.make_doc


def make_doc(rng: random.Random, layout: str, today: dt.date, doc_id: str, dtype: str | None = None) -> dict:
    doc = _orig_make_doc(rng, layout, today, doc_id, dtype)
    # A unit in a complex, on a line of its own above the street (not part of the street field).
    doc["complex"] = (f"{rng.choice(['Unit', 'Flat', 'No.', 'Door'])} {rng.randint(1, 120)} {rng.choice(COMPLEXES)}"
                      if rng.random() < 0.12 else None)
    return doc


# --------------------------------------------------------------------------- #
# New layout families
# --------------------------------------------------------------------------- #

INK, GREY, LIGHT = S.INK, S.GREY, S.LIGHT


def id_number(rng: random.Random) -> str:
    return S.digits(rng, 13)


def letterhead(p: S.Page, doc: dict, *, centre: bool, decoy: bool) -> float:
    rng, iss, W = p.rng, doc["issuer"], p.w
    c = iss["colour"]
    x0, x1 = 100 + S.J(p, 15), W - 100 + S.J(p, 15)
    y = 50 + S.J(p, 10)
    if centre:
        S.logo(p, W / 2 - 35, y, 70, doc)
        y += 82
        p.text(W / 2, y, [(iss["name"], "ISSUER")], p.f(rng.uniform(26, 34), True), c, anchor="c")
        y += 46
        lines = []
        if decoy:
            a = S.decoy_address(rng, doc["addr"], rng.choice(["head_office", "branch", "postal"]))
            doc["decoys"].append(a)
            lines, _ = S.address_lines(a, rng, labelled=False, single=True, upper=False)
            p.text(W / 2, y, lines[0], p.f(14), GREY, anchor="c")
            y += 22
        p.text(W / 2, y, f"Tel {iss['tel']}  |  {iss['email']}  |  {iss['web']}", p.f(14), GREY, anchor="c")
        y += 30
    else:
        S.logo(p, x0, y, 64, doc)
        p.text(x0 + 80, y + 6, [(iss["name"], "ISSUER")], p.f(rng.uniform(24, 32), True), c)
        p.text(x0 + 80, y + 44, iss["tagline"], p.f(14), GREY)
        yy = y
        f = p.f(13)
        if decoy:
            a = S.decoy_address(rng, doc["addr"], rng.choice(["head_office", "branch", "postal"]))
            doc["decoys"].append(a)
            lines, _ = S.address_lines(a, rng, labelled=False, single=False, upper=False)
            for ln in lines:
                p.text(x1, yy, ln, f, GREY, anchor="r")
                yy += 19
        for t in (f"Tel {iss['tel']}", iss["web"]):
            p.text(x1, yy, t, f, GREY, anchor="r")
            yy += 19
        y = max(y + 80, yy + 10)
    p.rule(x0, y, x1, c, rng.choice([1, 2, 3]))
    return y + 30


def addr_block_lines(doc: dict, rng: random.Random, *, single=False, upper=None) -> list[list]:
    lines, printed = S.address_lines(doc["addr"], rng, labelled=True, single=single, upper=upper)
    doc["province_printed"] |= printed
    if doc.get("complex") and not single:
        lines = [[doc["complex"]]] + lines
    return lines


def signature(p: S.Page, doc: dict, x, y, f) -> float:
    rng = p.rng
    agent = S.other_person(rng, doc)
    p.rule(x, y, x + 300, INK)
    y += 8
    p.text(x, y, f"{agent['first']} {agent['surname']}", f, INK)
    y += p.lh(f)
    p.text(x, y, rng.choice(["Branch Manager", "Customer Service Consultant", "Accounts Administrator", "Client Relations Officer",
                             "Operations Supervisor", "Senior Clerk", "Authorised Signatory"]), f, GREY)
    y += p.lh(f)
    if rng.random() < 0.6:
        # The branch's own place and code: a decoy the tagger must not take.
        a = S.decoy_address(rng, doc["addr"], "branch")
        doc["decoys"].append(a)
        lines, _ = S.address_lines(a, rng, labelled=False, single=True, upper=False)
        p.text(x, y, [rng.choice(["Branch: ", "Office: ", ""])] + lines[0], p.f(f.size * 0.9), GREY)
        y += p.lh(f)
    return y


def merge_punct(parts: list) -> list:
    merged = []
    for part in parts:
        if isinstance(part, str) and part.startswith((".", ",", ")")) and merged and not isinstance(merged[-1], str):
            merged[-1] = (merged[-1][0] + part[0], merged[-1][1])
            part = part[1:].strip()
            if not part:
                continue
        merged.append(part)
    return merged


def body_table(p: S.Page, doc: dict, x0, x1, y, *, headers=("Description", "Qty", "Amount"), head_fill=None, shade=None) -> float:
    """The page's body: charges and totals, or a bank statement's transactions."""
    rng = p.rng
    tf, tfb = p.f(15), p.f(15, True)
    if doc["type"] == "bank_statement":
        tx = S.transactions(rng, doc, rng.randint(5, 12))
        trs = [[S.D(doc, d), desc, S.money(amt, doc["money_style"])] for d, desc, amt in tx]
        return S.table(p, x0, y, x1 - x0, ["Date", "Description", "Amount"], trs, [0.2, 0.55, 0.25], "llr", tf, tfb,
                       head_fill=head_fill, head_ink=INK, shade=shade, grid=(228, 228, 232)) + 20
    rows_, raw = S.charge_rows(p, doc, rng.randint(3, 7), with_prev=doc["type"] != "insurance_statement")
    y = S.table(p, x0, y, x1 - x0, list(headers), rows_, [0.6, 0.15, 0.25], "lrr", tf, tfb,
                head_fill=head_fill, head_ink=INK, shade=shade, grid=(225, 225, 230)) + 20
    return S.totals(p, x1 - 10, y, doc, raw, tf, tfb, label_x=x1 - 420) + 20


def lay_w_letter(p: S.Page, doc: dict) -> None:
    """A confirmation-of-address letter: the holder named in a sentence."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    y = letterhead(p, doc, centre=rng.random() < 0.5, decoy=doc["decoy"])
    x0, x1 = 110 + S.J(p, 10), W - 110
    f, fb = p.f(rng.uniform(17, 20)), p.f(rng.uniform(17, 20), True)
    lh = p.lh(f, rng.uniform(1.35, 1.6))
    dl = rng.choice(["Date: ", "", "Date issued: "])
    right = rng.random() < 0.5
    p.text(x1 if right else x0, y, [dl, (S.D(doc, doc["date"]), "DOC_DATE")], f, INK, anchor="r" if right else "l")
    y += lh * 1.5
    if rng.random() < 0.5:
        p.text(x0, y, ["Our ref: ", (doc["acc"], "ACCOUNT_NO")], f, GREY)
        acc_done = True
        y += lh * 1.5
    else:
        acc_done = False
    if rng.random() < 0.65:
        p.text(x0, y, rng.choice(["TO WHOM IT MAY CONCERN", "To whom it may concern", "Dear Sir / Madam", "Dear Sir/Madam",
                                  "TO WHOM IT MAY CONCERN:"]), fb if rng.random() < 0.6 else f)
        y += lh * 1.6
    p.text(x0, y, rng.choice(["RE: CONFIRMATION OF ADDRESS", "CONFIRMATION OF RESIDENTIAL ADDRESS", "PROOF OF ADDRESS",
                              "RE: CONFIRMATION OF ACCOUNT AND ADDRESS", "Confirmation of residence", "ACCOUNT CONFIRMATION"]), fb)
    y += lh * 1.5
    name = (doc["person"]["printed"], "HOLDER_NAME")
    idn = f"(ID number {id_number(rng)})" if rng.random() < 0.5 else ""
    acc = [] if acc_done else [", account number", (doc["acc"], "ACCOUNT_NO") if True else "", ","]
    opener = rng.choice(["This letter serves to confirm that", "We hereby confirm that", "This is to confirm that",
                         "Please be advised that", "We confirm that"])
    holds = rng.choice([["is a client of", (iss["name"], "ISSUER")], ["holds an account with", (iss["name"], "ISSUER")],
                        ["is a customer of", (iss["name"], "ISSUER")], ["has been a client of ours since", str(rng.randint(1998, 2024))]])
    inline = rng.random() < 0.5
    lines = addr_block_lines(doc, rng, single=inline)
    if inline:
        sent = [opener, name] + ([idn] if idn else []) + holds + acc + [rng.choice(["and resides at", "and that the residential address on our records is",
                                                                                    "residing at", "whose physical address is"])] + lines[0] + ["."]
        y = p.flow(x0, y, x1 - x0, merge_punct(sent), f, INK, lh) + lh * 0.7
    else:
        sent = [opener, name] + ([idn] if idn else []) + holds + acc + [rng.choice(["and that the residential address on record is:",
                                                                                    "and resides at the following address:",
                                                                                    "The address on our records is:"])]
        y = p.flow(x0, y, x1 - x0, merge_punct(sent), f, INK, lh) + lh * 0.4
        ix = x0 + rng.choice([0, 40, 80])
        for ln in lines:
            p.text(ix, y, ln, f, INK)
            y += lh
        y += lh * 0.5
    y = p.flow(x0, y, x1 - x0, [rng.choice([
        "This confirmation is issued at the request of the client and without any liability on the part of the company or its officials.",
        "Should you require any further information, please do not hesitate to contact our offices during business hours.",
        "This letter is valid for three months from the date of issue.",
        "The information above is correct according to our records as at the date of this letter."])], f, INK, lh) + lh
    p.text(x0, y, rng.choice(["Yours faithfully", "Kind regards", "Sincerely", "Yours sincerely"]), f)
    y = signature(p, doc, x0, y + lh * 2.6, p.f(16)) + lh
    S.small_print(p, x0, max(y, H - 260), x1 - x0, H - 100, doc, 12, 1)
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=False, centre=True)


def lay_w_certify(p: S.Page, doc: dict) -> None:
    """DEV-G only: a certificate-style confirmation, the holder in a table and a sentence."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    y = letterhead(p, doc, centre=rng.random() < 0.6, decoy=doc["decoy"])
    x0, x1 = 120, W - 120
    f, fb = p.f(rng.uniform(16, 19)), p.f(rng.uniform(16, 19), True)
    lh = p.lh(f, 1.5)
    p.text(W / 2, y, rng.choice(["CERTIFICATE OF RESIDENCE", "ADDRESS VERIFICATION", "CONFIRMATION OF PHYSICAL ADDRESS"]), p.f(24, True), INK, anchor="c")
    y += lh * 2
    if rng.random() < 0.6:
        p.text(x0, y, rng.choice(["To whom it may concern", "TO WHOM IT MAY CONCERN"]), f)
        y += lh * 1.5
    y = p.flow(x0, y, x1 - x0, merge_punct([rng.choice(["It is hereby certified that the person named below", "We certify that the person below"]),
                                            "is known to", (iss["name"], "ISSUER"), rng.choice(["and resides at the address given.", "as a customer at the address shown."])]),
               f, INK, lh) + lh * 0.6
    rows = [("Full name", [(doc["person"]["printed"], "HOLDER_NAME")]), ("Identity number", id_number(rng)),
            ("Customer number", [(doc["acc"], "ACCOUNT_NO")])]
    lines = addr_block_lines(doc, rng, single=rng.random() < 0.4)
    lx, vx = x0 + 20, x0 + 300
    for lab, val in rows:
        p.text(lx, y, lab, f, GREY)
        p.text(vx, y, val, fb, INK)
        y += lh * 1.2
    p.text(lx, y, rng.choice(["Residential address", "Physical address", "Address"]), f, GREY)
    for ln in lines:
        p.text(vx, y, ln, fb, INK)
        y += lh
    y += lh * 0.5
    p.text(lx, y, "Date of issue", f, GREY)
    p.text(vx, y, [(S.D(doc, doc["date"]), "DOC_DATE")], fb, INK)
    y += lh * 2
    y = p.flow(x0, y, x1 - x0, ["Issued without prejudice and solely for the purpose of confirming the residential address of the person named above."], f, INK, lh) + lh
    y = signature(p, doc, x0, y + lh * 2, p.f(15))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"], centre=True)


def lay_w_window(p: S.Page, doc: dict) -> None:
    """A window-envelope page: a small return address above the holder's block."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 80 + S.J(p, 15), W - 80
    top = 50 + S.J(p, 10)
    right_logo = rng.random() < 0.5
    S.logo(p, x1 - 70 if right_logo else x0, top, 70, doc)
    p.text(x1 - 80 if right_logo else x0 + 85, top + 10, [(iss["name"], "ISSUER")], p.f(rng.uniform(22, 30), True), c, anchor="r" if right_logo else "l")
    title = rng.choice(["TAX INVOICE", "STATEMENT", "ACCOUNT STATEMENT", "MONTHLY STATEMENT", "INVOICE"])
    p.text(x1 if not right_logo else x0, top + 90, title, p.f(26, True), INK, anchor="r" if not right_logo else "l")
    # The envelope window: a return address in small print, then the holder.
    wy = 230 + S.J(p, 20)
    wx = x0 + rng.choice([0, 20, 50])
    a = S.decoy_address(rng, doc["addr"], rng.choice(["postal", "head_office"]))
    doc["decoys"].append(a)
    rl, _ = S.address_lines(a, rng, labelled=False, single=True, upper=rng.random() < 0.4)
    p.text(wx, wy, [rng.choice(["If undelivered return to: ", "Return address: ", ""]), iss["name"] + ", "] + rl[0], p.f(11), GREY)
    p.rule(wx, wy + 18, wx + 480, LIGHT)
    y = wy + 32
    f, fb = p.f(rng.uniform(17, 20)), p.f(rng.uniform(17, 20), rng.random() < 0.6)
    lh = p.lh(f, 1.3)
    p.text(wx, y, [(doc["person"]["printed"], "HOLDER_NAME")], fb, INK)
    y += lh
    for ln in addr_block_lines(doc, rng):
        p.text(wx, y, ln, f, INK)
        y += lh
    # Details at the right.
    kf, vf = p.f(15), p.f(15, True)
    rows = [(rng.choice(["Account number", "Account no.", "Customer no.", "Reference"]), [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Invoice date", "Statement date", "Date", "Issue date"]), [(S.D(doc, doc["date"]), "DOC_DATE")])]
    if doc["period"]:
        rows.append((rng.choice(["Period", "Billing period", "For the period"]), S.period_parts(doc)))
    rows.append(("Due date", S.D(doc, doc["due"])))
    S.kv_rows(p, x1 - 520, wy, rows, kf, vf, right=x1)
    y = max(y, wy + 4 * 30) + 40
    if rng.random() < 0.6:
        p.text(x0, y, ["Dear ", (doc["person"]["salutation"], "HOLDER_NAME"), ","], f)
        y += lh * 1.5
    y = body_table(p, doc, x0, x1, y, head_fill=S.tint(c, 0.2))
    y = S.small_print(p, x0, y, x1 - x0, H - 150, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"])


def lay_w_kv(p: S.Page, doc: dict) -> None:
    """Everything as label: value rows, the address a multi-line value; a postal address as decoy."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70 + S.J(p, 15), W - 70
    band = rng.random() < 0.5
    if band:
        p.d.rectangle((0, 0, W, 130), fill=c)
        p.text(x0, 40, [(iss["name"], "ISSUER")], p.f(30, True), S.WHITE)
        p.text(x1, 50, rng.choice(["Statement of account", "Tax invoice", "Account summary"]), p.f(20), S.WHITE, anchor="r")
        y = 170
    else:
        y = letterhead(p, doc, centre=False, decoy=doc["decoy"])
    lf, vf = p.f(rng.uniform(14, 17)), p.f(rng.uniform(15, 18), rng.random() < 0.5)
    lh = p.lh(vf, 1.35)
    colon = rng.random() < 0.6
    vx = x0 + rng.choice([200, 230, 260])
    cols2 = rng.random() < 0.5
    rows = [(rng.choice(["Account name", "Customer name", "Name", "Account holder", "Client"]), [(doc["person"]["printed"], "HOLDER_NAME")])]
    if rng.random() < 0.4:
        rows.append(("ID number", id_number(rng)))
    rows.append((rng.choice(["Account number", "Customer number", "Account no", "Contract number"]), [(doc["acc"], "ACCOUNT_NO")]))
    others = [(rng.choice(["Statement date", "Invoice date", "Date", "Date printed"]), [(S.D(doc, doc["date"]), "DOC_DATE")])]
    if doc["period"]:
        others.append((rng.choice(["Period", "Statement period", "Billing period"]), S.period_parts(doc)))
    others.append(("Due date", S.D(doc, doc["due"])))
    others.append(("Amount due", S.money(rng.randint(10000, 900000), doc["money_style"])))
    if not cols2:
        rows += others
    sfx = ":" if colon else ""
    y0 = y
    for lab, val in rows:
        p.text(x0, y, lab + sfx, lf, GREY)
        p.text(vx, y, val, vf, INK)
        y += lh
    addr_label = rng.choice(["Physical address", "Service address", "Residential address", "Supply address", "Address", "Premises"])
    p.text(x0, y, addr_label + sfx, lf, GREY)
    for ln in addr_block_lines(doc, rng, single=rng.random() < 0.3):
        p.text(vx, y, ln, vf, INK)
        y += lh
    if rng.random() < 0.55:
        # A postal address of the holder's: another place; a decoy (not the street address).
        a = S.decoy_address(rng, doc["addr"], "postal")
        doc["decoys"].append(a)
        p.text(x0, y, "Postal address" + sfx, lf, GREY)
        for ln in S.address_lines(a, rng, labelled=False)[0]:
            p.text(vx, y, ln, vf, INK)
            y += lh
    if cols2:
        yy = y0
        for lab, val in others:
            p.text(W / 2 + 60, yy, lab + sfx, lf, GREY)
            p.text(x1, yy, val, vf, INK, anchor="r")
            yy += lh
        y = max(y, yy)
    y += 30
    y = body_table(p, doc, x0, x1, y, head_fill=S.tint(c, 0.2))
    y = S.small_print(p, x0, y, x1 - x0, H - 140, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"] and not band)


def lay_w_branch(p: S.Page, doc: dict) -> None:
    """DEV-G only: a statement whose header carries a branch's address and contact person."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    S.logo(p, x0, 50, 60, doc)
    p.text(x0 + 75, 58, [(iss["name"], "ISSUER")], p.f(28, True), c)
    p.text(x1, 58, rng.choice(["Account statement", "Statement", "Account summary"]), p.f(22, True), INK, anchor="r")
    y = 140
    bf = p.f(14)
    a = S.decoy_address(rng, doc["addr"], "branch")
    doc["decoys"].append(a)
    agent = S.other_person(rng, doc)
    bx = W / 2 + rng.choice([-40, 40, 100])
    p.text(bx, y, rng.choice(["Your branch", "Branch details", "Store", "Service centre"]), p.f(14, True), GREY)
    by = y + 22
    p.text(bx, by, f"{rng.choice(['Consultant', 'Manager', 'Contact'])}: {agent['first']} {agent['surname']}", bf, GREY)
    by += 20
    for ln in S.address_lines(a, rng, labelled=False, upper=False)[0]:
        p.text(bx, by, ln, bf, GREY)
        by += 20
    p.text(bx, by, f"Tel {iss['tel']}", bf, GREY)
    f, fb = p.f(18), p.f(18, True)
    lh = p.lh(f, 1.3)
    hy = y + rng.choice([0, 20, 60])
    p.text(x0, hy, [(doc["person"]["printed"], "HOLDER_NAME")], fb, INK)
    hy += lh
    for ln in addr_block_lines(doc, rng):
        p.text(x0, hy, ln, f, INK)
        hy += lh
    y = max(hy, by) + 40
    kf, vf = p.f(15), p.f(15, True)
    rows = [("Account number", [(doc["acc"], "ACCOUNT_NO")]), ("Statement date", [(S.D(doc, doc["date"]), "DOC_DATE")])]
    if doc["period"]:
        rows.append(("Statement period", S.period_parts(doc)))
    y = S.kv_rows(p, x0, y, rows, kf, vf, val_x=x0 + 220) + 20
    tx = S.transactions(rng, doc, rng.randint(6, 14))
    tf, tfb = p.f(14), p.f(14, True)
    trs = [[S.D(doc, d), desc, S.money(amt, doc["money_style"])] for d, desc, amt in tx]
    y = S.table(p, x0, y, x1 - x0, ["Date", "Description", "Amount"], trs, [0.2, 0.55, 0.25], "llr", tf, tfb,
                head_fill=S.tint(c, 0.2), head_ink=INK, grid=(228, 228, 232)) + 20
    y = S.small_print(p, x0, y, x1 - x0, H - 140, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"])


def lay_w_panel(p: S.Page, doc: dict) -> None:
    """The holder in a shaded right-hand panel; the issuer's details on the left."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    y = 60
    p.text(x0, y, [(iss["name"], "ISSUER")], p.f(rng.uniform(26, 34), True), c)
    y += 50
    f = p.f(14)
    if doc["decoy"]:
        a = S.decoy_address(rng, doc["addr"], rng.choice(["head_office", "postal", "branch"]))
        doc["decoys"].append(a)
        for ln in S.address_lines(a, rng, labelled=False, upper=False)[0]:
            p.text(x0, y, ln, f, GREY)
            y += 20
    for t in (f"Tel {iss['tel']}", f"VAT No {iss['vat']}", iss["email"]):
        p.text(x0, y, t, f, GREY)
        y += 20
    px = W / 2 + rng.choice([20, 60, 100])
    py = 100 + S.J(p, 20)
    hf, hfb = p.f(17), p.f(17, True)
    lh = p.lh(hf, 1.3)
    lines = addr_block_lines(doc, rng)
    ph = lh * (len(lines) + 2) + 30
    p.d.rounded_rectangle((px - 20, py - 15, x1 + 10, py + ph), radius=8, fill=S.tint(c, 0.1))
    if rng.random() < 0.6:
        p.text(px, py, rng.choice(["Account holder", "Customer", "Billed to", "Statement for"]), p.f(13, True), GREY)
        py += 24
    p.text(px, py, [(doc["person"]["printed"], "HOLDER_NAME")], hfb, INK)
    py += lh
    for ln in lines:
        p.text(px, py, ln, hf, INK)
        py += lh
    y = max(y, py + 30) + 20
    kf, vf = p.f(15), p.f(15, True)
    rows = [(rng.choice(["Account number", "Account no", "Customer ref"]), [(doc["acc"], "ACCOUNT_NO")]),
            (rng.choice(["Statement date", "Date", "Bill date"]), [(S.D(doc, doc["date"]), "DOC_DATE")])]
    if doc["period"]:
        rows.append(("Period", S.period_parts(doc)))
    y = S.kv_rows(p, x0, y, rows, kf, vf, val_x=x0 + 210, colon=rng.random() < 0.5) + 20
    y = body_table(p, doc, x0, x1, y, headers=("Charges", "", "Amount"))
    y = S.small_print(p, x0, y, x1 - x0, H - 220, doc, 12, rng.randint(1, 2))
    if rng.random() < 0.6:
        S.remittance(p, doc, H - 210, x0, x1, 14, name=rng.random() < 0.5)
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"])


def lay_w_salute(p: S.Page, doc: dict) -> None:
    """A notice whose holder is named in the salutation and a block lower down; dense prose."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    y = letterhead(p, doc, centre=rng.random() < 0.3, decoy=doc["decoy"])
    x0, x1 = 90, W - 90
    f = p.f(rng.uniform(15, 18))
    lh = p.lh(f, 1.4)
    p.text(x1, y, [(S.D(doc, doc["date"]), "DOC_DATE")], f, INK, anchor="r")
    p.text(x0, y, ["Account: ", (doc["acc"], "ACCOUNT_NO")], f, INK)
    y += lh * 2
    block_first = rng.random() < 0.5
    if block_first:
        p.text(x0, y, [(doc["person"]["printed"], "HOLDER_NAME")], p.f(f.size, True), INK)
        y += lh
        for ln in addr_block_lines(doc, rng):
            p.text(x0, y, ln, f, INK)
            y += lh
        y += lh
    p.text(x0, y, ["Dear ", (doc["person"]["salutation"], "HOLDER_NAME"), ","], f)
    y += lh * 1.5
    p.text(x0, y, rng.choice(["IMPORTANT: CHANGES TO YOUR ACCOUNT", "Annual account notice", "Your new tariff", "Notice of account review"]),
           p.f(f.size + 2, True))
    y += lh * 1.5
    for _ in range(rng.randint(2, 4)):
        y = p.flow(x0, y, x1 - x0, [rng.choice(S.SMALL_PRINT).replace("{I}", iss["name"])], f, INK, lh) + lh * 0.5
    if not block_first:
        y += lh
        p.text(x0, y, rng.choice(["Service address", "Premises", "Your address on record", "Delivery address"]) + ":", p.f(f.size, True), GREY)
        y += lh
        p.text(x0, y, [(doc["person"]["printed"], "HOLDER_NAME")], f, INK)
        y += lh
        for ln in addr_block_lines(doc, rng):
            p.text(x0, y, ln, f, INK)
            y += lh
    y += lh
    p.text(x0, y, "Yours sincerely", f)
    signature(p, doc, x0, y + lh * 2.5, p.f(15))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"], centre=True)


def lay_w_grid(p: S.Page, doc: dict) -> None:
    """The holder's details in a ruled grid across the page: labels in one row, values in the row below."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 60, W - 60
    y = letterhead(p, doc, centre=rng.random() < 0.4, decoy=doc["decoy"])
    p.text(x0, y, rng.choice(["ACCOUNT SUMMARY", "STATEMENT OF ACCOUNT", "TAX INVOICE", "CUSTOMER DETAILS"]), p.f(22, True), INK)
    y += 44
    lf, vf = p.f(13, True), p.f(rng.uniform(14, 16))
    lh = p.lh(vf, 1.3)
    lines = addr_block_lines(doc, rng, single=rng.random() < 0.3)
    cols = [(rng.choice(["Name", "Customer", "Account holder", "Client name"]), [[(doc["person"]["printed"], "HOLDER_NAME")]]),
            (rng.choice(["Address", "Service address", "Physical address"]), lines),
            (rng.choice(["Account no.", "Account", "Reference"]), [[(doc["acc"], "ACCOUNT_NO")]]),
            (rng.choice(["Date", "Statement date", "Invoice date"]), [[(S.D(doc, doc["date"]), "DOC_DATE")]])]
    if rng.random() < 0.5:
        cols[0], cols[2] = cols[2], cols[0]
    fr = [0.24, 0.36, 0.2, 0.2]
    xs = [x0 + (x1 - x0) * sum(fr[:k]) for k in range(5)]
    rows_h = lh * max(len(v) for _, v in cols) + 16
    p.d.rectangle((x0, y, x1, y + 28), fill=S.tint(c, 0.2))
    for k, (lab, vals) in enumerate(cols):
        p.text(xs[k] + 8, y + 7, lab, lf, INK)
        vy = y + 36
        for v in vals:
            if p.d.textlength("".join(t if isinstance(t, str) else t[0] for t in v), font=vf) > xs[k + 1] - xs[k] - 12:
                vy = p.flow(xs[k] + 8, vy, xs[k + 1] - xs[k] - 12, v, vf, INK, lh)
            else:
                p.text(xs[k] + 8, vy, v, vf, INK)
                vy += lh
        p.d.line([(xs[k], y), (xs[k], y + 28 + rows_h)], fill=S.LIGHT)
    p.d.rectangle((x0, y, x1, y + 28 + rows_h), outline=S.LIGHT)
    y += 28 + rows_h + 40
    y = body_table(p, doc, x0, x1, y, head_fill=S.tint(c, 0.2))
    y = S.small_print(p, x0, y, x1 - x0, H - 140, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"])


AF = {"Account holder": "Rekeninghouer", "Name": "Naam", "Address": "Adres", "Account number": "Rekeningnommer", "Date": "Datum",
      "Statement date": "Staatdatum", "Due date": "Betaaldatum", "Amount due": "Bedrag verskuldig", "Period": "Tydperk"}


def lay_w_bilingual(p: S.Page, doc: dict) -> None:
    """Labels in English and Afrikaans ("Account number / Rekeningnommer"), the holder block at the top right."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    S.logo(p, x0, 50, 70, doc)
    p.text(x0 + 85, 60, [(iss["name"], "ISSUER")], p.f(rng.uniform(22, 30), True), c)
    if doc["decoy"]:
        a = S.decoy_address(rng, doc["addr"], rng.choice(["head_office", "postal"]))
        doc["decoys"].append(a)
        yy = 135
        for ln in S.address_lines(a, rng, labelled=False, upper=False)[0]:
            p.text(x0, yy, ln, p.f(13), GREY)
            yy += 19
    f, fb = p.f(17), p.f(17, True)
    lh = p.lh(f, 1.3)
    hx = W / 2 + rng.choice([40, 90, 140])
    hy = 140 + S.J(p, 20)
    both = lambda en: f"{en} / {AF[en]}" if rng.random() < 0.7 else f"{AF[en]} / {en}"  # noqa: E731
    p.text(hx, hy, both(rng.choice(["Account holder", "Name"])), p.f(12, True), GREY)
    hy += 22
    p.text(hx, hy, [(doc["person"]["printed"], "HOLDER_NAME")], fb, INK)
    hy += lh
    for ln in addr_block_lines(doc, rng):
        p.text(hx, hy, ln, f, INK)
        hy += lh
    y = max(hy, 260) + 40
    kf, vf = p.f(14), p.f(15, True)
    rows = [(both("Account number"), [(doc["acc"], "ACCOUNT_NO")]), (both("Statement date"), [(S.D(doc, doc["date"]), "DOC_DATE")])]
    if doc["period"]:
        rows.append((both("Period"), S.period_parts(doc)))
    rows.append((both("Due date"), S.D(doc, doc["due"])))
    y = S.kv_rows(p, x0, y, rows, kf, vf, val_x=x0 + 330) + 20
    y = body_table(p, doc, x0, x1, y, head_fill=S.tint(c, 0.25))
    y = S.small_print(p, x0, y, x1 - x0, H - 140, doc, 12, rng.randint(1, 3))
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=doc["extra_decoy"])


def lay_w_footer(p: S.Page, doc: dict) -> None:
    """The issuer's address block at the top left where a holder usually sits; the holder near the foot, above a tear-off slip."""
    rng, iss, W, H = p.rng, doc["issuer"], p.w, p.h
    c = iss["colour"]
    x0, x1 = 70, W - 70
    p.text(x1, 60, [(iss["name"], "ISSUER")], p.f(rng.uniform(24, 32), True), c, anchor="r")
    # A decoy where a window envelope would show an address: the issuer's office.
    a = S.decoy_address(rng, doc["addr"], rng.choice(["head_office", "branch"]))
    doc["decoys"].append(a)
    y = 160 + S.J(p, 20)
    p.text(x0, y, iss["legal"], p.f(16, True), INK)
    y += 24
    for ln in S.address_lines(a, rng, labelled=False, upper=rng.random() < 0.3)[0]:
        p.text(x0, y, ln, p.f(16), INK)
        y += 22
    kf, vf = p.f(15), p.f(15, True)
    rows = [(rng.choice(["Statement date", "Date"]), [(S.D(doc, doc["date"]), "DOC_DATE")]), ("Account", [(doc["acc"], "ACCOUNT_NO")])]
    S.kv_rows(p, x1 - 480, 160, rows, kf, vf, right=x1)
    y = max(y, 260) + 40
    y = body_table(p, doc, x0, x1, y, head_fill=S.tint(c, 0.2))
    y = S.small_print(p, x0, y, x1 - x0, H - 420, doc, 12, rng.randint(1, 2))
    hy = H - 380
    p.rule(x0, hy - 20, x1, GREY, 1, dash=8)
    p.text(x0, hy, rng.choice(["Statement for:", "Account holder:", "Prepared for:", "Customer:"]), p.f(13, True), GREY)
    hy += 22
    f = p.f(17)
    p.text(x0, hy, [(doc["person"]["printed"], "HOLDER_NAME")], p.f(17, True), INK)
    hy += 24
    for ln in addr_block_lines(doc, rng, single=rng.random() < 0.4):
        p.text(x0, hy, ln, f, INK)
        hy += 24
    S.footer(p, doc, H - 70, x0, x1, 12, decoy_here=False)


TRAIN_FAMILIES = ["w_letter", "w_window", "w_kv", "w_panel", "w_salute", "w_grid", "w_bilingual", "w_footer"]
DEVG_FAMILIES = ["w_branch", "w_certify"]
TYPES = ["utility_bill", "bank_statement", "municipal_account", "cellphone_account", "insurance_statement", "lease_agreement"]
# poa_synth's own layouts, minus the three DEV holds out (util_sidebar, bank_modern, muni_grid).
OLD_TRAIN = ["util_band", "util_minimal", "bank_classic", "muni_rates", "cell_invoice", "lease_letter", "insure_stmt", "util_slip", "proc"]


def register(split: str) -> list[str]:
    fams = TRAIN_FAMILIES if split == "train" else DEVG_FAMILIES
    for name in TRAIN_FAMILIES + DEVG_FAMILIES:
        S.LAYOUT_FN[name] = globals()["lay_" + name]
        S.LAYOUT_TYPES[name] = "utility_bill"  # replaced per document (wide_build)
        S.LAYOUT_DATE_STYLES[name] = S.DATE_STYLES[:-1]
        S.PERIOD_P[name] = 0.6
    for name in list(S.LAYOUT_FN):
        S.LAYOUT_FONTS[name] = list(S.FONTS)
    # For --debug's box labels only (not a page font in DEV-G).
    S.FONTS.setdefault("dejavu_sans", (S.DV + "DejaVuSans.ttf", S.DV + "DejaVuSans-Bold.ttf"))
    if split == "train":
        return fams * 2 + OLD_TRAIN  # the new families twice as often
    # DEV-G: the held-out families, and poa_synth's procedural pages in held-out fonts and vocabulary.
    return fams * 2 + ["proc"]


_orig_build = S.build
_orig_page_init = S.Page.__init__
LAST_PAGE: list = []


def _page_init(self, *a, **k):
    """A page that also records every word it draws (text and box), for
    training on synthetic OCR (train/synth_ocr.py): the line's box gives the
    word its top and height, as OCR's line crops do."""
    _orig_page_init(self, *a, **k)
    self.all_words = []
    draw_text = self.d.text

    def text(xy, s, *args, **kw):
        draw_text(xy, s, *args, **kw)
        font = kw.get("font", args[1] if len(args) > 1 else None)
        if kw.get("anchor") or font is None or not str(s).strip():
            return
        x, y = xy
        lb = self.d.textbbox((x, y), s, font=font)
        for m in re.finditer(r"\S+", s):
            xw = x + self.d.textlength(s[: m.start()], font=font)
            b = self.d.textbbox((xw, y), m.group(), font=font)
            self.all_words.append({"text": m.group(), "box": [round(b[0], 1), round(lb[1], 1), round(b[2], 1), round(lb[3], 1)],
                                   "size": font.size})

    self.d.text = text
    LAST_PAGE[:] = [self]


S.Page.__init__ = _page_init


def wide_build(seed: int, index: int, layout: str, today: dt.date, attempt: int):
    if layout.startswith("w_"):
        rng = random.Random(f"wide-type:{seed}:{index}")
        t = rng.choice(TYPES)
        S.LAYOUT_TYPES[layout] = t
        S.PERIOD_P[layout] = 0.0 if t == "lease_agreement" else 0.6
    captured = {}
    orig_make_doc = S.make_doc

    def keep(*a, **k):
        d = orig_make_doc(*a, **k)
        captured["doc"] = d
        return d

    S.make_doc = keep
    try:
        img, truth, texts = _orig_build(seed, index, layout, today, attempt)
    finally:
        S.make_doc = orig_make_doc
    pr = captured["doc"]["person"]
    # The holder as their ID names them, for verification against a known customer.
    truth["person"] = {"first": pr["first"], "middle": pr.get("middle"), "surname": pr["surname"]}
    truth["words_all"] = LAST_PAGE[0].all_words if LAST_PAGE else []
    truth["wide_split"] = SPLIT
    try:
        S.check(img, truth, texts)
    except AssertionError as e:
        raise S.ProcReroll(str(e))
    return img, truth, texts


def init_worker(split: str) -> None:
    install(split)
    register(split)
    S.build = wide_build


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=["train", "devg"], required=True)
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--seed", type=int, default=77)
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default="2026-10-15")
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    if args.split == "devg":
        assert args.seed != 77, "DEV-G uses its own seed (--seed 91)"
    init_worker(args.split)
    layouts = register(args.split)
    today = dt.date.fromisoformat(args.today)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    jobs = [(args.seed, i, layouts, today, args.out, args.debug) for i in range(args.start_index, args.start_index + args.count)]
    t0 = time.perf_counter()
    if args.jobs > 1:
        with mp.Pool(args.jobs, initializer=init_worker, initargs=(args.split,)) as pool:
            res = list(pool.imap_unordered(S.render_one, jobs, chunksize=4))
    else:
        res = [S.render_one(j) for j in jobs]
    print(f"wrote {len(res)} documents to {args.out} in {time.perf_counter() - t0:.1f} s; "
          f"{len(S.PLACES)} places, {len(S.FIRST_M) + len(S.FIRST_F)} first names, {len(S.SURNAMES)} surnames, {len(S.FONTS)} fonts")


if __name__ == "__main__":
    main()
