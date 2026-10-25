//! Private label-robustness probe (DEV / fictional stress only): `prepare.py
//! SNAP --patched` copies it into a snapshot as
//! `examples/label_robustness_probe.rs`, beside `text_v6-candidates.patch`.
//! Never committed into the crate.
//!
//! `label_robustness_probe --models=DIR --mode=MODE <image>...`
//!
//! Modes (one JSON line per image):
//! - `fast`: the shipped `Scanner::labelled_fast_native` (the baseline);
//! - `detailed`: the shipped `Scanner::labelled_native` (the comparator);
//! - `replica`: `labelled_fast_native`'s steps re-done here through the
//!   patch's `read_native_research` with no change (parity with `fast`);
//! - `a-fullres`: arm A, recognition crops sampled from the frame as given
//!   rather than from its 1280-wide copy (detection unchanged);
//! - `b-rescore`: arm B, every line's two readings (PP-OCRv6 tiny's greedy
//!   text and ocrs's recogniser's, on the same quad) scored by the sum of the
//!   two models' CTC log-likelihoods; the higher wins, PP-OCR on a tie.
//!
//! Field values are printed: the runner parses them in memory and writes
//! aggregates only.
use docscan::{Scanner, barcode, label_speed, labels, quality, text_v6, za};
use ocrs::{ImageSource, OcrEngine, OcrEngineParams};
use rten_imageproc::{PointF, RotatedRect, Vec2};
use rten_tensor::prelude::*;
use rten_tensor::NdTensor;
use std::collections::HashMap;
use std::time::Instant;

/// ocrs 0.13's default recogniser alphabet (class `i + 1` is character `i`).
const OCRS_ALPHABET: &str = " 0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~EABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}

fn log_add(a: f32, b: f32) -> f32 {
    if a == f32::NEG_INFINITY {
        return b;
    }
    if b == f32::NEG_INFINITY {
        return a;
    }
    a.max(b) + (-(a - b).abs()).exp().ln_1p()
}

/// log p(labels | x) under a CTC model (Graves et al. 2006, the forward
/// recursion over the blank-extended label sequence; blank is class 0).
/// `lp(t, c)` is the log posterior of class `c` at step `t`.
pub fn ctc_log_likelihood(steps: usize, lp: impl Fn(usize, usize) -> f32, labels: &[usize]) -> f32 {
    let ext: Vec<usize> = std::iter::once(0).chain(labels.iter().flat_map(|&l| [l, 0])).collect();
    let s = ext.len();
    if steps == 0 || labels.len() > steps {
        return f32::NEG_INFINITY;
    }
    let mut alpha = vec![f32::NEG_INFINITY; s];
    alpha[0] = lp(0, ext[0]);
    if s > 1 {
        alpha[1] = lp(0, ext[1]);
    }
    for t in 1..steps {
        let mut next = vec![f32::NEG_INFINITY; s];
        for i in 0..s {
            let mut a = alpha[i];
            if i >= 1 {
                a = log_add(a, alpha[i - 1]);
            }
            if i >= 2 && ext[i] != 0 && ext[i] != ext[i - 2] {
                a = log_add(a, alpha[i - 2]);
            }
            if a != f32::NEG_INFINITY {
                next[i] = a + lp(t, ext[i]);
            }
        }
        alpha = next;
    }
    if s == 1 { alpha[0] } else { log_add(alpha[s - 1], alpha[s - 2]) }
}

fn luhn(d: &[u8]) -> bool {
    let sum: u32 = d.iter().rev().enumerate().map(|(i, &c)| {
        let v = (c - b'0') as u32;
        if i % 2 == 1 { let x = v * 2; if x > 9 { x - 9 } else { x } } else { v }
    }).sum();
    sum % 10 == 0
}

/// Digit runs in a reading that pass a check digit: a 15-digit Luhn run
/// (IMEI), a 19-20 digit Luhn run starting 89 (ICCID), an 8/12/13-digit run
/// with a valid GTIN checksum. A rescore may not change any of them.
fn checked_runs(text: &str) -> Vec<String> {
    let mut runs = Vec::new();
    for run in text.split(|c: char| !c.is_ascii_digit()).filter(|r| !r.is_empty()) {
        let b = run.as_bytes();
        let ok = (b.len() == 15 && luhn(b)) || (matches!(b.len(), 19 | 20) && run.starts_with("89") && luhn(b)) || (matches!(b.len(), 8 | 12 | 13) && labels::gtin_valid(run));
        if ok {
            runs.push(run.to_owned());
        }
    }
    runs
}

