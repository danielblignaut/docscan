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

/// Letter pairs OCR reads as one letter in small print (`rn` as `m`, `li`
/// as `u`), folded on both sides before labels are compared.
fn fold_confusions(s: &str) -> String {
    s.replace("RN", "M").replace("LI", "U")
}

/// Whether `line` contains `label`, tolerating one OCR error (a wrong, missing
/// or extra character) per seven characters of a label of seven or more, after
/// [`fold_confusions`].
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
    let (line, label) = (fold_confusions(&line), fold_confusions(&label));
    if line.contains(&label) {
        return true;
    }
    budget > 0 && substring_distance(&line, &label) <= budget
}

/// The fewest edits (insertions, deletions, substitutions) turning `a` into `b`.
fn edit_distance(a: &[char], b: &str) -> usize {
    let b: Vec<char> = b.chars().collect();
    let mut row: Vec<usize> = (0..=b.len()).collect();
    for (i, ca) in a.iter().enumerate() {
        let mut diag = row[0];
        row[0] = i + 1;
        for j in 1..=b.len() {
            let up = row[j];
            row[j] = (diag + usize::from(*ca != b[j - 1])).min(up + 1).min(row[j - 1] + 1);
            diag = up;
        }
    }
    row[b.len()]
}

/// The fewest edits turning `pattern` into some substring of `text`
/// (Sellers' approximate substring match).
fn substring_distance(text: &str, pattern: &str) -> usize {
    let p: Vec<char> = pattern.chars().collect();
    let mut col: Vec<usize> = (0..=p.len()).collect();
    let mut best = col[p.len()];
    for t in text.chars() {
        let mut prev_diag = col[0];
        col[0] = 0;
        for i in 1..=p.len() {
            let cur = col[i];
            col[i] = (prev_diag + usize::from(p[i - 1] != t)).min(col[i] + 1).min(col[i - 1] + 1);
            prev_diag = cur;
        }
        best = best.min(col[p.len()]);
    }
    best
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
            // `Sex:` is the card's one label of three capitals.
            n.len() == 3 && n.chars().all(|c| c.is_ascii_uppercase()) && n != "SEX"
        }
        Expect::Sex => matches!(norm(v).as_str(), "M" | "F"),
        Expect::Date => digits >= 4 && (digits >= 8 || letters == 3),
        // Stray marks alone (`I I`, a lone letter beside a dash) are no name.
        Expect::Name => letters >= 2 && digits <= 1 && clean_name(v).is_some(),
    }
}

