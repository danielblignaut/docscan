//! Optional PP-OCRv6 tiny general-text OCR. Independent of ID/PoA OCR.
//! Coordinates are line-level quadrilaterals in the original input pixels.
//! Model provenance: scripts/ppocr-v6-models.json. Native and wasm use RTen.
use anyhow::{Context, Result, ensure};
use rten::{Dimension, Model, ValueView};
use rten_imageproc::{BoundingRect, PointF, RetrievalMode, find_contours, min_area_rect};
use rten_tensor::{NdTensor, prelude::*};
use serde::Serialize;
use wasm_bindgen::prelude::*;

/// Official tiny CTC symbols, including blank and space. Apache-2.0.
pub const DICTIONARY_JSON: &str = include_str!("text_v6_dictionary.json");
const CLASSES: usize = 6906;
const MAX_SIDE: usize = 960;
const DETAIL_MAX_SIDE: usize = 1600;
const MAX_PIXELS: usize = 24_000_000;
const MAX_CANDIDATES: usize = 3000;
const MAX_LINES: usize = 256;
const MAX_REC_WIDTH: usize = 3200;
type Quad = [[f32; 2]; 4];

#[derive(Debug, Serialize)]
pub struct PaddleTextLine {
    pub text: String,
    /// Mean emitted-symbol posterior; not calibrated accuracy.
    pub confidence: f32,
    /// TL, TR, BR, BL in original input pixels; no word boxes inferred.
    pub quad: Quad,
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}
#[derive(Debug, Default, Serialize)]
pub struct PaddleTextTimings {
    pub detect: f64,
    pub recognize: f64,
    pub total: f64,
}
#[derive(Debug, Serialize)]
pub struct PaddleTextResult {
    pub engine: &'static str,
    pub text: String,
    pub lines: Vec<PaddleTextLine>,
    pub page_size: [u32; 2],
    pub detection_max_side: usize,
    pub passes: u8,
    pub timings_ms: PaddleTextTimings,
}
#[wasm_bindgen]
#[derive(Default)]
pub struct PaddleTextScanner {
    detector: Option<Model>,
    recognizer: Option<Model>,
    characters: Vec<String>,
}
#[wasm_bindgen]
impl PaddleTextScanner {
    #[wasm_bindgen(constructor)]
    pub fn new() -> PaddleTextScanner {
        Self::default()
    }
    pub fn load_detector(&mut self, bytes: Vec<u8>) -> Result<(), JsError> {
        self.load_detector_native(bytes).map_err(|e| JsError::new(&e.to_string()))
    }
    pub fn load_recognizer(&mut self, bytes: Vec<u8>, dictionary_json: &str) -> Result<(), JsError> {
        self.load_recognizer_native(bytes, dictionary_json).map_err(|e| JsError::new(&e.to_string()))
    }
    /// Optional small-print profile: retains more detector pixels at higher cost.
    pub fn read_detailed(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let result = self
            .read_detailed_native(rgba, width as usize, height as usize)
            .map_err(|e| JsError::new(&e.to_string()))?;
        crate::to_js(&result)
    }
    pub fn read(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let result = self
            .read_native(rgba, width as usize, height as usize)
            .map_err(|e| JsError::new(&e.to_string()))?;
        crate::to_js(&result)
    }
}
fn dictionary(json: &str) -> Result<Vec<String>> {
    ensure!(json.len() <= 128 * 1024, "PP-OCR dictionary exceeds its size limit");
    let chars: Vec<String> = serde_json::from_str(json).context("invalid PP-OCR dictionary JSON")?;
    let expected: Vec<String> = serde_json::from_str(DICTIONARY_JSON)?;
    ensure!(chars == expected, "dictionary does not match the pinned PP-OCRv6 tiny recognizer");
    Ok(chars)
}
fn validate_model(model: &Model, recognition: bool) -> Result<()> {
    ensure!(
        model.input_ids().len() == 1 && model.output_ids().len() == 1,
        "expected one PP-OCR input and output"
    );
    let shape = model.input_shape(0).context("missing PP-OCR input shape")?;
    ensure!(
        shape.len() == 4 && shape[1] == Dimension::Fixed(3),
        "expected a three-channel PP-OCR NCHW input"
    );
    let output = model
        .node_info(model.output_ids()[0])
        .and_then(|n| n.shape())
        .context("missing PP-OCR output shape")?;
    if recognition {
        ensure!(shape[2] == Dimension::Fixed(48), "expected recognition height 48");
        ensure!(
            output.len() == 3 && output[2] == Dimension::Fixed(CLASSES),
            "model does not match tiny CTC classes"
        );
    } else {
        ensure!(output.len() == 4 && output[1] == Dimension::Fixed(1), "expected detection probability map");
    }
    Ok(())
}
impl PaddleTextScanner {
    pub fn load_detector_native(&mut self, bytes: Vec<u8>) -> Result<()> {
        ensure!(!bytes.is_empty() && bytes.len() <= 8 * 1024 * 1024, "invalid PP-OCR detector size");
        let model = Model::load(bytes).context("loading PP-OCR detector")?;
        validate_model(&model, false)?;
        self.detector = Some(model);
        Ok(())
    }
    pub fn load_recognizer_native(&mut self, bytes: Vec<u8>, dictionary_json: &str) -> Result<()> {
        let chars = dictionary(dictionary_json)?;
        ensure!(!bytes.is_empty() && bytes.len() <= 16 * 1024 * 1024, "invalid PP-OCR recognizer size");
        let model = Model::load(bytes).context("loading PP-OCR recognizer")?;
        validate_model(&model, true)?;
        self.recognizer = Some(model);
        self.characters = chars;
        Ok(())
    }
    pub fn read_native(&self, rgba: &[u8], width: usize, height: usize) -> Result<PaddleTextResult> {
        self.read_at_resolution(rgba, width, height, MAX_SIDE)
    }
    /// Compare two bounded resolutions for dense documents. More pixels can
    /// merge lines, so retain the reading with stronger recognized-text evidence
    /// rather than always replacing the standard pass. This is an OCR heuristic,
    /// not calibrated accuracy or document verification.
    pub fn read_detailed_native(&self, rgba: &[u8], width: usize, height: usize) -> Result<PaddleTextResult> {
        let start = crate::now();
        let standard = self.read_native(rgba, width, height)?;
        if width.max(height) <= MAX_SIDE {
            return Ok(standard);
        }
        let detailed = self.read_at_resolution(rgba, width, height, DETAIL_MAX_SIDE)?;
        let detect = standard.timings_ms.detect + detailed.timings_ms.detect;
        let recognize = standard.timings_ms.recognize + detailed.timings_ms.recognize;
        let mut selected = select_reading(standard, detailed);
        selected.passes = 2;
        selected.timings_ms = PaddleTextTimings { detect, recognize, total: crate::now() - start };
        Ok(selected)
    }
    fn read_at_resolution(&self, rgba: &[u8], width: usize, height: usize, max_side: usize) -> Result<PaddleTextResult> {
        validate_image(rgba, width, height)?;
        let detector = self.detector.as_ref().context("PP-OCR detector is not loaded")?;
        let recognizer = self.recognizer.as_ref().context("PP-OCR recognizer is not loaded")?;
        let start = crate::now();
        let image = Image {
            bytes: rgba,
            width,
            height,
            channels: 4,
        };
        let (input, dw, dh) = detection_input(&image, max_side);
        let value = ValueView::from_shape([1, 3, dh, dw], &input)?;
        let mut outputs = detector.run(vec![(detector.input_ids()[0], value.into())], detector.output_ids(), None)?;
        let map = outputs.remove(0).into_tensor::<f32>().context("non-float detector output")?;
        ensure!(map.shape() == [1, 1, dh, dw], "unexpected detector output shape");
        let boxes = detection_boxes(map.data().context("non-contiguous detector map")?, dw, dh, width, height)?;
        drop(map);
        drop(input);
        let detect = crate::now() - start;
        let mut lines = Vec::new();
        for quad in boxes {
            let (pixels, cw, ch) = line_crop(&image, &quad)?;
            let (input, rw) = recognition_input(&Image {
                bytes: &pixels,
                width: cw,
                height: ch,
                channels: 3,
            })?;
            let value = ValueView::from_shape([1, 3, 48, rw], &input)?;
            let mut outputs = recognizer.run(vec![(recognizer.input_ids()[0], value.into())], recognizer.output_ids(), None)?;
            let scores = outputs.remove(0).into_tensor::<f32>().context("non-float CTC output")?;
            ensure!(
                scores.ndim() == 3 && scores.shape()[0] == 1 && scores.shape()[2] == CLASSES,
                "unexpected CTC output shape"
            );
            let (text, confidence) = decode_ctc(scores.data().context("non-contiguous CTC output")?, &self.characters)?;
            if text.is_empty() {
                continue;
            }
            let x = quad.iter().map(|p| p[0]).fold(f32::INFINITY, f32::min);
            let y = quad.iter().map(|p| p[1]).fold(f32::INFINITY, f32::min);
            let right = quad.iter().map(|p| p[0]).fold(0.0, f32::max);
            let bottom = quad.iter().map(|p| p[1]).fold(0.0, f32::max);
            lines.push(PaddleTextLine {
                text,
                confidence,
                quad,
                x,
                y,
                w: right - x,
                h: bottom - y,
            });
        }
        let total = crate::now() - start;
        Ok(PaddleTextResult {
            engine: "ppocr_v6_tiny",
            text: lines.iter().map(|l| l.text.as_str()).collect::<Vec<_>>().join("\n"),
            lines,
            page_size: [width as u32, height as u32],
            detection_max_side: max_side,
            passes: 1,
            timings_ms: PaddleTextTimings {
                detect,
                recognize: total - detect,
                total,
            },
        })
    }
}
fn select_reading(standard: PaddleTextResult, detailed: PaddleTextResult) -> PaddleTextResult {
    let evidence = |result: &PaddleTextResult| -> f32 {
        result.lines.iter().map(|line| line.text.chars().filter(|c| c.is_alphanumeric()).count() as f32 * line.confidence).sum()
    };
    if evidence(&detailed) > evidence(&standard) { detailed } else { standard }
}
fn validate_image(bytes: &[u8], width: usize, height: usize) -> Result<()> {
    ensure!(width > 0 && height > 0, "empty image");
    ensure!(width <= 8192 && height <= 8192, "image dimensions exceed 8192 pixels; resize before reading");
    let pixels = width.checked_mul(height).context("image dimensions overflow")?;
    ensure!(pixels <= MAX_PIXELS, "image exceeds 24 megapixels; resize before reading");
    ensure!(bytes.len() == pixels * 4, "RGBA byte count does not match image dimensions");
    Ok(())
}
struct Image<'a> {
    bytes: &'a [u8],
    width: usize,
    height: usize,
    channels: usize,
}
impl Image<'_> {
    fn pixel(&self, x: isize, y: isize) -> [f32; 3] {
        let x = x.clamp(0, self.width as isize - 1) as usize;
        let y = y.clamp(0, self.height as isize - 1) as usize;
        let at = (y * self.width + x) * self.channels;
        let alpha = if self.channels == 4 { self.bytes[at + 3] as f32 / 255.0 } else { 1.0 };
        std::array::from_fn(|c| self.bytes[at + c] as f32 * alpha + 255.0 * (1.0 - alpha))
    }
    fn linear(&self, x: f32, y: f32) -> [f32; 3] {
        let (ix, iy) = (x.floor() as isize, y.floor() as isize);
        let (fx, fy) = (x - x.floor(), y - y.floor());
        let (a, b, c, d) = (self.pixel(ix, iy), self.pixel(ix + 1, iy), self.pixel(ix, iy + 1), self.pixel(ix + 1, iy + 1));
        std::array::from_fn(|k| {
            ((a[k] * (1.0 - fx) + b[k] * fx) * (1.0 - fy) + (c[k] * (1.0 - fx) + d[k] * fx) * fy)
                .round()
                .clamp(0.0, 255.0)
        })
    }
    fn cubic(&self, x: f32, y: f32) -> [u8; 3] {
        // OpenCV INTER_CUBIC: a=-0.75 and 1/32-pixel warp table.
        let (x, y) = ((x * 32.0).round() / 32.0, (y * 32.0).round() / 32.0);
        let (ix, iy) = (x.floor() as isize, y.floor() as isize);
        let mut out = [0.0f32; 3];
        for dy in -1..=2 {
            for dx in -1..=2 {
                let weight = cubic_weight(x - (ix + dx) as f32) * cubic_weight(y - (iy + dy) as f32);
                let p = self.pixel(ix + dx, iy + dy);
                for c in 0..3 {
                    out[c] += p[c] * weight;
                }
            }
        }
        out.map(|v| v.round().clamp(0.0, 255.0) as u8)
    }
}
fn cubic_weight(x: f32) -> f32 {
    let x = x.abs();
    if x <= 1.0 {
        1.25 * x.powi(3) - 2.25 * x.powi(2) + 1.0
    } else if x < 2.0 {
        -0.75 * x.powi(3) + 3.75 * x.powi(2) - 6.0 * x + 3.0
    } else {
        0.0
    }
}
fn detection_input(image: &Image<'_>, max_side: usize) -> (Vec<f32>, usize, usize) {
    let ratio = (max_side as f32 / image.width.max(image.height) as f32).min(1.0);
    let rounded = |size: usize| (((size as f32 * ratio).floor() / 32.0).round_ties_even() as usize * 32).max(32);
    let (w, h) = (rounded(image.width), rounded(image.height));
    let mut out = vec![0.0; 3 * w * h];
    for y in 0..h {
        for x in 0..w {
            let p = image.linear(
                (x as f32 + 0.5) * image.width as f32 / w as f32 - 0.5,
                (y as f32 + 0.5) * image.height as f32 / h as f32 - 0.5,
            );
            for c in 0..3 {
                out[c * w * h + y * w + x] = (p[2 - c] / 255.0 - [0.485, 0.456, 0.406][c]) / [0.229, 0.224, 0.225][c];
            }
        }
    }
    (out, w, h)
}
fn order_quad(mut points: [PointF; 4]) -> Quad {
    points.sort_by(|a, b| a.x.total_cmp(&b.x));
    if points[0].y > points[1].y {
        points.swap(0, 1);
    }
    if points[2].y > points[3].y {
        points.swap(2, 3);
    }
    [points[0], points[2], points[3], points[1]].map(|p| [p.x, p.y])
}
fn detection_boxes(map: &[f32], w: usize, h: usize, sw: usize, sh: usize) -> Result<Vec<Quad>> {
    ensure!(map.len() == w * h && map.iter().all(|p| p.is_finite()), "invalid detector probability map");
    let mask = NdTensor::from_data([h, w], map.iter().map(|&p| p > 0.2).collect::<Vec<_>>());
    let contours = find_contours(mask.view(), RetrievalMode::List);
    ensure!(contours.len() <= MAX_CANDIDATES, "too many text regions; use a clearer or smaller page crop");
    let mut boxes = Vec::new();
    for contour in contours.iter() {
        let points: Vec<PointF> = contour.iter().map(|p| PointF::from_yx(p.y as f32, p.x as f32)).collect();
        let Some(rect) = min_area_rect(&points) else { continue };
        if rect.width().min(rect.height()) < 3.0 {
            continue;
        }
        let bounds = rect.bounding_rect();
        let (mut sum, mut count) = (0.0, 0);
        for y in (bounds.top().floor().max(0.0) as usize)..=(bounds.bottom().ceil().min(h as f32 - 1.0) as usize) {
            for x in (bounds.left().floor().max(0.0) as usize)..=(bounds.right().ceil().min(w as f32 - 1.0) as usize) {
                if rect.contains(PointF::from_yx(y as f32, x as f32)) {
                    sum += map[y * w + x];
                    count += 1;
                }
            }
        }
        if count == 0 || sum / (count as f32) < 0.4 {
            continue;
        }
        // DB offsets a rectangle by area*1.4/perimeter. Its rounded offset
        // has this exact enclosing rectangle; no polygon-offset library.
        let d = rect.width() * rect.height() * 1.4 / (2.0 * (rect.width() + rect.height()));
        let expanded = rect.expanded(2.0 * d, 2.0 * d);
        if expanded.width().min(expanded.height()) < 5.0 {
            continue;
        }
        let mut quad = order_quad(expanded.corners());
        for p in &mut quad {
            p[0] = (p[0] * sw as f32 / w as f32).round_ties_even().clamp(0.0, sw as f32);
            p[1] = (p[1] * sh as f32 / h as f32).round_ties_even().clamp(0.0, sh as f32);
        }
        if distance(quad[0], quad[1]) >= 1.0 && distance(quad[0], quad[3]) >= 1.0 {
            boxes.push(quad);
        }
    }
    ensure!(boxes.len() <= MAX_LINES, "page has more than 256 text lines; capture a smaller section");
    // Recognition turns tall crops counter-clockwise. When most lines use
    // that turn, sort in the same virtual upright frame, while returning
    // untouched original-input coordinates. Otherwise a clockwise page's
    // last paragraph line would be returned first.
    let vertical = boxes.iter().filter(|q| distance(q[0], q[3]) >= 1.5 * distance(q[0], q[1])).count() * 2 > boxes.len();
    let position = |q: &Quad| if vertical { [q[0][1], sw as f32 - q[0][0]] } else { q[0] };
    sort_reading_order(&mut boxes, position);
    Ok(boxes)
}

