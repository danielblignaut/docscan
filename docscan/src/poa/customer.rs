//! Verification against a known customer: does this page show *this* person
//! at *this* address, dated within three months?
//!
//! Unlike blind extraction, the question is narrow, so the whole page's OCR
//! text is searched rather than only what the tagger tagged:
//!
//! - **Name**: the surname (one OCR slip allowed in a long one; multi-word
//!   surnames squashed) with the given names or initials printed beside it
//!   matched, in order, to the forenames on the customer's ID (`MR S J NKOSI`,
//!   `Nkosi, SJ`, `Sipho Nkosi`). A first name or initial that contradicts the
//!   ID is a different person; "Mr & Mrs" with the spouse's initial is
//!   accepted as a joint account and said so.
//! - **Address**: the house number exactly (letters OCR reads for digits
//!   folded), the street name by similarity, the suffix normalised (`St` =
//!   `Street`, `Rd` = `Road`, ...), and the suburb, city or postal code in
//!   the lines that follow. The occurrence must be the holder's: linked to a
//!   printed holder name above it (or in the sentence before it), and not in
//!   a block of the issuer's own contact details (head office, PO Box, Tel,
//!   VAT ...). Linking it through the tagger's STREET spans instead added
//!   nothing on the DEV set and once linked an issuer's address, so the
//!   decision rests on the printed text alone.
//! - **Date**: the document date the extractor read (voted across frames),
//!   within three calendar months.
//!
//! Every decision carries the scores and the printed lines it rests on.

use serde::{Deserialize, Serialize};

use super::features::Word;
use super::tagger::Span;
use super::verify::{self, Age, Date, similarity};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CustomerAddress {
    #[serde(default)]
    pub street: Option<String>,
    #[serde(default)]
    pub suburb: Option<String>,
    #[serde(default)]
    pub city: Option<String>,
    #[serde(default)]
    pub province: Option<String>,
    #[serde(default)]
    pub postal_code: Option<String>,
}

/// The known customer: the name as on their ID (forenames then surname; give
/// `surname` separately when known, e.g. from the ID's own field) and the
/// address they gave.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Customer {
    pub name: String,
    #[serde(default)]
    pub surname: Option<String>,
    #[serde(default)]
    pub address: CustomerAddress,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct NameMatch {
    /// 0–1: the surname's similarity times how well the given names agree.
    pub score: f32,
    /// The printed line the best match is on.
    pub line: String,
    pub surname_score: f32,
    /// 1: given names/initials agree; 0.8: "Mr & Mrs" with another initial;
    /// 0.6: surname only (no given name printed beside it); 0: they contradict.
    pub given_score: f32,
    pub note: Option<String>,
    #[serde(skip)]
    pub line_index: usize,
    /// The line's box, as fractions of the extent of the page's words (x0, y0, x1, y1).
    #[serde(skip)]
    pub bbox: [f32; 4],
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct AddressMatch {
    /// 0–1: street similarity, weighed with the locality.
    pub score: f32,
    /// The street line's box, as fractions of the extent of the page's words, and a line's height.
    #[serde(skip)]
    pub bbox: [f32; 4],
    #[serde(skip)]
    pub line_h: f32,
    pub street_score: f32,
    /// Share of the suburb, city and postal code given that were found near it.
    pub locality_score: f32,
    pub postal_code: Option<bool>,
    pub city: Option<bool>,
    pub suburb: Option<bool>,
    /// Linked to the holder: the customer's name printed above it (or in the sentence before it).
    pub holder_linked: bool,
    /// Inside a block of the issuer's contact details.
    pub issuer_block: bool,
    /// The printed lines it was found on.
    pub lines: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct CustomerCheck {
    pub accepted: bool,
    pub reasons: Vec<String>,
    pub name: Option<NameMatch>,
    /// The best occurrence of the customer's address that belongs to the holder.
    pub address: Option<AddressMatch>,
    /// The best occurrence at all, when it is not the holder's (e.g. the
    /// issuer's own address), or the same street with another number.
    pub address_elsewhere: Option<AddressMatch>,
    pub date: Option<Age>,
    /// Occurrences of the address that are the holder's in every way but
    /// the printed name above them, which another frame of the capture may
    /// have read ([`super::capture::combine_checks`]).
    #[serde(skip)]
    pub unlinked: Vec<AddressMatch>,
    /// The customer's name lines found, with their boxes, for the same.
    #[serde(skip)]
    pub names: Vec<NameMatch>,
}

/// Thresholds of the decision (calibrated on the DEV set, never the lockbox).
pub const NAME_MIN: f32 = 0.75;
pub const STREET_MIN: f32 = 0.8;
pub const LOCALITY_MIN: f32 = 0.5;

// --------------------------------------------------------------------------
// Text helpers
// --------------------------------------------------------------------------

fn norm(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_uppercase()).collect()
}

/// Digits OCR reads as look-alike letters, for comparing words.
fn fold_letters(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            '0' => 'O',
            '1' => 'I',
            '5' => 'S',
            '8' => 'B',
            'L' => 'I',
            'J' => 'I',
            _ => c,
        })
        .collect()
}

/// Letters OCR reads for digits, in a number.
fn fold_digits(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'O' | 'D' | 'Q' => '0',
            'I' | 'L' | '|' => '1',
            'S' | '$' => '5',
            'B' => '8',
            'Z' => '2',
            _ => c,
        })
        .collect()
}

/// Pairs of capitals (and digits) OCR mistakes for each other.
const CONFUSABLE: &[(char, char)] = &[
    ('C', 'G'), ('C', 'O'), ('C', 'E'), ('D', 'O'), ('Q', 'O'), ('U', 'V'), ('M', 'N'), ('E', 'F'), ('P', 'R'), ('H', 'N'), ('I', 'T'),
    ('I', 'J'), ('Y', 'V'), ('K', 'X'), ('A', '4'), ('G', '6'), ('Z', '2'), ('R', 'K'), ('B', 'E'), ('H', 'K'), ('I', 'E'), ('U', 'O'),
    ('A', 'O'),
];

