"""Render fictional identity documents and a multi-barcode sheet for the ID-scan spike.

Every holder here is invented. The documents carry a SPECIMEN mark and are drawn
only well enough to exercise a scanner: layout, labels, barcodes and MRZ follow
the published formats (see FORMATS.md), security features are not imitated.

Outputs: synth/<name>.png (clean render) and synth/<name>.json (ground truth).
Run: .venv/bin/python synth.py
"""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path

import barcode
import numpy as np
import pdf417gen
import segno
import zxingcpp
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "synth"
FONT_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_OCRB = str(ROOT / "fonts" / "OCRB.otf")  # Matthew Skala's OCR-B, public domain


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# --------------------------------------------------------------------------- #
# Check digits
# --------------------------------------------------------------------------- #


def sa_id_check_digit(first12: str) -> int:
    """Standard Luhn (mod 10) over the first 12 digits, as DHA uses for the 13th.

    Walk the 12 digits right to left; double every digit in an odd position
    counted from the right (i.e. the rightmost of the 12 is doubled), subtract 9
    from a doubled value above 9, sum everything, check = (10 - sum % 10) % 10.
    Equivalent to the "odd positions + 2 x concatenated even positions" recipe.
    """
    total = 0
    for i, ch in enumerate(reversed(first12)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def sa_id_valid(idn: str) -> bool:
    return len(idn) == 13 and idn.isdigit() and sa_id_check_digit(idn[:12]) == int(idn[12])


def make_sa_id(dob: dt.date, female: bool, seq: int, citizen: bool = True, a: int = 8) -> str:
    sss = (seq % 5000) + (0 if female else 5000)
    first12 = f"{dob:%y%m%d}{sss:04d}{0 if citizen else 1}{a}"
    return first12 + str(sa_id_check_digit(first12))


def mrz_char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c == "<":
        return 0
    return ord(c) - ord("A") + 10


def mrz_check(s: str) -> str:
    weights = (7, 3, 1)
    return str(sum(mrz_char_value(c) * weights[i % 3] for i, c in enumerate(s)) % 10)


def mrz_name(surname: str, given: str, width: int) -> str:
    def clean(x: str) -> str:
        return "".join(c if c.isalpha() else "<" for c in x.upper().replace("-", " ").replace("'", "")).replace(" ", "<")

    s = clean(surname) + "<<" + clean(given).strip("<")
    return (s + "<" * width)[:width]


def td3_mrz(*, doc_type: str, state: str, surname: str, given: str, number: str,
            nationality: str, dob: dt.date, sex: str, expiry: dt.date, optional: str,
            empty_optional_check: str = "<") -> list[str]:
    line1 = (doc_type + "<")[:2] + state + mrz_name(surname, given, 39)
    num = (number + "<" * 9)[:9]
    opt = (optional + "<" * 14)[:14]
    # ICAO 9303-4: when the personal-number field is all fillers its check digit may be
    # '<' or '0' (the computed value). Issuers differ, so a reader must accept both.
    opt_cd = mrz_check(opt) if optional else empty_optional_check
    body = (num + mrz_check(num) + nationality + f"{dob:%y%m%d}" + mrz_check(f"{dob:%y%m%d}")
            + sex + f"{expiry:%y%m%d}" + mrz_check(f"{expiry:%y%m%d}") + opt + opt_cd)
    composite = (body[0:10] + body[13:20] + body[21:43])
    line2 = body + mrz_check(composite)
    assert len(line1) == 44 and len(line2) == 44, (line1, line2)
    return [line1, line2]


def validate_td3(lines: list[str]) -> dict[str, bool]:
    l2 = lines[1]
    res = {
        "document_number": mrz_check(l2[0:9]) == l2[9],
        "date_of_birth": mrz_check(l2[13:19]) == l2[19],
        "date_of_expiry": mrz_check(l2[21:27]) == l2[27],
        "optional_data": (l2[42] == "<" and set(l2[28:42]) == {"<"}) or mrz_check(l2[28:42]) == l2[42],
        "composite": mrz_check(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43],
    }
    return res


# --------------------------------------------------------------------------- #
# Barcode renderers -> PIL "L" images
# --------------------------------------------------------------------------- #


def render_pdf417(text: str, columns: int = 17, scale: int = 3, ratio: int = 3, security: int = 5) -> Image.Image:
    codes = pdf417gen.encode(text, columns=columns, security_level=security)
    return pdf417gen.render_image(codes, scale=scale, ratio=ratio, padding=10).convert("L")


def render_linear(kind: str, data: str, module_px: float = 3, height_px: int = 120, text: bool = False) -> Image.Image:
    cls = barcode.get_barcode_class(kind)
    kwargs = {"add_checksum": False} if kind == "code39" else {}
    bc = cls(data, writer=ImageWriter(), **kwargs)
    buf = io.BytesIO()
    dpi = 300
    bc.write(buf, options={
        "module_width": module_px * 25.4 / dpi, "module_height": height_px * 25.4 / dpi,
        "dpi": dpi, "quiet_zone": 3.5, "write_text": text, "font_size": 8, "text_distance": 3.0,
    })
    buf.seek(0)
    return Image.open(buf).convert("L")


def render_zxing(fmt: zxingcpp.BarcodeFormat, data: str, scale: int = 8) -> Image.Image:
    bc = zxingcpp.create_barcode(data, fmt)
    return Image.fromarray(np.array(bc.to_image(scale=scale, add_quiet_zones=True))).convert("L")


def render_qr(data: str, scale: int = 10) -> Image.Image:
    buf = io.BytesIO()
    segno.make_qr(data, error="m").save(buf, kind="png", scale=scale, border=4)
    buf.seek(0)
    return Image.open(buf).convert("L")


def paste_barcode(page: Image.Image, bc: Image.Image, xy: tuple[int, int], size: tuple[int, int] | None = None) -> None:
    if size:
        bc = bc.resize(size, Image.NEAREST)
    page.paste(bc.convert("RGB"), xy)


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #


def guilloche(img: Image.Image, colour: tuple[int, int, int], seed: int, alpha: int = 40) -> None:
    rng = np.random.default_rng(seed)
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k in range(26):
        amp = rng.uniform(15, 70)
        freq = rng.uniform(0.004, 0.015)
        phase = rng.uniform(0, 6.28)
        y0 = rng.uniform(0, h)
        pts = [(x, y0 + amp * np.sin(freq * x + phase) + 0.3 * amp * np.sin(3.1 * freq * x)) for x in range(0, w, 6)]
        d.line(pts, fill=(*colour, alpha), width=2)
    img.alpha_composite(layer) if img.mode == "RGBA" else img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"))


def photo_box(img: Image.Image, box: tuple[int, int, int, int], seed: int) -> None:
    """A grey placeholder portrait: silhouette only, no face."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=(196, 198, 200), outline=(120, 120, 120), width=3)
    cx, w, h = (x0 + x1) // 2, x1 - x0, y1 - y0
    d.ellipse((cx - w * 0.22, y0 + h * 0.16, cx + w * 0.22, y0 + h * 0.56), fill=(150, 152, 156))
    d.chord((x0 + w * 0.08, y0 + h * 0.58, x1 - w * 0.08, y1 + h * 0.45), 180, 360, fill=(150, 152, 156))
    d.text((cx, y1 - 18), "PHOTO", fill=(110, 110, 110), font=font(FONT_SANS_B, max(14, w // 12)), anchor="ms")


def specimen_mark(img: Image.Image, text: str = "SPECIMEN", size: int = 140, angle: float = 18) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((img.width // 2, img.height // 2), text, font=font(FONT_SANS_B, size), fill=(200, 40, 40, 38), anchor="mm")
    layer = layer.rotate(angle, resample=Image.BICUBIC, center=(img.width // 2, img.height // 2))
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"))


def save(name: str, img: Image.Image, truth: dict) -> None:
    OUT.mkdir(exist_ok=True)
    img.save(OUT / f"{name}.png", optimize=True)
    truth = {"name": name, "image": f"synth/{name}.png", "size": list(img.size), **truth}
    (OUT / f"{name}.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False) + "\n")
    print("wrote", name, img.size)


def fmt_dmy(d: dt.date) -> str:
    return d.strftime("%d %b %Y").upper()


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

W_CARD, H_CARD = 1600, 1009  # ID-1, 85.60 x 53.98 mm
W_TD3, H_TD3 = 1600, 1126  # TD3, 125 x 88 mm


SMART = {
    "surname": "TESTERSON",
    "names": "ZANELE PRECIOUS",
    "sex": "F",
    "nationality": "RSA",
    "dob": dt.date(1990, 3, 14),
    "country_of_birth": "RSA",
    "status": "CITIZEN",
    "date_of_issue": dt.date(2019, 6, 21),
    "security_number": "40917",
    "card_number": "100345678",
}
SMART["identity_number"] = make_sa_id(SMART["dob"], female=True, seq=1234)


def sa_smart_front() -> None:
    s = SMART
    img = Image.new("RGB", (W_CARD, H_CARD), (226, 240, 228))
    guilloche(img, (90, 150, 110), seed=1)
    d = ImageDraw.Draw(img)
    # flag-ish block and header
    d.rectangle((50, 40, 170, 120), fill=(0, 119, 73))
    d.polygon([(50, 40), (110, 80), (50, 120)], fill=(255, 182, 18))
    d.text((210, 38), "REPUBLIC OF SOUTH AFRICA", font=font(FONT_SANS, 64), fill=(20, 20, 20))
    d.text((212, 112), "NATIONAL IDENTITY CARD", font=font(FONT_SANS, 46), fill=(30, 60, 40))
    photo_box(img, (1080, 220, 1500, 760), seed=2)
    lab, val = font(FONT_SANS, 30), font(FONT_SANS, 40)
    fields = [
        ("Surname", s["surname"]), ("Names", s["names"]), ("Sex", s["sex"]), ("Nationality", s["nationality"]),
        ("Identity Number", s["identity_number"]), ("Date of Birth", fmt_dmy(s["dob"])),
        ("Country of Birth", s["country_of_birth"]), ("Status", s["status"]),
    ]
    y = 200
    for label, value in fields:
        d.text((90, y), label + ":", font=lab, fill=(70, 100, 80))
        d.text((90, y + 34), value, font=val, fill=(10, 10, 10))
        y += 94
    d.text((1120, 800), "Signature", font=font(FONT_SANS, 30), fill=(70, 100, 80))
    d.line([(1120, 900), (1180, 860), (1240, 905), (1300, 850), (1380, 900), (1450, 870)], fill=(20, 20, 60), width=4)
    specimen_mark(img)
    save("za_smart_id_front", img, {
        "kind": "za_smart_id_front",
        "fields": {
            "surname": s["surname"], "names": s["names"], "sex": s["sex"], "nationality": s["nationality"],
            "identity_number": s["identity_number"], "date_of_birth": s["dob"].isoformat(),
            "date_of_birth_printed": fmt_dmy(s["dob"]), "country_of_birth": s["country_of_birth"],
            "status": s["status"],
        },
        "printed_labels": [f[0] for f in fields],
        "identity_number_luhn_valid": sa_id_valid(s["identity_number"]),
        "barcodes": [],
    })


def smart_pdf417_payload() -> str:
    s = SMART
    fields = [
        s["surname"], s["names"], s["sex"], s["nationality"], s["identity_number"],
        fmt_dmy(s["dob"]), s["country_of_birth"], s["status"], fmt_dmy(s["date_of_issue"]),
        s["security_number"], s["card_number"],
    ]
    head = "|".join(fields) + "|"
    filler = ("1234567890" * 60)[: 520 - len(head)]
    return head + filler


def sa_smart_back() -> None:
    s = SMART
    img = Image.new("RGB", (W_CARD, H_CARD), (232, 241, 232))
    guilloche(img, (120, 140, 120), seed=3)
    d = ImageDraw.Draw(img)
    d.text((345, 30), "Conditions:", font=font(FONT_SANS, 38), fill=(30, 110, 60), anchor="ma")
    cond = ["This card has been issued by the", "Department of Home Affairs in terms of the",
            "Identification Act, Act 68 of 1997 (Amended)", "", "For verification or enquiry purposes contact",
            "(012) xxx-xxxx", "If found please return to the Department of Home Affairs"]
    for i, line in enumerate(cond):
        d.text((345, 84 + i * 34), line, font=font(FONT_SANS, 22), fill=(30, 30, 30), anchor="ma")
    d.text((1530, 30), f"Date of Issue: {s['date_of_issue']:%Y-%m-%d}", font=font(FONT_SANS, 36), fill=(30, 110, 60), anchor="ra")
    d.text((1020, 230), "RSA", font=font(FONT_SANS_B, 90), fill=(60, 60, 60), anchor="mm")
    d.text((1020, 300), s["security_number"], font=font(FONT_SANS, 28), fill=(80, 80, 80), anchor="mm")
    photo_box(img, (90, 420, 330, 640), seed=4)
    d.text((1050, 380), s["card_number"], font=font(FONT_SANS, 40), fill=(10, 10, 10), anchor="mm")
    specimen_mark(img, size=110)  # under the barcodes, so it never degrades them
    # Code 39 of the ID number (left) and the PDF417 (right), as on the real reverse.
    c39 = render_linear("code39", s["identity_number"], module_px=2, height_px=150)
    paste_barcode(img, c39, (20, 700))
    payload = smart_pdf417_payload()
    p = render_pdf417(payload, columns=12, scale=3, ratio=3, security=4)
    assert p.width <= W_CARD - 580 and p.height <= H_CARD - 440, p.size
    paste_barcode(img, p, (580 + (W_CARD - 580 - p.width) // 2, 430))
    save("za_smart_id_back", img, {
        "kind": "za_smart_id_back",
        "fields": {"date_of_issue": s["date_of_issue"].isoformat(), "card_number": s["card_number"],
                   "security_number": s["security_number"], "identity_number": s["identity_number"]},
        "pdf417_field_order": ["surname", "names", "sex", "nationality", "identity_number", "date_of_birth",
                               "country_of_birth", "status", "date_of_issue", "security_number", "card_number",
                               "filler(1234567890...)"],
        "barcodes": [
            {"format": "Code39", "text": s["identity_number"]},
            {"format": "PDF417", "text": payload},
        ],
        "identity_number_luhn_valid": sa_id_valid(s["identity_number"]),
        "note": "PDF417 field order per Wikipedia/DHA; date formats inside the PDF417 are NOT verified against a real card (see FORMATS.md).",
    })


GREEN = {
    "surname": "VAN DER SPECIMEN",
    "forenames": "JOHANNES PIETER",
    "country_of_birth": "SUID-AFRIKA",
    "dob": dt.date(1975, 11, 2),
    "date_issued": dt.date(2001, 8, 17),
}
GREEN["identity_number"] = make_sa_id(GREEN["dob"], female=False, seq=731)


def sa_green_book() -> None:
    g = GREEN
    W, H = 1200, 1704  # one page of the book, 88 x 125 mm, portrait
    img = Image.new("RGB", (W, H), (196, 222, 190))
    guilloche(img, (60, 120, 70), seed=5, alpha=55)
    d = ImageDraw.Draw(img)
    lab = font(FONT_SANS, 26)
    val = font(FONT_SANS_B, 44)
    d.text((W // 2, 40), "REPUBLIEK VAN SUID-AFRIKA  ·  REPUBLIC OF SOUTH AFRICA", font=font(FONT_SANS, 30), fill=(30, 60, 30), anchor="ma")
    d.text((80, 120), "I.D. No.", font=font(FONT_SANS_B, 40), fill=(20, 40, 20))
    idn = g["identity_number"]
    d.text((300, 112), f"{idn[:6]} {idn[6:10]} {idn[10:]}", font=font(FONT_SANS_B, 56), fill=(10, 10, 10))
    c39 = render_linear("code39", idn, module_px=3, height_px=130)
    paste_barcode(img, c39, ((W - c39.width) // 2, 200))
    photo_box(img, (340, 400, 860, 1000), seed=6)
    rows = [
        ("VAN/SURNAME", g["surname"]),
        ("VOORNAME/FORENAMES", g["forenames"]),
        ("GEBOORTEDISTRIK OF-LAND/DISTRICT OR COUNTRY OF BIRTH", g["country_of_birth"]),
        ("GEBOORTEDATUM/DATE OF BIRTH", g["dob"].strftime("%Y-%m-%d")),
        ("DATUM UITGEREIK/DATE ISSUED", g["date_issued"].strftime("%Y-%m-%d")),
    ]
    y = 1040
    for label, value in rows:
        d.text((80, y), label, font=lab, fill=(40, 70, 40))
        d.text((80, y + 32), value, font=val, fill=(15, 15, 15))
        y += 120
    specimen_mark(img, text="SPECIMEN", size=120, angle=30)
    save("za_green_id_book", img, {
        "kind": "za_green_id_book",
        "fields": {"identity_number": idn, "surname": g["surname"], "forenames": g["forenames"],
                   "country_of_birth": g["country_of_birth"], "date_of_birth": g["dob"].isoformat(),
                   "date_issued": g["date_issued"].isoformat()},
        "printed_labels": ["I.D. No."] + [r[0] for r in rows],
        "barcodes": [{"format": "Code39", "text": idn}],
        "identity_number_luhn_valid": sa_id_valid(idn),
    })


def passport(name: str, *, state: str, header: str, nationality_text: str, surname: str, given: str,
             number: str, dob: dt.date, sex: str, issue: dt.date, expiry: dt.date, pob: str,
             authority: str, optional: str, bg: tuple[int, int, int], accent: tuple[int, int, int], seed: int,
             empty_optional_check: str = "<") -> None:
    img = Image.new("RGB", (W_TD3, H_TD3), bg)
    guilloche(img, accent, seed=seed)
    d = ImageDraw.Draw(img)
    hf = 48 if len(header) < 30 else 30
    d.text((W_TD3 // 2 + 230, 40), header, font=font(FONT_SANS_B, hf), fill=accent, anchor="ma")
    photo_box(img, (60, 150, 480, 690), seed=seed + 1)
    lab, val = font(FONT_SANS, 22), font(FONT_SANS_B, 36)
    col1, col2 = 540, 1100
    rows = [
        ((col1, 120), "Type / Type", "P"), ((col1 + 200, 120), "Code / Code", state),
        ((col2, 120), "Passport No. / N° du passeport", number),
        ((col1, 205), "Surname / Nom", surname),
        ((col1, 290), "Given names / Prénoms", given),
        ((col1, 375), "Nationality / Nationalité", nationality_text),
        ((col1, 460), "Date of birth / Date de naissance", fmt_dmy(dob)),
        ((col2, 460), "Sex / Sexe", sex),
        ((col1, 545), "Place of birth / Lieu de naissance", pob),
        ((col1, 630), "Date of issue / Date de délivrance", fmt_dmy(issue)),
        ((col2, 630), "Authority / Autorité", authority),
        ((col1, 715), "Date of expiry / Date d'expiration", fmt_dmy(expiry)),
    ]
    for (x, y), label, value in rows:
        d.text((x, y), label, font=lab, fill=tuple(int(c * 0.8) for c in accent))
        d.text((x, y + 26), value, font=val, fill=(15, 15, 15))
    mrz = td3_mrz(doc_type="P", state=state, surname=surname, given=given, number=number,
                  nationality=state, dob=dob, sex=sex, expiry=expiry, optional=optional,
                  empty_optional_check=empty_optional_check)
    # MRZ clear area: white-ish band, OCR-B ~ 10 cpi scaled; 44 chars across ~1480 px.
    d.rectangle((0, H_TD3 - 260, W_TD3, H_TD3), fill=tuple(min(255, c + 12) for c in bg))
    ocr = font(FONT_OCRB, 58)
    for i, line in enumerate(mrz):
        x = 60
        y = H_TD3 - 220 + i * 90
        pitch = (W_TD3 - 120) / 44
        for j, ch in enumerate(line):
            d.text((x + j * pitch + pitch / 2, y), ch, font=ocr, fill=(10, 10, 10), anchor="ma")
    specimen_mark(img, size=150)
    check = validate_td3(mrz)
    assert all(check.values()), check
    save(name, img, {
        "kind": name,
        "fields": {"document_type": "P", "issuing_state": state, "surname": surname, "given_names": given,
                   "document_number": number, "nationality": state, "date_of_birth": dob.isoformat(), "sex": sex,
                   "date_of_issue": issue.isoformat(), "date_of_expiry": expiry.isoformat(), "place_of_birth": pob,
                   "authority": authority, "optional_data": optional},
        "mrz": mrz,
        "mrz_check_digits_valid": check,
        "barcodes": [],
    })


def za_passport() -> None:
    dob = dt.date(1988, 7, 9)
    idn = make_sa_id(dob, female=False, seq=4321)
    passport("za_passport", state="ZAF", header="REPUBLIC OF SOUTH AFRICA", nationality_text="SOUTH AFRICAN",
             surname="SPECIMEN-NKOSI", given="THABO SIPHO", number="A09876543", dob=dob, sex="M",
             issue=dt.date(2022, 2, 1), expiry=dt.date(2032, 1, 31), pob="JOHANNESBURG",
             authority="DHA", optional=idn, bg=(232, 236, 244), accent=(20, 70, 50), seed=10)
    p = OUT / "za_passport.json"
    t = json.loads(p.read_text())
    t["fields"]["identity_number"] = idn
    t["identity_number_luhn_valid"] = sa_id_valid(idn)
    t["note"] = "ZAF passports are believed to carry the 13-digit SA ID number in the TD3 optional/personal-number field (line 2, positions 29-42); not verified against a specimen."
    p.write_text(json.dumps(t, indent=2) + "\n")


def gb_passport() -> None:
    passport("gb_passport", state="GBR", header="UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND",
             nationality_text="BRITISH CITIZEN", surname="UK SPECIMEN", given="ANGELA ZOE", number="925076473",
             dob=dt.date(1988, 12, 4), sex="F", issue=dt.date(2020, 3, 26), expiry=dt.date(2030, 3, 26),
             pob="CROYDON", authority="HMPO", optional="", bg=(240, 236, 246), accent=(60, 30, 100), seed=20,
             empty_optional_check="0")


def multi_barcode_sheet() -> None:
    W, H = 1600, 1131  # A4 landscape proportions
    img = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(img)
    d.text((W // 2, 24), "MULTI-SYMBOLOGY TEST SHEET (fictional payloads)", font=font(FONT_SANS_B, 36), fill=(30, 30, 30), anchor="ma")
    ean12 = "600123456789"
    ean13 = barcode.get_barcode_class("ean13")(ean12).get_fullcode()
    items = [
        ("QRCode", "https://example.test/id-scan-spike/qr?n=42", lambda t: render_qr(t, scale=6)),
        ("Code128", "DOCSCAN-TEST-0001", lambda t: render_linear("code128", t, module_px=2, height_px=160)),
        ("EAN13", ean13, lambda t: render_linear("ean13", t[:12], module_px=3, height_px=160, text=True)),
        ("DataMatrix", "DM-SPIKE-2026-10-14", lambda t: render_zxing(zxingcpp.BarcodeFormat.DataMatrix, t, scale=10)),
        ("PDF417", "PDF417 MULTI SHEET|ALPHA|BRAVO|1234567890", lambda t: render_pdf417(t, columns=5, scale=3, ratio=3, security=3)),
        ("Code39", "SPIKE-39", lambda t: render_linear("code39", t, module_px=2, height_px=160)),
        ("QRCode", "SECOND QR: 900314123408", lambda t: render_qr(t, scale=6)),
        ("Code128", "CARD-128-B", lambda t: render_linear("code128", t, module_px=2, height_px=120)),
    ]
    # 3 x 3 grid of cells; each barcode is centred in its cell and must fit.
    cols, rows, top = 3, 3, 90
    cw, ch = W // cols, (H - top) // rows
    truth = []
    for i, (fmt, text, fn) in enumerate(items):
        bc = fn(text)
        cx, cy = (i % cols) * cw, top + (i // cols) * ch
        assert bc.width <= cw - 20 and bc.height <= ch - 60, (fmt, bc.size)
        x = cx + (cw - bc.width) // 2
        y = cy + 40 + (ch - 40 - bc.height) // 2
        paste_barcode(img, bc, (x, y))
        d.text((cx + cw // 2, cy + 10), fmt, font=font(FONT_SANS, 24), fill=(90, 90, 90), anchor="ma")
        truth.append({"format": fmt, "text": text, "bbox": [x, y, x + bc.width, y + bc.height]})
    save("multi_barcode", img, {"kind": "multi_barcode", "barcodes": truth})


def main() -> None:
    sa_smart_front()
    sa_smart_back()
    sa_green_book()
    za_passport()
    gb_passport()
    multi_barcode_sheet()
    # Self-test the check-digit code against published vectors.
    icao = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
    assert all(validate_td3(icao).values()), validate_td3(icao)
    norway = ["P<NOROESTENBYEN<<AASAMUND<SPECIMEN<<<<<<<<<<", "CCC0022514NOR5604230M3004157<<<<<<<<<<<<<<04"]
    assert all(validate_td3(norway).values()), validate_td3(norway)
    assert sa_id_valid("8001015009087")
    print("check-digit self-tests passed")


if __name__ == "__main__":
    main()
