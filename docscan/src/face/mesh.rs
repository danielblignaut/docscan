//! Dense landmarks: MediaPipe's Face Mesh V2 (the Face Landmarker's
//! landmark model; 256 × 256 input, 478 points with the irises; Apache-2.0),
//! run on a square crop rotated so the eyes are level, and tracked from one
//! frame's landmarks to the next without re-running the detector.

use anyhow::Context;
use rten::Model;
use rten_tensor::NdTensor;
use rten_tensor::prelude::*;
use serde::Serialize;

use super::detect::Detection;
use super::image::{Affine, Frame, warp_hwc};

const INPUT: usize = 256;
/// The crop is this many times the face's extent (MediaPipe's own margin).
const ROI_SCALE: f32 = 1.5;
pub const POINTS: usize = 478;

/// A rotated square region of the frame.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct Roi {
    pub cx: f32,
    pub cy: f32,
    pub side: f32,
    /// Radians: the crop's x axis is `(cos, sin)` in the frame.
    pub angle: f32,
}

#[derive(Debug, Clone)]
pub struct MeshResult {
    /// Frame pixels; z in the same units, smaller is nearer the camera.
    pub points: Vec<[f32; 3]>,
    /// The model's face-presence probability.
    pub presence: f32,
    pub roi: Roi,
}

pub struct Mesh {
    model: Model,
}

/// Indices into the 478 points.
pub mod idx {
    /// The subject's right eye (the image's left): outer and inner corners.
    pub const RIGHT_EYE_OUTER: usize = 33;
    pub const RIGHT_EYE_INNER: usize = 133;
    pub const LEFT_EYE_OUTER: usize = 263;
    pub const LEFT_EYE_INNER: usize = 362;
    pub const NOSE_TIP: usize = 1;
    pub const MOUTH_RIGHT: usize = 61;
    pub const MOUTH_LEFT: usize = 291;
    pub const FOREHEAD: usize = 10;
    pub const CHIN: usize = 152;
    pub const RIGHT_CHEEK: usize = 234;
    pub const LEFT_CHEEK: usize = 454;
    /// Iris centres (the 478-point model only).
    pub const RIGHT_IRIS: usize = 468;
    pub const LEFT_IRIS: usize = 473;
    /// Eye-aspect-ratio points: corners, then two upper/lower pairs.
    pub const RIGHT_EAR: [usize; 6] = [33, 133, 160, 144, 158, 153];
    pub const LEFT_EAR: [usize; 6] = [263, 362, 387, 373, 385, 380];
}

impl Mesh {
    pub fn load(bytes: Vec<u8>) -> anyhow::Result<Mesh> {
        Ok(Mesh { model: Model::load(bytes).context("loading the face mesh model")? })
    }

    pub fn run(&self, frame: &Frame, roi: Roi) -> anyhow::Result<MeshResult> {
        let map = Affine::square(roi.cx, roi.cy, roi.side, roi.angle, INPUT);
        let input = warp_hwc(frame, &map, INPUT, INPUT, 1.0 / 255.0, 0.0);
        let input = NdTensor::from_data([1, INPUT, INPUT, 3], input);
        let input_id = self.model.input_ids()[0];
        let outputs = self.model.output_ids().to_vec();
        let out = self.model.run(vec![(input_id, input.into())], &outputs, None)?;
        // Outputs: the landmarks [1,1,1,1434], the presence logit [1,1,1,1], and a third unused one.
        let mut landmarks: Option<Vec<f32>> = None;
        let mut presence = 0.0;
        for o in out {
            let t: rten_tensor::Tensor<f32> = o.try_into()?;
            if t.len() == POINTS * 3 {
                landmarks = Some(t.to_vec());
            } else if t.len() == 1 && landmarks.is_some() && presence == 0.0 {
                presence = 1.0 / (1.0 + (-t.to_vec()[0]).exp());
            }
        }
        let lm = landmarks.context("face mesh: no landmark output")?;
        // Crop pixel (u, v) is the centre of output pixel u - 0.5.
        let k = roi.side / INPUT as f32;
        let points = lm
            .chunks_exact(3)
            .map(|p| {
                let (x, y) = map.apply(p[0] - 0.5, p[1] - 0.5);
                [x, y, p[2] * k]
            })
            .collect();
        Ok(MeshResult { points, presence, roi })
    }
}

