//! Barcode reading through rxing (a Rust port of ZXing): every code in a
//! frame, of any supported symbology, with its position.

use std::collections::HashSet;

use rxing::aztec::AztecReader;
use rxing::common::{BitMatrix, DetectorRXingResult, HybridBinarizer};
use rxing::multi::{GenericMultipleBarcodeReader, MultipleBarcodeReader};
use rxing::oned::MultiFormatOneDReader;
use rxing::pdf417::PDF417Reader;
use rxing::qrcode::cpp_port::QrReader;
use rxing::{Binarizer, BarcodeFormat, BinaryBitmap, DecodeHintValue, DecodeHints, Luma8LuminanceSource, MultiUseMultiFormatReader, RXingResult, Reader};
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Barcode {
    pub format: String,
    pub text: String,
    /// The raw payload, for binary codes whose text decoding is lossy.
    pub bytes: Vec<u8>,
    /// Corner or end points in the analysed image's pixels.
    pub points: Vec<[f32; 2]>,
}

pub fn format_from_name(name: &str) -> Option<BarcodeFormat> {
    Some(match name.to_ascii_lowercase().replace(['-', '_', ' '], "").as_str() {
        "qrcode" | "qr" => BarcodeFormat::QR_CODE,
        "datamatrix" => BarcodeFormat::DATA_MATRIX,
        "pdf417" => BarcodeFormat::PDF_417,
        "aztec" => BarcodeFormat::AZTEC,
        "code128" => BarcodeFormat::CODE_128,
        "code39" => BarcodeFormat::CODE_39,
        "code93" => BarcodeFormat::CODE_93,
        "codabar" => BarcodeFormat::CODABAR,
        "ean13" => BarcodeFormat::EAN_13,
        "ean8" => BarcodeFormat::EAN_8,
        "upca" => BarcodeFormat::UPC_A,
        "upce" => BarcodeFormat::UPC_E,
        "itf" => BarcodeFormat::ITF,
        "maxicode" => BarcodeFormat::MAXICODE,
        _ => return None,
    })
}

/// rxing's display names carry spaces (`"pdf 417"`); use the compact form.
pub fn format_name(format: &BarcodeFormat) -> String {
    format.to_string().to_ascii_lowercase().replace([' ', '_', '-'], "")
}

/// The symbologies an identity document can carry.
pub const ID_FORMATS: &[&str] = &["pdf417", "code39", "code128", "itf", "qrcode", "datamatrix"];

/// The 2-D symbologies, each read by its own detector.
const MATRIX: &[BarcodeFormat] = &[BarcodeFormat::QR_CODE, BarcodeFormat::DATA_MATRIX, BarcodeFormat::AZTEC, BarcodeFormat::PDF_417, BarcodeFormat::MAXICODE];

/// What a call asks for: every symbology, or the named ones.
struct Wanted(Option<HashSet<BarcodeFormat>>);

impl Wanted {
    fn new(formats: Option<&[String]>) -> Wanted {
        let set: Option<HashSet<BarcodeFormat>> = formats.map(|f| f.iter().filter_map(|f| format_from_name(f)).collect());
        // Names that match nothing mean all, as an empty list does.
        Wanted(set.filter(|s| !s.is_empty()))
    }
    fn has(&self, f: BarcodeFormat) -> bool {
        self.0.as_ref().is_none_or(|s| s.contains(&f))
    }
    fn linear(&self) -> HashSet<BarcodeFormat> {
        LINEAR.iter().copied().filter(|f| self.has(*f)).collect()
    }
}

/// The linear symbologies rxing reads.
const LINEAR: &[BarcodeFormat] = &[
    BarcodeFormat::CODE_128,
    BarcodeFormat::CODE_39,
    BarcodeFormat::CODE_93,
    BarcodeFormat::CODABAR,
    BarcodeFormat::EAN_13,
    BarcodeFormat::EAN_8,
    BarcodeFormat::UPC_A,
    BarcodeFormat::UPC_E,
    BarcodeFormat::ITF,
];

/// Reads every barcode. Each 2-D symbology has its own multi-symbol search,
/// on the frame, on its negative (light-on-dark codes) and, for QR, Data
/// Matrix and Aztec, on a finer local-mean binarisation; PDF417 is retried on
/// a copy levelled by the estimated skew. Linear codes are found first
/// (patches of parallel bars at any angle, [`oriented_regions`]) and each
/// patch is decoded on its own, squared up, with a cheap row scan of the whole
/// frame besides.
///
/// This replaced rxing's `GenericMultipleBarcodeReader` over every format,
/// which decodes one code and recurses into the strips around it: its
/// `TryHarder` 1-D row scan of every strip was most of the time, the first
/// format to decode in a strip hid the others, and its Aztec detector only
/// finds a code near the middle of the image.
pub fn read_all(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    if w < 16 || h < 16 || luma.len() != (w * h) as usize {
        return Vec::new();
    }
    let wanted = Wanted::new(formats);
    let mut found: Vec<Barcode> = Vec::new();
    if MATRIX.iter().any(|f| wanted.has(*f)) {
        read_matrix(luma, w, h, &wanted, false, &mut found);
        let negative: Vec<u8> = luma.iter().map(|v| 255 - v).collect();
        read_matrix(&negative, w, h, &wanted, true, &mut found);
        // A third binarisation, against the mean of a 31-pixel square: finer
        // than the hybrid binariser's 40-pixel blocks, it keeps the modules of
        // small and unevenly lit codes apart (zxing-cpp's local-average idea).
        let fine: HashSet<BarcodeFormat> = [BarcodeFormat::QR_CODE, BarcodeFormat::DATA_MATRIX, BarcodeFormat::AZTEC].into_iter().filter(|f| wanted.has(*f)).collect();
        if !fine.is_empty() {
            let local = local_mean_threshold(luma, w as usize, h as usize, LOCAL_RADIUS, LOCAL_OFFSET);
            read_matrix(&local, w, h, &Wanted(Some(fine)), true, &mut found);
        }
        if wanted.has(BarcodeFormat::PDF_417) && !found.iter().any(|b| b.format == "pdf417") {
            pdf417_levelled(luma, w, h, &mut found);
        }
    }
    let linear = wanted.linear();
    let mut regions = Vec::new();
    if !linear.is_empty() {
        regions = oriented_regions(luma, w as usize, h as usize);
        read_linear(luma, w, h, &linear, &regions, &mut found);
    }
    drop_nested_reads(found, &regions)
}

/// Opt-in exhaustive matrix retry: the unchanged first pass, then at most
/// two additional matrix-only searches (clockwise 90 degrees and half size).
/// Linear formats and MaxiCode are never retried. All points refer to the
/// original input; existing reads win format/text duplicates, including bytes.
/// This is deliberately separate from [`read_all`]: it costs extra scans.
/// The pass count is bounded, but the underlying decoder has no time budget.
pub fn read_all_with_matrix_retries(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    read_with_matrix_retries(luma, w, h, formats, false)
}

/// Cheaper opt-in fallback: only an empty first pass gets one half-size
/// matrix search. A successful first pass is returned without retry work.
pub fn read_all_with_empty_matrix_retry(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    read_with_matrix_retries(luma, w, h, formats, true)
}

fn matrix_retry_formats(formats: Option<&[String]>) -> Vec<String> {
    let wanted = Wanted::new(formats);
    [BarcodeFormat::QR_CODE, BarcodeFormat::DATA_MATRIX, BarcodeFormat::AZTEC, BarcodeFormat::PDF_417]
        .into_iter()
        .filter(|f| wanted.has(*f))
        .map(|f| format_name(&f))
        .collect()
}

fn read_with_matrix_retries(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>, empty_only: bool) -> Vec<Barcode> {
    // Check before calling the unchanged reader, whose size check uses u32.
    if w < 16 || h < 16 || w.checked_mul(h).is_none_or(|n| n as usize != luma.len()) {
        return Vec::new();
    }
    let mut found = read_all(luma, w, h, formats);
    if empty_only && !found.is_empty() {
        return found;
    }
    let retry_formats = matrix_retry_formats(formats);
    // An empty format list means ALL to read_all, so never pass one to it.
    if retry_formats.is_empty() {
        return found;
    }
    if !empty_only {
        merge_matrix_retry(&mut found, luma, w, h, &retry_formats, MatrixRetry::Clockwise);
    }
    if w >= 32 && h >= 32 {
        merge_matrix_retry(&mut found, luma, w, h, &retry_formats, MatrixRetry::Half);
    }
    found
}

#[derive(Clone, Copy)]
enum MatrixRetry {
    Clockwise,
    Half,
}

impl MatrixRetry {
    fn original_point(self, p: [f32; 2], w: u32, h: u32) -> [f32; 2] {
        match self {
            Self::Clockwise => [p[1], (h - 1) as f32 - p[0]],
            Self::Half => [(p[0] + 0.5) * w as f32 / (w / 2) as f32 - 0.5, (p[1] + 0.5) * h as f32 / (h / 2) as f32 - 0.5],
        }
    }

