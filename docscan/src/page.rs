//! Pages: a proof-of-address document (a bill, a statement, a lease) held up
//! to the camera. [`analyse`] runs on every frame: it finds the page outline
//! with [`quad::find_document`], says whether it has a page's proportions,
//! whether all of it is in view, and whether it is sharp and free of glare.
//! [`enhance`] prepares a captured, flattened page for OCR.

use serde::Serialize;

use crate::{geometry, quad, quality};

/// A4 (and A5, an A4 folded in half): 210 × 297 mm, short ÷ long ≈ 0.707.
pub const A4_RATIO: f32 = 210.0 / 297.0;
/// A4 folded in thirds (a DL letter fold): 210 × 99 mm.
pub const THIRD_RATIO: f32 = 99.0 / 210.0;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PageShape {
    /// A4 or A5 upright.
    Portrait,
    /// A4 or A5 on its side, or an A4 folded in half.
    Landscape,
    /// A third of an A4 page, as folded into a window envelope.
    Third,
    /// An outline, but not a page's proportions.
    Other,
}

/// Classifies a flattened outline's proportions. Perspective and a curled
/// page shift the measured ratio, so the bands are generous.
pub fn shape(width: usize, height: usize) -> PageShape {
    let r = width.min(height) as f32 / width.max(height).max(1) as f32;
    if (r - A4_RATIO).abs() <= 0.06 {
        if height >= width { PageShape::Portrait } else { PageShape::Landscape }
    } else if (r - THIRD_RATIO).abs() <= 0.07 {
        PageShape::Third
    } else {
        PageShape::Other
    }
}

/// Laplacian variance (see [`quality::measure`]) below which a page measured
/// at [`QUALITY_WIDTH`] is too blurred for its small print. Calibrated on the
/// synthetic camera set (`eval/poa_eval.py --calibrate`).
pub const SHARPNESS_MIN: f32 = 120.0;
/// More than this fraction of the page washed out hides text. Mild highlights
/// (the synthetic camera set: up to a quarter of the blocks blown out) still
/// read, so only a large one holds the capture back.
pub const GLARE_MAX: f32 = 0.3;
/// The width the page is flattened to for the per-frame quality measure.
pub const QUALITY_WIDTH: usize = 800;

#[derive(Debug, Clone, Serialize)]
pub struct PageAnalysis {
    /// The page outline in the frame, clockwise from top-left.
    pub outline: Option<quad::Quad>,
    pub shape: Option<PageShape>,
    /// The outline's measured size in frame pixels (its flattened size).
    pub size: Option<[u32; 2]>,
    /// Every corner lies inside the frame: nothing of the page is cut off.
    pub in_view: bool,
    /// Measured on the flattened page (or the frame when there is none).
    pub quality: quality::Quality,
    /// A page in view, sharp, lit and free of glare: worth capturing.
    pub accepted: bool,
    /// Why not, when not accepted (the first reason is the one to show).
    pub reasons: Vec<String>,
    /// No page outline was found, but the guide is filled with paper: the
    /// guide's own rectangle ([`guide_quad`]), for a capture to fall back on
    /// (flagged as such) when no frame gives an outline.
    #[serde(default)]
    pub guide: Option<quad::Quad>,
    pub ms: f64,
}

/// Share of the guide's samples that must look like paper for the guide-crop fallback.
pub const GUIDE_PAPER_MIN: f32 = 0.6;

/// The capture guide in a frame: the largest centred A4 rectangle (upright
/// in a portrait frame, on its side in a landscape one) covering 94% of the
/// frame along its binding side, as the page is framed when held to fill it.
pub fn guide_quad(w: usize, h: usize) -> quad::Quad {
    let (fw, fh) = (w as f32, h as f32);
    let ratio = if h >= w { A4_RATIO } else { 1.0 / A4_RATIO }; // width / height
    let (mut gw, mut gh) = (0.94 * fw, 0.94 * fw / ratio);
    if gh > 0.94 * fh {
        gh = 0.94 * fh;
        gw = gh * ratio;
    }
    let (x0, y0) = ((fw - gw) / 2.0, (fh - gh) / 2.0);
    quad::Quad { corners: [[x0, y0], [x0 + gw, y0], [x0 + gw, y0 + gh], [x0, y0 + gh]], support: 0.0 }
}