/// The landmark crop for a detection: centred on the box, rotated so the
/// eyes are level, 1.5 × the box's longer side.
pub fn roi_from_detection(d: &Detection) -> Roi {
    let [re, le] = [d.keypoints[0], d.keypoints[1]];
    let angle = (le[1] - re[1]).atan2(le[0] - re[0]);
    Roi { cx: d.bbox[0] + d.bbox[2] / 2.0, cy: d.bbox[1] + d.bbox[3] / 2.0, side: d.bbox[2].max(d.bbox[3]) * ROI_SCALE, angle }
}

/// The next frame's crop from this frame's landmarks: their extent in the
/// eye-levelled frame, 1.5 ×.
pub fn roi_from_points(points: &[[f32; 3]]) -> Roi {
    let re = points[idx::RIGHT_EYE_OUTER];
    let le = points[idx::LEFT_EYE_OUTER];
    let angle = (le[1] - re[1]).atan2(le[0] - re[0]);
    let (s, c) = angle.sin_cos();
    let (mut x0, mut y0, mut x1, mut y1) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for p in &points[..468.min(points.len())] {
        let u = c * p[0] + s * p[1];
        let v = -s * p[0] + c * p[1];
        x0 = x0.min(u);
        x1 = x1.max(u);
        y0 = y0.min(v);
        y1 = y1.max(v);
    }
    let (uc, vc) = ((x0 + x1) / 2.0, (y0 + y1) / 2.0);
    Roi { cx: c * uc - s * vc, cy: s * uc + c * vc, side: (x1 - x0).max(y1 - y0) * ROI_SCALE, angle }
}

/// The centre of a set of points (x, y).
pub fn centre(points: &[[f32; 3]], ids: &[usize]) -> [f32; 2] {
    let n = ids.len() as f32;
    let x = ids.iter().map(|&i| points[i][0]).sum::<f32>() / n;
    let y = ids.iter().map(|&i| points[i][1]).sum::<f32>() / n;
    [x, y]
}

fn dist(a: [f32; 3], b: [f32; 3]) -> f32 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2)).sqrt()
}

/// The eye aspect ratio (Soukupová and Čech, 2016): the mean of the two
/// lid-to-lid distances over the corner-to-corner width. About 0.25–0.35
/// open, under ~0.15 closed.
pub fn eye_aspect_ratio(points: &[[f32; 3]], ids: [usize; 6]) -> f32 {
    let p = |i: usize| points[ids[i]];
    let width = dist(p(0), p(1)).max(1e-3);
    (dist(p(2), p(3)) + dist(p(4), p(5))) / (2.0 * width)
}

/// The two pupils (iris centres) when the model has them, else the eye centres.
pub fn eye_centres(points: &[[f32; 3]]) -> ([f32; 2], [f32; 2]) {
    if points.len() > idx::LEFT_IRIS {
        let r = points[idx::RIGHT_IRIS];
        let l = points[idx::LEFT_IRIS];
        ([r[0], r[1]], [l[0], l[1]])
    } else {
        (centre(points, &idx::RIGHT_EAR), centre(points, &idx::LEFT_EAR))
    }
}

/// Distance between the pupils, in frame pixels: the face's scale.
pub fn interocular(points: &[[f32; 3]]) -> f32 {
    let (r, l) = eye_centres(points);
    ((r[0] - l[0]).powi(2) + (r[1] - l[1]).powi(2)).sqrt()
}

/// Axis-aligned extent of the face mesh, `[x, y, w, h]`.
pub fn bbox(points: &[[f32; 3]]) -> [f32; 4] {
    let (mut x0, mut y0, mut x1, mut y1) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for p in &points[..468.min(points.len())] {
        x0 = x0.min(p[0]);
        x1 = x1.max(p[0]);
        y0 = y0.min(p[1]);
        y1 = y1.max(p[1]);
    }
    [x0, y0, x1 - x0, y1 - y0]
}
