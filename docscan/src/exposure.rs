//! Experimental, explicit opt-in global exposure correction for ordinary OCR.
//!
//! A native port of the frozen reference arm
//! `experiments/research_optics/optics.py:preprocess(rgb, "global_exposure")`,
//! contract `experiments/research_optics/global-contract-v1.json`
//! (`frozen-global-exposure-v1`). It is never called by default: the only
//! caller is an explicit, opt-in brightness comparison for ordinary PP-OCR
//! text, which keeps the original reading primary and returns the corrected
//! one separately. It authorises nothing: a corrected reading is an
//! alternative, never a certified more-correct one, there is no automatic
//! selection or union of readings, and it must not feed ID or face
//! acceptance. Evidence and limits: `docs/improvements-exposure.md`.
//!
//! What it does, and nothing else:
//!
//! 1. A thumbnail at most 512 px on the long side (OpenCV `INTER_AREA`
//!    semantics on the encoded uint8 RGB; no resize when already small enough).
//! 2. Inverse sRGB as an *approximation* of linear light (not RAW, not a
//!    measured camera response), luminance `[0.2126, 0.7152, 0.0722]`.
//! 3. A background field: a 25 x 25 max filter (suppresses glyphs) then a
//!    Gaussian blur, sigma 9 (73 taps, reflect-101 border).
//! 4. Gate: the background's 90th percentile (numpy "linear"). At or above
//!    0.55 the image is left exactly as it is and no pixels are produced.
//! 5. Otherwise one scalar gain `min(4, 0.85 / max(p90, 0.01))`, applied to
//!    every channel of the full-resolution original in linear light, clipped
//!    and re-encoded. No per-channel white balance, no spatial gain, no
//!    sharpening, denoising, masking or text-dependent choice. (The local
//!    illumination arm and burst/glare selection were rejected and are not here.)
//!
//! The input slice is only read: the original buffer, and so the original
//! forensic evidence, is never altered. Diagnostics are returned separately
//! from any output pixels. Work is bounded by [`MAX_PIXELS`] and is a fixed
//! function of the dimensions (no iteration to convergence, no data-dependent
//! loops). The transcendental steps (inverse sRGB, sRGB encoding, the
//! Gaussian taps) are frozen tables generated from the reference
//! (`experiments/research_optics_native/tables.py`), and everything else is
//! plain f32/f64 arithmetic with no fused operations, so native and WASM
//! builds give the same bytes for the same input.

/// Identifies the frozen rules this module implements.
pub const VERSION: &str = "frozen-global-exposure-v1";
/// The same ceiling as the OCR reader (`text_v6::MAX_PIXELS`).
pub const MAX_PIXELS: usize = 24_000_000;
/// The thumbnail's long side.
pub const THUMBNAIL_MAX_SIDE: usize = 512;
/// The max filter's side.
pub const DILATE_SIDE: usize = 25;
/// The Gaussian's sigma, and its tap count as OpenCV derives it for float
/// images: `round(sigma * 4 * 2 + 1) | 1`.
pub const GAUSSIAN_SIGMA: f64 = 9.0;
pub const GAUSSIAN_TAPS: usize = 73;
/// The gate: correction runs only while the background p90 is below this.
pub const GATE_P90: f64 = 0.55;
/// The target background level and the gain ceiling.
pub const TARGET: f64 = 0.85;
pub const MAX_GAIN: f64 = 4.0;

/// How the caller's pixels are laid out. Alpha, when present, is copied
/// through untouched and never enters the statistics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Layout {
    Rgb,
    Rgba,
}

impl Layout {
    pub fn channels(self) -> usize {
        match self {
            Layout::Rgb => 3,
            Layout::Rgba => 4,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExposureError {
    /// Zero width or height.
    Empty,
    /// `width * height * channels` overflows `usize`.
    Overflow,
    /// More than [`MAX_PIXELS`] pixels.
    TooLarge { pixels: usize, max: usize },
    /// The slice is not exactly `width * height * channels` bytes.
    Length { expected: usize, actual: usize },
}

impl std::fmt::Display for ExposureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ExposureError::Empty => write!(f, "image has no pixels"),
            ExposureError::Overflow => write!(f, "image dimensions overflow"),
            ExposureError::TooLarge { pixels, max } => {
                write!(f, "image has {pixels} pixels, more than {max}; resize before correcting")
            }
            ExposureError::Length { expected, actual } => {
                write!(f, "pixel buffer is {actual} bytes, expected {expected}")
            }
        }
    }
}

impl std::error::Error for ExposureError {}

/// What the analysis found. Never contains pixels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ExposureDiagnostics {
    pub width: usize,
    pub height: usize,
    pub thumbnail_width: usize,
    pub thumbnail_height: usize,
    /// The background's 90th percentile, linear light, 0..1.
    pub background_p90: f64,
    /// Whether the gate opened (`background_p90 < GATE_P90`).
    pub applied: bool,
    /// The scalar gain in linear light; exactly 1 when not applied.
    pub gain: f64,
}

