//! Labelled readings: barcodes paired with the printed text around them.
//!
//! Device boxes and labels print each code's meaning beside it
//! (`IMEI1: 351204123456785` above its barcode, `SN: …` with no barcode at
//! all, the digits of an EAN-13 under its bars). This module turns the
//! barcodes and the OCR'd lines of one frame into named fields:
//!
//! - a `LABEL: value` line is a field, checked by its own rules (an IMEI's
//!   Luhn digit, an EAN's checksum);
//! - a barcode whose decoded value equals a printed value confirms that field,
//!   and takes its label; a barcode with no printed counterpart is a field of
//!   its own, named by the label line just above it if there is one;
//! - a decode with no printed support that overlaps a confirmed code, or sits
//!   on a line of text, is dropped: rxing occasionally reports a misread with
//!   a valid checksum, or a short code inside text.
//!
//! Printed values matter as much as the bars: a barcode too fine for the
//! camera still has its value printed beside it, and the check digit tells a
//! clean read from a bad one.

use serde::Serialize;

use crate::barcode::Barcode;
use crate::za::{Line, luhn_valid};

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    /// The barcode and the printed value agree.
    Both,
    Barcode,
    Text,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ValueKind {
    /// 15 digits with a Luhn check digit.
    Imei,
    /// A GTIN: EAN-13, EAN-8, UPC-A or UPC-E, with its checksum.
    Gtin,
    /// A SIM card's ICCID: 19 or 20 digits starting `89`, with a Luhn digit.
    Iccid,
    Text,
}

#[derive(Debug, Clone, Serialize)]
pub struct Field {
    /// The printed label, normalised (`IMEI1`, `SN`), or `None` for an
    /// unlabelled code.
    pub label: Option<String>,
    /// What to call the field: its label, or `Barcode 1`, `Barcode 2`, … in
    /// reading order for codes printed without one.
    pub name: String,
    /// Bars were found where this printed value's barcode should be, but they
    /// could not be decoded (too fine or blurred): the value comes from print.
    pub barcode_unread: bool,
    pub value: String,
    pub kind: ValueKind,
    pub source: Source,
    /// The value's own check digit, where its kind has one.
    pub check_digit_valid: Option<bool>,
    pub barcode_format: Option<String>,
    /// Where the field is, in the frame's pixels: `[x, y, w, h]`.
    pub bbox: [f32; 4],
}

#[derive(Debug, Clone, Serialize)]
pub struct Labelled {
    pub fields: Vec<Field>,
    /// Decodes dropped as unsupported misreads, for inspection.
    pub dropped: Vec<Barcode>,
}

/// GTIN checksum (EAN-13, EAN-8, UPC-A): weights 3 and 1 from the right,
/// the check digit included.
pub fn gtin_valid(digits: &str) -> bool {
    if !matches!(digits.len(), 8 | 12 | 13 | 14) || !digits.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let sum: u32 = digits
        .chars()
        .rev()
        .enumerate()
        .map(|(i, c)| c.to_digit(10).unwrap() * if i % 2 == 1 { 3 } else { 1 })
        .sum();
    sum % 10 == 0
}

/// Maps OCR look-alikes to digits, for a value that should be numeric.
fn digitise(s: &str) -> String {
    s.chars()
        .filter(|c| !c.is_whitespace())
        .map(|c| match c {
            'O' | 'o' | 'Q' | 'D' => '0',
            'I' | 'l' | '|' | 'i' | '!' => '1',
            'Z' | 'z' => '2',
            'S' | 's' => '5',
            'B' => '8',
            'G' | 'b' => '6',
            _ => c,
        })
        .collect()
}

fn alnum_upper(s: &str) -> String {
    s.chars().filter(|c| c.is_ascii_alphanumeric()).map(|c| c.to_ascii_uppercase()).collect()
}

/// Normalises a printed label: `S/N` → `SN`, `IMEl 1` → `IMEI1`.
fn normalise_label(raw: &str) -> String {
    if let Some(imei) = imei_label(raw) {
        return imei;
    }
    let l = alnum_upper(raw);
    // `S/N` with its slash read as a letter or digit.
    if matches!(l.as_str(), "SIN" | "S1N" | "SLN" | "STN") {
        return "SN".into();
    }
    l
}