/// Whether `l` starts in the column `label` starts: near its left edge. A
/// country code (three capitals, a strict shape) may also be read as part of
/// a box that starts further left, over the card's photo, and runs into the
/// column: the recogniser drops the photo's marks but keeps the box.
fn in_column(l: &Line, label: &Line, expect: Expect) -> bool {
    (l.x - label.x).abs() < label.h * 3.0
        || (matches!(expect, Expect::CountryCode) && l.x < label.x && l.x + l.w > label.x + label.h)
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
                // Below the label: its top past the label's middle, or (a
                // value in larger print, whose box starts level with the
                // small label) its middle past the label's foot.
                (l.y > line.y + line.h * 0.5 || l.y + l.h * 0.5 > line.y + line.h)
                    && l.y < line.y + line.h * 4.5
                    && in_column(l, line, expect)
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

/// The value printed above a label, for when the value's own label was not
/// read (cut off, or too garbled): on these layouts each value sits under
/// its label, so the value of one field is the nearest plausible line above
/// the next field's label, starting near its left edge and within two and a
/// half of its line heights.
pub fn value_above(lines: &[Line], next_labels: &[&str], expect: Expect) -> Option<String> {
    let label = next_labels.iter().find_map(|lab| lines.iter().find(|l| contains_label(&l.text, lab)))?;
    lines
        .iter()
        .filter(|l| {
            l.y + l.h <= label.y + label.h * 0.3
                && l.y >= label.y - label.h * 2.5
                && in_column(l, label, expect)
                && !is_label_like(&l.text)
                && plausible(&l.text, expect)
        })
        .max_by(|a, b| a.y.total_cmp(&b.y))
        .map(|l| l.text.trim().to_string())
}

/// The value printed to the right of a label, on the same row: where a
/// green book's photo page prints its date of birth, beside a label set
/// in two lines.
pub fn value_beside(lines: &[Line], labels: &[&str], expect: Expect) -> Option<String> {
    labels.iter().find_map(|lab| {
        let label = lines.iter().find(|l| contains_label(&l.text, lab))?;
        let mid = label.y + label.h / 2.0;
        lines
            .iter()
            .filter(|l| {
                l.x >= label.x + label.w * 0.8
                    && (l.y + l.h / 2.0 - mid).abs() < label.h.max(l.h)
                    && !is_label_like(&l.text)
                    && plausible(&l.text, expect)
            })
            .min_by(|a, b| a.x.total_cmp(&b.x))
            .map(|l| l.text.trim().to_string())
    })
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
    /// Fields filled in from the identity number because their print was
    /// not read (`"sex"`, `"date_of_birth"`): the number encodes both, and
    /// its check digit has passed.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub derived: Vec<&'static str>,
}

const MONTHS: [&str; 12] = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/// A smart ID front's printed date (`14 MAR 1990`) as (day, month, year),
/// when all three were read.
fn parse_dmy(s: &str) -> Option<(u32, u32, u32)> {
    let t: Vec<String> = s.split(|c: char| !c.is_alphanumeric()).filter(|t| !t.is_empty()).map(|t| t.to_uppercase()).collect();
    if t.len() != 3 {
        return None;
    }
    let day: u32 = t[0].parse().ok().filter(|d| (1..=31).contains(d))?;
    let month = MONTHS.iter().position(|m| *m == t[1])? as u32 + 1;
    let year: u32 = t[2].parse().ok().filter(|y| (1900..=2100).contains(y))?;
    Some((day, month, year))
}

/// Fills the card front's sex and date of birth from a valid identity number
/// when their print was not read (or the date only in part), and a
/// citizen's status and nationality, and records each in `derived`. A printed value that was read is never replaced. The
/// number gives the year without its century: a year after `this_year`
/// (two digits) is taken as the 1900s.
pub fn complete_from_id(p: &mut PrintedFields, this_year: u32) {
    let Some(id) = p.id_number.clone().filter(|id| id.luhn_valid && id.date_valid) else { return };
    if p.sex.is_none() {
        p.sex = Some(id.sex.to_string());
        p.derived.push("sex");
    }
    // The number's eleventh digit says a citizen; a smart ID's citizen
    // holder is `CITIZEN` of nationality `RSA`.
    if id.citizenship == "citizen" {
        if p.status.is_none() {
            p.status = Some("CITIZEN".into());
            p.derived.push("status");
        }
        if p.nationality.is_none() {
            p.nationality = Some("RSA".into());
            p.derived.push("nationality");
        }
    }
    let yy: u32 = id.date_of_birth[0..2].parse().unwrap_or(0);
    let mm: u32 = id.date_of_birth[2..4].parse().unwrap_or(1);
    let dd: u32 = id.date_of_birth[4..6].parse().unwrap_or(1);
    let year = if yy <= this_year % 100 { 2000 + yy } else { 1900 + yy };
    match p.date_of_birth.as_deref().and_then(parse_dmy) {
        Some(_) => {}
        None => {
            p.date_of_birth = Some(format!("{dd:02} {} {year}", MONTHS[(mm - 1) as usize]));
            p.derived.push("date_of_birth");
        }
    }
}

pub fn smart_id_front_fields(lines: &[Line]) -> PrintedFields {
    let names = value_as(lines, &["Names"], Expect::Name)
        .or_else(|| value_above(lines, &["Sex", "Nationality"], Expect::Name))
        .map(|first| match name_continued(lines, &first) {
            Some(more) => format!("{first} {more}"),
            None => first,
        });
    PrintedFields {
        surname: value_as(lines, &["Surname"], Expect::Name).or_else(|| value_above(lines, &["Names"], Expect::Name)).and_then(|v| clean_name(&v)),
        names: names.and_then(|v| clean_name(&v)),
        sex: value_as(lines, &["Sex"], Expect::Sex),
        // A value whose own label was not read sits above the next label.
        nationality: value_as(lines, &["Nationality"], Expect::CountryCode)
            .or_else(|| value_above(lines, &["Identity Number"], Expect::CountryCode)),
        date_of_birth: value_as(lines, &["Date of Birth"], Expect::Date),
        country_of_birth: value_as(lines, &["Country of Birth"], Expect::CountryCode)
            .or_else(|| value_above(lines, &["Status"], Expect::CountryCode))
            // Both labels lost: the code printed above the status itself.
            .or_else(|| value_above(lines, &["CITIZEN"], Expect::CountryCode)),
        status: value_as(lines, &["Status"], Expect::Name).map(|v| snap_status(&v)),
        id_number: lines.iter().find_map(|l| find_id_number(&l.text)),
        derived: Vec::new(),
    }
}

/// A name as printed: its words of letters, without the stray marks OCR
/// picks up beside it (a lone letter or digits from the hologram, the
/// security print or the photo's edge). Hyphens and apostrophes inside a
/// word are kept. `None` when nothing is left.
pub fn clean_name(value: &str) -> Option<String> {
    let mut words: Vec<String> = value
        .split_whitespace()
        .filter(|w| !w.chars().any(|c| c.is_ascii_digit()))
        .map(|w| w.trim_matches(|c: char| !c.is_alphabetic()).to_string())
        .filter(|w| !w.is_empty())
        .collect();
    // A lone letter at either end is a stray mark, not a name: names on
    // these documents are written in full.
    while words.last().is_some_and(|w| w.chars().count() == 1) {
        words.pop();
    }
    while words.first().is_some_and(|w| w.chars().count() == 1) {
        words.remove(0);
    }
    (!words.is_empty()).then(|| words.join(" "))
}

/// The second line of a name too long for one (the card prints it on the
/// next line, under the first): the line right below `first`, starting
/// where it starts, in capitals and not a label.
fn name_continued(lines: &[Line], first: &str) -> Option<String> {
    let line = lines.iter().find(|l| l.text.trim() == first)?;
    lines
        .iter()
        .filter(|l| {
            l.y > line.y + line.h * 0.5
                && l.y < line.y + line.h * 1.8
                && (l.x - line.x).abs() < line.h * 1.5
                && !is_label_like(&l.text)
                && !contains_label(&l.text, "Sex")
                && !l.text.chars().any(|c| c.is_lowercase())
                && plausible(&l.text, Expect::Name)
        })
        .min_by(|a, b| a.y.total_cmp(&b.y))
        .map(|l| l.text.trim().to_string())
}

/// The smart ID's status, `CITIZEN`, through a misread letter or two
/// (`CITIZE`, `CITEZEN`); anything else is kept as read.
fn snap_status(value: &str) -> String {
    let n = norm(value);
    if n.len().abs_diff(7) <= 2 && substring_distance(&n, "CITIZEN").min(substring_distance("CITIZEN", &n)) <= 2 {
        "CITIZEN".to_string()
    } else {
        value.to_string()
    }
}

/// The smart ID front's own labels, each counted once when a line begins
/// with it. A green book's labels are compound (`VAN/SURNAME`,
/// `VOORNAME/FORENAMES`, `DISTRICT OR COUNTRY OF BIRTH`) and do not begin
/// with the card's. The labels are small, light print, and real photos
/// lose letters of them (`entity Numbe`, `lationaiity`, `Date Or Birtn`):
/// a label of five letters or more is matched through one error in four.
pub const SMART_ID_FRONT_LABELS: &[&str] =
    &["Surname", "Names", "Sex", "Nationality", "Identity Number", "Date of Birth", "Country of Birth", "Status"];

pub fn front_labels(lines: &[Line]) -> usize {
    SMART_ID_FRONT_LABELS
        .iter()
        .filter(|label| {
            let want = norm(label);
            let want = fold_confusions(&want);
            let budget = if want.len() < 5 { 0 } else { want.len() / 4 };
            lines.iter().any(|l| {
                let line: Vec<char> = fold_confusions(&norm(&l.text)).chars().collect();
                // The line's beginning, as long as the label give or take the budget.
                (want.len().saturating_sub(budget)..=want.len() + budget)
                    .any(|k| k <= line.len() && edit_distance(&line[..k], &want) <= budget)
            })
        })
        .count()
}

/// The printed fields the identity number confirms: a date of birth and a
/// sex that were read (not filled in from the number) and agree with it.
/// Two readings of the same frame that agree are independent evidence that
/// the number was read right; the check digit alone catches only most
/// misreads.
pub fn confirmed_by_id(p: &PrintedFields) -> Vec<&'static str> {
    let Some(id) = p.id_number.as_ref().filter(|id| id.luhn_valid && id.date_valid) else { return Vec::new() };
    let mut out = Vec::new();
    // `14 MAR 1990` (the card) or `1990-03-14` (the book), as the number's YYMMDD.
    let yymmdd = |d: &str| -> Option<String> {
        if let Some((day, month, year)) = parse_dmy(d) {
            return Some(format!("{:02}{month:02}{day:02}", year % 100));
        }
        let digits: String = d.chars().filter(|c| c.is_ascii_digit()).collect();
        (digits.len() == 8).then(|| digits[2..8].to_string())
    };
    if !p.derived.contains(&"date_of_birth") && p.date_of_birth.as_deref().and_then(yymmdd).as_deref() == Some(id.date_of_birth.as_str()) {
        out.push("date_of_birth");
    }
    if !p.derived.contains(&"sex") && p.sex.as_deref().map(norm).as_deref() == Some(id.sex) {
        out.push("sex");
    }
    out
}

