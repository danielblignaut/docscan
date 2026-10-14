//! Finding the document in a frame and flattening it.
//!
//! The page is framed by an on-screen guide, so the document fills most of
//! the image and its four edges are long straight lines. A Hough transform
//! (votes restricted to each pixel's own gradient direction) proposes lines,
//! pairs of roughly horizontal and roughly vertical lines form candidate
//! quadrilaterals, and each candidate is scored by how much of its outline
//! lies on a strong edge. The winner is warped to a level rectangle with a
//! homography, which removes the tilt and perspective that defeat both the
//! PDF417 reader and line-based OCR.

use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub struct Quad {
    /// Top-left, top-right, bottom-right, bottom-left, in source pixels.
    pub corners: [[f32; 2]; 4],
    /// Mean fraction of each side lying on a strong edge, 0–1.
    pub support: f32,
}

#[derive(Clone, Copy, Debug)]
struct HLine {
    theta: f32,
    rho: f32,
    votes: f32,
}

const WORK_WIDTH: usize = 400;

struct Gradients {
    w: usize,
    h: usize,
    mag: Vec<f32>,
    /// Gradient direction in radians, (-π, π].
    dir: Vec<f32>,
    threshold: f32,
}

/// Sobel gradients over several planes (the colour channels), keeping the
/// strongest at each pixel: a pale green ID book on a beige desk differs in
/// hue far more than in brightness.
fn gradients(planes: &[Vec<u8>], w: usize, h: usize) -> Gradients {
    let mut mag = vec![0f32; w * h];
    let mut dir = vec![0f32; w * h];
    for img in planes {
        for y in 1..h - 1 {
            for x in 1..w - 1 {
                let p = |dx: isize, dy: isize| img[(y as isize + dy) as usize * w + (x as isize + dx) as usize] as f32;
                let gx = p(1, -1) + 2.0 * p(1, 0) + p(1, 1) - p(-1, -1) - 2.0 * p(-1, 0) - p(-1, 1);
                let gy = p(-1, 1) + 2.0 * p(0, 1) + p(1, 1) - p(-1, -1) - 2.0 * p(0, -1) - p(1, -1);
                let m = (gx * gx + gy * gy).sqrt();
                if m > mag[y * w + x] {
                    mag[y * w + x] = m;
                    dir[y * w + x] = gy.atan2(gx);
                }
            }
        }
    }
    // An edge is in the top quarter of gradient magnitudes. Faint document
    // edges (pale card, pale desk) need a low bar; votes are restricted to
    // each pixel's own direction, which keeps texture from forming lines.
    let mut sorted: Vec<f32> = mag.iter().copied().filter(|m| *m > 0.0).collect();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let threshold = sorted.get(sorted.len() * 75 / 100).copied().unwrap_or(40.0).max(24.0);
    Gradients { w, h, mag, dir, threshold }
}

fn hough(g: &Gradients) -> Vec<HLine> {
    const THETAS: usize = 180;
    let diag = ((g.w * g.w + g.h * g.h) as f32).sqrt();
    let rhos = (2.0 * diag) as usize + 1;
    let mut acc = vec![0f32; THETAS * rhos];
    let (sin, cos): (Vec<f32>, Vec<f32>) = (0..THETAS)
        .map(|t| (t as f32).to_radians().sin_cos())
        .unzip();
    for y in 0..g.h {
        for x in 0..g.w {
            let m = g.mag[y * g.w + x];
            if m < g.threshold {
                continue;
            }
            // The line's normal is the gradient direction (mod 180°).
            let t0 = g.dir[y * g.w + x].to_degrees().rem_euclid(180.0).round() as isize;
            for dt in -6..=6 {
                let t = (t0 + dt).rem_euclid(THETAS as isize) as usize;
                let rho = x as f32 * cos[t] + y as f32 * sin[t];
                let r = (rho + diag) as usize;
                acc[t * rhos + r] += 1.0;
            }
        }
    }
    // Peaks with non-maximum suppression over ±4° and ±12 px, so a barcode's
    // bars or a line of text yield one line, not a crowd of them.
    let mut peaks = Vec::new();
    let min_votes = (g.w.min(g.h) as f32) * 0.2;
    for t in 0..THETAS {
        for r in 0..rhos {
            let v = acc[t * rhos + r];
            if v < min_votes {
                continue;
            }
            let mut is_max = true;
            'n: for dt in -4isize..=4 {
                let tt = (t as isize + dt).rem_euclid(THETAS as isize) as usize;
                for dr in -12isize..=12 {
                    let rr = r as isize + dr;
                    if rr < 0 || rr >= rhos as isize || (dt == 0 && dr == 0) {
                        continue;
                    }
                    let o = acc[tt * rhos + rr as usize];
                    if o > v || (o == v && (dt, dr) < (0, 0)) {
                        is_max = false;
                        break 'n;
                    }
                }
            }
            if is_max {
                peaks.push(HLine { theta: (t as f32).to_radians(), rho: r as f32 - diag, votes: v });
            }
        }
    }
    peaks.sort_by(|a, b| b.votes.total_cmp(&a.votes));
    peaks.truncate(40);
    peaks
}

