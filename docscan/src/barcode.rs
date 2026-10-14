//! Barcode reading through rxing (a Rust port of ZXing): every code in a
//! frame, of any supported symbology, with its position.

use std::collections::HashSet;

use rxing::{BarcodeFormat, DecodeHints, helpers};
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Barcode {
    pub format: String,
    pub text: String,
    /// The raw payload, for binary codes whose text decoding is lossy.
    pub bytes: Vec<u8>,
    /// Corner or end points in the analysed image's pixels.
    pub points: Vec<[f32; 2]>,
}

pub fn format_from_name(name: &str) -> Option<BarcodeFormat> {
    Some(match name.to_ascii_lowercase().replace(['-', '_', ' '], "").as_str() {
        "qrcode" | "qr" => BarcodeFormat::QR_CODE,
        "datamatrix" => BarcodeFormat::DATA_MATRIX,
        "pdf417" => BarcodeFormat::PDF_417,
        "aztec" => BarcodeFormat::AZTEC,
        "code128" => BarcodeFormat::CODE_128,
        "code39" => BarcodeFormat::CODE_39,
        "code93" => BarcodeFormat::CODE_93,
        "codabar" => BarcodeFormat::CODABAR,
        "ean13" => BarcodeFormat::EAN_13,
        "ean8" => BarcodeFormat::EAN_8,
        "upca" => BarcodeFormat::UPC_A,
        "upce" => BarcodeFormat::UPC_E,
        "itf" => BarcodeFormat::ITF,
        "maxicode" => BarcodeFormat::MAXICODE,
        _ => return None,
    })
}

/// rxing's display names carry spaces (`"pdf 417"`); use the compact form.
pub fn format_name(format: &BarcodeFormat) -> String {
    format.to_string().to_ascii_lowercase().replace([' ', '_', '-'], "")
}

/// The symbologies an identity document can carry.
pub const ID_FORMATS: &[&str] = &["pdf417", "code39", "code128", "itf", "qrcode", "datamatrix"];

/// Reads every barcode; when a PDF417 is wanted but not found, retries on a
/// copy levelled by the estimated skew and maps its points back. Then
/// rescues linear codes too fine for the frame (see [`rescue_linear`]).
pub fn read_all(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    let mut found = read_with_skew_retry(luma, w, h, formats);
    let rescued = rescue_linear(luma, w as usize, h as usize, formats, &found);
    found.extend(rescued);
    drop_nested_reads(found)
}

/// Short, weakly checked linear codes, which a reader finds in part of
/// another symbol's bars.
const WEAK_LINEAR: &[&str] = &["upce", "ean8"];

/// Drops a weak short code (UPC-E, EAN-8) read along the bars of a longer
/// linear code in the same frame: two real codes cannot overlap, and a
/// UPC-E inside an EAN-13's bars, read on a scan line near its foot, has a
/// valid check digit often enough to show up on dense sheets.
pub fn drop_nested_reads(codes: Vec<Barcode>) -> Vec<Barcode> {
    let segment = |b: &Barcode| -> Option<([f32; 2], [f32; 2])> {
        (b.points.len() == 2).then(|| (b.points[0], b.points[1]))
    };
    let inside = |inner: &Barcode, outer: &Barcode| -> bool {
        let (Some((a0, a1)), Some((b0, b1))) = (segment(inner), segment(outer)) else { return false };
        let (dx, dy) = (b1[0] - b0[0], b1[1] - b0[1]);
        let len = (dx * dx + dy * dy).sqrt();
        if len < 1.0 {
            return false;
        }
        let (ux, uy) = (dx / len, dy / len);
        // Each end of the inner scan line, along and across the outer one.
        let place = |p: [f32; 2]| {
            let (px, py) = (p[0] - b0[0], p[1] - b0[1]);
            (px * ux + py * uy, (px * uy - py * ux).abs())
        };
        let ((s0, d0), (s1, d1)) = (place(a0), place(a1));
        let slack = 0.05 * len;
        // Within the outer code's extent, and within its bars' height,
        // which is a good fraction of its width on any 1D symbol.
        s0.min(s1) >= -slack && s0.max(s1) <= len + slack && d0.max(d1) <= 0.8 * len
    };
    let keep: Vec<bool> = codes
        .iter()
        .map(|c| {
            !WEAK_LINEAR.contains(&c.format.as_str())
                || !codes.iter().any(|o| !std::ptr::eq(o, c) && !WEAK_LINEAR.contains(&o.format.as_str()) && inside(c, o))
        })
        .collect();
    codes.into_iter().zip(keep).filter_map(|(c, k)| k.then_some(c)).collect()
}

