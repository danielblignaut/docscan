//! Where a labelled reading needs print read: the regions around a frame's
//! barcodes.
//!
//! `Scanner::labelled_native` reads the whole frame in overlapping OCR tiles
//! (six 600 × 800 tiles for a 720 × 1280 photo), though the print it pairs
//! with codes sits beside the bars: the label above a code (`IMEI1:`), the
//! digits under an EAN's bars, a value printed to a code's left, and the
//! code-less lines (`SN: …`) of the same sticker. [`plan`] grows every bar
//! patch, read or not, by margins that reach those lines, merges patches that
//! touch, and returns the few rectangles worth reading. When there are no bars
//! at all, or the grown patches cover most of the frame, it plans the whole
//! frame, which is what the full reading does: the plan can only remove OCR
//! work, never read less than the whole frame where nothing locates the print.
//!
//! Pure geometry over pixel rectangles (`[x, y, w, h]`, frame pixels): no
//! image, model or crate type, so it is cheap to test and to call from either
//! the native or the wasm entry point.

/// What a plan covers.
#[derive(Debug, Clone, PartialEq)]
pub struct Plan {
    /// Rectangles to read, `[x, y, w, h]` in whole frame pixels, inside the
    /// frame and not overlapping each other by more than their merge.
    pub rects: Vec<[u32; 4]>,
    /// Why the whole frame is read, when it is.
    pub whole_frame: Option<WholeFrame>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WholeFrame {
    /// No bar patch and no decoded code: nothing says where the print is.
    NoBars,
    /// The grown patches cover at least [`MAX_COVER`] of the frame: cropping
    /// would save little and could cut a line.
    MostOfFrame,
}

/// Above this share of the frame, the whole frame is read instead.
pub const MAX_COVER: f32 = 0.6;

/// The margins a bar patch is grown by, in multiples of the patch's shorter
/// side (`across`, the bars' height for a linear code) and its longer side
/// (`along`), with a floor in pixels. Vertical margins reach a label line and
/// the next labelled row above and below; horizontal ones a label or value
/// printed beside the bars.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Margins {
    pub vertical_across: f32,
    pub vertical_along: f32,
    pub horizontal_across: f32,
    pub horizontal_along: f32,
    pub min_px: f32,
}

/// The frozen candidate (`wide`; see `docs/performance-barcode.md`). On the
/// DEV labelled frames it still loses fields the whole-frame reading lists,
/// so it is not a replacement for it.
pub const MARGINS: Margins = Margins { vertical_across: 1.5, vertical_along: 0.4, horizontal_across: 1.0, horizontal_along: 0.4, min_px: 48.0 };

/// Tighter margins for an early, provisional reading shown while the
/// whole-frame reading runs (`tight`): one detection pass on a device-label
/// photo, but it loses and invents more fields, so its result must be
/// replaced by the whole-frame reading's.
pub const PREVIEW_MARGINS: Margins = Margins { vertical_across: 0.6, vertical_along: 0.15, horizontal_across: 0.3, horizontal_along: 0.1, min_px: 32.0 };

impl Margins {
    /// From `[vertical_across, vertical_along, horizontal_across,
    /// horizontal_along, min_px]`; anything else gives [`MARGINS`].
    pub fn from_slice(v: &[f32]) -> Margins {
        match v {
            [a, b, c, d, e] => Margins { vertical_across: *a, vertical_along: *b, horizontal_across: *c, horizontal_along: *d, min_px: *e },
            _ => MARGINS,
        }
    }
}

/// Grown rectangles closer than this (pixels) are merged into one: a line
/// between two patches must not be cut by both crops.
pub const MERGE_GAP_PX: f32 = 24.0;

/// The bar rectangle of a decoded code from its corner or end points: a
/// linear code reports only its scan line, so the bar patch containing the
/// line's centre is used when there is one, otherwise the line is given a
/// height of a third of its length (a typical linear code's aspect).
pub fn code_box(points: &[[f32; 2]], regions: &[[f32; 4]]) -> Option<[f32; 4]> {
    if points.is_empty() {
        return None;
    }
    let (x0, x1) = points.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
    let (y0, y1) = points.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
    let (cx, cy) = ((x0 + x1) / 2.0, (y0 + y1) / 2.0);
    if let Some(r) = regions.iter().find(|r| cx >= r[0] && cx <= r[0] + r[2] && cy >= r[1] && cy <= r[1] + r[3]) {
        return Some(*r);
    }
    let (w, h) = (x1 - x0, y1 - y0);
    if points.len() <= 2 {
        let len = w.hypot(h);
        // Thicken across the scan line.
        let t = len / 3.0;
        return Some(if w >= h { [x0, cy - t / 2.0, w, t] } else { [cx - t / 2.0, y0, t, h] });
    }
    Some([x0, y0, w, h])
}

