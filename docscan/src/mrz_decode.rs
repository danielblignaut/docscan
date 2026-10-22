//! Reading an MRZ line from the recogniser's own output, with the layout's
//! rules applied while decoding.
//!
//! ocrs decodes each line greedily into free text, which leaves the MRZ
//! reader two kinds of error to undo afterwards: look-alike characters (`O`
//! for `0` in a date) and a `<` gained or lost in a filler run, which shifts
//! every field after it. Both are avoidable when the decoder knows the line:
//! ICAO 9303 fixes each line's length and, at every position, whether a
//! digit, a letter, a filler or a sex code may stand there. So the line is
//! decoded as the best CTC path that emits exactly the template's number of
//! characters, each from its position's set (a Viterbi search over frame ×
//! position), and the template that explains the line best wins. Then each
//! check digit that fails is repaired, if possible, by the cheapest
//! substitution among the recogniser's next-best characters at the
//! positions it covers; a repair is only kept when it makes the digit pass.

use rten_tensor::prelude::*;
use rten_tensor::{NdTensor, NdTensorView};

/// The MRZ alphabet, in class order (class 0 is the CTC blank).
pub const MRZ: &str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<";
const N: usize = 37;
const FILLER: usize = 36;

fn idx(c: char) -> Option<usize> {
    MRZ.find(c)
}

/// ocrs's recogniser alphabet (class `i + 1` is character `i`; class 0 the blank).
const OCRS_ALPHABET: &str = " 0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~EABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

/// Maps the recogniser's log-probabilities (`[T, classes]`) to the MRZ
/// alphabet: `[T, 1 + 37]`, blank first. A character's lower-case form and
/// the stand-ins the recogniser uses for `<` (`«`, `(`, `[`, `{`) count
/// towards it; every other class is dropped (renormalised away).
pub fn to_mrz_classes(lp: NdTensorView<f32, 2>) -> NdTensor<f32, 2> {
    let [t, c] = lp.shape();
    // Source class -> MRZ class (1-based; 0 blank).
    let mut map: Vec<Option<usize>> = vec![None; c];
    map[0] = Some(0);
    for (i, ch) in OCRS_ALPHABET.chars().enumerate() {
        if i + 1 >= c {
            break;
        }
        let target = match ch {
            '(' | '[' | '{' => Some(FILLER),
            _ => idx(ch.to_ascii_uppercase()),
        };
        map[i + 1] = target.map(|k| k + 1);
    }
    let mut out = NdTensor::full([t, N + 1], f32::NEG_INFINITY);
    for ti in 0..t {
        let mut acc = [f32::NEG_INFINITY; N + 1];
        for ci in 0..c {
            if let Some(k) = map[ci] {
                let v = lp[[ti, ci]];
                let a = acc[k];
                acc[k] = if a == f32::NEG_INFINITY { v } else { a.max(v) + (-(a - v).abs()).exp().ln_1p() };
            }
        }
        let total = acc.iter().fold(f32::NEG_INFINITY, |a, &v| if a == f32::NEG_INFINITY { v } else { a.max(v) + (-(a - v).abs()).exp().ln_1p() });
        for k in 0..=N {
            out[[ti, k]] = acc[k] - total;
        }
    }
    out
}

/// The recogniser's output (`[T, classes]`, ocrs's alphabet) decoded
/// greedily into free text, as ocrs would read it.
pub fn greedy(lp: NdTensorView<f32, 2>) -> String {
    let alphabet: Vec<char> = OCRS_ALPHABET.chars().collect();
    let [t, c] = lp.shape();
    let mut out = String::new();
    let mut last = 0;
    for ti in 0..t {
        let best = (0..c).max_by(|&a, &b| lp[[ti, a]].total_cmp(&lp[[ti, b]])).unwrap_or(0);
        if best != last && best > 0 && best <= alphabet.len() {
            out.push(alphabet[best - 1]);
        }
        last = best;
    }
    out
}

/// Sets of MRZ characters, as bit masks over [`MRZ`].
const DIGITS: u64 = (1 << 10) - 1;
const LETTERS: u64 = ((1 << 26) - 1) << 10;
const F: u64 = 1 << FILLER;
const ALNUM_F: u64 = DIGITS | LETTERS | F;
const ALPHA_F: u64 = LETTERS | F;
fn one(c: char) -> u64 {
    1 << idx(c).unwrap()
}

/// A line layout: each position's allowed characters.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Template {
    Td3Line1,
    Td3Line2,
    Td1Line1,
    Td1Line2,
    Td1Line3,
}

