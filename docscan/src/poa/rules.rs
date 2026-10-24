//! The rules fallback: proof-of-address fields from OCR words by layout
//! heuristics alone, for when the tagger is not loaded.
//!
//! - The holder: a labelled name (`Account holder:`, `Customer`, `Tenant`,
//!   ...), a line starting with a title (`Mr`, `Ms`, ...), or a salutation.
//! - The address: blocks of lines ending in a 4-digit postal code, scored
//!   for a street line and the holder's name above them, and against the
//!   issuer's own address (`Head office`, `PO Box`, `Tel`, `VAT`, a footer).
//! - The date: the value of a date label (`Statement date`, `Invoice
//!   date`, ...) and not a due or payment date; else the latest date printed.
//! - The issuer: the largest print near the top of the page.

use super::features::Word;
use super::verify::{self, Date};
use super::{Address, Fields, Period, clean, document_type, infer_province};

#[derive(Debug, Clone)]
struct TextLine {
    text: String,
    words: Vec<usize>,
    x: f32,
    y: f32,
    right: f32,
    bottom: f32,
    /// Median word height.
    h: f32,
}

fn lines(words: &[Word]) -> Vec<TextLine> {
    let mut out: Vec<TextLine> = Vec::new();
    for (i, w) in words.iter().enumerate() {
        if out.len() <= w.line {
            out.resize(w.line + 1, TextLine { text: String::new(), words: vec![], x: f32::MAX, y: f32::MAX, right: 0.0, bottom: 0.0, h: 0.0 });
        }
        let l = &mut out[w.line];
        if !l.text.is_empty() {
            l.text.push(' ');
        }
        l.text.push_str(&w.text);
        l.words.push(i);
        l.x = l.x.min(w.x);
        l.y = l.y.min(w.y);
        l.right = l.right.max(w.x + w.w);
        l.bottom = l.bottom.max(w.y + w.h);
    }
    for l in &mut out {
        let mut hs: Vec<f32> = l.words.iter().map(|&i| words[i].h).collect();
        hs.sort_by(f32::total_cmp);
        l.h = hs.get(hs.len() / 2).copied().unwrap_or(0.0);
    }
    out.retain(|l| !l.words.is_empty());
    out
}

fn lower(s: &str) -> String {
    // Labels are ASCII. Keep their byte offsets valid in the original OCR
    // text: Unicode case conversion can change length (for example İ).
    s.to_ascii_lowercase()
}

const NAME_LABELS: &[&str] = &[
    "account holder", "account name", "customer name", "client name", "policyholder", "policy holder", "tenant", "lessee",
    "customer", "client", "name", "member", "insured",
];
const TITLES: &[&str] = &["mr", "mrs", "ms", "miss", "dr", "prof", "mr.", "mrs.", "ms.", "dr."];
const DECOY_WORDS: &[&str] = &[
    "head office", "registered office", "office:", "po box", "p.o. box", "p o box", "private bag", "tel", "fax", "vat",
    "reg no", "reg. no", "registration", "www", "@", "branch", "payment address", "return address", "pay at", "call centre",
];
const DATE_LABELS: &[&str] = &[
    "statement date", "invoice date", "date of issue", "issue date", "issued", "bill date", "billing date", "tax invoice date",
    "document date", "account date", "date printed", "signed on", "dated", "date",
];
const NOT_DOC_DATE: &[&str] = &["due", "payment", "paid", "previous", "last", "received", "birth", "next", "reading", "commence", "expir", "start"];
const ACCOUNT_LABELS: &[&str] = &[
    "account number", "account no", "account #", "acc no", "acc. no", "acct no", "customer number", "customer no",
    "customer ref", "account ref", "policy number", "policy no", "contract number", "account",
];

/// Words that make a line a label or a heading rather than a name.
const NOT_NAME: &[&str] = &[
    "address", "invoice", "account", "details", "holder", "statement", "tax", "number", "date", "customer", "page",
    "postal", "physical", "summary", "total", "due", "period", "reference", "policy", "tenant", "client", "name",
];