/// The rectangles to read for a `width` × `height` frame with these bar
/// patches (`barcode::oriented_regions`, read or not) and decoded codes'
/// points.
pub fn plan(width: u32, height: u32, regions: &[[f32; 4]], codes: &[Vec<[f32; 2]>], margins: Margins) -> Plan {
    let (fw, fh) = (width as f32, height as f32);
    let whole = |why| Plan { rects: vec![[0, 0, width, height]], whole_frame: Some(why) };
    let mut bars: Vec<[f32; 4]> = regions.to_vec();
    bars.extend(codes.iter().filter_map(|p| code_box(p, regions)));
    if bars.is_empty() || width == 0 || height == 0 {
        return whole(WholeFrame::NoBars);
    }
    // Grow each patch, clamped to the frame.
    let mut grown: Vec<[f32; 4]> = bars
        .iter()
        .map(|b| {
            let (across, along) = (b[2].min(b[3]), b[2].max(b[3]));
            let my = (margins.vertical_across * across + margins.vertical_along * along).max(margins.min_px);
            let mx = (margins.horizontal_across * across + margins.horizontal_along * along).max(margins.min_px);
            clamp([b[0] - mx, b[1] - my, b[2] + 2.0 * mx, b[3] + 2.0 * my], fw, fh)
        })
        .filter(|r| r[2] > 0.0 && r[3] > 0.0)
        .collect();
    // Merge rectangles that overlap or nearly touch, until none do.
    loop {
        let mut merged = false;
        'outer: for i in 0..grown.len() {
            for j in i + 1..grown.len() {
                if near(grown[i], grown[j], MERGE_GAP_PX) {
                    grown[i] = union(grown[i], grown[j]);
                    grown.swap_remove(j);
                    merged = true;
                    break 'outer;
                }
            }
        }
        if !merged {
            break;
        }
    }
    let area: f32 = grown.iter().map(|r| r[2] * r[3]).sum();
    if area >= MAX_COVER * fw * fh {
        return whole(WholeFrame::MostOfFrame);
    }
    grown.sort_by(|a, b| a[1].total_cmp(&b[1]).then(a[0].total_cmp(&b[0])));
    let rects = grown
        .iter()
        .map(|r| {
            let (x0, y0) = (r[0].floor().max(0.0) as u32, r[1].floor().max(0.0) as u32);
            let (x1, y1) = (((r[0] + r[2]).ceil() as u32).min(width), ((r[1] + r[3]).ceil() as u32).min(height));
            [x0, y0, x1 - x0, y1 - y0]
        })
        .filter(|r| r[2] >= 16 && r[3] >= 16)
        .collect::<Vec<_>>();
    if rects.is_empty() {
        return whole(WholeFrame::NoBars);
    }
    Plan { rects, whole_frame: None }
}

/// Copies `rect` out of an RGBA frame `width` pixels wide.
pub fn crop_rgba(rgba: &[u8], width: u32, rect: [u32; 4]) -> Vec<u8> {
    let [x, y, w, h] = rect.map(|v| v as usize);
    let stride = width as usize * 4;
    let mut out = Vec::with_capacity(w * h * 4);
    for row in y..y + h {
        out.extend_from_slice(&rgba[row * stride + x * 4..row * stride + (x + w) * 4]);
    }
    out
}

/// The text detector's input (ocrs pads or resizes every image to it): one
/// detection pass costs the same for a 100 px crop as for a full tile.
pub const CANVAS: [u32; 2] = [600, 800];

/// White space between packed crops, so no line of print joins two.
pub const GUTTER_PX: u32 = 48;

/// Where one planned rectangle is drawn on a shared canvas.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Placement {
    pub canvas: usize,
    /// The rectangle in frame pixels, `[x, y, w, h]`.
    pub source: [u32; 4],
    /// Its top-left corner on the canvas.
    pub at: [u32; 2],
}