    fn image(self, luma: &[u8], w: u32, h: u32) -> (Vec<u8>, u32, u32) {
        match self {
            Self::Clockwise => {
                let mut rotated = vec![0; luma.len()];
                for y in 0..h {
                    for x in 0..w {
                        rotated[(x * h + h - 1 - y) as usize] = luma[(y * w + x) as usize];
                    }
                }
                (rotated, h, w)
            }
            Self::Half => {
                let (tw, th) = (w / 2, h / 2);
                let mut small = vec![0; (tw * th) as usize];
                // Exact area weights in integer coordinates. Unlike a 2x2
                // crop this includes the last row/column of odd-size inputs.
                for y in 0..th {
                    let (y0, y1) = (u64::from(y) * u64::from(h), u64::from(y + 1) * u64::from(h));
                    for x in 0..tw {
                        let (x0, x1) = (u64::from(x) * u64::from(w), u64::from(x + 1) * u64::from(w));
                        let mut sum = 0u64;
                        for sy in y0 / u64::from(th)..y1.div_ceil(u64::from(th)) {
                            let wy = y1.min((sy + 1) * u64::from(th)) - y0.max(sy * u64::from(th));
                            for sx in x0 / u64::from(tw)..x1.div_ceil(u64::from(tw)) {
                                let wx = x1.min((sx + 1) * u64::from(tw)) - x0.max(sx * u64::from(tw));
                                sum += u64::from(luma[(sy * u64::from(w) + sx) as usize]) * wx * wy;
                            }
                        }
                        let area = u64::from(w) * u64::from(h);
                        small[(y * tw + x) as usize] = ((sum + area / 2) / area) as u8;
                    }
                }
                (small, tw, th)
            }
        }
    }
}

fn merge_matrix_retry(found: &mut Vec<Barcode>, luma: &[u8], w: u32, h: u32, formats: &[String], retry: MatrixRetry) {
    let (image, rw, rh) = retry.image(luma, w, h);
    for mut b in read_all(&image, rw, rh, Some(formats)) {
        for p in &mut b.points {
            *p = retry.original_point(*p, w, h);
        }
        push(found, b);
    }
}

fn push(out: &mut Vec<Barcode>, b: Barcode) {
    if !out.iter().any(|o| o.format == b.format && o.text == b.text) {
        out.push(b);
    }
}

fn to_barcode(r: &RXingResult, map: impl Fn([f32; 2]) -> [f32; 2]) -> Barcode {
    Barcode {
        format: format_name(r.getBarcodeFormat()),
        text: r.getText().to_string(),
        bytes: r.getRawBytes().to_vec(),
        points: r.getPoints().iter().map(|p| map([p.x, p.y])).collect(),
    }
}

fn hints(formats: HashSet<BarcodeFormat>, try_harder: bool) -> DecodeHints {
    DecodeHints::default().with(DecodeHintValue::TryHarder(try_harder)).with(DecodeHintValue::PossibleFormats(formats))
}

fn bitmap(luma: &[u8], w: u32, h: u32) -> Option<BinaryBitmap<HybridBinarizer<Luma8LuminanceSource>>> {
    Some(BinaryBitmap::new(HybridBinarizer::new(Luma8LuminanceSource::new(luma.to_vec(), w, h).ok()?)))
}

/// QR (zxing-cpp's multi-symbol detector), Data Matrix, PDF417 and Aztec on
/// one binarisation. `negative`: the image is inverted, for light-on-dark
/// codes; PDF417 and MaxiCode are not printed that way.
fn read_matrix(luma: &[u8], w: u32, h: u32, wanted: &Wanted, negative: bool, out: &mut Vec<Barcode>) {
    let Some(mut bmp) = bitmap(luma, w, h) else { return };
    let harder = DecodeHints::default().with(DecodeHintValue::TryHarder(true));
    if wanted.has(BarcodeFormat::QR_CODE)
        && let Ok(rs) = QrReader.decode_multiple_with_hints(&mut bmp, &harder)
    {
        for r in rs {
            push(out, to_barcode(&r, |p| p));
        }
    }
    if wanted.has(BarcodeFormat::DATA_MATRIX) {
        read_data_matrices(bmp.get_black_matrix(), out);
    }
    if !negative && wanted.has(BarcodeFormat::PDF_417) {
        read_pdf417s(&mut bmp, out);
    }
    if wanted.has(BarcodeFormat::AZTEC) {
        read_aztecs(luma, w, h, &mut bmp, out);
    }
    if !negative && wanted.has(BarcodeFormat::MAXICODE)
        && let Ok(r) = rxing::maxicode::MaxiCodeReader::default().decode_with_hints(&mut bmp, &harder)
    {
        push(out, to_barcode(&r, |p| p));
    }
}

/// PDF417: rxing's multi-symbol search; when it finds none, the
/// single-symbol one, then that in the strips beside each code already read
/// (as rxing's recursive reader did): another code beside a small PDF417
/// throws its row detector off.
fn read_pdf417s<B: Binarizer>(bmp: &mut BinaryBitmap<B>, out: &mut Vec<Barcode>) {
    let harder = DecodeHints::default().with(DecodeHintValue::TryHarder(true));
    if let Ok(rs) = PDF417Reader::new().decode_multiple_with_hints(bmp, &harder) {
        for r in rs {
            push(out, to_barcode(&r, |p| p));
        }
    }
    if out.iter().any(|b| b.format == "pdf417") {
        return;
    }
    if let Ok(r) = PDF417Reader::new().decode_with_hints(bmp, &harder) {
        push(out, to_barcode(&r, |p| p));
        return;
    }
    // The strips left, right, above and below each code already read.
    let (w, h) = (bmp.get_width() as f32, bmp.get_height() as f32);
    let boxes: Vec<[f32; 4]> = out
        .iter()
        .filter(|b| !b.points.is_empty())
        .map(|b| {
            let xs = b.points.iter().map(|p| p[0]);
            let ys = b.points.iter().map(|p| p[1]);
            [xs.clone().fold(f32::MAX, f32::min), ys.clone().fold(f32::MAX, f32::min), xs.fold(f32::MIN, f32::max), ys.fold(f32::MIN, f32::max)]
        })
        .collect();
    for [x0, y0, x1, y1] in boxes {
        let strips = [(0.0, 0.0, x0, h), (x1, 0.0, w - x1, h), (0.0, 0.0, w, y0), (0.0, y1, w, h - y1)];
        for (sx, sy, sw, sh) in strips {
            if sw < 100.0 || sh < 100.0 {
                continue;
            }
            let mut strip = bmp.crop(sx.max(0.0) as usize, sy.max(0.0) as usize, sw as usize, sh as usize);
            if let Ok(r) = PDF417Reader::new().decode_with_hints(&mut strip, &harder) {
                push(out, to_barcode(&r, |p| [p[0] + sx, p[1] + sy]));
                return;
            }
        }
    }
}

/// rxing's port of zxing-cpp's Data Matrix detector returns candidates from
/// scan lines across the image, but each line stops at its first symbol: a
/// second Data Matrix behind the first is never reached. Every candidate is
/// decoded, the symbols read are blanked out of the bit matrix, and the
/// search repeated while it finds new ones.
fn read_data_matrices(matrix: &BitMatrix, out: &mut Vec<Barcode>) {
    let mut m = matrix.clone();
    let decoder = rxing::datamatrix::decoder::Decoder::new();
    for _ in 0..4 {
        let Ok(symbols) = rxing::datamatrix::detector::zxing_cpp_detector::detect(&m, true, true) else { break };
        let mut any = false;
        for s in &symbols {
            let points = s.getPoints().to_vec();
            let (x0, x1) = points.iter().fold((f32::MAX, f32::MIN), |a, p| (a.0.min(p.x), a.1.max(p.x)));
            let (y0, y1) = points.iter().fold((f32::MAX, f32::MIN), |a, p| (a.0.min(p.y), a.1.max(p.y)));
            let (x0, y0) = ((x0 - 2.0).max(0.0) as u32, (y0 - 2.0).max(0.0) as u32);
            let (x1, y1) = (((x1 + 3.0).max(0.0) as u32).min(m.getWidth()), ((y1 + 3.0).max(0.0) as u32).min(m.getHeight()));
            // Blanked already: a second candidate of a symbol just decoded.
            if x1 <= x0 || y1 <= y0 || !m.get((x0 + x1) / 2, (y0 + y1) / 2) && (y0..y1).all(|y| (x0..x1).all(|x| !m.get(x, y))) {
                continue;
            }
            let Ok(d) = decoder.decode(s.getBits()) else { continue };
            for y in y0..y1 {
                for x in x0..x1 {
                    m.unset(x, y);
                }
            }
            any = true;
            let r = RXingResult::new(d.getText(), d.getRawBytes().clone(), points, BarcodeFormat::DATA_MATRIX);
            push(out, to_barcode(&r, |p| p));
        }
        if !any {
            break;
        }
    }
}