fn is_name_like(s: &str) -> bool {
    let ws: Vec<&str> = s.split_whitespace().collect();
    !ws.iter().any(|w| {
        let w = lower(w.trim_matches(|c: char| !c.is_alphanumeric()));
        NOT_NAME.iter().any(|n| w == *n || (w.len() >= 5 && verify::similarity(&w, n) >= 0.75))
    }) && (1..=6).contains(&ws.len())
        && ws.iter().all(|w| w.chars().all(|c| c.is_alphabetic() || matches!(c, '.' | '-' | '\'' | '&' | ',')))
        && ws.iter().any(|w| w.chars().filter(|c| c.is_alphabetic()).count() >= 2)
}

/// The value after a label on the same line (`Label: value`), or the line
/// below in the same column.
fn labelled_value(ls: &[TextLine], i: usize, label: &str) -> Option<(String, usize)> {
    let t = &ls[i].text;
    let at = lower(t).find(label)?;
    let rest = t[at + label.len()..].trim_start_matches(|c: char| c == ':' || c == '.' || c == '#' || c.is_whitespace());
    if !rest.trim().is_empty() {
        return Some((rest.trim().to_string(), i));
    }
    // A label column beside a value column: the nearest line to the right on the same row.
    let l = &ls[i];
    let right = ls
        .iter()
        .enumerate()
        .filter(|(_, o)| o.x > l.right && o.x - l.right < 25.0 * l.h.max(1.0))
        .filter(|(_, o)| {
            let overlap = o.bottom.min(l.bottom) - o.y.max(l.y);
            overlap > 0.5 * l.h.min(o.h).max(1.0)
        })
        .min_by(|a, b| a.1.x.total_cmp(&b.1.x));
    if let Some((j, o)) = right {
        return Some((o.text.clone(), j));
    }
    let below = ls.iter().enumerate().skip(i + 1).find(|(_, l)| l.x < ls[i].right + 40.0 && l.right > ls[i].x - 40.0)?;
    (below.1.y - ls[i].bottom < 2.5 * ls[i].h.max(1.0)).then(|| (below.1.text.clone(), below.0))
}

fn holder(ls: &[TextLine]) -> Option<(String, usize, f32)> {
    for label in NAME_LABELS {
        for (i, l) in ls.iter().enumerate() {
            let t = lower(&l.text);
            let starts = t.starts_with(label) || t.contains(&format!(" {label}:")) || t.contains(&format!("{label}:"));
            if !starts {
                continue;
            }
            if let Some((v, at)) = labelled_value(ls, i, label) {
                let v = clean(&v);
                if is_name_like(&v) && v.len() >= 3 {
                    return Some((v, at, 1.0));
                }
            }
        }
    }
    for (i, l) in ls.iter().enumerate() {
        let first = l.text.split_whitespace().next().map(lower).unwrap_or_default();
        if TITLES.contains(&first.as_str()) && is_name_like(&l.text) {
            return Some((clean(&l.text), i, 0.8));
        }
    }
    for (i, l) in ls.iter().enumerate() {
        if let Some(rest) = l.text.strip_prefix("Dear ").or_else(|| l.text.strip_prefix("DEAR ")) {
            let v = clean(rest);
            if is_name_like(&v) {
                return Some((v, i, 0.6));
            }
        }
    }
    None
}

fn postal_in(text: &str) -> Option<String> {
    let last = text.split([' ', ',']).filter(|w| !w.is_empty()).last()?;
    let d: String = last.chars().filter(|c| c.is_ascii_digit()).collect();
    (d.len() == 4 && last.chars().filter(|c| c.is_alphanumeric()).count() == 4 && !verify::provinces_for_postal_code(&d).is_empty()).then_some(d)
}