impl Template {
    pub const ALL: [Template; 5] = [Template::Td3Line1, Template::Td3Line2, Template::Td1Line1, Template::Td1Line2, Template::Td1Line3];

    pub fn len(self) -> usize {
        match self {
            Template::Td3Line1 | Template::Td3Line2 => 44,
            _ => 30,
        }
    }

    fn allowed(self) -> Vec<u64> {
        let sex = one('M') | one('F') | one('X') | F;
        let check = DIGITS;
        let mut v = vec![ALNUM_F; self.len()];
        let set = |v: &mut Vec<u64>, r: std::ops::Range<usize>, m: u64| v[r].iter_mut().for_each(|x| *x = m);
        match self {
            Template::Td3Line1 => {
                v[0] = one('P');
                set(&mut v, 1..44, ALPHA_F);
            }
            Template::Td3Line2 => {
                set(&mut v, 0..9, ALNUM_F);
                v[9] = check;
                set(&mut v, 10..13, ALPHA_F);
                set(&mut v, 13..19, DIGITS);
                v[19] = check;
                v[20] = sex;
                set(&mut v, 21..27, DIGITS);
                v[27] = check;
                set(&mut v, 28..42, ALNUM_F);
                v[42] = check | F;
                v[43] = check;
            }
            Template::Td1Line1 => {
                v[0] = one('I') | one('A') | one('C');
                set(&mut v, 1..5, ALPHA_F);
                set(&mut v, 5..14, ALNUM_F);
                v[14] = check | F;
                set(&mut v, 15..30, ALNUM_F);
            }
            Template::Td1Line2 => {
                set(&mut v, 0..6, DIGITS);
                v[6] = check;
                v[7] = sex;
                set(&mut v, 8..14, DIGITS);
                v[14] = check;
                set(&mut v, 15..18, ALPHA_F);
                set(&mut v, 18..29, ALNUM_F);
                v[29] = check;
            }
            Template::Td1Line3 => set(&mut v, 0..30, ALPHA_F),
        }
        v
    }

    /// The check-digit fields within the line: (field positions, check position).
    fn checks(self) -> Vec<(Vec<usize>, usize)> {
        match self {
            Template::Td3Line2 => {
                let mut composite: Vec<usize> = (0..10).collect();
                composite.extend(13..20);
                composite.extend(21..43);
                vec![((0..9).collect(), 9), ((13..19).collect(), 19), ((21..27).collect(), 27), ((28..42).collect(), 42), (composite, 43)]
            }
            Template::Td1Line1 => vec![((5..14).collect(), 14)],
            Template::Td1Line2 => vec![((0..6).collect(), 6), ((8..14).collect(), 14)],
            _ => vec![],
        }
    }
}

/// A decoded line: its text, the Viterbi path's log-probability, and per
/// position the best log-probability of each allowed character over the
/// frames the path gave that position.
#[derive(Clone, Debug)]
pub struct Decoded {
    pub template: Template,
    pub text: String,
    pub score: f32,
    alts: Vec<Vec<(usize, f32)>>,
}

