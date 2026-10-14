//! South African identity documents: the 13-digit identity number, the
//! smart ID card's PDF417, and the printed fields of the card front and the
//! green ID book.

use serde::Serialize;

/// The facts an SA identity number carries: `YYMMDD SSSS C A Z`.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct IdNumber {
    pub value: String,
    /// `YYMMDD`; the century is not encoded.
    pub date_of_birth: String,
    pub sex: &'static str,
    pub citizenship: &'static str,
    pub luhn_valid: bool,
    pub date_valid: bool,
}

pub fn luhn_valid(digits: &str) -> bool {
    if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let sum: u32 = digits
        .chars()
        .rev()
        .enumerate()
        .map(|(i, c)| {
            let d = c.to_digit(10).unwrap();
            if i % 2 == 1 {
                let x = d * 2;
                if x > 9 { x - 9 } else { x }
            } else {
                d
            }
        })
        .sum();
    sum % 10 == 0
}

fn date_valid(yymmdd: &str) -> bool {
    let n = |r: std::ops::Range<usize>| yymmdd[r].parse::<u32>().unwrap_or(0);
    let (m, d) = (n(2..4), n(4..6));
    (1..=12).contains(&m) && (1..=31).contains(&d)
}

pub fn parse_id_number(value: &str) -> Option<IdNumber> {
    if value.len() != 13 || !value.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let gender: u32 = value[6..10].parse().ok()?;
    Some(IdNumber {
        value: value.to_string(),
        date_of_birth: value[0..6].to_string(),
        sex: if gender >= 5000 { "M" } else { "F" },
        citizenship: match &value[10..11] {
            "0" => "citizen",
            "1" => "permanent_resident",
            "2" => "refugee",
            _ => "unknown",
        },
        luhn_valid: luhn_valid(value),
        date_valid: date_valid(&value[0..6]),
    })
}

/// Maps OCR look-alikes to digits, for a field known to be numeric.
fn digitise(s: &str) -> String {
    s.chars()
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

/// Finds a valid identity number anywhere in a line of OCR text. Digit
/// groups may be split by spaces (the card prints it as one run, the book
/// sometimes in groups), so spaces between digit groups are closed up.
pub fn find_id_number(text: &str) -> Option<IdNumber> {
    let digitised = digitise(text);
    let compact: String = digitised.chars().filter(|c| !c.is_whitespace()).collect();
    let bytes: Vec<char> = compact.chars().collect();
    let mut fallback = None;
    for start in 0..bytes.len() {
        if start + 13 > bytes.len() {
            break;
        }
        let window: String = bytes[start..start + 13].iter().collect();
        if let Some(id) = parse_id_number(&window) {
            let boundary_ok = (start == 0 || !bytes[start - 1].is_ascii_digit())
                && bytes.get(start + 13).is_none_or(|c| !c.is_ascii_digit());
            if id.luhn_valid && id.date_valid && boundary_ok {
                return Some(id);
            }
            if fallback.is_none() && boundary_ok {
                fallback = Some(id);
            }
        }
    }
    fallback
}

/// The smart ID card back's PDF417: pipe-separated plain text.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SmartIdBarcode {
    pub surname: String,
    pub names: String,
    pub sex: String,
    pub nationality: String,
    pub id_number: IdNumber,
    pub date_of_birth: String,
    pub country_of_birth: String,
    pub status: String,
    pub fields: Vec<String>,
}

/// Parses the smart ID PDF417 text. The identity number is located by
/// content rather than position, and the other fields are read relative to
/// it, so a variant with an extra leading field still parses.
pub fn parse_smart_id_barcode(text: &str) -> Option<SmartIdBarcode> {
    let fields: Vec<String> = text.split('|').map(|f| f.trim().to_string()).collect();
    if fields.len() < 6 {
        return None;
    }
    let idx = fields
        .iter()
        .position(|f| parse_id_number(f).is_some_and(|id| id.luhn_valid))?;
    if idx < 4 {
        return None;
    }
    let get = |i: usize| fields.get(i).cloned().unwrap_or_default();
    Some(SmartIdBarcode {
        surname: get(idx - 4),
        names: get(idx - 3),
        sex: get(idx - 2),
        nationality: get(idx - 1),
        id_number: parse_id_number(&fields[idx])?,
        date_of_birth: get(idx + 1),
        country_of_birth: get(idx + 2),
        status: get(idx + 3),
        fields,
    })
}

