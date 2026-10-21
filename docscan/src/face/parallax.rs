//! 3-D motion from the pixels, not from the landmark model's opinion.
//!
//! The landmark model has a strong prior of a face: shown a flat photo tilted
//! steeply, it still places the nose and cheeks where a *turned head* would
//! have them, so its landmarks stray from the photo's true homography almost
//! as much as a real head's do. Measured on synthetic clips, that alone
//! separated a tilted print from a turning head poorly (`face/RESULTS.md`).
//!
//! Here each rigid point is re-found in the turned frame by its texture:
//! a patch of the reference (frontal) frame, warped by the local affine of
//! the homography the landmarks suggest, is matched by normalised cross-
//! correlation in a window around the predicted position. On a flat
//! surface the matches land exactly on one homography; on a head, points at
//! different depths (the nose against the cheeks) land off it by the
//! parallax. The residual of a homography fitted to the matched points, as a
//! share of the interocular distance, is the measure.

use serde::Serialize;

use super::image::Frame;
use super::linalg::{apply_homography, fit_homography};

/// A grey image at analysis scale.
#[derive(Clone)]
pub struct Grey {
    pub w: usize,
    pub h: usize,
    pub data: Vec<f32>,
}

impl Grey {
    /// The frame's luma scaled by `scale` (≤ 1: box-averaged).
    pub fn from_frame(frame: &Frame, scale: f32) -> Grey {
        let w = ((frame.width as f32 * scale).round() as usize).max(1);
        let h = ((frame.height as f32 * scale).round() as usize).max(1);
        let inv = 1.0 / scale;
        let n = (inv.ceil() as usize).clamp(1, 6);
        let mut data = vec![0f32; w * h];
        for y in 0..h {
            for x in 0..w {
                let mut acc = 0f32;
                for sy in 0..n {
                    for sx in 0..n {
                        let fx = ((x as f32 + (sx as f32 + 0.5) / n as f32) * inv) as usize;
                        let fy = ((y as f32 + (sy as f32 + 0.5) / n as f32) * inv) as usize;
                        acc += frame.luma_at(fx.min(frame.width - 1), fy.min(frame.height - 1));
                    }
                }
                data[y * w + x] = acc / (n * n) as f32;
            }
        }
        Grey { w, h, data }
    }

    #[inline]
    fn at(&self, x: f32, y: f32) -> f32 {
        let x = x.clamp(0.0, (self.w - 1) as f32);
        let y = y.clamp(0.0, (self.h - 1) as f32);
        let x0 = x.floor() as usize;
        let y0 = y.floor() as usize;
        let x1 = (x0 + 1).min(self.w - 1);
        let y1 = (y0 + 1).min(self.h - 1);
        let fx = x - x0 as f32;
        let fy = y - y0 as f32;
        let a = self.data[y0 * self.w + x0];
        let b = self.data[y0 * self.w + x1];
        let c = self.data[y1 * self.w + x0];
        let d = self.data[y1 * self.w + x1];
        let top = a + (b - a) * fx;
        top + (c + (d - c) * fx - top) * fy
    }
}

/// Patch half-size (pixels at analysis scale) and the interocular distance
/// the analysis scale normalises to.
const HALF: i32 = 5;
const TARGET_IOD: f32 = 48.0;
/// The search window, as a share of the interocular distance.
const SEARCH: f32 = 0.16;
const MIN_NCC: f32 = 0.6;
const MIN_TEXTURE: f32 = 6.0;

