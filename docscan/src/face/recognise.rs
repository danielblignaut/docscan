//! Face templates: the face aligned onto the ArcFace five-point template
//! (112 × 112) by a similarity transform, then embedded by a recognition
//! model and L2-normalised. Two templates are compared by cosine similarity.
//!
//! The model is a choice (`face/MODELS.md` lists the ones benchmarked and
//! their licences); each needs its own input convention.

use anyhow::Context;
use rten::Model;
use rten_tensor::NdTensor;
use rten_tensor::prelude::*;
use serde::{Deserialize, Serialize};

use super::image::{Affine, Frame, hwc_to_chw, warp_hwc};
use super::linalg::similarity_2d;
use super::mesh::{eye_centres, idx};

pub const SIZE: usize = 112;

/// The ArcFace template: the subject's right eye, left eye, nose tip, right
/// and left mouth corners, in the 112 × 112 crop.
pub const TEMPLATE: [[f32; 2]; 5] = [
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
];

/// How a model wants its 112 × 112 input.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InputKind {
    /// RGB, `(x - 127.5) / 127.5`, NCHW: InsightFace's ArcFace models, EdgeFace.
    Arcface,
    /// RGB, 0–255, NCHW: OpenCV's SFace.
    Sface,
    /// RGB, `(x - 127.5) / 128`, NCHW: FaceNet (facenet-pytorch).
    Facenet,
}

impl InputKind {
    pub fn parse(s: &str) -> anyhow::Result<InputKind> {
        Ok(match s {
            "arcface" | "" => InputKind::Arcface,
            "sface" => InputKind::Sface,
            "facenet" => InputKind::Facenet,
            other => anyhow::bail!("unknown recogniser input kind {other:?}"),
        })
    }
}

pub struct Recogniser {
    model: Model,
    pub kind: InputKind,
    /// Input side: 112, or 160 for FaceNet (the template scaled to it).
    pub size: usize,
}

/// The five alignment points from the dense landmarks: the pupils (iris
/// centres), the nose tip and the outer mouth corners.
pub fn five_points(points: &[[f32; 3]]) -> [[f32; 2]; 5] {
    five_points_with(points, Alignment::Iris)
}

/// Which mesh points stand for the template's five (compared on the LFW DEV
/// split; `face/RESULTS.md`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Alignment {
    /// Iris centres, nose tip (1), outer mouth corners (61, 291).
    Iris,
    /// Eye-contour centres instead of the irises.
    EyeContour,
    /// Iris centres, the nose's lower tip (4), outer mouth corners.
    Nose4,
    /// Iris centres, nose tip, inner mouth corners (78, 308).
    InnerMouth,
}

impl Alignment {
    pub fn parse(s: &str) -> Option<Alignment> {
        Some(match s {
            "iris" => Alignment::Iris,
            "contour" => Alignment::EyeContour,
            "nose4" => Alignment::Nose4,
            "inner-mouth" => Alignment::InnerMouth,
            _ => return None,
        })
    }
}

pub fn five_points_with(points: &[[f32; 3]], a: Alignment) -> [[f32; 2]; 5] {
    let p = |i: usize| [points[i][0], points[i][1]];
    let (re, le) = match a {
        Alignment::EyeContour => (super::mesh::centre(points, &idx::RIGHT_EAR), super::mesh::centre(points, &idx::LEFT_EAR)),
        _ => eye_centres(points),
    };
    let nose = if a == Alignment::Nose4 { p(4) } else { p(idx::NOSE_TIP) };
    let (mr, ml) = if a == Alignment::InnerMouth { (p(78), p(308)) } else { (p(idx::MOUTH_RIGHT), p(idx::MOUTH_LEFT)) };
    [re, le, nose, mr, ml]
}

/// The map from the 112 × 112 crop to the frame that puts `five` on the template.
pub fn alignment(five: &[[f32; 2]; 5]) -> Affine {
    alignment_sized(five, SIZE)
}

/// The same alignment for a `size × size` crop (the template scaled).
pub fn alignment_sized(five: &[[f32; 2]; 5], size: usize) -> Affine {
    let k = size as f32 / SIZE as f32;
    let template = TEMPLATE.map(|p| [p[0] * k, p[1] * k]);
    // Template (crop pixel centres) → frame.
    let m = similarity_2d(&template, five);
    // Output pixel u's centre is at crop coordinate u + 0.5 in the template's
    // pixel-corner convention (InsightFace warps with cv2, pixel centres at
    // integers): keep integers as centres.
    Affine(m)
}

impl Recogniser {
    pub fn load(bytes: Vec<u8>, kind: InputKind) -> anyhow::Result<Recogniser> {
        let model = Model::load(bytes).context("loading the recognition model")?;
        let size = if kind == InputKind::Facenet { 160 } else { SIZE };
        Ok(Recogniser { model, kind, size })
    }

    /// The aligned face as RGB floats (HWC, 0–255), `size × size`.
    pub fn aligned(&self, frame: &Frame, five: &[[f32; 2]; 5]) -> Vec<f32> {
        warp_hwc(frame, &alignment_sized(five, self.size), self.size, self.size, 1.0, 0.0)
    }

    /// The unit-length template of an aligned face (HWC, 0–255, `size × size`).
    pub fn embed_aligned(&self, hwc: &[f32]) -> anyhow::Result<Vec<f32>> {
        let (scale, offset) = match self.kind {
            InputKind::Arcface => (1.0 / 127.5, -1.0),
            InputKind::Sface => (1.0, 0.0),
            InputKind::Facenet => (1.0 / 128.0, -127.5 / 128.0),
        };
        let norm: Vec<f32> = hwc.iter().map(|v| v * scale + offset).collect();
        let n = self.size;
        let chw = hwc_to_chw(&norm, n, n, false);
        let input = NdTensor::from_data([1, 3, n, n], chw);
        let input_id = self.model.input_ids()[0];
        let output_id = self.model.output_ids()[0];
        let [out] = self.model.run_n(vec![(input_id, input.into())], [output_id], None)?;
        let out: rten_tensor::Tensor<f32> = out.try_into()?;
        let mut v = out.to_vec();
        let n = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-12);
        for x in v.iter_mut() {
            *x /= n;
        }
        Ok(v)
    }

    /// The template of the face with these landmarks, with the flipped
    /// crop's added in when `flip` (a common test-time augmentation).
    pub fn embed(&self, frame: &Frame, five: &[[f32; 2]; 5], flip: bool) -> anyhow::Result<Vec<f32>> {
        let hwc = self.aligned(frame, five);
        let mut v = self.embed_aligned(&hwc)?;
        if flip {
            let f = flip_hwc(&hwc, self.size, self.size);
            let w = self.embed_aligned(&f)?;
            for (a, b) in v.iter_mut().zip(w) {
                *a += b;
            }
            let n = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-12);
            for x in v.iter_mut() {
                *x /= n;
            }
        }
        Ok(v)
    }
}

pub fn flip_hwc(hwc: &[f32], w: usize, h: usize) -> Vec<f32> {
    let mut out = vec![0f32; hwc.len()];
    for y in 0..h {
        for x in 0..w {
            for k in 0..3 {
                out[(y * w + x) * 3 + k] = hwc[(y * w + (w - 1 - x)) * 3 + k];
            }
        }
    }
    out
}

/// Cosine similarity of two templates (both unit length: the dot product).
pub fn similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let na = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let nb = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    dot / (na * nb).max(1e-12)
}
