//! The smart ID card's back: a second chance for its PDF417.
//!
//! The card is flattened at its size in the frame, which leaves the
//! PDF417's narrowest modules about a pixel and a half wide on a typical
//! frame; blur, a tilt or a small card then merge neighbouring modules and
//! rxing finds no rows. Resampling the card from the frame at twice that
//! size (bilinear) and sharpening it (an unsharp mask) restores a step
//! between modules that the binariser can use. Measured on the DEV frames,
//! this reads the barcode on most tilted, sideways, small and combined
//! (tilt, dim and blur) frames that failed, and still nothing on the bad
//! frames (motion blur, defocus, glare over the barcode, half out of view):
//! a PDF417 carries Reed-Solomon error correction, so a misread is rejected
//! by the decoder rather than returned.

use crate::{barcode, quad};

/// How much larger than the flattened card the rescue reads it, and the
/// longest side it may reach.
const SCALE: f32 = 2.0;
const MAX_SIDE: usize = 2600;
/// Below this length (pixels) the card's PDF417 modules are under a pixel
/// wide. The rescue sometimes still reads them (Reed-Solomon keeps such a
/// read right), but not reliably, and the page is designed to ask for the
/// card closer instead (README: the 960 x 540 clip, whose card is about 720
/// px long, must not capture).
const MIN_SIDE: usize = 760;

/// Whether a flattened outline could be a card: its measured proportions
/// (side lengths, which a strong tilt distorts) between 1.25 and 2.1 either
/// way up. ID-1 is 1.585; the rescue costs nothing in accuracy when wrong.
pub fn roughly_card_shaped(w: usize, h: usize) -> bool {
    let a = w.max(h) as f32 / w.min(h).max(1) as f32;
    (1.25..=2.1).contains(&a)
}

/// Whether a flattened card shows a barcode wide enough to be the back's
/// PDF417 or its Code 39: a patch of bars across a quarter of its length.
/// The front carries none, so it does not pay for the rescue.
pub fn has_wide_bars(flat: &[u8], w: usize, h: usize) -> bool {
    // Either way up: a card held sideways has its bars across its height.
    barcode::oriented_regions(flat, w, h).iter().any(|r| {
        let across = if r.ux.abs() > 0.9 { w } else if r.uy.abs() > 0.9 { h } else { return false };
        8.0 * r.half_across >= across as f32
    })
}

/// Reads the PDF417 from the card `quad` in the frame (`luma`, `w × h`),
/// resampled at twice the flattened size `ow × oh` and sharpened. Points are
/// returned in the flattened card's pixels.
pub fn rescue_pdf417(luma: &[u8], w: usize, h: usize, quad: &quad::Quad, ow: usize, oh: usize) -> Vec<barcode::Barcode> {
    let k = SCALE.min(MAX_SIDE as f32 / ow.max(oh) as f32);
    if k <= 1.05 || ow.max(oh) < MIN_SIDE {
        return Vec::new();
    }
    let (bw, bh) = ((ow as f32 * k).round() as usize, (oh as f32 * k).round() as usize);
    let Some(big) = quad::warp(luma, w, h, 1, &quad.corners, bw, bh) else { return Vec::new() };
    let sharp = unsharp(&big, bw, bh, 0.7 * k, 1.5);
    let only = ["pdf417".to_string()];
    let mut found = barcode::read_all(&sharp, bw as u32, bh as u32, Some(&only));
    for b in &mut found {
        for p in &mut b.points {
            *p = [p[0] / k, p[1] / k];
        }
    }
    found
}

/// `v + amount × (v − gaussian(v))`, separable.
pub fn unsharp(img: &[u8], w: usize, h: usize, sigma: f32, amount: f32) -> Vec<u8> {
    let r = (sigma * 3.0).ceil() as usize;
    let mut kernel: Vec<f32> = (0..=2 * r).map(|i| (-((i as f32 - r as f32).powi(2)) / (2.0 * sigma * sigma)).exp()).collect();
    let total: f32 = kernel.iter().sum();
    kernel.iter_mut().for_each(|v| *v /= total);
    let mut tmp = vec![0f32; w * h];
    for y in 0..h {
        let row = &img[y * w..(y + 1) * w];
        for x in 0..w {
            let mut acc = 0.0;
            for (i, kv) in kernel.iter().enumerate() {
                let sx = (x + i).saturating_sub(r).min(w - 1);
                acc += row[sx] as f32 * kv;
            }
            tmp[y * w + x] = acc;
        }
    }
    let mut out = vec![0u8; w * h];
    for y in 0..h {
        for x in 0..w {
            let mut acc = 0.0;
            for (i, kv) in kernel.iter().enumerate() {
                let sy = (y + i).saturating_sub(r).min(h - 1);
                acc += tmp[sy * w + x] * kv;
            }
            let v = img[y * w + x] as f32;
            out[y * w + x] = (v + amount * (v - acc)).clamp(0.0, 255.0) as u8;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsharp_keeps_flat_areas_and_steepens_edges() {
        let (w, h) = (40, 4);
        let img: Vec<u8> = (0..w * h).map(|i| if i % w < 20 { 50 } else { 200 }).collect();
        let s = unsharp(&img, w, h, 1.5, 1.5);
        assert_eq!(s[5], 50);
        assert_eq!(s[35], 200);
        assert!(s[19] < 50 && s[20] > 200);
    }
}
