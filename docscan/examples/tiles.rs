//! Prints the tiled OCR lines of an image: `tiles <image>`.
fn main() -> anyhow::Result<()> {
    let path = std::env::args().nth(1).unwrap();
    let models = concat!(env!("CARGO_MANIFEST_DIR"), "/../models");
    let mut s = docscan::Scanner::new();
    s.load_ocr_models(std::fs::read(format!("{models}/text-detection.rten"))?, std::fs::read(format!("{models}/text-recognition.rten"))?)?;
    let img = image::open(path)?.to_rgba8();
    for l in s.ocr_tiled(img.as_raw(), img.width() as usize, img.height() as usize)? {
        println!("{:>6.0} {:>6.0} {:>5.0} {:>4.0}  {}", l.x, l.y, l.w, l.h, l.text);
    }
    Ok(())
}