fn street_like(text: &str) -> bool {
    let mut ws = text.split_whitespace();
    let first = ws.next().unwrap_or("");
    let starts_with_number = first.chars().next().is_some_and(|c| c.is_ascii_digit()) && first.chars().filter(|c| c.is_ascii_digit()).count() <= 5;
    let suffix = text.split_whitespace().any(|w| {
        matches!(lower(w).trim_matches(|c: char| !c.is_alphanumeric()), "street" | "st" | "road" | "rd" | "avenue" | "ave" | "drive" | "dr" | "lane" | "crescent" | "way" | "close" | "place" | "boulevard" | "blvd" | "rylaan" | "straat" | "weg")
    });
    (starts_with_number && text.split_whitespace().count() >= 2) || (suffix && starts_with_number)
}

fn strip_label(text: &str) -> String {
    let l = lower(text);
    for lab in ["postal address", "physical address", "supply address", "service address", "residential address", "property address", "address", "premises"] {
        if let Some(at) = l.find(lab) {
            return text[at + lab.len()..].trim_start_matches([':', ' ']).to_string();
        }
    }
    text.to_string()
}

struct Block {
    address: Address,
    /// A name printed on the line before the street, inside the block.
    name: Option<String>,
    score: f32,
}

fn address_block(ls: &[TextLine], holder_line: Option<usize>, page_h: f32) -> Option<Block> {
    let mut best: Option<Block> = None;
    for (i, l) in ls.iter().enumerate() {
        let text = clean(&l.text);
        let Some(code) = postal_in(&text) else { continue };
        let mut block = vec![i];
        let mut j = i;
        while j > 0 && block.len() < 6 {
            let up = (0..j).rev().find(|&k| ls[k].x < l.right && ls[k].right > l.x && ls[k].bottom <= ls[j].y + 2.0);
            let Some(k) = up else { break };
            if ls[j].y - ls[k].bottom > 1.6 * ls[j].h.max(ls[k].h).max(1.0) {
                break;
            }
            block.insert(0, k);
            j = k;
        }
        let ctx: String = block.iter().map(|&k| lower(&ls[k].text)).collect::<Vec<_>>().join(" ");
        let near: String = (i.saturating_sub(block.len() + 2)..(i + 2).min(ls.len())).map(|k| lower(&ls[k].text)).collect::<Vec<_>>().join(" ");
        let mut score = 0.0;
        if DECOY_WORDS.iter().any(|d| ctx.contains(d)) {
            score -= 4.0;
        } else if DECOY_WORDS.iter().any(|d| near.contains(d)) {
            score -= 1.5;
        }
        if l.y > 0.82 * page_h {
            score -= 1.5;
        }
        if l.y < 0.5 * page_h {
            score += 0.5;
        }
        // A single comma-separated line: "12 Acacia Ave, Rondebosch, Cape Town, 7700".
        let parts: Vec<String> = text.split(',').map(|p| clean(p)).filter(|p| !p.is_empty()).collect();
        let mut addr = Address { postal_code: Some(code.clone()), ..Default::default() };
        let mut body: Vec<String> = Vec::new();
        if parts.len() >= 3 {
            body.extend(parts.iter().map(|p| strip_label(p)));
        } else {
            for &k in &block {
                if Some(k) == holder_line {
                    score += 3.0;
                    continue;
                }
                let t = clean(&strip_label(&ls[k].text));
                if t.is_empty() || (is_name_like(&t) && TITLES.contains(&lower(t.split_whitespace().next().unwrap_or("")).as_str())) {
                    continue;
                }
                body.push(t);
            }
        }
        if let Some(h) = holder_line
            && block.first().is_some_and(|&f| f > 0 && h + 1 >= f && h < f + 1)
        {
            score += 2.0;
        }
        // The last part holds the code, maybe with the city or province before it.
        if let Some(last) = body.pop() {
            let rest = clean(last.trim_end_matches(char::is_numeric).trim());
            let rest = clean(rest.trim_end_matches(&code[..]));
            if !rest.is_empty() {
                if let Some(p) = verify::province(&rest) {
                    addr.province = Some(p.into());
                } else {
                    // "Cape Town, Western Cape 8001": peel a trailing province off.
                    let (city, prov) = split_province(&rest);
                    if let Some(p) = prov {
                        addr.province = Some(p.into());
                    }
                    if !city.is_empty() {
                        addr.city = Some(city);
                    }
                }
            }
        }
        // "Ballito, KwaZulu-Natal" on its own line: the city, then the province.
        for t in body.iter_mut() {
            if fuzzy_province(t).is_none()
                && let (city, Some(p)) = split_province(t)
            {
                addr.province = Some(p.into());
                *t = city;
            }
        }
        let mut name = None;
        body.retain(|t| {
            if let Some(p) = fuzzy_province(t) {
                addr.province = Some(p.into());
                false
            } else {
                true
            }
        });
        if let Some(si) = body.iter().position(|t| street_like(t)) {
            if si > 0 && is_name_like(&body[si - 1]) {
                name = Some(body[si - 1].clone());
            }
            addr.street = Some(body[si].clone());
            score += 2.0;
            let after: Vec<String> = body[si + 1..].to_vec();
            match (after.len(), addr.city.is_some()) {
                (0, _) => {}
                (1, true) => addr.suburb = Some(after[0].clone()),
                (1, false) => addr.city = Some(after[0].clone()),
                (_, true) => addr.suburb = Some(after[0].clone()),
                (_, false) => {
                    addr.suburb = Some(after[0].clone());
                    addr.city = Some(after[after.len() - 1].clone());
                }
            }
        } else if let Some(last) = body.last() {
            if addr.city.is_none() {
                addr.city = Some(last.clone());
            } else {
                addr.suburb = Some(last.clone());
            }
        }
        if best.as_ref().is_none_or(|b| score > b.score) {
            best = Some(Block { address: addr, name, score });
        }
    }
    best
}