/// The result of [`correct`]. `pixels` is `None` when the gate stayed shut:
/// the caller keeps using its original buffer, with nothing copied.
#[derive(Debug, Clone, PartialEq)]
pub struct Corrected {
    pub diagnostics: ExposureDiagnostics,
    /// A new buffer in the input's layout and dimensions, or `None`.
    pub pixels: Option<Vec<u8>>,
    /// Whether `pixels` differs from the input in any byte (the reference's
    /// `changed`). A gate that opens can still change nothing.
    pub changed: bool,
}

/// Analyse, and when the gate opens, produce corrected pixels.
pub fn correct(
    pixels: &[u8],
    width: usize,
    height: usize,
    layout: Layout,
) -> Result<Corrected, ExposureError> {
    let diagnostics = analyse(pixels, width, height, layout)?;
    if !diagnostics.applied {
        return Ok(Corrected { diagnostics, pixels: None, changed: false });
    }
    let out = apply_gain(pixels, layout, diagnostics.gain);
    let changed = out != pixels;
    Ok(Corrected { diagnostics, pixels: Some(out), changed })
}

/// The gate and gain only; reads the pixels, writes nothing.
pub fn analyse(
    pixels: &[u8],
    width: usize,
    height: usize,
    layout: Layout,
) -> Result<ExposureDiagnostics, ExposureError> {
    check(pixels, width, height, layout)?;
    let (tw, th) = thumbnail_size(width, height);
    let channels = layout.channels();
    let thumb;
    let rgb: &[u8] = if (tw, th) == (width, height) && layout == Layout::Rgb {
        pixels
    } else if (tw, th) == (width, height) {
        thumb = strip_alpha(pixels);
        &thumb
    } else {
        thumb = resize_area(pixels, width, height, channels, tw, th);
        &thumb
    };
    let lut = linear_lut();
    let y: Vec<f32> = rgb
        .chunks_exact(3)
        .map(|p| luminance(lut[p[0] as usize], lut[p[1] as usize], lut[p[2] as usize]))
        .collect();
    let dilated = dilate(&y, tw, th, DILATE_SIDE);
    let background = gaussian(&dilated, tw, th);
    let p90 = percentile_linear(background, 0.9);
    let applied = p90 < GATE_P90;
    let gain = if applied { MAX_GAIN.min(TARGET / p90.max(0.01)) } else { 1.0 };
    Ok(ExposureDiagnostics {
        width,
        height,
        thumbnail_width: tw,
        thumbnail_height: th,
        background_p90: p90,
        applied,
        gain,
    })
}

/// Multiply every colour channel by one gain in linear light and re-encode.
/// Returns a new buffer; `pixels` is not touched. Each output byte depends
/// only on its input byte, so this is a 256-entry table.
pub fn apply_gain(pixels: &[u8], layout: Layout, gain: f64) -> Vec<u8> {
    let table = gain_table(gain);
    let mut out = Vec::with_capacity(pixels.len());
    match layout {
        Layout::Rgb => out.extend(pixels.iter().map(|&c| table[c as usize])),
        Layout::Rgba => {
            for p in pixels.chunks_exact(4) {
                out.extend_from_slice(&[
                    table[p[0] as usize],
                    table[p[1] as usize],
                    table[p[2] as usize],
                    p[3],
                ]);
            }
        }
    }
    out
}

/// `encode(linear(code) * gain)` for every code. The gain enters float32
/// arithmetic as numpy's weak Python-float promotion makes it: cast to f32.
pub fn gain_table(gain: f64) -> [u8; 256] {
    let lut = linear_lut();
    let g = gain as f32;
    std::array::from_fn(|c| encode(lut[c] * g))
}

fn check(pixels: &[u8], width: usize, height: usize, layout: Layout) -> Result<(), ExposureError> {
    if width == 0 || height == 0 {
        return Err(ExposureError::Empty);
    }
    let count = width.checked_mul(height).ok_or(ExposureError::Overflow)?;
    if count > MAX_PIXELS {
        return Err(ExposureError::TooLarge { pixels: count, max: MAX_PIXELS });
    }
    let expected = count.checked_mul(layout.channels()).ok_or(ExposureError::Overflow)?;
    if pixels.len() != expected {
        return Err(ExposureError::Length { expected, actual: pixels.len() });
    }
    Ok(())
}

/// `max(1, round(side * scale))` with Python's ties-to-even `round` and
/// `scale = min(1, 512 / max(height, width))` in f64.
pub fn thumbnail_size(width: usize, height: usize) -> (usize, usize) {
    let scale = (THUMBNAIL_MAX_SIDE as f64 / width.max(height) as f64).min(1.0);
    if scale >= 1.0 {
        return (width, height);
    }
    let side = |s: usize| ((s as f64 * scale).round_ties_even() as usize).max(1);
    (side(width), side(height))
}

/// Inverse sRGB of every code value, exactly as the reference's float32
/// arithmetic produces it.
pub fn linear_lut() -> [f32; 256] {
    LINEAR_BITS.map(f32::from_bits)
}

