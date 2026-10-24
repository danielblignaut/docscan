//! Descriptive pixel evidence, deliberately separate from document acceptance.
//!
//! A single decoded frame cannot establish that a physical document is an
//! original, and colour/texture statistics are not validated copy detectors.
//! `assess_pixels` therefore always abstains. No score here is a probability of
//! authenticity or tampering. See `docs/document-originality.md` for the scope,
//! rejected detector experiment and integration contract.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CopyStatus {
    Unknown,
    /// Reserved for a future independently validated source of copy evidence.
    CopyIndicated,
    /// Reserved; neither a camera frame nor absence of artifacts warrants this.
    OriginalIndicated,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CopyAssessment {
    pub status: CopyStatus,
    /// None means unassessed/indeterminate, never shorthand for false.
    pub is_copy: Option<bool>,
    /// None until a defined target and independent calibration are available.
    pub confidence: Option<f32>,
    pub signals: Vec<CopySignal>,
    pub limitations: Vec<CopyLimitation>,
}

/// All signals are observations, not warnings, decision scores or probabilities.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CopySignal {
    pub code: CopySignalCode,
    pub value: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CopySignalCode {
    /// Number of grid samples, including nonopaque ones; at most 4096.
    SampledPixelCount,
    /// Fraction of grid samples with alpha != 255, in [0, 1].
    SampledNonopaqueFraction,
    /// Opaque-sample mean of max(R,G,B)-min(R,G,B), in byte levels [0, 255].
    MeanRgbRange,
    /// Opaque-sample fraction with RGB range <= 8, in [0, 1]. This describes
    /// near-neutral colour, not photocopying: white paper also contributes.
    NearAchromaticFraction,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CopyLimitation {
    NoValidatedCopyDetector,
    PixelsDoNotEstablishPhysicalOriginal,
    MetadataUnavailableFromPixels,
    TamperingNotAssessed,
    InvalidRgbaDimensionsOrLength,
    SpatialSamplingMayMissLocalEvidence,
    NonopaqueSamplesExcludedFromColour,
    NoOpaqueSamples,
}

impl Default for CopyAssessment {
    fn default() -> Self {
        Self {
            status: CopyStatus::Unknown,
            is_copy: None,
            confidence: None,
            signals: Vec::new(),
            limitations: vec![
                CopyLimitation::NoValidatedCopyDetector,
                CopyLimitation::PixelsDoNotEstablishPhysicalOriginal,
                CopyLimitation::MetadataUnavailableFromPixels,
                CopyLimitation::TamperingNotAssessed,
            ],
        }
    }
}

/// Inspect tightly packed, 8-bit RGBA without I/O, weights or image-sized
/// allocations. At most 64 samples per axis (4096 total), spanning the frame.
/// Colour statistics exclude nonopaque samples rather than interpreting hidden
/// RGB or making an assumption about compositing/premultiplied alpha.
///
/// Empty dimensions, arithmetic overflow and *any* length mismatch return an
/// unknown assessment with no signals and an explicit invalid-input limitation.
/// Valid inputs also return unknown: none of these statistics establishes copy
/// status. Missing signals and null confidence must remain missing/null in UIs.
pub fn assess_pixels(rgba: &[u8], w: usize, h: usize) -> CopyAssessment {
    let mut result = CopyAssessment::default();
    let expected = w.checked_mul(h).and_then(|n| n.checked_mul(4));
    if w == 0 || h == 0 || expected != Some(rgba.len()) {
        result
            .limitations
            .push(CopyLimitation::InvalidRgbaDimensionsOrLength);
        return result;
    }

    let (nx, ny) = (w.min(64), h.min(64));
    let mut nonopaque = 0u32;
    let mut rgb_range_sum = 0u32;
    let mut neutral = 0u32;
    for iy in 0..ny {
        let y = sample_coordinate(iy, ny, h);
        for ix in 0..nx {
            let x = sample_coordinate(ix, nx, w);
            let offset = (y * w + x) * 4;
            let p = &rgba[offset..offset + 4];
            if p[3] != 255 {
                nonopaque += 1;
                continue;
            }
            let range = p[0].max(p[1]).max(p[2]) - p[0].min(p[1]).min(p[2]);
            rgb_range_sum += u32::from(range);
            neutral += u32::from(range <= 8);
        }
    }
    let count = (nx * ny) as u32;
    result.signals.push(CopySignal {
        code: CopySignalCode::SampledPixelCount,
        value: count as f32,
    });
    result.signals.push(CopySignal {
        code: CopySignalCode::SampledNonopaqueFraction,
        value: nonopaque as f32 / count as f32,
    });
    let opaque = count - nonopaque;
    if opaque > 0 {
        result.signals.push(CopySignal {
            code: CopySignalCode::MeanRgbRange,
            value: rgb_range_sum as f32 / opaque as f32,
        });
        result.signals.push(CopySignal {
            code: CopySignalCode::NearAchromaticFraction,
            value: neutral as f32 / opaque as f32,
        });
    } else {
        result.limitations.push(CopyLimitation::NoOpaqueSamples);
    }
    if nonopaque > 0 {
        result
            .limitations
            .push(CopyLimitation::NonopaqueSamplesExcludedFromColour);
    }
    if nx < w || ny < h {
        result
            .limitations
            .push(CopyLimitation::SpatialSamplingMayMissLocalEvidence);
    }
    result
}

// floor(i * (length - 1) / (count - 1)), without overflowing the product.
fn sample_coordinate(i: usize, count: usize, length: usize) -> usize {
    if count == 1 {
        return 0;
    }
    let end = length - 1;
    let denominator = count - 1;
    i * (end / denominator) + i * (end % denominator) / denominator
}

#[cfg(test)]
mod tests {
    use super::*;

    fn signal(a: &CopyAssessment, code: CopySignalCode) -> Option<f32> {
        a.signals.iter().find(|s| s.code == code).map(|s| s.value)
    }

    fn assert_unknown(a: &CopyAssessment) {
        assert_eq!(a.status, CopyStatus::Unknown);
        assert_eq!(a.is_copy, None);
        assert_eq!(a.confidence, None);
        assert!(
            a.limitations
                .contains(&CopyLimitation::TamperingNotAssessed)
        );
        assert!(a.signals.iter().all(|s| s.value.is_finite()));
    }

    #[test]
    fn invalid_buffers_are_unknown_without_measurements() {
        for (bytes, w, h) in [
            (&[][..], 0, 0),
            (&[][..], 0, 1),
            (&[][..], 1, 0),
            (&[][..], 1, 1),
            (&[0; 3][..], 1, 1),
            (&[0; 5][..], 1, 1),
            (&[][..], usize::MAX, 2),
            (&[][..], usize::MAX / 4 + 1, 1),
        ] {
            let a = assess_pixels(bytes, w, h);
            assert_unknown(&a);
            assert!(a.signals.is_empty());
            assert!(
                a.limitations
                    .contains(&CopyLimitation::InvalidRgbaDimensionsOrLength)
            );
        }
    }

    #[test]
    fn grey_and_colour_are_measurements_not_copy_decisions() {
        for rgb in [[0, 0, 0], [255, 255, 255], [128, 128, 128], [255, 0, 0]] {
            let a = assess_pixels(&[rgb[0], rgb[1], rgb[2], 255], 1, 1);
            assert_unknown(&a);
            let range = rgb.iter().max().unwrap() - rgb.iter().min().unwrap();
            assert_eq!(signal(&a, CopySignalCode::MeanRgbRange), Some(range as f32));
            assert_eq!(
                signal(&a, CopySignalCode::NearAchromaticFraction),
                Some(if range <= 8 { 1.0 } else { 0.0 })
            );
        }
    }

    #[test]
    fn neutral_tolerance_is_in_byte_levels() {
        let a = assess_pixels(&[100, 108, 100, 255, 100, 109, 100, 255], 2, 1);
        assert_eq!(signal(&a, CopySignalCode::MeanRgbRange), Some(8.5));
        assert_eq!(
            signal(&a, CopySignalCode::NearAchromaticFraction),
            Some(0.5)
        );
    }

    #[test]
    fn hidden_and_partial_alpha_rgb_never_bias_colour() {
        let a = assess_pixels(&[255, 0, 0, 0, 255, 0, 0, 254, 20, 20, 20, 255], 3, 1);
        assert_unknown(&a);
        assert_eq!(signal(&a, CopySignalCode::MeanRgbRange), Some(0.0));
        assert_eq!(
            signal(&a, CopySignalCode::SampledNonopaqueFraction),
            Some(2.0 / 3.0)
        );
        let empty = assess_pixels(&[255, 0, 0, 0], 1, 1);
        assert_unknown(&empty);
        assert_eq!(signal(&empty, CopySignalCode::NearAchromaticFraction), None);
        assert!(empty.limitations.contains(&CopyLimitation::NoOpaqueSamples));
    }

    #[test]
    fn sampling_is_bounded_even_on_thin_images() {
        for (w, h) in [(1, 10000), (10000, 1), (65, 65), (512, 512)] {
            let a = assess_pixels(&[128, 128, 128, 255].repeat(w * h), w, h);
            assert_unknown(&a);
            assert_eq!(
                signal(&a, CopySignalCode::SampledPixelCount),
                Some((w.min(64) * h.min(64)) as f32)
            );
            assert!(
                a.limitations
                    .contains(&CopyLimitation::SpatialSamplingMayMissLocalEvidence)
            );
        }
    }

    #[test]
    fn sampling_spans_endpoints_without_overflow() {
        for length in [1, 2, 63, 64, 65, 1000, usize::MAX] {
            let count = length.min(64);
            assert_eq!(sample_coordinate(0, count, length), 0);
            assert_eq!(sample_coordinate(count - 1, count, length), length - 1);
            for i in 0..count {
                assert!(sample_coordinate(i, count, length) < length);
            }
        }
    }

    #[test]
    fn wire_format_preserves_unknown_and_nulls() {
        let a = assess_pixels(&[255, 255, 255, 255], 1, 1);
        let json = serde_json::to_value(a).unwrap();
        assert_eq!(json["status"], "unknown");
        assert!(json["is_copy"].is_null());
        assert!(json["confidence"].is_null());
        assert_eq!(json["signals"][0]["code"], "sampled_pixel_count");
        assert_eq!(
            serde_json::to_value(CopyStatus::CopyIndicated).unwrap(),
            "copy_indicated"
        );
        assert_eq!(
            serde_json::to_value(CopyStatus::OriginalIndicated).unwrap(),
            "original_indicated"
        );
    }
}