/// Whether `a` is `b` with exactly one letter swapped for a look-alike (after
/// folding the digits OCR reads for letters).
fn confusable_slip(a: &str, b: &str) -> bool {
    let (a, b): (Vec<char>, Vec<char>) = (fold_letters(a).chars().collect(), fold_letters(b).chars().collect());
    if a.len() != b.len() {
        return false;
    }
    let diff: Vec<(char, char)> = a.iter().zip(&b).filter(|(x, y)| x != y).map(|(x, y)| (*x, *y)).collect();
    matches!(diff.as_slice(), [(x, y)] if CONFUSABLE.iter().any(|&(p, q)| (p, q) == (*x, *y) || (q, p) == (*x, *y)))
}

fn word_sim(a: &str, b: &str) -> f32 {
    similarity(&fold_letters(a), &fold_letters(b))
}

const TITLES: &[&str] = &["MR", "MRS", "MS", "MISS", "DR", "PROF", "MNR", "MEV", "ME", "MEJ", "ADV", "REV", "SIR"];
const CONNECTORS: &[&str] = &["AND", "EN"];
const PARTICLES: &[&str] = &["VAN", "DER", "DEN", "DU", "LE", "DE", "LA", "VON", "DA", "DOS", "TE", "TER", "DI"];
const LABELS: &[&str] = &[
    "NAME", "ACCOUNT", "HOLDER", "CUSTOMER", "CLIENT", "TENANT", "LESSEE", "POLICYHOLDER", "MEMBER", "DEAR", "ATTENTION",
    "ATTN", "TO", "BILL", "BILLED", "INVOICE", "DELIVER", "ADDRESSEE", "INSURED", "CONSUMER", "FOR", "STATEMENT",
];

/// Street suffixes and their abbreviations, to one canonical form.
pub(crate) fn suffix(token: &str) -> Option<&'static str> {
    Some(match token {
        "STREET" | "ST" | "STR" | "STRAAT" => "STREET",
        "ROAD" | "RD" | "WEG" => "ROAD",
        "AVENUE" | "AVE" | "AV" | "LAAN" | "RYLAAN" => "AVENUE",
        "DRIVE" | "DR" | "RYLAAN." => "DRIVE",
        "CRESCENT" | "CRES" | "CR" | "SINGEL" => "CRESCENT",
        "LANE" | "LN" | "STEEG" => "LANE",
        "CLOSE" | "CL" => "CLOSE",
        "WAY" | "WY" => "WAY",
        "PLACE" | "PL" | "PLEK" => "PLACE",
        "BOULEVARD" | "BLVD" => "BOULEVARD",
        "HIGHWAY" | "HWY" => "HIGHWAY",
        "TERRACE" | "TCE" => "TERRACE",
        "CIRCLE" | "CIR" => "CIRCLE",
        "COURT" | "CT" => "COURT",
        _ => return None,
    })
}

/// The spellings of a canonical street suffix.
fn suffix_forms(canonical: &str) -> Vec<&'static str> {
    const ALL: &[&str] = &[
        "STREET", "ST", "STR", "STRAAT", "ROAD", "RD", "WEG", "AVENUE", "AVE", "AV", "LAAN", "RYLAAN", "DRIVE", "DR", "CRESCENT", "CRES", "CR",
        "SINGEL", "LANE", "LN", "STEEG", "CLOSE", "CL", "WAY", "WY", "PLACE", "PL", "PLEK", "BOULEVARD", "BLVD", "HIGHWAY", "HWY", "TERRACE",
        "TCE", "CIRCLE", "CIR", "COURT", "CT",
    ];
    ALL.iter().copied().filter(|f| suffix(f) == Some(canonical)).collect()
}

/// Whether a token is the customer's street suffix, allowing one letter OCR
/// confuses ("CT" read for "CL").
fn same_suffix(token: &str, canonical: &str) -> bool {
    suffix(token) == Some(canonical) || suffix_forms(canonical).iter().any(|f| f.len() >= 2 && confusable_slip(token, f))
}

/// Words of the issuer's own address and contact block (as in `rules.rs`).
const ISSUER_CUES: &[&str] = &[
    "HEAD OFFICE", "REGISTERED OFFICE", "PO BOX", "P O BOX", "POBOX", "PRIVATE BAG", "TEL", "FAX", "VAT", "REG NO", "REGISTRATION",
    "WWW", "BRANCH", "PAYMENT ADDRESS", "RETURN ADDRESS", "PAY AT", "CALL CENTRE",
];

// --------------------------------------------------------------------------
// Lines and blocks
// --------------------------------------------------------------------------

struct Line {
    words: Vec<usize>,
    tokens: Vec<String>,
    /// Token -> word index (a word with no letters or digits gives no token).
    token_word: Vec<usize>,
    x0: f32,
    x1: f32,
    y0: f32,
    y1: f32,
    text: String,
    upper: String,
}

fn build_lines(words: &[Word]) -> Vec<Line> {
    let n = words.iter().map(|w| w.line).max().map_or(0, |m| m + 1);
    let mut lines: Vec<Line> = (0..n)
        .map(|_| Line { words: vec![], tokens: vec![], token_word: vec![], x0: f32::MAX, x1: f32::MIN, y0: f32::MAX, y1: f32::MIN, text: String::new(), upper: String::new() })
        .collect();
    for (i, w) in words.iter().enumerate() {
        let l = &mut lines[w.line];
        l.words.push(i);
        l.x0 = l.x0.min(w.x);
        l.x1 = l.x1.max(w.x + w.w);
        l.y0 = l.y0.min(w.y);
        l.y1 = l.y1.max(w.y + w.h);
        if !l.text.is_empty() {
            l.text.push(' ');
        }
        l.text.push_str(&w.text);
        // "$" is a 5 OCR misread ("$33 Seme Grove"); norm would drop it.
        let t = norm(&w.text.replace('$', "S"));
        // A house number OCR ran into the street name ("17KLIPLANE"): two tokens.
        let digits = t.chars().take_while(|c| c.is_ascii_digit()).count();
        if (1..=5).contains(&digits) && t.len() - digits >= 2 && t[digits..].chars().all(|c| c.is_ascii_uppercase()) {
            l.tokens.push(t[..digits].to_string());
            l.token_word.push(i);
            l.tokens.push(t[digits..].to_string());
            l.token_word.push(i);
        } else if t.len() >= 7 && t[t.len() - 4..].chars().all(|c| c.is_ascii_digit()) && t[..t.len() - 4].chars().all(|c| c.is_ascii_uppercase()) {
            // A place run into its postal code ("EKURHULENI1546"): two tokens.
            l.tokens.push(t[..t.len() - 4].to_string());
            l.token_word.push(i);
            l.tokens.push(t[t.len() - 4..].to_string());
            l.token_word.push(i);
        } else if !t.is_empty() {
            l.tokens.push(t);
            l.token_word.push(i);
        }
    }
    for l in &mut lines {
        l.upper = format!(" {} ", verify::normalise(&l.text));
    }
    lines.retain(|l| !l.words.is_empty());
    lines
}