fn read_with_skew_retry(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    let mut found = read_once(luma, w, h, formats);
    let wants_pdf417 = formats.is_none_or(|f| f.iter().any(|f| format_from_name(f) == Some(BarcodeFormat::PDF_417)));
    if wants_pdf417 && !found.iter().any(|b| b.format == "pdf417") {
        let skew = crate::geometry::estimate_skew(luma, w as usize, h as usize);
        if skew.abs() >= 2.0 {
            let (rot, rw, rh) = crate::geometry::rotate(luma, w as usize, h as usize, skew);
            let only = ["pdf417".to_string()];
            let (s, c) = skew.to_radians().sin_cos();
            let (cx, cy, ncx, ncy) = (w as f32 / 2.0, h as f32 / 2.0, rw as f32 / 2.0, rh as f32 / 2.0);
            for mut b in read_once(&rot, rw as u32, rh as u32, Some(&only)) {
                for p in &mut b.points {
                    let (dx, dy) = (p[0] - ncx, p[1] - ncy);
                    *p = [c * dx - s * dy + cx, s * dx + c * dy + cy];
                }
                found.push(b);
            }
        }
    }
    found
}

fn read_once(luma: &[u8], w: u32, h: u32, formats: Option<&[String]>) -> Vec<Barcode> {
    let mut hints = DecodeHints::default().with(rxing::DecodeHintValue::TryHarder(true));
    if let Some(formats) = formats {
        let set: HashSet<BarcodeFormat> =
            formats.iter().filter_map(|f| format_from_name(f)).collect();
        if !set.is_empty() {
            hints = hints.with(rxing::DecodeHintValue::PossibleFormats(set));
        }
    }
    let results = helpers::detect_multiple_in_luma_with_hints(luma.to_vec(), w, h, &mut hints)
        .unwrap_or_default();

    let mut seen = HashSet::new();
    results
        .into_iter()
        .filter(|r| seen.insert((r.getBarcodeFormat().to_string(), r.getText().to_string())))
        .map(|r| Barcode {
            format: format_name(r.getBarcodeFormat()),
            text: r.getText().to_string(),
            bytes: r.getRawBytes().to_vec(),
            points: r.getPoints().iter().map(|p| [p.x, p.y]).collect(),
        })
        .collect()
}

/// Linear symbologies the rescue pass looks for: those with a check
/// character or a strict structure. UPC-E, EAN-8, ITF and Codabar are left
/// out: on an upsampled patch of print they decode noise too readily.
const RESCUE_FORMATS: &[&str] = &["code128", "code39", "code93", "ean13"];
/// Upsampling across the bars. Calibrated on the HD test sheet, whose
/// Code 128s have about 1.2 px per module: 2× does not recover them, 4× does.
const RESCUE_SCALE: usize = 4;
/// Patches tried per frame at most, largest first.
const RESCUE_MAX_REGIONS: usize = 6;

/// A patch that looks like a linear barcode: bars across `x` (or across `y`
/// when `vertical_run` is set, a code turned 90°).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Region {
    pub x0: usize,
    pub y0: usize,
    pub x1: usize,
    pub y1: usize,
    pub bars_along_x: bool,
}