/// rxing's Aztec detector looks for the bull's eye from the middle of the
/// image, so it reads a code only when the image is centred on it. The
/// whole frame is tried, then a crop centred on each bull's eye found by a
/// scan for seven equal rings ([`bullseyes`]).
fn read_aztecs(luma: &[u8], w: u32, h: u32, bmp: &mut BinaryBitmap<HybridBinarizer<Luma8LuminanceSource>>, out: &mut Vec<Barcode>) {
    let harder = DecodeHints::default().with(DecodeHintValue::TryHarder(true));
    if let Ok(r) = AztecReader.decode_with_hints(bmp, &harder) {
        push(out, to_barcode(&r, |p| p));
    }
    for (cx, cy, module) in bullseyes(bmp.get_black_matrix()).into_iter().take(8) {
        // A compact Aztec is up to 27 modules across, a full one up to 151:
        // a tight crop first, then a wide one. The tight one is also tried
        // enlarged 2× (bilinear) when its modules are small: the bull's-eye
        // tracer needs it when blur closes up the rings of a code with three or
        // four pixels per module.
        for (reach, k) in [(20.0f32, 1), (20.0, 2), (45.0, 1)] {
            if k == 2 && module > 5.0 {
                continue;
            }
            let r = (reach * module).clamp(24.0, 400.0);
            let (x0, y0) = ((cx - r).max(0.0) as usize, (cy - r).max(0.0) as usize);
            let (x1, y1) = (((cx + r) as usize).min(w as usize), ((cy + r) as usize).min(h as usize));
            if x1 < x0 + 16 || y1 < y0 + 16 {
                continue;
            }
            let (cw, ch) = (x1 - x0, y1 - y0);
            let crop = crop(luma, w as usize, x0, y0, x1, y1);
            let (crop, cw, ch) = if k == 1 { (crop, cw, ch) } else { upsample(&crop, cw, ch, k) };
            let Some(mut cb) = bitmap(&crop, cw as u32, ch as u32) else { continue };
            if let Ok(res) = AztecReader.decode_with_hints(&mut cb, &harder) {
                push(out, to_barcode(&res, |p| [p[0] / k as f32 + x0 as f32, p[1] / k as f32 + y0 as f32]));
                break;
            }
        }
    }
}

/// The local-mean binarisation's square (`2r + 1` pixels) and the margin below
/// the mean that counts as dark.
const LOCAL_RADIUS: usize = 15;
const LOCAL_OFFSET: i32 = 4;

/// Black (0) where a pixel is darker than the mean of the `(2r + 1)²` square
/// around it by more than `c`, white (255) elsewhere (an integral image).
fn local_mean_threshold(luma: &[u8], w: usize, h: usize, r: usize, c: i32) -> Vec<u8> {
    let mut sum = vec![0u32; (w + 1) * (h + 1)];
    for y in 0..h {
        let mut row = 0u32;
        for x in 0..w {
            row += luma[y * w + x] as u32;
            sum[(y + 1) * (w + 1) + x + 1] = sum[y * (w + 1) + x + 1] + row;
        }
    }
    let mut out = vec![255u8; w * h];
    for y in 0..h {
        let (y0, y1) = (y.saturating_sub(r), (y + r + 1).min(h));
        for x in 0..w {
            let (x0, x1) = (x.saturating_sub(r), (x + r + 1).min(w));
            let total = sum[y1 * (w + 1) + x1] + sum[y0 * (w + 1) + x0] - sum[y0 * (w + 1) + x1] - sum[y1 * (w + 1) + x0];
            let mean = (total / ((y1 - y0) * (x1 - x0)) as u32) as i32;
            if (luma[y * w + x] as i32) < mean - c {
                out[y * w + x] = 0;
            }
        }
    }
    out
}

/// Bilinear enlargement by `k` in both directions.
fn upsample(img: &[u8], w: usize, h: usize, k: usize) -> (Vec<u8>, usize, usize) {
    let (nw, nh) = (w * k, h * k);
    let mut out = vec![0u8; nw * nh];
    for y in 0..nh {
        for x in 0..nw {
            let sx = ((x as f32 + 0.5) / k as f32).clamp(0.5, w as f32 - 0.5);
            let sy = ((y as f32 + 0.5) / k as f32).clamp(0.5, h as f32 - 0.5);
            out[y * nw + x] = bilinear(img, w, h, sx, sy);
        }
    }
    (out, nw, nh)
}

fn crop(luma: &[u8], w: usize, x0: usize, y0: usize, x1: usize, y1: usize) -> Vec<u8> {
    let mut p = Vec::with_capacity((x1 - x0) * (y1 - y0));
    for y in y0..y1 {
        p.extend_from_slice(&luma[y * w + x0..y * w + x1]);
    }
    p
}

/// Runs of one colour along a row (`horizontal`) or a column, between `from`
/// and `to`: (dark, start, length).
fn runs(m: &BitMatrix, horizontal: bool, line: u32, from: u32, to: u32) -> Vec<(bool, u32, u32)> {
    let get = |i: u32| if horizontal { m.get(i, line) } else { m.get(line, i) };
    let mut out = Vec::new();
    if to <= from {
        return out;
    }
    let (mut colour, mut start) = (get(from), from);
    for i in from + 1..to {
        let v = get(i);
        if v != colour {
            out.push((colour, start, i - start));
            (colour, start) = (v, i);
        }
    }
    out.push((colour, start, to - start));
    out
}

/// Seven runs of near-equal width, dark-light-…-dark centred on run `c`: the
/// rings of an Aztec bull's eye seen through its centre. Their mean width,
/// and their spread (mean absolute deviation over the mean).
fn rings(runs: &[(bool, u32, u32)], c: usize) -> Option<(f32, f32)> {
    if c < 3 || c + 3 >= runs.len() {
        return None;
    }
    let widths = runs[c - 3..=c + 3].iter().map(|r| r.2 as f32);
    let mean = widths.clone().sum::<f32>() / 7.0;
    let spread = widths.clone().map(|x| (x - mean).abs()).sum::<f32>() / 7.0 / mean;
    (mean >= 1.5 && widths.into_iter().all(|x| x > 0.5 * mean && x < 1.5 * mean)).then_some((mean, spread))
}

/// Candidate Aztec bull's-eye centres `(x, y, module)`, the most regular
/// first: the ring pattern across a row, confirmed down the column through
/// its middle.
pub fn bullseyes(m: &BitMatrix) -> Vec<(f32, f32, f32)> {
    let h = m.getHeight();
    let mut out: Vec<(f32, f32, f32, f32)> = Vec::new();
    for y in (2..h.saturating_sub(2)).step_by(2) {
        let row = runs(m, true, y, 0, m.getWidth());
        for c in 3..row.len().saturating_sub(3) {
            let Some((mh, sh)) = rings(&row, c) else { continue };
            let cx = row[c].1 as f32 + row[c].2 as f32 / 2.0;
            // The column through the middle, as far as the rings could reach.
            let reach = (12.0 * mh) as u32;
            let col = runs(m, false, cx as u32, y.saturating_sub(reach), (y + reach).min(h));
            let Some(ci) = col.iter().position(|r| r.1 <= y && y < r.1 + r.2) else { continue };
            let Some((mv, sv)) = rings(&col, ci).filter(|&(mv, _)| col[ci].0 == row[c].0 && mv > 0.6 * mh && mv < 1.6 * mh) else {
                continue;
            };
            let cy = col[ci].1 as f32 + col[ci].2 as f32 / 2.0;
            // And along a diagonal: a code's data seldom has seven equal runs
            // three ways through one point.
            let reach = (12.0 * mh) as i32;
            let line: Vec<bool> = (-reach..=reach)
                .map(|t| (cx as i32 + t, cy as i32 + t))
                .filter(|&(x, y)| x >= 0 && y >= 0 && (x as u32) < m.getWidth() && (y as u32) < h)
                .map(|(x, y)| m.get(x as u32, y as u32))
                .collect();
            let mut diag: Vec<(bool, u32, u32)> = Vec::new();
            for (i, &v) in line.iter().enumerate() {
                match diag.last_mut() {
                    Some(r) if r.0 == v => r.2 += 1,
                    _ => diag.push((v, i as u32, 1)),
                }
            }
            let mid = line.len() as u32 / 2;
            let Some(di) = diag.iter().position(|r| r.1 <= mid && mid < r.1 + r.2) else { continue };
            if rings(&diag, di).filter(|&(md, _)| diag[di].0 == row[c].0 && md > 0.5 * mh && md < 2.0 * mh).is_none() {
                continue;
            }
            let (module, spread) = ((mh + mv) / 2.0, sh + sv);
            match out.iter_mut().find(|p| (p.0 - cx).abs() < 3.0 * module && (p.1 - cy).abs() < 3.0 * module) {
                Some(p) if spread < p.3 => *p = (cx, cy, module, spread),
                Some(_) => {}
                None => out.push((cx, cy, module, spread)),
            }
        }
    }
    out.sort_by(|a, b| a.3.total_cmp(&b.3));
    out.into_iter().map(|(x, y, m, _)| (x, y, m)).collect()
}

