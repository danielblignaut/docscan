//! Checks on extracted proof-of-address fields: is each value printed on the
//! page (a guard against a model inventing one), does the postal code belong
//! to the province, and how old is the document.

use serde::Serialize;

// --------------------------------------------------------------------------
// Provinces and postal codes
// --------------------------------------------------------------------------

pub const PROVINCES: [&str; 9] = [
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "North West",
    "Northern Cape",
    "Western Cape",
];

/// The canonical province for a printed name or abbreviation.
pub fn province(text: &str) -> Option<&'static str> {
    let t: String = text.to_lowercase().chars().filter(|c| c.is_alphanumeric()).collect();
    Some(match t.as_str() {
        "easterncape" | "ec" | "oostkaap" => "Eastern Cape",
        "freestate" | "fs" | "vrystaat" => "Free State",
        "gauteng" | "gp" | "gt" => "Gauteng",
        "kwazulunatal" | "kzn" | "natal" | "kwazulu" => "KwaZulu-Natal",
        "limpopo" | "lp" | "lim" => "Limpopo",
        "mpumalanga" | "mp" => "Mpumalanga",
        "northwest" | "nw" | "noordwes" => "North West",
        "northerncape" | "nc" | "noordkaap" => "Northern Cape",
        "westerncape" | "wc" | "weskaap" => "Western Cape",
        _ => return None,
    })
}

/// Coarse street-code ranges of the South African Post Office, and the
/// provinces each may belong to. SAPO allocates codes in four regional
/// blocks (Northern 0001-2899: Gauteng, Mpumalanga, Limpopo, North West;
/// Eastern 2900-4730: KwaZulu-Natal and the east of the Eastern Cape;
/// 4731-6499 the rest of the Eastern Cape; Western 6500-8299; Central
/// 8300-9999: Northern Cape and Free State), as summarised in Wikipedia's
/// "Postal codes in South Africa" and SAPO's own code list
/// (https://www.postoffice.co.za, "Postal codes"). The sub-ranges below
/// follow the towns at their edges (e.g. Brits 0250 and Rustenburg 0300 in
/// North West, Sasolburg 1947 in the Free State, Springbok 8240 in the
/// Northern Cape, Vryburg 8601 in North West, Aliwal North 9750 in the
/// Eastern Cape). Ranges overlap by design: a code is inconsistent only when
/// its province is in none of them. 9000-9299 was South West Africa's and is
/// unused.
const POSTAL_RANGES: &[(u16, u16, &[&str])] = &[
    (1, 299, &["Gauteng", "North West"]),
    (300, 399, &["North West", "Limpopo"]),
    (400, 499, &["Limpopo", "Mpumalanga", "North West"]),
    (500, 999, &["Limpopo"]),
    (1000, 1399, &["Mpumalanga", "Gauteng"]),
    (1400, 1899, &["Gauteng"]),
    (1900, 1999, &["Gauteng", "Free State"]),
    (2000, 2199, &["Gauteng"]),
    (2200, 2499, &["Mpumalanga"]),
    (2500, 2899, &["North West"]),
    (2900, 4599, &["KwaZulu-Natal"]),
    (4600, 4730, &["KwaZulu-Natal", "Eastern Cape"]),
    (4731, 6499, &["Eastern Cape"]),
    (6500, 8099, &["Western Cape"]),
    (8100, 8299, &["Western Cape", "Northern Cape"]),
    (8300, 8499, &["Northern Cape"]),
    (8500, 8699, &["Northern Cape", "North West"]),
    (8700, 8999, &["Northern Cape"]),
    (9300, 9699, &["Free State"]),
    (9700, 9999, &["Free State", "Northern Cape", "Eastern Cape"]),
];

/// The provinces a 4-digit street code may belong to (empty: not a code).
pub fn provinces_for_postal_code(code: &str) -> &'static [&'static str] {
    let Ok(n) = code.trim().parse::<u16>() else { return &[] };
    if code.trim().len() != 4 {
        return &[];
    }
    POSTAL_RANGES.iter().find(|(lo, hi, _)| (*lo..=*hi).contains(&n)).map_or(&[], |(_, _, p)| p)
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PostalCheck {
    /// The code is in a range the province uses.
    Consistent,
    /// The code belongs to other provinces.
    Inconsistent,
    /// Not a valid code, or no province to compare it with.
    Unknown,
}

pub fn check_postal_code(code: Option<&str>, province: Option<&str>) -> PostalCheck {
    let (Some(code), Some(province)) = (code, province) else { return PostalCheck::Unknown };
    let allowed = provinces_for_postal_code(code);
    if allowed.is_empty() {
        PostalCheck::Unknown
    } else if allowed.contains(&province) {
        PostalCheck::Consistent
    } else {
        PostalCheck::Inconsistent
    }
}

// --------------------------------------------------------------------------
// Dates
// --------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct Date {
    pub year: i32,
    pub month: u32,
    pub day: u32,
}

