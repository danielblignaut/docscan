//! ICAO 9303 machine-readable zones: TD3 (passports, 2 × 44) and TD1 (ID
//! cards, 3 × 30).
//!
//! OCR confuses look-alike characters (`O`/`0`, `I`/`1`, `S`/`5`, `B`/`8`),
//! but every MRZ position is either alphabetic or numeric, so each field is
//! corrected towards its own class before the check digits are verified. A
//! result is only trusted when the check digits pass.

use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Mrz {
    pub format: &'static str,
    pub document_code: String,
    pub issuing_state: String,
    pub surname: String,
    pub given_names: String,
    pub document_number: String,
    pub nationality: String,
    pub date_of_birth: String,
    pub sex: String,
    pub date_of_expiry: String,
    pub optional_data: String,
    pub checks: MrzChecks,
    pub lines: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MrzChecks {
    pub document_number: bool,
    pub date_of_birth: bool,
    pub date_of_expiry: bool,
    pub optional_data: bool,
    pub composite: bool,
}

impl MrzChecks {
    pub fn all(&self) -> bool {
        self.document_number
            && self.date_of_birth
            && self.date_of_expiry
            && self.optional_data
            && self.composite
    }
}

pub fn char_value(c: char) -> u32 {
    match c {
        '0'..='9' => c as u32 - '0' as u32,
        'A'..='Z' => c as u32 - 'A' as u32 + 10,
        _ => 0,
    }
}

pub fn check_digit(field: &str) -> char {
    const WEIGHTS: [u32; 3] = [7, 3, 1];
    let sum: u32 = field
        .chars()
        .enumerate()
        .map(|(i, c)| char_value(c) * WEIGHTS[i % 3])
        .sum();
    char::from_digit(sum % 10, 10).unwrap()
}

fn verify(field: &str, check: char) -> bool {
    // An unused optional field may carry `<` as its check digit.
    (check == '<' && field.chars().all(|c| c == '<')) || check_digit(field) == check
}

fn to_digit_class(c: char) -> char {
    match c {
        'O' | 'Q' | 'D' | 'U' => '0',
        'I' | 'L' | 'T' | 'J' => '1',
        'Z' => '2',
        'A' => '4',
        'S' => '5',
        'G' | 'b' => '6',
        'B' => '8',
        'g' => '9',
        _ => c,
    }
}

fn to_alpha_class(c: char) -> char {
    match c {
        '0' => 'O',
        '1' => 'I',
        '2' => 'Z',
        '4' => 'A',
        '5' => 'S',
        '6' => 'G',
        '8' => 'B',
        _ => c,
    }
}

fn digits(s: &str) -> String {
    s.chars().map(to_digit_class).collect()
}

fn alpha(s: &str) -> String {
    s.chars().map(to_alpha_class).collect()
}

/// Upper-cases an OCR'd line, maps the usual stand-ins for the filler, and
/// drops anything that cannot appear in an MRZ.
pub fn clean_line(raw: &str) -> String {
    raw.chars()
        .filter(|c| !c.is_whitespace())
        .map(|c| match c {
            '«' | '‹' | '(' | '[' | '{' => '<',
            _ => c.to_ascii_uppercase(),
        })
        .filter(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || *c == '<')
        .collect()
}

/// Whether a line of OCR output plausibly belongs to an MRZ.
pub fn looks_like_mrz(raw: &str) -> bool {
    let line = clean_line(raw);
    let digits = line.chars().filter(|c| c.is_ascii_digit()).count();
    line.len() >= 28 && (line.contains('<') || digits >= 10)
}

/// Brings a recognised line to the format's length. The recogniser most
/// often gains or drops a `<` inside a long filler run, which shifts every
/// field after it, the check digits at the end included; so a line off by
/// one or two is corrected inside its longest filler run (three or more
/// fillers) when it has one, and truncated or padded at the end otherwise.
fn fit(line: &str, len: usize) -> String {
    let mut chars: Vec<char> = line.chars().collect();
    let off = chars.len().abs_diff(len);
    if (1..=2).contains(&off) {
        // The longest run of `<`, as (start, length).
        let mut best = (0, 0);
        let mut i = 0;
        while i < chars.len() {
            if chars[i] == '<' {
                let start = i;
                while i < chars.len() && chars[i] == '<' {
                    i += 1;
                }
                if i - start > best.1 {
                    best = (start, i - start);
                }
            } else {
                i += 1;
            }
        }
        if best.1 >= 3 {
            if chars.len() > len {
                chars.drain(best.0..best.0 + off);
            } else {
                for _ in 0..off {
                    chars.insert(best.0, '<');
                }
            }
        }
    }
    let mut s: String = chars.into_iter().take(len).collect();
    while s.len() < len {
        s.push('<');
    }
    s
}

/// Splits a name field whose `<<` (surname from given names) the recogniser
/// read as a single `<`. Only when the field holds no `<<` at all, and only
/// at a `<` where the words before and after are both printed elsewhere on
/// the page as lines of their own (the surname and given-name fields).
pub fn split_names_by_print(m: &mut Mrz, printed: &[String]) {
    let (line_idx, start, len) = match m.format {
        "TD3" => (0, 5, 44),
        _ => (2, 0, 30),
    };
    let Some(line) = m.lines.get(line_idx).cloned() else { return };
    let field: String = line.chars().skip(start).collect();
    let body = field.trim_end_matches('<');
    if body.contains("<<") || !body.contains('<') {
        return;
    }
    let norm = |s: &str| s.split(|c: char| !c.is_ascii_alphabetic()).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ").to_uppercase();
    let printed: std::collections::HashSet<String> = printed.iter().map(|l| norm(l)).collect();
    let tokens: Vec<&str> = body.split('<').collect();
    for k in 1..tokens.len() {
        let (surname, given) = (tokens[..k].join(" "), tokens[k..].join(" "));
        if printed.contains(&surname) && printed.contains(&given) {
            let fixed = format!("{}<<{}", tokens[..k].join("<"), tokens[k..].join("<"));
            m.surname = surname;
            m.given_names = given;
            m.lines[line_idx] = fit(&format!("{}{}", &line[..start], fixed), len);
            return;
        }
    }
}

fn names(field: &str) -> (String, String) {
    let field = alpha(field);
    let mut parts = field.splitn(2, "<<");
    let surname = parts.next().unwrap_or("").replace('<', " ").trim().to_string();
    let given = parts.next().unwrap_or("").replace('<', " ");
    let given = given.split_whitespace().collect::<Vec<_>>().join(" ");
    (surname, given)
}

fn strip_filler(s: &str) -> String {
    s.trim_end_matches('<').replace('<', " ")
}

/// Parses a TD3 MRZ from two cleaned lines.
pub fn parse_td3(l1: &str, l2: &str) -> Option<Mrz> {
    if l1.len() < 40 || !(42..=46).contains(&l2.len()) {
        return None;
    }
    let l1 = fit(l1, 44);
    let l2 = fit(l2, 44);
    if !l1.starts_with('P') {
        return None;
    }
    let document_code = alpha(&l1[0..2]);
    let issuing_state = alpha(&l1[2..5]);
    let (surname, given_names) = names(&l1[5..44]);

    // Document numbers are alphanumeric; trust the check digit to choose.
    let doc_raw = &l2[0..9];
    let doc_check = to_digit_class(l2.as_bytes()[9] as char);
    let document_number = best_alnum(doc_raw, doc_check);
    let nationality = alpha(&l2[10..13]);
    let dob = digits(&l2[13..19]);
    let dob_check = to_digit_class(l2.as_bytes()[19] as char);
    let sex = match l2.as_bytes()[20] as char {
        'M' | 'F' | '<' | 'X' => (l2.as_bytes()[20] as char).to_string(),
        'N' | 'H' => "M".to_string(),
        'E' | 'P' => "F".to_string(),
        other => other.to_string(),
    };
    let expiry = digits(&l2[21..27]);
    let expiry_check = to_digit_class(l2.as_bytes()[27] as char);
    let optional = l2[28..42].to_string();
    let optional_check = l2.as_bytes()[42] as char;
    let optional_check = if optional_check == '<' { '<' } else { to_digit_class(optional_check) };
    let composite_check = to_digit_class(l2.as_bytes()[43] as char);

    let composite_field = format!(
        "{}{}{}{}{}{}{}{}",
        document_number, doc_check, dob, dob_check, expiry, expiry_check, optional, optional_check
    );
    let checks = MrzChecks {
        document_number: verify(&document_number, doc_check),
        date_of_birth: verify(&dob, dob_check),
        date_of_expiry: verify(&expiry, expiry_check),
        optional_data: verify(&optional, optional_check),
        composite: verify(&composite_field, composite_check),
    };
    let fixed_l2 = format!(
        "{}{}{}{}{}{}{}{}{}{}{}",
        document_number,
        doc_check,
        nationality,
        dob,
        dob_check,
        sex,
        expiry,
        expiry_check,
        optional,
        optional_check,
        composite_check
    );
    Some(Mrz {
        format: "TD3",
        document_code: strip_filler(&document_code),
        issuing_state,
        surname,
        given_names,
        document_number: strip_filler(&document_number),
        nationality,
        date_of_birth: dob,
        sex,
        date_of_expiry: expiry,
        optional_data: strip_filler(&optional),
        checks,
        lines: vec![l1, fixed_l2],
    })
}

/// Parses a TD1 MRZ from three cleaned lines.
pub fn parse_td1(l1: &str, l2: &str, l3: &str) -> Option<Mrz> {
    if !(28..=32).contains(&l1.len()) || !(28..=32).contains(&l2.len()) || l3.len() < 20 {
        return None;
    }
    let (l1, l2, l3) = (fit(l1, 30), fit(l2, 30), fit(l3, 30));
    if !matches!(l1.as_bytes()[0], b'I' | b'A' | b'C') {
        return None;
    }
    let document_code = alpha(&l1[0..2]);
    let issuing_state = alpha(&l1[2..5]);
    let doc_check = to_digit_class(l1.as_bytes()[14] as char);
    let document_number = best_alnum(&l1[5..14], doc_check);
    let optional1 = l1[15..30].to_string();
    let dob = digits(&l2[0..6]);
    let dob_check = to_digit_class(l2.as_bytes()[6] as char);
    let sex = (l2.as_bytes()[7] as char).to_string();
    let expiry = digits(&l2[8..14]);
    let expiry_check = to_digit_class(l2.as_bytes()[14] as char);
    let nationality = alpha(&l2[15..18]);
    let optional2 = l2[18..29].to_string();
    let composite_check = to_digit_class(l2.as_bytes()[29] as char);
    let composite_field = format!(
        "{}{}{}{}{}{}{}{}",
        document_number, doc_check, optional1, dob, dob_check, expiry, expiry_check, optional2
    );
    let (surname, given_names) = names(&l3);
    let checks = MrzChecks {
        document_number: verify(&document_number, doc_check),
        date_of_birth: verify(&dob, dob_check),
        date_of_expiry: verify(&expiry, expiry_check),
        optional_data: true,
        composite: verify(&composite_field, composite_check),
    };
    Some(Mrz {
        format: "TD1",
        document_code: strip_filler(&document_code),
        issuing_state,
        surname,
        given_names,
        document_number: strip_filler(&document_number),
        nationality,
        date_of_birth: dob,
        sex,
        date_of_expiry: expiry,
        optional_data: strip_filler(&format!("{optional1}{optional2}")),
        checks,
        lines: vec![l1, l2, l3],
    })
}

/// A document number mixes letters and digits, so neither class can be
/// forced. Try the OCR reading, then the all-digit and all-letter readings
/// per ambiguous position, and keep the one the check digit accepts.
fn best_alnum(raw: &str, check: char) -> String {
    if check_digit(raw) == check {
        return raw.to_string();
    }
    let chars: Vec<char> = raw.chars().collect();
    let ambiguous: Vec<usize> = chars
        .iter()
        .enumerate()
        .filter(|(_, c)| to_digit_class(**c) != **c || to_alpha_class(**c) != **c)
        .map(|(i, _)| i)
        .take(8)
        .collect();
    for mask in 1u32..(1 << ambiguous.len()) {
        let mut candidate = chars.clone();
        for (bit, &i) in ambiguous.iter().enumerate() {
            if mask & (1 << bit) != 0 {
                let c = chars[i];
                candidate[i] = if to_digit_class(c) != c { to_digit_class(c) } else { to_alpha_class(c) };
            }
        }
        let s: String = candidate.into_iter().collect();
        if check_digit(&s) == check {
            return s;
        }
    }
    raw.to_string()
}

/// Letters the recogniser substitutes for a lone `<` between two names.
const FILLER_LOOKALIKES: &[char] = &['S', 'K', 'C', 'E', 'L', 'X', 'Z'];

/// Re-segments the name field using words printed elsewhere on the page.
///
/// Check digits do not cover names, and a recogniser reading OCR-B tends to
/// turn a lone `<` between two names into a letter (`UK<SPECIMEN` becomes
/// `UKSSPECIMEN`). A dynamic programme chooses which look-alike letters were
/// fillers so that the most letters fall inside words also printed on the
/// page, and the repair is kept only when it explains most of the field.
pub fn repair_names(m: &mut Mrz, vocab: &std::collections::HashSet<String>) {
    let (line_idx, start) = match m.format {
        "TD3" => (0, 5),
        _ => (2, 0),
    };
    let Some(line) = m.lines.get(line_idx).cloned() else { return };
    let field: Vec<char> = line.chars().skip(start).collect();
    let end = field.iter().rposition(|c| *c != '<').map_or(0, |i| i + 1);
    let body = &field[..end];
    if body.is_empty() || vocab.is_empty() {
        return;
    }
    let n = body.len();
    let words: Vec<Vec<char>> = vocab.iter().map(|w| w.chars().collect()).collect();
    #[derive(Clone, Copy)]
    enum Step {
        Sep,
        /// A vocabulary word, then (`true`) a separator in the text, or
        /// (`false`) one the recogniser dropped, before the next word.
        Word(usize, bool),
        /// Unknown letters up to this index, then a real `<` unless at the end.
        Literal(usize),
    }
    // best[i]: (letters inside vocabulary words, -repairs) for body[i..],
    // where a token starts at i. A repair (a look-alike letter read as `<`,
    // or a `<` the recogniser dropped) is allowed only next to a vocabulary
    // word: unknown letters are never split, so a real name the printed text
    // misread is left alone.
    let mut best: Vec<((i32, i32), Step)> = vec![((0, 0), Step::Sep); n + 1];
    for i in (0..n).rev() {
        let mut choice: Option<((i32, i32), Step)> = None;
        let mut offer = |score: (i32, i32), step: Step| {
            if choice.is_none_or(|(s, _)| score > s) {
                choice = Some((score, step));
            }
        };
        let is_word = |j: usize| j < n && matches!(best[j].1, Step::Word(..));
        // A real `<` (or a look-alike, after a word) at the field's start is
        // impossible: names begin with a letter.
        if i > 0 {
            let prev_sep = matches!(body[i - 1], '<') || FILLER_LOOKALIKES.contains(&body[i - 1]);
            let cost = match body[i] {
                '<' => Some(0),
                c if FILLER_LOOKALIKES.contains(&c) && prev_sep && is_word(i + 1) => Some(1),
                _ => None,
            };
            if let Some(cost) = cost {
                let rest = best[i + 1].0;
                offer((rest.0, rest.1 - cost), Step::Sep);
            }
        }
        for (wi, w) in words.iter().enumerate() {
            let len = w.len();
            if i + len > n {
                continue;
            }
            // The printed text is read less reliably than the MRZ: a word of
            // five letters or more may differ by one letter, at a point's cost.
            let mismatches = body[i..i + len].iter().zip(w).filter(|(a, b)| a != b).count();
            let gain = match mismatches {
                0 => len as i32,
                1 if len >= 5 => len as i32 - 1,
                _ => continue,
            };
            let j = i + len;
            if j == n {
                offer((gain, 0), Step::Word(wi, true));
                continue;
            }
            let c = body[j];
            // A look-alike letter is a separator when another separator, a
            // word, or the end of the names follows it.
            let sep_next = j + 1 == n || is_word(j + 1) || matches!(best[j + 1].1, Step::Sep);
            if c == '<' || (FILLER_LOOKALIKES.contains(&c) && sep_next) {
                let rest = best[j + 1].0;
                offer((rest.0 + gain, rest.1 - i32::from(c != '<')), Step::Word(wi, true));
            }
            if is_word(j) {
                let rest = best[j].0;
                offer((rest.0 + gain, rest.1 - 1), Step::Word(wi, false));
            }
        }
        if body[i] != '<' {
            // Unknown letters run to the next real `<` (or the end).
            let j = (i..n).find(|&k| body[k] == '<').unwrap_or(n);
            let rest = if j == n { (0, 0) } else { best[j + 1].0 };
            offer(rest, Step::Literal(j));
        }
        best[i] = choice.unwrap_or(((0, 0), Step::Literal(n)));
    }
    let letters = body.iter().filter(|c| **c != '<').count() as i32;
    let matched = (best[0].0).0;
    if (matched as f32) < letters as f32 * 0.6 {
        return;
    }
    let mut out = String::new();
    let mut i = 0;
    while i < n {
        match best[i].1 {
            Step::Sep => {
                out.push('<');
                i += 1;
            }
            Step::Word(wi, consumed) => {
                // Keep the MRZ's own letters: the vocabulary only places the separators.
                let len = words[wi].len();
                out.extend(&body[i..i + len]);
                i += len;
                if i < n {
                    out.push('<');
                    if consumed {
                        i += 1;
                    }
                }
            }
            Step::Literal(j) => {
                out.extend(&body[i..j]);
                i = j;
                if i < n {
                    out.push('<');
                    i += 1;
                }
            }
        }
    }
    let repaired: String = out.chars().chain(field[end..].iter().copied()).collect();
    let (surname, given) = names(&repaired);
    m.surname = surname;
    m.given_names = given;
    m.lines[line_idx] = format!("{}{}", &line[..start], repaired);
}

/// Finds and parses an MRZ among recognised text lines, in reading order.
pub fn find_mrz(lines: &[String]) -> Option<Mrz> {
    let cleaned: Vec<String> = lines.iter().map(|l| clean_line(l)).collect();
    let mut best: Option<Mrz> = None;
    let mut consider = |m: Mrz| {
        let score = |m: &Mrz| {
            let c = &m.checks;
            [c.document_number, c.date_of_birth, c.date_of_expiry, c.optional_data, c.composite]
                .iter()
                .filter(|b| **b)
                .count()
        };
        if best.as_ref().is_none_or(|b| score(&m) > score(b)) {
            best = Some(m);
        }
    };
    for i in 0..cleaned.len() {
        if i + 1 < cleaned.len()
            && let Some(m) = parse_td3(&cleaned[i], &cleaned[i + 1])
        {
            consider(m);
        }
        if i + 2 < cleaned.len()
            && let Some(m) = parse_td1(&cleaned[i], &cleaned[i + 1], &cleaned[i + 2])
        {
            consider(m);
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;

    // ICAO 9303 part 4 specimen.
    const L1: &str = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<";
    const L2: &str = "L898902C36UTO7408122F1204159ZE184226B<<<<<10";

    #[test]
    fn icao_specimen_passes() {
        let m = parse_td3(L1, L2).unwrap();
        assert!(m.checks.all(), "{:?}", m.checks);
        assert_eq!(m.surname, "ERIKSSON");
        assert_eq!(m.given_names, "ANNA MARIA");
        assert_eq!(m.document_number, "L898902C3");
        assert_eq!(m.date_of_birth, "740812");
    }

    #[test]
    fn ocr_confusions_are_corrected() {
        let l2 = "L898902C36UT07408I22F12O4159ZE184226B<<<<<1O";
        let m = parse_td3(&clean_line(L1), &clean_line(l2)).unwrap();
        assert!(m.checks.all(), "{:?}", m.checks);
        assert_eq!(m.nationality, "UTO");
    }

    #[test]
    fn names_repaired_from_printed_words() {
        let mut m = parse_td3("PSGBRUKSSPECIMENSSANGELASZOE<<<<<<<<<<<<<<<<", "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06").unwrap();
        let vocab = ["UK", "SPECIMEN", "ANGELA", "ZOE", "BRITISH", "CITIZEN"].iter().map(|s| s.to_string()).collect();
        repair_names(&mut m, &vocab);
        assert_eq!(m.surname, "UK SPECIMEN");
        assert_eq!(m.given_names, "ANGELA ZOE");
    }

    #[test]
    fn a_filler_gained_or_lost_keeps_the_check_digits() {
        let l2 = "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06";
        let long = "9250764733GBR8812049F3003264<<<<<<<<<<<<<<<06";
        let short = "9250764733GBR8812049F3003264<<<<<<<<<<<<<06";
        let l1 = "P<GBRUK<SPECIMEN<<ANGELA<ZOE<<<<<<<<<<<<<<<<";
        for l in [l2, long, short] {
            let m = parse_td3(l1, l).unwrap();
            assert!(m.checks.all(), "{l}: {:?}", m.checks);
        }
    }

    #[test]
    fn a_lost_double_filler_is_restored_from_the_printed_names() {
        let mut m = parse_td3("P<GBRUK<SPECIMEN<ANGELA<ZOE<<<<<<<<<<<<<<<<<", "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06").unwrap();
        assert_eq!(m.given_names, "");
        let printed = ["Surname / Nom", "UK SPECIMEN", "Given names / Prénoms", "ANGELA ZOE"].map(String::from);
        split_names_by_print(&mut m, &printed);
        assert_eq!((m.surname.as_str(), m.given_names.as_str()), ("UK SPECIMEN", "ANGELA ZOE"));
        assert_eq!(m.lines[0], "P<GBRUK<SPECIMEN<<ANGELA<ZOE<<<<<<<<<<<<<<<<");
        // Without both halves in print, nothing is guessed.
        let mut m2 = parse_td3("P<GBRUK<SPECIMEN<ANGELA<ZOE<<<<<<<<<<<<<<<<<", "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06").unwrap();
        split_names_by_print(&mut m2, &["UK SPECIMEN".to_string()]);
        assert_eq!(m2.given_names, "");
    }

    fn vocab(words: &[&str]) -> std::collections::HashSet<String> {
        words.iter().map(|s| s.to_string()).collect()
    }

    /// A `<` the recogniser dropped between two given names is put back.
    #[test]
    fn dropped_separator_is_restored() {
        let mut m = parse_td3("PAZAFSPECIMEN<<JOHANNESPIETER<<<<<<<<<<<<<<<", "A098765432ZAF8807098M3201314880709932108<<26").unwrap();
        repair_names(&mut m, &vocab(&["SPECIMEN", "JOHANNES", "PIETER", "SOUTH", "AFRICAN"]));
        assert_eq!(m.surname, "SPECIMEN");
        assert_eq!(m.given_names, "JOHANNES PIETER");
    }

    /// A correct name is never cut: a misread printed word (`ANGE` for
    /// `LANGE`) must not turn the name's first letter into a separator.
    #[test]
    fn correct_name_survives_misread_print() {
        let mut m = parse_td3("PAZAFLANGE<<THANDI<NOMSA<<<<<<<<<<<<<<<<<<<<", "A098765432ZAF8807098F3201314880709932108<<26").unwrap();
        repair_names(&mut m, &vocab(&["ANGE", "THANDI", "NOMSA"]));
        assert_eq!(m.surname, "LANGE");
        assert_eq!(m.given_names, "THANDI NOMSA");
    }

    /// The printed name misread by a letter still places the separator, and
    /// the MRZ's own spelling is kept.
    #[test]
    fn misread_print_still_segments() {
        let mut m = parse_td3("PAZAFSPECIMEN<<JOHANNESPIETER<<<<<<<<<<<<<<<", "A098765432ZAF8807098M3201314880709932108<<26").unwrap();
        repair_names(&mut m, &vocab(&["SPECIMEN", "JOHANNES", "PIETEP"]));
        assert_eq!(m.given_names, "JOHANNES PIETER");
    }

    /// A trailing filler read as a letter after the last name is dropped.
    #[test]
    fn trailing_filler_lookalike() {
        let mut m = parse_td3("P<ZAFSPECIMEN<NKOSI<<THABO<SIPHOK<<<<<<<<<<<", "A098765432ZAF8807098M3201314880709932108<<26").unwrap();
        repair_names(&mut m, &vocab(&["SPECIMEN", "NKOSI", "THABO", "SIPHO"]));
        assert_eq!(m.given_names, "THABO SIPHO");
    }

    /// A name with a vocabulary word as its prefix is not split.
    #[test]
    fn longer_name_is_not_split() {
        let mut m = parse_td3("P<GBRSMITH<<DANIELLE<<<<<<<<<<<<<<<<<<<<<<<<", "9250764733GBR8812049F3003264<<<<<<<<<<<<<<06").unwrap();
        repair_names(&mut m, &vocab(&["SMITH", "DANIEL"]));
        assert_eq!(m.given_names, "DANIELLE");
    }

    #[test]
    fn td1_specimen_passes() {
        let m = parse_td1(
            "I<UTOD231458907<<<<<<<<<<<<<<<",
            "7408122F1204159UTO<<<<<<<<<<<6",
            "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
        )
        .unwrap();
        assert!(m.checks.all(), "{:?}", m.checks);
    }
}