/// The best CTC path through `lp` (`[T, 1 + 37]`, from [`to_mrz_classes`])
/// that emits exactly `template.len()` characters from their positions' sets.
pub fn decode(lp: NdTensorView<f32, 2>, template: Template) -> Option<Decoded> {
    let allowed = template.allowed();
    let l = allowed.len();
    let [t, _] = lp.shape();
    if t < l {
        return None;
    }
    const NEG: f32 = f32::NEG_INFINITY;
    // States: `k * S` is the blank after k characters; `k * S + 1 + c` is
    // the k-th character (1-based), c, being emitted.
    const S: usize = N + 1;
    let states = (l + 1) * S;
    let mut cur = vec![NEG; states];
    let mut back = vec![u16::MAX; t * states];
    cur[0] = lp[[0, 0]];
    for c in 0..N {
        if allowed[0] & (1 << c) != 0 {
            cur[S + 1 + c] = lp[[0, c + 1]];
        }
    }
    let mut next = vec![NEG; states];
    for ti in 1..t {
        next.iter_mut().for_each(|v| *v = NEG);
        let bk = &mut back[ti * states..(ti + 1) * states];
        for k in 0..=l {
            // Blank after k: from itself or from the k-th character.
            let base = k * S;
            let (mut v, mut from) = (cur[base], base);
            if k >= 1 {
                for c in 0..N {
                    if cur[base + 1 + c] > v {
                        v = cur[base + 1 + c];
                        from = base + 1 + c;
                    }
                }
            }
            if v > NEG {
                next[base] = v + lp[[ti, 0]];
                bk[base] = from as u16;
            }
            if k == 0 {
                continue;
            }
            // The k-th character c: stay, or begin after the blank following
            // k-1, or directly after a different (k-1)-th character.
            let prev = (k - 1) * S;
            let (mut b1, mut b1c, mut b2, mut b2c) = (NEG, 0, NEG, 0);
            if k >= 2 {
                for c in 0..N {
                    let v = cur[prev + 1 + c];
                    if v > b1 {
                        (b2, b2c) = (b1, b1c);
                        (b1, b1c) = (v, c);
                    } else if v > b2 {
                        (b2, b2c) = (v, c);
                    }
                }
            }
            for c in 0..N {
                if allowed[k - 1] & (1 << c) == 0 {
                    continue;
                }
                let me = base + 1 + c;
                let (mut v, mut from) = (cur[me], me);
                if cur[prev] > v {
                    v = cur[prev];
                    from = prev;
                }
                let (o, oc) = if b1c != c { (b1, b1c) } else { (b2, b2c) };
                if o > v {
                    v = o;
                    from = prev + 1 + oc;
                }
                if v > NEG {
                    next[me] = v + lp[[ti, c + 1]];
                    bk[me] = from as u16;
                }
            }
        }
        std::mem::swap(&mut cur, &mut next);
    }
    // End in the blank after the last character, or on it.
    let end = l * S;
    let mut state = end;
    for c in 0..N {
        if cur[end + 1 + c] > cur[state] {
            state = end + 1 + c;
        }
    }
    let score = cur[state];
    if score == NEG {
        return None;
    }
    // Backtrack: each position's character and the frames it held.
    let mut chars = vec![0usize; l];
    let mut spans = vec![(usize::MAX, 0usize); l];
    for ti in (0..t).rev() {
        let (k, r) = (state / S, state % S);
        if r > 0 {
            chars[k - 1] = r - 1;
            let sp = &mut spans[k - 1];
            sp.0 = sp.0.min(ti);
            sp.1 = sp.1.max(ti);
        }
        if ti > 0 {
            state = back[ti * states + state] as usize;
        }
    }
    let alts = (0..l)
        .map(|k| {
            let (a, z) = spans[k];
            let mut v: Vec<(usize, f32)> = (0..N)
                .filter(|c| allowed[k] & (1 << c) != 0)
                .map(|c| (c, (a..=z).map(|f| lp[[f, c + 1]]).fold(NEG, f32::max)))
                .collect();
            v.sort_by(|x, y| y.1.total_cmp(&x.1));
            v.truncate(4);
            v
        })
        .collect();
    let text = chars.iter().map(|&c| MRZ.as_bytes()[c] as char).collect();
    Some(Decoded { template, text, score, alts })
}

fn check_digit(chars: &[usize]) -> usize {
    const W: [usize; 3] = [7, 3, 1];
    chars.iter().enumerate().map(|(i, &c)| if c == FILLER { 0 } else { c } * W[i % 3]).sum::<usize>() % 10
}

fn passes(chars: &[usize], field: &[usize], check: usize) -> bool {
    let f: Vec<usize> = field.iter().map(|&i| chars[i]).collect();
    let c = chars[check];
    (c == FILLER && f.iter().all(|&x| x == FILLER)) || (c < 10 && check_digit(&f) == c)
}