/// Groups recognised words into lines by position: words whose vertical
/// centres agree form a band, and a band splits where the horizontal gap is
/// wide (a second column). Sorted top to bottom, then left to right.
pub fn rows_from_words(mut words: Vec<Line>) -> Vec<Line> {
    words.retain(|w| w.h > 0.0 && !w.text.trim().is_empty());
    words.sort_by(|a, b| (a.y + a.h / 2.0).total_cmp(&(b.y + b.h / 2.0)));
    let mut bands: Vec<Vec<Line>> = Vec::new();
    for w in words {
        let cy = w.y + w.h / 2.0;
        let fits = bands.last().is_some_and(|band| {
            let bcy = band.iter().map(|b| b.y + b.h / 2.0).sum::<f32>() / band.len() as f32;
            let bh = band.iter().map(|b| b.h).fold(f32::MAX, f32::min);
            (cy - bcy).abs() < 0.45 * bh.min(w.h)
        });
        if fits {
            bands.last_mut().unwrap().push(w);
        } else {
            bands.push(vec![w]);
        }
    }
    let mut out = Vec::new();
    for mut band in bands {
        band.sort_by(|a, b| a.x.total_cmp(&b.x));
        let mut current: Option<Line> = None;
        for w in band {
            current = Some(match current.take() {
                Some(mut line) if w.x - (line.x + line.w) < 1.8 * line.h.max(w.h) => {
                    let right = (line.x + line.w).max(w.x + w.w);
                    let bottom = (line.y + line.h).max(w.y + w.h);
                    line.y = line.y.min(w.y);
                    line.w = right - line.x;
                    line.h = bottom - line.y;
                    line.text = format!("{} {}", line.text, w.text);
                    line
                }
                Some(line) => {
                    out.push(line);
                    w
                }
                None => w,
            });
        }
        out.extend(current);
    }
    out.sort_by(|a, b| a.y.total_cmp(&b.y).then(a.x.total_cmp(&b.x)));
    out
}

/// Upper-case alphabetic words of two letters or more, for repairing MRZ names.
pub fn words(lines: &[Line]) -> std::collections::HashSet<String> {
    lines
        .iter()
        .flat_map(|l| {
            l.text
                .split(|c: char| !c.is_alphabetic())
                .map(|w| w.to_uppercase())
                .filter(|w| w.len() >= 2)
                .collect::<Vec<_>>()
        })
        .collect()
}