/// An IMEI label as OCR reads it: `IMEI1`, `IMEI 1`, `IMEl1`, `1MEI2`, `IME) 1`,
/// `IME/2`, `IMFI2`, `IME17` (an `I` read as `1` and a `1` as `7`). The index
/// is 1 or 2 (a phone has at most two): a trailing `l`, `I`, `|`, `T` or `7`
/// is a 1, `Z` a 2. `None` when the label is not an IMEI's.
fn imei_label(raw: &str) -> Option<String> {
    let t = alnum_upper(raw);
    let index = |s: &str| -> Option<&'static str> {
        match s {
            "" => Some(""),
            "1" | "I" | "L" | "T" | "7" | "J" => Some("1"),
            "2" | "Z" => Some("2"),
            _ => None,
        }
    };
    // `I` misread as `1`, `l`, `|`, `T` or `J`; `E` as `F`.
    let like_i = |c: char| matches!(c, 'I' | '1' | 'L' | 'T' | 'J');
    let is_imei = |p: &str| {
        let c: Vec<char> = p.chars().collect();
        c.len() == 4 && [like_i(c[0]), c[1] == 'M', matches!(c[2], 'E' | 'F'), like_i(c[3])].iter().filter(|&&ok| !ok).count() <= 1
    };
    // An index set apart from the letters (`IME 1`, `IME) 1`, `IME/2`): the
    // letters before it are the word, even with its last `I` lost.
    let parts: Vec<String> = raw.split(|c: char| !c.is_alphanumeric()).filter(|p| !p.is_empty()).map(alnum_upper).collect();
    if parts.len() >= 2
        && let Some(i) = index(parts.last().unwrap())
        && !i.is_empty()
    {
        let word: String = parts[..parts.len() - 1].concat();
        if is_imei(&word) || word == "IME" {
            return Some(format!("IMEI{i}"));
        }
    }
    // Read twice over a tile seam (`IMEIIME2`): the last reading.
    if let Some(i) = t.rfind("IME").filter(|&i| i > 0) {
        return imei_label(&t[i..]);
    }
    // The first I lost (`MEI2`).
    if let Some(rest) = t.strip_prefix("MEI")
        && let Some(i) = index(rest).filter(|i| !i.is_empty())
    {
        return Some(format!("IMEI{i}"));
    }
    // `IME2`: the last I dropped, the index kept (a 2 is never an I).
    if matches!(t.as_str(), "IME2" | "IMEZ") {
        return Some("IMEI2".into());
    }
    // `IMEI1`, `IME11`, `IMFI2`: four letters like IMEI, then the index.
    if t.len() >= 4
        && is_imei(&t[..4])
        && let Some(i) = index(&t[4..])
    {
        return Some(format!("IMEI{i}"));
    }
    None
}

/// Classifies and normalises a printed value for its label.
fn classify(label: Option<&str>, raw: &str) -> (String, ValueKind, Option<bool>) {
    if raw.trim().is_empty() {
        return (String::new(), ValueKind::Text, None);
    }
    let digits = digitise(raw);
    let numeric = !digits.is_empty() && digits.chars().all(|c| c.is_ascii_digit());
    if label.is_some_and(|l| l.starts_with("IMEI")) || (numeric && digits.len() == 15 && luhn_valid(&digits)) {
        let value = if numeric { digits } else { alnum_upper(raw) };
        let ok = value.len() == 15 && luhn_valid(&value);
        return (value, ValueKind::Imei, Some(ok));
    }
    if label == Some("ICCID") || (numeric && is_iccid_shape(&digits) && luhn_valid(&digits)) {
        let value = if numeric { digits } else { alnum_upper(raw) };
        let ok = is_iccid_shape(&value) && luhn_valid(&value);
        return (value, ValueKind::Iccid, Some(ok));
    }
    if numeric && matches!(digits.len(), 8 | 12 | 13) && label.is_none_or(|l| matches!(l, "EAN" | "UPC" | "GTIN" | "BARCODE")) {
        let ok = gtin_valid(&digits);
        return (digits, ValueKind::Gtin, Some(ok));
    }
    (raw.trim().to_string(), ValueKind::Text, None)
}

/// 19 or 20 digits starting with the telecom industry's `89`.
fn is_iccid_shape(digits: &str) -> bool {
    matches!(digits.len(), 19 | 20) && digits.starts_with("89") && digits.chars().all(|c| c.is_ascii_digit())
}

struct Printed {
    label: Option<String>,
    value: String,
    kind: ValueKind,
    check: Option<bool>,
    line: Line,
}