fn sort_reading_order(boxes: &mut [Quad], position: impl Fn(&Quad) -> [f32; 2]) {
    boxes.sort_by(|a, b| {
        let (a, b) = (position(a), position(b));
        a[1].total_cmp(&b[1]).then(a[0].total_cmp(&b[0]))
    });
    for i in 1..boxes.len() {
        let mut j = i;
        while j > 0 && (position(&boxes[j])[1] - position(&boxes[j - 1])[1]).abs() < 10.0 && position(&boxes[j])[0] < position(&boxes[j - 1])[0] {
            boxes.swap(j, j - 1);
            j -= 1;
        }
    }
}
fn distance(a: [f32; 2], b: [f32; 2]) -> f32 {
    (a[0] - b[0]).hypot(a[1] - b[1])
}
fn line_crop(image: &Image<'_>, quad: &Quad) -> Result<(Vec<u8>, usize, usize)> {
    let w = (distance(quad[0], quad[1]).max(distance(quad[2], quad[3])) as usize).max(1);
    let h = (distance(quad[0], quad[3]).max(distance(quad[1], quad[2])) as usize).max(1);
    ensure!(
        w.checked_mul(h).is_some_and(|n| n <= 4_000_000),
        "text region is too large; capture a smaller section"
    );
    let matrix = homography(quad).context("degenerate text rectangle")?;
    let mut output = vec![0u8; w * h * 3];
    for y in 0..h {
        for x in 0..w {
            let (u, v) = (x as f64 / w as f64, y as f64 / h as f64);
            let divisor = matrix[6] * u + matrix[7] * v + 1.0;
            let sx = ((matrix[0] * u + matrix[1] * v + matrix[2]) / divisor) as f32;
            let sy = ((matrix[3] * u + matrix[4] * v + matrix[5]) / divisor) as f32;
            output[(y * w + x) * 3..(y * w + x + 1) * 3].copy_from_slice(&image.cubic(sx, sy));
        }
    }
    if (h as f32) / (w as f32) < 1.5 {
        return Ok((output, w, h));
    }
    let mut rotated = vec![0u8; output.len()];
    for y in 0..w {
        for x in 0..h {
            let at = (x * w + w - 1 - y) * 3;
            rotated[(y * h + x) * 3..(y * h + x + 1) * 3].copy_from_slice(&output[at..at + 3]);
        }
    }
    Ok((rotated, h, w))
}
/// Unit square to quadrilateral, using a small projective solve.
fn homography(quad: &Quad) -> Option<[f64; 8]> {
    let mut a = [[0.0f64; 9]; 8];
    for (i, (p, q)) in [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]].iter().zip(quad).enumerate() {
        let (u, v, x, y) = (p[0], p[1], q[0] as f64, q[1] as f64);
        a[2 * i] = [u, v, 1.0, 0.0, 0.0, 0.0, -u * x, -v * x, x];
        a[2 * i + 1] = [0.0, 0.0, 0.0, u, v, 1.0, -u * y, -v * y, y];
    }
    for column in 0..8 {
        let pivot = (column..8).max_by(|&i, &j| a[i][column].abs().total_cmp(&a[j][column].abs()))?;
        if a[pivot][column].abs() < 1e-10 {
            return None;
        }
        a.swap(column, pivot);
        let divisor = a[column][column];
        for k in column..9 {
            a[column][k] /= divisor;
        }
        for row in 0..8 {
            if row == column {
                continue;
            }
            let factor = a[row][column];
            for k in column..9 {
                a[row][k] -= factor * a[column][k];
            }
        }
    }
    Some(std::array::from_fn(|i| a[i][8]))
}
fn recognition_input(image: &Image<'_>) -> Result<(Vec<f32>, usize)> {
    let ratio = image.width as f32 / image.height as f32;
    // Bound the tensor, not the accepted line length. Dense small print can
    // legitimately exceed this aspect ratio; compressing it horizontally
    // matches the reference pipeline and preserves the rest of the page.
    let width = ((48.0 * ratio).floor() as usize).clamp(320, MAX_REC_WIDTH);
    let resized_width = ((48.0 * ratio).ceil() as usize).min(width).max(1);
    let mut out = vec![0.0; 3 * 48 * width];
    for y in 0..48 {
        for x in 0..resized_width {
            let p = image.linear(
                (x as f32 + 0.5) * image.width as f32 / resized_width as f32 - 0.5,
                (y as f32 + 0.5) * image.height as f32 / 48.0 - 0.5,
            );
            for c in 0..3 {
                out[c * 48 * width + y * width + x] = p[2 - c] / 127.5 - 1.0;
            }
        }
    }
    Ok((out, width))
}
fn decode_ctc(scores: &[f32], chars: &[String]) -> Result<(String, f32)> {
    ensure!(!chars.is_empty() && scores.len().is_multiple_of(chars.len()), "invalid CTC output shape");
    let (mut last, mut emitted) = (0, 0);
    let (mut text, mut confidence) = (String::new(), 0.0);
    for timestep in scores.chunks_exact(chars.len()) {
        ensure!(timestep.iter().all(|p| p.is_finite()), "non-finite CTC probability");
        let (token, probability) = timestep.iter().enumerate().max_by(|a, b| a.1.total_cmp(b.1).then(b.0.cmp(&a.0))).unwrap();
        if token != 0 && token != last {
            text.push_str(&chars[token]);
            confidence += probability;
            emitted += 1;
        }
        last = token;
    }
    Ok((text, if emitted > 0 { confidence / emitted as f32 } else { 0.0 }))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn malformed_and_excessive_images() {
        let scanner = PaddleTextScanner::new();
        for (pixels, w, h) in [
            (&[][..], 0, 1),
            (&[0u8; 3][..], 1, 1),
            (&[0u8; 5][..], 1, 1),
            (&[][..], usize::MAX, 2),
            (&[][..], 8000, 8000),
        ] {
            assert!(scanner.read_native(pixels, w, h).is_err());
        }
        assert!(scanner.read_native(&[255; 4], 1, 1).unwrap_err().to_string().contains("not loaded"));
    }
    #[test]
    fn dictionary_identity() {
        let mut chars = dictionary(DICTIONARY_JSON).unwrap();
        assert_eq!(chars.len(), CLASSES);
        chars.swap(1, 2);
        assert!(dictionary(&serde_json::to_string(&chars).unwrap()).is_err());
        assert!(dictionary("[]").is_err());
        assert!(dictionary("not json").is_err());
    }
    #[test]
    fn ctc_unicode_and_blank_separated_repetition() {
        let chars = ["", "é", "李", " "].map(String::from);
        let mut scores = vec![];
        for token in [1, 1, 0, 1, 3, 2, 2] {
            let mut row = [0.0; 4];
            row[token] = 1.0;
            scores.extend(row);
        }
        assert_eq!(decode_ctc(&scores, &chars).unwrap(), ("éé 李".into(), 1.0));
        assert_eq!(decode_ctc(&[1.0, 0.0, 0.0, 0.0], &chars).unwrap().0, "");
        assert!(decode_ctc(&[f32::NAN; 4], &chars).is_err());
    }
    #[test]
    fn blank_map_and_original_input_geometry() {
        assert!(detection_boxes(&[0.0; 64 * 64], 64, 64, 640, 640).unwrap().is_empty());
        let mut map = vec![0.0; 64 * 64];
        for y in 20..30 {
            for x in 10..50 {
                map[y * 64 + x] = 1.0;
            }
        }
        let boxes = detection_boxes(&map, 64, 64, 640, 320).unwrap();
        assert_eq!(boxes.len(), 1);
        let q = boxes[0];
        assert!(q[0][0] < 100.0 && q[1][0] > 490.0);
        assert!(q[0][1] < 100.0 && q[3][1] > 145.0);
        assert!(q.iter().all(|p| p[0] >= 0.0 && p[0] <= 640.0 && p[1] >= 0.0 && p[1] <= 320.0));
    }
    #[test]
    fn clockwise_page_uses_upright_paragraph_order() {
        let mut map = vec![0.0; 64 * 64];
        for y in 10..50 {
            for x in (10..17).chain(40..47) {
                map[y * 64 + x] = 1.0;
            }
        }
        let boxes = detection_boxes(&map, 64, 64, 640, 640).unwrap();
        assert_eq!(boxes.len(), 2);
        assert!(boxes[0][0][0] > boxes[1][0][0]);
    }
    #[test]
    fn bgr_normalization_and_transparency() {
        let image = Image {
            bytes: &[255, 0, 0, 255],
            width: 1,
            height: 1,
            channels: 4,
        };
        let (data, w, h) = detection_input(&image, MAX_SIDE);
        assert!((data[0] - (-0.485 / 0.229)).abs() < 1e-5);
        assert!((data[2 * w * h] - ((1.0 - 0.406) / 0.225)).abs() < 1e-5);
        let transparent = Image {
            bytes: &[0, 0, 0, 0],
            width: 1,
            height: 1,
            channels: 4,
        };
        assert_eq!(transparent.pixel(0, 0), [255.0; 3]);
    }
    #[test]
    fn detail_does_not_replace_a_richer_standard_reading_or_ties() {
        let result = |text: &str, confidence: f32, side| PaddleTextResult {
            engine: "ppocr_v6_tiny", text: text.into(), page_size: [100, 100],
            detection_max_side: side, passes: 1, timings_ms: PaddleTextTimings::default(),
            lines: vec![PaddleTextLine { text: text.into(), confidence,
                quad: [[0.0; 2]; 4], x: 0.0, y: 0.0, w: 10.0, h: 10.0 }],
        };
        let base = || result("Complete line of clearly recognized small print", 0.98, MAX_SIDE);
        assert_eq!(select_reading(base(), result("truncated", 0.99, DETAIL_MAX_SIDE)).detection_max_side, MAX_SIDE);
        assert_eq!(select_reading(base(), result("A longer line but with extremely uncertain recognition", 0.1, DETAIL_MAX_SIDE)).detection_max_side, MAX_SIDE);
        assert_eq!(select_reading(base(), base()).detection_max_side, MAX_SIDE);
        assert_eq!(select_reading(result("partial", 0.98, MAX_SIDE), base()).text, base().text);
    }
    #[test]
    fn detailed_detector_retains_pixels_with_a_fixed_bound() {
        let pixels = vec![255u8; 1600 * 1000 * 4];
        let image = Image { bytes: &pixels, width: 1600, height: 1000, channels: 4 };
        let (_, w, h) = detection_input(&image, MAX_SIDE);
        let (detail, dw, dh) = detection_input(&image, DETAIL_MAX_SIDE);
        assert_eq!((w, h), (960, 608));
        assert_eq!((dw, dh), (1600, 992));
        assert_eq!(detail.len(), 3 * dw * dh);
        assert!(dw <= DETAIL_MAX_SIDE && dh <= DETAIL_MAX_SIDE);
        let small = Image { bytes: &pixels[..64 * 64 * 4], width: 64, height: 64, channels: 4 };
        assert_eq!(detection_input(&small, MAX_SIDE), detection_input(&small, DETAIL_MAX_SIDE));
    }
    #[test]
    fn long_lines_fit_the_bounded_recognition_tensor() {
        let pixels = vec![255u8; 10000 * 10 * 3];
        let image = Image {
            bytes: &pixels,
            width: 10000,
            height: 10,
            channels: 3,
        };
        let (input, width) = recognition_input(&image).unwrap();
        assert_eq!(width, MAX_REC_WIDTH);
        assert_eq!(input.len(), 3 * 48 * MAX_REC_WIDTH);
        assert!(input.iter().all(|value| *value == 1.0));
    }
}