impl Date {
    pub fn new(year: i32, month: u32, day: u32) -> Option<Date> {
        let dim = days_in_month(year, month)?;
        (1..=dim).contains(&day).then_some(Date { year, month, day })
    }

    pub fn iso(&self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }

    /// Days since 1970-01-01 (Howard Hinnant's `days_from_civil`).
    pub fn days(&self) -> i64 {
        let y = if self.month <= 2 { self.year - 1 } else { self.year } as i64;
        let era = if y >= 0 { y } else { y - 399 } / 400;
        let yoe = y - era * 400;
        let m = self.month as i64;
        let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + self.day as i64 - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        era * 146097 + doe - 719468
    }

    /// The same day `months` calendar months earlier, clamped to the month's end.
    pub fn minus_months(&self, months: u32) -> Date {
        let total = self.year * 12 + self.month as i32 - 1 - months as i32;
        let (year, month) = (total.div_euclid(12), total.rem_euclid(12) as u32 + 1);
        let day = self.day.min(days_in_month(year, month).unwrap_or(28));
        Date { year, month, day }
    }

    pub fn parse_iso(s: &str) -> Option<Date> {
        let p: Vec<&str> = s.trim().split('-').collect();
        if p.len() != 3 {
            return None;
        }
        Date::new(p[0].parse().ok()?, p[1].parse().ok()?, p[2].parse().ok()?)
    }
}

fn days_in_month(year: i32, month: u32) -> Option<u32> {
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    Some(match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => return None,
    })
}

fn month_number(word: &str) -> Option<u32> {
    let w: String = word.to_lowercase().chars().filter(|c| c.is_alphabetic()).collect();
    if w.len() < 3 {
        return None;
    }
    const NAMES: [&str; 12] = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
    // Afrikaans month names that do not share the English prefix.
    const AF: [(&str, u32); 4] = [("januarie", 1), ("februarie", 2), ("maart", 3), ("mei", 5)];
    if let Some(&(_, m)) = AF.iter().find(|(n, _)| *n == w) {
        return Some(m);
    }
    if w == "okt" || w == "oktober" {
        return Some(10);
    }
    if w == "des" || w == "desember" {
        return Some(12);
    }
    if let Some(i) = NAMES.iter().position(|n| n.starts_with(&w)) {
        return Some(i as u32 + 1);
    }
    // An OCR slip in a written-out month ("Octeber", "Septernber").
    if w.len() >= 5 {
        return NAMES
            .iter()
            .enumerate()
            .map(|(i, n)| (i, similarity(&w, n)))
            .filter(|(_, s)| *s >= 0.75)
            .max_by(|a, b| a.1.total_cmp(&b.1))
            .map(|(i, _)| i as u32 + 1);
    }
    None
}

fn year(s: &str) -> Option<i32> {
    let d: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
    if d.len() != s.trim_matches(|c: char| !c.is_alphanumeric()).len() {
        return None;
    }
    match d.len() {
        4 => d.parse().ok().filter(|y| (1990..=2100).contains(y)),
        2 => d.parse::<i32>().ok().map(|y| 2000 + y),
        _ => None,
    }
}

fn number(s: &str, max: u32) -> Option<u32> {
    let t = s.trim_matches(|c: char| !c.is_alphanumeric());
    let t = t.trim_end_matches(|c: char| c.is_alphabetic()); // 15th, 1st
    (!t.is_empty() && t.len() <= 2 && t.chars().all(|c| c.is_ascii_digit())).then(|| t.parse().ok()).flatten().filter(|&n| n >= 1 && n <= max)
}

/// A date written in one word: `2026-03-15`, `2026/03/15`, `15/03/2026`,
/// `15.03.2026`, `15-Mar-2026`. South African dates are day first.
fn date_word(word: &str) -> Option<Date> {
    let t = word.trim_matches(|c: char| !c.is_alphanumeric());
    let p: Vec<&str> = t.split(['/', '-', '.']).collect();
    if p.len() != 3 {
        return None;
    }
    if p[0].len() == 4 {
        return Date::new(year(p[0])?, number(p[1], 12)?, number(p[2], 31)?);
    }
    let month = number(p[1], 12).or_else(|| month_number(p[1]))?;
    Date::new(year(p[2])?, month, number(p[0], 31)?)
}

