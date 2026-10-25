//! Pre-freeze diagnosis probe (DEV only): `prepare.py d0 --probe=diag.rs`
//! copies it into an unpatched snapshot as `examples/label_robustness_probe.rs`.
//!
//! `label_robustness_probe --models=DIR <image>...` prints one JSON line per
//! image: the shipped Fast reading (`Scanner::labelled_fast_native`) and the
//! PP-OCRv6 lines it was built from (text, mean CTC confidence, axis box), so
//! the runner can classify Fast's misses. Values stay in memory in the runner.
use docscan::{Scanner, quality, text_v6};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let models = args.iter().find_map(|a| a.strip_prefix("--models=")).expect("--models=DIR").to_owned();
    let read = |n: &str| std::fs::read(format!("{models}/{n}"));
    let mut scanner = Scanner::new();
    scanner.load_label_reader_native(read("ppocr-v6-tiny-det.onnx")?, read("ppocr-v6-tiny-rec.onnx")?)?;
    let mut paddle = text_v6::PaddleTextScanner::new();
    paddle.load_detector_native(read("ppocr-v6-tiny-det.onnx")?)?;
    paddle.load_recognizer_native(read("ppocr-v6-tiny-rec.onnx")?, text_v6::DICTIONARY_JSON)?;
    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let img = image::open(path)?.to_rgba8();
        let (w, h) = img.dimensions();
        let rgba = img.into_raw();
        let out = scanner.labelled_fast_native(&rgba, w, h)?;
        let k = (Scanner::LABEL_OCR_WIDTH_PX as f32 / w as f32).min(1.0);
        let (small, sw, sh) = if k < 1.0 { quality::scale_rgba(&rgba, w as usize, h as usize, k) } else { (rgba.clone(), w as usize, h as usize) };
        let r = paddle.read_native(&small, sw, sh)?;
        let lines: Vec<_> = r.lines.iter().map(|l| serde_json::json!({"text": l.text, "confidence": l.confidence, "box": [l.x / k, l.y / k, l.w / k, l.h / k]})).collect();
        println!("{}", serde_json::json!({"path": path, "fields": out.fields, "lines": lines}));
    }
    Ok(())
}
