fn main() {
    for path in std::env::args().skip(1) {
        let img = image::open(&path).unwrap().to_rgba8();
        let (w, h) = img.dimensions();
        let (f, lines) = docscan::quad::debug_lines(img.as_raw(), w as usize, h as usize);
        println!("{}", serde_json::json!({"path": path, "factor": f, "lines": lines}));
    }
}
