//! Prints the linear-barcode regions of an image: `regions <image>`.
fn main() {
    let path = std::env::args().nth(1).unwrap();
    let img = image::open(path).unwrap().to_luma8();
    for r in docscan::barcode::oriented_regions(img.as_raw(), img.width() as usize, img.height() as usize) {
        let [x, y, w, h] = r.bounds();
        let angle = r.uy.atan2(r.ux).to_degrees();
        println!("centre {:.0},{:.0}  across {:.0}  along {:.0}  bars at {angle:.0}°  box {x:.0},{y:.0} {w:.0}x{h:.0}", r.cx, r.cy, 2.0 * r.half_across, 2.0 * r.half_along);
    }
}
