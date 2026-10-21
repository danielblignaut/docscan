"""Deterministic generator for a hard, synthetic, multi-barcode benchmark set.

Every frame is a camera-like photo (desk or wood background, perspective, lighting,
blur, noise, JPEG) of one or more printed sheets or stickers carrying barcodes of the
13 symbologies the scanner reads (`docscan/src/barcode.rs`):

    qrcode datamatrix pdf417 aztec code128 code39 code93 codabar ean13 ean8 upca upce itf

Layouts (interleaved by frame index, so every split has them in proportion; 25-slot cycle):

    single    7/25  one code on a small sheet, any pose
    sheet     5/25  2-8 codes of mixed symbologies packed on one sheet
    multi     5/25  2-4 small stickers, 1-3 codes each, not overlapping
    labelled  6/25  device-box / shipping-label stickers: each code with a printed label
                    and value above, below or to its left of the bars, unlabelled codes,
                    "unreadable bars" (module < 0.8 px, value in clear text beside them)
                    and text-only fields; truth `fields` lists what the scanner's
                    labelled mode (`docscan/src/labels.rs`) should output
    negative  2/25  no barcode at all: desk, wood, printed text page, bar-like stripes,
                    window blinds / grille, keyboard, book spines

Conditions are drawn per frame from a difficulty tier (`difficulty`: easy 30%, medium
45%, hard 25%), which sets the print module size, tilt, rotation mix, blur, motion blur,
JPEG quality and how often codes are damaged or low-contrast:

    module   measured module_px about 1-6 px (medians ~2.7 / 2.2 / 1.6 px by tier); on
             1920-px frames the targets are 1.5x, since the scanner analyses at most
             1280 px wide; deliberately unreadable codes 0.4-0.75 px
    symbols  QR versions 1-15 with ECC L/M/Q/H, Data Matrix square and rectangular,
             PDF417 3-15 columns and security 2-5, Aztec 23-50% EC, short and long
             linear payloads, bar heights 0.15-0.5 of the width (EAN/UPC 0.45-0.8)
    pose     in-plane rotation near upright, exactly 90/180/270, +-25 deg off an axis, or
             any angle (easy: upright or right angles only); codes also turned in
             90-degree steps on their sheet; tilt up to 12 / 25 / 40 deg by tier
    camera   gaussian blur 0.3-0.8 / 0.4-1.0 / 0.5-1.2 px (10% of hard frames 1.5-2.5),
             motion blur 3-9 px, noise, JPEG quality 75/55/40-95 (5% lossless PNG),
             uneven light, glare over a code or the background, curved surface (8%)
    print    low contrast (grey on grey, 15-40%), inverted 2-D codes, damage: scratches,
             blots, occluding stickers within the error-correction budget (`damaged`,
             still decodable) or beyond it (`damaged` + `unreadable`)

Labelled stickers keep OCR possible: text em 19-26 px (x-height >= ~10 px after the
scanner's 1280-px downscale), rotation within +-10 deg, tilt within 25 deg, blur <= 1.5 px.
Printed labels use forms labels.rs parses (`IMEI1: `, `IMEI 1: `, `IMEI1 `, `S/N: `,
`SN: `, `SN `, `EAN: `, a bare `IMEI2:` left of the bars); serial numbers use only
letters labels.rs never reads as digits.

Code tags: inverted, low_contrast, damaged, unreadable, tiny (module < 1.3 px), glare
(inside the glare spot), dense. Frame tags: hd, portrait, low_res, labelled, multi_code,
multi_sheet, rot_moderate, rot_right_angle, rot_any, tilt_moderate, tilt_strong,
uneven_light, glare, glare_background, blur, blur_heavy, motion_blur, noise, curved,
jpeg_low, png, negative_<kind>.

Ground truth. Each symbol is first rendered clean and decoded with zxing-cpp, which must
return exactly the stored payload (modulo the ZXing/rxing conventions below), otherwise
generation fails (python-barcode output that does not decode, e.g. its Code 128 of a
payload starting "99", is re-encoded with zxing-cpp's writer). Damage and photometric changes are applied to the symbol at its print
resolution and the result decoded again; a code is `decodable: false` (tagged
`unreadable`) only if that damaged print no longer decodes, or its module is below
0.8 frame px. Codes made hard by the camera (blur, tilt, glare) stay `decodable: true`.

Text conventions (what rxing, like ZXing, returns):
    ean13  13 digits incl. check; never starts with 0 (a leading 0 is reported as upca)
    upca   12 digits incl. check
    upce   8 digits: number system 0 + 6 digits + check (zxing-cpp reports the 13-digit
           expansion; that is asserted against our own expansion)
    ean8   8 digits incl. check
    code39 no start/stop asterisks, no check character, plain (non-extended) charset
           (zxing-cpp is asked for plain Code 39: it would read some as Code 32 / PZN)
    code93 plain charset, check characters stripped (as ZXing does)
    codabar without the start/stop letters (rxing strips them; zxing-cpp keeps them)
    itf    even number of digits, length 6-24

Seeds: dev = 101, test = 202 (`--seed` overrides). Frame i uses
`np.random.default_rng([seed, i])` alone, so output does not depend on `--jobs` and is
byte-identical across runs.

Output under --out DIR:
    frames/bc_<split>_<index:05d>.jpg (or .png)
    truth.jsonl, one JSON object per frame, sorted by id:
    {"id", "image" (relative to DIR), "size": [w, h], "layout", "difficulty",
     "tags": [frame conditions], "negative": bool, "params": {numeric conditions},
     "codes": [{"format", "text", "corners": [[x, y] x4, TL TR BR BL of the symbol in its
                own reading orientation, frame px, quiet zone excluded],
                "module_px": smallest module in frame px (linear and PDF417: across the
                bars; 2-D: the smaller axis), "tags": [...], "decodable": bool}],
     "fields": [{"label": "IMEI1"|"IMEI2"|"SN"|"EAN"|null (normalised as labels.rs
                 normalise_label does), "value", "position": "above"|"below"|"left"|"none",
                 "barcode_format": str|null, "barcode_decodable": bool}]   (labelled only)}

Field positions: `above`/`below`/`left` say where the label (or, for an unlabelled EAN,
its digits) sits relative to the bars; `none` with a barcode_format is a code printed with
no label (the scanner names it `Barcode N`); `none` with barcode_format null is a
text-only field (a `SN: ...` line with no barcode).

Payloads are random or obviously fictional (example.test URLs, made-up models).

Run: gen_barcodes.py --out DIR --split dev|test --count N [--jobs 8] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import segno  # noqa: E402
import zxingcpp  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "testdata"))
import augment  # noqa: E402
import synth  # noqa: E402

cv2.setNumThreads(1)

SEEDS = {"dev": 101, "test": 202}
FORMATS = ["qrcode", "datamatrix", "pdf417", "aztec", "code128", "code39", "code93",
           "codabar", "ean13", "ean8", "upca", "upce", "itf"]
LINEAR = {"code128", "code39", "code93", "codabar", "ean13", "ean8", "upca", "upce", "itf"}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
K = 2.0  # sheet pixels per frame pixel, nominal: sheets are printed at twice frame resolution
MIN_DECODABLE_MODULE = 0.8
ZX = zxingcpp.BarcodeFormat

LAYOUT_COUNTS = {"single": 7, "sheet": 5, "multi": 5, "labelled": 6, "negative": 2}


def layout_cycle() -> list[str]:
    """The 25-slot layout cycle, each layout spread evenly through it."""
    slots = [((k + 0.5) / n, name) for name, n in LAYOUT_COUNTS.items() for k in range(n)]
    return [name for _, name in sorted(slots)]


LAYOUTS = layout_cycle()

# --------------------------------------------------------------------------- #
# Check digits and payloads
# --------------------------------------------------------------------------- #

OCR_DIGIT_LOOKALIKES = set("OQDIZSBG")  # uppercase letters labels.rs digitise() maps to digits
SERIAL_LETTERS = [c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in OCR_DIGIT_LOOKALIKES]
DIGITS = "0123456789"


def luhn_valid(digits: str) -> bool:
    """za.rs luhn_valid: from the right, double every second digit."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def luhn_complete(body: str) -> str:
    return next(body + c for c in DIGITS if luhn_valid(body + c))


