//! Cheap per-frame image quality: sharpness, glare and exposure, computed on
//! a downscaled greyscale copy so it can run on every video frame.

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Quality {
    /// Variance of the Laplacian on a ~400 px wide copy. Higher is sharper.
    pub sharpness: f32,
    /// Fraction of the image under washed-out patches: 12 × 12 blocks (on
    /// the ~400 px copy) that are almost all blown out (≥ 250). Counting
    /// single pixels flagged white paper — a passport's MRZ band is pure
    /// white — while a highlight, which erases the print under it, leaves
    /// whole blocks blank; text breaks up the paper's.
    pub glare: f32,
    /// Mean brightness, 0–255.
    pub brightness: f32,
    /// Fraction of pixels on a strong edge: near zero means nothing is in view.
    pub edge_density: f32,
}

pub fn rgba_to_luma(rgba: &[u8]) -> Vec<u8> {
    rgba.chunks_exact(4)
        .map(|p| ((p[0] as u32 * 77 + p[1] as u32 * 150 + p[2] as u32 * 29) >> 8) as u8)
        .collect()
}

/// The brightest channel of each pixel: dark only where the print is dark in
/// every channel. Black ink stays black, while coloured security printing
/// (a red SPECIMEN overprint, green guilloche lines) fades towards the paper,
/// so it no longer merges with the text it crosses.
pub fn rgba_to_ink(rgba: &[u8]) -> Vec<u8> {
    rgba.chunks_exact(4).map(|p| p[0].max(p[1]).max(p[2])).collect()
}

/// Box-filter downscale by an integer factor.
pub fn downscale(luma: &[u8], w: usize, h: usize, factor: usize) -> (Vec<u8>, usize, usize) {
    if factor <= 1 {
        return (luma.to_vec(), w, h);
    }
    let (nw, nh) = (w / factor, h / factor);
    let mut out = vec![0u8; nw * nh];
    let area = (factor * factor) as u32;
    for y in 0..nh {
        for x in 0..nw {
            let mut sum = 0u32;
            for dy in 0..factor {
                let row = (y * factor + dy) * w + x * factor;
                for dx in 0..factor {
                    sum += luma[row + dx] as u32;
                }
            }
            out[y * nw + x] = (sum / area) as u8;
        }
    }
    (out, nw, nh)
}

pub fn measure(luma: &[u8], w: usize, h: usize) -> Quality {
    let factor = (w / 400).max(1);
    let (img, w, h) = downscale(luma, w, h, factor);
    let n = (w * h).max(1) as f32;
    let brightness = img.iter().map(|&v| v as f32).sum::<f32>() / n;
    let glare = washed_out(&img, w, h);

    let (mut sum, mut sum_sq, mut count, mut edges) = (0f64, 0f64, 0f64, 0usize);
    for y in 1..h.saturating_sub(1) {
        for x in 1..w.saturating_sub(1) {
            let c = img[y * w + x] as i32;
            let lap = img[(y - 1) * w + x] as i32
                + img[(y + 1) * w + x] as i32
                + img[y * w + x - 1] as i32
                + img[y * w + x + 1] as i32
                - 4 * c;
            let lap = lap as f64;
            sum += lap;
            sum_sq += lap * lap;
            count += 1.0;
            if lap.abs() > 40.0 {
                edges += 1;
            }
        }
    }
    let mean = if count > 0.0 { sum / count } else { 0.0 };
    let variance = if count > 0.0 { sum_sq / count - mean * mean } else { 0.0 };
    Quality {
        sharpness: variance as f32,
        glare,
        brightness,
        edge_density: edges as f32 / n,
    }
}

/// Fraction of 12 × 12 blocks with at least 95% of pixels at 250 or above.
fn washed_out(img: &[u8], w: usize, h: usize) -> f32 {
    const B: usize = 12;
    let (bw, bh) = (w / B, h / B);
    if bw == 0 || bh == 0 {
        return 0.0;
    }
    let mut blank = 0;
    for by in 0..bh {
        for bx in 0..bw {
            let mut sat = 0;
            for y in by * B..(by + 1) * B {
                sat += img[y * w + bx * B..y * w + (bx + 1) * B].iter().filter(|&&v| v >= 250).count();
            }
            if sat * 100 >= B * B * 95 {
                blank += 1;
            }
        }
    }
    blank as f32 / (bw * bh) as f32
}

#[cfg(test)]
mod tests {
    use super::*;

    /// White paper with print on it is not glare; a blank blown-out patch is.
    #[test]
    fn glare_is_washed_out_patches_not_white_paper() {
        let (w, h) = (240, 120);
        // White paper with a two-pixel line of "text" every 8 rows.
        let mut paper = vec![255u8; w * h];
        for y in (0..h).filter(|y| y % 8 < 2) {
            for x in (0..w).step_by(2) {
                paper[y * w + x] = 30;
            }
        }
        assert!(measure(&paper, w, h).glare < 0.01);
        // The same page with a highlight erasing the left half.
        for y in 0..h {
            for x in 0..w / 2 {
                paper[y * w + x] = 255;
            }
        }
        let g = measure(&paper, w, h).glare;
        assert!((0.4..=0.6).contains(&g), "{g}");
    }
}