/// `LABEL: value` (a colon, or a label of known shape followed by a space),
/// or a bare run of digits such as an EAN's human-readable line.
fn parse_line(line: &Line) -> Option<Printed> {
    let t = line.text.trim();
    if let Some((label, value)) = t.split_once([':', '：'])
        && label.chars().filter(|c| c.is_alphanumeric()).count() >= 2
        && label.chars().count() <= 16
    {
        let label = normalise_label(label);
        let (value, kind, check) = classify(Some(&label), value);
        return Some(Printed { label: Some(label), value, kind, check, line: line.clone() });
    }
    // A label without its colon (`IMEI1 351204123456785`, `SN 10AB12C…`).
    // The label may be two words when its index stands apart (`IME 1 3512…`).
    let words: Vec<&str> = t.split_whitespace().collect();
    for n in [2, 1] {
        if words.len() <= n || (n == 2 && words[1].chars().count() != 1) {
            continue;
        }
        let label = normalise_label(&words[..n].join(" "));
        if label.starts_with("IMEI") || matches!(label.as_str(), "SN" | "MEID" | "EID" | "ICCID" | "PN") {
            let (value, kind, check) = classify(Some(&label), &words[n..].join(" "));
            return Some(Printed { label: Some(label), value, kind, check, line: line.clone() });
        }
    }
    let digits = digitise(t);
    if digits.len() >= 8 && digits.chars().all(|c| c.is_ascii_digit()) {
        let (value, kind, check) = classify(None, t);
        return Some(Printed { label: None, value, kind, check, line: line.clone() });
    }
    None
}

/// Axis-aligned box of a barcode's points, padded for 1D codes (which report
/// only scan-line end points) to a nominal bar height.
fn barcode_box(b: &Barcode) -> [f32; 4] {
    let xs = b.points.iter().map(|p| p[0]);
    let ys = b.points.iter().map(|p| p[1]);
    let (x0, x1) = (xs.clone().fold(f32::MAX, f32::min), xs.fold(f32::MIN, f32::max));
    let (y0, y1) = (ys.clone().fold(f32::MAX, f32::min), ys.fold(f32::MIN, f32::max));
    let pad = if y1 - y0 < 4.0 { ((x1 - x0) * 0.08).max(6.0) } else { 0.0 };
    [x0, y0 - pad, (x1 - x0).max(1.0), (y1 - y0) + 2.0 * pad]
}

fn overlap(a: [f32; 4], b: [f32; 4]) -> f32 {
    let w = (a[0] + a[2]).min(b[0] + b[2]) - a[0].max(b[0]);
    let h = (a[1] + a[3]).min(b[1] + b[3]) - a[1].max(b[1]);
    if w <= 0.0 || h <= 0.0 {
        return 0.0;
    }
    (w * h) / (a[2] * a[3]).min(b[2] * b[3]).max(1.0)
}

fn kind_of_barcode(b: &Barcode) -> (ValueKind, Option<bool>) {
    let t = b.text.trim();
    if matches!(b.format.as_str(), "ean13" | "ean8" | "upca") {
        return (ValueKind::Gtin, Some(gtin_valid(t)));
    }
    if t.len() == 15 && t.chars().all(|c| c.is_ascii_digit()) {
        return (ValueKind::Imei, Some(luhn_valid(t)));
    }
    // Only a valid ICCID is called one: other long numbers starting 89 exist.
    if is_iccid_shape(t) && luhn_valid(t) {
        return (ValueKind::Iccid, Some(true));
    }
    (ValueKind::Text, None)
}