/// Share of pale, unsaturated (paper-like) samples inside a quadrilateral.
pub fn paper_share(rgba: &[u8], w: usize, h: usize, q: &quad::Quad) -> f32 {
    let c = &q.corners;
    let (mut paper, mut n) = (0, 0);
    for j in 0..20 {
        for i in 0..14 {
            let (u, v) = ((i as f32 + 0.5) / 14.0, (j as f32 + 0.5) / 20.0);
            let top = [c[0][0] + (c[1][0] - c[0][0]) * u, c[0][1] + (c[1][1] - c[0][1]) * u];
            let bot = [c[3][0] + (c[2][0] - c[3][0]) * u, c[3][1] + (c[2][1] - c[3][1]) * u];
            let (x, y) = ((top[0] + (bot[0] - top[0]) * v) as usize, (top[1] + (bot[1] - top[1]) * v) as usize);
            if x >= w || y >= h {
                continue;
            }
            let p = &rgba[(y * w + x) * 4..(y * w + x) * 4 + 3];
            let (mx, mn) = (p[0].max(p[1]).max(p[2]) as i32, p[0].min(p[1]).min(p[2]) as i32);
            let l = (p[0] as i32 * 77 + p[1] as i32 * 150 + p[2] as i32 * 29) / 256;
            n += 1;
            if l > 140 && mx - mn < 45 {
                paper += 1;
            }
        }
    }
    if n == 0 { 0.0 } else { paper as f32 / n as f32 }
}

/// One frame's page analysis: the outline, its shape, whether it is wholly
/// in view, and the quality of the flattened page.
pub fn analyse(rgba: &[u8], w: usize, h: usize) -> PageAnalysis {
    let t0 = crate::now();
    let luma = quality::rgba_to_luma(rgba);
    let outline = quad::find_page(rgba, w, h);
    let mut reasons = Vec::new();
    let (quality, shape, size, in_view) = match &outline {
        Some(q) => {
            let (ow, oh) = quad::output_size(q, usize::MAX >> 1);
            let (qw, qh) = (QUALITY_WIDTH, (QUALITY_WIDTH as f32 * oh as f32 / ow.max(1) as f32).round() as usize);
            let flat = quad::warp(&luma, w, h, 1, &q.corners, qw, qh.max(32));
            let quality = match flat {
                Some(img) => page_quality(&img, qw, qh.max(32)),
                None => page_quality(&luma, w, h),
            };
            // Corners may be found a little outside the frame (find_document
            // allows 8%); any outside means part of the page is cut off.
            let margin = 0.005 * w.max(h) as f32;
            let in_view = q.corners.iter().all(|p| {
                p[0] >= margin && p[1] >= margin && p[0] <= w as f32 - margin && p[1] <= h as f32 - margin
            });
            (quality, Some(shape(ow, oh)), Some([ow as u32, oh as u32]), in_view)
        }
        None => (page_quality(&luma, w, h), None, None, false),
    };
    if quality.edge_density < 0.01 {
        reasons.push("no page in view".into());
    }
    match (shape, in_view) {
        (None, _) => reasons.push("no page outline".into()),
        (Some(PageShape::Other), _) => reasons.push("the outline is not a page's shape".into()),
        (_, false) => reasons.push("part of the page is out of view".into()),
        _ => {}
    }
    if quality.brightness < 60.0 {
        reasons.push("too dark".into());
    }
    if quality.sharpness < SHARPNESS_MIN {
        reasons.push("blurred".into());
    }
    if quality.glare > GLARE_MAX {
        reasons.push("glare".into());
    }
    let guide = if outline.is_none() || shape == Some(PageShape::Other) {
        let g = guide_quad(w, h);
        (paper_share(rgba, w, h, &g) >= GUIDE_PAPER_MIN).then_some(g)
    } else {
        None
    };
    PageAnalysis {
        guide,
        outline,
        shape,
        size,
        in_view,
        quality,
        accepted: reasons.is_empty(),
        reasons,
        ms: crate::now() - t0,
    }
}