/// Repairs failing check digits with the next-best characters: for each
/// failing field (in order, the composite last), the cheapest change of one
/// or two positions (cost: how much less likely the replacement was) that
/// makes it pass without breaking a field that already passes. Gives up on
/// a field when no change within `max_cost` (nats) does it.
pub fn repair(d: &mut Decoded, max_cost: f32) {
    let checks = d.template.checks();
    if checks.is_empty() {
        return;
    }
    let mut chars: Vec<usize> = d.text.chars().map(|c| idx(c).unwrap()).collect();
    let all_ok = |chars: &[usize], upto: usize| checks[..upto].iter().all(|(f, c)| passes(chars, f, *c));
    for (n, (field, check)) in checks.iter().enumerate() {
        if passes(&chars, field, *check) {
            continue;
        }
        let mut positions: Vec<usize> = field.clone();
        positions.push(*check);
        // Candidate single changes: (position, char, cost).
        let mut singles: Vec<(usize, usize, f32)> = Vec::new();
        for &p in &positions {
            let best = d.alts[p].first().map_or(0.0, |a| a.1);
            for &(c, s) in d.alts[p].iter().skip(0) {
                if c != chars[p] && best - s <= max_cost {
                    singles.push((p, c, best - s));
                }
            }
        }
        singles.sort_by(|a, b| a.2.total_cmp(&b.2));
        let mut done: Option<(f32, Vec<(usize, usize)>)> = None;
        let try_set = |chars: &mut Vec<usize>, set: &[(usize, usize)], cost: f32, done: &mut Option<(f32, Vec<(usize, usize)>)>| {
            if done.as_ref().is_some_and(|(c, _)| *c <= cost) || cost > max_cost {
                return;
            }
            let saved: Vec<usize> = set.iter().map(|&(p, _)| chars[p]).collect();
            for &(p, c) in set {
                chars[p] = c;
            }
            if passes(chars, field, *check) && all_ok(chars, n) {
                *done = Some((cost, set.to_vec()));
            }
            for (&(p, _), s) in set.iter().zip(saved) {
                chars[p] = s;
            }
        };
        for &(p, c, cost) in &singles {
            try_set(&mut chars, &[(p, c)], cost, &mut done);
        }
        for i in 0..singles.len() {
            for j in i + 1..singles.len() {
                let (a, b) = (singles[i], singles[j]);
                if a.0 != b.0 {
                    try_set(&mut chars, &[(a.0, a.1), (b.0, b.1)], a.2 + b.2, &mut done);
                }
            }
        }
        if let Some((cost, set)) = done {
            for (p, c) in set {
                chars[p] = c;
            }
            d.score -= cost;
        }
    }
    d.text = chars.iter().map(|&c| MRZ.as_bytes()[c] as char).collect();
}

/// Finishes the MRZ lines of a page together, once each is decoded: puts
/// back the `<` after a passport's `P` when it was lost (the issuing state is
/// then found a place early, where the holder's nationality from line 2
/// reads), and reconciles the names with the words printed on the page
/// ([`reconcile_names`]).
pub fn finish_lines(lines: &mut [Decoded], vocab: &std::collections::HashSet<String>) {
    let nationality = lines.iter().find(|d| d.template == Template::Td3Line2).map(|d| d.text[10..13].to_string());
    for d in lines.iter_mut() {
        match d.template {
            Template::Td3Line1 => {
                if let Some(nat) = &nationality
                    && &d.text[2..5] != nat
                    && &d.text[1..4] == nat
                {
                    d.text = format!("P<{}", &d.text[1..43]);
                    let mut alts = vec![d.alts[0].clone(), vec![(FILLER, 0.0)]];
                    alts.extend(d.alts[1..43].iter().cloned());
                    d.alts = alts;
                }
                reconcile_names(d, 5, vocab);
            }
            Template::Td1Line3 => reconcile_names(d, 0, vocab),
            _ => {}
        }
    }
    // Then the state codes, once the line is in place.
    for d in lines.iter_mut() {
        match d.template {
            Template::Td3Line1 | Template::Td1Line1 => fix_state(d, 2),
            Template::Td3Line2 => fix_state(d, 10),
            Template::Td1Line2 => fix_state(d, 15),
            _ => {}
        }
    }
}

/// A state code (`d.text[at..at + 3]`) that no state uses is replaced by the
/// valid code the recogniser found most likely among its alternatives at
/// those three positions, when one costs under 4 nats in all.
fn fix_state(d: &mut Decoded, at: usize) {
    if d.text.len() < at + 3 || crate::mrz::valid_state(&d.text[at..at + 3]) {
        return;
    }
    let mut best: Option<(f32, &str)> = None;
    for code in crate::mrz::STATE_CODES {
        let mut cost = 0.0;
        for (k, ch) in code.chars().enumerate() {
            let alts = &d.alts[at + k];
            let top = alts.first().map_or(0.0, |a| a.1);
            match idx(ch).and_then(|c| alts.iter().find(|a| a.0 == c)) {
                Some(a) => cost += top - a.1,
                None => cost = f32::INFINITY,
            }
        }
        if cost < 4.0 && best.is_none_or(|(b, _)| cost < b) {
            best = Some((cost, code));
        }
    }
    if let Some((_, code)) = best {
        d.text.replace_range(at..at + 3, code);
    }
}