/// Pairs barcodes with printed labels and values. `regions` are patches
/// that look like linear barcodes (`barcode::oriented_regions`), decoded or
/// not; `lines` are OCR lines. Everything is in the same frame pixels.
///
/// A label can sit above a code, below it, or to its left. A code with no
/// label is named `Barcode n` in reading order. Bars that would not decode
/// still claim the labelled value printed beside them, so the field says
/// where its value came from.
pub fn associate(barcodes: &[Barcode], regions: &[[f32; 4]], lines: &[Line]) -> Labelled {
    let printed: Vec<Printed> = merge_digit_groups(lines).iter().filter_map(parse_line).collect();
    let mut used = vec![false; printed.len()];

    // A decoded linear code reports only its scan line; the bar region it
    // lies in gives its real extent, which placing labels needs.
    let boxes: Vec<[f32; 4]> = barcodes
        .iter()
        .map(|b| {
            let scan = barcode_box(b);
            let (cx, cy) = (scan[0] + scan[2] / 2.0, scan[1] + scan[3] / 2.0);
            regions
                .iter()
                .find(|r| cx >= r[0] && cx <= r[0] + r[2] && cy >= r[1] && cy <= r[1] + r[3])
                .copied()
                .unwrap_or(scan)
        })
        .collect();

    // A label printed just left of its bars is often read together with them
    // (`IMEI1: INNNN`): an IMEI "value" with hardly a digit is the bars, and
    // the label a bare one.
    let mut printed = printed;
    for p in printed.iter_mut().filter(|p| p.kind == ValueKind::Imei && p.value.chars().filter(|c| c.is_ascii_digit()).count() <= 1) {
        p.value.clear();
        (p.kind, p.check) = (ValueKind::Text, None);
    }

    // Decoded codes whose value is printed (exactly, or within two OCR slips).
    let hits: Vec<Option<usize>> = barcodes
        .iter()
        .map(|b| {
            // The closest printed value that plausibly prints this code.
            let hit = printed
                .iter()
                .enumerate()
                .filter(|(i, _)| !used[*i])
                .filter_map(|(i, p)| value_distance(&p.value, &b.text, p.check == Some(true)).map(|d| (d, i)))
                .min()
                .map(|(_, i)| i);
            if let Some(i) = hit {
                used[i] = true;
            }
            hit
        })
        .collect();
    let confirmed: Vec<[f32; 4]> = hits.iter().zip(&boxes).filter(|(h, _)| h.is_some()).map(|(_, b)| *b).collect();

    let mut fields = Vec::new();
    let mut dropped = Vec::new();
    for (bi, b) in barcodes.iter().enumerate() {
        let bbox = boxes[bi];
        let (kind, check) = kind_of_barcode(b);
        let mut field = Field {
            label: None,
            name: String::new(),
            barcode_unread: false,
            value: b.text.clone(),
            kind,
            source: Source::Barcode,
            check_digit_valid: check,
            barcode_format: Some(b.format.clone()),
            bbox,
        };
        if let Some(pi) = hits[bi] {
            let p = &printed[pi];
            field.source = Source::Both;
            field.label = p.label.clone();
            if p.kind != ValueKind::Text {
                field.kind = p.kind;
            }
            field.check_digit_valid = check.or(p.check);
        } else {
            // Unsupported decodes: a misread overlapping a confirmed code, a
            // short code sitting on text, or one failing its own checksum.
            let on_confirmed = confirmed.iter().any(|c| overlap(*c, bbox) > 0.3);
            let on_text = matches!(b.format.as_str(), "upce" | "ean8" | "codabar" | "itf")
                && lines.iter().any(|l| overlap([l.x, l.y, l.w, l.h], bbox) > 0.3);
            if on_confirmed || on_text || check == Some(false) {
                dropped.push(b.clone());
                continue;
            }
        }
        fields.push(field);
    }
    // Bare labels beside decoded codes that have none yet.
    let unlabelled: Vec<usize> = (0..fields.len()).filter(|&i| fields[i].label.is_none()).collect();
    let targets: Vec<[f32; 4]> = unlabelled.iter().map(|&i| fields[i].bbox).collect();
    let values: Vec<Option<&str>> = unlabelled.iter().map(|&i| Some(fields[i].value.as_str())).collect();
    for (k, hit) in match_labels(&printed, &used, &targets, &values, true).into_iter().enumerate() {
        if let Some(pi) = hit {
            used[pi] = true;
            fields[unlabelled[k]].label = printed[pi].label.clone();
        }
    }

    // Bars that would not decode: they take the labelled value printed next
    // to them (`IMEI1: 8620…` above a Code 128 too fine to read).
    let unread: Vec<[f32; 4]> = regions.iter().copied().filter(|r| !boxes.iter().any(|d| overlap(*d, *r) > 0.3)).collect();
    for (ri, hit) in match_labels(&printed, &used, &unread, &vec![None; unread.len()], false).into_iter().enumerate() {
        let Some(pi) = hit else { continue };
        used[pi] = true;
        let p = &printed[pi];
        fields.push(Field {
            label: p.label.clone(),
            name: String::new(),
            barcode_unread: true,
            value: p.value.clone(),
            kind: p.kind,
            source: Source::Text,
            check_digit_valid: p.check,
            barcode_format: None,
            bbox: unread[ri],
        });
    }

    // Printed fields with no barcode at all.
    for (pi, p) in printed.iter().enumerate() {
        if used[pi] || p.label.is_none() || p.value.is_empty() {
            continue;
        }
        fields.push(Field {
            label: p.label.clone(),
            name: String::new(),
            barcode_unread: false,
            value: p.value.clone(),
            kind: p.kind,
            source: Source::Text,
            check_digit_valid: p.check,
            barcode_format: None,
            bbox: [p.line.x, p.line.y, p.line.w, p.line.h],
        });
    }
    fields.sort_by(|a, b| a.bbox[1].total_cmp(&b.bbox[1]).then(a.bbox[0].total_cmp(&b.bbox[0])));
    let mut n = 0;
    for f in &mut fields {
        f.name = match &f.label {
            Some(l) => l.clone(),
            None => {
                n += 1;
                format!("Barcode {n}")
            }
        };
    }
    Labelled { fields, dropped }
}

