//! Prints the linear-barcode regions of an image: `regions <image>`.
fn main() {
    let path = std::env::args().nth(1).unwrap();
    let img = image::open(path).unwrap().to_luma8();
    for r in docscan::barcode::linear_regions(img.as_raw(), img.width() as usize, img.height() as usize) {
        println!("x {}-{}  y {}-{}  along_x={}", r.x0, r.x1, r.y0, r.y1, r.bars_along_x);
    }
}
