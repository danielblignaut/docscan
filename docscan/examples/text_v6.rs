//! Optional PP-OCRv6 tiny native CLI. One JSON line per image.
//! cargo run --release --example text_v6 -- [--models=DIR] IMAGE...
use docscan::text_v6::{DICTIONARY_JSON, PaddleTextScanner};
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let default_models = concat!(env!("CARGO_MANIFEST_DIR"), "/../models");
    let models = args.iter().find_map(|a| a.strip_prefix("--models=")).unwrap_or(default_models);
    let model_directory = std::fs::canonicalize(models)?.to_string_lossy().into_owned();
    let mut scanner = PaddleTextScanner::new();
    scanner.load_detector_native(std::fs::read(format!("{models}/ppocr-v6-tiny-det.onnx"))?)?;
    scanner.load_recognizer_native(std::fs::read(format!("{models}/ppocr-v6-tiny-rec.onnx"))?, DICTIONARY_JSON)?;
    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let result = (|| -> anyhow::Result<serde_json::Value> {
            let image = image::open(path)?.to_rgba8();
            let read = if args.iter().any(|a| a == "--detail") {
                scanner.read_detailed_native(image.as_raw(), image.width() as usize, image.height() as usize)?
            } else {
                scanner.read_native(image.as_raw(), image.width() as usize, image.height() as usize)?
            };
            let mut output = serde_json::to_value(&read)?;
            output["path"] = path.clone().into();
            output["model_directory"] = model_directory.clone().into();
            Ok(output)
        })();
        match result {
            Ok(output) => println!("{output}"),
            Err(error) => println!("{}", serde_json::json!({"path": path, "error": error.to_string(), "model_directory": model_directory})),
        }
    }
    Ok(())
}
