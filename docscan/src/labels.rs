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
    Text,
}

#[derive(Debug, Clone, Serialize)]
pub struct Field {
    /// The printed label, normalised (`IMEI1`, `SN`), or `None` for an
    /// unlabelled code.
    pub label: Option<String>,
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
    let mut l = alnum_upper(raw);
    if let Some(rest) = l.strip_prefix("IMEL").or_else(|| l.strip_prefix("1MEI")).or_else(|| l.strip_prefix("IME1")) {
        l = format!("IMEI{rest}");
    }
    if let Some(rest) = l.strip_prefix("IMEI") {
        // The index after IMEI is a digit: `l`, `I` and `|` are a 1, `Z` a 2.
        l = format!("IMEI{}", digitise(rest));
    }
    l
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
    if numeric && matches!(digits.len(), 8 | 12 | 13) && label.is_none_or(|l| matches!(l, "EAN" | "UPC" | "GTIN" | "BARCODE")) {
        let ok = gtin_valid(&digits);
        return (digits, ValueKind::Gtin, Some(ok));
    }
    (raw.trim().to_string(), ValueKind::Text, None)
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
    let mut parts = t.splitn(2, char::is_whitespace);
    if let (Some(first), Some(rest)) = (parts.next(), parts.next()) {
        let label = normalise_label(first);
        if label.starts_with("IMEI") || matches!(label.as_str(), "SN" | "MEID" | "EID" | "ICCID" | "PN") {
            let (value, kind, check) = classify(Some(&label), rest);
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
    (ValueKind::Text, None)
}

/// Pairs barcodes with printed labels and values. `lines` must be in the
/// same pixel coordinates as the barcodes' points.
pub fn associate(barcodes: &[Barcode], lines: &[Line]) -> Labelled {
    let printed: Vec<Printed> = merge_digit_groups(lines).iter().filter_map(parse_line).collect();
    let mut used = vec![false; printed.len()];
    let norm = |s: &str| alnum_upper(s);

    // Barcodes whose value is printed somewhere: confirmed.
    let mut confirmed: Vec<(usize, Option<usize>)> = Vec::new();
    for (bi, b) in barcodes.iter().enumerate() {
        let hit = printed.iter().position(|p| norm(&p.value) == norm(&b.text));
        if let Some(pi) = hit {
            used[pi] = true;
        }
        confirmed.push((bi, hit));
    }
    let confirmed_boxes: Vec<[f32; 4]> =
        confirmed.iter().filter(|(_, p)| p.is_some()).map(|(bi, _)| barcode_box(&barcodes[*bi])).collect();

    let mut fields = Vec::new();
    let mut dropped = Vec::new();
    for (bi, hit) in confirmed {
        let b = &barcodes[bi];
        let bbox = barcode_box(b);
        let (kind, check) = kind_of_barcode(b);
        if let Some(pi) = hit {
            let p = &printed[pi];
            let label = p.label.clone().or_else(|| label_above(&printed, &used, bbox).map(|(l, _)| l));
            fields.push(Field {
                label,
                value: b.text.clone(),
                kind: if p.kind != ValueKind::Text { p.kind } else { kind },
                source: Source::Both,
                check_digit_valid: check.or(p.check),
                barcode_format: Some(b.format.clone()),
                bbox,
            });
            continue;
        }
        // Unsupported decodes: drop a misread overlapping a confirmed code,
        // a code that sits on text, or one whose own checksum fails.
        let on_confirmed = confirmed_boxes.iter().any(|c| overlap(*c, bbox) > 0.3);
        let on_text = matches!(b.format.as_str(), "upce" | "ean8" | "codabar" | "itf")
            && lines.iter().any(|l| overlap([l.x, l.y, l.w, l.h], bbox) > 0.3);
        if on_confirmed || on_text || check == Some(false) {
            dropped.push(b.clone());
            continue;
        }
        let label = label_above(&printed, &used, bbox).map(|(l, pi)| {
            used[pi] = true;
            l
        });
        fields.push(Field {
            label,
            value: b.text.clone(),
            kind,
            source: Source::Barcode,
            check_digit_valid: check,
            barcode_format: Some(b.format.clone()),
            bbox,
        });
    }
    // Printed fields with no barcode.
    for (pi, p) in printed.iter().enumerate() {
        if used[pi] || p.label.is_none() || p.value.is_empty() {
            continue;
        }
        fields.push(Field {
            label: p.label.clone(),
            value: p.value.clone(),
            kind: p.kind,
            source: Source::Text,
            check_digit_valid: p.check,
            barcode_format: None,
            bbox: [p.line.x, p.line.y, p.line.w, p.line.h],
        });
    }
    fields.sort_by(|a, b| a.bbox[1].total_cmp(&b.bbox[1]).then(a.bbox[0].total_cmp(&b.bbox[0])));
    Labelled { fields, dropped }
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

/// The nearest unused label line just above a barcode and overlapping it
/// horizontally, within about two line heights.
fn label_above(printed: &[Printed], used: &[bool], bbox: [f32; 4]) -> Option<(String, usize)> {
    printed
        .iter()
        .enumerate()
        // A label line printing its own (different) value is a field of its
        // own; only a bare label names the code below it.
        .filter(|(i, p)| !used[*i] && p.label.is_some() && p.value.is_empty())
        .filter(|(_, p)| {
            let l = &p.line;
            let gap = bbox[1] - (l.y + l.h);
            let overlaps_x = l.x < bbox[0] + bbox[2] && l.x + l.w > bbox[0];
            overlaps_x && gap > -l.h * 0.5 && gap < l.h * 2.5
        })
        .min_by(|a, b| (bbox[1] - a.1.line.y).total_cmp(&(bbox[1] - b.1.line.y)))
        .map(|(i, p)| (p.label.clone().unwrap(), i))
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
    fn checksums() {
        assert!(gtin_valid("6932204520951"));
        assert!(gtin_valid("9562094714436"));
        assert!(luhn_valid("351204123456785"));
        assert!(luhn_valid("351204123456793"));
        assert!(!luhn_valid("351204123456786"));
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
        let out = associate(&barcodes, &lines);
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
        let out = associate(&barcodes, &lines);
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
        let out = associate(&barcodes, &lines);
        assert_eq!(out.fields.len(), 1);
        let f = &out.fields[0];
        assert_eq!((f.label.as_deref(), f.source, f.kind), (Some("IMEI1"), Source::Barcode, ValueKind::Imei));
    }

    #[test]
    fn barcode_takes_label_above() {
        let lines = vec![line("IMEI1: 3512O4123456785", 400.0, 440.0, 290.0)];
        let barcodes = vec![bar("code128", "351204123456785", 405.0, 690.0, 470.0)];
        let out = associate(&barcodes, &lines);
        assert_eq!(out.fields.len(), 1);
        let f = &out.fields[0];
        assert_eq!((f.label.as_deref(), f.source, f.kind), (Some("IMEI1"), Source::Both, ValueKind::Imei));
    }
}