fn intersect(a: HLine, b: HLine) -> Option<[f32; 2]> {
    let (sa, ca) = a.theta.sin_cos();
    let (sb, cb) = b.theta.sin_cos();
    let det = ca * sb - sa * cb;
    if det.abs() < 1e-3 {
        return None;
    }
    Some([(a.rho * sb - b.rho * sa) / det, (ca * b.rho - cb * a.rho) / det])
}

/// Fraction of points along a segment that sit on a strong edge whose
/// gradient is perpendicular to the segment.
fn side_support(g: &Gradients, a: [f32; 2], b: [f32; 2]) -> f32 {
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let len = (dx * dx + dy * dy).sqrt();
    if len < 1.0 {
        return 0.0;
    }
    let normal = dy.atan2(dx) + std::f32::consts::FRAC_PI_2;
    let samples = 48;
    let mut hit = 0;
    let mut inside = 0;
    for i in 0..samples {
        let t = (i as f32 + 0.5) / samples as f32;
        let (px, py) = (a[0] + dx * t, a[1] + dy * t);
        if px < 1.0 || py < 1.0 || px >= (g.w - 1) as f32 || py >= (g.h - 1) as f32 {
            continue;
        }
        inside += 1;
        // Allow the edge to be a pixel or two off the fitted line.
        let (nx, ny) = (normal.cos(), normal.sin());
        let found = (-2..=2).any(|k| {
            let (qx, qy) = ((px + nx * k as f32) as usize, (py + ny * k as f32) as usize);
            if qx >= g.w || qy >= g.h {
                return false;
            }
            let i = qy * g.w + qx;
            let diff = (g.dir[i] - normal).rem_euclid(std::f32::consts::PI);
            let aligned = diff < 0.35 || diff > std::f32::consts::PI - 0.35;
            g.mag[i] >= g.threshold * 0.6 && aligned
        });
        if found {
            hit += 1;
        }
    }
    // Sides mostly outside the frame cannot be confirmed.
    if inside < samples / 2 {
        return 0.0;
    }
    hit as f32 / samples as f32
}

fn area(c: &[[f32; 2]; 4]) -> f32 {
    let mut s = 0.0;
    for i in 0..4 {
        let (a, b) = (c[i], c[(i + 1) % 4]);
        s += a[0] * b[1] - b[0] * a[1];
    }
    s.abs() / 2.0
}

fn is_convex(c: &[[f32; 2]; 4]) -> bool {
    let mut sign = 0.0f32;
    for i in 0..4 {
        let (a, b, d) = (c[i], c[(i + 1) % 4], c[(i + 2) % 4]);
        let cross = (b[0] - a[0]) * (d[1] - b[1]) - (b[1] - a[1]) * (d[0] - b[0]);
        if sign == 0.0 {
            sign = cross.signum();
        } else if cross.signum() != sign {
            return false;
        }
    }
    true
}

/// The R, G and B planes of an RGBA image, box-downscaled by `factor`.
fn colour_planes(rgba: &[u8], w: usize, h: usize, factor: usize) -> (Vec<Vec<u8>>, usize, usize) {
    let mut planes = Vec::new();
    let (mut sw, mut sh) = (w, h);
    for c in 0..3 {
        let plane: Vec<u8> = rgba.chunks_exact(4).map(|p| p[c]).collect();
        let (small, nw, nh) = crate::quality::downscale(&plane, w, h, factor);
        (sw, sh) = (nw, nh);
        planes.push(small);
    }
    (planes, sw, sh)
}