/// sRGB encoding, clipped, `rint` (ties to even) to a byte: the number of
/// thresholds at or below `x`. Non-negative f32 order is bit-pattern order.
fn encode(x: f32) -> u8 {
    if !(x > 0.0) {
        return 0;
    }
    let bits = x.min(1.0).to_bits();
    ENCODE_THRESHOLD_BITS.partition_point(|&t| t <= bits) as u8
}

fn luminance(r: f32, g: f32, b: f32) -> f32 {
    r * 0.2126 + g * 0.7152 + b * 0.0722
}

fn strip_alpha(pixels: &[u8]) -> Vec<u8> {
    pixels.chunks_exact(4).flat_map(|p| [p[0], p[1], p[2]]).collect()
}

/// OpenCV's `INTER_AREA` downscale of interleaved uint8, to RGB (alpha
/// dropped). Integer factors take OpenCV's fast path (an exact box mean:
/// `(sum + 2) >> 2` for 2 x 2, else `saturate_cast` of `sum * (1/area)`);
/// other factors its fractional-coverage
/// path (`computeResizeAreaTab`, float accumulation, row by row).
fn resize_area(src: &[u8], sw: usize, sh: usize, cn: usize, dw: usize, dh: usize) -> Vec<u8> {
    let scale_x = sw as f64 / dw as f64;
    let scale_y = sh as f64 / dh as f64;
    let (ix, iy) = (scale_x.round_ties_even(), scale_y.round_ties_even());
    let mut out = vec![0u8; dw * dh * 3];
    if (scale_x - ix).abs() < f64::EPSILON && (scale_y - iy).abs() < f64::EPSILON {
        let (ix, iy) = (ix as usize, iy as usize);
        let inv = 1.0f32 / (ix * iy) as f32;
        for dy in 0..dh {
            for dx in 0..dw {
                for c in 0..3 {
                    let mut sum = 0u32;
                    for y in dy * iy..dy * iy + iy {
                        let row = &src[y * sw * cn..];
                        for x in dx * ix..dx * ix + ix {
                            sum += row[x * cn + c] as u32;
                        }
                    }
                    // OpenCV's 2 x 2 uint8 kernel rounds half up in integers;
                    // every other factor rounds `sum * (1/area)` to even.
                    out[(dy * dw + dx) * 3 + c] =
                        if (ix, iy) == (2, 2) { ((sum + 2) >> 2) as u8 } else { saturate(sum as f32 * inv) };
                }
            }
        }
        return out;
    }
    let xtab = area_table(sw, dw, scale_x);
    let ytab = area_table(sh, dh, scale_y);
    let mut buf = vec![0f32; dw * 3];
    let mut sum = vec![0f32; dw * 3];
    let mut prev_dy = ytab[0].0;
    for &(dy, sy, beta) in &ytab {
        buf.fill(0.0);
        let row = &src[sy * sw * cn..(sy + 1) * sw * cn];
        for &(dx, sx, alpha) in &xtab {
            for c in 0..3 {
                buf[dx * 3 + c] += row[sx * cn + c] as f32 * alpha;
            }
        }
        if dy != prev_dy {
            for (o, s) in out[prev_dy * dw * 3..(prev_dy + 1) * dw * 3].iter_mut().zip(&sum) {
                *o = saturate(*s);
            }
            for (s, b) in sum.iter_mut().zip(&buf) {
                *s = beta * b;
            }
            prev_dy = dy;
        } else {
            for (s, b) in sum.iter_mut().zip(&buf) {
                *s += beta * b;
            }
        }
    }
    for (o, s) in out[prev_dy * dw * 3..(prev_dy + 1) * dw * 3].iter_mut().zip(&sum) {
        *o = saturate(*s);
    }
    out
}

/// OpenCV's `computeResizeAreaTab`: (destination index, source index, weight).
fn area_table(ssize: usize, dsize: usize, scale: f64) -> Vec<(usize, usize, f32)> {
    let mut tab = Vec::with_capacity(ssize * 2);
    for dx in 0..dsize {
        let fsx1 = dx as f64 * scale;
        let fsx2 = fsx1 + scale;
        let cell = scale.min(ssize as f64 - fsx1);
        let mut sx1 = fsx1.ceil() as i64;
        let mut sx2 = fsx2.floor() as i64;
        sx2 = sx2.min(ssize as i64 - 1);
        sx1 = sx1.min(sx2);
        if sx1 as f64 - fsx1 > 1e-3 {
            tab.push((dx, (sx1 - 1) as usize, ((sx1 as f64 - fsx1) / cell) as f32));
        }
        for sx in sx1..sx2 {
            tab.push((dx, sx as usize, (1.0 / cell) as f32));
        }
        if fsx2 - sx2 as f64 > 1e-3 {
            let w = (fsx2 - sx2 as f64).min(1.0).min(cell) / cell;
            tab.push((dx, sx2 as usize, w as f32));
        }
    }
    tab
}