/// How far a printed value is from a decoded one, when it plausibly prints
/// that code: equal; or, for values of eight characters or more, within two
/// OCR slips (substitutions, a dropped or doubled character; `?` matches
/// anything); or cut short (a prefix or suffix of at least 60% of it, a line
/// clipped by a tile edge or split by layout). A printed value that passes
/// its own check digit (`checked`) but differs is a different number, not a
/// misread: a phone's two IMEIs differ only in their last digits.
fn value_distance(printed: &str, decoded: &str, checked: bool) -> Option<usize> {
    let p: Vec<char> = printed.chars().filter(|c| c.is_ascii_alphanumeric() || *c == '?').map(|c| c.to_ascii_uppercase()).collect();
    let d: Vec<char> = alnum_upper(decoded).chars().collect();
    if p.is_empty() || d.is_empty() {
        return None;
    }
    if p == d {
        return Some(0);
    }
    if checked || p.len() < 8 {
        return None;
    }
    let same = |a: char, b: char| a == b || a == '?';
    // Cut short at either end.
    if p.len() < d.len() && p.len() * 5 >= d.len() * 3 {
        if p.iter().zip(&d).all(|(&a, &b)| same(a, b)) || p.iter().rev().zip(d.iter().rev()).all(|(&a, &b)| same(a, b)) {
            return Some(1);
        }
    }
    // Levenshtein distance, `?` a wildcard.
    let mut prev: Vec<usize> = (0..=d.len()).collect();
    for (i, &a) in p.iter().enumerate() {
        let mut cur = vec![i + 1; d.len() + 1];
        for (j, &b) in d.iter().enumerate() {
            cur[j + 1] = (prev[j] + usize::from(!same(a, b))).min(prev[j + 1] + 1).min(cur[j] + 1);
        }
        prev = cur;
    }
    let dist = prev[d.len()];
    (dist <= 2).then_some(dist)
}

/// Joins runs of digit groups on one row (`6`, `932204`, `520951`: an EAN's
/// human-readable line, which layout splits at its wide gaps) into one line.
fn merge_digit_groups(lines: &[Line]) -> Vec<Line> {
    let digitish = |t: &str| !t.trim().is_empty() && digitise(t).chars().all(|c| c.is_ascii_digit());
    // Rows first (vertical centres within half a line height), then left to
    // right within a row: a group can sit a pixel above its neighbour.
    let mut sorted: Vec<&Line> = lines.iter().collect();
    sorted.sort_by(|a, b| (a.y + a.h / 2.0).total_cmp(&(b.y + b.h / 2.0)));
    let mut rows: Vec<Vec<&Line>> = Vec::new();
    for l in sorted {
        let cy = l.y + l.h / 2.0;
        match rows.last_mut() {
            Some(row) if row.iter().all(|r| ((r.y + r.h / 2.0) - cy).abs() < 0.5 * r.h.min(l.h)) => row.push(l),
            _ => rows.push(vec![l]),
        }
    }
    let mut out: Vec<Line> = Vec::new();
    for mut row in rows {
        row.sort_by(|a, b| a.x.total_cmp(&b.x));
        let mut current: Option<Line> = None;
        for l in row {
            current = Some(match current.take() {
                Some(mut prev)
                    if digitish(&prev.text) && digitish(&l.text) && l.x - (prev.x + prev.w) < 6.0 * prev.h.max(l.h) =>
                {
                    prev.text = format!("{} {}", prev.text, l.text);
                    let right = (prev.x + prev.w).max(l.x + l.w);
                    let bottom = (prev.y + prev.h).max(l.y + l.h);
                    prev.y = prev.y.min(l.y);
                    prev.w = right - prev.x;
                    prev.h = bottom - prev.y;
                    prev
                }
                Some(prev) => {
                    out.push(prev);
                    l.clone()
                }
                None => l.clone(),
            });
        }
        out.extend(current);
    }
    out
}