/// A province as OCR may print it (`WESTERI CAPE`, `Eastem Cape`): the
/// closest canonical name within a couple of letters.
fn fuzzy_province(text: &str) -> Option<&'static str> {
    if let Some(p) = verify::province(text) {
        return Some(p);
    }
    let t = verify::normalise(text).replace(' ', "");
    if t.len() < 5 {
        return None;
    }
    verify::PROVINCES
        .iter()
        .map(|p| (*p, verify::similarity(&t, &verify::normalise(p).replace(' ', ""))))
        .filter(|(_, s)| *s >= 0.8)
        .max_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(p, _)| p)
}

/// "East London, Eastern Cape" → ("East London", Eastern Cape): the last one
/// or two words, when they read as a province.
fn split_province(text: &str) -> (String, Option<&'static str>) {
    let words: Vec<&str> = text.split_whitespace().collect();
    for take in [2usize, 1] {
        if words.len() > take
            && let Some(p) = fuzzy_province(&words[words.len() - take..].join(" "))
        {
            return (clean(&words[..words.len() - take].join(" ")), Some(p));
        }
    }
    (clean(text), None)
}

fn line_dates(l: &TextLine) -> Vec<Date> {
    let ws: Vec<&str> = l.text.split_whitespace().collect();
    verify::find_dates(&ws).into_iter().map(|d| d.2).collect()
}

/// Where `label` starts in `t`, allowing an OCR slip or two ("Invoire date").
fn find_label(t: &str, label: &str) -> Option<usize> {
    if let Some(at) = t.find(label) {
        return Some(at);
    }
    if label.len() < 8 || !t.is_ascii() || t.len() < label.len() {
        return None;
    }
    (0..=t.len().saturating_sub(label.len())).find(|&i| verify::similarity(&t[i..i + label.len()], label) >= 0.85)
}

