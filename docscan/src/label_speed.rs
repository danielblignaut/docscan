//! Label experiment helpers and the PP-OCR line adapter.
//! `rows_from_paddle` is used by the explicit `Scanner::labelled_fast` API.
//! `read_lines`, `Detection`, `Stats` and `tile_starts` are retained only for
//! reproducing rejected experiments; no shipped Scanner method invokes them.
//! See `docs/improvements-label-speed-v2.md`. The description below concerns
//! those rejected research arms, not the Fast reader.
//!
//! [`crate::Scanner::labelled_native`] reads print with
//! [`crate::Scanner::ocr_tiled`]: overlapping 600 × 800 tiles, each levelled,
//! detected **and recognised** on its own, then de-duplicated by keeping the
//! longest reading. A 720 × 1280 frame takes six tiles (two columns
//! overlapping by 480 px, three rows by 560 px), so most lines are recognised
//! three to four times, and recognition is most of OCR's cost.
//!
//! [`read_lines`] keeps what the tiles were for (detection at the model's
//! native resolution, so small print keeps its detail) and drops the repeats:
//!
//! 1. the frame's ink plane is levelled once by its estimated skew (the tiles
//!    each estimated their own);
//! 2. words are detected either tile by tile at the baseline's tile positions
//!    ([`Detection::Tiles`]), or in one pass with the fully convolutional
//!    page detector (`models/text-detection-page.onnx`) on strips the width
//!    of the frame ([`Detection::Page`]); detections of a word seen by two
//!    tiles keep the larger box;
//! 3. lines are found on the whole levelled frame (ocrs's own layout), split
//!    at wide gaps, and recognised once, in batches of similar width;
//! 4. words are filtered as the tiles filter them (an MRZ-looking line is
//!    dropped; a `?` in a word of capitals is re-read with capitals only),
//!    grouped into rows ([`za::rows_from_words`]) and mapped back to frame
//!    pixels.
//!
//! The result feeds [`crate::labels::associate`] unchanged.
use crate::{geometry, mrz, mrz_decode, quality, za};
use ocrs::{ImageSource, OcrEngine, TextItem};
use rten_imageproc::{BoundingRect, Point, RotatedRect};
use rten_tensor::prelude::*;
use rten_tensor::NdTensor;

/// Where words come from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Detection {
    /// ocrs's fixed 800 × 600 detector, tile by tile at the baseline's
    /// (dense) tile positions.
    Tiles,
    /// The free-size page detector, once over the whole frame in strips.
    Page,
}

/// What a reading cost, for instrumentation.
#[derive(Clone, Debug, Default, serde::Serialize)]
pub struct Stats {
    pub skew_ms: f64,
    pub detect_ms: f64,
    pub layout_ms: f64,
    pub recognise_ms: f64,
    pub detection_passes: usize,
    /// Detector input pixels, summed over passes.
    pub detection_px: usize,
    pub words_detected: usize,
    pub lines_recognised: usize,
}

const TILE_W: usize = 600;
const TILE_H: usize = 800;

/// The baseline's dense tile starts along one side (`Scanner::tiled`, not sparse).
pub fn tile_starts(len: usize, tile: usize) -> Vec<usize> {
    if len <= tile {
        return vec![0];
    }
    let n = len.div_ceil(tile * 3 / 4);
    let step = (len - tile) as f32 / (n - 1).max(1) as f32;
    (0..n).map(|i| (i as f32 * step).round() as usize).collect()
}