/// Packs rectangles onto as few [`CANVAS`]-sized canvases as fit them
/// (shelves, tallest first), at their own scale, so every canvas costs one
/// detection pass however many crops it holds. Rectangles larger than a
/// canvas are returned apart, to be read in tiles as before.
pub fn pack(rects: &[[u32; 4]]) -> (Vec<Placement>, Vec<[u32; 4]>) {
    let [cw, ch] = CANVAS;
    let mut order: Vec<usize> = (0..rects.len()).collect();
    order.sort_by_key(|&i| std::cmp::Reverse(rects[i][3]));
    // Per canvas, its shelves: (top, height, next free x).
    let mut canvases: Vec<Vec<(u32, u32, u32)>> = Vec::new();
    let (mut placed, mut apart) = (Vec::new(), Vec::new());
    for i in order {
        let r = rects[i];
        let (w, h) = (r[2], r[3]);
        if w > cw || h > ch {
            apart.push(r);
            continue;
        }
        let mut spot = None;
        'find: for (ci, shelves) in canvases.iter_mut().enumerate() {
            for s in shelves.iter_mut() {
                let x = if s.2 == 0 { 0 } else { s.2 + GUTTER_PX };
                if h <= s.1 && x + w <= cw {
                    s.2 = x + w;
                    spot = Some((ci, [x, s.0]));
                    break 'find;
                }
            }
            let top = shelves.last().map_or(0, |s| s.0 + s.1 + GUTTER_PX);
            if top + h <= ch {
                shelves.push((top, h, w));
                spot = Some((ci, [0, top]));
                break 'find;
            }
        }
        let (canvas, at) = spot.unwrap_or_else(|| {
            canvases.push(vec![(0, h, w)]);
            (canvases.len() - 1, [0, 0])
        });
        placed.push(Placement { canvas, source: r, at });
    }
    (placed, apart)
}

/// Draws a canvas's crops on white, as RGBA of [`CANVAS`] size.
pub fn compose(rgba: &[u8], width: u32, placements: &[Placement], canvas: usize) -> Vec<u8> {
    let [cw, ch] = CANVAS.map(|v| v as usize);
    let mut out = vec![255u8; cw * ch * 4];
    for p in placements.iter().filter(|p| p.canvas == canvas) {
        let [x, y, w, h] = p.source.map(|v| v as usize);
        let [ax, ay] = p.at.map(|v| v as usize);
        let stride = width as usize * 4;
        for row in 0..h {
            let src = (y + row) * stride + x * 4;
            let dst = ((ay + row) * cw + ax) * 4;
            out[dst..dst + w * 4].copy_from_slice(&rgba[src..src + w * 4]);
        }
    }
    out
}

/// A box read on `canvas` back in frame pixels: the crop holding its centre,
/// or `None` when it lies in a gutter.
pub fn canvas_to_frame(placements: &[Placement], canvas: usize, b: [f32; 4]) -> Option<[f32; 4]> {
    let (cx, cy) = (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0);
    placements.iter().filter(|p| p.canvas == canvas).find_map(|p| {
        let (ax, ay, w, h) = (p.at[0] as f32, p.at[1] as f32, p.source[2] as f32, p.source[3] as f32);
        (cx >= ax && cx <= ax + w && cy >= ay && cy <= ay + h).then(|| [b[0] - ax + p.source[0] as f32, b[1] - ay + p.source[1] as f32, b[2], b[3]])
    })
}

fn clamp(r: [f32; 4], fw: f32, fh: f32) -> [f32; 4] {
    let (x0, y0) = (r[0].max(0.0), r[1].max(0.0));
    let (x1, y1) = ((r[0] + r[2]).min(fw), (r[1] + r[3]).min(fh));
    [x0, y0, (x1 - x0).max(0.0), (y1 - y0).max(0.0)]
}

fn union(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    let (x0, y0) = (a[0].min(b[0]), a[1].min(b[1]));
    let (x1, y1) = ((a[0] + a[2]).max(b[0] + b[2]), (a[1] + a[3]).max(b[1] + b[3]));
    [x0, y0, x1 - x0, y1 - y0]
}