/// The frontal reference: its grey image, the analysis scale, and the
/// points (frame pixels) with enough texture to match.
pub struct Reference {
    scale: f32,
    /// Reference positions (analysis pixels) and their index in the point list.
    points: Vec<(usize, [f32; 2])>,
    patches: Vec<Vec<f32>>,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct Parallax {
    /// RMS residual of the best homography, as a share of the interocular
    /// distance (the 80% best-fitting matches, to ignore stray locks).
    pub residual: f32,
    /// The share of matches no single homography explains (RANSAC at 2.5%
    /// of the interocular distance): near 0 for a flat surface.
    pub outliers: f32,
    pub matched: usize,
    pub ncc: f32,
}

fn patch(g: &Grey, c: [f32; 2], jac: [f32; 4]) -> Vec<f32> {
    let mut out = Vec::with_capacity(((2 * HALF + 1) * (2 * HALF + 1)) as usize);
    for dy in -HALF..=HALF {
        for dx in -HALF..=HALF {
            let (dx, dy) = (dx as f32, dy as f32);
            out.push(g.at(c[0] + jac[0] * dx + jac[1] * dy, c[1] + jac[2] * dx + jac[3] * dy));
        }
    }
    out
}

fn normalise(p: &mut [f32]) -> f32 {
    let n = p.len() as f32;
    let mean = p.iter().sum::<f32>() / n;
    let var = p.iter().map(|v| (v - mean).powi(2)).sum::<f32>() / n;
    let sd = var.sqrt();
    for v in p.iter_mut() {
        *v = (*v - mean) / sd.max(1e-3);
    }
    sd
}

impl Reference {
    /// `points`: the rigid landmarks (frame pixels); `iod`: interocular distance (frame pixels).
    pub fn new(frame: &Frame, points: &[[f32; 2]], iod: f32) -> Reference {
        let scale = (TARGET_IOD / iod.max(1.0)).min(1.0);
        let grey = Grey::from_frame(frame, scale);
        let mut pts = Vec::new();
        let mut patches = Vec::new();
        for (i, p) in points.iter().enumerate() {
            let c = [p[0] * scale, p[1] * scale];
            let mut pa = patch(&grey, c, [1.0, 0.0, 0.0, 1.0]);
            if normalise(&mut pa) >= MIN_TEXTURE {
                pts.push((i, c));
                patches.push(pa);
            }
        }
        Reference { scale, points: pts, patches }
    }

    pub fn usable(&self) -> usize {
        self.points.len()
    }

    /// Matches every reference point around where `h` predicts it, within
    /// `radius` analysis pixels: (reference, match, NCC).
    fn search(&self, grey: &Grey, h: &[f64; 9], radius: i32) -> Vec<([f64; 2], [f64; 2], f32)> {
        let mut matched = Vec::new();
        for ((_, p), refp) in self.points.iter().zip(&self.patches) {
            let p64 = [p[0] as f64, p[1] as f64];
            let q0 = apply_homography(h, p64);
            let qx = apply_homography(h, [p64[0] + 1.0, p64[1]]);
            let qy = apply_homography(h, [p64[0], p64[1] + 1.0]);
            let jac = [(qx[0] - q0[0]) as f32, (qy[0] - q0[0]) as f32, (qx[1] - q0[1]) as f32, (qy[1] - q0[1]) as f32];
            let side = (2 * radius + 1) as usize;
            let mut scores = vec![f32::MIN; side * side];
            let mut best = (f32::MIN, 0i32, 0i32);
            for oy in -radius..=radius {
                for ox in -radius..=radius {
                    let c = [q0[0] as f32 + ox as f32, q0[1] as f32 + oy as f32];
                    let mut cur = patch(grey, c, jac);
                    if normalise(&mut cur) < 1.0 {
                        continue;
                    }
                    let ncc = cur.iter().zip(refp).map(|(a, b)| a * b).sum::<f32>() / cur.len() as f32;
                    scores[((oy + radius) as usize) * side + (ox + radius) as usize] = ncc;
                    if ncc > best.0 {
                        best = (ncc, ox, oy);
                    }
                }
            }
            if best.0 < MIN_NCC {
                continue;
            }
            let at = |ox: i32, oy: i32| -> Option<f32> {
                if ox.abs() > radius || oy.abs() > radius {
                    return None;
                }
                let v = scores[((oy + radius) as usize) * side + (ox + radius) as usize];
                (v > f32::MIN).then_some(v)
            };
            let sub = |m: Option<f32>, c: f32, p: Option<f32>| match (m, p) {
                (Some(m), Some(p)) => {
                    let d = m - 2.0 * c + p;
                    if d.abs() > 1e-6 { (0.5 * (m - p) / d).clamp(-0.5, 0.5) } else { 0.0 }
                }
                _ => 0.0,
            };
            let (c, bx, by) = best;
            let fx = sub(at(bx - 1, by), c, at(bx + 1, by));
            let fy = sub(at(bx, by - 1), c, at(bx, by + 1));
            matched.push((p64, [q0[0] + bx as f64 + fx as f64, q0[1] + by as f64 + fy as f64], c));
        }
        matched
    }

