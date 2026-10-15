//! Captures from already-OCR'd frames (`eval/poa_capture_eval.py`): one JSON
//! line per capture on stdin, `{id, customer, frames: [{words, page_size,
//! page, error, fallback}]}`, and per capture on stdout what the live
//! pipeline makes of it: the frames it picks and reads (the first frames
//! whose page analysis was accepted, then the sharpest of the rest; two, and
//! a third when they disagree), the voted fields, the decision about the
//! customer, and every frame's own reading for single-frame scoring.
//!
//! `cargo run --release --example poa_capture -- --tagger=PATH [--today=YYYY-MM-DD] [--max-frames=N]`
use std::io::BufRead;

use docscan::Scanner;
use docscan::poa::{AddressResult, Method, capture, customer::{self, Customer}, features::Word, verify::Date};
use serde_json::{Value, json};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let today = Date::parse_iso(args.iter().find_map(|a| a.strip_prefix("--today=")).unwrap_or("2026-10-15")).unwrap();
    let max_frames: usize = args.iter().find_map(|a| a.strip_prefix("--max-frames=")).map_or(capture::MAX_FRAMES, |v| v.parse().unwrap());
    let min_frames: usize = args.iter().find_map(|a| a.strip_prefix("--min-frames=")).map_or(2, |v| v.parse().unwrap());
    let mut scanner = Scanner::new();
    let tagger = args.iter().find_map(|a| a.strip_prefix("--tagger=")).ok_or_else(|| anyhow::anyhow!("--tagger=PATH"))?;
    scanner.load_tagger_native(std::fs::read(tagger)?)?;
    scanner.set_gazetteer(!args.iter().any(|a| a == "--no-gazetteer"));
    for line in std::io::stdin().lock().lines() {
        let v: Value = serde_json::from_str(&line?)?;
        let cust: Option<Customer> = v.get("customer").filter(|c| !c.is_null()).map(|c| serde_json::from_value(c.clone())).transpose()?;
        let frames = v["frames"].as_array().cloned().unwrap_or_default();
        // Every frame's own reading.
        let mut readings: Vec<Option<(AddressResult, Vec<Word>)>> = Vec::new();
        let mut single = Vec::new();
        for f in &frames {
            let (Some(words), Some(size)) = (f.get("words").filter(|w| !w.is_null()), f.get("page_size").filter(|w| !w.is_null())) else {
                readings.push(None);
                single.push(json!({"fields": null, "verify": {"accepted": false, "reasons": ["no page read"]}}));
                continue;
            };
            let words: Vec<Word> = serde_json::from_value(words.clone())?;
            let (w, h) = (size[0].as_u64().unwrap_or(1) as usize, size[1].as_u64().unwrap_or(1) as usize);
            let r = scanner.address_from_words(&words, w, h, today, Some(Method::Tagger))?;
            let check = cust.as_ref().map(|c| customer::check(&words, &r.spans, c, capture::doc_date(&r.fields), today));
            single.push(json!({"fields": r.fields, "verify": check}));
            readings.push(Some((r, words)));
        }
        // The live pipeline's order: accepted frames first, in order; then the sharpest of the rest.
        let accepted = |f: &Value| f["page"]["accepted"].as_bool().unwrap_or(false);
        let sharp = |f: &Value| f["page"]["quality"]["sharpness"].as_f64().unwrap_or(0.0);
        let mut order: Vec<usize> = (0..frames.len()).filter(|&i| readings[i].is_some() && accepted(&frames[i])).collect();
        let mut rest: Vec<usize> = (0..frames.len()).filter(|&i| readings[i].is_some() && !accepted(&frames[i])).collect();
        rest.sort_by(|&a, &b| sharp(&frames[b]).total_cmp(&sharp(&frames[a])));
        order.extend(rest);
        let mut picked: Vec<usize> = Vec::new();
        let mut result = None;
        for &i in &order {
            picked.push(i);
            let rs: Vec<&AddressResult> = picked.iter().map(|&k| &readings[k].as_ref().unwrap().0).collect();
            let ws: Vec<&[Word]> = picked.iter().map(|&k| readings[k].as_ref().unwrap().1.as_slice()).collect();
            let r = capture::combine(&rs, &ws, cust.as_ref(), today);
            let more = picked.len() < min_frames || (capture::next_frame_needed(&r) && picked.len() < max_frames);
            result = Some(r);
            if !more || picked.len() >= max_frames {
                break;
            }
        }
        let fallback = picked.iter().any(|&i| frames[i]["fallback"].as_bool().unwrap_or(false));
        let cap = match result {
            Some(r) => json!({"fields": r.fields, "votes": r.votes, "verify": r.customer, "frames_read": r.frames_read, "picked": picked, "fallback": fallback}),
            None => json!({"fields": null, "verify": {"accepted": false, "reasons": ["no frame read"]}, "frames_read": 0}),
        };
        println!("{}", json!({"id": v["id"], "capture": cap, "frames": single}));
    }
    Ok(())
}