/// Print lines of an RGBA frame in frame pixels, each line recognised once.
/// `page_detector` is required for [`Detection::Page`]; `recognition` (the
/// recognition model run directly) enables the capitals-only re-read of
/// words with a `?`, as the tiled reading does. `now` is a millisecond clock.
pub fn read_lines(
    ocr: &OcrEngine,
    page_detector: Option<&rten::Model>,
    recognition: Option<&rten::Model>,
    detection: Detection,
    rgba: &[u8],
    w: usize,
    h: usize,
    now: &dyn Fn() -> f64,
) -> anyhow::Result<(Vec<za::Line>, Stats)> {
    let mut st = Stats::default();
    let t = now();
    let ink = quality::rgba_to_ink(rgba);
    let luma = quality::rgba_to_luma(rgba);
    let skew = geometry::estimate_skew(&luma, w, h);
    let (ink, lw, lh) = if skew.abs() >= 1.0 { geometry::rotate(&ink, w, h, skew) } else { (ink, w, h) };
    drop(luma);
    st.skew_ms = now() - t;

    let t = now();
    let words = match detection {
        Detection::Tiles => detect_tiles(ocr, &ink, lw, lh, &mut st)?,
        Detection::Page => {
            let det = page_detector.ok_or_else(|| anyhow::anyhow!("page detector not loaded"))?;
            detect_page(det, &ink, lw, lh, &mut st)?
        }
    };
    st.words_detected = words.len();
    st.detect_ms = now() - t;

    let t = now();
    let input = ocr.prepare_input(ImageSource::from_bytes(&ink, (lw as u32, lh as u32))?)?;
    let lines = split_wide_gaps(ocr.find_text_lines(&input, &words));
    st.layout_ms = now() - t;

    let t = now();
    let texts = recognise_batched(ocr, &input, &lines, 16)?;
    st.lines_recognised = lines.len();
    let mut read: Vec<(usize, za::Line)> = Vec::new();
    for (li, text) in texts.into_iter().enumerate() {
        let Some(text) = text else { continue };
        // The tiled reading drops an MRZ-looking line from the words (it
        // goes to the MRZ decoder, which labels never use).
        if mrz::looks_like_mrz(&text.to_string()) {
            continue;
        }
        for word in text.words() {
            let r = word.bounding_rect();
            let mut word_text = word.to_string();
            if word_text.contains('?')
                && word_text.chars().filter(|c| c.is_ascii_uppercase()).count() * 2 >= word_text.chars().count()
                && let Some(rec) = recognition
            {
                let pad = 2.0;
                let rect = RotatedRect::from_rect(rten_imageproc::RectF::from_tlbr(
                    r.top() as f32 - pad,
                    r.left() as f32 - pad,
                    r.bottom() as f32 + pad,
                    r.right() as f32 + pad,
                ));
                let img = ocr.prepare_recognition_input(&input, &[rect])?;
                let [ih, iw] = img.shape();
                let out: NdTensor<f32, 3> = rec.run_one(img.into_shape([1, 1, ih, iw]).view().into(), None)?.try_into()?;
                let again = mrz_decode::greedy_restricted(out.slice((.., 0, ..)), "ABCDEFGHIJKLMNOPQRSTUVWXYZ-'");
                if !again.is_empty() {
                    word_text = again;
                }
            }
            read.push((lines[li].len(), za::Line { text: word_text, x: r.left() as f32, y: r.top() as f32, w: r.width() as f32, h: r.height() as f32 }));
        }
    }
    st.recognise_ms = now() - t;

    // Words read twice (by two overlapping line crops): keep the reading
    // from the line with more words, whose crop fits the text best.
    read.sort_by(|a, b| b.0.cmp(&a.0));
    let mut words: Vec<za::Line> = Vec::new();
    for (_, l) in read {
        if !words.iter().any(|k| overlaps(k, &l)) {
            words.push(l);
        }
    }
    let mut out = za::rows_from_words(words);
    if skew.abs() >= 1.0 {
        for l in &mut out {
            let c = [[l.x, l.y], [l.x + l.w, l.y], [l.x, l.y + l.h], [l.x + l.w, l.y + l.h]].map(|p| geometry::rotated_to_source(p, w, h, skew));
            let (x0, x1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
            let (y0, y1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
            (l.x, l.y, l.w, l.h) = (x0, y0, x1 - x0, y1 - y0);
        }
    }
    out.sort_by(|a, b| a.y.total_cmp(&b.y).then(a.x.total_cmp(&b.x)));
    Ok((out, st))
}

fn overlaps(k: &za::Line, l: &za::Line) -> bool {
    let ow = (k.x + k.w).min(l.x + l.w) - k.x.max(l.x);
    let oh = (k.y + k.h).min(l.y + l.h) - k.y.max(l.y);
    ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (l.w * l.h).min(k.w * k.h)
}

/// Words of a levelled grey plane, tile by tile at the baseline's tile
/// positions (each tile enlarged up to 2× when the frame is smaller than the
/// model's input, as the baseline does), merged keeping the larger box.
fn detect_tiles(ocr: &OcrEngine, grey: &[u8], w: usize, h: usize, st: &mut Stats) -> anyhow::Result<Vec<RotatedRect>> {
    let (tw, th) = (TILE_W.min(w), TILE_H.min(h));
    let mut found: Vec<RotatedRect> = Vec::new();
    for &y0 in &tile_starts(h, th) {
        for &x0 in &tile_starts(w, tw) {
            let mut tile = Vec::with_capacity(tw * th);
            for y in y0..y0 + th {
                tile.extend_from_slice(&grey[y * w + x0..y * w + x0 + tw]);
            }
            let k = ((TILE_W as f32 / tw as f32).min(TILE_H as f32 / th as f32)).clamp(1.0, 2.0);
            let (tile, sw, sh) = if k > 1.05 { scale_grey(&tile, tw, th, k) } else { (tile, tw, th) };
            let input = ocr.prepare_input(ImageSource::from_bytes(&tile, (sw as u32, sh as u32))?)?;
            st.detection_passes += 1;
            st.detection_px += TILE_W * TILE_H;
            for r in ocr.detect_words(&input)? {
                let c = r.center();
                found.push(RotatedRect::new(Point::from_yx(c.y / k + y0 as f32, c.x / k + x0 as f32), r.up_axis(), r.width() / k, r.height() / k));
            }
        }
    }
    let area = |r: &RotatedRect| r.width() * r.height();
    found.sort_by(|a, b| area(b).total_cmp(&area(a)));
    let mut words: Vec<RotatedRect> = Vec::new();
    for r in found {
        let b = r.bounding_rect();
        let dup = words.iter().any(|k| {
            let kb = k.bounding_rect();
            let ow = kb.right().min(b.right()) - kb.left().max(b.left());
            let oh = kb.bottom().min(b.bottom()) - kb.top().max(b.top());
            ow > 0.0 && oh > 0.0 && ow * oh > 0.5 * (b.width() * b.height()).min(kb.width() * kb.height())
        });
        if !dup {
            words.push(r);
        }
    }
    Ok(words)
}

fn scale_grey(g: &[u8], w: usize, h: usize, k: f32) -> (Vec<u8>, usize, usize) {
    let rgba: Vec<u8> = g.iter().flat_map(|&v| [v, v, v, 255]).collect();
    let (s, sw, sh) = quality::scale_rgba(&rgba, w, h, k);
    (s.chunks_exact(4).map(|p| p[0]).collect(), sw, sh)
}

/// Words of a levelled grey plane from the free-size page detector, on
/// strips the width of the frame (`Scanner::detect_page`'s strip scheme and
/// ocrs's own mask-to-rectangle steps: threshold 0.2, contours simplified,
/// the minimum-area rectangle grown by 3 px, at least 100 px²). Its input is
/// normalised as ocrs normalises (value / 255 − 0.5, padding −0.5).
fn detect_page(det: &rten::Model, grey: &[u8], w: usize, h: usize, st: &mut Stats) -> anyhow::Result<Vec<RotatedRect>> {
    use rten_imageproc::{RetrievalMode, find_contours, min_area_rect, simplify_polygon};
    const STRIP: usize = 384;
    const OVERLAP: usize = 64;
    let pw = w.next_multiple_of(32);
    let sh = STRIP.min(h.next_multiple_of(32));
    let mut starts = vec![0usize];
    while starts.last().unwrap() + sh < h {
        starts.push((starts.last().unwrap() + sh - OVERLAP).min(h.saturating_sub(sh)));
    }
    let mut prob = vec![0f32; w * h];
    for (k, &y0) in starts.iter().enumerate() {
        let mut input = NdTensor::full([1, 1, sh, pw], -0.5f32);
        for y in 0..sh.min(h - y0) {
            for x in 0..w {
                input[[0, 0, y, x]] = grey[(y0 + y) * w + x] as f32 / 255.0 - 0.5;
            }
        }
        st.detection_passes += 1;
        st.detection_px += sh * pw;
        let out: NdTensor<f32, 4> = det.run_one(input.view().as_dyn().into(), None)?.try_into()?;
        let top = if k == 0 { 0 } else { (starts[k - 1] + sh).saturating_sub(y0) / 2 };
        let bottom = if k + 1 == starts.len() { sh.min(h - y0) } else { (y0 + sh - starts[k + 1]) / 2 + (starts[k + 1] - y0) };
        for y in top..bottom.min(h - y0) {
            for x in 0..w {
                prob[(y0 + y) * w + x] = out[[0, 0, y, x]];
            }
        }
    }
    let mask = NdTensor::from_fn([h, w], |[y, x]| prob[y * w + x] > 0.2);
    Ok(find_contours(mask.view(), RetrievalMode::External)
        .iter()
        .filter_map(|poly| {
            let pts: Vec<_> = poly.iter().map(|p| p.to_f32()).collect();
            min_area_rect(&simplify_polygon(&pts, 2.0)).map(|mut r| {
                r.resize(r.width() + 6.0, r.height() + 6.0);
                r
            })
        })
        .filter(|r| r.area() >= 100.0)
        .collect())
}

/// A "line" of word boxes far apart is recognised as one crop spanning the
/// gap, which reads every word in between a second time: split at gaps wider
/// than three line heights.
fn split_wide_gaps(lines: Vec<Vec<RotatedRect>>) -> Vec<Vec<RotatedRect>> {
    let mut split: Vec<Vec<RotatedRect>> = Vec::new();
    for line in lines {
        let mut cur: Vec<RotatedRect> = Vec::new();
        for r in line {
            if let Some(prev) = cur.last() {
                let (pb, b) = (prev.bounding_rect(), r.bounding_rect());
                let h = pb.height().max(b.height()).max(1.0);
                if b.left() - pb.right() > 3.0 * h {
                    split.push(std::mem::take(&mut cur));
                }
            }
            cur.push(r);
        }
        if !cur.is_empty() {
            split.push(cur);
        }
    }
    split
}

/// Lines recognised in batches of `batch` lines of similar width (ocrs pads
/// a batch to its widest line), readings returned in the input order.
fn recognise_batched(ocr: &OcrEngine, input: &ocrs::OcrInput, lines: &[Vec<RotatedRect>], batch: usize) -> anyhow::Result<Vec<Option<ocrs::TextLine>>> {
    let aspect = |line: &[RotatedRect]| {
        let (x0, x1) = line.iter().map(|r| r.bounding_rect()).fold((f32::MAX, f32::MIN), |(a, b), r| (a.min(r.left()), b.max(r.right())));
        let h = line.iter().map(|r| r.bounding_rect().height()).fold(1.0f32, f32::max);
        (x1 - x0) / h
    };
    let mut order: Vec<usize> = (0..lines.len()).collect();
    order.sort_by(|&a, &b| aspect(&lines[a]).total_cmp(&aspect(&lines[b])));
    let mut texts: Vec<Option<ocrs::TextLine>> = vec![None; lines.len()];
    for chunk in order.chunks(batch.max(1)) {
        let group: Vec<Vec<RotatedRect>> = chunk.iter().map(|&i| lines[i].clone()).collect();
        for (&i, t) in chunk.iter().zip(ocr.recognize_text(input, &group)?) {
            texts[i] = t;
        }
    }
    Ok(texts)
}

/// Lines of a PP-OCRv6 reading as rows, for [`crate::labels::associate`].
pub fn rows_from_paddle(lines: &[crate::text_v6::PaddleTextLine]) -> Vec<za::Line> {
    za::rows_from_words(lines.iter().map(|l| za::Line { text: l.text.clone(), x: l.x, y: l.y, w: l.w, h: l.h }).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tile_starts_match_the_baseline() {
        // 720 × 1280: two columns, three rows (six tiles), as the tiled reading.
        assert_eq!(tile_starts(720, 600), vec![0, 120]);
        assert_eq!(tile_starts(1280, 800), vec![0, 240, 480]);
        assert_eq!(tile_starts(1280, 600), vec![0, 340, 680]);
        assert_eq!(tile_starts(480, 800), vec![0]);
    }

    #[test]
    fn wide_gaps_split_lines() {
        let r = |x: f32| RotatedRect::from_rect(rten_imageproc::RectF::from_tlbr(0.0, x, 10.0, x + 20.0));
        let lines = split_wide_gaps(vec![vec![r(0.0), r(25.0), r(200.0)]]);
        assert_eq!(lines.iter().map(|l| l.len()).collect::<Vec<_>>(), vec![2, 1]);
    }
}