/// Bonus, in nats per letter, for a name explained by a word printed on the
/// page: a printed word replaces the MRZ's reading of a token when the
/// recogniser found its letters plausible there at a total cost below this
/// times its length.
const PRINTED_BONUS: f32 = 0.6;

/// The names (`d.text[start..]`) re-read with the printed words as a
/// lexicon. Check digits do not cover the names, and the recogniser misreads
/// letters there (`HENDRTK`), reads a lone `<` as a letter (`JOHANCSIPHO`) or
/// adds one at the end; the data page prints the same names. A dynamic
/// programme splits the field into separators, printed words and literal
/// tokens: a printed word may stand at a position only through characters
/// among the recogniser's own alternatives there (cost: how much less
/// likely each was than what was read), and earns [`PRINTED_BONUS`] per
/// letter; a literal token keeps the reading as it is. So a name is changed
/// only when the print and the MRZ's own evidence agree on it.
pub fn reconcile_names(d: &mut Decoded, start: usize, vocab: &std::collections::HashSet<String>) {
    let field: Vec<usize> = d.text.chars().skip(start).map(|c| idx(c).unwrap_or(FILLER)).collect();
    let alts = &d.alts[start..];
    let n = field.len();
    if n == 0 || vocab.is_empty() || alts.len() != n {
        return;
    }
    let cost = |k: usize, c: usize| -> f32 {
        let read = alts[k].iter().find(|a| a.0 == field[k]).map_or(0.0, |a| a.1);
        if c == field[k] {
            return 0.0;
        }
        alts[k].iter().find(|a| a.0 == c).map_or(f32::INFINITY, |a| (read - a.1).max(0.0))
    };
    let words: Vec<Vec<usize>> = vocab
        .iter()
        .filter(|w| w.len() >= 2 && w.chars().all(|c| c.is_ascii_uppercase()))
        .map(|w| w.chars().map(|c| idx(c).unwrap()).collect())
        .collect();
    #[derive(Clone, Copy)]
    enum Step {
        Sep,
        Word(usize),
        Literal(usize),
    }
    let mut best: Vec<(f32, Step)> = vec![(0.0, Step::Sep); n + 1];
    for i in (0..n).rev() {
        let mut choice = (f32::INFINITY, Step::Sep);
        let sep = cost(i, FILLER) + best[i + 1].0;
        if sep < choice.0 {
            choice = (sep, Step::Sep);
        }
        // A name cannot begin the field with a filler, nor follow one
        // directly unless the reading has it.
        for (wi, w) in words.iter().enumerate() {
            let l = w.len();
            if i + l > n {
                continue;
            }
            let mut c: f32 = (0..l).map(|j| cost(i + j, w[j])).sum();
            let next = if i + l == n {
                0.0
            } else {
                c += cost(i + l, FILLER);
                best[i + l + 1].0
            };
            let v = c - PRINTED_BONUS * l as f32 + next;
            if v < choice.0 {
                choice = (v, Step::Word(wi));
            }
        }
        if field[i] != FILLER {
            let j = (i..n).find(|&k| field[k] == FILLER).unwrap_or(n);
            let v = if j == n { 0.0 } else { best[j + 1].0 };
            if v < choice.0 {
                choice = (v, Step::Literal(j));
            }
        }
        best[i] = choice;
    }
    let mut out: Vec<usize> = Vec::with_capacity(n);
    let mut i = 0;
    while i < n {
        match best[i].1 {
            Step::Sep => {
                out.push(FILLER);
                i += 1;
            }
            Step::Word(wi) => {
                out.extend(&words[wi]);
                i += words[wi].len();
                if i < n {
                    out.push(FILLER);
                    i += 1;
                }
            }
            Step::Literal(j) => {
                out.extend(&field[i..j]);
                i = j;
                if i < n {
                    out.push(FILLER);
                    i += 1;
                }
            }
        }
    }
    let head: String = d.text.chars().take(start).collect();
    d.text = head + &out.iter().map(|&c| MRZ.as_bytes()[c] as char).collect::<String>();
}