/// Every date in a run of words, with the word span it covers
/// (`start..end`). Also `15 March 2026`, `15 Mar 2026`, `March 15, 2026`.
pub fn find_dates(words: &[&str]) -> Vec<(usize, usize, Date)> {
    // OCR runs "16," and "2026" together ("16,2026"): split such words, and
    // map spans back to the words given.
    let mut split: Vec<(String, usize)> = Vec::new();
    for (i, w) in words.iter().enumerate() {
        // "OCT2026", "15Mar": letters and digits run together.
        let boundary = w.char_indices().skip(1).find(|&(k, c)| {
            let prev = w[..k].chars().last().unwrap();
            (prev.is_ascii_alphabetic() && c.is_ascii_digit()) || (prev.is_ascii_digit() && c.is_ascii_alphabetic())
        });
        match (w.split_once(','), boundary) {
            (Some((a, b)), _) if !a.is_empty() && !b.is_empty() && b.chars().all(|c| c.is_ascii_digit()) => {
                split.push((format!("{a},"), i));
                split.push((b.to_string(), i));
            }
            (_, Some((k, _))) if w.chars().all(|c| c.is_ascii_alphanumeric()) && month_number(&w[..k]).or(month_number(&w[k..])).is_some() => {
                split.push((w[..k].to_string(), i));
                split.push((w[k..].to_string(), i));
            }
            _ => split.push((w.to_string(), i)),
        }
    }
    if split.len() != words.len() {
        let ws: Vec<&str> = split.iter().map(|s| s.0.as_str()).collect();
        return find_dates(&ws).into_iter().map(|(a, b, d)| (split[a].1, split[b - 1].1 + 1, d)).collect();
    }
    let mut out = Vec::new();
    let mut i = 0;
    while i < words.len() {
        if let Some(d) = date_word(words[i]) {
            out.push((i, i + 1, d));
            i += 1;
            continue;
        }
        if i + 2 < words.len() {
            // 15 March 2026
            if let (Some(day), Some(m), Some(y)) = (number(words[i], 31), month_number(words[i + 1]), year(words[i + 2]))
                && let Some(d) = Date::new(y, m, day)
            {
                out.push((i, i + 3, d));
                i += 3;
                continue;
            }
            // March 15, 2026
            if let (Some(m), Some(day), Some(y)) = (month_number(words[i]), number(words[i + 1], 31), year(words[i + 2]))
                && let Some(d) = Date::new(y, m, day)
            {
                out.push((i, i + 3, d));
                i += 3;
                continue;
            }
        }
        i += 1;
    }
    out
}

/// The first date in a string.
pub fn parse_date(text: &str) -> Option<Date> {
    let words: Vec<&str> = text.split_whitespace().collect();
    find_dates(&words).first().map(|d| d.2)
}

#[derive(Debug, Clone, Serialize)]
pub struct Age {
    pub date: String,
    pub age_days: i64,
    /// Issued no more than three calendar months before `today`.
    pub recent: bool,
    /// Dated after `today`.
    pub future: bool,
}

pub fn age(date: Date, today: Date) -> Age {
    let age_days = today.days() - date.days();
    Age { date: date.iso(), age_days, recent: date >= today.minus_months(3) && age_days >= -7, future: age_days < 0 }
}

// --------------------------------------------------------------------------
// Is the value printed on the page?
// --------------------------------------------------------------------------

/// Upper-case letters and digits, words separated by one space.
pub fn normalise(s: &str) -> String {
    s.split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_uppercase())
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn levenshtein(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    let mut cur = vec![0; b.len() + 1];
    for i in 1..=a.len() {
        cur[0] = i;
        for j in 1..=b.len() {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            cur[j] = (prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + cost);
        }
        std::mem::swap(&mut prev, &mut cur);
    }
    prev[b.len()]
}

pub fn similarity(a: &str, b: &str) -> f32 {
    let n = a.chars().count().max(b.chars().count());
    if n == 0 {
        return 1.0;
    }
    1.0 - levenshtein(a, b) as f32 / n as f32
}

/// How well `value` matches the best run of words in the page's text, 0–1:
/// windows of the value's word count (and one either side) are compared
/// with the Levenshtein ratio, ignoring case, punctuation and spacing.
pub fn best_match(value: &str, page_words: &[String]) -> f32 {
    let v = normalise(value);
    if v.is_empty() {
        return 0.0;
    }
    let vc: String = v.chars().filter(|c| *c != ' ').collect();
    let n = v.split(' ').count();
    let mut best = 0f32;
    for len in n.saturating_sub(1).max(1)..=n + 1 {
        for win in page_words.windows(len.min(page_words.len().max(1))) {
            let s: String = win.concat();
            best = best.max(similarity(&vc, &s));
            if best >= 1.0 {
                return 1.0;
            }
        }
    }
    best
}

