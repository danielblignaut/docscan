//! Per-word features for the field tagger. The training script reads these
//! from `examples/poa_words.rs` rather than recomputing them, so training and
//! inference cannot drift apart: this module is the only definition.
//!
//! Each OCR word gets
//! - up to [`MAX_IDS`] hashed text features (the whole word, its shape and
//!   its character trigrams), FNV-1a hashed into [`BUCKETS`] (0 is padding);
//! - [`NUM_FEATURES`] numbers: its box on the page, its place in its line
//!   and the gaps around it, and simple shape flags (digits, case, a 4-digit
//!   number, a date, a month or province name, a currency amount, ...).

use serde::{Deserialize, Serialize};

use crate::za::Line;

/// Hash buckets for the text features. Bucket 0 is padding.
pub const BUCKETS: u32 = 16384;
pub const MAX_IDS: usize = 24;
pub const NUM_FEATURES: usize = 32;

/// An OCR word in reading order, with its line.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Word {
    pub text: String,
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
    /// Index of the line it sits on, in reading order.
    pub line: usize,
}

/// Groups OCR words into lines (by vertical overlap, as `za::rows_from_words`
/// does) and returns them in reading order: lines top to bottom, words left
/// to right. A line is also split where a horizontal gap is wide enough to
/// mean a second column.
pub fn reading_order(words: &[Line]) -> Vec<Word> {
    let mut ws: Vec<&Line> = words.iter().filter(|w| w.h > 0.0 && !w.text.trim().is_empty()).collect();
    ws.sort_by(|a, b| (a.y + a.h / 2.0).total_cmp(&(b.y + b.h / 2.0)));
    let mut bands: Vec<Vec<&Line>> = Vec::new();
    for w in ws {
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
    let mut line = 0;
    for mut band in bands {
        band.sort_by(|a, b| a.x.total_cmp(&b.x));
        let mut prev_right: Option<(f32, f32)> = None;
        for w in band {
            if let Some((right, h)) = prev_right
                && w.x - right > 2.5 * h.max(w.h)
            {
                line += 1;
            }
            out.push(Word { text: w.text.clone(), x: w.x, y: w.y, w: w.w, h: w.h, line });
            prev_right = Some((w.x + w.w, w.h));
        }
        line += 1;
    }
    out
}

/// Characters per word for the character encoder (longer words are cut).
pub const MAX_CHARS: usize = 20;
/// Character ids: 0 padding, then a–z, A–Z, 0–9, a little punctuation, other.
pub const CHAR_VOCAB: usize = 76;

/// A word's characters as ids for the tagger's character encoder (see
/// [`CHAR_VOCAB`]); `train/train_tagger.py` mirrors this mapping.
pub fn char_ids(text: &str) -> [i32; MAX_CHARS] {
    const PUNCT: &str = ".,:;-/&'()#@";
    let mut out = [0i32; MAX_CHARS];
    for (k, c) in text.chars().take(MAX_CHARS).enumerate() {
        out[k] = match c {
            'a'..='z' => 1 + (c as i32 - 'a' as i32),
            'A'..='Z' => 27 + (c as i32 - 'A' as i32),
            '0'..='9' => 53 + (c as i32 - '0' as i32),
            _ => PUNCT.find(c).map_or(75, |i| 63 + i as i32),
        };
    }
    out
}

/// FNV-1a, 32-bit.
pub fn fnv1a(bytes: &[u8]) -> u32 {
    let mut h: u32 = 0x811c9dc5;
    for &b in bytes {
        h ^= b as u32;
        h = h.wrapping_mul(0x01000193);
    }
    h
}

fn bucket(s: &str) -> i32 {
    (fnv1a(s.as_bytes()) % (BUCKETS - 1) + 1) as i32
}

/// The word's shape: digits as `0`, lower-case letters `a`, capitals `A`,
/// anything else kept; runs longer than 3 cut to 3.
pub fn word_shape(s: &str) -> String {
    let mut out = String::new();
    let mut last = '\0';
    let mut run = 0;
    for c in s.chars() {
        let k = if c.is_ascii_digit() {
            '0'
        } else if c.is_lowercase() {
            'a'
        } else if c.is_uppercase() {
            'A'
        } else {
            c
        };
        run = if k == last { run + 1 } else { 1 };
        last = k;
        if run <= 3 {
            out.push(k);
        }
    }
    out
}

/// The hashed text features of a word.
pub fn text_ids(text: &str) -> Vec<i32> {
    let lower = text.to_lowercase();
    let mut ids = vec![bucket(&format!("w:{lower}")), bucket(&format!("s:{}", word_shape(text)))];
    let core: String = lower.chars().filter(|c| c.is_alphanumeric()).collect();
    if core != lower && !core.is_empty() {
        ids.push(bucket(&format!("w:{core}")));
    }
    let chars: Vec<char> = format!("^{core}$").chars().collect();
    for g in chars.windows(3) {
        if ids.len() >= MAX_IDS {
            break;
        }
        ids.push(bucket(&format!("t:{}", g.iter().collect::<String>())));
    }
    ids.truncate(MAX_IDS);
    ids
}

const MONTHS: &[&str] = &[
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "january", "february",
    "march", "april", "june", "july", "august", "september", "october", "november", "december",
];
const PROVINCE_WORDS: &[&str] = &[
    "gauteng", "western", "eastern", "northern", "cape", "kwazulu-natal", "kwazulu", "natal", "kzn", "free", "state",
    "limpopo", "mpumalanga", "north", "west", "north-west", "gp", "wc", "ec", "nc", "fs", "lp", "mp", "nw",
];
const TITLES: &[&str] = &["mr", "mrs", "ms", "miss", "dr", "prof", "mnr", "mev", "me"];
const STREET_SUFFIXES: &[&str] = &[
    "street", "st", "road", "rd", "avenue", "ave", "av", "drive", "dr", "lane", "ln", "crescent", "cres", "way",
    "close", "place", "pl", "boulevard", "blvd", "highway", "hwy", "circle", "terrace", "rylaan", "straat", "weg",
];

fn bare(text: &str) -> String {
    text.to_lowercase().trim_matches(|c: char| !c.is_alphanumeric()).to_string()
}

pub fn is_month(text: &str) -> bool {
    let b = bare(text);
    MONTHS.contains(&b.as_str())
}

/// `15/03/2026`, `2026-03-15`, `15.03.2026` and the like, as one word.
pub fn date_like(text: &str) -> bool {
    let t = text.trim_matches(|c: char| !c.is_alphanumeric());
    let parts: Vec<&str> = t.split(['/', '-', '.']).collect();
    parts.len() == 3 && parts.iter().all(|p| !p.is_empty() && p.len() <= 4 && p.chars().all(|c| c.is_ascii_alphanumeric()))
        && parts.iter().filter(|p| p.chars().all(|c| c.is_ascii_digit())).count() >= 2
}

fn currency_like(text: &str) -> bool {
    let t = text.trim_matches(|c: char| c == ',' || c == ';');
    let t = t.strip_prefix('R').unwrap_or(t);
    let t = t.trim_start_matches('-');
    let Some((int, dec)) = t.rsplit_once(['.', ',']) else { return false };
    dec.len() == 2 && dec.chars().all(|c| c.is_ascii_digit()) && !int.is_empty() && int.chars().all(|c| c.is_ascii_digit() || c == ' ' || c == ',')
}

/// The text features (`ids`, padded to [`MAX_IDS`] with 0) and the numeric
/// ones for every word of a page `width × height`, in the order given.
pub fn features(words: &[Word], width: f32, height: f32) -> (Vec<[i32; MAX_IDS]>, Vec<[f32; NUM_FEATURES]>) {
    let mut hs: Vec<f32> = words.iter().map(|w| w.h).collect();
    hs.sort_by(f32::total_cmp);
    let mh = hs.get(hs.len() / 2).copied().unwrap_or(10.0).max(1.0);
    // Line extents, for position-in-line features.
    let lines = words.iter().map(|w| w.line).max().map_or(0, |m| m + 1);
    let mut line_words: Vec<Vec<usize>> = vec![Vec::new(); lines];
    for (i, w) in words.iter().enumerate() {
        line_words[w.line].push(i);
    }
    let line_top: Vec<f32> = line_words.iter().map(|ix| ix.iter().map(|&i| words[i].y).fold(f32::MAX, f32::min)).collect();
    let line_bottom: Vec<f32> = line_words.iter().map(|ix| ix.iter().map(|&i| words[i].y + words[i].h).fold(f32::MIN, f32::max)).collect();
    let colon_before: Vec<bool> = {
        let mut v = vec![false; words.len()];
        for ix in &line_words {
            let mut seen = false;
            for &i in ix {
                v[i] = seen;
                if words[i].text.contains(':') {
                    seen = true;
                }
            }
        }
        v
    };

    let mut ids = Vec::with_capacity(words.len());
    let mut num = Vec::with_capacity(words.len());
    for (i, w) in words.iter().enumerate() {
        let mut row = [0i32; MAX_IDS];
        for (k, id) in text_ids(&w.text).into_iter().enumerate() {
            row[k] = id;
        }
        ids.push(row);

        let in_line = &line_words[w.line];
        let pos = in_line.iter().position(|&j| j == i).unwrap_or(0);
        let prev = (pos > 0).then(|| &words[in_line[pos - 1]]);
        let next = in_line.get(pos + 1).map(|&j| &words[j]);
        // The nearest line above in the same column (horizontal overlap).
        let above = (0..w.line).rev().find(|&l| {
            line_words[l].iter().any(|&j| words[j].x < w.x + w.w && words[j].x + words[j].w > w.x)
        });
        let gap_above = above.map_or(10.0, |l| ((line_top[w.line] - line_bottom[l]) / mh).clamp(0.0, 10.0));

        let t = w.text.as_str();
        let core: String = t.chars().filter(|c| c.is_alphanumeric()).collect();
        let letters = core.chars().filter(|c| c.is_alphabetic()).count();
        let digits = core.chars().filter(|c| c.is_ascii_digit()).count();
        let b = bare(t);
        let f = |v: bool| if v { 1.0 } else { 0.0 };
        let postal = core.len() == 4 && digits == 4 && core.parse::<u32>().is_ok_and(|n| n >= 1 && !(9000..9300).contains(&n));
        num.push([
            w.x / width,
            w.y / height,
            (w.x + w.w) / width,
            (w.y + w.h) / height,
            (w.x + w.w / 2.0) / width,
            (w.y + w.h / 2.0) / height,
            (w.h / mh).clamp(0.0, 4.0) / 2.0,
            ((w.w / w.h.max(1.0)).max(0.05).ln() / 3.0).clamp(-2.0, 2.0),
            (pos as f32 / 10.0).min(1.0),
            (in_line.len() as f32 / 10.0).min(1.0),
            f(pos == 0),
            f(pos + 1 == in_line.len()),
            prev.map_or(1.0, |p| ((w.x - p.x - p.w) / mh).clamp(0.0, 10.0) / 10.0),
            next.map_or(1.0, |n| ((n.x - w.x - w.w) / mh).clamp(0.0, 10.0) / 10.0),
            gap_above / 10.0,
            f(digits > 0 && letters == 0),
            f(digits > 0),
            f(letters > 0 && digits == 0),
            f(letters > 0 && core.chars().all(|c| !c.is_lowercase())),
            f(core.chars().next().is_some_and(|c| c.is_uppercase()) && core.chars().skip(1).all(|c| !c.is_uppercase())),
            (core.chars().count() as f32 / 12.0).min(1.5),
            f(core.len() == 4 && digits == 4),
            f(date_like(t)),
            f(is_month(t)),
            f(PROVINCE_WORDS.contains(&b.as_str())),
            f(currency_like(t)),
            f(t.ends_with(',')),
            f(t.contains(':')),
            f(TITLES.contains(&b.as_str())),
            f(STREET_SUFFIXES.contains(&b.as_str())),
            f(colon_before[i]),
            f(postal),
        ]);
    }
    (ids, num)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line(text: &str, x: f32, y: f32) -> Line {
        Line { text: text.into(), x, y, w: 10.0 * text.len() as f32, h: 20.0 }
    }

    /// The hash is the one the Python side checks against (train_tagger.py).
    #[test]
    fn hashing_is_stable() {
        assert_eq!(fnv1a(b""), 0x811c9dc5);
        assert_eq!(fnv1a(b"a"), 0xe40c292c);
        assert_eq!(word_shape("Rondebosch,"), "Aaaa,");
        assert_eq!(word_shape("7700"), "000");
        let ids = text_ids("Cape");
        assert_eq!(ids.len(), 2 + 4);
        assert!(ids.iter().all(|&i| i >= 1 && i < BUCKETS as i32));
    }

    #[test]
    fn reading_order_splits_columns() {
        let words = vec![line("Invoice", 600.0, 100.0), line("Mr", 50.0, 102.0), line("Nkosi", 90.0, 101.0), line("12", 50.0, 140.0)];
        let r = reading_order(&words);
        let texts: Vec<&str> = r.iter().map(|w| w.text.as_str()).collect();
        assert_eq!(texts, ["Mr", "Nkosi", "Invoice", "12"]);
        assert_eq!(r[0].line, r[1].line);
        assert_ne!(r[1].line, r[2].line);
        let (ids, num) = features(&r, 1000.0, 1400.0);
        assert_eq!(ids.len(), 4);
        assert_eq!(num[0][10], 1.0); // first in its line
    }

    #[test]
    fn char_ids_are_stable() {
        let c = char_ids("Ab9,é");
        assert_eq!(&c[..6], &[27, 2, 62, 64, 75, 0]);
    }

    #[test]
    fn shapes() {
        assert!(date_like("15/03/2026") && date_like("2026-03-15") && !date_like("12"));
        assert!(currency_like("R1,234.56") && currency_like("234.00") && !currency_like("7700"));
        assert!(is_month("March") && is_month("Mar,"));
    }
}