/// OpenCV `saturate_cast<uchar>(float)`: round half to even, then clamp.
fn saturate(v: f32) -> u8 {
    v.round_ties_even().clamp(0.0, 255.0) as u8
}

/// A `side x side` max filter, centred, ignoring everything outside the
/// image (OpenCV's default dilation border). Separable and exact.
fn dilate(src: &[f32], w: usize, h: usize, side: usize) -> Vec<f32> {
    let r = side / 2;
    let mut rows = vec![0f32; w * h];
    for y in 0..h {
        let line = &src[y * w..(y + 1) * w];
        for x in 0..w {
            let window = &line[x.saturating_sub(r)..(x + r + 1).min(w)];
            rows[y * w + x] = window.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        }
    }
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        let (lo, hi) = (y.saturating_sub(r), (y + r + 1).min(h));
        let line = &mut out[y * w..(y + 1) * w];
        line.copy_from_slice(&rows[lo * w..(lo + 1) * w]);
        for yy in lo + 1..hi {
            for (o, &v) in line.iter_mut().zip(&rows[yy * w..(yy + 1) * w]) {
                *o = o.max(v);
            }
        }
    }
    out
}

/// OpenCV `getGaussianKernel(73, 9, CV_32F)`, as frozen from OpenCV.
fn gaussian_kernel() -> [f32; GAUSSIAN_TAPS] {
    GAUSSIAN_BITS.map(f32::from_bits)
}

/// OpenCV `borderInterpolate(p, len, BORDER_REFLECT_101)`.
fn reflect101(mut p: isize, len: usize) -> usize {
    let len = len as isize;
    if len == 1 {
        return 0;
    }
    while p < 0 || p >= len {
        p = if p < 0 { -p } else { 2 * len - 2 - p };
    }
    p as usize
}

/// Separable Gaussian, rows then columns, reflect-101 border, f32.
fn gaussian(src: &[f32], w: usize, h: usize) -> Vec<f32> {
    let k = gaussian_kernel();
    let r = (GAUSSIAN_TAPS / 2) as isize;
    let xs: Vec<usize> = (-r..w as isize + r).map(|p| reflect101(p, w)).collect();
    let ys: Vec<usize> = (-r..h as isize + r).map(|p| reflect101(p, h)).collect();
    let mut rows = vec![0f32; w * h];
    for y in 0..h {
        let line = &src[y * w..(y + 1) * w];
        for x in 0..w {
            let mut s = 0f32;
            for (t, &kv) in k.iter().enumerate() {
                s += kv * line[xs[x + t]];
            }
            rows[y * w + x] = s;
        }
    }
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        let line = &mut out[y * w..(y + 1) * w];
        for (t, &kv) in k.iter().enumerate() {
            let src_row = &rows[ys[y + t] * w..(ys[y + t] + 1) * w];
            for (o, &v) in line.iter_mut().zip(src_row) {
                *o += kv * v;
            }
        }
    }
    out
}

/// numpy `percentile(a, [q * 100])` with the default "linear" method, as it
/// evaluates for a float32 array and a list of percentiles: the neighbours'
/// difference in f32, the interpolation in f64.
fn percentile_linear(mut values: Vec<f32>, q: f64) -> f64 {
    let n = values.len();
    let virtual_index = (n - 1) as f64 * q;
    let lo = (virtual_index.floor() as usize).min(n - 1);
    let hi = (lo + 1).min(n - 1);
    let gamma = virtual_index - lo as f64;
    let (_, &mut a, upper) = values.select_nth_unstable_by(lo, f32::total_cmp);
    let b = if hi == lo { a } else { upper.iter().copied().fold(f32::INFINITY, f32::min) };
    let diff = (b - a) as f64;
    if gamma >= 0.5 { b as f64 - diff * (1.0 - gamma) } else { a as f64 + diff * gamma }
}