fn document_date(ls: &[TextLine], today: Date) -> Option<(Date, f32)> {
    for label in DATE_LABELS {
        for (i, l) in ls.iter().enumerate() {
            let t = lower(&l.text);
            let Some(at) = find_label(&t, label) else { continue };
            if *label == "date" && !(t[at..].starts_with("date:") || t[at..].starts_with("date ") || &t[at..] == "date") {
                continue;
            }
            // "Due date", "Payment date": the word before the label decides.
            let before = &t[..at];
            if NOT_DOC_DATE.iter().any(|n| before.ends_with(&format!("{n} ")) || before.ends_with(n) || (*label == "date" && before.contains(n))) {
                continue;
            }
            if t.contains("period") {
                continue;
            }
            let ws: Vec<&str> = l.text[at..].split_whitespace().collect();
            if let Some(d) = verify::find_dates(&ws).first() {
                return Some((d.2, 1.0));
            }
            // The value beside the label, or under it in the same column.
            if l.text[at..].split_whitespace().count() <= 3
                && let Some((_, j)) = labelled_value(ls, i, &t[at..at + label.len().min(t.len() - at)])
                && j != i
                && let Some(d) = line_dates(&ls[j]).first()
            {
                return Some((*d, 0.8));
            }
            // A row of column headings (ACCOUNT DATE | DUE DATE) has no
            // value to the right of the label. Read the first line below
            // within this column; never skip a non-date to a later row or
            // borrow the neighbouring column's payment date.
            if *label != "date" && l.text[at..].split_whitespace().count() <= 3 {
                let below = ls.iter()
                    .filter(|other| other.y >= l.bottom && other.y - l.bottom < 2.5 * l.h.max(1.0))
                    .filter(|other| other.x < l.right && other.right > l.x)
                    .min_by(|a, b| a.y.total_cmp(&b.y).then((a.x - l.x).abs().total_cmp(&(b.x - l.x).abs())));
                if let Some(other) = below
                    && let Some(d) = line_dates(other).first()
                {
                    return Some((*d, 0.8));
                }
            }
        }
    }
    // The latest plausible date on the page, outside due/payment lines.
    ls.iter()
        .filter(|l| !NOT_DOC_DATE.iter().any(|n| lower(&l.text).contains(n)))
        .flat_map(line_dates)
        .filter(|d| d.days() <= today.days() + 7)
        .max()
        .map(|d| (d, 0.4))
}

fn period(ls: &[TextLine]) -> Option<Period> {
    for (i, l) in ls.iter().enumerate() {
        let t = lower(&l.text);
        if !(t.contains("period") || t.contains("from") && t.contains(" to ")) {
            continue;
        }
        let mut ds = line_dates(l);
        if ds.len() < 2
            && let Some(next) = ls.get(i + 1)
        {
            ds.extend(line_dates(next));
        }
        if ds.len() >= 2 {
            return Some(Period { from: Some(ds[0].iso()), to: Some(ds[1].iso()) });
        }
    }
    None
}

fn account_number(ls: &[TextLine]) -> Option<String> {
    for label in ACCOUNT_LABELS {
        for (i, l) in ls.iter().enumerate() {
            let t = lower(&l.text);
            if !t.contains(label) || (*label == "account" && !t.contains("account:") && !t.contains("account no")) {
                continue;
            }
            let Some((v, _)) = labelled_value(ls, i, label) else { continue };
            // The run of words that carry digits, from the start of the value.
            let run: Vec<&str> = v
                .split_whitespace()
                .take_while(|w| w.chars().any(|c| c.is_ascii_digit()) || (w.len() <= 4 && w.chars().all(|c| c.is_ascii_uppercase() || c == '-')))
                .collect();
            let s = clean(&run.join(" "));
            if s.chars().filter(|c| c.is_ascii_digit()).count() >= 4 {
                return Some(s);
            }
        }
    }
    None
}

const TITLE_WORDS: &[&str] = &["tax invoice", "invoice", "statement", "account", "bill", "lease", "agreement", "page", "original", "copy", "summary", "notice"];

fn issuer(ls: &[TextLine], page_h: f32) -> Option<String> {
    ls.iter()
        .filter(|l| l.y < 0.25 * page_h)
        .filter(|l| {
            let t = lower(&l.text);
            l.text.chars().filter(|c| c.is_alphabetic()).count() >= 4
                && !l.text.chars().any(|c| c.is_ascii_digit())
                && !TITLE_WORDS.iter().any(|w| t == *w || t.starts_with(&format!("{w} ")) || t.ends_with(&format!(" {w}")) && t.split_whitespace().count() <= 2)
        })
        // The largest print; between equals, the top-most.
        .max_by(|a, b| (a.h - 0.001 * a.y).total_cmp(&(b.h - 0.001 * b.y)))
        .map(|l| super::clean_issuer(&l.text))
}

