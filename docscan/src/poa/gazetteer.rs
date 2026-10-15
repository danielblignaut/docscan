//! South African places and postal codes (GeoNames, CC BY 4.0; built by
//! `train/build_gazetteer.py` into `za_places.tsv`), and the correction of an
//! OCR'd city, suburb or postal code to the nearest real one.
//!
//! A correction is made only under a small edit distance *and* agreement
//! with the rest of the address: a place name is corrected only to a place
//! that has the address's postal code, and a postal code only to one that
//! belongs to the address's place. A value already in the table is left
//! alone, so a real place GeoNames lacks is never "corrected" into another
//! unless it is one slip away from a place with the same code.

use std::collections::HashMap;
use std::sync::OnceLock;

use super::verify::levenshtein;

const TSV: &str = include_str!("za_places.tsv");

pub struct Gazetteer {
    /// Normalised place name -> (printed name, postal codes).
    by_name: HashMap<String, (String, Vec<String>)>,
    /// Postal code -> normalised place names.
    by_code: HashMap<String, Vec<String>>,
}

fn key(s: &str) -> String {
    s.chars().filter(|c| c.is_alphanumeric()).flat_map(char::to_uppercase).collect()
}

pub fn gazetteer() -> &'static Gazetteer {
    static G: OnceLock<Gazetteer> = OnceLock::new();
    G.get_or_init(|| {
        let mut by_name: HashMap<String, (String, Vec<String>)> = HashMap::new();
        let mut by_code: HashMap<String, Vec<String>> = HashMap::new();
        for line in TSV.lines().filter(|l| !l.starts_with('#')) {
            let mut it = line.split('\t');
            let (Some(code), Some(place)) = (it.next(), it.next()) else { continue };
            let k = key(place);
            by_name.entry(k.clone()).or_insert_with(|| (place.to_string(), Vec::new())).1.push(code.to_string());
            by_code.entry(code.to_string()).or_default().push(k);
        }
        Gazetteer { by_name, by_code }
    })
}

/// The printed value in the case of the original (all capitals stays all capitals).
fn in_case_of(original: &str, canonical: &str) -> String {
    let letters: Vec<char> = original.chars().filter(|c| c.is_alphabetic()).collect();
    if !letters.is_empty() && letters.iter().all(|c| c.is_uppercase()) { canonical.to_uppercase() } else { canonical.to_string() }
}

impl Gazetteer {
    pub fn knows_place(&self, name: &str) -> bool {
        self.by_name.contains_key(&key(name))
    }

    pub fn knows_code(&self, code: &str) -> bool {
        self.by_code.contains_key(code)
    }

    /// Whether the place has this postal code.
    pub fn consistent(&self, name: &str, code: &str) -> bool {
        self.by_name.get(&key(name)).is_some_and(|(_, codes)| codes.iter().any(|c| c == code))
    }

    /// A misread place name corrected: the unique place one slip away (two
    /// in a name of ten letters or more) that has the postal code.
    pub fn correct_place(&self, name: &str, code: Option<&str>) -> Option<String> {
        let k = key(name);
        let code = code?;
        if k.len() < 4 || self.by_name.contains_key(&k) {
            return None;
        }
        let max = if k.len() >= 10 { 2 } else { 1 };
        let cands: Vec<&String> = self.by_code.get(code)?.iter().filter(|c| levenshtein(c, &k) <= max).collect();
        match cands.as_slice() {
            [one] => Some(in_case_of(name, &self.by_name[*one].0)),
            _ => None,
        }
    }

    /// A misread postal code corrected: the unique code one digit away that
    /// belongs to the place (city or suburb) read with it.
    pub fn correct_code(&self, code: &str, places: &[&str]) -> Option<String> {
        if code.len() != 4 || places.iter().any(|p| self.consistent(p, code)) {
            return None;
        }
        let mut cands: Vec<&String> = Vec::new();
        for p in places {
            if let Some((_, codes)) = self.by_name.get(&key(p)) {
                for c in codes {
                    if levenshtein(c, code) == 1 && !cands.contains(&c) {
                        cands.push(c);
                    }
                }
            }
        }
        match cands.as_slice() {
            [one] => Some((*one).clone()),
            _ => None,
        }
    }
}

/// Corrects the address of extracted fields in place; returns what changed.
pub fn correct(f: &mut super::Fields) -> Vec<String> {
    let g = gazetteer();
    let mut changed = Vec::new();
    let a = &mut f.address;
    // The code first, from the place names as read; then the names, from the code.
    if let Some(code) = a.postal_code.clone() {
        let places: Vec<&str> = [a.city.as_deref(), a.suburb.as_deref()].into_iter().flatten().collect();
        if let Some(c) = g.correct_code(&code, &places) {
            changed.push(format!("postal code {code} -> {c}"));
            a.postal_code = Some(c);
        }
    }
    let code = a.postal_code.clone();
    for (field, v) in [("city", &mut a.city), ("suburb", &mut a.suburb)] {
        if let Some(name) = v.clone()
            && let Some(c) = g.correct_place(&name, code.as_deref())
        {
            changed.push(format!("{field} {name} -> {c}"));
            *v = Some(c);
        }
    }
    changed
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corrects_only_with_agreement() {
        let g = gazetteer();
        assert!(g.knows_place("Rondebosch") && g.consistent("Cape Town", "7700"));
        assert_eq!(g.correct_place("RONDEBOSOH", Some("7700")).as_deref(), Some("RONDEBOSCH"));
        // Without the code, or with another place's code, nothing changes.
        assert_eq!(g.correct_place("Rondebosoh", None), None);
        assert_eq!(g.correct_place("Rondebosoh", Some("2196")), None);
        assert_eq!(g.correct_code("7790", &["Rondebosch"]).as_deref(), Some("7700"));
        assert_eq!(g.correct_code("7701", &["Rondebosch"]), None); // 7700, 7702 and 7707 are all one away
        assert_eq!(g.correct_code("7700", &["Rondebosch"]), None);
    }
}
