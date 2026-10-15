//! A capture: several frames of the same page, read one by one and combined.
//!
//! Live capture sees a burst of frames of the held page. Reading two or
//! three of them and voting per field outvotes most one-character OCR slips
//! (each frame is sampled a little differently); for verification the best
//! evidence of any frame counts for the name and address, and the date is
//! voted. [`next_frame_needed`] says whether the frames read so far agree
//! well enough to stop.

use std::collections::HashMap;

use serde::Serialize;

use super::customer::{self, Customer, CustomerCheck};
use super::verify::{self, Date};
use super::{AddressResult, Fields, Period};

/// The weight of the rules' labelled date against one frame's tagged date.
pub const RULES_DATE_VOTE: f32 = 0.3;

/// The most frames worth reading for one capture.
pub const MAX_FRAMES: usize = 4;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fuller_names() {
        assert!(fuller_name("J. MBATHA", "MBATHA"));
        assert!(fuller_name("Liezel J Petersen", "Liezel Petersen"));
        assert!(fuller_name("Nkosi, SZ", "Nkosi,"));
        assert!(!fuller_name("Mpho Visser P", "Mpho Visser"));
        assert!(!fuller_name("Thabo Ntuli", "Thabo Ntull"));
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct FieldVote {
    pub field: &'static str,
    pub value: Option<String>,
    /// Frames whose reading agrees with the value / frames read.
    pub agree: usize,
    pub of: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct CaptureResult {
    pub fields: Fields,
    pub votes: Vec<FieldVote>,
    /// Against the known customer, when one was given.
    pub customer: Option<CustomerCheck>,
    pub frames_read: usize,
}

fn key(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(char::to_uppercase).collect()
}

fn confidence(r: &AddressResult, field: &str) -> f32 {
    r.verification.fields.iter().find(|c| c.field == field).map_or(0.0, |c| c.confidence)
}

/// Whether name `a` is name `b` with initials `b` lacks: the extra words are
/// initials, and they come before the last word or after a comma.
fn fuller_name(a: &str, b: &str) -> bool {
    let (wa, wb): (Vec<String>, Vec<String>) = (a.split_whitespace().map(key).collect(), b.split_whitespace().map(key).collect());
    if wa.len() <= wb.len() || wb.is_empty() {
        return false;
    }
    // b must be a subsequence of a.
    let mut j = 0;
    let mut extra = Vec::new();
    for (i, w) in wa.iter().enumerate() {
        if j < wb.len() && *w == wb[j] {
            j += 1;
        } else {
            extra.push(i);
        }
    }
    let raw: Vec<&str> = a.split_whitespace().collect();
    j == wb.len()
        && extra.iter().all(|&i| {
            wa[i].len() <= 2 && wa[i].chars().all(char::is_alphabetic) && (i + 1 < wa.len() || raw.get(i.wrapping_sub(1)).is_some_and(|p| p.ends_with(',')))
        })
}

/// How plausible a value is for its field, 0–1, from its form alone: a
/// street with a number and a suffix, a place or code the gazetteer knows.
fn plausibility(field: &str, v: &str) -> f32 {
    let words: Vec<&str> = v.split_whitespace().collect();
    let g = super::gazetteer::gazetteer();
    match field {
        "street" => {
            let num = words.first().is_some_and(|w| w.chars().next().is_some_and(|c| c.is_ascii_digit()));
            let sfx = words.last().is_some_and(|w| super::customer::suffix(&key(w)).is_some());
            0.5 * num as u8 as f32 + 0.5 * sfx as u8 as f32
        }
        "city" | "suburb" => g.knows_place(v) as u8 as f32,
        "postal_code" => {
            let k = key(v);
            0.5 * (k.len() == 4 && k.chars().all(|c| c.is_ascii_digit())) as u8 as f32 + 0.5 * g.knows_code(&k) as u8 as f32
        }
        "holder_name" => (words.len() >= 2 && words.len() <= 6 && !v.chars().any(|c| c.is_ascii_digit())) as u8 as f32,
        _ => 0.0,
    }
}

/// The value most frames agree on (ties: the more confident), with the count.
fn vote(readings: &[&AddressResult], field: &'static str, get: impl Fn(&Fields) -> Option<String>) -> FieldVote {
    let mut groups: HashMap<String, (usize, f32, String)> = HashMap::new();
    let mut none = 0;
    for r in readings {
        match get(&r.fields) {
            Some(v) if !key(&v).is_empty() => {
                let g = groups.entry(key(&v)).or_insert((0, 0.0, v.clone()));
                g.0 += 1;
                let c = confidence(r, field);
                if c > g.1 {
                    g.2 = v;
                }
                g.1 += c.max(1e-3);
            }
            _ => none += 1,
        }
    }
    // Ties (frames that each read it differently) go to the value that is
    // more plausible for the field, then to the one closest to the others
    // (the median reading), then to the more confident.
    let keys: Vec<String> = groups.keys().cloned().collect();
    let score = |k: &String, g: &(usize, f32, String)| -> f32 {
        let others: Vec<&String> = keys.iter().filter(|o| *o != k).collect();
        let spread = if others.is_empty() {
            0.0
        } else {
            others.iter().map(|o| 1.0 - verify::similarity(k, o)).sum::<f32>() / others.len() as f32
        };
        // A name read with an initial that another frame missed ("J. MBATHA"
        // and "MBATHA") is supported by that frame too.
        let absorbed: usize = if field == "holder_name" {
            groups.iter().filter(|(o, _)| *o != k).filter(|(_, og)| fuller_name(&g.2, &og.2)).map(|(_, og)| og.0).sum()
        } else {
            0
        };
        (g.0 + absorbed) as f32 + 0.45 * plausibility(field, &g.2) - 0.3 * spread + 0.05 * g.1.min(3.0)
    };
    let best = groups.iter().max_by(|a, b| score(a.0, a.1).total_cmp(&score(b.0, b.1))).map(|(_, g)| g.clone());
    // A field the page may well not print (a suburb, the province, a
    // period) is left empty when most frames found none; any other field a
    // frame did read beats frames that read none (a frame misses a field far
    // more often than it invents one).
    let optional = matches!(field, "suburb" | "province" | "period_from" | "period_to");
    match best {
        Some((n, _, v)) if !optional || n >= none => FieldVote { field, value: Some(v), agree: n, of: readings.len() },
        _ => FieldVote { field, value: None, agree: none, of: readings.len() },
    }
}

/// Combines the readings of one capture's frames into one set of fields.
pub fn vote_fields(readings: &[&AddressResult]) -> (Fields, Vec<FieldVote>) {
    let mut votes = vec![
        vote(readings, "holder_name", |f| f.holder_name.clone()),
        vote(readings, "street", |f| f.address.street.clone()),
        vote(readings, "suburb", |f| f.address.suburb.clone()),
        vote(readings, "city", |f| f.address.city.clone()),
        vote(readings, "province", |f| f.address.province.clone()),
        vote(readings, "postal_code", |f| f.address.postal_code.clone()),
        vote(readings, "document_date", |f| f.document_date.clone()),
        vote(readings, "period_from", |f| f.statement_period.as_ref().and_then(|p| p.from.clone())),
        vote(readings, "period_to", |f| f.statement_period.as_ref().and_then(|p| p.to.clone())),
        vote(readings, "issuer", |f| f.issuer.clone()),
        vote(readings, "account_number", |f| f.account_number.clone()),
    ];
    let v = |name: &str| votes.iter().find(|x| x.field == name).and_then(|x| x.value.clone());
    let mut f = Fields {
        holder_name: v("holder_name"),
        document_date: v("document_date"),
        issuer: v("issuer"),
        account_number: v("account_number"),
        ..Default::default()
    };
    f.address.street = v("street");
    f.address.suburb = v("suburb");
    f.address.city = v("city");
    f.address.province = v("province");
    f.address.postal_code = v("postal_code");
    let (from, to) = (v("period_from"), v("period_to"));
    if from.is_some() || to.is_some() {
        f.statement_period = Some(Period { from, to });
    }
    f.document_type = readings.first().map(|r| r.fields.document_type).unwrap_or_default();
    f.province_inferred = readings.iter().any(|r| r.fields.province_inferred) && f.address.province.is_some();
    votes.retain(|x| x.of > 0);
    (f, votes)
}

/// The document's date for the age check: its date, or else the end of its period.
pub fn doc_date(f: &Fields) -> Option<Date> {
    f.document_date.as_deref().or(f.statement_period.as_ref().and_then(|p| p.to.as_deref())).and_then(Date::parse_iso)
}

/// Combines the customer checks of several frames: the best name and the
/// best holder's address of any frame, and the voted date.
pub fn combine_checks(checks: &[&CustomerCheck], date: Option<Date>, today: Date) -> CustomerCheck {
    let name = checks.iter().filter_map(|c| c.name.clone()).max_by(|a, b| a.score.total_cmp(&b.score));
    let address = checks.iter().filter_map(|c| c.address.clone()).max_by(|a, b| a.score.total_cmp(&b.score));
    let elsewhere = if address.is_none() {
        checks.iter().filter_map(|c| c.address_elsewhere.clone()).max_by(|a, b| a.score.total_cmp(&b.score))
    } else {
        None
    };
    customer::decide(name, address, elsewhere, date.map(|d| verify::age(d, today)))
}

/// Reads one capture from per-frame readings (each with its words, for the
/// customer check).
pub fn combine(readings: &[&AddressResult], words: &[&[super::features::Word]], customer_: Option<&Customer>, today: Date) -> CaptureResult {
    let (mut fields, votes) = vote_fields(readings);
    // The document date: the tagger's reading of each frame, with the
    // rules' labelled date ("Statement date: ...") of each frame as half a vote.
    let mut tally: Vec<(String, f32)> = Vec::new();
    let mut add = |d: Option<String>, w: f32| {
        if let Some(d) = d {
            match tally.iter_mut().find(|t| t.0 == d) {
                Some(t) => t.1 += w,
                None => tally.push((d, w)),
            }
        }
    };
    for (r, w) in readings.iter().zip(words) {
        add(r.fields.document_date.clone(), 1.0);
        add(super::rules::extract(w, r.page_size[1] as f32, &r.text, today).0.document_date, RULES_DATE_VOTE);
    }
    // Between readings that disagree, a date within the last thirteen months
    // (a misread year is the usual slip: 2020 for 2026) is the likelier.
    for t in tally.iter_mut() {
        if let Some(d) = Date::parse_iso(&t.0) {
            let age = today.days() - d.days();
            if (-10..=400).contains(&age) {
                t.1 += 0.2;
            }
        }
    }
    if let Some((d, wgt)) = tally.iter().cloned().max_by(|a, b| a.1.total_cmp(&b.1))
        && fields.document_date.as_ref().is_none_or(|cur| tally.iter().find(|t| &t.0 == cur).map_or(0.0, |t| t.1) < wgt)
    {
        fields.document_date = Some(d);
    }
    let date = doc_date(&fields);
    let customer = customer_.map(|c| {
        let checks: Vec<CustomerCheck> =
            readings.iter().zip(words).map(|(r, w)| customer::check(w, &r.spans, c, date, today)).collect();
        let refs: Vec<&CustomerCheck> = checks.iter().collect();
        combine_checks(&refs, date, today)
    });
    CaptureResult { fields, votes, customer, frames_read: readings.len() }
}

/// Whether another frame should be read: fewer than two read, or the two
/// (or more) read so far disagree on a key field (name, street, city, postal
/// code, date), and fewer than
/// [`MAX_FRAMES`] have been read.
pub fn next_frame_needed(result: &CaptureResult) -> bool {
    if result.frames_read >= MAX_FRAMES {
        return false;
    }
    if result.frames_read < 2 {
        return true;
    }
    let key_fields = ["holder_name", "street", "city", "postal_code", "document_date"];
    let split = result.votes.iter().filter(|v| key_fields.contains(&v.field)).any(|v| v.agree < v.of);
    split
}
