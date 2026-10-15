//! The fields from already-OCR'd pages: reads `train/build_dataset.py` lines
//! (with `words` and `page_size`) on stdin and writes, per page, what the
//! rules and (with `--tagger=PATH`) the tagger make of them, with the checks.
//! OCR is the slow part; this lets the extractors be scored without it.
use std::io::BufRead;

use docscan::poa::{Method, features::Word, verify::Date};
use docscan::Scanner;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let today = Date::parse_iso(args.iter().find_map(|a| a.strip_prefix("--today=")).unwrap_or("2026-10-15")).unwrap();
    let mut scanner = Scanner::new();
    let tagger = args.iter().find_map(|a| a.strip_prefix("--tagger="));
    if let Some(p) = tagger {
        scanner.load_tagger_native(std::fs::read(p)?)?;
    }
    for line in std::io::stdin().lock().lines() {
        let v: serde_json::Value = serde_json::from_str(&line?)?;
        let mut out = serde_json::json!({"id": v["id"], "kind": v["kind"], "layout": v["layout"], "source": v["source"], "ok": v["ok"]});
        if let (Some(words), Some(size)) = (v.get("words"), v.get("page_size")) {
            let words: Vec<Word> = serde_json::from_value(words.clone())?;
            let (w, h) = (size[0].as_u64().unwrap_or(1) as usize, size[1].as_u64().unwrap_or(1) as usize);
            let t = std::time::Instant::now();
            let r = scanner.address_from_words(&words, w, h, today, Some(Method::Rules))?;
            out["rules"] = serde_json::json!({"fields": r.fields, "verification": r.verification, "ms": t.elapsed().as_secs_f64() * 1e3});
            if tagger.is_some() {
                let t = std::time::Instant::now();
                let r = scanner.address_from_words(&words, w, h, today, Some(Method::Tagger))?;
                out["tagger"] = serde_json::json!({"fields": r.fields, "verification": r.verification, "spans": r.spans, "ms": t.elapsed().as_secs_f64() * 1e3});
            }
            out["text"] = r.text.into();
        }
        println!("{out}");
    }
    Ok(())
}