/// The line directly below `i` in the same column, if close enough to
/// continue its block.
fn below(lines: &[Line], i: usize) -> Option<usize> {
    let a = &lines[i];
    let h = (a.y1 - a.y0).max(1.0);
    (0..lines.len())
        .filter(|&j| j != i)
        .filter(|&j| {
            let b = &lines[j];
            b.y0 > a.y0 + 0.5 * h && b.y0 - a.y1 < 1.6 * h && b.x0 < a.x1 && b.x1 > a.x0
        })
        .min_by(|&p, &q| lines[p].y0.total_cmp(&lines[q].y0).then(lines[p].x0.total_cmp(&lines[q].x0)))
}

fn above(lines: &[Line], i: usize) -> Option<usize> {
    let a = &lines[i];
    let h = (a.y1 - a.y0).max(1.0);
    (0..lines.len())
        .filter(|&j| j != i)
        .filter(|&j| {
            let b = &lines[j];
            b.y0 < a.y0 - 0.5 * h && a.y0 - b.y1 < 1.6 * h && b.x0 < a.x1 && b.x1 > a.x0
        })
        .max_by(|&p, &q| lines[p].y0.total_cmp(&lines[q].y0))
}

fn chain(lines: &[Line], i: usize, n: usize, step: fn(&[Line], usize) -> Option<usize>) -> Vec<usize> {
    let mut out = Vec::new();
    let mut cur = i;
    for _ in 0..n {
        match step(lines, cur) {
            Some(j) if !out.contains(&j) && j != i => {
                out.push(j);
                cur = j;
            }
            _ => break,
        }
    }
    out
}

fn has_issuer_cue(l: &Line) -> bool {
    ISSUER_CUES.iter().any(|c| l.upper.contains(&format!(" {c} ")))
}

// --------------------------------------------------------------------------
// Names
// --------------------------------------------------------------------------

/// Forenames and surname of the customer.
pub fn split_name(c: &Customer) -> (Vec<String>, String) {
    let toks: Vec<String> = c.name.split_whitespace().map(norm).filter(|t| !t.is_empty()).collect();
    if let Some(s) = &c.surname {
        let sn: Vec<String> = s.split_whitespace().map(norm).filter(|t| !t.is_empty()).collect();
        let joined = sn.concat();
        // The forenames: the name without the surname's words.
        let mut given = toks.clone();
        if given.len() >= sn.len() && given[given.len() - sn.len()..] == sn[..] {
            given.truncate(given.len() - sn.len());
        } else if given.len() >= sn.len() && given[..sn.len()] == sn[..] {
            given.drain(..sn.len());
        }
        return (given, joined);
    }
    // Surname: the last word, with the particles before it ("van der Merwe").
    let mut k = toks.len().saturating_sub(1);
    while k > 1 && PARTICLES.contains(&toks[k - 1].as_str()) {
        k -= 1;
    }
    (toks[..k].to_vec(), toks[k..].concat())
}

enum Given {
    Initial(char),
    Name(String),
}

fn given_items(words: &[&str]) -> Vec<Given> {
    let mut out = Vec::new();
    for w in words {
        let t = norm(w);
        if t.is_empty() {
            continue;
        }
        let raw_upper = w.chars().filter(|c| c.is_alphabetic()).all(|c| c.is_uppercase());
        if let Some(c) = super::initial_digit(w) {
            out.push(Given::Initial(c));
        } else if t.len() == 1 {
            out.push(Given::Initial(t.chars().next().unwrap()));
        } else if t.len() <= 3 && raw_upper && t.chars().all(|c| c.is_alphabetic()) && (w.len() <= 3 || w.contains('.')) {
            // "SJ", "S.J."
            out.extend(t.chars().map(Given::Initial));
        } else if t.len() <= 3 && t.chars().any(|c| c.is_ascii_digit()) && t.chars().all(|c| c.is_alphabetic() || super::initial_digit(&c.to_string()).is_some()) {
            // Initials with a letter OCR read as a digit ("L2" for "LZ").
            out.extend(t.chars().map(|c| Given::Initial(super::initial_digit(&c.to_string()).unwrap_or(c))));
        } else {
            out.push(Given::Name(t));
        }
    }
    out
}

/// How well the given names printed beside a surname agree with the ID's.
fn given_agreement(items: &[Given], given: &[String]) -> f32 {
    if items.is_empty() {
        return 0.6;
    }
    let try_from = |start: usize| -> bool {
        items.iter().enumerate().all(|(k, it)| {
            let Some(g) = given.get(start + k) else { return false };
            match it {
                Given::Initial(c) => g.starts_with(*c) || fold_letters(&c.to_string()) == fold_letters(&g[..1]),
                Given::Name(s) => word_sim(s, g) >= 0.75 || (s.len() >= 4 && g.starts_with(s.as_str())),
            }
        })
    };
    if try_from(0) {
        1.0
    } else if given.len() > 1 && try_from(1) {
        // Known by a second forename.
        0.9
    } else {
        0.0
    }
}

/// A piece of a printed name line: a word, or part of one OCR ran together
/// with its neighbour ("MRLS" for "MR LS", "D.Sacoor" for "D. Sacoor").
struct Piece {
    /// Letters and digits, in capitals.
    t: String,
    /// As printed (initials are told from names by their case and stops).
    raw: String,
    /// A comma or full stop after it ("Nkosi, SJ", often read "Nkosi. SJ").
    stop_after: bool,
    /// Starts with a lower-case letter: a word of the sentence around a name.
    lower: bool,
    colon: bool,
}