/// Linear codes whose narrowest bars span little more than a pixel alias to
/// grey and defeat the binariser. Each barcode-like patch not already read
/// is upsampled across its bars (bilinear) and sharpened (an unsharp mask),
/// which restores a usable edge between neighbouring bars, then decoded for
/// the linear symbologies only.
pub fn rescue_linear(luma: &[u8], w: usize, h: usize, formats: Option<&[String]>, found: &[Barcode]) -> Vec<Barcode> {
    let wanted: Vec<String> = RESCUE_FORMATS
        .iter()
        .filter(|f| formats.is_none_or(|fs| fs.iter().any(|x| format_from_name(x) == format_from_name(f))))
        .map(|f| f.to_string())
        .collect();
    if wanted.is_empty() {
        return Vec::new();
    }
    let mut out: Vec<Barcode> = Vec::new();
    let read_already = |r: &Region, codes: &[Barcode]| {
        codes.iter().any(|b| {
            b.points.iter().any(|p| {
                let (x, y) = (p[0] as usize, p[1] as usize);
                x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1
            })
        })
    };
    for r in linear_regions(luma, w, h).into_iter().take(RESCUE_MAX_REGIONS * 2) {
        if read_already(&r, found) || read_already(&r, &out) {
            continue;
        }
        // Pad by a quiet zone's worth either side of the bars.
        let (pw, ph) = ((r.x1 - r.x0) / 8 + 8, (r.y1 - r.y0) / 8 + 8);
        let (x0, y0) = (r.x0.saturating_sub(pw), r.y0.saturating_sub(ph));
        let (x1, y1) = ((r.x1 + pw).min(w), (r.y1 + ph).min(h));
        let (cw, ch) = (x1 - x0, y1 - y0);
        let mut patch = Vec::with_capacity(cw * ch);
        for y in y0..y1 {
            patch.extend_from_slice(&luma[y * w + x0..y * w + x1]);
        }
        // Work with the bars vertical: transpose a code turned 90°.
        let (patch, pw2, ph2) = if r.bars_along_x { (patch, cw, ch) } else { transpose(&patch, cw, ch) };
        let (up, uw, uh) = upsample_x(&patch, pw2, ph2, RESCUE_SCALE);
        let sharp = unsharp_x(&up, uw, uh, 0.8 * RESCUE_SCALE as f32, 2.0);
        for mut b in read_once(&sharp, uw as u32, uh as u32, Some(&wanted)) {
            if out.iter().chain(found).any(|o| o.format == b.format && o.text == b.text) {
                continue;
            }
            for p in &mut b.points {
                let (px, py) = (p[0] / RESCUE_SCALE as f32, p[1]);
                *p = if r.bars_along_x { [px + x0 as f32, py + y0 as f32] } else { [py + x0 as f32, px + y0 as f32] };
            }
            out.push(b);
        }
        if out.len() >= RESCUE_MAX_REGIONS {
            break;
        }
    }
    out
}

/// Patches dense with parallel edges: 8 × 8 cells whose gradient runs
/// overwhelmingly along one axis, grouped into connected runs. Largest first.
pub fn linear_regions(luma: &[u8], w: usize, h: usize) -> Vec<Region> {
    const C: usize = 8;
    let (cw, ch) = (w / C, h / C);
    if cw < 4 || ch < 2 {
        return Vec::new();
    }
    // 0 = nothing, 1 = bars across x (vertical bars), 2 = bars across y.
    let mut cell = vec![0u8; cw * ch];
    for cy in 0..ch {
        for cx in 0..cw {
            let (mut gx, mut gy) = (0u32, 0u32);
            for y in cy * C..(cy + 1) * C {
                for x in cx * C..(cx + 1) * C {
                    let v = luma[y * w + x] as i32;
                    if x + 1 < w {
                        gx += (luma[y * w + x + 1] as i32 - v).unsigned_abs();
                    }
                    if y + 1 < h {
                        gy += (luma[(y + 1) * w + x] as i32 - v).unsigned_abs();
                    }
                }
            }
            // Mean step of 12 grey levels per pixel along the dominant axis:
            // bars, not paper texture or a soft shadow.
            let strong = (C * C * 12) as u32;
            cell[cy * cw + cx] = if gx >= strong && gx > 3 * gy {
                1
            } else if gy >= strong && gy > 3 * gx {
                2
            } else {
                0
            };
        }
    }
    let mut seen = vec![false; cw * ch];
    let mut regions: Vec<(usize, Region)> = Vec::new();
    for start in 0..cw * ch {
        let kind = cell[start];
        if kind == 0 || seen[start] {
            continue;
        }
        // Flood fill, bridging a one-cell gap across the bars (a wide space).
        let mut stack = vec![start];
        seen[start] = true;
        let (mut x0, mut y0, mut x1, mut y1, mut n) = (cw, ch, 0, 0, 0usize);
        while let Some(i) = stack.pop() {
            let (x, y) = (i % cw, i / cw);
            (x0, y0, x1, y1) = (x0.min(x), y0.min(y), x1.max(x), y1.max(y));
            n += 1;
            for (dx, dy) in [(-1i32, 0i32), (1, 0), (0, -1), (0, 1), (-2, 0), (2, 0), (0, -2), (0, 2)] {
                let bridge_ok = if kind == 1 { dy.abs() < 2 } else { dx.abs() < 2 };
                let (nx, ny) = (x as i32 + dx, y as i32 + dy);
                if !bridge_ok || nx < 0 || ny < 0 || nx >= cw as i32 || ny >= ch as i32 {
                    continue;
                }
                let j = ny as usize * cw + nx as usize;
                if !seen[j] && cell[j] == kind {
                    seen[j] = true;
                    stack.push(j);
                }
            }
        }
        let (across, along) = if kind == 1 { (x1 - x0 + 1, y1 - y0 + 1) } else { (y1 - y0 + 1, x1 - x0 + 1) };
        // A code is at least ~48 px across its bars and 16 px along them,
        // and mostly filled (text lines are sparse and ragged).
        if across >= 6 && along >= 2 && n * 2 >= (x1 - x0 + 1) * (y1 - y0 + 1) {
            regions.push((
                n,
                Region { x0: x0 * C, y0: y0 * C, x1: ((x1 + 1) * C).min(w), y1: ((y1 + 1) * C).min(h), bars_along_x: kind == 1 },
            ));
        }
    }
    regions.sort_by(|a, b| b.0.cmp(&a.0));
    regions.into_iter().map(|(_, r)| r).collect()
}