// Generated by experiments/research_optics_native/tables.py from the frozen
// reference (numpy 2.5.4, OpenCV 5.0.0); do not edit.
const LINEAR_BITS: [u32; 256] = [
    0x00000000, 0x399f22b4, 0x3a1f22b4, 0x3a6eb40e, 0x3a9f22b4, 0x3ac6eb61, 0x3aeeb40e, 0x3b0b3e5d,
    0x3b1f22b4, 0x3b33070b, 0x3b46eb61, 0x3b5b518d, 0x3b70f18d, 0x3b83e1c6, 0x3b8fe616, 0x3b9c87fd,
    0x3ba9c9b7, 0x3bb7ad6f, 0x3bc63549, 0x3bd56361, 0x3be539c1, 0x3bf5ba70, 0x3c0373b5, 0x3c0c6152,
    0x3c15a703, 0x3c1f45be, 0x3c293e6b, 0x3c3391f7, 0x3c3e4149, 0x3c494d43, 0x3c54b6c7, 0x3c607eb1,
    0x3c6ca5df, 0x3c792d22, 0x3c830aa8, 0x3c89af9f, 0x3c9085db, 0x3c978dc5, 0x3c9ec7c2, 0x3ca63433,
    0x3cadd37d, 0x3cb5a601, 0x3cbdac20, 0x3cc5e639, 0x3cce54ab, 0x3cd6f7d5, 0x3cdfd010, 0x3ce8ddb9,
    0x3cf2212c, 0x3cfb9ac1, 0x3d02a569, 0x3d0798dc, 0x3d0ca7e6, 0x3d11d2af, 0x3d171963, 0x3d1c7c2e,
    0x3d21fb3c, 0x3d2796b2, 0x3d2d4ebb, 0x3d332380, 0x3d39152b, 0x3d3f23e3, 0x3d454fd1, 0x3d4b991c,
    0x3d51ffef, 0x3d58846a, 0x3d5f26b7, 0x3d65e6fe, 0x3d6cc564, 0x3d73c20f, 0x3d7add29, 0x3d810b67,
    0x3d84b795, 0x3d887330, 0x3d8c3e4a, 0x3d9018f6, 0x3d940345, 0x3d97fd4a, 0x3d9c0716, 0x3da020bb,
    0x3da44a4b, 0x3da883d7, 0x3daccd70, 0x3db12728, 0x3db59112, 0x3dba0b3b, 0x3dbe95b5, 0x3dc33092,
    0x3dc7dbe2, 0x3dcc97b6, 0x3dd1641f, 0x3dd6412c, 0x3ddb2eef, 0x3de02d77, 0x3de53cd5, 0x3dea5d19,
    0x3def8e52, 0x3df4d091, 0x3dfa23e8, 0x3dff8861, 0x3e027f07, 0x3e054280, 0x3e080ea3, 0x3e0ae378,
    0x3e0dc105, 0x3e10a754, 0x3e13966b, 0x3e168e52, 0x3e198f10, 0x3e1c98ad, 0x3e1fab30, 0x3e22c6a3,
    0x3e25eb09, 0x3e29186c, 0x3e2c4ed0, 0x3e2f8e41, 0x3e32d6c4, 0x3e362861, 0x3e39831e, 0x3e3ce703,
    0x3e405416, 0x3e43ca5f, 0x3e4749e4, 0x3e4ad2ae, 0x3e4e64c2, 0x3e520027, 0x3e55a4e6, 0x3e595303,
    0x3e5d0a8b, 0x3e60cb7c, 0x3e6495e0, 0x3e6869bf, 0x3e6c4720, 0x3e702e0c, 0x3e741e84, 0x3e781890,
    0x3e7c1c38, 0x3e8014c2, 0x3e82203c, 0x3e84308d, 0x3e8645ba, 0x3e885fc5, 0x3e8a7eb2, 0x3e8ca283,
    0x3e8ecb3d, 0x3e90f8e1, 0x3e932b74, 0x3e9562f8, 0x3e979f71, 0x3e99e0e2, 0x3e9c274e, 0x3e9e72b7,
    0x3ea0c322, 0x3ea31892, 0x3ea57308, 0x3ea7d289, 0x3eaa3718, 0x3eaca0b7, 0x3eaf0f69, 0x3eb18333,
    0x3eb3fc18, 0x3eb67a18, 0x3eb8fd37, 0x3ebb8579, 0x3ebe12e1, 0x3ec0a571, 0x3ec33d2d, 0x3ec5da17,
    0x3ec87c33, 0x3ecb2383, 0x3ecdd00b, 0x3ed081cd, 0x3ed338cc, 0x3ed5f50b, 0x3ed8b68d, 0x3edb7d54,
    0x3ede4965, 0x3ee11ac1, 0x3ee3f16b, 0x3ee6cd67, 0x3ee9aeb6, 0x3eec955d, 0x3eef815d, 0x3ef272ba,
    0x3ef56976, 0x3ef86594, 0x3efb6717, 0x3efe6e02, 0x3f00bd2d, 0x3f02460e, 0x3f03d1a7, 0x3f055ff9,
    0x3f06f106, 0x3f0884cf, 0x3f0a1b56, 0x3f0bb49b, 0x3f0d50a0, 0x3f0eef67, 0x3f1090f1, 0x3f12353e,
    0x3f13dc51, 0x3f15862b, 0x3f1732cd, 0x3f18e239, 0x3f1a946f, 0x3f1c4971, 0x3f1e0141, 0x3f1fbbdf,
    0x3f21794e, 0x3f23398e, 0x3f24fca0, 0x3f26c286, 0x3f288b41, 0x3f2a56d3, 0x3f2c253d, 0x3f2df680,
    0x3f2fca9e, 0x3f31a197, 0x3f337b6c, 0x3f355820, 0x3f3737b3, 0x3f391a26, 0x3f3aff7c, 0x3f3ce7b5,
    0x3f3ed2d2, 0x3f40c0d4, 0x3f42b1be, 0x3f44a590, 0x3f469c4b, 0x3f4895f1, 0x3f4a9282, 0x3f4c9201,
    0x3f4e946e, 0x3f5099cb, 0x3f52a218, 0x3f54ad57, 0x3f56bb8a, 0x3f58ccb0, 0x3f5ae0cd, 0x3f5cf7e0,
    0x3f5f11ec, 0x3f612eee, 0x3f634eef, 0x3f6571e9, 0x3f6797e3, 0x3f69c0d6, 0x3f6beccd, 0x3f6e1bbf,
    0x3f704db8, 0x3f7282af, 0x3f74baae, 0x3f76f5ae, 0x3f7933b9, 0x3f7b74c6, 0x3f7db8e0, 0x3f800000,
];