/// Titles as OCR reads them at the start of a name line ("Kr", "Nrs" for
/// "Mr", "Mrs"), taken as titles only there.
const OCR_TITLES: &[&str] = &["KR", "NR", "XR", "NRS", "HRS", "MRA", "M5", "MI", "NS", "KISS", "NISS", "HISS"];

fn pieces(l: &Line, words: &[Word]) -> Vec<Piece> {
    let mut out = Vec::new();
    for &wi in &l.words {
        let raw = words[wi].text.as_str();
        if raw == "&" {
            out.push(Piece { t: "AND".into(), raw: "&".into(), stop_after: false, lower: false, colon: false });
            continue;
        }
        let t = norm(raw);
        if t.is_empty() {
            continue;
        }
        // Two words OCR joined at a comma or full stop: "Wetlumuntshe.FM", "Nkosi,SJ".
        if let Some(k) = raw.find([',', '.'])
            && k >= 3
            && raw[..k].chars().all(char::is_alphabetic)
            && raw[k + 1..].chars().count() >= 1
            && raw[k + 1..].chars().all(char::is_alphabetic)
            && raw[k + 1..].chars().all(char::is_uppercase)
        {
            let (a, b) = (&raw[..k], &raw[k + 1..]);
            out.push(Piece { t: norm(a), raw: a.to_string(), stop_after: true, lower: a.chars().next().is_some_and(char::is_lowercase), colon: false });
            out.push(Piece { t: norm(b), raw: b.to_string(), stop_after: false, lower: false, colon: false });
            continue;
        }
        let stop_after = raw.ends_with(',') || raw.ends_with('.');
        let lower = raw.chars().next().is_some_and(char::is_lowercase);
        let colon = raw.ends_with(':');
        // An initial run into the next word at a full stop: "D.Sacoor", "M.Ndlovu".
        if let Some((a, b)) = raw.split_once('.')
            && !a.is_empty()
            && a.chars().all(char::is_alphabetic)
            && a.chars().count() <= 2
            && b.chars().filter(|c| c.is_alphabetic()).count() >= 3
            && b.chars().next().is_some_and(char::is_uppercase)
        {
            out.push(Piece { t: norm(a), raw: format!("{a}."), stop_after: false, lower: false, colon: false });
            out.push(Piece { t: norm(b), raw: b.to_string(), stop_after, lower: false, colon });
            continue;
        }
        // A title run into the initials after it: "MRLS", "MRSK", "MSNK".
        let letters: String = raw.chars().filter(|c| c.is_alphabetic()).collect();
        let mut split = false;
        for title in ["MISS", "PROF", "MRS", "MNR", "MEV", "MR", "MS", "DR"] {
            if t.len() > title.len() && t.len() <= title.len() + 3 && t.starts_with(title) && t.chars().all(char::is_alphabetic) {
                let rest: String = letters.chars().skip(title.len()).collect();
                if rest.chars().all(char::is_uppercase) && !TITLES.contains(&t.as_str()) {
                    out.push(Piece { t: title.to_string(), raw: title.to_string(), stop_after: false, lower: false, colon: false });
                    out.push(Piece { t: norm(&rest), raw: rest, stop_after, lower: false, colon });
                    split = true;
                }
                break;
            }
        }
        if !split {
            out.push(Piece { t, raw: raw.to_string(), stop_after, lower, colon });
        }
    }
    out
}

/// How well a title and given names run together ("MPFARISENIB", "MSS")
/// spell the ID's forenames, in order, each in full or as its initial: 1 when
/// they do, 0 when they cannot be read that way.
fn run_together_agreement(run: &str, given: &[String]) -> f32 {
    let mut rest = run;
    for t in ["MISS", "PROF", "MRS", "MNR", "MEV", "MR", "MS", "DR"] {
        if let Some(r) = rest.strip_prefix(t) {
            rest = r;
            break;
        }
    }
    let rest = fold_letters(rest);
    fn walk(rest: &str, given: &[String]) -> bool {
        if rest.is_empty() {
            return true;
        }
        let Some((g, more)) = given.split_first() else { return false };
        let g = fold_letters(g);
        (g.len() > 1 && rest.starts_with(&g) && walk(&rest[g.len()..], more)) || (rest.starts_with(&g[..1]) && walk(&rest[1..], more))
    }
    if !rest.is_empty() && walk(&rest, given) { 1.0 } else { 0.0 }
}

fn is_title(p: &[Piece], k: usize) -> bool {
    // "NS" is also a pair of initials: a title only before a full name and a surname.
    let need = if p[k].t == "NS" { 3 } else { 2 };
    TITLES.contains(&p[k].t.as_str()) || (k == 0 && p.len() >= need && OCR_TITLES.contains(&p[k].t.as_str()))
}

