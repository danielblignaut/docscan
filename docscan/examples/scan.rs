//! `cargo run --release --example scan -- [--barcodes] <image>...` prints one JSON result per image.
use docscan::Scanner;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let barcodes_only = args.iter().any(|a| a == "--barcodes");
    let labelled = args.iter().any(|a| a == "--labelled");
    // `--expect=green_book` and so on: the step the page would be on.
    let expected = docscan::Expected::parse(args.iter().find_map(|a| a.strip_prefix("--expect=")).unwrap_or(""));
    let models = concat!(env!("CARGO_MANIFEST_DIR"), "/../models");
    let mut scanner = Scanner::new();
    scanner.load_ocr_models(
        std::fs::read(format!("{models}/text-detection.rten"))?,
        std::fs::read(format!("{models}/text-recognition.rten"))?,
    )?;
    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let img = image::open(path)?;
        // Mirror the browser: analyse at most 1280 px wide.
        let max: u32 = std::env::var("SCAN_MAX_WIDTH").ok().and_then(|v| v.parse().ok()).unwrap_or(1280);
        let img = if img.width() > max { img.resize(max, 10_000, image::imageops::FilterType::Triangle) } else { img };
        let rgba = img.to_rgba8();
        let (w, h) = rgba.dimensions();
        if labelled {
            let t = std::time::Instant::now();
            let out = scanner.labelled_native(rgba.as_raw(), w, h)?;
            let mut v = serde_json::to_value(&out)?;
            v["path"] = serde_json::json!(path);
            v["ms"] = serde_json::json!(t.elapsed().as_millis());
            for b in v["dropped"].as_array_mut().unwrap() { b.as_object_mut().unwrap().remove("bytes"); }
            println!("{}", serde_json::to_string(&v)?);
        } else if barcodes_only {
            let luma = docscan::quality::rgba_to_luma(rgba.as_raw());
            let t = std::time::Instant::now();
            let found = docscan::barcode::read_all(&luma, w, h, None);
            println!("{}", serde_json::json!({"path": path, "ms": t.elapsed().as_millis(), "barcodes": found.iter().map(|b| serde_json::json!({"format": b.format, "text": b.text, "points": b.points})).collect::<Vec<_>>()}));
        } else {
            let r = scanner.analyse(rgba.as_raw(), w, h, true, expected)?;
            let mut v = serde_json::to_value(&r)?;
            v["path"] = serde_json::json!(path);
            v["lines"] = serde_json::json!(r.lines.iter().map(|l| l.text.clone()).collect::<Vec<_>>());
            for b in v["barcodes"].as_array_mut().unwrap() { b.as_object_mut().unwrap().remove("bytes"); }
            println!("{}", serde_json::to_string(&v)?);
        }
    }
    Ok(())
}