/// PDF417 on a copy levelled by the estimated skew, points mapped back:
/// rxing's PDF417 row scanner gives up a few degrees off level.
fn pdf417_levelled(luma: &[u8], w: u32, h: u32, out: &mut Vec<Barcode>) {
    let skew = crate::geometry::estimate_skew(luma, w as usize, h as usize);
    if skew.abs() < 2.0 {
        return;
    }
    let (rot, rw, rh) = crate::geometry::rotate(luma, w as usize, h as usize, skew);
    let Some(mut bmp) = bitmap(&rot, rw as u32, rh as u32) else { return };
    let harder = DecodeHints::default().with(DecodeHintValue::TryHarder(true));
    let (s, c) = skew.to_radians().sin_cos();
    let (cx, cy, ncx, ncy) = (w as f32 / 2.0, h as f32 / 2.0, rw as f32 / 2.0, rh as f32 / 2.0);
    if let Ok(rs) = PDF417Reader::new().decode_multiple_with_hints(&mut bmp, &harder) {
        for r in rs {
            push(out, to_barcode(&r, |p| {
                let (dx, dy) = (p[0] - ncx, p[1] - ncy);
                [c * dx - s * dy + cx, s * dx + c * dy + cy]
            }));
        }
    }
}

/// Bar patches tried per frame at most, largest first.
const MAX_LINEAR_REGIONS: usize = 12;
/// Upsampling across the bars for the second try on a patch, with an unsharp
/// mask. Linear codes whose narrowest bars span little more than a pixel
/// alias to grey and defeat the binariser; bilinear upsampling and
/// sharpening restore an edge between neighbouring bars. (The HD test
/// sheet's Code 128s, about 1.2 px per module, needed 3-4×.)
const LINEAR_UPSAMPLE: f32 = 3.0;

