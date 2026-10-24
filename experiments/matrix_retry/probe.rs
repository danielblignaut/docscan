//! Copied into isolated snapshots as an example; no shared example is edited.
use docscan::{barcode, quality};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = &args[0];
    let path = &args[1];
    let image = image::open(path)?.to_rgba8();
    let (w, h) = image.dimensions();
    let luma = quality::rgba_to_luma(image.as_raw());
    let start = std::time::Instant::now();
    let found = scan(mode, &luma, w, h);
    println!("{}", serde_json::json!({"barcodes":found, "ms":start.elapsed().as_secs_f64()*1000.0}));
    Ok(())
}

// PREPARE_SCAN_FUNCTION
