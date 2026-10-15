//! Page-finding accuracy on synthetic camera frames: for each `<frame>.json`
//! (testdata/poa_augment.py), the largest corner error of
//! `page::analyse`'s outline, as a fraction of the frame diagonal.
//! `cargo run --release --example page_check -- @list.txt` (one .json path per line).
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let list: Vec<String> = match args.first() {
        Some(a) if a.starts_with('@') => std::fs::read_to_string(&a[1..])?.lines().map(String::from).collect(),
        _ => args.clone(),
    };
    let (mut ok, mut n) = (0, 0);
    for meta in &list {
        let m: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(meta)?)?;
        let img = image::open(m["image"].as_str().unwrap())?.to_rgba8();
        let (w, h) = (img.width() as usize, img.height() as usize);
        let k = (1280.0 / w as f32).min(1.0);
        let (small, sw, sh) = if k < 1.0 { docscan::quality::scale_rgba(img.as_raw(), w, h, k) } else { (img.into_raw(), w, h) };
        let a = docscan::page::analyse(&small, sw, sh);
        let diag = ((w * w + h * h) as f32).sqrt();
        let err = a.outline.map_or(1.0, |q| {
            (0..4)
                .map(|i| {
                    let t = &m["corners_tl_tr_br_bl"][i];
                    let (tx, ty) = (t[0].as_f64().unwrap() as f32, t[1].as_f64().unwrap() as f32);
                    ((q.corners[i][0] / k - tx).powi(2) + (q.corners[i][1] / k - ty).powi(2)).sqrt()
                })
                .fold(0f32, f32::max)
                / diag
        });
        n += 1;
        ok += usize::from(err < 0.05);
        println!("{meta} {err:.4} {:?} {:.0}ms", a.shape, a.ms);
    }
    eprintln!("{ok}/{n} within 5% of the diagonal");
    Ok(())
}
