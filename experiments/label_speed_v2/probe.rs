//! Private label-speed probe (DEV only): `prepare.py` copies it into the
//! snapshot as `examples/label_speed_probe.rs`. Never committed into the crate.
//!
//! `label_speed_probe --models=DIR --mode=MODE [--repeat=N] [--parity] <image>...`
//!
//! Modes (each prints one JSON line per image and iteration):
//! - `full`: `Scanner::labelled_native`'s stages, re-timed (`--parity` also
//!   runs `labelled_native` and reports whether the fields are identical);
//! - `profile`: a replica of the tiled reading's per-tile work with its own
//!   `OcrEngine` (level, detect, layout, recognise per tile), for the time
//!   split and the number of line recognitions; its fields are not used;
//! - `once-tiles`, `once-page`: `label_speed::read_lines` with tile or page
//!   detection, every line recognised once;
//! - `ppocr`, `ppocr-detail`: PP-OCRv6 tiny (`read_native`, max side 960;
//!   `read_detailed_native`, also 1600) lines as rows.
//!
//! The fields hold values: the runner reads them in memory and writes
//! aggregates only.
#[path = "../src/label_speed.rs"]
mod label_speed;

#[allow(unused_imports)]
use docscan::{geometry, mrz, mrz_decode, quality, text_v6, za};
use docscan::{Scanner, barcode, labels};
use ocrs::{ImageSource, OcrEngine, OcrEngineParams, TextItem};
use rten_imageproc::BoundingRect;
use std::time::Instant;

fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let opt = |k: &str| args.iter().find_map(|a| a.strip_prefix(k)).map(str::to_owned);
    let mode = opt("--mode=").unwrap_or_else(|| "full".into());
    let repeat: usize = opt("--repeat=").and_then(|v| v.parse().ok()).unwrap_or(1);
    let parity = args.iter().any(|a| a == "--parity");
    let models = opt("--models=").expect("--models=DIR");
    let read = |n: &str| std::fs::read(format!("{models}/{n}"));

    let t_models = Instant::now();
    let mut scanner = Scanner::new();
    scanner.load_ocr_models(read("text-detection.rten")?, read("text-recognition.rten")?)?;
    let engine = OcrEngine::new(OcrEngineParams {
        detection_model: Some(rten::Model::load(read("text-detection.rten")?)?),
        recognition_model: Some(rten::Model::load(read("text-recognition.rten")?)?),
        ..Default::default()
    })?;
    let rec = rten::Model::load(read("text-recognition.rten")?)?;
    let page_det = if mode == "once-page" { Some(rten::Model::load(read("text-detection-page.onnx")?)?) } else { None };
    let mut paddle = text_v6::PaddleTextScanner::new();
    if mode.starts_with("ppocr") {
        paddle.load_detector_native(read("ppocr-v6-tiny-det.onnx")?)?;
        paddle.load_recognizer_native(read("ppocr-v6-tiny-rec.onnx")?, text_v6::DICTIONARY_JSON)?;
    }
    let models_ms = ms(t_models);
    let clock = Instant::now();
    let now = move || clock.elapsed().as_secs_f64() * 1000.0;

    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let t_load = Instant::now();
        let img = image::open(path)?.to_rgba8();
        let (w, h) = img.dimensions();
        let rgba = img.into_raw();
        let load_ms = ms(t_load);
        for iteration in 0..repeat {
            let t0 = Instant::now();
            let luma = quality::rgba_to_luma(&rgba);
            let t = Instant::now();
            let codes = barcode::read_all(&luma, w, h, None);
            let read_all_ms = ms(t);
            let t = Instant::now();
            let regions: Vec<[f32; 4]> = barcode::oriented_regions(&luma, w as usize, h as usize).iter().map(|r| r.bounds()).collect();
            let regions_ms = ms(t);
            let t = Instant::now();
            let k = (Scanner::LABEL_OCR_WIDTH_PX as f32 / w as f32).min(1.0);
            let (small, sw, sh) = if k < 1.0 { quality::scale_rgba(&rgba, w as usize, h as usize, k) } else { (rgba.clone(), w as usize, h as usize) };
            let scale_ms = ms(t);
            let t = Instant::now();
            let mut extra = serde_json::Value::Null;
            let mut lines: Vec<za::Line> = match mode.as_str() {
                "full" => scanner.ocr_tiled(&small, sw, sh)?,
                "profile" => {
                    let (l, p) = profile_tiled(&engine, &small, sw, sh)?;
                    extra = p;
                    l
                }
                "once-tiles" | "once-page" => {
                    let d = if mode == "once-page" { label_speed::Detection::Page } else { label_speed::Detection::Tiles };
                    let (l, st) = label_speed::read_lines(&engine, page_det.as_ref(), Some(&rec), d, &small, sw, sh, &now)?;
                    extra = serde_json::to_value(&st)?;
                    l
                }
                "ppocr" | "ppocr-detail" => {
                    let r = if mode == "ppocr" { paddle.read_native(&small, sw, sh)? } else { paddle.read_detailed_native(&small, sw, sh)? };
                    extra = serde_json::json!({"detect_ms": r.timings_ms.detect, "recognise_ms": r.timings_ms.recognize, "passes": r.passes, "lines_recognised": r.lines.len()});
                    label_speed::rows_from_paddle(&r.lines)
                }
                m => anyhow::bail!("unknown mode {m}"),
            };
            if k < 1.0 {
                for l in &mut lines {
                    (l.x, l.y, l.w, l.h) = (l.x / k, l.y / k, l.w / k, l.h / k);
                }
            }
            let ocr_ms = ms(t);
            let t = Instant::now();
            let out = labels::associate(&codes, &regions, &lines);
            let associate_ms = ms(t);
            let total_ms = ms(t0);
            let same = if parity && iteration == 0 {
                let lib = scanner.labelled_native(&rgba, w, h)?;
                Some(serde_json::to_value(&lib.fields)? == serde_json::to_value(&out.fields)?)
            } else {
                None
            };
            println!(
                "{}",
                serde_json::json!({"path": path, "mode": mode, "iteration": iteration, "w": w, "h": h, "load_ms": load_ms, "models_ms": models_ms,
                    "stages": {"read_all": read_all_ms, "regions": regions_ms, "scale": scale_ms, "ocr": ocr_ms, "associate": associate_ms},
                    "total_ms": total_ms, "ocr_stats": extra, "lines": lines.len(), "same_as_library": same,
                    "barcodes": codes.len(), "fields": out.fields})
            );
        }
    }
    Ok(())
}

