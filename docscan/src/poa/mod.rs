//! Proof of address: the holder's name and address, the document's date and
//! issuer, read from a captured page.
//!
//! The page is OCR'd word by word ([`crate::Scanner::ocr_tiled_words`]) and
//! then either
//! - tagged by a small trained model ([`tagger`]; the default), whose spans
//!   become fields, or
//! - read by layout rules ([`rules`]; the fallback when no model is loaded).
//!
//! Either way, [`verify`] then checks every value against the page's text,
//! the postal code against the province, and the document's age.

pub mod features;
pub mod rules;
pub mod tagger;
pub mod verify;

use serde::{Deserialize, Serialize};

use features::Word;
use tagger::Span;
use verify::{Age, Date, PostalCheck};

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Address {
    pub street: Option<String>,
    pub suburb: Option<String>,
    pub city: Option<String>,
    /// One of [`verify::PROVINCES`].
    pub province: Option<String>,
    pub postal_code: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Period {
    pub from: Option<String>,
    pub to: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DocumentType {
    UtilityBill,
    BankStatement,
    MunicipalAccount,
    CellphoneAccount,
    LeaseAgreement,
    InsuranceStatement,
    #[default]
    Other,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Fields {
    pub holder_name: Option<String>,
    pub address: Address,
    /// ISO 8601.
    pub document_date: Option<String>,
    pub statement_period: Option<Period>,
    pub issuer: Option<String>,
    pub account_number: Option<String>,
    pub document_type: DocumentType,
    /// The province was not printed, and was taken from the postal code.
    #[serde(default)]
    pub province_inferred: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct FieldCheck {
    pub field: &'static str,
    pub value: String,
    /// The value is printed on the page (see [`verify::found`]).
    pub found: bool,
    /// How well it matches the best run of words on the page, 0–1.
    pub match_score: f32,
    /// The extractor's own confidence, 0–1 (the tagger's probability; rules
    /// report 1 for a labelled value and 0.5 for a guessed one).
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize)]
pub struct Verification {
    pub fields: Vec<FieldCheck>,
    pub postal_code: PostalCheck,
    pub age: Option<Age>,
    /// Name, street, postal code and a date present; every value printed;
    /// the postal code consistent; issued within three months.
    pub accepted: bool,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Method {
    Tagger,
    Rules,
}

#[derive(Debug, Clone, Serialize)]
pub struct AddressResult {
    pub method: Method,
    pub fields: Fields,
    pub verification: Verification,
    /// The page's text, line by line in reading order.
    pub text: String,
    pub words: usize,
    /// The tagger's spans, for inspection.
    pub spans: Vec<Span>,
    pub page_size: [u32; 2],
    pub timings_ms: AddressTimings,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct AddressTimings {
    pub enhance: f64,
    pub ocr: f64,
    pub extract: f64,
    pub total: f64,
}

/// The page's text, one line per reading-order line.
pub fn page_text(words: &[Word]) -> String {
    let mut out = String::new();
    let mut last = usize::MAX;
    for w in words {
        if last != usize::MAX {
            out.push(if w.line != last { '\n' } else { ' ' });
        }
        out.push_str(&w.text);
        last = w.line;
    }
    out
}

/// Strips the punctuation a field picks up from the page (`Rondebosch,`,
/// `Name:`), keeping a closing `.` of an initial.
pub fn clean(s: &str) -> String {
    let t = s.trim().trim_matches(|c: char| matches!(c, ',' | ';' | ':' | '|' | '-' | '–' | '(' | ')' | '"' | '\'')).trim();
    // A full stop OCR read for a comma ("Benoni."), but not an initial's ("J.").
    let last = t.split_whitespace().last().unwrap_or("");
    let t = if last.len() > 2 && !last[..last.len() - 1].contains('.') { t.strip_suffix('.').unwrap_or(t) } else { t };
    t.trim_end_matches(',').trim().to_string()
}

/// The kind of document, from the words printed on it.
pub fn document_type(text: &str) -> DocumentType {
    let t = text.to_lowercase();
    let score = |words: &[&str]| words.iter().map(|w| t.matches(w).count()).sum::<usize>();
    let candidates = [
        (DocumentType::LeaseAgreement, score(&["lease", "lessee", "lessor", "tenant", "landlord", "rental agreement"]) * 2),
        (DocumentType::BankStatement, score(&["bank statement", "opening balance", "closing balance", "branch code", "transaction", "cheque account", "savings account", "current account"])),
        (DocumentType::MunicipalAccount, score(&["municipal", "municipality", "rates", "refuse", "sewerage", "property valuation", "erf"])),
        (DocumentType::CellphoneAccount, score(&["airtime", "contract", "data bundle", "cellphone", "mobile", "sms", "msisdn", "sim"])),
        (DocumentType::InsuranceStatement, score(&["policy", "policyholder", "premium", "insurer", "cover", "insured"])),
        (DocumentType::UtilityBill, score(&["electricity", "kwh", "water", "meter", "prepaid", "utility", "consumption", "units"])),
    ];
    candidates.into_iter().filter(|c| c.1 > 0).max_by_key(|c| c.1).map_or(DocumentType::Other, |c| c.0)
}

/// Turns the tagger's spans into fields. For each entity the most probable
/// span wins; the address parts prefer spans near the chosen postal code (a
/// page often carries the issuer's own address too).
pub fn fields_from_spans(words: &[Word], spans: &[Span], text: &str) -> (Fields, Vec<(&'static str, f32)>) {
    let mut confidence = Vec::new();
    let mut hs: Vec<f32> = words.iter().map(|w| w.h).collect();
    hs.sort_by(f32::total_cmp);
    let mh = hs.get(hs.len() / 2).copied().unwrap_or(10.0).max(1.0);
    let centre = |s: &Span| {
        let n = s.words.len() as f32;
        (s.words.iter().map(|&i| words[i].x + words[i].w / 2.0).sum::<f32>() / n, s.words.iter().map(|&i| words[i].y + words[i].h / 2.0).sum::<f32>() / n)
    };
    let best = |entity: &str, near: Option<(f32, f32)>| -> Option<&Span> {
        spans.iter().filter(|s| s.entity == entity).max_by(|a, b| {
            let adj = |s: &Span| match near {
                Some((x, y)) => {
                    let (cx, cy) = centre(s);
                    let d = ((cy - y).abs() + 0.3 * (cx - x).abs()) / mh;
                    s.score - 0.02 * d + 0.05 * s.words.len().min(5) as f32
                }
                // Between spans as likely, the fuller one: "Dear Mrs Jali"
                // also tags the holder, but "Mrs B Jali" is the name.
                None => s.score + 0.05 * s.words.len().min(5) as f32,
            };
            adj(a).total_cmp(&adj(b))
        })
    };
    let mut f = Fields::default();
    let postal = spans
        .iter()
        .filter(|s| s.entity == "POSTAL_CODE")
        .filter(|s| clean(&s.text).chars().filter(|c| c.is_ascii_digit()).count() == 4)
        .max_by(|a, b| a.score.total_cmp(&b.score));
    let anchor = postal.map(centre);
    if let Some(p) = postal {
        f.address.postal_code = Some(clean(&p.text).chars().filter(|c| c.is_ascii_digit()).collect());
        confidence.push(("postal_code", p.score));
    }
    let mut take = |entity: &'static str, field: &'static str, near: Option<(f32, f32)>| -> Option<String> {
        let s = best(entity, near)?;
        confidence.push((field, s.score));
        Some(clean(&s.text))
    };
    f.address.street = take("STREET", "street", anchor);
    f.address.suburb = take("SUBURB", "suburb", anchor);
    f.address.city = take("CITY", "city", anchor);
    f.address.province = take("PROVINCE", "province", anchor).and_then(|p| verify::province(&p).map(String::from));
    f.holder_name = take("HOLDER_NAME", "holder_name", anchor).map(|n| clean_name(&n));
    f.issuer = take("ISSUER", "issuer", None).map(|i| clean_issuer(&i));
    f.account_number = take("ACCOUNT_NO", "account_number", None);
    let date_of = |entity: &str| -> Option<String> { best(entity, None).and_then(|s| span_date(words, s)).map(|d| d.iso()) };
    let mut dated = |entity: &'static str, field: &'static str| {
        let d = date_of(entity);
        if d.is_some()
            && let Some(s) = best(entity, None)
        {
            confidence.push((field, s.score));
        }
        d
    };
    f.document_date = dated("DOC_DATE", "document_date");
    let from = dated("PERIOD_FROM", "period_from");
    let to = dated("PERIOD_TO", "period_to");
    if from.is_some() || to.is_some() {
        f.statement_period = Some(Period { from, to });
    }
    f.document_type = document_type(text);
    infer_province(&mut f);
    (f, confidence)
}

/// An issuer's name as read from a header: without the logo's initials in
/// front ("NW Nalendi Water", "OBOndela Bank") and said once ("Qhamani Bank
/// Qhamani Bank": the name and the logo's wordmark).
pub fn clean_issuer(s: &str) -> String {
    let s = clean(s);
    let mut words: Vec<String> = s.split_whitespace().map(String::from).collect();
    if words.len() >= 2 {
        let initials = |ws: &[String]| -> String { ws.iter().filter_map(|w| w.chars().next()).filter(|c| c.is_alphabetic()).collect::<String>().to_uppercase() };
        let first = words[0].clone();
        if words.len() >= 3 && first.len() <= 3 && first.chars().all(char::is_alphabetic) && initials(&words[1..]).starts_with(&first.to_uppercase()) {
            words.remove(0);
        } else {
            // Initials run into the name: "OBOndela" + "Bank".
            for k in (1..=3).rev() {
                if first.len() > k + 2 && first.is_char_boundary(k) && first[..k].chars().all(|c| c.is_ascii_uppercase()) {
                    let mut rest = vec![first[k..].to_string()];
                    rest.extend(words[1..].iter().cloned());
                    if initials(&rest).starts_with(&first[..k]) && first[k..].chars().next().is_some_and(char::is_uppercase) {
                        words = rest;
                        break;
                    }
                }
            }
        }
    }
    // The same name twice in a row (allowing an OCR slip): keep one.
    let n = words.len();
    if n >= 2 && n % 2 == 0 {
        let (a, b) = (words[..n / 2].join(" "), words[n / 2..].join(" "));
        if verify::similarity(&verify::normalise(&a), &verify::normalise(&b)) >= 0.8 {
            return clean(&b);
        }
    }
    clean(&words.join(" "))
}

/// A holder's name without a label read into it ("Name RIAAN JOUBERT").
pub fn clean_name(s: &str) -> String {
    let s = clean(s);
    let lower = s.to_lowercase();
    for label in ["account holder", "account name", "customer name", "name", "customer", "client", "tenant", "lessee", "policyholder", "member", "dear", "attention", "attn"] {
        if let Some(rest) = lower.strip_prefix(label)
            && (rest.starts_with(' ') || rest.starts_with(':'))
        {
            return clean(&s[label.len()..]);
        }
    }
    s
}

/// Rejoins a numeric date OCR split at a separator (`08.12. 2025`,
/// `15 /03/2026`).
pub fn rejoin_date(s: &str) -> String {
    let mut out = String::new();
    let chars: Vec<char> = s.chars().collect();
    for (i, &c) in chars.iter().enumerate() {
        if c == ' ' {
            let prev = chars[..i].iter().rev().find(|c| **c != ' ');
            let next = chars[i + 1..].iter().find(|c| **c != ' ');
            let sep = |c: Option<&char>| c.is_some_and(|c| matches!(c, '.' | '/' | '-'));
            if (sep(prev) && next.is_some_and(|c| c.is_ascii_digit())) || (sep(next) && prev.is_some_and(|c| c.is_ascii_digit())) {
                continue;
            }
        }
        out.push(c);
    }
    out
}

/// The date a span tags. The tagger often marks only part of a written date
/// ("14, 2026" of "June 14, 2026"), so when the span alone does not parse,
/// the dates printed on its line(s) are read and the one overlapping the
/// span is taken.
fn span_date(words: &[Word], s: &Span) -> Option<Date> {
    if let Some(d) = verify::parse_date(&rejoin_date(&s.text)) {
        return Some(d);
    }
    let lines: Vec<usize> = s.words.iter().map(|&i| words[i].line).collect();
    let on: Vec<usize> = (0..words.len()).filter(|i| lines.contains(&words[*i].line)).collect();
    let texts: Vec<String> = on.iter().map(|&i| words[i].text.clone()).collect();
    let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
    verify::find_dates(&refs)
        .into_iter()
        .find(|(a, b, _)| on[*a..*b].iter().any(|i| s.words.contains(i)))
        .map(|d| d.2)
}

/// A province not printed is taken from the postal code when the code
/// belongs to one province only.
pub fn infer_province(f: &mut Fields) {
    if f.address.province.is_none()
        && let Some(code) = &f.address.postal_code
        && let [only] = verify::provinces_for_postal_code(code)
    {
        f.address.province = Some(only.to_string());
        f.province_inferred = true;
    }
}

/// Checks every field against the page and the rules.
pub fn verify_fields(f: &Fields, text: &str, confidence: &[(&'static str, f32)], today: Date) -> Verification {
    let page = verify::page_words(text);
    let conf = |field: &str| confidence.iter().find(|(k, _)| *k == field).map_or(0.0, |c| c.1);
    let mut checks = Vec::new();
    let mut check = |field: &'static str, value: Option<&String>| {
        if let Some(v) = value {
            let (found, score) = verify::found(v, &page);
            checks.push(FieldCheck { field, value: v.clone(), found, match_score: score, confidence: conf(field) });
        }
    };
    check("holder_name", f.holder_name.as_ref());
    check("street", f.address.street.as_ref());
    check("suburb", f.address.suburb.as_ref());
    check("city", f.address.city.as_ref());
    if !f.province_inferred {
        check("province", f.address.province.as_ref());
    }
    check("postal_code", f.address.postal_code.as_ref());
    check("issuer", f.issuer.as_ref());
    check("account_number", f.account_number.as_ref());
    // Dates are checked as dates: any printed date on the page that equals it.
    let printed_dates: Vec<Date> = {
        let ws: Vec<&str> = text.split_whitespace().collect();
        verify::find_dates(&ws).into_iter().map(|d| d.2).collect()
    };
    for (field, value) in [
        ("document_date", f.document_date.as_ref()),
        ("period_from", f.statement_period.as_ref().and_then(|p| p.from.as_ref())),
        ("period_to", f.statement_period.as_ref().and_then(|p| p.to.as_ref())),
    ] {
        if let Some(v) = value {
            let found = Date::parse_iso(v).is_some_and(|d| printed_dates.contains(&d));
            checks.push(FieldCheck { field, value: v.clone(), found, match_score: if found { 1.0 } else { 0.0 }, confidence: conf(field) });
        }
    }

    let postal_code = verify::check_postal_code(f.address.postal_code.as_deref(), f.address.province.as_deref());
    // The document's date; failing that, the end of its statement period.
    let date = f
        .document_date
        .as_deref()
        .or(f.statement_period.as_ref().and_then(|p| p.to.as_deref()))
        .and_then(Date::parse_iso);
    let age = date.map(|d| verify::age(d, today));

    let mut reasons = Vec::new();
    for (name, v) in [("holder name", &f.holder_name), ("street", &f.address.street), ("postal code", &f.address.postal_code)] {
        if v.is_none() {
            reasons.push(format!("no {name}"));
        }
    }
    match &age {
        None => reasons.push("no document date".into()),
        Some(a) if a.future => reasons.push(format!("dated in the future ({})", a.date)),
        Some(a) if !a.recent => reasons.push(format!("older than three months ({} days)", a.age_days)),
        _ => {}
    }
    for c in &checks {
        if !c.found {
            reasons.push(format!("{} not found on the page", c.field));
        }
    }
    if postal_code == PostalCheck::Inconsistent {
        reasons.push("postal code does not match the province".into());
    }
    Verification { fields: checks, postal_code, age, accepted: reasons.is_empty(), reasons }
}