const GAUSSIAN_BITS: [u32; 73] = [
    0x37797d70, 0x37c15ba4, 0x38140428, 0x385fd55c, 0x38a72a98, 0x38f6a09a, 0x3933b28b, 0x39815313,
    0x39b7dc43, 0x3a0117e5, 0x3a330e3a, 0x3a754ea0, 0x3aa5f96c, 0x3addd70b, 0x3b126f90, 0x3b3ef391,
    0x3b75f1c5, 0x3b9c71b4, 0x3bc495b9, 0x3bf3fe75, 0x3c158f74, 0x3c351a01, 0x3c589a9b, 0x3c7fe326,
    0x3c954b03, 0x3cac1141, 0x3cc3e1f7, 0x3cdc420f, 0x3cf4a0bb, 0x3d062e20, 0x3d11643c, 0x3d1b9b50,
    0x3d247f04, 0x3d2bc283, 0x3d3124ca, 0x3d347467, 0x3d359273, 0x3d347467, 0x3d3124ca, 0x3d2bc283,
    0x3d247f04, 0x3d1b9b50, 0x3d11643c, 0x3d062e20, 0x3cf4a0bb, 0x3cdc420f, 0x3cc3e1f7, 0x3cac1141,
    0x3c954b03, 0x3c7fe326, 0x3c589a9b, 0x3c351a01, 0x3c158f74, 0x3bf3fe75, 0x3bc495b9, 0x3b9c71b4,
    0x3b75f1c5, 0x3b3ef391, 0x3b126f90, 0x3addd70b, 0x3aa5f96c, 0x3a754ea0, 0x3a330e3a, 0x3a0117e5,
    0x39b7dc43, 0x39815313, 0x3933b28b, 0x38f6a09a, 0x38a72a98, 0x385fd55c, 0x38140428, 0x37c15ba4,
    0x37797d70,
];