/// A recognised line with its position in the analysed image.
#[derive(Debug, Clone, Serialize)]
pub struct Line {
    pub text: String,
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

fn norm(s: &str) -> String {
    s.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(|c| c.to_uppercase())
        .collect()
}

/// Whether `line` contains `label`, tolerating one OCR error per word.
fn contains_label(line: &str, label: &str) -> bool {
    let line = norm(line);
    let label = norm(label);
    if label.is_empty() {
        return false;
    }
    if line.contains(&label) {
        return true;
    }
    let budget = if label.len() < 7 { 0 } else { (label.len() / 7).max(1) };
    line.char_indices().any(|(i, _)| {
        let tail: String = line[i..].chars().take(label.len()).collect();
        tail.len() == label.len() && hamming(&tail, &label) <= budget
    })
}

fn hamming(a: &str, b: &str) -> usize {
    a.chars().zip(b.chars()).filter(|(x, y)| x != y).count()
}

pub fn has_any(lines: &[Line], labels: &[&str]) -> bool {
    lines.iter().any(|l| labels.iter().any(|lab| contains_label(&l.text, lab)))
}

/// What a field's value must look like, so a watermark or a neighbouring
/// field's text under the label is skipped.
#[derive(Clone, Copy)]
pub enum Expect {
    Any,
    /// A three-letter country code such as `RSA`.
    CountryCode,
    /// `M` or `F`.
    Sex,
    /// A printed date: `14 MAR 1990` or `1990-03-14`.
    Date,
    /// Letters, spaces and hyphens only (names).
    Name,
}

fn plausible(value: &str, expect: Expect) -> bool {
    let v = value.trim();
    let letters = v.chars().filter(|c| c.is_alphabetic()).count();
    let digits = v.chars().filter(|c| c.is_ascii_digit()).count();
    if is_label_like(v) || letters + digits < 1 {
        return false;
    }
    match expect {
        Expect::Any => true,
        Expect::CountryCode => {
            let n = norm(v);
            n.len() == 3 && n.chars().all(|c| c.is_ascii_uppercase())
        }
        Expect::Sex => matches!(norm(v).as_str(), "M" | "F"),
        Expect::Date => digits >= 4 && (digits >= 8 || letters == 3),
        Expect::Name => letters >= 2 && digits <= 1,
    }
}

/// The value printed for a label: the rest of the label's line when it
/// carries one, else the nearest plausible line below that starts near the
/// label's left edge.
pub fn value_for(lines: &[Line], labels: &[&str]) -> Option<String> {
    value_as(lines, labels, Expect::Any)
}

pub fn value_as(lines: &[Line], labels: &[&str], expect: Expect) -> Option<String> {
    for label in labels {
        let Some(at) = lines.iter().position(|l| contains_label(&l.text, label)) else {
            continue;
        };
        let line = &lines[at];
        let rest = strip_label(&line.text, label);
        if plausible(&rest, expect) && rest.chars().filter(|c| c.is_alphanumeric()).count() >= 1 {
            return Some(rest);
        }
        let mut below: Vec<&Line> = lines
            .iter()
            .filter(|l| {
                l.y > line.y + line.h * 0.5
                    && l.y < line.y + line.h * 4.5
                    && (l.x - line.x).abs() < line.h * 3.0
            })
            .collect();
        below.sort_by(|a, b| a.y.total_cmp(&b.y));
        // Stop at the next label: a value never sits beyond it.
        for b in below {
            if is_label_like(&b.text) {
                break;
            }
            if plausible(&b.text, expect) {
                return Some(b.text.trim().to_string());
            }
        }
    }
    None
}

const ALL_LABELS: &[&str] = &[
    "Surname", "Names", "Nationality", "Identity Number", "Date of Birth",
    "Country of Birth", "Status", "Forenames", "VOORNAME", "GEBOORTEDISTRIK",
    "GEBOORTEDATUM", "UITGEREIK",
];

fn is_label_like(text: &str) -> bool {
    ALL_LABELS.iter().any(|l| contains_label(text, l))
}

fn strip_label(text: &str, label: &str) -> String {
    let lab = norm(label);
    // Walk the original text until the label's characters have been consumed.
    let mut consumed = 0;
    let mut cut = 0;
    let lab_chars: Vec<char> = lab.chars().collect();
    let upper: Vec<char> = text.chars().collect();
    let start = norm(text).find(&lab).map(|_| ()).is_some();
    if !start {
        // Fuzzy match: drop roughly the label's length of alphanumerics.
        cut = upper.len();
        for (i, c) in upper.iter().enumerate() {
            if c.is_alphanumeric() {
                consumed += 1;
            }
            if consumed + 1 >= lab_chars.len() {
                // Within one character of the label's length: allow for a
                // dropped letter, then skip the rest of that word.
                cut = upper[i + 1..]
                    .iter()
                    .position(|c| c.is_whitespace() || *c == ':')
                    .map_or(upper.len(), |p| i + 1 + p);
                break;
            }
        }
    } else {
        let mut k = 0;
        for (i, c) in upper.iter().enumerate() {
            if k < lab_chars.len() && c.to_uppercase().next() == Some(lab_chars[k]) {
                k += 1;
                if k == lab_chars.len() {
                    cut = i + 1;
                    break;
                }
            } else if c.is_alphanumeric() {
                k = 0;
                if c.to_uppercase().next() == Some(lab_chars[0]) {
                    k = 1;
                }
            }
        }
    }
    upper[cut..]
        .iter()
        .collect::<String>()
        .trim_matches(|c: char| !c.is_alphanumeric())
        .to_string()
}

pub const SMART_ID_FRONT_ANCHORS: &[&str] = &["IDENTITY CARD", "Country of Birth", "Identity Number"];
pub const PASSPORT_ANCHORS: &[&str] = &["PASSPORT", "PASPOORT", "PASSEPORT", "Date of expiry"];
pub const GREEN_BOOK_ANCHORS: &[&str] = &[
    "SUID-AFRIKA",
    "IDENTITEITSNOMMER",
    "VOORNAME",
    "GEBOORTEDATUM",
    "VAN/SURNAME",
    "BURGER",
];
pub const SA_ANCHORS: &[&str] = &["REPUBLIC OF SOUTH AFRICA", "SOUTH AFRICA"];

#[derive(Debug, Clone, Serialize, Default)]
pub struct PrintedFields {
    pub surname: Option<String>,
    pub names: Option<String>,
    pub sex: Option<String>,
    pub nationality: Option<String>,
    pub date_of_birth: Option<String>,
    pub country_of_birth: Option<String>,
    pub status: Option<String>,
    pub id_number: Option<IdNumber>,
}

pub fn smart_id_front_fields(lines: &[Line]) -> PrintedFields {
    PrintedFields {
        surname: value_as(lines, &["Surname"], Expect::Name),
        names: value_as(lines, &["Names"], Expect::Name),
        sex: value_as(lines, &["Sex"], Expect::Sex),
        nationality: value_as(lines, &["Nationality"], Expect::CountryCode),
        date_of_birth: value_as(lines, &["Date of Birth"], Expect::Date),
        country_of_birth: value_as(lines, &["Country of Birth"], Expect::CountryCode),
        status: value_as(lines, &["Status"], Expect::Name),
        id_number: lines.iter().find_map(|l| find_id_number(&l.text)),
    }
}

pub fn green_book_fields(lines: &[Line]) -> PrintedFields {
    PrintedFields {
        surname: value_as(lines, &["VAN/SURNAME", "SURNAME"], Expect::Name),
        names: value_as(lines, &["VOORNAME/FORENAMES", "FORENAMES", "VOORNAME"], Expect::Name),
        date_of_birth: value_as(lines, &["GEBOORTEDATUM/DATE OF BIRTH", "DATE OF BIRTH"], Expect::Date),
        country_of_birth: value_for(lines, &["GEBOORTEDISTRIK OF-LAND", "COUNTRY OF BIRTH"]),
        id_number: lines.iter().find_map(|l| find_id_number(&l.text)),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn luhn() {
        // A widely published sample number.
        assert!(luhn_valid("8001015009087"));
        assert!(!luhn_valid("8001015009088"));
    }

    #[test]
    fn id_number_facts() {
        let id = parse_id_number("8001015009087").unwrap();
        assert_eq!(id.sex, "M");
        assert_eq!(id.citizenship, "citizen");
        assert!(id.luhn_valid && id.date_valid);
    }

    #[test]
    fn finds_id_in_ocr_noise() {
        let id = find_id_number("I.D. No. 8OO1 O15 OO9 O87").unwrap();
        assert_eq!(id.value, "8001015009087");
    }

    #[test]
    fn smart_id_barcode() {
        let b = parse_smart_id_barcode(
            "DOE|JOHN JAMES|M|RSA|8001015009087|01 JAN 1980|RSA|CITIZEN|12 MAR 2019|10511|123456789|",
        )
        .unwrap();
        assert_eq!(b.surname, "DOE");
        assert_eq!(b.names, "JOHN JAMES");
        assert_eq!(b.status, "CITIZEN");
    }

    #[test]
    fn label_value_below() {
        let line = |t: &str, x, y| Line { text: t.into(), x, y, w: 200.0, h: 20.0 };
        let lines = vec![
            line("Surname", 100.0, 100.0),
            line("DOE", 102.0, 125.0),
            line("Names", 100.0, 160.0),
            line("JOHN JAMES", 101.0, 185.0),
        ];
        assert_eq!(value_for(&lines, &["Surname"]).as_deref(), Some("DOE"));
        assert_eq!(value_for(&lines, &["Names"]).as_deref(), Some("JOHN JAMES"));
    }
}