/// Finds the document's outline in an RGBA frame. `None` when no
/// convincing quadrilateral covers a reasonable share of the frame.
pub fn find_document(rgba: &[u8], w: usize, h: usize) -> Option<Quad> {
    let factor = (w / WORK_WIDTH).max(1);
    let (planes, sw, sh) = colour_planes(rgba, w, h, factor);
    if sw < 32 || sh < 32 {
        return None;
    }
    let g = gradients(&planes, sw, sh);
    let lines = hough(&g);
    // Roughly horizontal lines have a normal near 90°; roughly vertical near 0°/180°.
    let horizontal: Vec<HLine> = lines
        .iter()
        .copied()
        .filter(|l| (l.theta.to_degrees() - 90.0).abs() <= 35.0)
        .take(14)
        .collect();
    let vertical: Vec<HLine> = lines
        .iter()
        .copied()
        .filter(|l| {
            let d = l.theta.to_degrees();
            d <= 35.0 || d >= 145.0
        })
        .take(14)
        .collect();

    let frame = (sw * sh) as f32;
    let mut best: Option<(f32, Quad)> = None;
    for (i, &h1) in horizontal.iter().enumerate() {
        for &h2 in &horizontal[i + 1..] {
            for (j, &v1) in vertical.iter().enumerate() {
                for &v2 in &vertical[j + 1..] {
                    let (Some(p1), Some(p2), Some(p3), Some(p4)) =
                        (intersect(h1, v1), intersect(h1, v2), intersect(h2, v2), intersect(h2, v1))
                    else {
                        continue;
                    };
                    let mut pts = [p1, p2, p3, p4];
                    // Corners may lie a little outside the frame, not far.
                    if pts.iter().any(|p| {
                        p[0] < -0.08 * sw as f32
                            || p[1] < -0.08 * sh as f32
                            || p[0] > 1.08 * sw as f32
                            || p[1] > 1.08 * sh as f32
                    }) {
                        continue;
                    }
                    order(&mut pts);
                    if !is_convex(&pts) {
                        continue;
                    }
                    let a = area(&pts) / frame;
                    if !(0.25..=1.1).contains(&a) {
                        continue;
                    }
                    let sides: Vec<f32> = (0..4).map(|k| side_support(&g, pts[k], pts[(k + 1) % 4])).collect();
                    let weakest = sides.iter().copied().fold(f32::MAX, f32::min);
                    let mean = sides.iter().sum::<f32>() / 4.0;
                    if weakest < 0.35 || mean < 0.55 {
                        continue;
                    }
                    // Among well-supported outlines the largest wins: inner
                    // rectangles (the photo, a barcode panel, the MRZ band)
                    // also have strong straight edges, but lie inside.
                    let score = 0.6 * mean + 0.2 * weakest + 0.8 * a;
                    if best.as_ref().is_none_or(|(s, _)| score > *s) {
                        let scale = factor as f32;
                        let corners = pts.map(|p| [p[0] * scale + scale / 2.0, p[1] * scale + scale / 2.0]);
                        best = Some((score, Quad { corners, support: mean }));
                    }
                }
            }
        }
    }
    best.map(|(_, q)| q)
}

/// Orders four points as top-left, top-right, bottom-right, bottom-left.
fn order(p: &mut [[f32; 2]; 4]) {
    let cx = p.iter().map(|q| q[0]).sum::<f32>() / 4.0;
    let cy = p.iter().map(|q| q[1]).sum::<f32>() / 4.0;
    p.sort_by(|a, b| (a[1] - cy).atan2(a[0] - cx).total_cmp(&(b[1] - cy).atan2(b[0] - cx)));
    // Sorted by angle from -π: top-left comes first for a level quad.
    let tl = (0..4).min_by(|&a, &b| (p[a][0] + p[a][1]).total_cmp(&(p[b][0] + p[b][1]))).unwrap();
    p.rotate_left(tl);
}