def gtin_check(body: str) -> str:
    s = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return str((10 - s % 10) % 10)


def upce_to_upca(upce8: str) -> str:
    """ZXing's convertUPCEtoUPCA: 8-digit UPC-E -> 12-digit UPC-A."""
    ns, d, check = upce8[0], upce8[1:7], upce8[7]
    last = d[5]
    if last in "012":
        mid = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        mid = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        mid = d[0:4] + "00000" + d[4]
    else:
        mid = d[0:5] + "0000" + last
    return ns + mid + check


def digits(rng: np.random.Generator, n: int) -> str:
    return "".join(DIGITS[int(i)] for i in rng.integers(0, 10, n))


def chars(rng: np.random.Generator, alphabet: str, n: int) -> str:
    return "".join(alphabet[int(i)] for i in rng.integers(0, len(alphabet), n))


def make_imei(rng: np.random.Generator) -> str:
    """15 digits, Luhn-valid, with a TAC-like reporting-body prefix."""
    prefix = str(rng.choice(["35", "86", "01", "99", "35"]))
    return luhn_complete(prefix + digits(rng, 12))


def make_serial(rng: np.random.Generator) -> str:
    """An alphanumeric serial whose letters OCR cannot mistake for digits."""
    L = "".join(SERIAL_LETTERS)
    style = int(rng.integers(0, 3))
    if style == 0:  # R58N12ABCDE-like
        return chars(rng, "RHL", 1) + digits(rng, 2) + chars(rng, L, 1) + digits(rng, 2) + chars(rng, L, 5)
    if style == 1:  # 12 mixed characters, at least 3 letters
        while True:
            s = chars(rng, L + DIGITS, 12)
            if sum(c.isalpha() for c in s) >= 3 and s[0].isalpha():
                return s
    return chars(rng, L, 2) + digits(rng, 8) + chars(rng, L, 2)


def make_ean13(rng: np.random.Generator, prefix: str | None = None) -> str:
    body = prefix or str(int(rng.integers(1, 10)))
    body += digits(rng, 12 - len(body))
    return body + gtin_check(body)


WORDS = ("alpha bravo delta echo kilo lima metro nova orbit pixel quartz radio sierra tango "
         "ultra vector whisky yankee zulu amber cobalt ember fjord grove harbor indigo jasper").split()

C39 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-."
C93 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. "
C128 = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789-/"
QR_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -./:"
TEXTY = "abcdefghijklmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ0123456789 -_/.:;,=+#"


def linear_length(rng: np.random.Generator, short: tuple[int, int], long: tuple[int, int]) -> int:
    lo, hi = short if rng.random() < 0.6 else long
    return int(rng.integers(lo, hi + 1))


def qr_payload(rng: np.random.Generator, n: int) -> str:
    kind = int(rng.integers(0, 4))
    if kind == 0:
        s = "https://example.test/" + chars(rng, "abcdefghijkmnopqrstuvwxyz0123456789/-", max(1, n))
    elif kind == 1:
        s = chars(rng, QR_ALNUM, n)
    elif kind == 2:
        s = digits(rng, n)
    else:
        s = chars(rng, TEXTY, n)
    return s[:n].strip() or "X"


# --------------------------------------------------------------------------- #
# Symbols: a module matrix plus the payload and its expected decodes
# --------------------------------------------------------------------------- #


@dataclass
class Symbol:
    fmt: str            # scanner format name
    text: str           # what rxing returns
    matrix: np.ndarray  # bool, True = dark; linear codes are 1 x N
    zx_format: str      # what zxing-cpp reports, normalised the scanner's way
    zx_text: str
    row_aspect: float = 1.0  # module height / width for each matrix row (PDF417: its row ratio)
    quiet: int = 4
    info: dict = field(default_factory=dict)
    ecc_frac: float = 0.0  # rough fraction of the symbol that error correction can absorb


def norm_format(f: object) -> str:
    return str(f).lower().replace(" ", "").replace("-", "").replace("_", "")


def matrix_from_image(img: np.ndarray, mx: float, my: float | None) -> np.ndarray:
    """Samples module centres of a rendered symbol (dark-pixel bounding box);
    `my=None` samples one row at mid-height (a linear code)."""
    dark = img < 128
    ys, xs = np.where(dark)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    my = my or float(y1 - y0)
    nx, ny = (x1 - x0) / mx, (y1 - y0) / my
    assert abs(nx - round(nx)) < 1e-6 and abs(ny - round(ny)) < 1e-6, (nx, ny)
    cx = (x0 + (np.arange(round(nx)) + 0.5) * mx).astype(int)
    cy = (y0 + (np.arange(round(ny)) + 0.5) * my).astype(int)
    return dark[np.ix_(cy, cx)]


def zx_matrix(fmt: zxingcpp.BarcodeFormat, data: str, **kw) -> np.ndarray:
    a = np.array(zxingcpp.create_barcode(data, fmt, **kw).to_image(scale=1, add_quiet_zones=False)) < 128
    return a


def sym_qr(rng: np.random.Generator, tier: str) -> Symbol:
    vmax = {"easy": 6, "medium": 10, "hard": 15}[tier]
    version = int(rng.integers(1, vmax + 1))
    error = str(rng.choice(["l", "m", "q", "h"]))
    seed_text = qr_payload(rng, 400)

    def fits(n: int) -> bool:
        try:
            segno.make_qr(seed_text[:n].strip() or "X", version=version, error=error, boost_error=False)
            return True
        except segno.DataOverflowError:
            return False

    lo, hi = 1, len(seed_text)
    while lo < hi:  # largest prefix that fits this version
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid - 1)
    n = int(rng.integers(max(1, int(lo * 0.45)), lo + 1))
    text = seed_text[:n].strip() or "X"
    q = segno.make_qr(text, version=version, error=error, boost_error=False)
    m = np.array([list(r) for r in q.matrix], bool)
    frac = {"l": 0.07, "m": 0.15, "q": 0.25, "h": 0.30}[error]
    return Symbol("qrcode", text, m, "qrcode", text, quiet=4, info={"version": version, "ecc": error.upper()}, ecc_frac=frac)


def sym_datamatrix(rng: np.random.Generator, tier: str) -> Symbol:
    nmax = {"easy": 30, "medium": 70, "hard": 110}[tier]
    text = chars(rng, TEXTY, int(rng.integers(1, nmax + 1))).strip() or "DM"
    m = zx_matrix(ZX.DataMatrix, text)
    return Symbol("datamatrix", text, m, "datamatrix", text, quiet=2,
                  info={"size": f"{m.shape[0]}x{m.shape[1]}"}, ecc_frac=0.18)


def sym_aztec(rng: np.random.Generator, tier: str) -> Symbol:
    nmax = {"easy": 25, "medium": 60, "hard": 100}[tier]
    text = chars(rng, TEXTY, int(rng.integers(1, nmax + 1))).strip() or "AZ"
    ec = int(rng.integers(23, 51))
    m = zx_matrix(ZX.Aztec, text, ec_level=str(ec))
    return Symbol("aztec", text, m, "aztec", text, quiet=2, info={"size": m.shape[0], "ec_pct": ec}, ecc_frac=ec / 200)


