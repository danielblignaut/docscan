//! Face image quality: the individual, explainable measures that decide
//! whether a frame (or a document photo) is good enough to enrol or match,
//! in the spirit of ISO/IEC 29794-5 (OFIQ) but computed from the landmarks
//! and pixels already at hand: size, pose, exposure, evenness of light,
//! sharpness and open eyes.

use serde::Serialize;

use super::image::{Frame, laplacian_variance, luma_hwc};
use super::mesh::{eye_aspect_ratio, idx, interocular};
use super::pose::Pose;

#[derive(Debug, Clone, Serialize, Default)]
pub struct FaceQuality {
    /// Pixels between the pupils.
    pub interocular_px: f32,
    /// Mean luma of the inner face, 0–255.
    pub brightness: f32,
    /// The darker cheek's luma over the lighter's (1 = evenly lit).
    pub evenness: f32,
    /// Share of the inner face that is blown out (luma ≥ 250).
    pub saturated: f32,
    /// Laplacian variance of the aligned 112 × 112 face.
    pub sharpness: f32,
    /// Mean eye aspect ratio of the two eyes.
    pub eyes_open: f32,
    /// Degrees off frontal: the larger of |yaw| and |pitch|.
    pub off_frontal: f32,
    pub roll: f32,
    /// 0–1, the product of each measure's own 0–1 score.
    pub score: f32,
    /// What is wrong, worst first, in words for a hint.
    pub problems: Vec<&'static str>,
}

pub const MIN_IOD_PX: f32 = 28.0;
pub const SHARPNESS_MIN: f32 = 60.0;

fn ramp(x: f32, lo: f32, hi: f32) -> f32 {
    ((x - lo) / (hi - lo)).clamp(0.0, 1.0)
}

/// Mean luma over a polygon-free proxy of the inner face: a grid of samples
/// between the eyes and the mouth, and each cheek's own mean.
fn face_light(frame: &Frame, points: &[[f32; 3]]) -> (f32, f32, f32) {
    let sample_region = |ids: &[usize]| -> (f32, f32) {
        let (mut sum, mut sat, mut n) = (0f32, 0f32, 0f32);
        for &a in ids {
            for &b in ids {
                if a >= b {
                    continue;
                }
                for t in [0.25f32, 0.5, 0.75] {
                    let x = points[a][0] + (points[b][0] - points[a][0]) * t;
                    let y = points[a][1] + (points[b][1] - points[a][1]) * t;
                    if x < 0.0 || y < 0.0 || x >= frame.width as f32 || y >= frame.height as f32 {
                        continue;
                    }
                    let l = frame.luma_at(x as usize, y as usize);
                    sum += l;
                    sat += if l >= 250.0 { 1.0 } else { 0.0 };
                    n += 1.0;
                }
            }
        }
        if n > 0.0 { (sum / n, sat / n) } else { (0.0, 0.0) }
    };
    // Cheeks: points on each cheek and under each eye.
    let right = sample_region(&[116, 117, 118, 50, 101, 205]);
    let left = sample_region(&[345, 346, 347, 280, 330, 425]);
    let centre = sample_region(&[6, 197, 195, 5, 4, 151, 9]);
    let brightness = (right.0 + left.0 + centre.0) / 3.0;
    let evenness = right.0.min(left.0) / right.0.max(left.0).max(1.0);
    let saturated = (right.1 + left.1 + centre.1) / 3.0;
    (brightness, evenness, saturated)
}

/// The quality of the face with these landmarks; `aligned` is its
/// 112 × 112 aligned crop (HWC, 0–255), when one was made.
pub fn assess(frame: &Frame, points: &[[f32; 3]], pose: &Pose, aligned: Option<&[f32]>) -> FaceQuality {
    let iod = interocular(points);
    let (brightness, evenness, saturated) = face_light(frame, points);
    let sharpness = aligned.map(|a| laplacian_variance(&luma_hwc(a), 112, 112)).unwrap_or(0.0);
    let eyes_open = (eye_aspect_ratio(points, idx::RIGHT_EAR) + eye_aspect_ratio(points, idx::LEFT_EAR)) / 2.0;
    let off_frontal = pose.yaw.abs().max(pose.pitch.abs());
    let mut problems = Vec::new();
    let s_size = ramp(iod, MIN_IOD_PX * 0.6, MIN_IOD_PX);
    // Absolute luma must not penalise dark skin: only a face too dark to see is flagged.
    let s_dark = ramp(brightness, 25.0, 45.0);
    let s_bright = 1.0 - ramp(brightness, 235.0, 252.0);
    let s_even = ramp(evenness, 0.3, 0.5);
    let s_sat = 1.0 - ramp(saturated, 0.15, 0.35);
    let s_sharp = if aligned.is_some() { ramp(sharpness, SHARPNESS_MIN * 0.5, SHARPNESS_MIN) } else { 1.0 };
    let s_eyes = ramp(eyes_open, 0.12, 0.2);
    let s_pose = 1.0 - ramp(off_frontal, 15.0, 30.0);
    let s_roll = 1.0 - ramp(pose.roll.abs(), 10.0, 25.0);
    if s_size < 1.0 {
        problems.push("face too small");
    }
    if s_dark < 1.0 {
        problems.push("too dark");
    }
    if s_bright < 1.0 || s_sat < 1.0 {
        problems.push("too bright");
    }
    if s_even < 1.0 {
        problems.push("uneven light");
    }
    if s_sharp < 1.0 {
        problems.push("blurred");
    }
    if s_eyes < 1.0 {
        problems.push("eyes closed");
    }
    if s_pose < 1.0 || s_roll < 1.0 {
        problems.push("not facing the camera");
    }
    let score = s_size * s_dark * s_bright * s_even * s_sat * s_sharp * s_eyes * s_pose * s_roll;
    FaceQuality { interocular_px: iod, brightness, evenness, saturated, sharpness, eyes_open, off_frontal, roll: pose.roll, score, problems }
}