fn match_names(lines: &[Line], words: &[Word], c: &Customer) -> Vec<NameMatch> {
    let (given, surname) = split_name(c);
    if surname.is_empty() {
        return Vec::new();
    }
    let need = if surname.len() >= 5 { 0.8 } else { 0.99 };
    let mut out = Vec::new();
    for (li, l) in lines.iter().enumerate() {
        let p = pieces(l, words);
        let n = p.len();
        let mut best: Option<NameMatch> = None;
        for i in 0..n {
            for len in 1..=3.min(n - i) {
                let cand: String = p[i..i + len].iter().map(|x| x.t.as_str()).collect();
                // The surname, or (one piece) the surname with the initials OCR ran into it ("MHIZUHLE").
                let mut tries: Vec<(String, String)> = vec![(cand.clone(), String::new())];
                if len == 1 && surname.len() >= 3 {
                    for k in (1..=2).filter(|_| surname.len() >= 4) {
                        if cand.len() > k + 3 && cand.is_char_boundary(k) && p[i].raw.chars().nth(k).is_some_and(|ch| ch.is_uppercase()) {
                            tries.push((cand[k..].to_string(), cand[..k].to_string()));
                        }
                    }
                    // A whole name OCR ran into one word ("MPFARISENIBHLOPHE", "MsSHiophe"):
                    // the surname at its end, the title and given names before it.
                    if cand.len() >= surname.len() + 2 && cand.is_char_boundary(cand.len() - surname.len()) {
                        let k = cand.len() - surname.len();
                        tries.push((cand[k..].to_string(), format!("~{}", &cand[..k])));
                    }
                }
                for (body, glued) in tries {
                    if body.len() + 3 < surname.len() || body.len() > surname.len() + 3 {
                        continue;
                    }
                    let mut sim = word_sim(&body, &surname);
                    if sim < need {
                        // A short surname with one letter OCR confuses with
                        // another ("TAU" read "TAV"): a near match,
                        // enough only when the given names printed beside it agree.
                        if surname.len() >= 3 && confusable_slip(&body, &surname) {
                            sim = 0.95;
                        } else {
                            continue;
                        }
                    }
                    if !glued.is_empty() && sim < 0.99 {
                        continue;
                    }
                    if let Some(run) = glued.strip_prefix('~') {
                        // Given names run into the surname: they count only when they spell the ID's.
                        let g = run_together_agreement(run, &given);
                        let score = g * sim;
                        if g > 0.0 && best.as_ref().is_none_or(|b| score > b.score) {
                            best = Some(NameMatch { score, line: l.text.clone(), surname_score: sim, given_score: g, note: None, line_index: li, bbox: [0.0; 4] });
                        }
                        continue;
                    }
                    // Given names: the pieces just before the surname (stopping at a
                    // title or label), or, with none, the pieces after ("Nkosi, SJ").
                    // The given names from piece `end` back (stopping at a title,
                    // a label, a connector or the sentence around the name).
                    let collect = |end: usize| -> (Vec<String>, Option<usize>, bool) {
                        let mut v: Vec<String> = Vec::new();
                        for k in (0..end).rev() {
                            if is_title(&p, k) {
                                // "Mr & Mrs J Botha": a second title before it.
                                let couple = (0..k).any(|j| is_title(&p, j)) || l.text.contains('&') || l.upper.contains(" AND ");
                                v.reverse();
                                return (v, None, couple);
                            }
                            // A word in lower case is the sentence the name sits in
                            // ("We confirm that CRAIG F DESAI is ..."), not a given name.
                            let t = p[k].t.as_str();
                            if CONNECTORS.contains(&t) {
                                // Two given names printed ("Sipho & Thandi Nkosi"): one must be
                                // the customer's (checked below), not a joint account by default.
                                v.reverse();
                                return (v, Some(k), false);
                            }
                            if LABELS.contains(&t) || v.len() >= 3 || p[k].colon || p[k].lower {
                                break;
                            }
                            v.push(p[k].raw.clone());
                        }
                        v.reverse();
                        (v, None, false)
                    };
                    let (mut before, connector, couple) = collect(i);
                    // "Sipho & Thandi Nkosi": the given name before the "&" may be the customer's.
                    let other_side = connector.map(|k| collect(k).0).filter(|v| !v.is_empty());
                    if !glued.is_empty() {
                        before.push(glued.clone());
                    }
                    let refs: Vec<&str> = before.iter().map(String::as_str).collect();
                    let mut items = given_items(&refs);
                    let mut only_if_agree = false;
                    if items.is_empty() && i + len < n {
                        let after: Vec<&str> = p[i + len..].iter().take(2).take_while(|x| !x.lower).map(|x| x.raw.as_str()).collect();
                        // After a comma ("Nkosi, SJ"); or, the comma lost, a line
                        // that starts with the surname ("LIEBENBERG RIANA"), taken
                        // only when the names agree.
                        let first = (0..i).all(|k| LABELS.contains(&p[k].t.as_str()) || p[k].colon);
                        if p[i + len - 1].stop_after {
                            items = given_items(&after);
                        } else if first && n - (i + len) <= 3 {
                            items = given_items(&after);
                            only_if_agree = true;
                        }
                    }
                    let mut g = given_agreement(&items, &given);
                    if only_if_agree && g < 0.9 {
                        g = 0.6;
                    }
                    if let Some(o) = &other_side {
                        let refs: Vec<&str> = o.iter().map(String::as_str).collect();
                        g = g.max(given_agreement(&given_items(&refs), &given));
                    }
                    let mut note = None;
                    if g == 0.0 && couple {
                        g = 0.8;
                        note = Some("joint holders printed as \"Mr & Mrs\"".to_string());
                    } else if g == 0.6 {
                        note = Some("only the surname is printed here".to_string());
                    }
                    let score = g * sim;
                    if best.as_ref().is_none_or(|b| score > b.score) {
                        best = Some(NameMatch { score, line: l.text.clone(), surname_score: sim, given_score: g, note, line_index: li, bbox: [0.0; 4] });
                    }
                }
            }
        }
        if let Some(b) = best {
            out.push(b);
        }
    }
    out.sort_by(|a, b| b.score.total_cmp(&a.score));
    out
}

// --------------------------------------------------------------------------
// Addresses
// --------------------------------------------------------------------------

struct StreetParts {
    number: String,
    core: String,
    suffix: Option<&'static str>,
    core_tokens: usize,
}

fn street_parts(street: &str) -> Option<StreetParts> {
    let toks: Vec<String> = street.split_whitespace().map(norm).filter(|t| !t.is_empty()).collect();
    let k = toks.iter().position(|t| t.chars().next().is_some_and(|c| c.is_ascii_digit()))?;
    let mut number = toks[k].clone();
    let mut rest = &toks[k + 1..];
    // "12 A Acacia Road": a one-letter unit suffix.
    if number.chars().all(|c| c.is_ascii_digit()) && rest.len() > 1 && rest[0].len() == 1 && rest[0].chars().all(char::is_alphabetic) {
        number.push_str(&rest[0]);
        rest = &rest[1..];
    }
    let (core, sfx) = match rest.last().and_then(|t| suffix(t)) {
        Some(s) if rest.len() > 1 => (&rest[..rest.len() - 1], Some(s)),
        _ => (rest, None),
    };
    if core.is_empty() {
        return None;
    }
    Some(StreetParts { number, core: core.concat(), suffix: sfx, core_tokens: core.len() })
}

struct StreetHit {
    line: usize,
    /// Token index just after the street words.
    end: usize,
    number_ok: bool,
    score: f32,
}