/// Fields by rules alone, and a confidence per field.
pub fn extract(words: &[Word], page_h: f32, text: &str, today: Date) -> (Fields, Vec<(&'static str, f32)>) {
    let ls = lines(words);
    let mut conf = Vec::new();
    let mut f = Fields::default();
    let holder = holder(&ls);
    let labelled = holder.as_ref().filter(|h| h.2 >= 1.0);
    if let Some((name, _, c)) = labelled {
        f.holder_name = Some(name.clone());
        conf.push(("holder_name", *c));
    }
    if let Some(b) = address_block(&ls, holder.as_ref().map(|h| h.1), page_h) {
        let c = if b.score > 1.0 { 1.0 } else { 0.5 };
        for (k, v) in [("street", &b.address.street), ("suburb", &b.address.suburb), ("city", &b.address.city), ("province", &b.address.province), ("postal_code", &b.address.postal_code)] {
            if v.is_some() {
                conf.push((k, c));
            }
        }
        // No labelled name: the name at the head of the address block.
        if f.holder_name.is_none()
            && let Some(n) = &b.name
        {
            f.holder_name = Some(n.clone());
            conf.push(("holder_name", 0.8));
        }
        f.address = b.address;
    }
    if f.holder_name.is_none()
        && let Some((name, _, c)) = &holder
    {
        f.holder_name = Some(name.clone());
        conf.push(("holder_name", *c));
    }
    if let Some((d, c)) = document_date(&ls, today) {
        f.document_date = Some(d.iso());
        conf.push(("document_date", c));
    }
    f.statement_period = period(&ls);
    if f.statement_period.is_some() {
        conf.push(("period_from", 1.0));
        conf.push(("period_to", 1.0));
    }
    if let Some(a) = account_number(&ls) {
        f.account_number = Some(a);
        conf.push(("account_number", 1.0));
    }
    if let Some(i) = issuer(&ls, page_h) {
        f.issuer = Some(i);
        conf.push(("issuer", 0.5));
    }
    f.document_type = document_type(text);
    infer_province(&mut f);
    (f, conf)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::poa::features::reading_order;
    use crate::za::Line;

    fn page(rows: &[(&str, f32, f32)]) -> Vec<Word> {
        let mut ws = Vec::new();
        for (row, &(text, x, y)) in rows.iter().enumerate() {
            let mut cx = x;
            // The first row is the issuer's name, in larger print.
            let h = if row == 0 { 34.0 } else { 20.0 };
            for w in text.split_whitespace() {
                let width = 0.55 * h * w.chars().count() as f32;
                ws.push(Line { text: w.into(), x: cx, y, w: width, h });
                cx += width + 0.4 * h;
            }
        }
        reading_order(&ws)
    }

    #[test]
    fn old_issue_date_is_not_replaced_by_a_recent_period_or_payment() {
        let words = page(&[
            ("Statement date: 2 April 2024", 60.0, 40.0),
            ("Period: May 2 – May 26, 2026", 60.0, 100.0),
            ("Payment date: 30 May 2026", 60.0, 160.0),
        ]);
        let today = Date::new(2026, 6, 1).unwrap();
        let (fields, conf) = extract(&words, 1000.0, &super::super::page_text(&words), today);
        assert_eq!(fields.document_date.as_deref(), Some("2024-04-02"));
        assert_eq!(fields.statement_period, Some(Period { from: Some("2026-05-02".into()), to: Some("2026-05-26".into()) }));
        let checked = super::super::verify_fields(&fields, &super::super::page_text(&words), &conf, today);
        assert!(!checked.age.unwrap().recent);
        assert!(!checked.accepted);
    }

    #[test]
    fn document_date_below_a_column_heading_is_not_the_due_date() {
        let today = Date::new(2026, 10, 15).unwrap();
        for issued in ["2026/07/24", "2025/07/24"] {
            let words = page(&[
                ("Municipal account", 60.0, 40.0),
                ("ACCOUNT NUMBER", 60.0, 180.0),
                ("ACCOUNT DATE", 350.0, 180.0),
                ("DUE DATE", 640.0, 180.0),
                ("12345678", 60.0, 215.0),
                (issued, 350.0, 215.0),
                ("2026/08/18", 640.0, 215.0),
            ]);
            assert_eq!(document_date(&lines(&words), today).map(|v| v.0), verify::parse_date(issued));
        }
    }

    #[test]
    fn transaction_date_column_is_not_the_document_date() {
        let words = page(&[
            ("Bank statement", 60.0, 40.0),
            ("03/08/2026", 800.0, 100.0),
            ("DATE", 60.0, 400.0),
            ("TRANSACTION", 300.0, 400.0),
            ("AMOUNT", 800.0, 400.0),
            ("04/07/2026", 60.0, 435.0),
            ("Payment", 300.0, 435.0),
            ("R 100.00", 800.0, 435.0),
        ]);
        assert_eq!(document_date(&lines(&words), Date::new(2026, 10, 15).unwrap()).map(|v| v.0), Date::new(2026, 8, 3));
    }

    /// The issuer's head-office address must not be taken for the holder's.
    #[test]
    fn holder_address_not_the_issuers() {
        let words = page(&[
            ("Lesedi Utilities", 60.0, 40.0),
            ("Head office: 45 Market Street, Marshalltown, Johannesburg, 2001", 60.0, 90.0),
            ("Tax invoice", 900.0, 40.0),
            ("MS T DLAMINI", 60.0, 300.0),
            ("12 Acacia Avenue", 60.0, 326.0),
            ("Rondebosch", 60.0, 352.0),
            ("Cape Town", 60.0, 378.0),
            ("7700", 60.0, 404.0),
            ("Invoice date: 30 September 2026", 700.0, 300.0),
            ("Due date: 15/10/2026", 700.0, 326.0),
            ("Account number: 4012 3381 22", 700.0, 352.0),
            ("Electricity consumption 412 kWh R 1 234.56", 60.0, 600.0),
        ]);
        let text = crate::poa::page_text(&words);
        let today = Date::new(2026, 10, 15).unwrap();
        let (f, _) = extract(&words, 1754.0, &text, today);
        assert_eq!(f.holder_name.as_deref(), Some("MS T DLAMINI"));
        assert_eq!(f.address.street.as_deref(), Some("12 Acacia Avenue"));
        assert_eq!(f.address.suburb.as_deref(), Some("Rondebosch"));
        assert_eq!(f.address.city.as_deref(), Some("Cape Town"));
        assert_eq!(f.address.postal_code.as_deref(), Some("7700"));
        assert_eq!(f.address.province.as_deref(), Some("Western Cape"));
        assert!(f.province_inferred);
        assert_eq!(f.document_date.as_deref(), Some("2026-09-30"));
        assert_eq!(f.account_number.as_deref(), Some("4012 3381 22"));
        assert_eq!(f.issuer.as_deref(), Some("Lesedi Utilities"));
        assert_eq!(f.document_type, crate::poa::DocumentType::UtilityBill);

        let v = crate::poa::verify_fields(&f, &text, &[], today);
        assert!(v.accepted, "{:?}", v.reasons);
    }

    #[test]
    fn one_line_address() {
        let words = page(&[("Mr Sipho Nkosi", 60.0, 200.0), ("Address: 8 Protea Rd, Umhlanga, Durban, 4319", 60.0, 226.0)]);
        let text = crate::poa::page_text(&words);
        let (f, _) = extract(&words, 1754.0, &text, Date::new(2026, 10, 15).unwrap());
        assert_eq!(f.holder_name.as_deref(), Some("Mr Sipho Nkosi"));
        assert_eq!(f.address.street.as_deref(), Some("8 Protea Rd"));
        assert_eq!(f.address.suburb.as_deref(), Some("Umhlanga"));
        assert_eq!(f.address.city.as_deref(), Some("Durban"));
        assert_eq!(f.address.province.as_deref(), Some("KwaZulu-Natal"));
    }
}