/// The page's words, normalised as [`best_match`] wants them.
pub fn page_words(text: &str) -> Vec<String> {
    normalise(text).split(' ').filter(|w| !w.is_empty()).map(String::from).collect()
}

/// A value counts as printed when it matches this well (short values,
/// like a postal code, must match exactly).
pub fn found(value: &str, page_words: &[String]) -> (bool, f32) {
    let score = best_match(value, page_words);
    let short = normalise(value).chars().filter(|c| *c != ' ').count() <= 5;
    (if short { score >= 0.999 } else { score >= 0.8 }, score)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dates_in_many_formats() {
        let want = Date::new(2026, 3, 15).unwrap();
        for s in ["15 March 2026", "15 Mar 2026", "2026-03-15", "15/03/2026", "2026/03/15", "15.03.2026", "March 15, 2026", "15-Mar-2026", "15 Maart 2026", "Date: 15/03/26"] {
            assert_eq!(parse_date(s), Some(want), "{s}");
        }
        assert_eq!(parse_date("31/02/2026"), None);
        let words = ["Period:", "01", "Sep", "2026", "-", "30", "Sep", "2026"];
        let found = find_dates(&words);
        assert_eq!(found.len(), 2);
        assert_eq!(found[1].2.iso(), "2026-09-30");
        assert_eq!(parse_date("March 16,2026"), Some(Date::new(2026, 3, 16).unwrap()));
        assert_eq!(parse_date("05 Octeber 2026"), Some(Date::new(2026, 10, 5).unwrap()));
        assert_eq!(parse_date("08 OCT2026"), Some(Date::new(2026, 10, 8).unwrap()));
    }

    #[test]
    fn three_month_rule() {
        let today = Date::new(2026, 10, 15).unwrap();
        assert!(age(Date::new(2026, 7, 15).unwrap(), today).recent);
        assert!(!age(Date::new(2026, 7, 14).unwrap(), today).recent);
        assert_eq!(age(Date::new(2026, 10, 1).unwrap(), today).age_days, 14);
        // Month ends clamp: 31 May minus three months is 28 February.
        assert_eq!(Date::new(2026, 5, 31).unwrap().minus_months(3).iso(), "2026-02-28");
        assert!(age(Date::new(2026, 10, 20).unwrap(), today).future);
    }

    #[test]
    fn postal_codes_and_provinces() {
        let c = |code, p| check_postal_code(Some(code), Some(p));
        assert_eq!(c("7700", "Western Cape"), PostalCheck::Consistent); // Rondebosch
        assert_eq!(c("2196", "Gauteng"), PostalCheck::Consistent); // Sandton
        assert_eq!(c("0083", "Gauteng"), PostalCheck::Consistent); // Hatfield
        assert_eq!(c("4319", "KwaZulu-Natal"), PostalCheck::Consistent); // Umhlanga
        assert_eq!(c("6001", "Eastern Cape"), PostalCheck::Consistent); // Summerstrand
        assert_eq!(c("9301", "Free State"), PostalCheck::Consistent); // Bloemfontein
        assert_eq!(c("0699", "Limpopo"), PostalCheck::Consistent); // Polokwane
        assert_eq!(c("1200", "Mpumalanga"), PostalCheck::Consistent); // Mbombela
        assert_eq!(c("8301", "Northern Cape"), PostalCheck::Consistent); // Kimberley
        assert_eq!(c("2531", "North West"), PostalCheck::Consistent); // Potchefstroom
        assert_eq!(c("7700", "Gauteng"), PostalCheck::Inconsistent);
        assert_eq!(c("9100", "Gauteng"), PostalCheck::Unknown);
        assert_eq!(province("KZN"), Some("KwaZulu-Natal"));
        assert_eq!(province("WESTERN CAPE"), Some("Western Cape"));
    }

    #[test]
    fn printed_values_are_found() {
        let words = page_words("Account holder: MS T DLAMINI\n12 Acacia Avenue, Rondebosch\nCape Town 7700");
        assert!(found("Ms T. Dlamini", &words).0);
        assert!(found("12 Acacia Ave", &words).1 > 0.7);
        assert!(found("7700", &words).0);
        assert!(!found("7701", &words).0);
        assert!(!found("Mr Sipho Nkosi", &words).0);
    }
}