fn find_streets(lines: &[Line], sp: &StreetParts) -> Vec<StreetHit> {
    let mut out = Vec::new();
    for (li, l) in lines.iter().enumerate() {
        let n = l.tokens.len();
        for j in 0..n {
            let t = &l.tokens[j];
            // The number: the token itself, or the token and a one-letter unit after it.
            let mut num = fold_digits(t);
            let mut after = j + 1;
            if num.chars().all(|c| c.is_ascii_digit()) && sp.number.chars().last().is_some_and(char::is_alphabetic) && j + 1 < n && l.tokens[j + 1].len() == 1 {
                num.push_str(&l.tokens[j + 1]);
                after = j + 2;
            }
            let digits_like = t.chars().filter(|c| c.is_ascii_digit()).count() * 2 >= t.len();
            if !digits_like {
                continue;
            }
            let number_ok = num == sp.number || (num.len() == sp.number.len() && fold_digits(&num) == fold_digits(&sp.number));
            // The street name: as many tokens as the customer's, one either side.
            let mut best = 0f32;
            let mut best_end = after;
            for len in sp.core_tokens.saturating_sub(1).max(1)..=sp.core_tokens + 1 {
                if after + len > n {
                    break;
                }
                let cand: String = l.tokens[after..after + len].concat();
                let mut sim = word_sim(&cand, &sp.core);
                let mut end = after + len;
                // The customer's suffix run into the name ("FETHADLROAD").
                if let Some(a) = sp.suffix
                    && let Some(f) = suffix_forms(a).into_iter().filter(|f| f.len() >= 4).find(|f| cand.len() >= f.len() + 3 && cand.ends_with(f))
                {
                    sim = sim.max(word_sim(&cand[..cand.len() - f.len()], &sp.core));
                }
                let next = l.tokens.get(end);
                let page_sfx = next.and_then(|t| suffix(t)).or_else(|| sp.suffix.filter(|a| next.is_some_and(|t| same_suffix(t, a))));
                match (sp.suffix, page_sfx) {
                    (Some(a), Some(b)) if a == b || next.is_some_and(|t| same_suffix(t, a)) => end += 1,
                    (Some(_), Some(_)) => {
                        sim *= 0.7;
                        end += 1;
                    }
                    (None, Some(_)) => end += 1,
                    (Some(_), None) => sim *= 0.97,
                    (None, None) => {}
                }
                if sim > best {
                    best = sim;
                    best_end = end;
                }
            }
            if best >= 0.6 {
                out.push(StreetHit { line: li, end: best_end, number_ok, score: best });
            }
        }
    }
    out
}

fn window_match(tokens: &[String], want: &str) -> bool {
    let w = norm(want);
    if w.is_empty() {
        return false;
    }
    let n = want.split_whitespace().count().max(1);
    for len in n.saturating_sub(1).max(1)..=n + 1 {
        for win in tokens.windows(len.min(tokens.len().max(1))) {
            let cand = win.concat();
            let need = if w.len() >= 5 { 0.8 } else { 0.99 };
            if word_sim(&cand, &w) >= need {
                return true;
            }
        }
    }
    false
}

fn address_matches(lines: &[Line], words: &[Word], names: &[NameMatch], c: &Customer) -> Vec<AddressMatch> {
    let Some(street) = c.address.street.as_deref() else { return Vec::new() };
    let Some(sp) = street_parts(street) else { return Vec::new() };
    let holder_lines: Vec<usize> = names.iter().filter(|n| n.score >= NAME_MIN).map(|n| n.line_index).collect();
    let mut out = Vec::new();
    for hit in find_streets(lines, &sp) {
        if !hit.number_ok && hit.score < STREET_MIN {
            continue;
        }
        let l = &lines[hit.line];
        // The rest of the line and the lines below it: the locality.
        let below_lines = chain(lines, hit.line, 4, below);
        let mut tokens: Vec<String> = l.tokens[hit.end.min(l.tokens.len())..].to_vec();
        for &b in &below_lines {
            tokens.extend(lines[b].tokens.iter().cloned());
        }
        let a = &c.address;
        let postal = a.postal_code.as_ref().map(|p| {
            let p = norm(p);
            tokens.iter().any(|t| fold_digits(t) == p)
        });
        let city = a.city.as_ref().map(|x| window_match(&tokens, x));
        let suburb = a.suburb.as_ref().map(|x| window_match(&tokens, x));
        let (mut got, mut of) = (0f32, 0f32);
        for (v, wgt) in [(postal, 1.0), (city, 1.0), (suburb, 0.5)] {
            if let Some(v) = v {
                of += wgt;
                if v {
                    got += wgt;
                }
            }
        }
        // A suburb printed where the customer put the city (or the other way round).
        let swapped = city == Some(false) && a.suburb.is_none() && a.city.as_ref().is_some_and(|x| window_match(&tokens, x));
        let locality = if of > 0.0 { got / of } else { 0.5 } + if swapped { 0.25 } else { 0.0 };
        let above_lines = chain(lines, hit.line, 4, above);
        // Linked to the holder: a holder-name line above it in its column,
        // on the same line before it, or the sentence just before it.
        let near_name = holder_lines.iter().any(|&h| h == hit.line || above_lines.contains(&h) || (h < hit.line && hit.line - h <= 3 && lines[h].y1 <= l.y0 + 1.0 && lines[h].x0 <= l.x1 && lines[h].x1 >= l.x0));
        let block: Vec<usize> = std::iter::once(hit.line).chain(above_lines.iter().copied().take(2)).chain(below_lines.iter().copied()).collect();
        let issuer = block.iter().any(|&b| has_issuer_cue(&lines[b]));
        let mut shown: Vec<String> = above_lines.iter().take(1).rev().map(|&i| lines[i].text.clone()).collect();
        shown.push(l.text.clone());
        shown.extend(below_lines.iter().take(3).map(|&i| lines[i].text.clone()));
        let score = if hit.number_ok { hit.score * (0.6 + 0.4 * locality.min(1.0)) } else { 0.0 };
        let _ = words;
        out.push(AddressMatch {
            score,
            bbox: [l.x0, l.y0, l.x1, l.y1],
            line_h: l.y1 - l.y0,
            street_score: if hit.number_ok { hit.score } else { 0.0 },
            locality_score: locality.min(1.0),
            postal_code: postal,
            city,
            suburb,
            holder_linked: near_name,
            issuer_block: issuer && !near_name,
            lines: shown,
        });
    }
    out.sort_by(|a, b| b.score.total_cmp(&a.score));
    out
}

