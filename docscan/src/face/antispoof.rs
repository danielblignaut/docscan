//! Passive presentation-attack detection: Minivision's MiniFASNetV2 (2.7 ×
//! crop) and MiniFASNetV1SE (4.0 × crop), 80 × 80 BGR each, exported together
//! by `face/tools/export_minifasnet.py` (Apache-2.0 code and weights from
//! Silent-Face-Anti-Spoofing; trained on Minivision's own, unpublished data).
//!
//! The crops reproduce the original `CropImage`: the face box scaled about
//! its centre (the scale clamped so the crop fits the frame), shifted back
//! inside the frame, axis-aligned, resized to 80 × 80.

use anyhow::Context;
use rten::Model;
use rten_tensor::NdTensor;
use rten_tensor::prelude::*;
use serde::Serialize;

use super::image::{Affine, Frame, hwc_to_chw, warp_hwc};

const SIZE: usize = 80;

pub struct AntiSpoof {
    model: Model,
    /// The face box from the mesh is scaled by this before cropping, to match
    /// the RetinaFace boxes the models were trained with (tuned on DEV).
    pub box_scale: f32,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct SpoofScore {
    /// Probability of a live face (the mean of the two models).
    pub real: f32,
    pub print: f32,
    pub replay: f32,
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
        Ok(AntiSpoof { model: Model::load(bytes).context("loading the anti-spoofing model")?, box_scale: 1.0 })
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
        Ok(SpoofScore { print: p[0], real: p[1], replay: p[2] })
    }
}
