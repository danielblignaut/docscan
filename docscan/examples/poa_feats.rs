//! Recomputes the tagger's input features from OCR words already read
//! (`train/build_dataset.py` output), so a new feature set can be trained
//! without OCR'ing the pages again: one JSON line per page on stdin with
//! `words` and `page_size`; the same line on stdout with `ids` and `num`
//! replaced by [`docscan::poa::features::features_v2`]'s (or, with `--v1`,
//! the first set's).
//!
//! With `--order`, the line's `words_raw` (`{text, x, y, w, h}` in any
//! order, e.g. from `train/synth_ocr.py`) are first put in reading order
//! (`features::reading_order`, as the live pipeline does) and written as `words`.
//!
//! `cargo run --release --example poa_feats [--v1] [--order] < pages.jsonl > pages_v2.jsonl`
use std::io::{BufRead, Write};

use docscan::poa::features::{self, Word};
use docscan::za::Line;
use serde_json::Value;

fn main() -> anyhow::Result<()> {
    let v1 = std::env::args().any(|a| a == "--v1");
    let order = std::env::args().any(|a| a == "--order");
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());
    for line in std::io::stdin().lock().lines() {
        let mut v: Value = serde_json::from_str(&line?)?;
        if order && let Some(raw) = v.get("words_raw").filter(|w| !w.is_null()) {
            #[derive(serde::Deserialize)]
            struct Raw {
                text: String,
                x: f32,
                y: f32,
                w: f32,
                h: f32,
            }
            let raw: Vec<Raw> = serde_json::from_value(raw.clone())?;
            let raw: Vec<Line> = raw.into_iter().map(|r| Line { text: r.text, x: r.x, y: r.y, w: r.w, h: r.h }).collect();
            v["words"] = serde_json::to_value(features::reading_order(&raw))?;
            v.as_object_mut().unwrap().remove("words_raw");
        }
        if let (Some(words), Some(size)) = (v.get("words").filter(|w| !w.is_null()), v.get("page_size").filter(|s| !s.is_null())) {
            let words: Vec<Word> = serde_json::from_value(words.clone())?;
            let (w, h) = (size[0].as_f64().unwrap_or(1.0) as f32, size[1].as_f64().unwrap_or(1.0) as f32);
            if v1 {
                let (ids, num) = features::features(&words, w, h);
                v["ids"] = serde_json::to_value(ids)?;
                v["num"] = serde_json::to_value(num.iter().map(|r| r.to_vec()).collect::<Vec<_>>())?;
            } else {
                let (ids, num) = features::features_v2(&words, w, h);
                v["ids"] = serde_json::to_value(ids)?;
                v["num"] = serde_json::to_value(num.iter().map(|r| r.to_vec()).collect::<Vec<_>>())?;
            }
        }
        writeln!(out, "{v}")?;
    }
    Ok(())
}