    /// Re-finds the reference points in `frame` by their texture, around
    /// where the landmarks (`model_ref` → `model_cur`, frame pixels) put
    /// them; then again around where the homography of those matches puts
    /// them (a flat surface converges on its homography; a head keeps its
    /// parallax); and measures how far the matches depart from one homography.
    pub fn measure(&self, frame: &Frame, model_ref: &[[f32; 2]], model_cur: &[[f32; 2]], iod_cur: f32) -> Option<Parallax> {
        let s = self.scale;
        let grey = Grey::from_frame(frame, s);
        let src: Vec<[f64; 2]> = model_ref.iter().map(|p| [(p[0] * s) as f64, (p[1] * s) as f64]).collect();
        let dst: Vec<[f64; 2]> = model_cur.iter().map(|p| [(p[0] * s) as f64, (p[1] * s) as f64]).collect();
        let h0 = fit_homography(&src, &dst)?;
        let iod = (iod_cur * s).max(4.0) as f64;
        let first = self.search(&grey, &h0, (SEARCH as f64 * iod).ceil() as i32);
        if first.len() < 8 {
            return None;
        }
        let (h1, _) = ransac(&first, 0.03 * iod)?;
        let matched = self.search(&grey, &h1, (0.12 * iod).ceil() as i32);
        if matched.len() < 8 {
            return None;
        }
        let (_, inliers) = ransac(&matched, 0.025 * iod)?;
        let src: Vec<[f64; 2]> = matched.iter().map(|m| m.0).collect();
        let dst: Vec<[f64; 2]> = matched.iter().map(|m| m.1).collect();
        let h = fit_homography(&src, &dst)?;
        let mut res: Vec<f64> = src
            .iter()
            .zip(&dst)
            .map(|(a, b)| {
                let p = apply_homography(&h, *a);
                ((p[0] - b[0]).powi(2) + (p[1] - b[1]).powi(2)).sqrt()
            })
            .collect();
        res.sort_by(f64::total_cmp);
        let keep = &res[..((res.len() as f32 * 0.8).ceil() as usize).max(1)];
        let rms = (keep.iter().map(|r| r * r).sum::<f64>() / keep.len() as f64).sqrt();
        let ncc = matched.iter().map(|m| m.2).sum::<f32>() / matched.len() as f32;
        Some(Parallax { residual: (rms / iod) as f32, outliers: 1.0 - inliers as f32 / matched.len() as f32, matched: matched.len(), ncc })
    }
}

/// The homography most matches agree with (within `tol` analysis pixels),
/// refitted to its inliers, and the inlier count. Deterministic samples.
fn ransac(m: &[([f64; 2], [f64; 2], f32)], tol: f64) -> Option<([f64; 9], usize)> {
    let n = m.len();
    let mut seed = 0x9E37_79B9_7F4A_7C15u64;
    let mut next = move || {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        (seed % n as u64) as usize
    };
    let count = |h: &[f64; 9]| m.iter().filter(|(a, b, _)| {
        let p = apply_homography(h, *a);
        ((p[0] - b[0]).powi(2) + (p[1] - b[1]).powi(2)).sqrt() <= tol
    }).count();
    let mut best: Option<([f64; 9], usize)> = None;
    for _ in 0..200 {
        let idx = [next(), next(), next(), next()];
        if idx.iter().enumerate().any(|(i, a)| idx[..i].contains(a)) {
            continue;
        }
        let src: Vec<[f64; 2]> = idx.iter().map(|&i| m[i].0).collect();
        let dst: Vec<[f64; 2]> = idx.iter().map(|&i| m[i].1).collect();
        let Some(h) = fit_homography(&src, &dst) else { continue };
        let c = count(&h);
        if best.as_ref().is_none_or(|b| c > b.1) {
            best = Some((h, c));
        }
    }
    let (h, _) = best?;
    let inl: Vec<&([f64; 2], [f64; 2], f32)> = m.iter().filter(|(a, b, _)| {
        let p = apply_homography(&h, *a);
        ((p[0] - b[0]).powi(2) + (p[1] - b[1]).powi(2)).sqrt() <= tol
    }).collect();
    if inl.len() < 4 {
        return Some((h, inl.len()));
    }
    let src: Vec<[f64; 2]> = inl.iter().map(|x| x.0).collect();
    let dst: Vec<[f64; 2]> = inl.iter().map(|x| x.1).collect();
    let h2 = fit_homography(&src, &dst).unwrap_or(h);
    let c = count(&h2);
    Some((h2, c))
}