/// The homography mapping the unit rectangle `(0,0)-(ow,oh)` onto `quad`.
fn homography(quad: &[[f32; 2]; 4], ow: f32, oh: f32) -> Option<[f64; 9]> {
    let src = [[0.0, 0.0], [ow as f64, 0.0], [ow as f64, oh as f64], [0.0, oh as f64]];
    let mut a = [[0f64; 9]; 8];
    for i in 0..4 {
        let (x, y) = (src[i][0], src[i][1]);
        let (u, v) = (quad[i][0] as f64, quad[i][1] as f64);
        a[2 * i] = [x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u];
        a[2 * i + 1] = [0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v];
    }
    // Gaussian elimination with partial pivoting on the 8×8 system.
    for col in 0..8 {
        let pivot = (col..8).max_by(|&r1, &r2| a[r1][col].abs().total_cmp(&a[r2][col].abs()))?;
        if a[pivot][col].abs() < 1e-12 {
            return None;
        }
        a.swap(col, pivot);
        for row in 0..8 {
            if row != col {
                let f = a[row][col] / a[col][col];
                for k in col..9 {
                    a[row][k] -= f * a[col][k];
                }
            }
        }
    }
    let h: Vec<f64> = (0..8).map(|i| a[i][8] / a[i][i]).collect();
    Some([h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1.0])
}

/// Samples `quad` from a `channels`-per-pixel image into an `ow × oh`
/// rectangle (bilinear). Works for greyscale (1) and RGBA (4).
pub fn warp(src: &[u8], w: usize, h: usize, channels: usize, quad: &[[f32; 2]; 4], ow: usize, oh: usize) -> Option<Vec<u8>> {
    let m = homography(quad, ow as f32, oh as f32)?;
    let mut out = vec![255u8; ow * oh * channels];
    for y in 0..oh {
        for x in 0..ow {
            let (xf, yf) = (x as f64 + 0.5, y as f64 + 0.5);
            let d = m[6] * xf + m[7] * yf + m[8];
            let sx = ((m[0] * xf + m[1] * yf + m[2]) / d) as f32 - 0.5;
            let sy = ((m[3] * xf + m[4] * yf + m[5]) / d) as f32 - 0.5;
            if sx < 0.0 || sy < 0.0 || sx >= (w - 1) as f32 || sy >= (h - 1) as f32 {
                continue;
            }
            let (x0, y0) = (sx as usize, sy as usize);
            let (fx, fy) = (sx - x0 as f32, sy - y0 as f32);
            for c in 0..channels {
                let at = |xx: usize, yy: usize| src[(yy * w + xx) * channels + c] as f32;
                let v = at(x0, y0) * (1.0 - fx) * (1.0 - fy)
                    + at(x0 + 1, y0) * fx * (1.0 - fy)
                    + at(x0, y0 + 1) * (1.0 - fx) * fy
                    + at(x0 + 1, y0 + 1) * fx * fy;
                out[(y * ow + x) * channels + c] = v as u8;
            }
        }
    }
    Some(out)
}

fn dist(a: [f32; 2], b: [f32; 2]) -> f32 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2)).sqrt()
}

/// Output size for a flattened quad: the measured aspect ratio, `max_width`
/// wide at most, and no wider than the quad itself (no pointless upscaling).
pub fn output_size(quad: &Quad, max_width: usize) -> (usize, usize) {
    let c = quad.corners;
    let width = (dist(c[0], c[1]) + dist(c[3], c[2])) / 2.0;
    let height = (dist(c[0], c[3]) + dist(c[1], c[2])) / 2.0;
    let ow = (width.round() as usize).clamp(64, max_width);
    let oh = ((ow as f32) * height / width.max(1.0)).round() as usize;
    (ow, oh.max(32))
}

/// The candidate lines (`[theta_radians, rho, votes]`) in working-image
/// coordinates, and the working scale factor. For debugging only.
pub fn debug_lines(rgba: &[u8], w: usize, h: usize) -> (usize, Vec<[f32; 3]>) {
    let factor = (w / WORK_WIDTH).max(1);
    let (planes, sw, sh) = colour_planes(rgba, w, h, factor);
    let g = gradients(&planes, sw, sh);
    (factor, hough(&g).into_iter().map(|l| [l.theta, l.rho, l.votes]).collect())
}