const ENCODE_THRESHOLD_BITS: [u32; 255] = [
    0x391f22b5, 0x39eeb40e, 0x3a46eb62, 0x3a8b3e5d, 0x3ab3070c, 0x3adacfb7, 0x3b014c33, 0x3b153089,
    0x3b2914e1, 0x3b3cf936, 0x3b50f2d1, 0x3b65fb9a, 0x3b7c3404, 0x3b89d060, 0x3b962333, 0x3ba314be,
    0x3bb0a733, 0x3bbedcb6, 0x3bcdb770, 0x3bdd3966, 0x3bed64b2, 0x3bfe3b44, 0x3c07df92, 0x3c10f919,
    0x3c1a6b35, 0x3c2436c7, 0x3c2e5cc9, 0x3c38de19, 0x3c43bba5, 0x3c4ef646, 0x3c5a8ee5, 0x3c668654,
    0x3c72dd73, 0x3c7f9512, 0x3c865703, 0x3c8d1490, 0x3c940396, 0x3c9b247c, 0x3ca277a8, 0x3ca9fd79,
    0x3cb1b654, 0x3cb9a299, 0x3cc1c2a9, 0x3cca16e3, 0x3cd29fa4, 0x3cdb5d4d, 0x3ce45034, 0x3ced78b6,
    0x3cf6d72f, 0x3d0035fc, 0x3d051bb6, 0x3d0a1cee, 0x3d0f39d1, 0x3d14728a, 0x3d19c745, 0x3d1f382b,
    0x3d24c56a, 0x3d2a6f24, 0x3d303586, 0x3d3618b9, 0x3d3c18e6, 0x3d423634, 0x3d4870cb, 0x3d4ec8d3,
    0x3d553e77, 0x3d5bd1d3, 0x3d62831c, 0x3d69526a, 0x3d703ff2, 0x3d774bce, 0x3d7e762b, 0x3d82df92,
    0x3d869376, 0x3d8a56cc, 0x3d8e29af, 0x3d920c28, 0x3d95fe52, 0x3d9a0036, 0x3d9e11ee, 0x3da23384,
    0x3da66512, 0x3daaa6a0, 0x3daef849, 0x3db35a17, 0x3db7cc1f, 0x3dbc4e6c, 0x3dc0e118, 0x3dc5842a,
    0x3dca37bd, 0x3dcefbd7, 0x3dd3d092, 0x3dd8b5f6, 0x3dddac1c, 0x3de2b30a, 0x3de7cadc, 0x3decf395,
    0x3df22d52, 0x3df7781a, 0x3dfcd401, 0x3e012088, 0x3e03dfb1, 0x3e06a77c, 0x3e0977f8, 0x3e0c5127,
    0x3e0f3316, 0x3e121dc6, 0x3e151145, 0x3e180d95, 0x3e1b12c4, 0x3e1e20d1, 0x3e2137cc, 0x3e2457b7,
    0x3e27809c, 0x3e2ab27c, 0x3e2ded6a, 0x3e313160, 0x3e347e73, 0x3e37d49d, 0x3e3b33ee, 0x3e3e9c68,
    0x3e420e18, 0x3e4588fa, 0x3e490d25, 0x3e4c9a8f, 0x3e50314f, 0x3e53d15c, 0x3e577acd, 0x3e5b2d99,
    0x3e5ee9d6, 0x3e62af7c, 0x3e667ea1, 0x3e6a5740, 0x3e6e3968, 0x3e722512, 0x3e761a58, 0x3e7a192d,
    0x3e7e21aa, 0x3e8119e2, 0x3e8327ca, 0x3e853a87, 0x3e875224, 0x3e896e9e, 0x3e8b8ffe, 0x3e8db641,
    0x3e8fe172, 0x3e92118b, 0x3e944698, 0x3e968094, 0x3e98bf8b, 0x3e9b0377, 0x3e9d4c63, 0x3e9f9a4b,
    0x3ea1ed3a, 0x3ea4452a, 0x3ea6a228, 0x3ea9042d, 0x3eab6b46, 0x3eadd76b, 0x3eb048ac, 0x3eb2bf01,
    0x3eb53a75, 0x3eb7bb01, 0x3eba40b4, 0x3ebccb86, 0x3ebf5b84, 0x3ec1f0a7, 0x3ec48afd, 0x3ec72a7d,
    0x3ec9cf35, 0x3ecc791e, 0x3ecf2845, 0x3ed1dca2, 0x3ed49644, 0x3ed75521, 0x3eda1948, 0x3edce2b1,
    0x3edfb16a, 0x3ee2856a, 0x3ee55ebf, 0x3ee83d62, 0x3eeb215f, 0x3eee0aaf, 0x3ef0f961, 0x3ef3ed69,
    0x3ef6e6d9, 0x3ef9e5a6, 0x3efce9e0, 0x3efff37f, 0x3f018147, 0x3f030b82, 0x3f049879, 0x3f062827,
    0x3f07ba94, 0x3f094fba, 0x3f0ae7a1, 0x3f0c8244, 0x3f0e1fac, 0x3f0fbfd2, 0x3f1162bf, 0x3f13086e,
    0x3f14b0e6, 0x3f165c22, 0x3f180a2a, 0x3f19baf9, 0x3f1b6e97, 0x3f1d24fe, 0x3f1ede37, 0x3f209a3b,
    0x3f225914, 0x3f241abb, 0x3f25df39, 0x3f27a688, 0x3f2970b0, 0x3f2b3dac, 0x3f2d0d84, 0x3f2ee033,
    0x3f30b5c0, 0x3f328e25, 0x3f34696b, 0x3f36478c, 0x3f382891, 0x3f3a0c73, 0x3f3bf33c, 0x3f3ddce5,
    0x3f3fc977, 0x3f41b8eb, 0x3f43ab4a, 0x3f45a08f, 0x3f4798c1, 0x3f4993da, 0x3f4b91e4, 0x3f4d92d8,
    0x3f4f96bf, 0x3f519d91, 0x3f53a75a, 0x3f55b410, 0x3f57c3bf, 0x3f59d65e, 0x3f5bebf8, 0x3f5e0485,
    0x3f60200f, 0x3f623e91, 0x3f64600f, 0x3f668486, 0x3f68abfe, 0x3f6ad671, 0x3f6d03e8, 0x3f6f345b,
    0x3f7167d5, 0x3f739e4d, 0x3f75d7cf, 0x3f781452, 0x3f7a53e0, 0x3f7c9671, 0x3f7edc11,
];


#[cfg(test)]
mod tests {
    use super::*;

    fn flat(w: usize, h: usize, v: u8) -> Vec<u8> {
        vec![v; w * h * 3]
    }

    #[test]
    fn rejects_bad_dimensions_without_allocating_output() {
        assert_eq!(correct(&[], 0, 4, Layout::Rgb), Err(ExposureError::Empty));
        assert_eq!(correct(&[0; 11], 2, 2, Layout::Rgb), Err(ExposureError::Length { expected: 12, actual: 11 }));
        assert_eq!(correct(&[], usize::MAX, 2, Layout::Rgb), Err(ExposureError::Overflow));
        assert_eq!(
            correct(&[], 6000, 4001, Layout::Rgb),
            Err(ExposureError::TooLarge { pixels: 24_006_000, max: MAX_PIXELS })
        );
    }

    #[test]
    fn white_page_is_a_clean_no_op() {
        let mut page = flat(320, 240, 255);
        for y in 50..55 {
            for x in 40..200 {
                page[(y * 320 + x) * 3..][..3].fill(20);
            }
        }
        let before = page.clone();
        let result = correct(&page, 320, 240, Layout::Rgb).unwrap();
        assert!(!result.diagnostics.applied);
        assert_eq!(result.diagnostics.gain, 1.0);
        assert!(result.pixels.is_none() && !result.changed);
        assert_eq!(page, before);
    }