#[derive(Default, serde::Serialize)]
struct Stats {
    lines: usize,
    considered: usize,
    agreed: usize,
    skipped_vertical: usize,
    skipped_alphabet: usize,
    protected_check_digit: usize,
    replaced: usize,
    ocrs_rec_ms: f64,
    max_ocrs_lse_dev: f32,
}

struct Ocrs {
    engine: OcrEngine,
    rec: rten::Model,
}

fn rotated(quad: &[[f32; 2]; 4]) -> RotatedRect {
    let c = quad.iter().fold([0.0, 0.0], |a, p| [a[0] + p[0] / 4.0, a[1] + p[1] / 4.0]);
    let up = Vec2::from_xy(quad[0][0] - quad[3][0], quad[0][1] - quad[3][1]);
    let w = (quad[1][0] - quad[0][0]).hypot(quad[1][1] - quad[0][1]);
    let h = up.length();
    RotatedRect::new(PointF::from_yx(c[1], c[0]), up.normalized(), w.max(1.0), h.max(1.0))
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let opt = |k: &str| args.iter().find_map(|a| a.strip_prefix(k)).map(str::to_owned);
    let mode = opt("--mode=").unwrap_or_else(|| "fast".into());
    let models = opt("--models=").expect("--models=DIR");
    let read = |n: &str| std::fs::read(format!("{models}/{n}"));

    let t_models = Instant::now();
    let mut scanner = Scanner::new();
    if mode == "detailed" {
        scanner.load_ocr_models(read("text-detection.rten")?, read("text-recognition.rten")?)?;
    }
    scanner.load_label_reader_native(read("ppocr-v6-tiny-det.onnx")?, read("ppocr-v6-tiny-rec.onnx")?)?;
    let mut paddle = text_v6::PaddleTextScanner::new();
    paddle.load_detector_native(read("ppocr-v6-tiny-det.onnx")?)?;
    paddle.load_recognizer_native(read("ppocr-v6-tiny-rec.onnx")?, text_v6::DICTIONARY_JSON)?;
    let ocrs = if mode == "b-rescore" {
        Some(Ocrs {
            engine: OcrEngine::new(OcrEngineParams { recognition_model: Some(rten::Model::load(read("text-recognition.rten")?)?), ..Default::default() })?,
            rec: rten::Model::load(read("text-recognition.rten")?)?,
        })
    } else {
        None
    };
    let pp_ids: HashMap<char, usize> = paddle.dictionary().iter().enumerate().skip(1).filter_map(|(i, s)| {
        let mut cs = s.chars();
        match (cs.next(), cs.next()) { (Some(c), None) => Some((c, i)), _ => None }
    }).collect();
    let ocrs_ids: HashMap<char, usize> = OCRS_ALPHABET.chars().enumerate().map(|(i, c)| (c, i + 1)).collect();
    let models_ms = ms(t_models);

    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let img = image::open(path)?.to_rgba8();
        let (w, h) = img.dimensions();
        let rgba = img.into_raw();
        let t0 = Instant::now();
        let mut stats = Stats::default();
        let (fields, ocr_ms) = match mode.as_str() {
            "fast" => (scanner.labelled_fast_native(&rgba, w, h)?.fields, None),
            "detailed" => (scanner.labelled_native(&rgba, w, h)?.fields, None),
            "replica" | "a-fullres" | "b-rescore" => {
                // `Scanner::labelled_with`'s steps, with print read by the patch's research entry point.
                let luma = quality::rgba_to_luma(&rgba);
                let codes = barcode::read_all(&luma, w, h, None);
                let regions: Vec<[f32; 4]> = barcode::oriented_regions(&luma, w as usize, h as usize).iter().map(|r| r.bounds()).collect();
                let k = (Scanner::LABEL_OCR_WIDTH_PX as f32 / w as f32).min(1.0);
                let (small, sw, sh) = if k < 1.0 { quality::scale_rgba(&rgba, w as usize, h as usize, k) } else { (rgba.clone(), w as usize, h as usize) };
                let t = Instant::now();
                let crop = (mode == "a-fullres" && k < 1.0).then_some((rgba.as_slice(), w as usize, h as usize));
                let ocrs_input = match &ocrs {
                    Some(o) => Some(o.engine.prepare_input(ImageSource::from_bytes(&small, (sw as u32, sh as u32))?)?),
                    None => None,
                };
                let mut rescore = |quad: &[[f32; 2]; 4], probs: &[f32], text: &str| -> Option<String> {
                    stats.lines += 1;
                    let (Some(o), Some(input)) = (&ocrs, &ocrs_input) else { return None };
                    let qw = (quad[1][0] - quad[0][0]).hypot(quad[1][1] - quad[0][1]);
                    let qh = (quad[3][0] - quad[0][0]).hypot(quad[3][1] - quad[0][1]);
                    if qh >= 1.5 * qw {
                        stats.skipped_vertical += 1;
                        return None;
                    }
                    let tr = Instant::now();
                    let line = o.engine.prepare_recognition_input(input, &[rotated(quad)]).ok()?;
                    let [ih, iw] = line.shape();
                    let out: NdTensor<f32, 3> = o.rec.run_one(line.into_shape([1, 1, ih, iw]).view().into(), None).ok()?.try_into().ok()?;
                    stats.ocrs_rec_ms += ms(tr);
                    let lp = out.slice((.., 0, ..));
                    let [steps, classes] = lp.shape();
                    let lse = (0..classes).fold(f32::NEG_INFINITY, |a, c| log_add(a, lp[[0, c]]));
                    stats.max_ocrs_lse_dev = stats.max_ocrs_lse_dev.max(lse.abs());
                    let alt = docscan::mrz_decode::greedy(lp.view());
                    stats.considered += 1;
                    if alt == text {
                        stats.agreed += 1;
                        return None;
                    }
                    let ids = |s: &str, m: &HashMap<char, usize>| s.chars().map(|c| m.get(&c).copied()).collect::<Option<Vec<usize>>>();
                    let (Some(pp_a), Some(pp_b), Some(o_a), Some(o_b)) = (ids(text, &pp_ids), ids(&alt, &pp_ids), ids(text, &ocrs_ids), ids(&alt, &ocrs_ids)) else {
                        stats.skipped_alphabet += 1;
                        return None;
                    };
                    let pc = paddle.dictionary().len();
                    let pt = probs.len() / pc;
                    let pp_lp = |t: usize, c: usize| probs[t * pc + c].max(1e-30).ln();
                    let o_lp = |t: usize, c: usize| lp[[t, c]];
                    let keep = ctc_log_likelihood(pt, pp_lp, &pp_a) + ctc_log_likelihood(steps, o_lp, &o_a);
                    let swap = ctc_log_likelihood(pt, pp_lp, &pp_b) + ctc_log_likelihood(steps, o_lp, &o_b);
                    if !(swap > keep) {
                        return None;
                    }
                    let alt_runs = checked_runs(&alt);
                    if checked_runs(text).iter().any(|r| !alt_runs.contains(r)) {
                        stats.protected_check_digit += 1;
                        return None;
                    }
                    stats.replaced += 1;
                    Some(alt)
                };
                let r = paddle.read_native_research(&small, sw, sh, crop, &mut rescore)?;
                let mut lines: Vec<za::Line> = label_speed::rows_from_paddle(&r.lines);
                if k < 1.0 {
                    for l in &mut lines {
                        (l.x, l.y, l.w, l.h) = (l.x / k, l.y / k, l.w / k, l.h / k);
                    }
                }
                let ocr_ms = ms(t);
                (labels::associate(&codes, &regions, &lines).fields, Some(ocr_ms))
            }
            m => anyhow::bail!("unknown mode {m}"),
        };
        let total_ms = ms(t0);
        println!(
            "{}",
            serde_json::json!({"path": path, "mode": mode, "w": w, "h": h, "models_ms": models_ms, "total_ms": total_ms,
                "ocr_ms": ocr_ms, "stats": stats, "fields": fields})
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ctc_forward_matches_enumeration() {
        // Two steps, classes {blank, a, b}: p("a") = P(aa) + P(a-) + P(-a).
        let p = [[0.2f32, 0.5, 0.3], [0.4, 0.4, 0.2]];
        let lp = |t: usize, c: usize| p[t][c].ln();
        let want = p[0][1] * p[1][1] + p[0][1] * p[1][0] + p[0][0] * p[1][1];
        assert!((ctc_log_likelihood(2, lp, &[1]).exp() - want).abs() < 1e-6);
        // "aa" needs a blank between: impossible in two steps.
        assert_eq!(ctc_log_likelihood(2, lp, &[1, 1]), f32::NEG_INFINITY);
        assert!((ctc_log_likelihood(2, lp, &[1, 2]).exp() - p[0][1] * p[1][2]).abs() < 1e-6);
    }

    #[test]
    fn check_digit_runs() {
        assert_eq!(checked_runs("IMEI1: 990000123456784"), vec!["990000123456784"]);
        assert!(checked_runs("IMEI1: 990000123456785").is_empty());
        assert_eq!(checked_runs("6 001234 567892").len(), 0); // split groups are not one run
        assert_eq!(checked_runs("4006381333931"), vec!["4006381333931"]);
    }
}