fn address_ok(a: &AddressMatch) -> bool {
    a.street_score >= STREET_MIN && a.locality_score >= LOCALITY_MIN && a.holder_linked && !a.issuer_block
}

/// Checks one page against the customer. `date` is the document's date as
/// read by the extractor (or voted across frames).
pub fn check(words: &[Word], spans: &[Span], customer: &Customer, date: Option<Date>, today: Date) -> CustomerCheck {
    let lines = build_lines(words);
    let mut names = match_names(&lines, words, customer);
    let _ = spans; // the decision rests on the printed text alone (see the module docs)
    let mut addrs = address_matches(&lines, words, &names, customer);
    // Boxes as fractions of the words' extent, comparable between frames.
    let (x0, y0) = words.iter().fold((f32::MAX, f32::MAX), |(a, b), w| (a.min(w.x), b.min(w.y)));
    let (x1, y1) = words.iter().fold((f32::MIN, f32::MIN), |(a, b), w| (a.max(w.x + w.w), b.max(w.y + w.h)));
    let (sw, sh) = ((x1 - x0).max(1.0), (y1 - y0).max(1.0));
    let norm_box = |b: [f32; 4]| [(b[0] - x0) / sw, (b[1] - y0) / sh, (b[2] - x0) / sw, (b[3] - y0) / sh];
    for n in &mut names {
        let l = &lines[n.line_index];
        n.bbox = norm_box([l.x0, l.y0, l.x1, l.y1]);
    }
    for a in &mut addrs {
        a.bbox = norm_box(a.bbox);
        a.line_h /= sh;
    }
    let address = addrs.iter().find(|a| address_ok(a)).cloned();
    let address_elsewhere = if address.is_none() { addrs.first().cloned() } else { None };
    let unlinked: Vec<AddressMatch> = addrs.iter().filter(|a| !a.holder_linked && address_ok(&AddressMatch { holder_linked: true, issuer_block: false, ..(*a).clone() }) && !a.issuer_block).cloned().collect();
    let top: Vec<NameMatch> = names.iter().filter(|n| n.score >= NAME_MIN).cloned().collect();
    let mut c = decide(names.into_iter().next(), address, address_elsewhere, date.map(|d| verify::age(d, today)));
    c.unlinked = unlinked;
    c.names = top;
    c
}

