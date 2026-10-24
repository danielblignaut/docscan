//! General text OCR: `text --page|--legacy <image>...`, JSON per image.
use docscan::Scanner;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let default_models = concat!(env!("CARGO_MANIFEST_DIR"), "/../models");
    let models = args.iter().find_map(|a| a.strip_prefix("--models=")).unwrap_or(default_models);
    let model_directory = std::fs::canonicalize(models)?.to_string_lossy().into_owned();
    let mut scanner = Scanner::new();
    scanner.load_ocr_models(
        std::fs::read(format!("{models}/text-detection.rten"))?,
        std::fs::read(format!("{models}/text-recognition.rten"))?,
    )?;
    if !args.iter().any(|s| s == "--tiles") {
        if let Ok(model) = std::fs::read(format!("{models}/text-detection-page.onnx")) {
            scanner.load_page_detector_native(model)?;
        }
    }
    for path in args.iter().filter(|s| !s.starts_with("--")) {
        let image = image::open(path)?.to_rgba8();
        let (w, h) = image.dimensions();
        let start = std::time::Instant::now();
        let mut out = if args.iter().any(|s| s == "--legacy") {
            let result = scanner.ocr_lines(image.as_raw(), w, h)?;
            serde_json::json!({ "text": result.lines.iter().map(|l| l.text.as_str()).collect::<Vec<_>>().join("\n"), "lines": result.lines })
        } else {
            serde_json::to_value(scanner.text_page_native(image.as_raw(), w, h)?)?
        };
        out["ms"] = serde_json::json!(start.elapsed().as_secs_f64() * 1000.0);
        out["path"] = serde_json::json!(path);
        out["model_directory"] = serde_json::json!(model_directory);
        println!("{out}");
    }
    Ok(())
}