/// The tiled reading's per-tile work, timed: each tile levelled by its own
/// skew, words detected, lines laid out and recognised (no MRZ or capitals
/// re-reads, which labels rarely trigger). Lines are de-duplicated as
/// `Scanner::tiled` does. Returns the lines and the time split.
fn profile_tiled(ocr: &OcrEngine, rgba: &[u8], w: usize, h: usize) -> anyhow::Result<(Vec<za::Line>, serde_json::Value)> {
    let (tw, th) = (600.min(w), 800.min(h));
    let (mut level_ms, mut detect_ms, mut layout_ms, mut rec_ms) = (0.0, 0.0, 0.0, 0.0);
    let (mut tiles, mut recognised, mut rec_px_w, mut words_n) = (0usize, 0usize, 0f32, 0usize);
    let mut all: Vec<za::Line> = Vec::new();
    for &y0 in &label_speed::tile_starts(h, th) {
        for &x0 in &label_speed::tile_starts(w, tw) {
            tiles += 1;
            let t = Instant::now();
            let mut tile = Vec::with_capacity(tw * th * 4);
            for y in y0..y0 + th {
                tile.extend_from_slice(&rgba[(y * w + x0) * 4..(y * w + x0 + tw) * 4]);
            }
            let k = ((600.0 / tw as f32).min(800.0 / th as f32)).clamp(1.0, 2.0);
            let (tile, sw, sh) = if k > 1.05 { quality::scale_rgba(&tile, tw, th, k) } else { (tile, tw, th) };
            let ink = quality::rgba_to_ink(&tile);
            let luma = quality::rgba_to_luma(&tile);
            let skew = geometry::estimate_skew(&luma, sw, sh);
            let (ink, lw, lh) = if skew.abs() >= 1.0 { geometry::rotate(&ink, sw, sh, skew) } else { (ink, sw, sh) };
            let input = ocr.prepare_input(ImageSource::from_bytes(&ink, (lw as u32, lh as u32))?)?;
            level_ms += ms(t);
            let t = Instant::now();
            let words = ocr.detect_words(&input)?;
            detect_ms += ms(t);
            words_n += words.len();
            let t = Instant::now();
            let line_rects = ocr.find_text_lines(&input, &words);
            layout_ms += ms(t);
            let t = Instant::now();
            let texts = ocr.recognize_text(&input, &line_rects)?;
            rec_ms += ms(t);
            recognised += line_rects.len();
            for l in &line_rects {
                let (a, b) = l.iter().map(|r| r.bounding_rect()).fold((f32::MAX, f32::MIN), |(a, b), r| (a.min(r.left()), b.max(r.right())));
                let hh = l.iter().map(|r| r.bounding_rect().height()).fold(1.0f32, f32::max);
                rec_px_w += (b - a) / hh * 64.0;
            }
            let mut placed = Vec::new();
            for text in texts.iter().flatten() {
                for word in text.words() {
                    let r = word.bounding_rect();
                    placed.push(za::Line { text: word.to_string(), x: r.left() as f32, y: r.top() as f32, w: r.width() as f32, h: r.height() as f32 });
                }
            }
            for mut l in za::rows_from_words(placed) {
                if skew.abs() >= 1.0 {
                    let c = [[l.x, l.y], [l.x + l.w, l.y], [l.x, l.y + l.h], [l.x + l.w, l.y + l.h]].map(|p| geometry::rotated_to_source(p, sw, sh, skew));
                    let (a, b) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
                    let (cc, d) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
                    (l.x, l.y, l.w, l.h) = (a, cc, b - a, d - cc);
                }
                (l.x, l.y, l.w, l.h) = (l.x / k + x0 as f32, l.y / k + y0 as f32, l.w / k, l.h / k);
                all.push(l);
            }
        }
    }
    let before = all.len();
    all.sort_by(|a, b| b.text.chars().count().cmp(&a.text.chars().count()));
    let mut kept: Vec<za::Line> = Vec::new();
    for l in all {
        let dup = kept.iter().any(|k| {
            let ow = (k.x + k.w).min(l.x + l.w) - k.x.max(l.x);
            let oh = (k.y + k.h).min(l.y + l.h) - k.y.max(l.y);
            ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (l.w * l.h).min(k.w * k.h)
        });
        if !dup {
            kept.push(l);
        }
    }
    kept.sort_by(|a, b| a.y.total_cmp(&b.y).then(a.x.total_cmp(&b.x)));
    let v = serde_json::json!({"tiles": tiles, "level_ms": level_ms, "detect_ms": detect_ms, "layout_ms": layout_ms, "recognise_ms": rec_ms,
        "lines_recognised": recognised, "rec_width_px_at_64": rec_px_w, "words_detected": words_n, "rows_before_dedup": before, "rows_after_dedup": kept.len()});
    Ok((kept, v))
}
