//! Face detection: MediaPipe's BlazeFace short-range model (128 × 128 input,
//! 896 anchors, a box and six keypoints per face; Apache-2.0), converted to
//! ONNX with tf2onnx and run on rten.

use anyhow::Context;
use rten::Model;
use rten_tensor::prelude::*;
use rten_tensor::{NdTensor, NdTensorView};
use serde::Serialize;

use super::image::{Affine, Frame, warp_hwc};

const INPUT: usize = 128;
const MIN_SCORE: f32 = 0.5;
const NMS_IOU: f32 = 0.3;

/// A detected face in frame pixels.
#[derive(Debug, Clone, Serialize)]
pub struct Detection {
    pub score: f32,
    /// `[x, y, width, height]`.
    pub bbox: [f32; 4],
    /// The subject's right eye, left eye, nose tip, mouth, right ear tragion,
    /// left ear tragion (MediaPipe's order; "right" is the image's left).
    pub keypoints: [[f32; 2]; 6],
}

pub struct Detector {
    model: Model,
    anchors: Vec<[f32; 2]>,
}

/// SSD anchors of the short-range model: strides 8 (2 per cell) and 16 (6 per
/// cell), centred, unit size.
fn anchors() -> Vec<[f32; 2]> {
    let mut out = Vec::with_capacity(896);
    for (stride, per_cell) in [(8usize, 2usize), (16, 6)] {
        let g = INPUT / stride;
        for y in 0..g {
            for x in 0..g {
                for _ in 0..per_cell {
                    out.push([(x as f32 + 0.5) / g as f32, (y as f32 + 0.5) / g as f32]);
                }
            }
        }
    }
    out
}

fn iou(a: &[f32; 4], b: &[f32; 4]) -> f32 {
    let x0 = a[0].max(b[0]);
    let y0 = a[1].max(b[1]);
    let x1 = (a[0] + a[2]).min(b[0] + b[2]);
    let y1 = (a[1] + a[3]).min(b[1] + b[3]);
    let inter = (x1 - x0).max(0.0) * (y1 - y0).max(0.0);
    let union = a[2] * a[3] + b[2] * b[3] - inter;
    if union > 0.0 { inter / union } else { 0.0 }
}

impl Detector {
    pub fn load(bytes: Vec<u8>) -> anyhow::Result<Detector> {
        let model = Model::load(bytes).context("loading the face detector")?;
        Ok(Detector { model, anchors: anchors() })
    }

    /// Every face in the frame, the frame letterboxed into the square input.
    pub fn detect(&self, frame: &Frame) -> anyhow::Result<Vec<Detection>> {
        let side = frame.width.max(frame.height) as f32;
        let cx = frame.width as f32 / 2.0;
        let cy = frame.height as f32 / 2.0;
        self.detect_square(frame, cx, cy, side)
    }

    /// Faces in a square region of the frame (centre and side in pixels).
    pub fn detect_square(&self, frame: &Frame, cx: f32, cy: f32, side: f32) -> anyhow::Result<Vec<Detection>> {
        let map = Affine::square(cx, cy, side, 0.0, INPUT);
        // [-1, 1], NHWC.
        let input = warp_hwc(frame, &map, INPUT, INPUT, 1.0 / 127.5, -1.0);
        let input = NdTensor::from_data([1, INPUT, INPUT, 3], input);
        let input_id = self.model.input_ids()[0];
        let regressors = self.model.node_id("regressors")?;
        let classificators = self.model.node_id("classificators")?;
        let [reg, cls] = self.model.run_n(vec![(input_id, input.into())], [regressors, classificators], None)?;
        let reg: NdTensor<f32, 3> = reg.try_into()?;
        let cls: NdTensor<f32, 3> = cls.try_into()?;
        let reg: NdTensorView<f32, 3> = reg.view();
        let x0 = cx - side / 2.0;
        let y0 = cy - side / 2.0;
        let mut raw = Vec::new();
        for (i, a) in self.anchors.iter().enumerate() {
            let logit = cls[[0, i, 0]].clamp(-100.0, 100.0);
            let score = 1.0 / (1.0 + (-logit).exp());
            if score < MIN_SCORE {
                continue;
            }
            let r = |k: usize| reg[[0, i, k]] / INPUT as f32;
            let (xc, yc, w, h) = (r(0) + a[0], r(1) + a[1], r(2), r(3));
            let mut kps = [[0f32; 2]; 6];
            for (k, kp) in kps.iter_mut().enumerate() {
                *kp = [x0 + (r(4 + 2 * k) + a[0]) * side, y0 + (r(5 + 2 * k) + a[1]) * side];
            }
            raw.push(Detection { score, bbox: [x0 + (xc - w / 2.0) * side, y0 + (yc - h / 2.0) * side, w * side, h * side], keypoints: kps });
        }
        Ok(weighted_nms(raw))
    }
}

/// MediaPipe's weighted non-maximum suppression: each kept face is the
/// score-weighted mean of the boxes that overlap it.
fn weighted_nms(mut dets: Vec<Detection>) -> Vec<Detection> {
    dets.sort_by(|a, b| b.score.total_cmp(&a.score));
    let mut out = Vec::new();
    let mut used = vec![false; dets.len()];
    for i in 0..dets.len() {
        if used[i] {
            continue;
        }
        let mut total = 0f32;
        let mut bbox = [0f32; 4];
        let mut kps = [[0f32; 2]; 6];
        for j in i..dets.len() {
            if used[j] || iou(&dets[i].bbox, &dets[j].bbox) < NMS_IOU {
                continue;
            }
            used[j] = true;
            let w = dets[j].score;
            total += w;
            for k in 0..4 {
                bbox[k] += dets[j].bbox[k] * w;
            }
            for k in 0..6 {
                kps[k][0] += dets[j].keypoints[k][0] * w;
                kps[k][1] += dets[j].keypoints[k][1] * w;
            }
        }
        for v in bbox.iter_mut() {
            *v /= total;
        }
        for kp in kps.iter_mut() {
            kp[0] /= total;
            kp[1] /= total;
        }
        out.push(Detection { score: dets[i].score, bbox, keypoints: kps });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn anchor_count() {
        assert_eq!(anchors().len(), 896);
    }
}
