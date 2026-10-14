//! Skew estimation and rotation. A document held a few degrees off level
//! defeats rxing's PDF417 row scanner, so the reader estimates the skew from
//! the image's dominant edge direction and retries on a levelled copy.

/// The dominant edge orientation of the image, in degrees within (-45, 45]:
/// the angle to rotate by (counter-clockwise positive) to level it.
pub fn estimate_skew(luma: &[u8], w: usize, h: usize) -> f32 {
    let factor = (w / 480).max(1);
    let (img, w, h) = crate::quality::downscale(luma, w, h, factor);
    // Histogram of gradient angles folded into 90°, weighted by magnitude:
    // a document's edges, text lines and barcode bars all vote for its axes.
    const BINS: usize = 180;
    let mut hist = [0f32; BINS];
    for y in 1..h.saturating_sub(1) {
        for x in 1..w.saturating_sub(1) {
            let p = |dx: isize, dy: isize| img[(y as isize + dy) as usize * w + (x as isize + dx) as usize] as f32;
            let gx = p(1, -1) + 2.0 * p(1, 0) + p(1, 1) - p(-1, -1) - 2.0 * p(-1, 0) - p(-1, 1);
            let gy = p(-1, 1) + 2.0 * p(0, 1) + p(1, 1) - p(-1, -1) - 2.0 * p(0, -1) - p(1, -1);
            let mag = (gx * gx + gy * gy).sqrt();
            if mag < 60.0 {
                continue;
            }
            let deg = gy.atan2(gx).to_degrees().rem_euclid(90.0);
            hist[((deg / 90.0 * BINS as f32) as usize).min(BINS - 1)] += mag;
        }
    }
    // Smooth circularly and take the peak.
    let smooth: Vec<f32> = (0..BINS)
        .map(|i| (0..7).map(|k| hist[(i + BINS + k - 3) % BINS]).sum())
        .collect();
    let peak = (0..BINS).max_by(|&a, &b| smooth[a].total_cmp(&smooth[b])).unwrap_or(0);
    let deg = (peak as f32 + 0.5) * 90.0 / BINS as f32;
    // Gradients at `deg` mean the content is turned by `deg` (or by
    // `deg - 90` when that axis is nearer); level it by the opposite.
    if deg > 45.0 { deg - 90.0 } else { deg }
}

/// Rotates a greyscale image by a quarter turn: `quarters` × 90°, clockwise.
pub fn rotate_quarters(img: &[u8], w: usize, h: usize, quarters: u8) -> (Vec<u8>, usize, usize) {
    match quarters % 4 {
        0 => (img.to_vec(), w, h),
        2 => (img.iter().rev().copied().collect(), w, h),
        q => {
            let mut out = vec![0u8; w * h];
            for y in 0..h {
                for x in 0..w {
                    // Clockwise: (x, y) -> (h - 1 - y, x); anticlockwise: (y, w - 1 - x).
                    let (nx, ny) = if q == 1 { (h - 1 - y, x) } else { (y, w - 1 - x) };
                    out[ny * h + nx] = img[y * w + x];
                }
            }
            (out, h, w)
        }
    }
}

/// Where a point of [`rotate`]'s output came from in its `w × h` source.
pub fn rotated_to_source(p: [f32; 2], w: usize, h: usize, degrees: f32) -> [f32; 2] {
    let (s, c) = degrees.to_radians().sin_cos();
    let nw = (w as f32 * c.abs() + h as f32 * s.abs()).ceil();
    let nh = (w as f32 * s.abs() + h as f32 * c.abs()).ceil();
    let (dx, dy) = (p[0] - nw / 2.0, p[1] - nh / 2.0);
    [c * dx - s * dy + w as f32 / 2.0, s * dx + c * dy + h as f32 / 2.0]
}

/// Rotates a greyscale image by `degrees` (counter-clockwise positive) about
/// its centre, enlarging the canvas so nothing is cut off. Bilinear.
pub fn rotate(luma: &[u8], w: usize, h: usize, degrees: f32) -> (Vec<u8>, usize, usize) {
    let (s, c) = degrees.to_radians().sin_cos();
    let nw = (w as f32 * c.abs() + h as f32 * s.abs()).ceil() as usize;
    let nh = (w as f32 * s.abs() + h as f32 * c.abs()).ceil() as usize;
    let (cx, cy) = (w as f32 / 2.0, h as f32 / 2.0);
    let (ncx, ncy) = (nw as f32 / 2.0, nh as f32 / 2.0);
    let mut out = vec![255u8; nw * nh];
    for y in 0..nh {
        for x in 0..nw {
            let dx = x as f32 - ncx;
            let dy = y as f32 - ncy;
            // Inverse map: image y points down, so this is a CCW rotation on screen.
            let sx = c * dx - s * dy + cx;
            let sy = s * dx + c * dy + cy;
            if sx < 0.0 || sy < 0.0 || sx >= (w - 1) as f32 || sy >= (h - 1) as f32 {
                continue;
            }
            let (x0, y0) = (sx as usize, sy as usize);
            let (fx, fy) = (sx - x0 as f32, sy - y0 as f32);
            let i = y0 * w + x0;
            let v = luma[i] as f32 * (1.0 - fx) * (1.0 - fy)
                + luma[i + 1] as f32 * fx * (1.0 - fy)
                + luma[i + w] as f32 * (1.0 - fx) * fy
                + luma[i + w + 1] as f32 * fx * fy;
            out[y * nw + x] = v as u8;
        }
    }
    (out, nw, nh)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A white image with dark horizontal stripes, rotated by a known angle,
    /// must estimate back to roughly that angle.
    #[test]
    fn skew_round_trip() {
        let (w, h) = (400, 300);
        let mut img = vec![255u8; w * h];
        for y in 0..h {
            if (y / 10) % 2 == 0 {
                for x in 0..w {
                    img[y * w + x] = 20;
                }
            }
        }
        for angle in [-12.0f32, -5.0, 7.0, 20.0] {
            let (r, rw, rh) = rotate(&img, w, h, angle);
            let est = estimate_skew(&r, rw, rh);
            assert!((est + angle).abs() < 2.0, "rotated {angle}, estimated {est}");
        }
    }
}

#[cfg(test)]
mod quarter_tests {
    use super::rotate_quarters;

    #[test]
    fn quarter_turns_compose() {
        // 3 × 2 image, values 0..6.
        let img: Vec<u8> = (0..6).collect();
        let (cw, w, h) = rotate_quarters(&img, 3, 2, 1);
        assert_eq!((w, h), (2, 3));
        assert_eq!(cw, vec![3, 0, 4, 1, 5, 2]);
        let (back, _, _) = rotate_quarters(&cw, 2, 3, 3);
        assert_eq!(back, img);
    }
}