    #[test]
    fn dark_page_gain_is_bounded_and_black_stays_black() {
        let mut page = flat(320, 240, 60);
        for y in 50..55 {
            for x in 40..200 {
                page[(y * 320 + x) * 3..][..3].fill(0);
            }
        }
        let result = correct(&page, 320, 240, Layout::Rgb).unwrap();
        let d = result.diagnostics;
        assert!(d.applied && d.gain > 1.0 && d.gain <= MAX_GAIN);
        let out = result.pixels.unwrap();
        assert_eq!(out.len(), page.len());
        assert_eq!(out[(52 * 320 + 100) * 3], 0);
        assert!(out[0] > 60);
    }

    #[test]
    fn rgba_matches_rgb_and_keeps_alpha() {
        let (w, h) = (700, 333);
        let rgb: Vec<u8> = (0..w * h * 3).map(|i| ((i * 7 + i / 977) % 90) as u8).collect();
        let rgba: Vec<u8> = rgb.chunks_exact(3).enumerate().flat_map(|(i, p)| [p[0], p[1], p[2], (i % 251) as u8]).collect();
        let a = correct(&rgb, w, h, Layout::Rgb).unwrap();
        let b = correct(&rgba, w, h, Layout::Rgba).unwrap();
        assert_eq!(a.diagnostics, b.diagnostics);
        let (pa, pb) = (a.pixels.unwrap(), b.pixels.unwrap());
        for (i, (x, y)) in pa.chunks_exact(3).zip(pb.chunks_exact(4)).enumerate() {
            assert_eq!(x, &y[..3]);
            assert_eq!(y[3], (i % 251) as u8);
        }
    }

    #[test]
    fn tables_agree_with_the_formulas() {
        for (c, &v) in linear_lut().iter().enumerate() {
            let x = c as f32 / 255.0;
            let f = if x <= 0.04045 { x / 12.92 } else { ((x + 0.055) / 1.055).powf(2.4) };
            assert!((f.to_bits() as i64 - v.to_bits() as i64).abs() <= 1, "code {c}");
        }
        let k = gaussian_kernel();
        let raw: Vec<f64> = (0..GAUSSIAN_TAPS).map(|i| (-0.5 * ((i as f64 - 36.0) / GAUSSIAN_SIGMA).powi(2)).exp()).collect();
        let total: f64 = raw.iter().sum();
        for (a, b) in k.iter().zip(&raw) {
            assert!((*a as f64 - b / total).abs() < 1e-7);
        }
        // Each threshold sits where the formula crosses k - 0.5.
        for (i, &t) in ENCODE_THRESHOLD_BITS.iter().enumerate() {
            let x = f32::from_bits(t) as f64;
            let v = if x <= 0.003_130_8 { 12.92 * x } else { 1.055 * x.powf(1.0 / 2.4) - 0.055 };
            assert!((255.0 * v - (i as f64 + 0.5)).abs() < 1e-3, "code {}", i + 1);
        }
        assert_eq!(encode(0.0), 0);
        assert_eq!(encode(1.0), 255);
        assert_eq!(encode(7.5), 255);
    }

    #[test]
    fn srgb_round_trips_every_code() {
        assert!(gain_table(1.0).iter().enumerate().all(|(c, &v)| v as usize == c));
    }

    #[test]
    fn thumbnail_rounds_ties_to_even() {
        assert_eq!(thumbnail_size(512, 100), (512, 100));
        assert_eq!(thumbnail_size(1024, 701), (512, 350));
        assert_eq!(thumbnail_size(595, 841), (362, 512));
        assert_eq!(thumbnail_size(100_000, 1), (512, 1));
    }

    #[test]
    fn deterministic() {
        let page: Vec<u8> = (0..1191 * 600 * 3).map(|i| ((i * 13) % 101) as u8).collect();
        assert_eq!(correct(&page, 1191, 600, Layout::Rgb), correct(&page, 1191, 600, Layout::Rgb));
    }

    #[test]
    fn percentile_matches_numpy_linear() {
        // numpy.percentile(np.arange(11, dtype=float32), [90]) == 9.0
        assert_eq!(percentile_linear((0..11).map(|v| v as f32).collect(), 0.9), 9.0);
        // numpy.percentile([0, 1, 2, 10], [90]) == 7.6 (index 2.7)
        let v = percentile_linear(vec![10.0, 0.0, 2.0, 1.0], 0.9);
        assert!((v - 7.6).abs() < 1e-12, "{v}");
        assert_eq!(percentile_linear(vec![0.25], 0.9), 0.25);
    }

    #[test]
    fn reflect101_matches_opencv() {
        assert_eq!(reflect101(-1, 5), 1);
        assert_eq!(reflect101(5, 5), 3);
        assert_eq!(reflect101(-36, 5), 4);
        assert_eq!(reflect101(-3, 1), 0);
    }
}