fn near(a: [f32; 4], b: [f32; 4], gap: f32) -> bool {
    a[0] - gap <= b[0] + b[2] && b[0] - gap <= a[0] + a[2] && a[1] - gap <= b[1] + b[3] && b[1] - gap <= a[1] + a[3]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_bars_reads_the_whole_frame() {
        let p = plan(720, 1280, &[], &[], MARGINS);
        assert_eq!(p.rects, vec![[0, 0, 720, 1280]]);
        assert_eq!(p.whole_frame, Some(WholeFrame::NoBars));
    }

    #[test]
    fn one_code_reads_a_grown_patch_inside_the_frame() {
        let p = plan(720, 1280, &[[200.0, 600.0, 300.0, 60.0]], &[], MARGINS);
        assert_eq!(p.whole_frame, None);
        assert_eq!(p.rects.len(), 1);
        let [x, y, w, h] = p.rects[0];
        // Reaches a label line above and the digits below, and stays in frame.
        assert!(y + 90 <= 600 && y + h >= 660 + 90 && x + w <= 720);
        assert!(w * h < 720 * 1280 / 2);
    }

    #[test]
    fn touching_patches_merge_and_a_covered_frame_falls_back() {
        let two = plan(720, 1280, &[[100.0, 400.0, 300.0, 60.0], [100.0, 560.0, 300.0, 60.0]], &[], MARGINS);
        assert_eq!(two.rects.len(), 1);
        let spread: Vec<[f32; 4]> = (0..6).map(|i| [50.0 + (i % 2) as f32 * 330.0, 60.0 + (i / 2) as f32 * 420.0, 300.0, 80.0]).collect();
        assert_eq!(plan(720, 1280, &spread, &[], MARGINS).whole_frame, Some(WholeFrame::MostOfFrame));
    }

    #[test]
    fn a_linear_scan_line_takes_its_bar_patch_or_a_thickened_box() {
        let line = vec![[100.0, 300.0], [400.0, 300.0]];
        assert_eq!(code_box(&line, &[[90.0, 260.0, 320.0, 80.0]]), Some([90.0, 260.0, 320.0, 80.0]));
        let b = code_box(&line, &[]).unwrap();
        assert!((b[3] - 100.0).abs() < 1e-3 && b[1] < 300.0 && b[1] + b[3] > 300.0);
    }

    #[test]
    fn crops_share_a_canvas_and_map_back() {
        let rects = [[300, 380, 380, 370], [240, 810, 430, 380], [110, 120, 110, 90], [0, 0, 720, 900]];
        let (placed, apart) = pack(&rects);
        assert_eq!(apart, vec![[0, 0, 720, 900]]);
        assert_eq!(placed.len(), 3);
        for p in &placed {
            let [x, y] = p.at;
            assert!(x + p.source[2] <= CANVAS[0] && y + p.source[3] <= CANVAS[1]);
        }
        // No two placements on one canvas overlap, gutters included.
        for a in &placed {
            for b in placed.iter().filter(|b| b.canvas == a.canvas && *b != a) {
                let sep = |a: &Placement, b: &Placement, k: usize| a.at[k] + a.source[2 + k] + GUTTER_PX <= b.at[k];
                assert!(sep(a, b, 0) || sep(b, a, 0) || sep(a, b, 1) || sep(b, a, 1));
            }
        }
        let p = placed[0];
        let inside = [p.at[0] as f32 + 10.0, p.at[1] as f32 + 20.0, 30.0, 12.0];
        assert_eq!(canvas_to_frame(&placed, p.canvas, inside), Some([p.source[0] as f32 + 10.0, p.source[1] as f32 + 20.0, 30.0, 12.0]));
        let rgba = vec![7u8; 720 * 1280 * 4];
        let c = compose(&rgba, 720, &placed, 0);
        assert_eq!(c.len(), (CANVAS[0] * CANVAS[1] * 4) as usize);
        assert!(c.contains(&255) && c.contains(&7));
    }

    #[test]
    fn crop_copies_rows() {
        let rgba: Vec<u8> = (0..4 * 4 * 3).map(|v| v as u8).collect();
        let c = crop_rgba(&rgba, 4, [1, 1, 2, 2]);
        assert_eq!(c.len(), 16);
        assert_eq!(&c[..4], &rgba[(4 + 1) * 4..(4 + 1) * 4 + 4]);
    }
}
