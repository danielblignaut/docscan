//! Private API-contract check (DEV only): `prepare.py --patched` copies it
//! into the patched snapshot as `examples/label_speed_api.rs`. Prints one JSON
//! line per image with the fields of `Scanner::labelled_fast_native` (the
//! patch's public entry point); the runner compares them in memory with the
//! probe's measured `ppocr` mode and writes flags only.
use docscan::Scanner;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let models = args.iter().find_map(|a| a.strip_prefix("--models=")).expect("--models=DIR").to_owned();
    let read = |n: &str| std::fs::read(format!("{models}/{n}"));
    let mut s = Scanner::new();
    // The detailed reader stays loaded beside the fast one, as the demo will have it.
    s.load_ocr_models(read("text-detection.rten")?, read("text-recognition.rten")?)?;
    s.load_label_reader_native(read("ppocr-v6-tiny-det.onnx")?, read("ppocr-v6-tiny-rec.onnx")?)?;
    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let img = image::open(path)?.to_rgba8();
        let (w, h) = img.dimensions();
        let out = s.labelled_fast_native(img.as_raw(), w, h)?;
        println!("{}", serde_json::json!({"path": path, "fields": out.fields}));
    }
    // Not loaded: an explicit error, never a silent fallback.
    let bare = Scanner::new();
    let err = bare.labelled_fast_native(&[255; 64], 4, 4).is_err();
    println!("{}", serde_json::json!({"unloaded_errors": err}));
    Ok(())
}
