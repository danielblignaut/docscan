//! Head pose from the dense landmarks: a similarity fit of MediaPipe's
//! canonical face (468 vertices) to the predicted 3-D points.
//!
//! Angles are in degrees, as seen by the camera (not mirrored):
//! - `yaw` > 0: the face turns towards the image's right;
//! - `pitch` > 0: the face tilts up;
//! - `roll` > 0: the head tilts anticlockwise in the image.

use serde::Serialize;

use super::canonical::VERTICES;
use super::linalg::similarity_3d;

/// Added to the fitted pitch: the canonical face, fitted to Face Mesh V2's
/// points, reads a frontal face as tilted down; the median pitch over LFW's
/// 13 233 images (mostly frontal photos taken at eye level) was -4.2°.
pub const PITCH_OFFSET: f64 = 4.2;

#[derive(Debug, Clone, Copy, Serialize, Default)]
pub struct Pose {
    pub yaw: f32,
    pub pitch: f32,
    pub roll: f32,
    /// The direction the face looks, camera coordinates (x right, y up, z
    /// towards the camera).
    pub forward: [f32; 3],
    /// Frame pixels per canonical centimetre.
    pub scale: f32,
}

/// The pose from the 478 (or 468) predicted points in frame pixels.
pub fn estimate(points: &[[f32; 3]]) -> Pose {
    let n = VERTICES.len().min(points.len());
    let src: Vec<[f64; 3]> = VERTICES[..n].iter().map(|v| [v[0] as f64, v[1] as f64, v[2] as f64]).collect();
    // Image y is down and the model's z grows away from the camera.
    let dst: Vec<[f64; 3]> = points[..n].iter().map(|p| [p[0] as f64, -p[1] as f64, -p[2] as f64]).collect();
    let (r, scale, _) = similarity_3d(&src, &dst);
    let forward = [r[2], r[5], r[8]];
    let right = [r[0], r[3], r[6]];
    let yaw = forward[0].atan2(forward[2]).to_degrees();
    let pitch = forward[1].atan2((forward[0].powi(2) + forward[2].powi(2)).sqrt()).to_degrees() + PITCH_OFFSET;
    let roll = right[1].atan2(right[0]).to_degrees();
    Pose { yaw: yaw as f32, pitch: pitch as f32, roll: roll as f32, forward: forward.map(|v| v as f32), scale: scale as f32 }
}

/// The angle between two looking directions, degrees.
pub fn angle_between(a: [f32; 3], b: [f32; 3]) -> f32 {
    let dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    let na = (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]).sqrt();
    let nb = (b[0] * b[0] + b[1] * b[1] + b[2] * b[2]).sqrt();
    (dot / (na * nb).max(1e-9)).clamp(-1.0, 1.0).acos().to_degrees()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Projects the canonical face turned by yaw/pitch into "frame" points.
    fn render(yaw: f32, pitch: f32) -> Vec<[f32; 3]> {
        let (sy, cy) = yaw.to_radians().sin_cos();
        let (sp, cp) = pitch.to_radians().sin_cos();
        VERTICES
            .iter()
            .map(|v| {
                // Yaw about y (towards +x), then pitch about x (towards +y).
                let x = cy * v[0] + sy * v[2];
                let z = -sy * v[0] + cy * v[2];
                let y = cp * v[1] + sp * z;
                let z = -sp * v[1] + cp * z;
                [200.0 + 10.0 * x, 200.0 - 10.0 * y, -10.0 * z]
            })
            .collect()
    }

    #[test]
    fn recovers_yaw_and_pitch_signs() {
        let p = estimate(&render(20.0, 0.0));
        assert!((p.yaw - 20.0).abs() < 0.5 && (p.pitch - PITCH_OFFSET as f32).abs() < 0.5, "{p:?}");
        let p = estimate(&render(0.0, 15.0));
        assert!((p.pitch - 15.0 - PITCH_OFFSET as f32).abs() < 0.5 && p.yaw.abs() < 0.5, "{p:?}");
        assert!((p.scale - 10.0).abs() < 0.01);
    }
}