/// The line read under the template that explains it best, with its check
/// digits repaired where the recogniser's alternatives allow. `None` when no
/// template fits (the line is too short for any).
pub fn read_line(lp: NdTensorView<f32, 2>) -> Option<Decoded> {
    let mrz = to_mrz_classes(lp);
    let mut best: Option<Decoded> = None;
    for t in Template::ALL {
        if let Some(d) = decode(mrz.view(), t)
            && best.as_ref().is_none_or(|b| d.score > b.score)
        {
            best = Some(d);
        }
    }
    let mut d = best?;
    repair(&mut d, 6.0);
    Some(d)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A synthetic recogniser output (ocrs's 97 classes) spelling `text`: two
    /// frames per character, a blank between; `swaps` make another character
    /// the most likely at a position, the truth `s` nats behind.
    fn frames(text: &str, swaps: &[(usize, char, f32)]) -> NdTensor<f32, 2> {
        let class = |ch: char| OCRS_ALPHABET.chars().collect::<Vec<_>>().iter().rposition(|&c| c == ch).unwrap() + 1;
        let n = text.len() * 3 + 2;
        let mut lp = NdTensor::full([n, 97], -12.0f32);
        let mut t = 0;
        lp[[t, 0]] = 0.0;
        t += 1;
        for (i, ch) in text.chars().enumerate() {
            for _ in 0..2 {
                lp[[t, class(ch)]] = -0.05;
                for &(at, alt, s) in swaps {
                    if at == i {
                        lp[[t, class(ch)]] = -s;
                        lp[[t, class(alt)]] = -0.05;
                    }
                }
                t += 1;
            }
            lp[[t, 0]] = 0.0;
            t += 1;
        }
        lp[[t, 0]] = 0.0;
        lp
    }

    const L2: &str = "L898902C36UTO7408122F1204159ZE184226B<<<<<10";

    #[test]
    fn decodes_a_clean_line_under_its_template() {
        let lp = frames(L2, &[]);
        let d = decode(to_mrz_classes(lp.view()).view(), Template::Td3Line2).unwrap();
        assert_eq!(d.text, L2);
        let r = read_line(lp.view()).unwrap();
        assert_eq!(r.template, Template::Td3Line2);
        assert_eq!(r.text, L2);
    }

    #[test]
    fn a_digit_position_cannot_take_a_letter() {
        // The recogniser prefers `O` in the date of birth; the template only
        // allows digits there, so the next best (`0`) is read.
        let mut lp = frames(L2, &[]);
        let class = |ch: char| OCRS_ALPHABET.chars().collect::<Vec<_>>().iter().rposition(|&c| c == ch).unwrap() + 1;
        // Position 14 ('4'): make 'O' best and '0' second.
        let n0 = 1 + 14 * 3;
        for f in n0..n0 + 2 {
            lp[[f, class('4')]] = -3.0;
            lp[[f, class('O')]] = -0.05;
            lp[[f, class('0')]] = -0.5;
        }
        let d = read_line(lp.view()).unwrap();
        // '0' is read (a digit), and the date's check digit then fails, so
        // the repair puts back '4', the next best digit that passes.
        assert_eq!(d.text, L2);
    }

    #[test]
    fn names_follow_the_print_where_the_recogniser_allows() {
        let l1 = "P<GBRLE<ROUX<<HENDRIK<ZODWA<<<<<<<<<<<<<<<<<";
        // `HENDRIK` read `HENDRTK` ('I' a close second), `ZODWA` read `ZODHA`
        // with no `W` among the alternatives: only the first is changed.
        let swap_i = 14 + 5;
        let lp = frames(l1, &[(swap_i, 'T', 0.8)]);
        let mut d = read_line(lp.view()).unwrap();
        assert_eq!(d.template, Template::Td3Line1);
        assert_eq!(&d.text[14..21], "HENDRTK");
        let vocab: std::collections::HashSet<String> = ["LE", "ROUX", "HENDRIK", "ZODWA", "MOKOENA"].iter().map(|s| s.to_string()).collect();
        reconcile_names(&mut d, 5, &vocab);
        assert_eq!(d.text, l1);
        // A token the print does not explain is kept as read.
        let lp = frames("P<ZAFMOKOENA<<OWEN<<<<<<<<<<<<<<<<<<<<<<<<<<", &[]);
        let mut d = read_line(lp.view()).unwrap();
        let vocab: std::collections::HashSet<String> = ["MO", "OENA"].iter().map(|s| s.to_string()).collect();
        reconcile_names(&mut d, 5, &vocab);
        assert_eq!(&d.text[5..18], "MOKOENA<<OWEN");
    }

    #[test]
    fn repairs_a_check_digit_from_the_alternatives() {
        // The document number's last digit misread as '5' (the truth, '3', a close second).
        let lp = frames(L2, &[(8, '5', 0.7)]);
        let d = read_line(lp.view()).unwrap();
        assert_eq!(d.text, L2);
    }
}