/// Linear codes. Each bar patch on its own (largest first, a dozen at most),
/// cut out with its bars vertical: as it is, then upsampled and sharpened
/// across the bars ([`read_patch`]), then as an averaged profile
/// ([`read_profile`]). And a row scan of the whole frame (no `TryHarder`: the
/// middle rows each way) for codes the patch finder misses; a row-scan read
/// stands unless the patch it lies in read as another code.
fn read_linear(luma: &[u8], w: u32, h: u32, formats: &HashSet<BarcodeFormat>, regions: &[OrientedRegion], out: &mut Vec<Barcode>) {
    let quick = hints(formats.clone(), false);
    let mut rows: Vec<Barcode> = Vec::new();
    if let Some(mut bmp) = bitmap(luma, w, h)
        && let Ok(rs) = GenericMultipleBarcodeReader::new(MultiUseMultiFormatReader::default()).decode_multiple_with_hints(&mut bmp, &quick)
    {
        for r in rs {
            push(&mut rows, to_barcode(&r, |p| p));
        }
    }
    let middle = |b: &Barcode| match b.points[..] {
        [p0, p1] => Some([(p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0]),
        _ => None,
    };
    // Each patch, largest first, unless it holds a code a patch already gave.
    let mut patches: Vec<(OrientedRegion, Option<Barcode>)> = Vec::new();
    for r in regions {
        if patches.len() == MAX_LINEAR_REGIONS {
            break;
        }
        if patches.iter().any(|(_, b)| b.as_ref().and_then(middle).is_some_and(|m| r.contains(m, 0.0))) {
            continue;
        }
        let grown = r.grown(luma, w as usize, h as usize);
        // Quiet zone: the frame either side of the bars, 15% of their width:
        // UPC-E's end guard wants six modules of it.
        let pad = (grown.half_across * 0.3).max(12.0);
        let mut read = None;
        for (k, sharpen) in [(1.0f32, false), (LINEAR_UPSAMPLE, true)] {
            let (img, crop) = grown.sample(luma, w as usize, h as usize, pad, k);
            let img = if sharpen { unsharp_x(&img, crop.width, crop.height, 0.8 * k, 2.0) } else { img };
            if let Some(res) = read_patch(&img, crop.width, crop.height, 2.0 * r.half_across * k, formats) {
                read = Some(to_barcode(&res, |p| crop.to_frame(p)));
                break;
            }
        }
        if read.is_none() {
            read = read_profile(luma, w as usize, h as usize, &grown, pad, formats);
        }
        patches.push((*r, read));
    }
    for (_, b) in &patches {
        if let Some(b) = b {
            push(out, b.clone());
        }
    }
    // A row-scan read stands unless the patch it lies in read as another code
    // (the patch reading is checked twice over).
    for b in rows {
        let Some(m) = middle(&b) else {
            push(out, b);
            continue;
        };
        let patch = patches.iter().filter(|(r, _)| r.contains(m, 0.0)).min_by(|p, q| p.0.half_across.total_cmp(&q.0.half_across));
        let keep = match patch {
            None => true,
            Some((_, Some(read))) => read.format == b.format && read.text == b.text,
            Some((_, None)) => true,
        };
        if keep {
            push(out, b);
        }
    }
}

/// Symbologies the averaged-profile reading may return: those whose check
/// characters make a read from a reconstructed profile trustworthy.
const PROFILE_FORMATS: &[BarcodeFormat] = &[BarcodeFormat::CODE_128, BarcodeFormat::CODE_93, BarcodeFormat::EAN_13, BarcodeFormat::UPC_A];
/// Samples per frame pixel across the bars for the profile.
const PROFILE_K: f32 = 4.0;

/// The last try on a bar patch: the middle 60% of the bars averaged into one
/// profile (scratches, blots, glare and noise average out), its edges found
/// as the alternating extrema of its derivative (with sub-sample peaks), and
/// the bars redrawn crisp from those edges for the readers. Only a code with
/// a check character covering most of the patch is taken.
fn read_profile(luma: &[u8], w: usize, h: usize, r: &OrientedRegion, pad: f32, formats: &HashSet<BarcodeFormat>) -> Option<Barcode> {
    let allowed: HashSet<BarcodeFormat> = formats.iter().copied().filter(|f| PROFILE_FORMATS.contains(f)).collect();
    if allowed.is_empty() {
        return None;
    }
    let k = PROFILE_K;
    let ha = r.half_across + pad;
    let n = (2.0 * ha * k).ceil() as usize;
    let rows: Vec<f32> = (0..9).map(|i| (i as f32 / 8.0 - 0.5) * 1.2 * r.half_along).collect();
    let mut profile: Vec<f32> = (0..n)
        .map(|i| {
            let a = (i as f32 + 0.5) / k - ha;
            rows.iter().map(|&b| bilinear(luma, w, h, r.cx + a * r.ux - b * r.uy, r.cy + a * r.uy + b * r.ux) as f32).sum::<f32>() / rows.len() as f32
        })
        .collect();
    smooth(&mut profile, 0.3 * k);
    let hints = hints(allowed, true);
    for sharpen in [0.0f32, 0.6, 1.0] {
        let mut p = profile.clone();
        if sharpen > 0.0 {
            let mut g = p.clone();
            smooth(&mut g, sharpen * k);
            for (v, b) in p.iter_mut().zip(&g) {
                *v += 1.5 * (*v - b);
            }
        }
        let bars = redraw(&p);
        // A few identical rows, with a quiet zone on every side.
        let (bw, bh, margin) = (n + 80, 12, 40);
        let mut img = vec![255u8; bw * bh];
        for y in 2..bh - 2 {
            for (x, &dark) in bars.iter().enumerate() {
                if dark {
                    img[y * bw + margin + x] = 0;
                }
            }
        }
        let Some(res) = decode_linear(&img, bw, bh, &hints) else { continue };
        let [a, b] = res.getPoints()[..] else { continue };
        if (b.x - a.x).abs() < 0.8 * 2.0 * r.half_across * k {
            continue;
        }
        let to_frame = |p: [f32; 2]| {
            let a = (p[0] - margin as f32) / k - ha;
            [r.cx + a * r.ux, r.cy + a * r.uy]
        };
        return Some(to_barcode(&res, to_frame));
    }
    None
}

/// Gaussian smoothing of a profile in place.
fn smooth(p: &mut [f32], sigma: f32) {
    let rad = (3.0 * sigma).ceil() as isize;
    let kernel: Vec<f32> = (-rad..=rad).map(|i| (-(i * i) as f32 / (2.0 * sigma * sigma)).exp()).collect();
    let total: f32 = kernel.iter().sum();
    let src = p.to_vec();
    let n = src.len() as isize;
    for i in 0..n {
        let acc: f32 = kernel.iter().enumerate().map(|(j, kv)| src[(i + j as isize - rad).clamp(0, n - 1) as usize] * kv).sum();
        p[i as usize] = acc / total;
    }
}

/// Bars from a profile: dark from each falling edge to the next rising one,
/// the edges being the derivative's alternating extrema above 12% of its
/// largest, placed to a fraction of a sample by a parabola.
fn redraw(p: &[f32]) -> Vec<bool> {
    let n = p.len();
    let mut d = vec![0f32; n];
    for i in 1..n.saturating_sub(1) {
        d[i] = (p[i + 1] - p[i - 1]) / 2.0;
    }
    let floor = 0.12 * d.iter().fold(0f32, |m, v| m.max(v.abs()));
    let mut edges: Vec<(f32, bool, f32)> = Vec::new(); // (position, rising, strength)
    for i in 1..n.saturating_sub(1) {
        let (a, b, c) = (d[i - 1], d[i], d[i + 1]);
        let peak = (b > 0.0 && b >= a && b > c) || (b < 0.0 && b <= a && b < c);
        if !peak || b.abs() < floor {
            continue;
        }
        let den = a - 2.0 * b + c;
        let at = i as f32 + if den != 0.0 { 0.5 * (a - c) / den } else { 0.0 };
        let rising = b > 0.0;
        match edges.last_mut() {
            Some(last) if last.1 == rising => {
                if b.abs() > last.2.abs() {
                    *last = (at, rising, b);
                }
            }
            _ => edges.push((at, rising, b)),
        }
    }
    let mut bars = vec![false; n];
    for pair in edges.windows(2) {
        if !pair[0].1 && pair[1].1 {
            let (from, to) = (pair[0].0.round().max(0.0) as usize, (pair[1].0.round() as usize).min(n));
            bars[from..to].iter_mut().for_each(|v| *v = true);
        }
    }
    bars
}

/// The linear code in a bar patch cut out with its bars vertical (`bars`
/// pixels of it across them). A weak code or an ITF covering little of the
/// bars is part of a longer code (an EAN-8 inside a UPC-A's bars): its format
/// is set aside and the patch read again. The other two thirds of the patch,
/// read on their own, must not read another code: a single row through
/// blurred bars sometimes misreads into another valid code (zxing-cpp asks
/// for two rows); and a weak code (UPC-E, EAN-8) must be read again in one of
/// them, which keeps the readers from finding one in stripes or ruled lines.
fn read_patch(img: &[u8], w: usize, h: usize, bars: f32, formats: &HashSet<BarcodeFormat>) -> Option<RXingResult> {
    let mut formats = formats.clone();
    for _ in 0..3 {
        let harder = hints(formats.clone(), true);
        let res = decode_linear(img, w, h, &harder)?;
        let name = format_name(res.getBarcodeFormat());
        if let [a, b] = res.getPoints()[..]
            && PARTIAL_PRONE.contains(&name.as_str())
            && (b.x - a.x).abs() < partial_share(&name) * bars
        {
            formats.remove(res.getBarcodeFormat());
            continue;
        }
        let row = res.getPoints().first().map_or(0.0, |p| p.y) as usize;
        let third = h / 3;
        let (mut agree, mut differ) = (0, 0);
        if third >= 4 {
            for band in 0..3 {
                let (y0, y1) = (band * third, if band == 2 { h } else { (band + 1) * third });
                if (y0..y1).contains(&row) {
                    continue;
                }
                match decode_linear(&img[y0 * w..y1 * w], w, y1 - y0, &harder) {
                    Some(o) if o.getText() == res.getText() && o.getBarcodeFormat() == res.getBarcodeFormat() => agree += 1,
                    Some(_) => differ += 1,
                    None => {}
                }
            }
        }
        let weak = matches!(res.getBarcodeFormat(), BarcodeFormat::UPC_E | BarcodeFormat::EAN_8);
        if differ > 0 || (weak && third >= 4 && agree == 0) {
            return None;
        }
        return Some(res);
    }
    None
}

/// The share of its bar patch under which a [`PARTIAL_PRONE`] read is part of
/// a longer code. EAN-8 is the one read inside a UPC-A or EAN-13 (67 of their
/// 95 modules); UPC-E prints a digit beside each end of its bars, which the
/// patch includes.
fn partial_share(format: &str) -> f32 {
    if format == "ean8" { 0.8 } else { 0.6 }
}

fn decode_linear(img: &[u8], w: usize, h: usize, hints: &DecodeHints) -> Option<RXingResult> {
    let mut bmp = bitmap(img, w as u32, h as u32)?;
    MultiFormatOneDReader::new(hints).decode_with_hints(&mut bmp, hints).ok()
}

/// Short, weakly checked linear codes, which a reader finds in part of
/// another symbol's bars.
const WEAK_LINEAR: &[&str] = &["upce", "ean8"];

/// Drops partial reads. A weak short code (UPC-E, EAN-8) read along the bars
/// of a longer linear code in the same frame: two real codes cannot overlap,
/// and a UPC-E inside an EAN-13's bars, read on a scan line near its foot, has
/// a valid check digit often enough to show up on dense sheets. The bar patch
/// (`regions`) holding the longer code gives its real extent; without one,
/// the bars are taken to be up to 0.8 of the code's width tall. And a weak
/// code or an ITF covering little of the bar patch it lies in, or an ITF
/// inside another ITF's digits ([`PARTIAL_PRONE`]).
pub fn drop_nested_reads(codes: Vec<Barcode>, regions: &[OrientedRegion]) -> Vec<Barcode> {
    let segment = |b: &Barcode| -> Option<([f32; 2], [f32; 2])> { (b.points.len() == 2).then(|| (b.points[0], b.points[1])) };
    let middle = |b: &Barcode| {
        let n = b.points.len().max(1) as f32;
        let (x, y) = b.points.iter().fold((0.0, 0.0), |a, p| (a.0 + p[0], a.1 + p[1]));
        [x / n, y / n]
    };
    let inside = |inner: &Barcode, outer: &Barcode| -> bool {
        let (Some((a0, a1)), Some((b0, b1))) = (segment(inner), segment(outer)) else { return false };
        if let Some(r) = regions.iter().find(|r| r.contains(middle(outer), 4.0)) {
            return r.contains(middle(inner), 4.0);
        }
        let (dx, dy) = (b1[0] - b0[0], b1[1] - b0[1]);
        let len = (dx * dx + dy * dy).sqrt();
        if len < 1.0 {
            return false;
        }
        let (ux, uy) = (dx / len, dy / len);
        // Each end of the inner scan line, along and across the outer one.
        let place = |p: [f32; 2]| {
            let (px, py) = (p[0] - b0[0], p[1] - b0[1]);
            (px * ux + py * uy, (px * uy - py * ux).abs())
        };
        let ((s0, d0), (s1, d1)) = (place(a0), place(a1));
        let slack = 0.05 * len;
        // Within the outer code's extent, and within its bars' height,
        // which is a good fraction of its width on any 1D symbol.
        s0.min(s1) >= -slack && s0.max(s1) <= len + slack && d0.max(d1) <= 0.8 * len
    };
    // A partial read: a weak code or an ITF (no check digit) spanning well
    // under the width of the smallest bar patch it lies in, or an ITF whose
    // digits are part of another ITF's.
    let partial = |c: &Barcode| -> bool {
        if !PARTIAL_PRONE.contains(&c.format.as_str()) {
            return false;
        }
        if c.format == "itf" && codes.iter().any(|o| !std::ptr::eq(o, c) && o.format == "itf" && o.text.len() > c.text.len() && o.text.contains(&c.text)) {
            return true;
        }
        let Some((a, b)) = segment(c) else { return false };
        let span = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
        let smallest = regions.iter().filter(|r| r.contains(middle(c), 4.0)).min_by(|p, q| p.half_across.total_cmp(&q.half_across));
        smallest.is_some_and(|r| span < partial_share(&c.format) * 2.0 * r.half_across)
    };
    let keep: Vec<bool> = codes
        .iter()
        .map(|c| {
            !partial(c)
                && (!WEAK_LINEAR.contains(&c.format.as_str())
                    || !codes.iter().any(|o| !std::ptr::eq(o, c) && !WEAK_LINEAR.contains(&o.format.as_str()) && inside(c, o)))
        })
        .collect();
    codes.into_iter().zip(keep).filter_map(|(c, k)| k.then_some(c)).collect()
}

/// Linear codes a row through part of another code's bars can read: weakly
/// checked short codes, and ITF, which has no check digit at all.
const PARTIAL_PRONE: &[&str] = &["upce", "ean8", "itf"];

/// A patch of parallel bars at any angle: its centre, the unit vector across
/// the bars, and its half extents across and along them, in frame pixels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OrientedRegion {
    pub cx: f32,
    pub cy: f32,
    pub ux: f32,
    pub uy: f32,
    pub half_across: f32,
    pub half_along: f32,
    /// Cells in the patch: its size, for ordering.
    pub cells: usize,
}

impl OrientedRegion {
    /// The patch's axis-aligned bounding box in the frame: `[x, y, w, h]`.
    pub fn bounds(&self) -> [f32; 4] {
        let ex = self.ux.abs() * self.half_across + self.uy.abs() * self.half_along;
        let ey = self.uy.abs() * self.half_across + self.ux.abs() * self.half_along;
        [self.cx - ex, self.cy - ey, 2.0 * ex, 2.0 * ey]
    }

    /// Whether `p` lies within the patch, grown by `slack` pixels.
    pub fn contains(&self, p: [f32; 2], slack: f32) -> bool {
        let (dx, dy) = (p[0] - self.cx, p[1] - self.cy);
        (dx * self.ux + dy * self.uy).abs() <= self.half_across + slack && (-dx * self.uy + dy * self.ux).abs() <= self.half_along + slack
    }

