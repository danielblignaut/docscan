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
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct AddressMatch {
    /// 0–1: street similarity, weighed with the locality.
    pub score: f32,
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
            'S' => '5',
            'B' => '8',
            'Z' => '2',
            _ => c,
        })
        .collect()
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
        let t = norm(&w.text);
        if !t.is_empty() {
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

fn match_names(lines: &[Line], words: &[Word], c: &Customer) -> Vec<NameMatch> {
    let (given, surname) = split_name(c);
    if surname.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for (li, l) in lines.iter().enumerate() {
        let n = l.tokens.len();
        let mut best: Option<NameMatch> = None;
        for i in 0..n {
            for len in 1..=3.min(n - i) {
                let cand: String = l.tokens[i..i + len].concat();
                if cand.len() + 3 < surname.len() || cand.len() > surname.len() + 3 {
                    continue;
                }
                let sim = word_sim(&cand, &surname);
                let need = if surname.len() >= 5 { 0.8 } else { 0.99 };
                if sim < need {
                    continue;
                }
                // Given names: the words just before the surname (stopping at a
                // title or label), or, with none, the words after ("Nkosi, SJ").
                let wi: Vec<usize> = l.token_word[..i].to_vec();
                let mut before: Vec<&str> = Vec::new();
                let mut couple = false;
                for &w in wi.iter().rev() {
                    let t = norm(&words[w].text);
                    if TITLES.contains(&t.as_str()) {
                        // "Mr & Mrs J Botha": a second title before it.
                        let k = wi.iter().position(|&x| x == w).unwrap();
                        couple = wi[..k].iter().any(|&x| TITLES.contains(&norm(&words[x].text).as_str()))
                            || l.text.contains('&')
                            || l.upper.contains(" AND ");
                        break;
                    }
                    if LABELS.contains(&t.as_str()) || CONNECTORS.contains(&t.as_str()) || before.len() >= 3 || words[w].text.ends_with(':') {
                        break;
                    }
                    before.push(words[w].text.as_str());
                }
                before.reverse();
                let mut items = given_items(&before);
                if items.is_empty() && i + len < n {
                    let after: Vec<&str> = l.token_word[i + len..].iter().take(2).map(|&w| words[w].text.as_str()).collect();
                    // Only after a comma: "Nkosi, SJ".
                    let last_word = l.token_word[i + len - 1];
                    if words[last_word].text.ends_with(',') {
                        items = given_items(&after);
                    }
                }
                let mut g = given_agreement(&items, &given);
                let mut note = None;
                if g == 0.0 && couple {
                    g = 0.8;
                    note = Some("joint holders printed as \"Mr & Mrs\"".to_string());
                } else if g == 0.6 {
                    note = Some("only the surname is printed here".to_string());
                }
                let score = g * sim;
                if best.as_ref().is_none_or(|b| score > b.score) {
                    best = Some(NameMatch { score, line: l.text.clone(), surname_score: sim, given_score: g, note, line_index: li });
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
                let page_sfx = l.tokens.get(end).and_then(|t| suffix(t));
                match (sp.suffix, page_sfx) {
                    (Some(a), Some(b)) if a == b => end += 1,
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
    let names = match_names(&lines, words, customer);
    let _ = spans; // the decision rests on the printed text alone (see the module docs)
    let addrs = address_matches(&lines, words, &names, customer);
    let address = addrs.iter().find(|a| address_ok(a)).cloned();
    let address_elsewhere = if address.is_none() { addrs.first().cloned() } else { None };
    decide(names.into_iter().next(), address, address_elsewhere, date.map(|d| verify::age(d, today)))
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
    CustomerCheck { accepted, reasons, name, address, address_elsewhere, date }
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
    }
}