def sym_pdf417(rng: np.random.Generator, tier: str) -> Symbol:
    cols = int(rng.integers(3, 16))
    security = int(rng.integers(2, 6))
    nmax = {"easy": 80, "medium": 180, "hard": 300}[tier]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 |-./abcdefghijklmnopqrstuvwxyz"
    n = int(rng.integers(8, nmax + 1))
    text = chars(rng, alphabet, n).strip() or "PDF417"
    while True:
        try:
            img = np.array(synth.render_pdf417(text, columns=cols, scale=2, ratio=3, security=security))
            break
        except ValueError as e:
            if "Minimum" in str(e):  # fewer than 3 rows: narrower
                cols = max(1, cols - 2)
            else:  # more than 90 rows: shorter
                text = text[: max(4, len(text) * 2 // 3)].strip() or "PDF417"
    m = matrix_from_image(img, 2, 6)
    return Symbol("pdf417", text, m, "pdf417", text, row_aspect=3.0, quiet=2,
                  info={"columns": cols, "rows": m.shape[0], "security": security},
                  ecc_frac=min(0.3, 2 ** security / (cols * m.shape[0])))  # half the EC codewords


ZX_LINEAR = {"code128": ZX.Code128, "code39": ZX.Code39, "ean13": ZX.EAN13, "ean8": ZX.EAN8, "upca": ZX.UPCA}


def sym_python_barcode(kind: str, data: str, fmt: str, text: str, zx_format: str, zx_text: str) -> Symbol:
    """python-barcode's rendering, checked; zxing-cpp's writer when it is wrong
    (python-barcode encodes a Code 128 payload starting "99" as a Code C shift)."""
    img = np.array(synth.render_linear(kind, data, module_px=3, height_px=60))
    m = matrix_from_image(img, 3, None)
    sym = Symbol(fmt, text, m.reshape(1, -1), zx_format, zx_text, quiet=10, info={"encoder": "python-barcode"})
    if not decodes(draw_symbol(sym, 3)[0], sym):
        sym = sym_zx_linear(ZX_LINEAR[kind], data, fmt, text, zx_format, zx_text)
        sym.info = {"encoder": "zxing-cpp"}
    return sym


def sym_zx_linear(zfmt: zxingcpp.BarcodeFormat, data: str, fmt: str, text: str, zx_format: str, zx_text: str) -> Symbol:
    a = zx_matrix(zfmt, data)
    return Symbol(fmt, text, a[a.shape[0] // 2].reshape(1, -1), zx_format, zx_text, quiet=10)


def sym_linear(rng: np.random.Generator, fmt: str, tier: str) -> Symbol:
    if fmt == "code128":
        t = chars(rng, C128, linear_length(rng, (3, 12), (13, 32 if tier == "hard" else 22)))
        return sym_python_barcode("code128", t, fmt, t, "code128", t)
    if fmt == "code39":
        t = chars(rng, C39, linear_length(rng, (3, 8), (9, 18 if tier == "hard" else 13))).strip(".")
        t = t or "C39"
        return sym_python_barcode("code39", t, fmt, t, "code39", t)
    if fmt == "code93":
        t = chars(rng, C93, linear_length(rng, (3, 10), (11, 24))).strip() or "C93"
        return sym_zx_linear(ZX.Code93, t, fmt, t, "code93", t)
    if fmt == "codabar":
        start, stop = (str(rng.choice(list("ABCD"))) for _ in range(2))
        t = chars(rng, "0123456789-$:/.+", linear_length(rng, (4, 10), (11, 20)))
        return sym_zx_linear(ZX.Codabar, start + t + stop, fmt, t, "codabar", start + t + stop)
    if fmt == "itf":
        t = digits(rng, 2 * linear_length(rng, (3, 7), (8, 12)))
        return sym_zx_linear(ZX.ITF, t, fmt, t, "itf", t)
    if fmt == "ean13":
        t = make_ean13(rng, str(rng.choice(["600", "601", "4", "5", "7", "9"])))
        return sym_python_barcode("ean13", t[:12], fmt, t, "ean13", t)
    if fmt == "ean8":
        b = digits(rng, 7)
        t = b + gtin_check(b)
        return sym_python_barcode("ean8", b, fmt, t, "ean8", t)
    if fmt == "upca":
        b = digits(rng, 11)
        t = b + gtin_check(b)
        return sym_python_barcode("upca", b, fmt, t, "ean13", "0" + t)
    if fmt == "upce":
        while True:  # zero-suppression rules forbid some bodies (e.g. ...X4 with X = 0)
            b = "0" + digits(rng, 6)
            t = b + gtin_check(upce_to_upca(b + "0")[:11])  # the check digit is the UPC-A expansion's
            try:
                return sym_zx_linear(ZX.UPCE, b, fmt, t, "upce", "0" + upce_to_upca(t))
            except ValueError:
                continue
    raise ValueError(fmt)


def make_symbol(rng: np.random.Generator, fmt: str, tier: str) -> Symbol:
    makers = {"qrcode": sym_qr, "datamatrix": sym_datamatrix, "aztec": sym_aztec, "pdf417": sym_pdf417}
    sym = makers[fmt](rng, tier) if fmt in makers else sym_linear(rng, fmt, tier)
    canvas, _ = draw_symbol(sym, 4 if sym.fmt not in LINEAR else 3)
    assert decodes(canvas, sym), f"clean render does not decode: {sym.fmt} {sym.text!r}"
    return sym


def symbol_from_text(fmt: str, text: str) -> Symbol:
    """A Code 128 / Code 39 / EAN-13 symbol for a given payload (labels)."""
    if fmt == "code128":
        sym = sym_python_barcode("code128", text, fmt, text, "code128", text)
    elif fmt == "code39":
        sym = sym_python_barcode("code39", text, fmt, text, "code39", text)
    elif fmt == "ean13":
        sym = sym_python_barcode("ean13", text[:12], fmt, text, "ean13", text)
    else:
        raise ValueError(fmt)
    canvas, _ = draw_symbol(sym, 3)
    assert decodes(canvas, sym), f"clean render does not decode: {fmt} {text!r}"
    return sym


# zxing-cpp reads some Code 39 symbols as Code 32 (Italian pharmacode) or PZN, which
# rxing does not know; read Code 39 as plain Code 39 only.
READ_AS = {"code39": ZX.Code39Std}


def decodes(img: np.ndarray, sym: Symbol) -> bool:
    kw = {"formats": READ_AS[sym.fmt]} if sym.fmt in READ_AS else {}
    for r in zxingcpp.read_barcodes(img, **kw):
        if norm_format(r.format) == sym.zx_format and r.text == sym.zx_text:
            return True
    return False


def draw_symbol(sym: Symbol, m: int, bar_modules: float | None = None) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """The symbol at m px per module with its quiet zone: (L image, symbol rect x0 y0 x1 y1)."""
    if sym.fmt in LINEAR:
        n = sym.matrix.shape[1]
        h = max(m * 12, int(round((bar_modules or max(24.0, 0.3 * n)) * m)))
        img = np.repeat(np.repeat(sym.matrix, h, 0), m, 1)
    else:
        rh = int(round(sym.row_aspect * m))
        img = np.repeat(np.repeat(sym.matrix, rh, 0), m, 1)
    img = np.where(img, 0, 255).astype(np.uint8)
    q = sym.quiet * m
    qy = 2 * m if sym.fmt in LINEAR else q  # bars need their quiet zone only at the ends
    img = np.pad(img, ((qy, qy), (q, q)), constant_values=255)
    return img, (q, qy, img.shape[1] - q, img.shape[0] - qy)


# --------------------------------------------------------------------------- #
# Per-code conditions, applied to the print (before the camera)
# --------------------------------------------------------------------------- #


@dataclass
class Code:
    """A printed code: its canvas at sheet resolution and where the symbol is on it."""
    sym: Symbol
    canvas: np.ndarray  # L uint8, sheet resolution
    corners: np.ndarray  # 4x2 symbol corners TL TR BR BL in canvas px (reading orientation)
    module_vecs: tuple[np.ndarray, np.ndarray]  # canvas px per module along symbol x and y
    tags: list[str]
    printed_decodable: bool


def low_contrast(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    hi = float(rng.uniform(150, 225))
    lo = hi - float(rng.uniform(0.15, 0.40)) * 255
    return (lo + (hi - lo) * img.astype(np.float32) / 255).astype(np.uint8)


def scratch(img: np.ndarray, rng: np.random.Generator, rect, m: int, linear: bool) -> None:
    """1-3 thin lines across the bars: along the code's length for 1-D codes."""
    x0, y0, x1, y1 = rect
    for _ in range(int(rng.integers(1, 4))):
        if linear:
            ya, yb = rng.uniform(y0, y1, 2)
            p, q = (int(x0 - 5 * m), int(ya)), (int(x1 + 5 * m), int(yb))
        else:
            p = (int(rng.uniform(x0, x1)), int(y0 - m))
            q = (int(rng.uniform(x0, x1)), int(y1 + m))
            if rng.random() < 0.5:
                p, q = (int(x0 - m), int(rng.uniform(y0, y1))), (int(x1 + m), int(rng.uniform(y0, y1)))
        colour = 255 if rng.random() < 0.6 else 30
        cv2.line(img, p, q, colour, max(1, int(m * rng.uniform(0.3, 0.9))), cv2.LINE_AA)


def blot(img: np.ndarray, rng: np.random.Generator, rect, area_frac: float, centred: bool) -> None:
    """An ink blot (dark ellipse) or a light sticker over `area_frac` of the symbol."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    a = area_frac * w * h
    aspect = float(rng.uniform(0.6, 1.6))
    if centred:
        cx, cy = x0 + w * rng.uniform(0.35, 0.65), y0 + h * rng.uniform(0.35, 0.65)
    else:  # interior, clear of the edges where finder patterns live
        cx, cy = x0 + w * rng.uniform(0.3, 0.75), y0 + h * rng.uniform(0.3, 0.75)
    if rng.random() < 0.5:
        rx = math.sqrt(a * aspect / math.pi)
        cv2.ellipse(img, (int(cx), int(cy)), (int(rx), int(rx / aspect)), float(rng.uniform(0, 180)), 0, 360,
                    int(rng.integers(0, 60)), -1, cv2.LINE_AA)
    else:
        sw, sh = math.sqrt(a * aspect), math.sqrt(a / aspect)
        box = cv2.boxPoints(((cx, cy), (sw, sh), float(rng.uniform(-20, 20)))).astype(np.int32)
        cv2.fillConvexPoly(img, box, int(rng.integers(225, 256)), cv2.LINE_AA)


def occlude_linear(img: np.ndarray, rng: np.random.Generator, rect, frac: float) -> None:
    """A sticker over the full bar height across `frac` of the code's width."""
    x0, y0, x1, y1 = rect
    w = (x1 - x0) * frac
    s = x0 + (x1 - x0 - w) * rng.uniform(0.2, 0.8)
    cv2.rectangle(img, (int(s), int(y0 - 4)), (int(s + w), int(y1 + 4)), int(rng.integers(225, 256)), -1)


def apply_damage(base: np.ndarray, rng: np.random.Generator, sym: Symbol, rect, m: int, beyond: bool) -> tuple[np.ndarray, bool]:
    """Damages a print and reports whether it still decodes. Within budget it retries
    with less damage until it decodes; beyond budget with more until it does not."""
    linear = sym.fmt in LINEAR
    frac = (rng.uniform(0.28, 0.45) if linear else rng.uniform(1.6, 2.4) * max(sym.ecc_frac, 0.12)) if beyond \
        else rng.uniform(0.3, 0.6) * max(sym.ecc_frac, 0.08)
    out, ok = base, True
    for _ in range(4):
        out = base.copy()
        if beyond:
            occlude_linear(out, rng, rect, frac) if linear else blot(out, rng, rect, min(frac, 0.6), centred=True)
        elif linear or rng.random() < 0.5:
            scratch(out, rng, rect, m, linear)
        else:
            blot(out, rng, rect, frac, centred=False)
        ok = decodes(out, sym)
        if ok != beyond:
            break
        frac = frac * 1.3 if beyond else frac * 0.5
    return out, ok


def rot90_point(p: np.ndarray, w: int, h: int) -> np.ndarray:
    """Where a point lands after np.rot90 (counter-clockwise) of a w x h image."""
    return np.array([p[1], w - p[0]], np.float64)


def print_code(rng: np.random.Generator, sym: Symbol, module_sheet: float, *, rot_k: int = 0,
               inverted: bool = False, contrast: bool = False, damage: str | None = None,
               bar_modules: float | None = None) -> Code:
    """Renders a symbol at its base resolution, applies print conditions, verifies the
    decode, and scales it to `module_sheet` px per module at sheet resolution."""
    tags = []
    m = max(3, math.ceil(module_sheet))
    base, rect = draw_symbol(sym, m, bar_modules)
    ok = True
    if inverted:
        base = 255 - base
        tags.append("inverted")
    if contrast:
        base = low_contrast(base, rng)
        tags.append("low_contrast")
    if damage:
        base, ok = apply_damage(base, rng, sym, rect, m, beyond=damage == "beyond")
        tags.append("damaged")
    elif inverted or contrast:
        ok = decodes(base, sym)
    scale = module_sheet / m
    if scale < 1:
        nw, nh = max(1, round(base.shape[1] * scale)), max(1, round(base.shape[0] * scale))
        canvas = cv2.resize(base, (nw, nh), interpolation=cv2.INTER_AREA)
        sx, sy = nw / base.shape[1], nh / base.shape[0]
    else:
        canvas, sx, sy = base, 1.0, 1.0
    x0, y0, x1, y1 = rect
    corners = np.array([[x0 * sx, y0 * sy], [x1 * sx, y0 * sy], [x1 * sx, y1 * sy], [x0 * sx, y1 * sy]])
    nrows = sym.matrix.shape[0]
    for _ in range(rot_k % 4):
        h, w = canvas.shape
        corners = np.array([rot90_point(p, w, h) for p in corners])
        canvas = np.ascontiguousarray(np.rot90(canvas))
    u = (corners[1] - corners[0]) / sym.matrix.shape[1]
    v = (corners[3] - corners[0]) / (nrows if sym.fmt not in LINEAR else 1)
    if sym.fmt == "pdf417":
        v = v / sym.row_aspect
    return Code(sym, canvas, corners, (u, v), tags, ok)


# --------------------------------------------------------------------------- #
# Sheets and stickers
# --------------------------------------------------------------------------- #

PAPERS = [(246, 247, 248), (236, 240, 242), (224, 233, 240), (215, 222, 226), (200, 225, 240)]  # BGR


@dataclass
class Sheet:
    image: np.ndarray  # BGR uint8
    codes: list[tuple[Code, np.ndarray]]  # code and its canvas origin on the sheet
    fields: list[dict] = field(default_factory=list)


def paper(rng: np.random.Generator, w: int, h: int, colour=None) -> np.ndarray:
    c = np.array(colour or PAPERS[int(rng.integers(0, len(PAPERS)))], np.float32)
    tex = (rng.random((h, w), np.float32) - 0.5) * 6
    return np.clip(c[None, None, :] + tex[..., None], 0, 255).astype(np.uint8)


def paste(sheet: np.ndarray, canvas: np.ndarray, x: int, y: int) -> None:
    h, w = canvas.shape
    sheet[y:y + h, x:x + w] = canvas[..., None]


def pack_sheet(rng: np.random.Generator, codes: list[Code], max_w: int) -> Sheet:
    """Shelf-packs code canvases left to right, row by row, with margins."""
    gap = int(rng.integers(20, 60))
    x = y = gap
    row_h = 0
    places = []
    width = 0
    for c in codes:
        h, w = c.canvas.shape
        if x + w + gap > max_w and x > gap:
            x, y = gap, y + row_h + gap
            row_h = 0
        jitter = int(rng.integers(0, gap // 2 + 1))
        places.append((x, y + jitter))
        x += w + gap
        row_h = max(row_h, h + jitter)
        width = max(width, x)
    img = paper(rng, width, y + row_h + gap)
    out = []
    for c, (px, py) in zip(codes, places):
        paste(img, c.canvas, px, py)
        out.append((c, np.array([px, py], np.float64)))
    return Sheet(img, out)


def font(size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, max(6, int(round(size))))


# --------------------------------------------------------------------------- #
# Labelled stickers (device box / shipping label)
# --------------------------------------------------------------------------- #

LABEL_PRINTS = {
    "IMEI1": ["IMEI1: ", "IMEI 1: ", "IMEI1 "],
    "IMEI2": ["IMEI2: ", "IMEI 2: ", "IMEI2 "],
    "SN": ["S/N: ", "SN: ", "SN "],
    "EAN": ["EAN: "],
}
DIGITISE = {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
            "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "G": "6", "b": "6"}


def scanner_label(printed: str) -> str:
    """labels.rs normalise_label, for the label part of a printed line."""
    lab = "".join(c.upper() for c in printed if c.isascii() and c.isalnum())
    for p in ("IMEL", "1MEI", "IME1"):
        if lab.startswith(p):
            lab = "IMEI" + lab[4:]
            break
    if lab.startswith("IMEI"):
        lab = "IMEI" + "".join(DIGITISE.get(c, c) for c in lab[4:] if not c.isspace())
    return lab


@dataclass
class Block:
    """One labelled item laid out on its own: a white tile with text and at most one code."""
    image: np.ndarray  # BGR
    code: tuple[Code, np.ndarray] | None
    truth: dict  # the field's truth record


def text_size(f: ImageFont.FreeTypeFont, s: str) -> tuple[int, int]:
    b = f.getbbox(s)
    return b[2] - b[0], b[3] - b[1]


def draw_text(img: np.ndarray, xy: tuple[int, int], s: str, f: ImageFont.FreeTypeFont, ink: int) -> np.ndarray:
    pil = Image.fromarray(img)
    ImageDraw.Draw(pil).text(xy, s, font=f, fill=(ink, ink, ink), anchor="lt")
    return np.array(pil)


def make_block(rng: np.random.Generator, kind: str, em: float, ctx: dict) -> Block:
    """Builds one item. kinds: imei_above, imei_left, sn_above, sn_below, ean_below,
    ean_above, unreadable, text_only, none (an unlabelled code)."""
    f = font(em)
    ink = int(rng.integers(10, 60))
    line_h = int(em * 1.25)
    m_lo, m_hi = ctx["module_range"]
    module = float(rng.uniform(m_lo, m_hi)) * K
    bar_modules = float(rng.uniform(2.0, 3.2)) * em / module
    label = value = fmt = None
    printed = None

    if kind in ("imei_above", "imei_left", "unreadable"):
        label = ctx["next_imei"]()
        value = make_imei(rng)
        fmt = "code128"
        if label is None:  # a sticker has at most IMEI1 and IMEI2: the rest are serials
            kind = {"imei_above": "sn_above", "imei_left": "sn_below"}.get(kind, kind)
            label, value = "SN", make_serial(rng)
    elif kind in ("sn_above", "sn_below"):
        label, value = "SN", make_serial(rng)
        fmt = "code128" if rng.random() < 0.7 else "code39"
    elif kind in ("ean_below", "ean_above"):
        label = None if kind == "ean_below" else "EAN"
        value = make_ean13(rng, str(rng.choice(["600", "601", "6", "5"])))
        fmt = "ean13"
        bar_modules = float(rng.uniform(40, 70))
    elif kind == "text_only":
        label = ctx["next_imei"]() if rng.random() < 0.4 else None
        label, value = (label, make_imei(rng)) if label else ("SN", make_serial(rng))
    if kind == "unreadable":
        module = float(rng.uniform(0.45, 0.72)) * K
        bar_modules = float(rng.uniform(2.0, 3.0)) * em / module
        if label != "SN" and rng.random() < 0.3:
            label, value = "SN", make_serial(rng)
    if label is not None:
        printed = str(rng.choice(LABEL_PRINTS[label]))
        assert scanner_label(printed.strip().rstrip(":")) == label, (printed, label)

    code = None
    if kind == "none":
        fmt = str(rng.choice(["qrcode", "datamatrix", "code128", "qrcode"]))
        if fmt == "code128":
            sym = symbol_from_text("code128", chars(rng, C128, int(rng.integers(6, 16))))
        else:
            sym = make_symbol(rng, fmt, "easy")
            module = float(rng.uniform(max(m_lo, 1.6), max(m_hi, 2.6))) * K
        value = sym.text
        code = print_code(rng, sym, module, bar_modules=bar_modules)
    elif fmt is not None:
        sym = symbol_from_text(fmt, value)
        code = print_code(rng, sym, module, bar_modules=bar_modules)

    pad = int(em * 0.5)
    gap = int(em * 0.35)
    if code is None:  # text-only line
        s = printed + value
        tw, _ = text_size(f, s)
        img = np.full((line_h + 2 * pad, tw + 2 * pad, 3), 255, np.uint8)
        img = draw_text(img, (pad, pad), s, f, ink)
        return Block(img, None, {"label": label, "value": value, "position": "none",
                                 "barcode_format": None, "barcode_decodable": False})

    ch, cw = code.canvas.shape
    sym_x0 = int(code.corners[:, 0].min())
    sym_x1 = int(code.corners[:, 0].max())
    if kind in ("imei_above", "sn_above", "unreadable", "ean_above"):
        s = printed + value
        tw, _ = text_size(f, s)
        W = max(cw, sym_x0 + tw) + 2 * pad
        H = pad + line_h + gap + ch + pad
        img = np.full((H, W, 3), 255, np.uint8)
        img = draw_text(img, (pad + sym_x0, pad), s, f, ink)
        origin = np.array([pad, pad + line_h + gap], np.float64)
        position = "above"
    elif kind in ("sn_below", "ean_below"):
        if kind == "ean_below":  # retail style: 6 001234 567893 under the bars
            s = f"{value[0]}  {value[1:7]}  {value[7:]}"
        else:
            s = printed + value
        tw, _ = text_size(f, s)
        W = max(cw, sym_x0 + tw) + 2 * pad
        H = pad + ch + gap + line_h + pad
        img = np.full((H, W, 3), 255, np.uint8)
        tx = pad + (sym_x0 + sym_x1 - tw) // 2 if kind == "ean_below" else pad + sym_x0
        sym_y1 = int(code.corners[:, 1].max())
        img = draw_text(img, (max(0, tx), pad + sym_y1 + gap), s, f, ink)
        origin = np.array([pad, pad], np.float64)
        position = "below"
    elif kind == "imei_left":  # bare label left of the bars, value under them
        lab = printed.strip()
        lab = lab if lab.endswith(":") else lab + ":"
        lw, _ = text_size(f, lab)
        tw, _ = text_size(f, value)
        left = pad + lw + int(em * 0.6)
        sym_y0, sym_y1 = int(code.corners[:, 1].min()), int(code.corners[:, 1].max())
        W = left + max(cw, sym_x0 + tw) + pad
        H = pad + ch + gap + line_h + pad
        img = np.full((H, W, 3), 255, np.uint8)
        img = draw_text(img, (pad, pad + (sym_y0 + sym_y1) // 2 - line_h // 2), lab, f, ink)
        img = draw_text(img, (left + sym_x0, pad + sym_y1 + gap), value, f, ink)
        origin = np.array([left, pad], np.float64)
        position = "left"
    else:
        W, H = cw + 2 * pad, ch + 2 * pad
        img = np.full((H, W, 3), 255, np.uint8)
        origin = np.array([pad, pad], np.float64)
        position = "none"
    paste(img, code.canvas, int(origin[0]), int(origin[1]))
    return Block(img, (code, origin), {"label": label, "value": value, "position": position,
                                       "barcode_format": code.sym.fmt, "barcode_decodable": None})


DEVICE_ITEMS = ["imei_above", "imei_above", "imei_left", "sn_above", "sn_below", "ean_below",
                "ean_above", "unreadable", "unreadable", "text_only", "none"]


def labelled_sticker(rng: np.random.Generator, em: float, n_items: int, ctx: dict, title: bool) -> Sheet:
    """A device-box or shipping-label sticker: items stacked in one or two columns."""
    kinds = [str(k) for k in rng.choice(DEVICE_ITEMS, n_items, replace=True)]
    imei_n = iter(["IMEI1", "IMEI2"])
    ctx = {**ctx, "next_imei": lambda: next(imei_n, None)}
    blocks = [make_block(rng, k, em, ctx) for k in kinds]
    ncols = 2 if n_items >= 4 and ctx["landscape"] else 1
    gap_y = int(em * rng.uniform(1.2, 2.0))
    gap_x = int(em * 2.5)
    pad = int(em * 1.0)
    cols = [blocks[i::ncols] for i in range(ncols)]
    col_w = [max(b.image.shape[1] for b in col) for col in cols]
    col_h = [sum(b.image.shape[0] for b in col) + gap_y * (len(col) - 1) for col in cols]
    head = int(em * 1.8) if title else 0
    W = sum(col_w) + gap_x * (ncols - 1) + 2 * pad
    H = max(col_h) + 2 * pad + head
    img = np.full((H, W, 3), 255, np.uint8)
    if title:
        name = f"{str(rng.choice(['XQ', 'ZT', 'NV', 'KR']))}-{int(rng.integers(100, 999))} " + \
            str(rng.choice(["SMARTPHONE", "TABLET", "HANDSET", "PHONE"])) + f" {int(rng.choice([64, 128, 256]))}GB"
        img = draw_text(img, (pad, pad // 2), name, font(em * 1.1, bold=True), 20)
    codes, fields = [], []
    x = pad
    for col, w in zip(cols, col_w):
        y = pad + head
        for b in col:
            h, bw = b.image.shape[:2]
            img[y:y + h, x:x + bw] = b.image
            if b.code:
                c, o = b.code
                codes.append((c, o + np.array([x, y], np.float64)))
                b.truth["_code"] = len(codes) - 1
            fields.append(b.truth)
            y += h + gap_y
        x += w + gap_x
    # off-white sticker stock
    tint = np.array(PAPERS[int(rng.integers(0, 3))], np.float32) / 255
    img = (img.astype(np.float32) * tint).astype(np.uint8)
    return Sheet(img, codes, fields)


# --------------------------------------------------------------------------- #
# Placement: sheets in the frame
# --------------------------------------------------------------------------- #


ROTATION_MIX = {  # (upright +-8, exact 90/180/270, moderate +-25, any angle) per tier
    "easy": (0.7, 0.3, 0.0, 0.0),
    "medium": (0.45, 0.2, 0.2, 0.15),
    "hard": (0.25, 0.15, 0.25, 0.35),
}


def sample_rotation(rng: np.random.Generator, tier: str, profile: str) -> tuple[float, str]:
    """In-plane rotation of a sheet. ZXing-family 1-D readers scan rows (and columns),
    so a linear code turned off-axis decodes only if its bars are tall enough for one
    scan line to cross them all: arbitrary angles are kept for the harder tiers."""
    if profile == "labelled":  # OCR reads upright print: device labels are photographed square-on
        return (float(rng.uniform(-4, 4)), "upright") if rng.random() < 0.75 else (float(rng.uniform(-10, 10)), "rot_moderate")
    kind = int(rng.choice(4, p=ROTATION_MIX[tier]))
    if kind == 0:
        return float(rng.uniform(-8, 8)), "upright"
    if kind == 1:
        return float(rng.choice([90.0, 180.0, 270.0])), "rot_right_angle"
    if kind == 2:
        return float(rng.uniform(-25, 25)) + float(rng.choice([0.0, 90.0, 180.0, 270.0])), "rot_moderate"
    return float(rng.uniform(0, 360)), "rot_any"


def sample_tilt(rng: np.random.Generator, tier: str, profile: str) -> tuple[float, float, str]:
    limit = {"easy": 12, "medium": 25, "hard": 40 if rng.random() < 0.3 else 25}[tier]
    if profile == "labelled":
        limit = min(limit, 25)
    rx, ry = (float(rng.uniform(-limit, limit)) for _ in range(2))
    worst = max(abs(rx), abs(ry))
    return rx, ry, ("tilt_strong" if worst > 25 else "tilt_moderate" if worst > 12 else "tilt_mild")


def sheet_homography(w: int, h: int, corners: np.ndarray) -> np.ndarray:
    src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    return cv2.getPerspectiveTransform(src, corners.astype(np.float32))


def apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), H).reshape(-1, 2)


def polygons_overlap(a: np.ndarray, b: np.ndarray, pad: float = 1.06) -> bool:
    def grow(p):
        c = p.mean(0)
        return ((p - c) * pad + c).astype(np.float32)
    area, _ = cv2.intersectConvexConvex(grow(a), grow(b))
    return area > 0


def place_sheet(rng: np.random.Generator, sheet: Sheet, frame: tuple[int, int], tier: str, profile: str,
                placed: list[np.ndarray], scale: float = 1 / K, min_shrink: float = 0.35):
    """Finds a pose putting the whole sheet in frame without touching earlier sheets.
    Returns (corners, pose dict, tags) or None."""
    fw, fh = frame
    h, w = sheet.image.shape[:2]
    rz, rot_tag = sample_rotation(rng, tier, profile)
    shrink = 1.0
    while shrink >= min_shrink:
        for _ in range(30):
            rx, ry, tilt_tag = sample_tilt(rng, tier, profile)
            pose = {"rx": rx, "ry": ry, "rz": rz, "width_frac": scale * shrink * w / fw,
                    "cx": float(rng.uniform(0.12, 0.88)), "cy": float(rng.uniform(0.12, 0.88))}
            c = augment.project_corners(w, h, frame_w=fw, frame_h=fh, **pose)
            mx, my = 0.01 * fw, 0.01 * fh
            if c[:, 0].min() < mx or c[:, 0].max() > fw - mx or c[:, 1].min() < my or c[:, 1].max() > fh - my:
                continue
            if any(polygons_overlap(c, p) for p in placed):
                continue
            return c, {k: round(v, 3) for k, v in pose.items()} | {"shrink": round(shrink, 3)}, [rot_tag, tilt_tag]
        shrink *= 0.88
    return None


def module_in_frame(H: np.ndarray, code: Code, origin: np.ndarray) -> float:
    """Smallest module length in frame px, at the four symbol corners."""
    c = code.corners + origin
    u, v = code.module_vecs
    use_v = code.sym.fmt not in LINEAR and code.sym.fmt != "pdf417"
    lengths = []
    for p, su, sv in zip(c, (1, -1, -1, 1), (1, 1, -1, -1)):
        q = apply_h(H, [p, p + su * u, p + sv * v])
        lengths.append(np.linalg.norm(q[1] - q[0]))
        if use_v:
            lengths.append(np.linalg.norm(q[2] - q[0]))
    return float(min(lengths))


# --------------------------------------------------------------------------- #
# Camera
# --------------------------------------------------------------------------- #


def curve_warp(img: np.ndarray, rng: np.random.Generator):
    """A gently curved surface: rows (or columns) displaced by a long sine.
    Returns the warped image and the forward point map."""
    h, w = img.shape[:2]
    amp = float(rng.uniform(4, 12))
    along_x = bool(rng.random() < 0.6)
    lam = float(rng.uniform(0.9, 2.0)) * (w if along_x else h)
    ph = float(rng.uniform(0, 2 * math.pi))
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    if along_x:
        mx, my = xs, ys - amp * np.sin(2 * math.pi * xs / lam + ph)
    else:
        mx, my = xs - amp * np.sin(2 * math.pi * ys / lam + ph), ys
    out = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def fwd(p: np.ndarray) -> np.ndarray:
        p = np.array(p, np.float64)
        if along_x:
            p[:, 1] += amp * np.sin(2 * math.pi * p[:, 0] / lam + ph)
        else:
            p[:, 0] += amp * np.sin(2 * math.pi * p[:, 1] / lam + ph)
        return p

    return out, fwd, {"amp": round(amp, 2), "axis": "x" if along_x else "y"}


def camera(rng: np.random.Generator, img: np.ndarray, tier: str, frame_tags: list[str], params: dict,
           glare_targets: list[tuple[np.ndarray, float]], profile: str):
    """Lighting, glare, blur, noise, motion blur, curvature. img is float BGR.
    Returns uint8 image and the point map for curvature (or None)."""
    if rng.random() < 0.6:
        strength = float(rng.uniform(0.2, 0.5))
        img = augment.uneven_lighting(img, rng, strength)
        frame_tags.append("uneven_light")
        params["light_strength"] = round(strength, 2)
    p_glare = {"easy": 0.1, "medium": 0.25, "hard": 0.4}[tier]
    if glare_targets and rng.random() < p_glare:
        centre, diag = glare_targets[int(rng.integers(0, len(glare_targets)))]
        r = diag * float(rng.uniform(0.2, 0.45))
        peak = float(rng.uniform(80, 200))
        img = augment.glare(img, (float(centre[0]), float(centre[1])), (r, r * float(rng.uniform(0.5, 1))), peak,
                            float(rng.uniform(0, math.pi)))
        frame_tags.append("glare")
        params["glare"] = {"centre": [round(float(centre[0]), 1), round(float(centre[1]), 1)], "radius": round(r, 1),
                           "peak": round(peak, 1)}
    elif rng.random() < 0.15:
        h, w = img.shape[:2]
        img = augment.glare(img, (float(rng.uniform(0, w)), float(rng.uniform(0, h))),
                            (float(rng.uniform(50, 150)), float(rng.uniform(30, 90))), float(rng.uniform(60, 140)),
                            float(rng.uniform(0, math.pi)))
        frame_tags.append("glare_background")
    lo, hi = {"easy": (0.3, 0.8), "medium": (0.4, 1.0), "hard": (0.5, 1.2)}[tier]
    if tier == "hard" and rng.random() < 0.1:
        lo, hi = 1.5, 2.5
    if profile == "labelled":
        lo, hi = min(lo, 1.2), min(hi, 1.5)
    blur = float(rng.uniform(lo, hi))
    if blur >= 1.0:
        frame_tags.append("blur_heavy" if blur >= 1.8 else "blur")
    noise = float(rng.uniform(2, 6)) if rng.random() < 0.75 or tier == "easy" else float(rng.uniform(8, 16))
    if noise >= 8:
        frame_tags.append("noise")
    params["blur_sigma"], params["noise_sigma"] = round(blur, 2), round(noise, 2)
    out = augment.finish(img, rng, blur, noise)
    p_motion = {"easy": 0.0, "medium": 0.12, "hard": 0.25}[tier]
    if rng.random() < p_motion:
        length = int(rng.integers(3, 7 if tier == "medium" else 10))
        ang = float(rng.uniform(0, 180))
        out = augment.motion_blur(out, length, ang)
        frame_tags.append("motion_blur")
        params["motion_blur"] = {"length": length, "angle_deg": round(ang, 1)}
    warp = None
    if tier != "easy" and rng.random() < 0.08:
        out, warp, params["curve"] = curve_warp(out, rng)
        frame_tags.append("curved")
    return out, warp


def encode(rng: np.random.Generator, img: np.ndarray, tier: str, frame_tags: list[str], params: dict) -> tuple[bytes, str]:
    if rng.random() < 0.05:
        frame_tags.append("png")
        ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        return buf.tobytes(), "png"
    lo = {"easy": 75, "medium": 55, "hard": 40}[tier]
    q = int(rng.integers(lo, 96))
    if q < 60:
        frame_tags.append("jpeg_low")
    params["jpeg_quality"] = q
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes(), "jpg"


# --------------------------------------------------------------------------- #
# Layouts
# --------------------------------------------------------------------------- #

# Print module targets in frame px; tilt, perspective and fitting make the measured
# module_px smaller (medians come out about 2.7 / 2.2 / 1.6 for these).
TIER_MODULE = {"easy": (3.0, 6.0), "medium": (2.4, 4.5), "hard": (1.7, 3.4)}


def pick_frame(rng: np.random.Generator) -> tuple[tuple[int, int], list[str]]:
    r = rng.random()
    if r < 0.45:
        return (1280, 720), []
    if r < 0.70:
        return (1920, 1080), ["hd"]
    if r < 0.85:
        return (720, 1280), ["portrait"]
    return (640, 480), ["low_res"]


def bar_height(rng: np.random.Generator, sym: Symbol) -> float:
    """Bar height in modules: EAN/UPC near their nominal 0.7 of the width, others lower."""
    n = sym.matrix.shape[1]
    lo, hi = (0.45, 0.8) if sym.fmt in ("ean13", "ean8", "upca", "upce") else (0.15, 0.5)
    return max(20.0, float(rng.uniform(lo, hi)) * n)


def random_code(rng: np.random.Generator, tier: str, frame: tuple[int, int], fit_frac: float, fmt: str | None = None) -> Code:
    """A random symbol with print conditions, sized for the tier and the frame."""
    fmt = fmt or FORMATS[int(rng.integers(0, len(FORMATS)))]
    hd = max(1.0, frame[0] / 1280)  # the scanner analyses at most 1280 px wide
    lo, hi = (v * hd for v in TIER_MODULE[tier])
    limit = fit_frac * min(frame)
    for _ in range(6):
        sym = make_symbol(rng, fmt, tier)
        n = sym.matrix.shape[1] + 2 * sym.quiet
        cap = (fit_frac * 1.6 * max(frame) if sym.fmt in LINEAR else limit) / n
        if cap >= lo:
            break
        tier = "easy"  # too big for the frame at this tier's modules: try a smaller payload
    unreadable = tier != "easy" and rng.random() < 0.05
    m_f = float(rng.uniform(0.4, 0.75)) if unreadable else min(float(rng.uniform(lo, hi)), cap)
    two_d = sym.fmt not in LINEAR
    damage = None
    if tier != "easy":
        r = rng.random()
        damage = "within" if r < 0.12 else "beyond" if r < 0.16 else None
    rot_k = int(rng.choice([0, 0, 0, 1, 2, 3])) if rng.random() < 0.6 else 0
    return print_code(rng, sym, m_f * K, rot_k=rot_k, inverted=two_d and rng.random() < 0.08,
                      contrast=tier != "easy" and rng.random() < 0.12, damage=damage,
                      bar_modules=bar_height(rng, sym) if not two_d else None)


def compose(rng: np.random.Generator, frame: tuple[int, int], sheets: list[Sheet], tier: str, profile: str,
            frame_tags: list[str], params: dict):
    """Places sheets, composites them on a background, runs the camera.
    Returns (uint8 image, codes truth list, field list)."""
    fw, fh = frame
    bg, bg_kind = augment.background(rng, fw, fh)
    params["background"] = bg_kind
    img = bg.astype(np.float32)
    placed, poses, records, fields = [], [], [], []
    for si, sheet in enumerate(sheets):
        res = place_sheet(rng, sheet, frame, tier, profile, placed)
        if res is None:
            if si == 0:
                raise RuntimeError("first sheet does not fit")
            continue
        corners, pose, ptags = res
        placed.append(corners)
        poses.append(pose)
        for t in ptags:
            if t not in frame_tags and t != "upright" and t != "tilt_mild":
                frame_tags.append(t)
        img = augment.composite(img, sheet.image, corners)
        h, w = sheet.image.shape[:2]
        H = sheet_homography(w, h, corners)
        first = len(records)
        for code, origin in sheet.codes:
            fc = apply_h(H, code.corners + origin)
            records.append({"code": code, "corners": fc, "module_px": module_in_frame(H, code, origin)})
        for fdef in sheet.fields:
            fdef = dict(fdef)
            if "_code" in fdef:
                fdef["_code"] = first + fdef["_code"]
            fields.append(fdef)
    params["sheets"] = poses
    if len(placed) > 1:
        frame_tags.append("multi_sheet")
    targets = [(r["corners"].mean(0), float(np.linalg.norm(r["corners"][2] - r["corners"][0]))) for r in records]
    out, warp = camera(rng, img, tier, frame_tags, params, targets, profile)
    glare_at = params.get("glare")
    codes = []
    for r in records:
        code: Code = r["code"]
        corners = warp(r["corners"]) if warp else r["corners"]
        tags = list(code.tags)
        if r["module_px"] < 1.3:
            tags.append("tiny")
        if glare_at:
            c = np.array(glare_at["centre"])
            if np.linalg.norm(r["corners"].mean(0) - c) < glare_at["radius"] + 1e-6:
                tags.append("glare")
        decodable = code.printed_decodable and r["module_px"] >= MIN_DECODABLE_MODULE
        if not decodable:
            tags.append("unreadable")
        info = code.sym.info
        if (code.sym.fmt == "qrcode" and info.get("version", 0) >= 10) or \
           (code.sym.fmt == "pdf417" and info.get("columns", 0) >= 10) or \
           (code.sym.fmt == "datamatrix" and code.sym.matrix.size >= 40 * 40):
            tags.append("dense")
        codes.append({"format": code.sym.fmt, "text": code.sym.text,
                      "corners": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
                      "module_px": round(r["module_px"], 2), "tags": tags, "decodable": decodable})
    for fdef in fields:
        if "_code" in fdef:
            fdef["barcode_decodable"] = codes[fdef.pop("_code")]["decodable"]
    return out, codes, fields


def layout_single(rng, frame, tier):
    code = random_code(rng, tier, frame, 0.55)
    return [pack_sheet(rng, [code], 10 ** 6)], "single"


def layout_sheet(rng, frame, tier):
    n = int(rng.integers(2, 5 if tier == "easy" else 9))
    codes = [random_code(rng, tier, frame, 0.6 / math.sqrt(n)) for _ in range(n)]
    return [pack_sheet(rng, codes, int(K * max(frame) * rng.uniform(0.55, 0.85)))], "sheet"


def layout_multi(rng, frame, tier):
    sheets = []
    budget = 8  # codes per frame at most
    for _ in range(int(rng.integers(2, 5))):
        k = min(int(rng.integers(1, 4)), budget)
        if k <= 0:
            break
        budget -= k
        codes = [random_code(rng, tier, frame, 0.32 / math.sqrt(k)) for _ in range(k)]
        sheets.append(pack_sheet(rng, codes, int(K * max(frame) * 0.4)))
    return sheets, "multi"


def layout_labelled(rng, frame, tier):
    fw, fh = frame
    em_f = float(rng.uniform(19, 26)) * max(1.0, fw / 1280)  # survives the scanner's 1280-px analysis
    m_lo, m_hi = {"easy": (2.2, 3.4), "medium": (1.6, 2.8), "hard": (1.2, 2.2)}[tier]
    ctx = {"module_range": (m_lo * max(1.0, fw / 1280), m_hi * max(1.0, fw / 1280)), "landscape": fw > fh}
    sheets = []
    n = int(rng.integers(3, 6))
    for attempt in range(6):  # fewer items until the sticker fits at its print size
        sheet = labelled_sticker(rng, em_f * K, n, ctx, title=rng.random() < 0.7)
        h, w = sheet.image.shape[:2]
        if w / K <= 0.92 * fw and h / K <= 0.85 * fh:
            break
        n = max(1, n - 1)
    sheets.append(sheet)
    if rng.random() < 0.25:
        sheets.append(labelled_sticker(rng, em_f * K, int(rng.integers(1, 3)), ctx, title=False))
    return sheets, "labelled", em_f


# Negatives ------------------------------------------------------------------


def neg_text_page(rng, w, h):
    img = paper(rng, w, h, (245, 245, 243))
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    size = int(rng.integers(18, 34))
    f, fb = font(size), font(size * 1.4, bold=True)
    y = size
    d.text((size * 2, y), " ".join(str(rng.choice(WORDS)).upper() for _ in range(3)), font=fb, fill=(20, 20, 20))
    y += int(size * 2.5)
    while y < h - size * 2:
        line = " ".join(str(rng.choice(WORDS)) for _ in range(int(rng.integers(4, 12))))
        d.text((size * 2, y), line.capitalize() + ".", font=f, fill=(30, 30, 30))
        y += int(size * rng.uniform(1.3, 1.8))
    return np.array(pil)


def neg_stripes(rng, w, h):
    """Bars of random widths: barcode-like but not a code."""
    img = paper(rng, w, h)
    x = int(rng.integers(10, 40))
    dark = int(rng.integers(0, 80))
    regular = rng.random() < 0.4
    period = int(rng.integers(4, 30))
    while x < w - 10:
        bw = period // 2 if regular else int(rng.integers(2, 24))
        img[:, x:x + bw] = dark
        x += bw + (period - period // 2 if regular else int(rng.integers(2, 24)))
    return img


def neg_blinds(rng, w, h):
    img = paper(rng, w, h, (200, 205, 210))
    period = int(rng.integers(14, 60))
    for y in range(0, h, period):
        cv2.rectangle(img, (0, y), (w, y + int(period * rng.uniform(0.15, 0.4))), (90, 95, 100), -1)
    if rng.random() < 0.5:  # a grille: add the other axis
        for x in range(0, w, period):
            cv2.rectangle(img, (x, 0), (x + int(period * 0.2), h), (90, 95, 100), -1)
    return img


def neg_keyboard(rng, w, h):
    img = np.full((h, w, 3), int(rng.integers(20, 60)), np.uint8)
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    key = w // 16
    f = font(key * 0.35)
    for r in range(max(1, h // key)):
        off = int(key * 0.25 * r)
        for c in range(16):
            x0, y0 = off + c * key + 4, r * key + 4
            d.rounded_rectangle((x0, y0, x0 + key - 8, y0 + key - 8), radius=6, fill=(60, 62, 66), outline=(90, 90, 95))
            d.text((x0 + key * 0.3, y0 + key * 0.25), "QWERTYUIOPASDFGHJKLZXCVBNM"[(r * 16 + c) % 26], font=f,
                   fill=(220, 220, 220))
    return np.array(pil)


def neg_spines(rng, w, h):
    img = np.zeros((h, w, 3), np.uint8)
    x = 0
    while x < w:
        bw = int(rng.integers(12, 70))
        img[:, x:x + bw] = rng.integers(20, 230, 3)
        cv2.line(img, (x + bw // 2, h // 5), (x + bw // 2, h // 3), (230, 230, 230), max(1, bw // 6))
        x += bw + int(rng.integers(1, 4))
    return img


NEGATIVES = {"text_page": neg_text_page, "stripes": neg_stripes, "blinds": neg_blinds, "keyboard": neg_keyboard,
             "spines": neg_spines, "desk": None, "wood": None}


def layout_negative(rng, frame, tier, frame_tags, params):
    fw, fh = frame
    for _ in range(5):  # the frame must hold no decodable code
        kind = str(rng.choice(list(NEGATIVES)))
        tags = list(frame_tags) + [f"negative_{kind}"]
        prm = dict(params)
        if NEGATIVES[kind] is None:
            img = augment.wood_background(rng, fw, fh) if kind == "wood" else augment.desk_background(rng, fw, fh)
            out, _ = camera(rng, img.astype(np.float32), tier, tags, prm, [], "negative")
        else:
            w, h = int(K * fw * rng.uniform(0.5, 0.8)), int(K * fh * rng.uniform(0.5, 0.8))
            sheet = Sheet(NEGATIVES[kind](rng, w, h), [])
            out, _, _ = compose(rng, frame, [sheet], tier, "negative", tags, prm)
        if not zxingcpp.read_barcodes(out):
            return out, tags, prm
    raise RuntimeError("could not make a negative without a decodable pattern")


# --------------------------------------------------------------------------- #
# One frame
# --------------------------------------------------------------------------- #


def generate_frame(job: tuple[str, int, int, str]) -> dict:
    split, seed, index, out_dir = job
    rng = np.random.default_rng([seed, index])
    layout = LAYOUTS[index % len(LAYOUTS)]
    frame, frame_tags = pick_frame(rng)
    tier = str(rng.choice(["easy", "medium", "hard"], p=[0.3, 0.45, 0.25]))
    params: dict = {}
    fields: list[dict] = []
    codes: list[dict] = []
    if layout == "negative":
        img, frame_tags, params = layout_negative(rng, frame, tier, frame_tags, params)
    else:
        if layout == "labelled":
            sheets, _, em_f = layout_labelled(rng, frame, tier)
            params["text_em_px"] = round(em_f, 1)
            frame_tags.append("labelled")
            profile = "labelled"
        else:
            sheets, _ = {"single": layout_single, "sheet": layout_sheet, "multi": layout_multi}[layout](rng, frame, tier)
            profile = "plain"
        out, codes, fields = compose(rng, frame, sheets, tier, profile, frame_tags, params)
        img = out
        if len(codes) > 1:
            frame_tags.append("multi_code")
    data, ext = encode(rng, img, tier, frame_tags, params)
    fid = f"bc_{split}_{index:05d}"
    rel = f"frames/{fid}.{ext}"
    (Path(out_dir) / rel).write_bytes(data)
    truth = {"id": fid, "image": rel, "size": [frame[0], frame[1]], "layout": layout, "difficulty": tier,
             "tags": frame_tags, "negative": layout == "negative", "params": params, "codes": codes}
    if layout == "labelled":
        truth["fields"] = fields
    return truth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--split", required=True, choices=sorted(SEEDS))
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None, help="override the split's seed")
    args = ap.parse_args()
    seed = SEEDS[args.split] if args.seed is None else args.seed
    (args.out / "frames").mkdir(parents=True, exist_ok=True)
    jobs = [(args.split, seed, i, str(args.out)) for i in range(args.count)]
    t0 = time.time()
    if args.jobs > 1:
        with Pool(min(args.jobs, 8)) as pool:
            truths = pool.map(generate_frame, jobs, chunksize=1)
    else:
        truths = [generate_frame(j) for j in jobs]
    truths.sort(key=lambda t: t["id"])
    with open(args.out / "truth.jsonl", "w") as f:
        for t in truths:
            f.write(json.dumps(t, ensure_ascii=True, sort_keys=False) + "\n")
    n_codes = sum(len(t["codes"]) for t in truths)
    dt = time.time() - t0
    print(f"wrote {len(truths)} frames, {n_codes} codes to {args.out} in {dt:.1f}s "
          f"({dt / max(1, len(truths)):.2f}s/frame wall, jobs={args.jobs})")


if __name__ == "__main__":
    main()