    /// The patch as an image with its bars vertical, `pad` pixels either
    /// side of the bars, `k` samples per pixel across them. Near an axis (within
    /// [`SNAP_DEGREES`], and while a row drifts less than half the bars'
    /// height over the code's length) it is cut straight from the frame,
    /// transposed when the bars lie across: rows still cross every bar of a
    /// slanted code, and no resampling blurs it. Otherwise it is resampled
    /// square (bilinear).
    pub fn sample(&self, luma: &[u8], w: usize, h: usize, pad: f32, k: f32) -> (Vec<u8>, Crop) {
        let (ha, hb) = (self.half_across + pad, self.half_along.max(6.0));
        // Snapped only while a straight row stays within the bars from one end
        // to the other: a long code tilted a few degrees drifts off its rows.
        let snap = SNAP_DEGREES.to_radians().sin();
        let off_axis = self.uy.abs().min(self.ux.abs());
        if off_axis < snap && 2.0 * ha * off_axis < hb {
            let transposed = self.ux.abs() < self.uy.abs();
            // The box's extent in the frame.
            let (ex, ey) = (self.ux.abs() * ha + self.uy.abs() * hb, self.uy.abs() * ha + self.ux.abs() * hb);
            let x0 = (self.cx - ex).floor().max(0.0) as usize;
            let y0 = (self.cy - ey).floor().max(0.0) as usize;
            let x1 = ((self.cx + ex).ceil() as usize).min(w);
            let y1 = ((self.cy + ey).ceil() as usize).min(h);
            let (cw, ch) = (x1.saturating_sub(x0).max(1), y1.saturating_sub(y0).max(1));
            // Columns across the bars, rows along them.
            let (across, along) = if transposed { (ch, cw) } else { (cw, ch) };
            let ow = ((across as f32) * k).round() as usize;
            let mut out = vec![0u8; ow * along];
            for r in 0..along {
                for x in 0..ow {
                    let t = ((x as f32 + 0.5) / k - 0.5).clamp(0.0, (across - 1) as f32);
                    let (t0, f) = (t as usize, t.fract());
                    let t1 = (t0 + 1).min(across - 1);
                    let at = |i: usize| if transposed { luma[(y0 + i) * w + x0 + r] } else { luma[(y0 + r) * w + x0 + i] } as f32;
                    out[r * ow + x] = (at(t0) * (1.0 - f) + at(t1) * f).round() as u8;
                }
            }
            return (out, Crop { width: ow, height: along, map: CropMap::Axis { x0: x0 as f32, y0: y0 as f32, transposed, k } });
        }
        let (ow, oh) = ((2.0 * ha * k).ceil() as usize, (2.0 * hb).ceil() as usize);
        let mut out = vec![0u8; ow * oh];
        for y in 0..oh {
            let b = y as f32 + 0.5 - hb;
            for x in 0..ow {
                let a = (x as f32 + 0.5) / k - ha;
                out[y * ow + x] = bilinear(luma, w, h, self.cx + a * self.ux - b * self.uy, self.cy + a * self.uy + b * self.ux);
            }
        }
        (out, Crop { width: ow, height: oh, map: CropMap::Rotated { region: *self, ha, hb, k } })
    }

    /// The patch grown across its bars to the quiet zone on each side: the
    /// cells at a code's ends can miss the bar test (a blurred or slanted
    /// edge, a shadow), and a crop that cuts the first bars cannot decode.
    /// Walks out along the middle line until the gap since the last edge is
    /// three times the patch's mean bar width.
    pub fn grown(&self, luma: &[u8], w: usize, h: usize) -> OrientedRegion {
        let reach = self.half_across * 0.5;
        let n = (2.0 * (self.half_across + reach)).ceil() as usize;
        // The mean of three lines along the bars' middle half, one sample per pixel.
        let profile: Vec<f32> = (0..n)
            .map(|i| {
                let a = i as f32 + 0.5 - self.half_across - reach;
                [-0.25f32, 0.0, 0.25]
                    .iter()
                    .map(|f| {
                        let b = f * self.half_along;
                        bilinear(luma, w, h, self.cx + a * self.ux - b * self.uy, self.cy + a * self.uy + b * self.ux) as f32
                    })
                    .sum::<f32>()
                    / 3.0
            })
            .collect();
        let (lo, hi) = (reach as usize, (reach + 2.0 * self.half_across) as usize).min((n - 1, n - 1));
        let inside = &profile[lo..hi.max(lo + 1)];
        let (min, max) = inside.iter().fold((f32::MAX, f32::MIN), |a, &v| (a.0.min(v), a.1.max(v)));
        let step = 0.12 * (max - min);
        let edge = |i: usize| i > 0 && i + 1 < n && (profile[i + 1] - profile[i - 1]).abs() > step;
        let edges = (lo..hi).filter(|&i| edge(i) && !edge(i - 1)).count().max(1);
        let gap = (3.0 * (hi - lo) as f32 / edges as f32).clamp(6.0, 40.0) as usize;
        let walk = |from: usize, dir: isize| -> f32 {
            let (mut last, mut i) = (from as isize, from as isize);
            while i > 0 && (i as usize) < n - 1 && ((i - last).unsigned_abs()) <= gap {
                if edge(i as usize) {
                    last = i;
                }
                i += dir;
            }
            (last - from as isize).unsigned_abs() as f32
        };
        let (left, right) = (walk(lo, -1), walk(hi, 1));
        let shift = (right - left) / 2.0;
        OrientedRegion {
            cx: self.cx + shift * self.ux,
            cy: self.cy + shift * self.uy,
            half_across: self.half_across + (left + right) / 2.0,
            ..*self
        }
    }

}

/// Within this many degrees of an axis, a bar patch is cut from the frame
/// rather than resampled.
const SNAP_DEGREES: f32 = 22.0;

/// A bar patch cut out by [`OrientedRegion::sample`]: its size, and how its
/// pixels map back to the frame.
#[derive(Debug, Clone, Copy)]
pub struct Crop {
    pub width: usize,
    pub height: usize,
    map: CropMap,
}

#[derive(Debug, Clone, Copy)]
enum CropMap {
    Axis { x0: f32, y0: f32, transposed: bool, k: f32 },
    Rotated { region: OrientedRegion, ha: f32, hb: f32, k: f32 },
}

impl Crop {
    /// A point of the cut-out image in frame pixels.
    pub fn to_frame(&self, p: [f32; 2]) -> [f32; 2] {
        match self.map {
            CropMap::Axis { x0, y0, transposed, k } => {
                let (across, along) = (p[0] / k, p[1]);
                if transposed { [x0 + along, y0 + across] } else { [x0 + across, y0 + along] }
            }
            CropMap::Rotated { region: r, ha, hb, k } => {
                let (a, b) = (p[0] / k - ha, p[1] - hb);
                [r.cx + a * r.ux - b * r.uy, r.cy + a * r.uy + b * r.ux]
            }
        }
    }
}

fn bilinear(img: &[u8], w: usize, h: usize, x: f32, y: f32) -> u8 {
    let (x, y) = (x - 0.5, y - 0.5);
    if x < 0.0 || y < 0.0 || x >= (w - 1) as f32 || y >= (h - 1) as f32 {
        let xi = (x.round().max(0.0) as usize).min(w - 1);
        let yi = (y.round().max(0.0) as usize).min(h - 1);
        return img[yi * w + xi];
    }
    let (x0, y0) = (x as usize, y as usize);
    let (fx, fy) = (x - x0 as f32, y - y0 as f32);
    let i = y0 * w + x0;
    let top = img[i] as f32 * (1.0 - fx) + img[i + 1] as f32 * fx;
    let bottom = img[i + w] as f32 * (1.0 - fx) + img[i + w + 1] as f32 * fx;
    (top * (1.0 - fy) + bottom * fy).round() as u8
}

/// Side of the cells the bar finder measures.
const CELL: usize = 8;