/// Pairs label lines with codes across the whole frame. A label belongs to
/// the code it sits above first (the usual layout: `IMEI2:` printed between
/// IMEI1's bars and its own sits closer to IMEI1's, but labels it own), then
/// to a code on its right, then to one it sits below. Candidates are taken in
/// that priority, nearest first, and each label and each code is used once.
///
/// With `bare_only`, only labels printing no value of their own qualify (a
/// labelled value is a field in its own right); without it (bars that did not
/// decode) only labels that print a value qualify, since the value is what
/// those bars hold.
/// Whether a code holding `value` can carry `label`: an IMEI label only a
/// 15-digit value with its Luhn digit, an EAN or UPC label only a GTIN, an
/// ICCID label only an ICCID.
fn fits_label(label: &str, value: &str) -> bool {
    if label.starts_with("IMEI") {
        return value.len() == 15 && luhn_valid(value);
    }
    if matches!(label, "EAN" | "UPC" | "GTIN") {
        return gtin_valid(value);
    }
    if label == "ICCID" {
        return is_iccid_shape(value) && luhn_valid(value);
    }
    true
}

/// `values`: each target's decoded value, when known; a label goes only to a
/// value it fits ([`fits_label`]).
fn match_labels(printed: &[Printed], used: &[bool], targets: &[[f32; 4]], values: &[Option<&str>], bare_only: bool) -> Vec<Option<usize>> {
    let mut candidates: Vec<(u8, f32, usize, usize)> = Vec::new();
    for (pi, p) in printed.iter().enumerate() {
        if used[pi] || p.label.is_none() || bare_only != p.value.is_empty() {
            continue;
        }
        let l = &p.line;
        let (lx0, ly0, lx1, ly1) = (l.x, l.y, l.x + l.w, l.y + l.h);
        let reach = 2.5 * l.h;
        for (ti, t) in targets.iter().enumerate() {
            if values[ti].is_some_and(|v| !fits_label(p.label.as_deref().unwrap_or(""), v)) {
                continue;
            }
            let (bx0, by0, bx1, by1) = (t[0], t[1], t[0] + t[2], t[1] + t[3]);
            let x_overlap = lx0 < bx1 && lx1 > bx0;
            let y_overlap = (ly1.min(by1) - ly0.max(by0)) > 0.5 * l.h.min(t[3]);
            let above = by0 - ly1; // label above the code
            let left = bx0 - lx1; // label left of the code
            let below = ly0 - by1; // label below the code
            if x_overlap && above > -0.5 * l.h && above < reach {
                candidates.push((0, above.max(0.0), pi, ti));
            } else if y_overlap && left > -l.h && left < 6.0 * l.h {
                candidates.push((1, left.max(0.0), pi, ti));
            } else if x_overlap && below > -0.5 * l.h && below < reach {
                candidates.push((2, below.max(0.0), pi, ti));
            }
        }
    }
    candidates.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.total_cmp(&b.1)));
    let mut out = vec![None; targets.len()];
    let mut taken = vec![false; printed.len()];
    for (_, _, pi, ti) in candidates {
        if out[ti].is_none() && !taken[pi] {
            out[ti] = Some(pi);
            taken[pi] = true;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line(text: &str, x: f32, y: f32, w: f32) -> Line {
        Line { text: text.into(), x, y, w, h: 14.0 }
    }

    fn bar(format: &str, text: &str, x0: f32, x1: f32, y: f32) -> Barcode {
        Barcode { format: format.into(), text: text.into(), bytes: vec![], points: vec![[x0, y], [x1, y]] }
    }

    #[test]
    fn imei_and_serial_labels_as_ocr_reads_them() {
        for (raw, want) in [
            ("IMEI1", "IMEI1"), ("IMEI 1", "IMEI1"), ("IMEl1", "IMEI1"), ("1MEI2", "IMEI2"), ("IME) 1", "IMEI1"), ("IME/2", "IMEI2"),
            ("IMFI2", "IMEI2"), ("IME17", "IMEI1"), ("IME11", "IMEI1"), ("IMEIT", "IMEI1"), ("IME2", "IMEI2"), ("IME 1", "IMEI1"),
            ("IMEI", "IMEI"), ("IMEIIME2", "IMEI2"), ("IMEIMEI2", "IMEI2"), ("MEI2", "IMEI2"), ("S/N", "SN"), ("SIN", "SN"), ("SN", "SN"), ("EAN", "EAN"), ("MEID", "MEID"), ("ITEM", "ITEM"),
        ] {
            assert_eq!(normalise_label(raw), want, "{raw}");
        }
    }

    #[test]
    fn label_index_apart_from_its_word() {
        let p = parse_line(&line("IME 1 860449065649608", 0.0, 0.0, 300.0)).unwrap();
        assert_eq!((p.label.as_deref(), p.value.as_str(), p.check), (Some("IMEI1"), "860449065649608", Some(true)));
        let p = parse_line(&line("IME) 1: 359774779498853", 0.0, 0.0, 300.0)).unwrap();
        assert_eq!((p.label.as_deref(), p.value.as_str()), (Some("IMEI1"), "359774779498853"));
    }

    #[test]
    fn printed_values_that_confirm_a_code() {
        assert!(value_distance("F465MM?TT9T1", "F465MM7TT9T1", false).is_some());
        assert!(value_distance("R58N67EAIP", "R58N67EAJPJ", false).is_some());
        assert!(value_distance("W12KVM5T39", "W12KVM5T396U", false).is_some());
        assert!(value_distance("55430598320", "5543059832017", false).is_some());
        // A valid IMEI that differs is the other IMEI, however close.
        assert_eq!(value_distance("351204123456785", "351204123456793", true), None);
        assert_eq!(value_distance("351204123456785", "351204123456785", true), Some(0));
        // Short values must match exactly.
        assert_eq!(value_distance("AB12", "AB13", false), None);
        assert_eq!(value_distance("HH2", "HH28269516CN", false), None);
    }

    /// A SIM box: the ICCID printed with its label, checked by its Luhn digit.
    #[test]
    fn iccid() {
        // 8927 0000 0000 0000 000 with its Luhn digit.
        let body = "892700000000000000";
        let check = (0..10).map(|d| format!("{body}{d}")).find(|v| luhn_valid(v)).unwrap();
        let p = parse_line(&line(&format!("ICCID: {check}"), 0.0, 0.0, 300.0)).unwrap();
        assert_eq!((p.label.as_deref(), p.kind, p.check), (Some("ICCID"), ValueKind::Iccid, Some(true)));
        let mut wrong = check.clone();
        wrong.replace_range(5..6, if &check[5..6] == "1" { "2" } else { "1" });
        assert_eq!(parse_line(&line(&format!("ICCID {wrong}"), 0.0, 0.0, 300.0)).unwrap().check, Some(false));
        let b = bar("code128", &check, 0.0, 300.0, 40.0);
        assert_eq!(kind_of_barcode(&b), (ValueKind::Iccid, Some(true)));
    }

    #[test]
    fn checksums() {
        assert!(gtin_valid("6932204520951"));
        assert!(gtin_valid("9562094714436"));
        assert!(luhn_valid("351204123456785"));
        assert!(luhn_valid("351204123456793"));
        assert!(!luhn_valid("351204123456786"));
    }

    /// A label printed between two codes belongs to the one below it.
    #[test]
    fn label_between_two_codes_belongs_below() {
        let lines = vec![
            line("IMEI1: 351204123456785", 400.0, 426.0, 265.0),
            line("IMEI2: 351204123456793", 399.0, 501.0, 262.0),
        ];
        let regions = [[400.0, 464.0, 312.0, 40.0], [392.0, 536.0, 312.0, 40.0]];
        let out = associate(&[], &regions, &lines);
        let got: Vec<(&str, bool, f32)> = out.fields.iter().map(|f| (f.name.as_str(), f.barcode_unread, f.bbox[1])).collect();
        assert_eq!(got, vec![("IMEI1", true, 464.0), ("IMEI2", true, 536.0)]);
    }

    /// Bars that would not decode take the labelled value above them, a code
    /// with a label on its left or below it takes that label, and codes with
    /// none are numbered.
    #[test]
    fn labels_above_left_below_and_numbering() {
        let lines = vec![
            line("IMEI1: 351204123456785", 400.0, 100.0, 290.0),
            line("Order:", 20.0, 310.0, 70.0),
            line("Lot:", 400.0, 470.0, 50.0),
        ];
        // An unreadable Code 128 under the IMEI line.
        let regions = [[400.0, 120.0, 290.0, 50.0], [100.0, 300.0, 300.0, 40.0], [400.0, 420.0, 280.0, 45.0]];
        let barcodes = vec![
            bar("code128", "ORD-778", 110.0, 390.0, 320.0),
            bar("code128", "LOT-5521", 410.0, 670.0, 440.0),
            bar("qrcode", "https://example.test/a", 50.0, 90.0, 600.0),
            bar("qrcode", "https://example.test/b", 50.0, 90.0, 700.0),
        ];
        let out = associate(&barcodes, &regions, &lines);
        let names: Vec<(&str, &str)> = out.fields.iter().map(|f| (f.name.as_str(), f.value.as_str())).collect();
        assert_eq!(
            names,
            vec![
                ("IMEI1", "351204123456785"),
                ("ORDER", "ORD-778"),
                ("LOT", "LOT-5521"),
                ("Barcode 1", "https://example.test/a"),
                ("Barcode 2", "https://example.test/b"),
            ]
        );
        let imei = &out.fields[0];
        assert!(imei.barcode_unread && imei.source == Source::Text && imei.check_digit_valid == Some(true));
    }

    /// The device-box layout: two IMEIs whose barcodes are too fine to
    /// decode, a serial number with no barcode, and the box's EAN-13 with its
    /// digits printed under it, plus a misread EAN overlapping it.
    #[test]
    fn device_box() {
        let lines = vec![
            line("IMEl1: 351204123456785", 400.0, 440.0, 290.0),
            line("IMEI2: 351204123456793", 400.0, 510.0, 290.0),
            line("SN: 10AB12C345000X1", 400.0, 575.0, 250.0),
            line("6 932204 520951", 395.0, 665.0, 290.0),
        ];
        let barcodes = vec![
            bar("ean13", "3954117520951", 422.0, 703.0, 645.0),
            bar("ean13", "6932204520951", 422.0, 703.0, 655.0),
        ];
        let out = associate(&barcodes, &[], &lines);
        let get = |l: &str| out.fields.iter().find(|f| f.label.as_deref() == Some(l)).unwrap();
        assert_eq!(get("IMEI1").value, "351204123456785");
        assert_eq!(get("IMEI1").check_digit_valid, Some(true));
        assert_eq!(get("IMEI1").source, Source::Text);
        assert_eq!(get("IMEI2").value, "351204123456793");
        assert_eq!(get("SN").value, "10AB12C345000X1");
        let ean = out.fields.iter().find(|f| f.kind == ValueKind::Gtin).unwrap();
        assert_eq!((ean.value.as_str(), ean.source), ("6932204520951", Source::Both));
        assert_eq!(out.dropped.len(), 1);
        assert_eq!(out.dropped[0].text, "3954117520951");
    }

    /// The EAN's digits split into groups by layout still confirm it.
    #[test]
    fn split_digit_groups_confirm_ean() {
        let lines = vec![line("6", 395.0, 665.0, 12.0), line("932204", 450.0, 665.0, 90.0), line("520951", 600.0, 665.0, 90.0)];
        let barcodes = vec![bar("ean13", "3954117520951", 422.0, 703.0, 645.0), bar("ean13", "6932204520951", 422.0, 703.0, 655.0)];
        let out = associate(&barcodes, &[], &lines);
        assert_eq!(out.fields.len(), 1);
        assert_eq!((out.fields[0].value.as_str(), out.fields[0].source), ("6932204520951", Source::Both));
        assert_eq!(out.dropped.len(), 1);
    }

    /// The exact boxes OCR gave for a real device box's EAN digits.
    #[test]
    fn real_box_digit_groups() {
        let l = |t: &str, x, y, w, h| Line { text: t.into(), x, y, w, h };
        let lines = vec![
            l("HSU", 637.0, 644.0, 46.0, 18.0),
            l("09.07", 3.0, 651.0, 53.0, 22.0),
            // The middle group sits half a pixel above the first: order by row, then x.
            l("932204", 452.0, 658.6, 75.0, 21.0),
            l("6", 394.0, 659.3, 19.0, 19.0),
            l("520951", 595.0, 661.0, 76.0, 22.0),
        ];
        let merged = merge_digit_groups(&lines);
        assert!(merged.iter().any(|m| m.text == "6 932204 520951"), "{:?}", merged.iter().map(|m| &m.text).collect::<Vec<_>>());
    }

    #[test]
    fn barcode_takes_bare_label_above() {
        let lines = vec![line("IMEI1:", 400.0, 440.0, 60.0)];
        let barcodes = vec![bar("code128", "351204123456785", 405.0, 690.0, 470.0)];
        let out = associate(&barcodes, &[], &lines);
        assert_eq!(out.fields.len(), 1);
        let f = &out.fields[0];
        assert_eq!((f.label.as_deref(), f.source, f.kind), (Some("IMEI1"), Source::Barcode, ValueKind::Imei));
    }

    #[test]
    fn barcode_takes_label_above() {
        let lines = vec![line("IMEI1: 3512O4123456785", 400.0, 440.0, 290.0)];
        let barcodes = vec![bar("code128", "351204123456785", 405.0, 690.0, 470.0)];
        let out = associate(&barcodes, &[], &lines);
        assert_eq!(out.fields.len(), 1);
        let f = &out.fields[0];
        assert_eq!((f.label.as_deref(), f.source, f.kind), (Some("IMEI1"), Source::Both, ValueKind::Imei));
    }
}