/// A green book's date as printed, `YYYY-MM-DD`, read through misread
/// separators: real pages print small dashes that OCR reads as a digit or a
/// letter (`1980101-01`). Ten characters with digits everywhere but the two
/// separators' places are that date, when it is a real one; anything else is
/// kept as read.
fn book_date(value: &str) -> String {
    let c: Vec<char> = value.trim().chars().collect();
    let digits_at = |r: std::ops::Range<usize>| r.clone().all(|i| c[i].is_ascii_digit());
    if c.len() == 10 && digits_at(0..4) && digits_at(5..7) && digits_at(8..10) && !(c[4].is_ascii_digit() && c[7].is_ascii_digit()) {
        let s: String = c.iter().collect();
        let (y, m, d): (u32, u32, u32) = (s[0..4].parse().unwrap(), s[5..7].parse().unwrap(), s[8..10].parse().unwrap());
        if (1900..=2100).contains(&y) && (1..=12).contains(&m) && (1..=31).contains(&d) {
            return format!("{}-{}-{}", &s[0..4], &s[5..7], &s[8..10]);
        }
    }
    value.trim().to_string()
}

/// The identity number printed on a green book's page (not its barcode's).
pub fn green_book_printed_number(lines: &[Line]) -> Option<IdNumber> {
    lines.iter().find_map(|l| find_id_number(&l.text))
}