fn transpose(img: &[u8], w: usize, h: usize) -> (Vec<u8>, usize, usize) {
    let mut out = vec![0u8; w * h];
    for y in 0..h {
        for x in 0..w {
            out[x * h + y] = img[y * w + x];
        }
    }
    (out, h, w)
}

/// Bilinear upsampling by `k` along x only.
fn upsample_x(img: &[u8], w: usize, h: usize, k: usize) -> (Vec<u8>, usize, usize) {
    let nw = w * k;
    let mut out = vec![0u8; nw * h];
    for y in 0..h {
        let row = &img[y * w..(y + 1) * w];
        for x in 0..nw {
            let sx = ((x as f32 + 0.5) / k as f32 - 0.5).clamp(0.0, (w - 1) as f32);
            let x0 = sx as usize;
            let x1 = (x0 + 1).min(w - 1);
            let f = sx - x0 as f32;
            out[y * nw + x] = (row[x0] as f32 * (1.0 - f) + row[x1] as f32 * f).round() as u8;
        }
    }
    (out, nw, h)
}

/// An unsharp mask along x: `v + amount × (v − gaussian(v))`.
fn unsharp_x(img: &[u8], w: usize, h: usize, sigma: f32, amount: f32) -> Vec<u8> {
    let r = (sigma * 3.0).ceil() as isize;
    let kernel: Vec<f32> = (-r..=r).map(|i| (-(i * i) as f32 / (2.0 * sigma * sigma)).exp()).collect();
    let total: f32 = kernel.iter().sum();
    let mut out = vec![0u8; w * h];
    for y in 0..h {
        let row = &img[y * w..(y + 1) * w];
        for x in 0..w {
            let mut acc = 0.0;
            for (k, kv) in kernel.iter().enumerate() {
                let sx = (x as isize + k as isize - r).clamp(0, w as isize - 1) as usize;
                acc += row[sx] as f32 * kv;
            }
            let v = row[x] as f32;
            out[y * w + x] = (v + amount * (v - acc / total)).clamp(0.0, 255.0) as u8;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn linear(format: &str, text: &str, a: [f32; 2], b: [f32; 2]) -> Barcode {
        Barcode { format: format.into(), text: text.into(), bytes: vec![], points: vec![a, b] }
    }

    /// The UPC-E read on frame 84 of the HD multi-barcode clip, along the
    /// foot of the EAN-13's bars: dropped. A UPC-E elsewhere is kept.
    #[test]
    fn a_weak_code_inside_another_is_dropped() {
        let ean = linear("ean13", "6001234567899", [886.0, 165.0], [1042.0, 165.0]);
        let nested = linear("upce", "11032861", [1024.0, 260.0], [899.0, 260.0]);
        let apart = linear("upce", "01234565", [200.0, 600.0], [300.0, 600.0]);
        let kept = drop_nested_reads(vec![ean, nested, apart]);
        let texts: Vec<&str> = kept.iter().map(|b| b.text.as_str()).collect();
        assert_eq!(texts, ["6001234567899", "01234565"]);
    }

    /// A band of vertical bars on paper is found as one region, bars across x;
    /// the same turned 90° is found with bars across y.
    #[test]
    fn finds_bar_patches() {
        let (w, h) = (320, 160);
        let mut img = vec![230u8; w * h];
        for y in 40..100 {
            for x in 60..260 {
                if (x / 2 + x / 7) % 2 == 0 {
                    img[y * w + x] = 20;
                }
            }
        }
        let r = linear_regions(&img, w, h);
        assert_eq!(r.len(), 1, "{r:?}");
        assert!(r[0].bars_along_x && r[0].x0 <= 64 && r[0].x1 >= 256 && r[0].y0 <= 40 && r[0].y1 >= 96, "{r:?}");
        let (t, tw, th) = transpose(&img, w, h);
        let r = linear_regions(&t, tw, th);
        assert_eq!(r.len(), 1, "{r:?}");
        assert!(!r[0].bars_along_x);
    }
}
