//! Passive presentation-attack detection: Minivision's MiniFASNetV2 (2.7 ×
//! crop) and MiniFASNetV1SE (4.0 × crop), 80 × 80 BGR each, exported together
//! by `face/tools/export_minifasnet.py` (Apache-2.0 code and weights from
//! Silent-Face-Anti-Spoofing; trained on Minivision's own, unpublished data).
//!
//! The crops reproduce the original `CropImage`: the face box scaled about
//! its centre (the scale clamped so the crop fits the frame), shifted back
//! inside the frame, axis-aligned, resized to 80 × 80.
//!
//! Two choices were made on the CelebA-Spoof DEV split (`face/RESULTS.md`,
//! `docs/improvements-face.md`): the mesh's face box is shrunk to
//! [`BOX_SCALE`] of itself before the 2.7 × and 4.0 × crops (the models were
//! trained on a tighter detector box than the mesh's extent: AUC 0.858 →
//! 0.910), and the live probability is calibrated in log-odds so that 0.5
//! falls at raw [`RAW_THRESHOLD`], where the DEV BPCER is the uncalibrated
//! model's at 0.5 (10.6%): as many genuine faces rejected as before, a quarter
//! fewer attacks accepted. The liveness session decides at its own,
//! stricter operating point ([`SESSION_RAW_THRESHOLD`], the DEV equal-error
//! point), over several frames. CelebA-Spoof is non-commercial research
//! data: it chose these constants and trained nothing.

use anyhow::Context;
use rten::Model;
use rten_tensor::NdTensor;
use rten_tensor::prelude::*;
use serde::Serialize;

use super::image::{Affine, Frame, hwc_to_chw, warp_hwc};

const SIZE: usize = 80;

/// The mesh's face box is scaled by this before cropping.
pub const BOX_SCALE: f32 = 0.55;
/// The raw live probability (the two models' mean) that maps to 0.5.
pub const RAW_THRESHOLD: f32 = 0.59;
/// The raw live probability at the CelebA-Spoof DEV equal-error point: the
/// liveness session's default threshold (as a calibrated probability, see
/// [`session_threshold`]).
pub const SESSION_RAW_THRESHOLD: f32 = 0.78;

/// The calibrated probability the liveness session requires by default.
pub fn session_threshold() -> f32 {
    calibrate(SESSION_RAW_THRESHOLD, RAW_THRESHOLD)
}

pub struct AntiSpoof {
    model: Model,
    /// The face box from the mesh is scaled by this before cropping, to match
    /// the boxes the models were trained with ([`BOX_SCALE`]).
    pub box_scale: f32,
    /// The raw live probability that maps to 0.5 ([`RAW_THRESHOLD`]; 0.5: none).
    pub raw_threshold: f32,
}

fn logit(p: f32) -> f32 {
    let p = p.clamp(1e-6, 1.0 - 1e-6);
    (p / (1.0 - p)).ln()
}

/// The calibrated live probability: the raw one shifted in log-odds so that
/// `raw_threshold` becomes 0.5.
pub fn calibrate(raw: f32, raw_threshold: f32) -> f32 {
    1.0 / (1.0 + (-(logit(raw) - logit(raw_threshold))).exp())
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct SpoofScore {
    /// Calibrated probability of a live face (0.5 is the balanced decision).
    pub real: f32,
    /// The two spoof classes' share of the rest.
    pub print: f32,
    pub replay: f32,
    /// The uncalibrated live probability (the mean of the two models).
    pub raw_real: f32,
}

/// The original crop rectangle `[x0, y0, x1, y1]` for a box and scale.
fn crop_box(w: f32, h: f32, bbox: [f32; 4], scale: f32) -> [f32; 4] {
    let [x, y, bw, bh] = bbox;
    let scale = scale.min((h - 1.0) / bh).min((w - 1.0) / bw);
    let (nw, nh) = (bw * scale, bh * scale);
    let (cx, cy) = (x + bw / 2.0, y + bh / 2.0);
    let (mut x0, mut y0, mut x1, mut y1) = (cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0);
    if x0 < 0.0 {
        x1 -= x0;
        x0 = 0.0;
    }
    if y0 < 0.0 {
        y1 -= y0;
        y0 = 0.0;
    }
    if x1 > w - 1.0 {
        x0 -= x1 - w + 1.0;
        x1 = w - 1.0;
    }
    if y1 > h - 1.0 {
        y0 -= y1 - h + 1.0;
        y1 = h - 1.0;
    }
    [x0.floor(), y0.floor(), x1.floor(), y1.floor()]
}

impl AntiSpoof {
    pub fn load(bytes: Vec<u8>) -> anyhow::Result<AntiSpoof> {
        Ok(AntiSpoof { model: Model::load(bytes).context("loading the anti-spoofing model")?, box_scale: BOX_SCALE, raw_threshold: RAW_THRESHOLD })
    }

    fn crop(&self, frame: &Frame, bbox: [f32; 4], scale: f32) -> Vec<f32> {
        let [x0, y0, x1, y1] = crop_box(frame.width as f32, frame.height as f32, bbox, scale);
        // cv2.resize of the inclusive crop [x0, x1] × [y0, y1] to 80 × 80.
        let sx = (x1 - x0 + 1.0) / SIZE as f32;
        let sy = (y1 - y0 + 1.0) / SIZE as f32;
        let map = Affine([sx, 0.0, x0 + 0.5 * sx - 0.5, 0.0, sy, y0 + 0.5 * sy - 0.5]);
        let hwc = warp_hwc(frame, &map, SIZE, SIZE, 1.0, 0.0);
        hwc_to_chw(&hwc, SIZE, SIZE, true)
    }

    /// Scores the face in `bbox` (`[x, y, w, h]`, frame pixels).
    pub fn score(&self, frame: &Frame, bbox: [f32; 4]) -> anyhow::Result<SpoofScore> {
        let k = self.box_scale;
        let b = [bbox[0] + bbox[2] * (1.0 - k) / 2.0, bbox[1] + bbox[3] * (1.0 - k) / 2.0, bbox[2] * k, bbox[3] * k];
        let a = NdTensor::from_data([1, 3, SIZE, SIZE], self.crop(frame, b, 2.7));
        let c = NdTensor::from_data([1, 3, SIZE, SIZE], self.crop(frame, b, 4.0));
        let ia = self.model.node_id("crop27")?;
        let ic = self.model.node_id("crop40")?;
        let out = self.model.node_id("probs")?;
        let [p] = self.model.run_n(vec![(ia, a.into()), (ic, c.into())], [out], None)?;
        let p: rten_tensor::Tensor<f32> = p.try_into()?;
        let p = p.to_vec();
        let real = calibrate(p[1], self.raw_threshold);
        let spoof = (p[0] + p[2]).max(1e-12);
        Ok(SpoofScore { print: (1.0 - real) * p[0] / spoof, real, replay: (1.0 - real) * p[2] / spoof, raw_real: p[1] })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calibration_moves_the_threshold_to_one_half() {
        assert!((calibrate(RAW_THRESHOLD, RAW_THRESHOLD) - 0.5).abs() < 1e-6);
        assert!((calibrate(0.3, 0.5) - 0.3).abs() < 1e-5);
        assert!(calibrate(0.9, 0.78) > 0.5 && calibrate(0.7, 0.78) < 0.5);
        // The session's threshold is the raw equal-error point, calibrated.
        assert!((calibrate(SESSION_RAW_THRESHOLD, RAW_THRESHOLD) - session_threshold()).abs() < 1e-6);
        assert!(session_threshold() > 0.5);
    }
}
