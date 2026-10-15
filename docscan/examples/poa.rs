//! Proof of address, natively: one JSON line per image.
//!
//! `cargo run --release --example poa -- [--flat] [--words] [--tagger=PATH] [--today=YYYY-MM-DD] <image>...`
//!
//! - Without `--flat`, the page outline is found first (as on a camera
//!   frame) and the page flattened from the full-resolution image; `--flat`
//!   takes the image as the page itself (a clean render or a scan).
//! - `--words` adds the OCR words and the tagger's input features, which is
//!   what `train/train_tagger.py` learns from.
//! - The fields are read by rules always, and by the tagger when given.
use docscan::poa::{self, Method, verify::Date};
use docscan::{Scanner, page, quad};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let flat = args.iter().any(|a| a == "--flat");
    let dump_words = args.iter().any(|a| a == "--words");
    let today = args.iter().find_map(|a| a.strip_prefix("--today=")).unwrap_or("2026-10-15");
    let today = Date::parse_iso(today).ok_or_else(|| anyhow::anyhow!("--today must be YYYY-MM-DD"))?;
    let models = concat!(env!("CARGO_MANIFEST_DIR"), "/../models");
    let mut scanner = Scanner::new();
    scanner.load_ocr_models(
        std::fs::read(format!("{models}/text-detection.rten"))?,
        std::fs::read(format!("{models}/text-recognition.rten"))?,
    )?;
    let tagger = args.iter().find_map(|a| a.strip_prefix("--tagger="));
    if let Some(path) = tagger {
        scanner.load_tagger_native(std::fs::read(path)?)?;
    }
    let paths: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();
    let list: Vec<String> = match paths.as_slice() {
        // `@list.txt`: one path per line.
        [one] if one.starts_with('@') => std::fs::read_to_string(&one[1..])?.lines().map(String::from).collect(),
        _ => paths.iter().map(|s| s.to_string()).collect(),
    };
    for path in &list {
        let t0 = std::time::Instant::now();
        let img = match image::open(path) {
            Ok(i) => i.to_rgba8(),
            Err(e) => {
                println!("{}", serde_json::json!({"path": path, "error": e.to_string()}));
                continue;
            }
        };
        let (w, h) = (img.width() as usize, img.height() as usize);
        let mut out = serde_json::json!({"path": path, "frame": [w, h]});
        // The page: the whole image, or the outline found in it, flattened.
        let (rgba, pw, ph) = if flat {
            (img.into_raw(), w, h)
        } else {
            // Find the outline on a frame-sized copy, as the browser does (≤ 1280 wide).
            let k = (1280.0 / w as f32).min(1.0);
            let (small, sw, sh) = if k < 1.0 { docscan::quality::scale_rgba(img.as_raw(), w, h, k) } else { (img.as_raw().clone(), w, h) };
            let analysis = page::analyse(&small, sw, sh);
            out["page"] = serde_json::to_value(&analysis)?;
            let Some(q) = analysis.outline else {
                out["error"] = "no outline".into();
                println!("{out}");
                continue;
            };
            let corners = q.corners.map(|p| [p[0] / k, p[1] / k]);
            let full = quad::Quad { corners, support: q.support };
            let (ow, oh) = quad::output_size(&full, 4000);
            let Some(flat) = quad::warp(img.as_raw(), w, h, 4, &corners, ow, oh) else {
                out["error"] = "degenerate outline".into();
                println!("{out}");
                continue;
            };
            out["corners"] = serde_json::to_value(corners)?;
            (flat, ow, oh)
        };
        out["flat_size"] = serde_json::json!([pw, ph]);
        // The colour page as the demo keeps it (1024 px on the long side), for a VLM to read.
        if let Some(dir) = args.iter().find_map(|a| a.strip_prefix("--save-flat=")) {
            let k = (1024.0 / pw.max(ph) as f32).min(1.0);
            let (small, sw, sh) = docscan::quality::scale_rgba(&rgba, pw, ph, k);
            let stem = std::path::Path::new(path).file_stem().unwrap().to_string_lossy().to_string();
            let file = format!("{dir}/{stem}_flat.png");
            image::RgbaImage::from_raw(sw as u32, sh as u32, small).unwrap().save(&file)?;
            out["flat_image"] = file.into();
        }
        let t1 = std::time::Instant::now();
        let (rules, words) = scanner.address_native(&rgba, pw, ph, today, Some(Method::Rules))?;
        let [gw, gh] = rules.page_size;
        out["page_size"] = serde_json::json!([gw, gh]);
        out["ms"] = serde_json::json!({"load_flatten": (t1 - t0).as_millis(), "enhance": rules.timings_ms.enhance, "ocr": rules.timings_ms.ocr, "rules": rules.timings_ms.extract});
        out["text"] = rules.text.clone().into();
        out["rules"] = serde_json::json!({"fields": rules.fields, "verification": rules.verification});
        if tagger.is_some() {
            let t = std::time::Instant::now();
            let r = scanner.address_from_words(&words, gw as usize, gh as usize, today, Some(Method::Tagger))?;
            out["ms"]["tagger"] = (t.elapsed().as_secs_f64() * 1000.0).into();
            out["tagger"] = serde_json::json!({"fields": r.fields, "verification": r.verification, "spans": r.spans});
        }
        if dump_words {
            let (ids, num) = poa::features::features(&words, gw as f32, gh as f32);
            out["words"] = serde_json::to_value(&words)?;
            out["ids"] = serde_json::to_value(&ids)?;
            out["num"] = serde_json::to_value(&num)?;
        }
        println!("{out}");
    }
    Ok(())
}