/// [`quality::measure`], with glare judged against the paper. White paper
/// photographed under good light is near-saturated everywhere, so blown-out
/// blocks are glare only when the paper itself is not blown out: when the
/// typical block peaks below 245, a block saturated through is a highlight.
fn page_quality(luma: &[u8], w: usize, h: usize) -> quality::Quality {
    let mut q = quality::measure(luma, w, h);
    let factor = (w / 400).max(1);
    let (img, sw, sh) = quality::downscale(luma, w, h, factor);
    const B: usize = 12;
    let mut peaks = Vec::new();
    for by in 0..sh / B {
        for bx in 0..sw / B {
            let mut m = 0u8;
            for y in by * B..(by + 1) * B {
                m = m.max(*img[y * sw + bx * B..y * sw + (bx + 1) * B].iter().max().unwrap_or(&0));
            }
            peaks.push(m);
        }
    }
    peaks.sort_unstable();
    let paper = peaks.get(peaks.len() / 2).copied().unwrap_or(0);
    if paper >= 245 {
        q.glare = 0.0;
    }
    q
}

/// A flattened page made ready for OCR: one plane (the brightest channel,
/// [`quality::rgba_to_ink`], or luma), levelled by its estimated skew, and
/// contrast-normalised against the paper. The paper's own brightness is
/// estimated as a smooth surface (the maximum over coarse blocks, blurred),
/// and every pixel divided by it, which removes shadows, vignetting and
/// uneven light; the result is then stretched so the paper is white and the
/// darkest print black.
pub fn enhance(rgba: &[u8], w: usize, h: usize, plane: Plane) -> (Vec<u8>, usize, usize) {
    let img = match plane {
        Plane::Ink => quality::rgba_to_ink(rgba),
        Plane::Luma => quality::rgba_to_luma(rgba),
    };
    let skew = geometry::estimate_skew(&img, w, h);
    // Only small residual skews: a flattened page is level to within a few
    // degrees, and a large estimate comes from a table's diagonal or a logo.
    let (img, w, h) = if skew.abs() >= 0.5 && skew.abs() <= 6.0 { geometry::rotate(&img, w, h, skew) } else { (img, w, h) };
    (normalise(&img, w, h), w, h)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Plane {
    Ink,
    Luma,
}

/// Divides by the estimated paper brightness, then stretches the levels.
fn normalise(img: &[u8], w: usize, h: usize) -> Vec<u8> {
    // Block maxima: a block of ~3% of the page always holds some paper.
    let b = (w.max(h) / 32).max(8);
    let (bw, bh) = (w.div_ceil(b), h.div_ceil(b));
    let mut bg = vec![0f32; bw * bh];
    for by in 0..bh {
        for bx in 0..bw {
            let mut vals: Vec<u8> = Vec::with_capacity(b * b);
            for y in by * b..((by + 1) * b).min(h) {
                vals.extend_from_slice(&img[y * w + bx * b..y * w + ((bx + 1) * b).min(w)]);
            }
            // The 95th percentile rather than the maximum: noise and specks.
            vals.sort_unstable();
            bg[by * bw + bx] = vals[(vals.len() * 95 / 100).min(vals.len() - 1)] as f32;
        }
    }
    // A block that is all print (a dark header band) is lifted towards its
    // neighbours: take the max over a 3 × 3 neighbourhood, then average.
    let at = |g: &[f32], x: isize, y: isize| g[(y.clamp(0, bh as isize - 1) as usize) * bw + x.clamp(0, bw as isize - 1) as usize];
    let mut dil = vec![0f32; bw * bh];
    for y in 0..bh as isize {
        for x in 0..bw as isize {
            let mut m = 0f32;
            for dy in -1..=1 {
                for dx in -1..=1 {
                    m = m.max(at(&bg, x + dx, y + dy));
                }
            }
            dil[y as usize * bw + x as usize] = m;
        }
    }
    let mut smooth = vec![0f32; bw * bh];
    for y in 0..bh as isize {
        for x in 0..bw as isize {
            let mut s = 0f32;
            for dy in -1..=1 {
                for dx in -1..=1 {
                    s += at(&dil, x + dx, y + dy);
                }
            }
            smooth[y as usize * bw + x as usize] = (s / 9.0).max(1.0);
        }
    }
    // Bilinear interpolation of the background at each pixel.
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        let fy = ((y as f32 + 0.5) / b as f32 - 0.5).clamp(0.0, (bh - 1) as f32);
        let (y0, ty) = (fy as usize, fy.fract());
        let y1 = (y0 + 1).min(bh - 1);
        for x in 0..w {
            let fx = ((x as f32 + 0.5) / b as f32 - 0.5).clamp(0.0, (bw - 1) as f32);
            let (x0, tx) = (fx as usize, fx.fract());
            let x1 = (x0 + 1).min(bw - 1);
            let g = smooth[y0 * bw + x0] * (1.0 - tx) * (1.0 - ty)
                + smooth[y0 * bw + x1] * tx * (1.0 - ty)
                + smooth[y1 * bw + x0] * (1.0 - tx) * ty
                + smooth[y1 * bw + x1] * tx * ty;
            out[y * w + x] = (img[y * w + x] as f32 / g).min(1.0);
        }
    }
    // Stretch: the 0.5th percentile to black, paper (1.0) to white.
    let mut hist = [0usize; 256];
    for &v in &out {
        hist[(v * 255.0) as usize] += 1;
    }
    let target = out.len() / 200;
    let mut acc = 0;
    let mut lo = 0usize;
    for (i, &n) in hist.iter().enumerate() {
        acc += n;
        if acc > target {
            lo = i;
            break;
        }
    }
    let lo = (lo as f32 / 255.0).min(0.6);
    out.iter().map(|&v| (((v - lo) / (1.0 - lo)).clamp(0.0, 1.0) * 255.0).round() as u8).collect()
}