/// Patches of parallel bars at any angle, largest first. Each 8 × 8 cell's
/// gradient structure tensor gives its edge energy, its coherence (bars: one
/// dominant gradient direction; text, 2-D codes and texture: several) and
/// the direction across its bars. Coherent, energetic cells are grouped with
/// neighbours of the same direction; groups split by a bar or space wider
/// than a cell (large modules) are joined when they lie side by side across
/// the bars with the same height.
pub fn oriented_regions(luma: &[u8], w: usize, h: usize) -> Vec<OrientedRegion> {
    const MIN_ENERGY: f32 = 400.0; // mean squared central difference: a 20-level step per pixel
    const MIN_COHERENCE: f32 = 0.75;
    let c = CELL;
    let (cw, ch) = (w / c, h / c);
    if cw < 4 || ch < 2 {
        return Vec::new();
    }
    // Per cell, the doubled angle of the gradient (bars at θ and θ + 180° alike), or NaN.
    let mut angle = vec![f32::NAN; cw * ch];
    for cy in 0..ch {
        for cx in 0..cw {
            let (y0, y1) = ((cy * c).max(1), ((cy + 1) * c).min(h - 1));
            let (x0, x1) = ((cx * c).max(1), ((cx + 1) * c).min(w - 1));
            let (mut jxx, mut jyy, mut jxy) = (0f32, 0f32, 0f32);
            for y in y0..y1 {
                let (up, r, down) = ((y - 1) * w, y * w, (y + 1) * w);
                for x in x0..x1 {
                    // Sobel: smoothed across the derivative, so the staircase
                    // edges of bars at an angle still agree on their direction.
                    let p = |i: usize| luma[i] as i32;
                    let gx = (p(up + x + 1) + 2 * p(r + x + 1) + p(down + x + 1) - p(up + x - 1) - 2 * p(r + x - 1) - p(down + x - 1)) as f32;
                    let gy = (p(down + x - 1) + 2 * p(down + x) + p(down + x + 1) - p(up + x - 1) - 2 * p(up + x) - p(up + x + 1)) as f32;
                    jxx += gx * gx;
                    jyy += gy * gy;
                    jxy += gx * gy;
                }
            }
            // Sobel's gain is 4 over a central difference: 16 on squares.
            let n = 16.0 * ((y1 - y0) * (x1 - x0)).max(1) as f32;
            if (jxx + jyy) / n < MIN_ENERGY {
                continue;
            }
            let coherence = ((jxx - jyy).powi(2) + 4.0 * jxy * jxy).sqrt() / (jxx + jyy);
            if coherence >= MIN_COHERENCE {
                angle[cy * cw + cx] = (2.0 * jxy).atan2(jxx - jyy);
            }
        }
    }
    // Within about 14° of each other (0.5 rad doubled).
    let close = |a: f32, b: f32| {
        let d = (a - b).abs();
        d.min(2.0 * std::f32::consts::PI - d) < 0.5
    };
    let mut seen = vec![false; cw * ch];
    let mut groups: Vec<Vec<usize>> = Vec::new();
    for start in 0..cw * ch {
        if seen[start] || angle[start].is_nan() {
            continue;
        }
        seen[start] = true;
        let (mut stack, mut members) = (vec![start], Vec::new());
        while let Some(i) = stack.pop() {
            members.push(i);
            let (x, y) = ((i % cw) as i32, (i / cw) as i32);
            for (dx, dy) in [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)] {
                let (nx, ny) = (x + dx, y + dy);
                if nx < 0 || ny < 0 || nx >= cw as i32 || ny >= ch as i32 {
                    continue;
                }
                let j = ny as usize * cw + nx as usize;
                if !seen[j] && !angle[j].is_nan() && close(angle[j], angle[i]) {
                    seen[j] = true;
                    stack.push(j);
                }
            }
        }
        if members.len() >= 2 {
            groups.push(members);
        }
    }
    let region = |members: &[usize]| -> OrientedRegion {
        let (sx, sy) = members.iter().fold((0f32, 0f32), |(a, b), &i| (a + angle[i].cos(), b + angle[i].sin()));
        let phi = sy.atan2(sx) / 2.0;
        let (ux, uy) = (phi.cos(), phi.sin());
        let centre = |i: usize| (((i % cw) * c + c / 2) as f32, ((i / cw) * c + c / 2) as f32);
        let (mx, my) = members.iter().fold((0f32, 0f32), |(a, b), &i| (a + centre(i).0, b + centre(i).1));
        let (mx, my) = (mx / members.len() as f32, my / members.len() as f32);
        let (mut a0, mut a1, mut b0, mut b1) = (f32::MAX, f32::MIN, f32::MAX, f32::MIN);
        for &i in members {
            let (dx, dy) = (centre(i).0 - mx, centre(i).1 - my);
            let (a, b) = (dx * ux + dy * uy, -dx * uy + dy * ux);
            (a0, a1, b0, b1) = (a0.min(a), a1.max(a), b0.min(b), b1.max(b));
        }
        let (am, bm) = ((a0 + a1) / 2.0, (b0 + b1) / 2.0);
        OrientedRegion {
            cx: mx + ux * am - uy * bm,
            cy: my + uy * am + ux * bm,
            ux,
            uy,
            half_across: (a1 - a0 + c as f32) / 2.0,
            half_along: (b1 - b0 + c as f32) / 2.0,
            cells: members.len(),
        }
    };
    // Join the pieces of one code split by a wide bar or space. Two codes
    // side by side can be joined as well, so the pieces stay candidates too.
    let pieces = groups.clone();
    loop {
        let boxes: Vec<OrientedRegion> = groups.iter().map(|g| region(g)).collect();
        let pair = (0..groups.len()).flat_map(|i| (i + 1..groups.len()).map(move |j| (i, j))).find(|&(i, j)| {
            let (p, q) = (&boxes[i], &boxes[j]);
            if groups[i].len() < 4 || groups[j].len() < 4 || (p.ux * q.ux + p.uy * q.uy).abs() < 0.985 {
                return false;
            }
            let (dx, dy) = (q.cx - p.cx, q.cy - p.cy);
            let gap = (dx * p.ux + dy * p.uy).abs() - p.half_across - q.half_across;
            let offset = (-dx * p.uy + dy * p.ux).abs();
            let along = p.half_along.max(q.half_along);
            p.half_along.min(q.half_along) > 0.6 * along && offset < 0.3 * along && gap > -(c as f32) && gap < (3 * c) as f32 && gap < along
        });
        let Some((i, j)) = pair else { break };
        let g = groups.remove(j);
        groups[i].extend(g);
    }
    let mut out: Vec<OrientedRegion> = groups
        .iter()
        .filter(|g| !pieces.contains(g))
        .chain(&pieces)
        .filter(|g| g.len() >= 6)
        .map(|g| region(g))
        // At least five cells across the bars, and mostly filled.
        .filter(|r| 2.0 * r.half_across >= (5 * c) as f32 && r.cells as f32 * (c * c) as f32 >= 0.35 * 4.0 * r.half_across * r.half_along)
        .collect();
    // Largest first: a joined patch before its pieces.
    out.sort_by(|a, b| b.cells.cmp(&a.cells));
    out
}

