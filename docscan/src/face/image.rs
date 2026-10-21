//! Pixel helpers for the face models: affine resampling of an RGBA frame into
//! a model's input tensor (bilinear, supersampled when shrinking), and luma.

/// An RGBA frame, row-major, 4 bytes a pixel.
#[derive(Clone, Copy)]
pub struct Frame<'a> {
    pub rgba: &'a [u8],
    pub width: usize,
    pub height: usize,
}

impl<'a> Frame<'a> {
    pub fn new(rgba: &'a [u8], width: usize, height: usize) -> anyhow::Result<Frame<'a>> {
        anyhow::ensure!(width > 0 && height > 0, "empty frame");
        anyhow::ensure!(rgba.len() >= width * height * 4, "frame is {} bytes, want {}", rgba.len(), width * height * 4);
        Ok(Frame { rgba, width, height })
    }

    /// Bilinear RGB at a sub-pixel position, the edge pixels repeated outside.
    #[inline]
    pub fn sample(&self, x: f32, y: f32) -> [f32; 3] {
        let x = x.clamp(0.0, (self.width - 1) as f32);
        let y = y.clamp(0.0, (self.height - 1) as f32);
        let x0 = x.floor() as usize;
        let y0 = y.floor() as usize;
        let x1 = (x0 + 1).min(self.width - 1);
        let y1 = (y0 + 1).min(self.height - 1);
        let fx = x - x0 as f32;
        let fy = y - y0 as f32;
        let px = |xx: usize, yy: usize| {
            let i = (yy * self.width + xx) * 4;
            [self.rgba[i] as f32, self.rgba[i + 1] as f32, self.rgba[i + 2] as f32]
        };
        let (a, b, c, d) = (px(x0, y0), px(x1, y0), px(x0, y1), px(x1, y1));
        let mut out = [0f32; 3];
        for k in 0..3 {
            let top = a[k] + (b[k] - a[k]) * fx;
            let bottom = c[k] + (d[k] - c[k]) * fx;
            out[k] = top + (bottom - top) * fy;
        }
        out
    }

    pub fn luma_at(&self, x: usize, y: usize) -> f32 {
        let i = (y * self.width + x) * 4;
        0.299 * self.rgba[i] as f32 + 0.587 * self.rgba[i + 1] as f32 + 0.114 * self.rgba[i + 2] as f32
    }
}

/// A 2 × 3 affine map from output pixel centres to source positions:
/// `src = [a b c; d e f] · [u v 1]`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Affine(pub [f32; 6]);

impl Affine {
    pub fn apply(&self, u: f32, v: f32) -> (f32, f32) {
        let m = &self.0;
        (m[0] * u + m[1] * v + m[2], m[3] * u + m[4] * v + m[5])
    }

    /// The inverse map (source to output).
    pub fn inverse(&self) -> Affine {
        let [a, b, c, d, e, f] = self.0;
        let det = a * e - b * d;
        let det = if det.abs() < 1e-12 { 1e-12 } else { det };
        let ia = e / det;
        let ib = -b / det;
        let id = -d / det;
        let ie = a / det;
        Affine([ia, ib, -(ia * c + ib * f), id, ie, -(id * c + ie * f)])
    }

    /// Source pixels per output pixel (the larger singular value, roughly).
    pub fn scale(&self) -> f32 {
        let [a, b, _, d, e, _] = self.0;
        (a * a + d * d).sqrt().max((b * b + e * e).sqrt())
    }