/// A greyscale image as RGBA, for the OCR entry points that take colour.
pub fn grey_to_rgba(grey: &[u8]) -> Vec<u8> {
    grey.iter().flat_map(|&v| [v, v, v, 255]).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_shapes() {
        assert_eq!(shape(1240, 1754), PageShape::Portrait);
        assert_eq!(shape(1754, 1240), PageShape::Landscape);
        assert_eq!(shape(1240, 877), PageShape::Landscape); // A5: half an A4
        assert_eq!(shape(1240, 585), PageShape::Third);
        assert_eq!(shape(1000, 1000), PageShape::Other);
        assert_eq!(shape(856, 540), PageShape::Other); // an ID card
    }

    /// A page under a strong lighting gradient comes out evenly white, with
    /// its print still dark.
    #[test]
    fn normalise_removes_uneven_light() {
        let (w, h) = (320, 400);
        let mut img = vec![0u8; w * h];
        for y in 0..h {
            for x in 0..w {
                let light = 120.0 + 120.0 * x as f32 / w as f32; // 120 .. 240
                let ink = (y % 20 < 3) && (x % 9 < 6);
                img[y * w + x] = if ink { (light * 0.25) as u8 } else { light as u8 };
            }
        }
        let out = normalise(&img, w, h);
        let paper_left = out[10 * w + 5];
        let paper_right = out[10 * w + w - 5];
        assert!(paper_left > 220 && paper_right > 235, "{paper_left} {paper_right}");
        assert!(out[w + 2] < 80, "print stays dark: {}", out[w + 2]);
    }
}