/// An unsharp mask along x: `v + amount × (v − gaussian(v))`.
fn unsharp_x(img: &[u8], w: usize, h: usize, sigma: f32, amount: f32) -> Vec<u8> {
    let r = (sigma * 3.0).ceil() as isize;
    let kernel: Vec<f32> = (-r..=r).map(|i| (-(i * i) as f32 / (2.0 * sigma * sigma)).exp()).collect();
    let total: f32 = kernel.iter().sum();
    let mut out = vec![0u8; w * h];
    for y in 0..h {
        let row = &img[y * w..(y + 1) * w];
        for x in 0..w {
            let mut acc = 0.0;
            for (k, kv) in kernel.iter().enumerate() {
                let sx = (x as isize + k as isize - r).clamp(0, w as isize - 1) as usize;
                acc += row[sx] as f32 * kv;
            }
            let v = row[x] as f32;
            out[y * w + x] = (v + amount * (v - acc / total)).clamp(0.0, 255.0) as u8;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    // Generated synthetic QR only; contains no corpus payload or source image.
    fn retry_fixture() -> (Vec<u8>, u32, u32) {
        let rows = [
            "1111111001000010101111111",
            "1000001011001000001000001",
            "1011101011011110001011101",
            "1011101001101111101011101",
            "1011101001111001101011101",
            "1000001000010000101000001",
            "1111111010101010101111111",
            "0000000000101010000000000",
            "0111011001011011000000110",
            "1100100111000000110100010",
            "0000001110100000100110000",
            "0111110011111110100001110",
            "1101011001101000011010101",
            "0110100111110011101110011",
            "0111101000010000100110010",
            "1001110110110100100000011",
            "0001101000101100111110101",
            "0000000010011000100010001",
            "1111111001011110101010011",
            "1000001010100111100011010",
            "1011101001101110111111010",
            "1011101010010011011111111",
            "1011101010001010001110010",
            "1000001010100110001100100",
            "1111111001011001011001111",
        ];
        let (w, h) = (337u32, 221u32);
        let mut image = vec![255u8; (w * h) as usize];
        for (y, row) in rows.iter().enumerate() {
            for (x, bit) in row.bytes().enumerate() {
                for dy in 0..4 {
                    for dx in 0..4 {
                        image[(52 + 4 * y + dy) * w as usize + 36 + 4 * x + dx] = if bit == b'1' { 0 } else { 255 };
                    }
                }
            }
        }
        (image, w, h)
    }

    #[test]
    fn retry_coordinates_and_payload_are_in_the_original_image() {
        let (image, w, h) = retry_fixture();
        let formats = vec!["qrcode".to_owned()];
        let first = read_all(&image, w, h, Some(&formats));
        assert_eq!(first.len(), 1);
        assert_eq!(first[0].text, "matrix retry fixture");
        assert!(!first[0].bytes.is_empty());
        for transform in [MatrixRetry::Clockwise, MatrixRetry::Half] {
            let mut retry = Vec::new();
            merge_matrix_retry(&mut retry, &image, w, h, &formats, transform);
            assert_eq!(retry.len(), 1);
            assert_eq!(retry[0].text, first[0].text);
            assert_eq!(retry[0].bytes, first[0].bytes);
            // RXing reports symbol edges slightly differently after rotation
            // and resampling: allow one fixture module (4 original pixels).
            // Exact inverse pixel mappings are checked separately below.
            for p in &retry[0].points {
                assert!(
                    first[0].points.iter().any(|q| (p[0] - q[0]).abs() <= 4.0 && (p[1] - q[1]).abs() <= 4.0),
                    "{p:?} not near original {:?}",
                    first[0].points
                );
            }
        }
        // Duplicate retries cannot replace baseline points or binary payload.
        let retried = read_all_with_matrix_retries(&image, w, h, Some(&formats));
        assert_eq!(serde_json::to_value(&first).unwrap(), serde_json::to_value(&retried).unwrap());
        let fallback = read_all_with_empty_matrix_retry(&image, w, h, Some(&formats));
        assert_eq!(serde_json::to_value(&first).unwrap(), serde_json::to_value(&fallback).unwrap());
    }

    #[test]
    fn empty_baseline_recovers_striped_synthetic_qr() {
        let (mut image, w, h) = retry_fixture();
        // A one-pixel white stripe on every even column interrupts source
        // modules; area averaging restores their contrast at half scale.
        for y in 0..h as usize {
            for x in (0..w as usize).step_by(2) {
                image[y * w as usize + x] = 255;
            }
        }
        let qr = vec!["qrcode".to_owned()];
        assert!(read_all(&image, w, h, Some(&qr)).is_empty());
        let recovered = read_all_with_empty_matrix_retry(&image, w, h, Some(&qr));
        assert_eq!(recovered.len(), 1);
        assert_eq!(recovered[0].text, "matrix retry fixture");
        assert_eq!(recovered[0].bytes, b"matrix retry fixture");
        assert_eq!(recovered[0].format, "qrcode");
        let expected = [[36.0, 52.0], [136.0, 52.0], [36.0, 152.0], [136.0, 152.0]];
        assert_eq!(recovered[0].points.len(), 4);
        for point in &recovered[0].points {
            assert!(expected.iter().any(|corner| (point[0] - corner[0]).abs() < 4.0 && (point[1] - corner[1]).abs() < 4.0));
        }
        assert!(read_all_with_empty_matrix_retry(&image, w, h, Some(&["datamatrix".to_owned()])).is_empty());
    }

    #[test]
    fn retries_do_not_expand_linear_or_unsupported_matrix_requests() {
        let (image, w, h) = retry_fixture();
        for names in [vec!["code128".to_owned()], vec!["ean13".to_owned(), "unknown".to_owned()], vec!["maxicode".to_owned()]] {
            assert!(matrix_retry_formats(Some(&names)).is_empty());
            assert!(read_all_with_matrix_retries(&image, w, h, Some(&names)).is_empty());
            assert!(read_all_with_empty_matrix_retry(&image, w, h, Some(&names)).is_empty());
        }
        let mixed = vec!["code128".to_owned(), "QR-Code".to_owned()];
        assert_eq!(matrix_retry_formats(Some(&mixed)), ["qrcode"]);
        // Match read_all's established all-formats default for empty/unknown lists.
        assert_eq!(matrix_retry_formats(Some(&[])), matrix_retry_formats(None));
        assert_eq!(matrix_retry_formats(Some(&["unknown".to_owned()])), matrix_retry_formats(None));
    }

    #[test]
    fn retry_transforms_cover_non_square_and_odd_images() {
        let (rotated, w, h) = MatrixRetry::Clockwise.image(&[1, 2, 3, 4, 5, 6], 3, 2);
        assert_eq!((w, h), (2, 3));
        assert_eq!(rotated, [4, 1, 5, 2, 6, 3]);
        for y in 0..h {
            for x in 0..w {
                let p = MatrixRetry::Clockwise.original_point([x as f32, y as f32], 3, 2);
                assert_eq!(rotated[(y * w + x) as usize], [1, 2, 3, 4, 5, 6][p[1] as usize * 3 + p[0] as usize]);
            }
        }
        let (small, w, h) = MatrixRetry::Half.image(&[0, 0, 100, 0, 0, 100, 100, 100, 100], 3, 3);
        assert_eq!((w, h), (1, 1));
        assert_eq!(small, [56]); // all nine pixels, including last row/column
        assert_eq!(MatrixRetry::Half.original_point([0.0, 0.0], 3, 3), [1.0, 1.0]);
        assert_eq!(MatrixRetry::Half.original_point([0.0, 0.0], 4, 4), [0.5, 0.5]);
    }

    #[test]
    fn retries_reject_invalid_buffers_and_skip_too_small_half_images() {
        assert!(read_all_with_matrix_retries(&[], u32::MAX, 16, None).is_empty());
        assert!(read_all_with_empty_matrix_retry(&[], 32, 32, None).is_empty());
        assert!(read_all_with_matrix_retries(&[255; 16 * 31], 16, 31, None).is_empty());
    }

    fn linear(format: &str, text: &str, a: [f32; 2], b: [f32; 2]) -> Barcode {
        Barcode { format: format.into(), text: text.into(), bytes: vec![], points: vec![a, b] }
    }

    /// The UPC-E read on frame 84 of the HD multi-barcode clip, along the
    /// foot of the EAN-13's bars: dropped. A UPC-E elsewhere is kept.
    #[test]
    fn a_weak_code_inside_another_is_dropped() {
        let ean = linear("ean13", "6001234567899", [886.0, 165.0], [1042.0, 165.0]);
        let nested = linear("upce", "11032861", [1024.0, 260.0], [899.0, 260.0]);
        let apart = linear("upce", "01234565", [200.0, 600.0], [300.0, 600.0]);
        let kept = drop_nested_reads(vec![ean, nested, apart], &[]);
        let texts: Vec<&str> = kept.iter().map(|b| b.text.as_str()).collect();
        assert_eq!(texts, ["6001234567899", "01234565"]);
    }

    /// An Aztec bull's eye (concentric squares, dark centre) far from the
    /// middle of the image is found, with its module size.
    #[test]
    fn finds_an_off_centre_bulls_eye() {
        let (w, h, m) = (400u32, 300u32, 4i32);
        let mut bits = BitMatrix::new(w, h).unwrap();
        let (cx, cy) = (80i32, 220i32);
        for y in 0..h as i32 {
            for x in 0..w as i32 {
                // Chebyshev distance in modules from the centre module.
                let r = ((x - cx).abs().max((y - cy).abs()) + m / 2) / m;
                if r <= 4 && r % 2 == 0 {
                    bits.set(x as u32, y as u32);
                }
            }
        }
        let eyes = bullseyes(&bits);
        assert!(!eyes.is_empty());
        let (x, y, module) = eyes[0];
        assert!((x - cx as f32).abs() < 3.0 && (y - cy as f32).abs() < 3.0 && (module - m as f32).abs() < 1.0, "{eyes:?}");
    }

    /// Bars blurred to a smooth profile are redrawn at their edges.
    #[test]
    fn redraws_blurred_bars() {
        // Bars of 1-4 units, 8 samples per unit, then blurred.
        let widths = [3, 1, 1, 2, 4, 1, 2, 3, 1, 1];
        let mut crisp = vec![false; 16];
        for (i, wdt) in widths.iter().enumerate() {
            crisp.extend(std::iter::repeat_n(i % 2 == 0, wdt * 8));
        }
        crisp.extend([false; 16]);
        let mut p: Vec<f32> = crisp.iter().map(|&d| if d { 40.0 } else { 220.0 }).collect();
        smooth(&mut p, 5.0);
        let bars = redraw(&p);
        let wrong = bars.iter().zip(&crisp).filter(|(a, b)| a != b).count();
        // Each edge within a sample or two.
        assert!(wrong <= 2 * widths.len(), "{wrong} samples wrong");
    }

    /// A band of bars on paper is found as one region, across x; the same
    /// turned 90° across y, and turned 30° at 30°.
    #[test]
    fn finds_bar_patches_at_any_angle() {
        let (w, h) = (360, 360);
        for deg in [0.0f32, 90.0, 30.0] {
            let (s, c) = deg.to_radians().sin_cos();
            let mut img = vec![230u8; w * h];
            for y in 0..h {
                for x in 0..w {
                    // Coordinates across (a) and along (b) the bars, from the centre.
                    let (dx, dy) = (x as f32 - 180.0, y as f32 - 180.0);
                    let (a, b) = (dx * c + dy * s, -dx * s + dy * c);
                    let ai = (a + 100.0) as i32;
                    if a.abs() < 100.0 && b.abs() < 30.0 && (ai / 3 + ai / 8) % 2 == 0 {
                        img[y * w + x] = 20;
                    }
                }
            }
            let r = oriented_regions(&img, w, h);
            assert_eq!(r.len(), 1, "{deg}: {r:?}");
            let got = r[0].uy.atan2(r[0].ux).to_degrees().rem_euclid(180.0);
            let want = deg.rem_euclid(180.0);
            assert!((got - want).abs() < 4.0 || (got - want).abs() > 176.0, "{deg}: {got}");
            assert!((r[0].cx - 180.0).abs() < 10.0 && (r[0].cy - 180.0).abs() < 10.0 && r[0].half_across > 85.0, "{deg}: {r:?}");
        }
    }
}