    /// A rotated square: output `size × size` pixels covering a square of
    /// side `side` source pixels centred on `(cx, cy)`, rotated by `angle`
    /// radians (the output's x axis along `(cos, sin)` in the source).
    pub fn square(cx: f32, cy: f32, side: f32, angle: f32, size: usize) -> Affine {
        let k = side / size as f32;
        let (s, c) = angle.sin_cos();
        // Output pixel centre (u + 0.5) maps to the offset from the centre.
        let half = size as f32 / 2.0;
        let a = c * k;
        let b = -s * k;
        let d = s * k;
        let e = c * k;
        // src = centre + R·k·((u + 0.5) - half, (v + 0.5) - half)
        let off = 0.5 - half;
        Affine([a, b, cx + a * off + b * off, d, e, cy + d * off + e * off])
    }
}

/// Resamples `frame` through `map` into `size_w × size_h` RGB floats,
/// interleaved (HWC), as `value * scale + offset`. Shrinking by more than
/// 1.5× averages a grid of samples per output pixel, so fine detail is
/// filtered rather than aliased.
pub fn warp_hwc(frame: &Frame, map: &Affine, size_w: usize, size_h: usize, scale: f32, offset: f32) -> Vec<f32> {
    let n = (map.scale().ceil() as usize).clamp(1, 4);
    let n = if map.scale() < 1.5 { 1 } else { n };
    let mut out = vec![0f32; size_w * size_h * 3];
    let inv = 1.0 / (n * n) as f32;
    for v in 0..size_h {
        for u in 0..size_w {
            let mut acc = [0f32; 3];
            for sy in 0..n {
                for sx in 0..n {
                    let du = (sx as f32 + 0.5) / n as f32 - 0.5;
                    let dv = (sy as f32 + 0.5) / n as f32 - 0.5;
                    let (x, y) = map.apply(u as f32 + du, v as f32 + dv);
                    let p = frame.sample(x, y);
                    acc[0] += p[0];
                    acc[1] += p[1];
                    acc[2] += p[2];
                }
            }
            let i = (v * size_w + u) * 3;
            for k in 0..3 {
                out[i + k] = acc[k] * inv * scale + offset;
            }
        }
    }
    out
}

/// HWC to CHW, optionally swapping R and B.
pub fn hwc_to_chw(hwc: &[f32], w: usize, h: usize, bgr: bool) -> Vec<f32> {
    let mut out = vec![0f32; w * h * 3];
    for i in 0..w * h {
        for k in 0..3 {
            let src = if bgr { 2 - k } else { k };
            out[k * w * h + i] = hwc[i * 3 + src];
        }
    }
    out
}

/// The warped crop as RGBA bytes, for images handed back to the page.
pub fn warp_rgba(frame: &Frame, map: &Affine, w: usize, h: usize) -> Vec<u8> {
    let hwc = warp_hwc(frame, map, w, h, 1.0, 0.0);
    let mut out = Vec::with_capacity(w * h * 4);
    for p in hwc.chunks_exact(3) {
        out.extend_from_slice(&[p[0].round().clamp(0.0, 255.0) as u8, p[1].round().clamp(0.0, 255.0) as u8, p[2].round().clamp(0.0, 255.0) as u8, 255]);
    }
    out
}

/// Luma of an HWC float crop (0–255 values).
pub fn luma_hwc(hwc: &[f32]) -> Vec<f32> {
    hwc.chunks_exact(3).map(|p| 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]).collect()
}

/// Variance of the 4-neighbour Laplacian: a sharpness measure.
pub fn laplacian_variance(luma: &[f32], w: usize, h: usize) -> f32 {
    if w < 3 || h < 3 {
        return 0.0;
    }
    let mut sum = 0f64;
    let mut sum2 = 0f64;
    let mut n = 0f64;
    for y in 1..h - 1 {
        for x in 1..w - 1 {
            let c = luma[y * w + x];
            let l = luma[y * w + x - 1] + luma[y * w + x + 1] + luma[(y - 1) * w + x] + luma[(y + 1) * w + x] - 4.0 * c;
            sum += l as f64;
            sum2 += (l * l) as f64;
            n += 1.0;
        }
    }
    let mean = sum / n;
    (sum2 / n - mean * mean) as f32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn square_maps_centre_and_inverts() {
        let m = Affine::square(100.0, 50.0, 64.0, 0.3, 32);
        let (x, y) = m.apply(16.0 - 0.5, 16.0 - 0.5);
        assert!((x - 100.0).abs() < 1e-3 && (y - 50.0).abs() < 1e-3, "{x} {y}");
        let inv = m.inverse();
        let (u, v) = inv.apply(x, y);
        assert!((u - 15.5).abs() < 1e-3 && (v - 15.5).abs() < 1e-3);
        assert!((m.scale() - 2.0).abs() < 1e-4);
    }
}