/// The decision from the evidence (also used to combine frames).
pub fn decide(name: Option<NameMatch>, address: Option<AddressMatch>, address_elsewhere: Option<AddressMatch>, date: Option<Age>) -> CustomerCheck {
    let mut reasons = Vec::new();
    match &name {
        None => reasons.push("the customer's surname is not printed on the page".to_string()),
        Some(n) if n.score < NAME_MIN => {
            if n.given_score == 0.0 {
                reasons.push(format!("the name printed differs from the customer's ({})", n.line))
            } else {
                reasons.push(format!("the customer's name is not clearly printed (best: {})", n.line))
            }
        }
        _ => {}
    }
    if address.is_none() {
        match &address_elsewhere {
            Some(a) if a.street_score == 0.0 => reasons.push(format!("the house number differs ({})", a.lines.join(" / "))),
            Some(a) if a.issuer_block => reasons.push(format!("the address is the issuer's own, not the holder's ({})", a.lines.join(" / "))),
            Some(a) if !a.holder_linked => reasons.push(format!("the address is printed, but not as the holder's ({})", a.lines.join(" / "))),
            Some(a) if a.locality_score < LOCALITY_MIN => reasons.push(format!("the street matches but not the suburb, city or code ({})", a.lines.join(" / "))),
            _ => reasons.push("the customer's address is not printed on the page".to_string()),
        }
    }
    match &date {
        None => reasons.push("no document date read".into()),
        Some(a) if a.future => reasons.push(format!("dated in the future ({})", a.date)),
        Some(a) if !a.recent => reasons.push(format!("older than three months ({}, {} days)", a.date, a.age_days)),
        _ => {}
    }
    let accepted = reasons.is_empty() && address.is_some();
    CustomerCheck { accepted, reasons, name, address, address_elsewhere, date, unlinked: Vec::new(), names: Vec::new() }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn page(rows: &[(&str, f32, f32)]) -> Vec<Word> {
        let mut out = Vec::new();
        for (li, (text, x, y)) in rows.iter().enumerate() {
            let mut cx = *x;
            for w in text.split_whitespace() {
                out.push(Word { text: w.into(), x: cx, y: *y, w: 12.0 * w.len() as f32, h: 20.0, line: li });
                cx += 12.0 * w.len() as f32 + 10.0;
            }
        }
        out
    }

    fn customer(name: &str, street: &str, city: &str, code: &str) -> Customer {
        Customer {
            name: name.into(),
            surname: None,
            address: CustomerAddress { street: Some(street.into()), city: Some(city.into()), postal_code: Some(code.into()), ..Default::default() },
        }
    }

    const TODAY: Date = Date { year: 2026, month: 10, day: 15 };
    const RECENT: Date = Date { year: 2026, month: 9, day: 20 };

    fn bill() -> Vec<Word> {
        page(&[
            ("Head office: 45 Market Street, Marshalltown", 600.0, 40.0),
            ("Johannesburg 2001  Tel 011 555 1234", 600.0, 62.0),
            ("MR S J NKOSI", 60.0, 200.0),
            ("12 Acacia Road", 60.0, 224.0),
            ("Rondebosch", 60.0, 248.0),
            ("Cape Town 7700", 60.0, 272.0),
        ])
    }

    #[test]
    fn genuine_with_abbreviations_and_initials() {
        let c = customer("SIPHO JABULANI NKOSI", "12 Acacia Rd", "Cape Town", "7700");
        let r = check(&bill(), &[], &c, Some(RECENT), TODAY);
        assert!(r.accepted, "{:?}", r.reasons);
        assert_eq!(r.name.unwrap().given_score, 1.0);
    }

    #[test]
    fn wrong_person_wrong_number_old_and_issuer_address() {
        let r = check(&bill(), &[], &customer("THABO NKOSI", "12 Acacia Road", "Cape Town", "7700"), Some(RECENT), TODAY);
        assert!(!r.accepted);
        let r = check(&bill(), &[], &customer("SIPHO NKOSI", "21 Acacia Road", "Cape Town", "7700"), Some(RECENT), TODAY);
        assert!(!r.accepted && r.reasons[0].contains("house number"), "{:?}", r.reasons);
        let r = check(&bill(), &[], &customer("SIPHO NKOSI", "12 Acacia Road", "Cape Town", "7700"), Date::new(2026, 5, 1), TODAY);
        assert!(!r.accepted);
        let r = check(&bill(), &[], &customer("SIPHO NKOSI", "45 Market St", "Johannesburg", "2001"), Some(RECENT), TODAY);
        assert!(!r.accepted && r.reasons[0].contains("issuer"), "{:?}", r.reasons);
    }

    #[test]
    fn a_name_inside_a_sentence() {
        let words = page(&[
            ("We hereby confirm that CRAIG F DESAI is the holder of an account and", 60.0, 200.0),
            ("that the residential address on record is:", 60.0, 224.0),
            ("778 Ixia Close", 120.0, 248.0),
            ("Ladysmith 3370", 120.0, 272.0),
        ]);
        let c = customer("CRAIG FARAI DESAI", "778 Ixia Cl", "Ladysmith", "3370");
        let r = check(&words, &[], &c, Some(RECENT), TODAY);
        assert!(r.accepted, "{:?}", r.reasons);
        // A comma OCR read as a full stop.
        let words = page(&[("GXOWA. ST is the holder", 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
        assert!(check(&words, &[], &customer("SIPHO THABO GXOWA", "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
    }

    #[test]
    fn names_in_other_forms() {
        let (g, s) = split_name(&Customer { name: "Pieter Jan van der Merwe".into(), ..Default::default() });
        assert_eq!((g, s.as_str()), (vec!["PIETER".to_string(), "JAN".to_string()], "VANDERMERWE"));
        let words = page(&[("van der Merwe, PJ", 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
        let c = customer("PIETER JAN VAN DER MERWE", "3 Oak Ave", "Paarl", "7646");
        assert!(check(&words, &[], &c, Some(RECENT), TODAY).accepted);
        // An OCR slip in a long surname is allowed; a different initial is not.
        let words = page(&[("Mrs T Dlamlni", 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
        assert!(check(&words, &[], &customer("THANDI DLAMINI", "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
        assert!(!check(&words, &[], &customer("ZANELE DLAMINI", "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
        // A look-alike slip in a short surname, with the given name agreeing, is the customer; without it, not.
        let words = page(&[("Mrs T Tav", 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
        assert!(check(&words, &[], &customer("THANDI TAU", "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
        let words = page(&[("Mrs Tav", 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
        assert!(!check(&words, &[], &customer("THANDI TAU", "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
        assert!(!confusable_slip("NEL", "NAL") && confusable_slip("TAV", "TAU"));
    }

    #[test]
    fn names_ocr_ran_together() {
        let ok = |line: &str, name: &str| {
            let words = page(&[(line, 60.0, 200.0), ("3 Oak Avenue", 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
            check(&words, &[], &customer(name, "3 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted
        };
        assert!(ok("Mr MHizuhle", "MAVA V HIZUHLE"));
        assert!(ok("MRLS NDLAMTHIVENDLE", "LWAZI S NDLAMTHIVENDLE"));
        assert!(ok("Miss D.Sacoor", "DIKELEDI SACOOR"));
        assert!(ok("Kr MOLEFI LEBONA", "MOLEFI LEBONA"));
        assert!(ok("LIEBENBERG RIANA", "RIANA W LIEBENBERG"));
        // Another person's initial run in is still another person.
        assert!(!ok("Mr THizuhle", "MAVA V HIZUHLE"));
        assert!(!ok("MRLS NDLAMTHIVENDLE", "THABO NDLAMTHIVENDLE"));
        assert!(ok("Wetlumuntshe.FM", "FIKILE M WETLUMUNTSHE"));
        assert!(ok("Nkosi, L2", "LINDA Z NKOSI"));
        assert!(ok("Mi Ashwin von Aswegen", "ASHWIN C VAN ASWEGEN"));
        assert!(ok("NTSANOHAVU & KIRSTEN HUMAN", "NTSANOHAVU E HUMAN"));
        assert!(ok("MISS ISTEWART", "JONQAVA S STEWART"));
        assert!(!ok("THABO & KIRSTEN HUMAN", "NTSANOHAVU E HUMAN"));
        assert!(ok("MPFARISENIBHLOPHE", "MPFARISENI B HLOPHE"));
        assert!(ok("MsSHiophe", "SIPHO E HLOPHE"));
        assert!(!ok("MsTHiophe", "SIPHO E HLOPHE"));
        assert!(ok("MRSNSUYS", "NOMSA S UYS"));
        assert!(ok("XR FV JAFTER", "FARIED V JAFFER"));
        assert!(!ok("MRSTSUYS", "NOMSA S UYS"));
    }

    #[test]
    fn streets_ocr_ran_together() {
        let ok = |street_line: &str, street: &str| {
            let words = page(&[("Mrs T Dlamini", 60.0, 200.0), (street_line, 60.0, 224.0), ("Paarl 7646", 60.0, 248.0)]);
            check(&words, &[], &customer("THANDI DLAMINI", street, "Paarl", "7646"), Some(RECENT), TODAY).accepted
        };
        assert!(ok("17klipLane", "17 Klip Lane"));
        assert!(ok("54 FETHADLROAD", "54 Fethadli Road"));
        assert!(ok("71 Buffalo Ct", "71 Buffalo Cl"));
        assert!(ok("$33 Seme Grove", "533 Seme Grove"));
        let words = page(&[("Mrs T Dlamini", 60.0, 200.0), ("12 Oak Avenue", 60.0, 224.0), ("Paarl7646", 60.0, 248.0)]);
        assert!(check(&words, &[], &customer("THANDI DLAMINI", "12 Oak Avenue", "Paarl", "7646"), Some(RECENT), TODAY).accepted);
        assert!(!ok("71 Buffalo Ct", "17 Buffalo Cl"));
        assert!(!ok("18klipLane", "17 Klip Lane"));
    }
}