pub fn green_book_fields(lines: &[Line]) -> PrintedFields {
    PrintedFields {
        surname: value_as(lines, &["VAN/SURNAME", "SURNAME"], Expect::Name)
            .or_else(|| value_above(lines, &["VOORNAME/FORENAMES", "FORENAMES", "VOORNAME"], Expect::Name))
            .and_then(|v| clean_name(&v)),
        names: value_as(lines, &["VOORNAME/FORENAMES", "FORENAMES", "VOORNAME"], Expect::Name)
            .or_else(|| value_above(lines, &["GEBOORTEDISTRIK OF-LAND", "COUNTRY OF BIRTH"], Expect::Name))
            .and_then(|v| clean_name(&v)),
        date_of_birth: value_as(lines, &["GEBOORTEDATUM/DATE OF BIRTH", "DATE OF BIRTH"], Expect::Date)
            .or_else(|| value_beside(lines, &["GEBOORTEDATUM", "DATE OF BIRTH"], Expect::Date))
            .map(|d| book_date(&d)),
        country_of_birth: value_for(lines, &["GEBOORTEDISTRIK OF-LAND", "COUNTRY OF BIRTH"]),
        id_number: green_book_printed_number(lines),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn front_fields_completed_from_the_id_number() {
        let mut p = PrintedFields { id_number: parse_id_number("8001015009087"), date_of_birth: Some("JAN1980".into()), ..Default::default() };
        complete_from_id(&mut p, 2026);
        assert_eq!(p.sex.as_deref(), Some("M"));
        assert_eq!(p.date_of_birth.as_deref(), Some("01 JAN 1980"));
        assert_eq!(p.derived, ["sex", "status", "nationality", "date_of_birth"]);
        assert_eq!((p.status.as_deref(), p.nationality.as_deref()), (Some("CITIZEN"), Some("RSA")));
        // Read print stays, even where it disagrees.
        let mut p = PrintedFields {
            id_number: parse_id_number("8001015009087"),
            sex: Some("F".into()),
            date_of_birth: Some("02 JAN 1980".into()),
            status: Some("CITIZEN".into()),
            nationality: Some("RSA".into()),
            ..Default::default()
        };
        complete_from_id(&mut p, 2026);
        assert_eq!((p.sex.as_deref(), p.date_of_birth.as_deref()), (Some("F"), Some("02 JAN 1980")));
        assert!(p.derived.is_empty());
    }

    #[test]
    fn labels_survive_common_misreads() {
        assert!(contains_label("Sumame:", "Surname"));
        assert!(contains_label("VAN/SLIRNAME", "VAN/SURNAME"));
        assert!(contains_label("VOORNAM/ORENAMES", "VOORNAME/FORENAMES"));
        // Short labels stay exact: a name is not the label `Names`.
        assert!(!contains_label("JAMES", "Names"));
        assert!(!contains_label("DLAMINI", "Surname"));
    }

    #[test]
    fn value_above_the_next_label() {
        let line = |t: &str, x, y| Line { text: t.into(), x, y, w: 200.0, h: 20.0 };
        // The surname's label was cut to `VA`; its value sits above the forenames label.
        let lines = vec![
            line("PHOTO", 300.0, 20.0),
            line("VA", 100.0, 100.0),
            line("KOWALSKI", 101.0, 125.0),
            line("VOORNAM/ORENAMES", 100.0, 160.0),
            line("SIPHO", 101.0, 185.0),
        ];
        let f = green_book_fields(&lines);
        assert_eq!(f.surname.as_deref(), Some("KOWALSKI"));
        assert_eq!(f.names.as_deref(), Some("SIPHO"));
    }

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

    fn at(t: &str, x: f32, y: f32) -> Line {
        Line { text: t.into(), x, y, w: 200.0, h: 20.0 }
    }

    /// A real card front as OCR reads it: the header lost, labels missing
    /// letters, a name wrapped onto a second line, stray marks beside the
    /// surname, `CITIZEN` misread and the country of birth's label garbled.
    fn worn_front() -> Vec<Line> {
        vec![
            at("Surnama:", 100.0, 100.0),
            at("DOE P", 100.0, 122.0),
            at("Names:", 100.0, 150.0),
            at("JOHN ALEXANDER", 100.0, 172.0),
            at("JAMES", 100.0, 194.0),
            at("lationaiity", 100.0, 222.0),
            at("RSA", 100.0, 244.0),
            at("entity Numbe", 100.0, 272.0),
            at("8001015009087", 100.0, 294.0),
            at("Date of Birth:", 100.0, 322.0),
            at("01 JAN 1980", 100.0, 344.0),
            at("Couy of Brt", 100.0, 372.0),
            at("RSA", 100.0, 394.0),
            at("Status:", 100.0, 422.0),
            at("CITIZE", 100.0, 444.0),
            at("Sex:", 400.0, 372.0),
            at("M", 400.0, 394.0),
        ]
    }

    #[test]
    fn worn_front_fields() {
        let lines = worn_front();
        assert!(front_labels(&lines) >= 5);
        let mut p = smart_id_front_fields(&lines);
        complete_from_id(&mut p, 2026);
        assert_eq!(p.surname.as_deref(), Some("DOE"));
        assert_eq!(p.names.as_deref(), Some("JOHN ALEXANDER JAMES"));
        assert_eq!(p.status.as_deref(), Some("CITIZEN"));
        assert_eq!(p.country_of_birth.as_deref(), Some("RSA"));
        assert_eq!(p.sex.as_deref(), Some("M"));
        // Both labels around the nationality are garbled: a citizen's is RSA.
        assert_eq!((p.nationality.as_deref(), p.derived.as_slice()), (Some("RSA"), ["nationality"].as_slice()));
        assert_eq!(confirmed_by_id(&p), ["date_of_birth", "sex"]);
        // A date that disagrees with the number confirms nothing.
        p.date_of_birth = Some("02 JAN 1980".into());
        assert_eq!(confirmed_by_id(&p), ["sex"]);
    }

    #[test]
    fn names_without_stray_marks() {
        assert_eq!(clean_name("DOE P").as_deref(), Some("DOE"));
        assert_eq!(clean_name("JOHN JAMES 9").as_deref(), Some("JOHN JAMES"));
        assert_eq!(clean_name("I VAN DER MERWE.").as_deref(), Some("VAN DER MERWE"));
        assert_eq!(clean_name("O'NEILL-SMITH").as_deref(), Some("O'NEILL-SMITH"));
        assert_eq!(clean_name("1 2"), None);
    }

    #[test]
    fn green_book_date_beside_its_label() {
        // The photo page prints the date to the right of its two-line label.
        let lines = vec![
            at("VAN/SURNAME", 100.0, 100.0),
            at("DOE", 100.0, 122.0),
            at("1980-01-01", 330.0, 196.0),
            at("GEBOORTEDATUM", 100.0, 205.0),
            at("DATE OF BIRTH", 100.0, 220.0),
            at("DATUM UITGEREIK", 320.0, 245.0),
            at("DATE ISSUED", 320.0, 262.0),
            at("2001-06-23", 330.0, 284.0),
        ];
        assert_eq!(green_book_fields(&lines).date_of_birth.as_deref(), Some("1980-01-01"));
    }

    #[test]
    fn values_past_stray_marks_and_in_larger_print() {
        // Stray marks beside the label are no surname: the name below is.
        let lines = vec![at("Surname: I I", 100.0, 100.0), at("-", 100.0, 118.0), at("DOE", 100.0, 136.0), at("Names", 100.0, 170.0)];
        assert_eq!(smart_id_front_fields(&lines).surname.as_deref(), Some("DOE"));
        // A book's forenames, in print larger than the small label above
        // them, start level with the label's middle.
        let small = |t: &str, x: f32, y: f32, h: f32| Line { text: t.into(), x, y, w: 200.0, h };
        let lines = vec![
            small("SURNAME", 70.0, 184.0, 15.0),
            small("DOE", 70.0, 199.0, 25.0),
            small("FORENAMES", 70.0, 265.0, 15.0),
            small("JOHN JAMES", 35.0, 272.0, 39.0),
            small("COUNTRY OF BIRTH", 70.0, 344.0, 17.0),
        ];
        assert_eq!(green_book_fields(&lines).names.as_deref(), Some("JOHN JAMES"));
    }

    #[test]
    fn country_of_birth_without_its_labels_or_beside_the_photo() {
        let lines = vec![
            at("Date of Birth", 250.0, 390.0),
            at("01 JAN 1980", 250.0, 415.0),
            at("RSA", 250.0, 466.0),
            at("CITIZEN", 250.0, 514.0),
        ];
        assert_eq!(smart_id_front_fields(&lines).country_of_birth.as_deref(), Some("RSA"));
        // A box running in from the photo, on the left, into the label's column.
        let wide = Line { text: "RSA".into(), x: 67.0, y: 440.0, w: 373.0, h: 38.0 };
        let lines = vec![at("Country of Birth:", 240.0, 415.0), wide, at("Status:", 240.0, 464.0)];
        assert_eq!(smart_id_front_fields(&lines).country_of_birth.as_deref(), Some("RSA"));
        // A name never comes from such a box.
        let wide = Line { text: "DOE".into(), x: 67.0, y: 440.0, w: 373.0, h: 20.0 };
        assert_eq!(value_as(&[at("Surname", 240.0, 415.0), wide], &["Surname"], Expect::Name), None);
    }

    #[test]
    fn book_dates_through_misread_dashes() {
        assert_eq!(book_date("1980101-01"), "1980-01-01");
        assert_eq!(book_date("1980-01S01"), "1980-01-01");
        assert_eq!(book_date("1980-01-01"), "1980-01-01");
        // Both dashes read as digits, or an impossible month: kept as read.
        assert_eq!(book_date("1980101101"), "1980101101");
        assert_eq!(book_date("1980-13-01"), "1980-13-01");
    }

    #[test]
    fn book_labels_are_not_card_labels() {
        let lines = vec![
            at("VAN/SURNAME", 100.0, 100.0),
            at("VOORNAME/FORENAMES", 100.0, 150.0),
            at("GEBOORTEDISTRIK OF-LAND/", 100.0, 200.0),
            at("DISTRICT OR COUNTRY OF BIRTH", 100.0, 220.0),
            at("GEBOORTEDATUM/DATE OF BIRTH", 100.0, 260.0),
        ];
        assert_eq!(front_labels(&lines), 0);
    }
}
