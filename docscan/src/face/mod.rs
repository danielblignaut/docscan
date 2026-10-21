//! Face liveness and verification on the device.
//!
//! One [`FaceScanner`] holds the face models, all ONNX run on rten inside the
//! same wasm as the document scanner:
//!
//! - detection: MediaPipe BlazeFace short-range (`detect`);
//! - 478 dense landmarks, tracked frame to frame: MediaPipe Face Mesh V2
//!   (`mesh`), and head pose from them (`pose`);
//! - passive anti-spoofing: Minivision's MiniFASNet pair (`antispoof`);
//! - templates: a recognition model on the ArcFace-aligned face (`recognise`);
//! - quality measures (`quality`), and the active liveness session
//!   (`liveness`): a ring swept by turning the head, with 3-D motion,
//!   anti-spoofing, continuity and identity checks.
//!
//! The page hands it RGBA camera frames and gets JSON back. See the README's
//! "Face liveness and verification" section and `face/`.

pub mod antispoof;
pub mod canonical;
pub mod detect;
pub mod image;
pub mod linalg;
pub mod liveness;
pub mod mesh;
pub mod parallax;
pub mod pose;
pub mod quality;
pub mod recognise;

use std::cell::RefCell;

use serde::Serialize;
use wasm_bindgen::prelude::*;

use detect::{Detection, Detector};
use image::Frame;
use mesh::{Mesh, MeshResult};
use pose::Pose;
use quality::FaceQuality;
use recognise::{InputKind, Recogniser};

/// Below this face-presence probability the tracked face is lost.
const MIN_PRESENCE: f32 = 0.5;

/// One frame's face, as the page sees it.
#[derive(Debug, Clone, Serialize)]
pub struct Observation {
    pub found: bool,
    /// Faces the detector saw, when it ran this frame.
    pub faces: Option<usize>,
    pub presence: f32,
    /// `[x, y, w, h]` of the landmarks, frame pixels.
    pub bbox: [f32; 4],
    pub pose: Pose,
    pub quality: FaceQuality,
    /// Mean eye aspect ratio.
    pub ear: f32,
    pub tracked: bool,
    /// The 478 points, `[x, y, z]` frame pixels (not serialised; see `outline`).
    #[serde(skip)]
    pub points: Vec<[f32; 3]>,
    /// The face's outline (36 points of the mesh's silhouette), for drawing.
    pub outline: Vec<[f32; 2]>,
    pub timings_ms: ObservationTimings,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct ObservationTimings {
    pub detect: f64,
    pub mesh: f64,
    pub total: f64,
}

/// The mesh's face oval, in order.
pub const FACE_OVAL: [usize; 36] = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
];

/// The face models and the tracking state between frames.
#[derive(Default)]
pub struct FaceEngine {
    pub detector: Option<Detector>,
    pub mesh: Option<Mesh>,
    pub antispoof: Option<antispoof::AntiSpoof>,
    pub recogniser: Option<Recogniser>,
    /// The recognition model's name, reported with each template.
    pub recogniser_name: String,
    /// The last frame's landmarks, to track from.
    prev: RefCell<Option<Vec<[f32; 3]>>>,
    /// Frames since the detector last ran.
    since_detect: RefCell<u32>,
}

/// The detector re-runs at least this often while tracking, to count faces.
const DETECT_EVERY: u32 = 6;

impl FaceEngine {
    pub fn reset_tracking(&self) {
        *self.prev.borrow_mut() = None;
        *self.since_detect.borrow_mut() = DETECT_EVERY;
    }

    /// The most prominent detection: the largest, ties to the most central.
    fn pick(dets: &[Detection], frame: &Frame) -> Option<Detection> {
        let (cx, cy) = (frame.width as f32 / 2.0, frame.height as f32 / 2.0);
        dets.iter()
            .max_by(|a, b| {
                let key = |d: &Detection| {
                    let dc = ((d.bbox[0] + d.bbox[2] / 2.0 - cx).powi(2) + (d.bbox[1] + d.bbox[3] / 2.0 - cy).powi(2)).sqrt();
                    d.bbox[2] * d.bbox[3] - 0.1 * dc
                };
                key(a).total_cmp(&key(b))
            })
            .cloned()
    }

    /// Detects (over the whole frame, then in tiles for small faces) and
    /// returns every face found.
    pub fn detect_all(&self, frame: &Frame, tiles: bool) -> anyhow::Result<Vec<Detection>> {
        let det = self.detector.as_ref().ok_or_else(|| anyhow::anyhow!("face detector not loaded"))?;
        let mut found = det.detect(frame)?;
        if found.is_empty() && tiles {
            // The short-range model wants a face over ~15% of its input: try
            // squares of half and a third of the shorter side, overlapping.
            let short = frame.width.min(frame.height) as f32;
            for frac in [0.6f32, 0.4] {
                let side = short * frac;
                let step = side / 2.0;
                let mut y = side / 2.0;
                while y <= frame.height as f32 - side / 2.0 + 1.0 {
                    let mut x = side / 2.0;
                    while x <= frame.width as f32 - side / 2.0 + 1.0 {
                        found.extend(det.detect_square(frame, x, y, side)?);
                        x += step;
                    }
                    y += step;
                }
                if !found.is_empty() {
                    break;
                }
            }
        }
        Ok(found)
    }

    /// Landmarks for one detection.
    pub fn landmarks(&self, frame: &Frame, d: &Detection) -> anyhow::Result<MeshResult> {
        let mesh = self.mesh.as_ref().ok_or_else(|| anyhow::anyhow!("face mesh not loaded"))?;
        let first = mesh.run(frame, mesh::roi_from_detection(d))?;
        // A second pass from the first's landmarks centres the crop as tracking would.
        if first.presence >= MIN_PRESENCE {
            let second = mesh.run(frame, mesh::roi_from_points(&first.points))?;
            if second.presence >= MIN_PRESENCE {
                return Ok(second);
            }
        }
        Ok(first)
    }

    /// One camera frame: track the face from the last frame's landmarks
    /// (detecting it afresh when lost, and every few frames to count faces),
    /// then its pose and quality.
    pub fn observe(&self, frame: &Frame) -> anyhow::Result<Observation> {
        let t0 = crate::now();
        let mesh = self.mesh.as_ref().ok_or_else(|| anyhow::anyhow!("face mesh not loaded"))?;
        let mut timings = ObservationTimings::default();
        let mut faces = None;
        let mut result: Option<MeshResult> = None;
        let mut tracked = false;
        let prev = self.prev.borrow().clone();
        let due = {
            let mut s = self.since_detect.borrow_mut();
            *s += 1;
            *s >= DETECT_EVERY
        };
        if let Some(prev) = &prev {
            let t = crate::now();
            let r = mesh.run(frame, mesh::roi_from_points(prev))?;
            timings.mesh += crate::now() - t;
            if r.presence >= MIN_PRESENCE {
                result = Some(r);
                tracked = true;
            }
        }
        if result.is_none() || due {
            let t = crate::now();
            let dets = self.detect_all(frame, false)?;
            timings.detect = crate::now() - t;
            *self.since_detect.borrow_mut() = 0;
            faces = Some(dets.len());
            if result.is_none() {
                if let Some(d) = Self::pick(&dets, frame) {
                    let t = crate::now();
                    let r = self.landmarks(frame, &d)?;
                    timings.mesh += crate::now() - t;
                    if r.presence >= MIN_PRESENCE {
                        result = Some(r);
                    }
                }
            }
        }
        let Some(r) = result else {
            *self.prev.borrow_mut() = None;
            timings.total = crate::now() - t0;
            return Ok(Observation {
                found: false,
                faces,
                presence: 0.0,
                bbox: [0.0; 4],
                pose: Pose::default(),
                quality: FaceQuality::default(),
                ear: 0.0,
                tracked: false,
                points: Vec::new(),
                outline: Vec::new(),
                timings_ms: timings,
            });
        };
        *self.prev.borrow_mut() = Some(r.points.clone());
        let pose = pose::estimate(&r.points);
        let aligned = image::warp_hwc(frame, &recognise::alignment(&recognise::five_points(&r.points)), 112, 112, 1.0, 0.0);
        let quality = quality::assess(frame, &r.points, &pose, Some(&aligned));
        let ear = quality.eyes_open;
        timings.total = crate::now() - t0;
        Ok(Observation {
            found: true,
            faces,
            presence: r.presence,
            bbox: mesh::bbox(&r.points),
            pose,
            quality,
            ear,
            tracked,
            outline: FACE_OVAL.iter().map(|&i| [r.points[i][0], r.points[i][1]]).collect(),
            points: r.points,
            timings_ms: timings,
        })
    }

    /// The template of the face with these landmarks.
    pub fn template(&self, frame: &Frame, points: &[[f32; 3]], flip: bool) -> anyhow::Result<Vec<f32>> {
        let rec = self.recogniser.as_ref().ok_or_else(|| anyhow::anyhow!("recognition model not loaded"))?;
        rec.embed(frame, &recognise::five_points(points), flip)
    }

    /// A still photo (an uploaded selfie, or an identity document's photo):
    /// the most prominent face, its quality, aligned crop and template.
    pub fn photo(&self, frame: &Frame) -> anyhow::Result<PhotoFace> {
        let t0 = crate::now();
        let dets = self.detect_all(frame, true)?;
        let Some(d) = Self::pick(&dets, frame) else {
            return Ok(PhotoFace { found: false, faces: 0, ..Default::default() });
        };
        let r = self.landmarks(frame, &d)?;
        let pose = pose::estimate(&r.points);
        let five = recognise::five_points(&r.points);
        let map = recognise::alignment(&five);
        let aligned = image::warp_hwc(frame, &map, 112, 112, 1.0, 0.0);
        let quality = quality::assess(frame, &r.points, &pose, Some(&aligned));
        let template = match &self.recogniser {
            Some(rec) => rec.embed(frame, &five, true)?,
            None => Vec::new(),
        };
        let spoof = match &self.antispoof {
            Some(a) => Some(a.score(frame, mesh::bbox(&r.points))?),
            None => None,
        };
        Ok(PhotoFace {
            found: r.presence >= MIN_PRESENCE,
            faces: dets.len(),
            detection_score: d.score,
            presence: r.presence,
            bbox: mesh::bbox(&r.points),
            pose,
            quality,
            aligned: image::warp_rgba(frame, &map, 112, 112),
            template,
            model: self.recogniser_name.clone(),
            antispoof: spoof,
            ms: crate::now() - t0,
        })
    }
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct PhotoFace {
    pub found: bool,
    pub faces: usize,
    pub detection_score: f32,
    pub presence: f32,
    pub bbox: [f32; 4],
    pub pose: Pose,
    pub quality: FaceQuality,
    /// The aligned 112 × 112 face, RGBA.
    #[serde(with = "serde_bytes_vec")]
    pub aligned: Vec<u8>,
    pub template: Vec<f32>,
    pub model: String,
    pub antispoof: Option<antispoof::SpoofScore>,
    pub ms: f64,
}

/// Bytes as a `Uint8Array` for the page rather than an array of numbers.
mod serde_bytes_vec {
    pub fn serialize<S: serde::Serializer>(v: &[u8], s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(v)
    }
}

/// Decision thresholds on the cosine similarity of two templates, per model,
/// measured on LFW (`face/RESULTS.md`): the threshold that gave a false
/// accept rate of 1e-3 on the DEV split (View 1), and its rate on TEST.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct Threshold {
    pub model: &'static str,
    pub threshold: f32,
    pub far_dev: f32,
}

/// From `face/RESULTS.md`: the LFW DEV split (View 1 without the pairs that
/// are also in View 2), docscan's own detection, landmarks and alignment.
pub const THRESHOLDS: &[Threshold] = &[
    Threshold { model: "sface_int8", threshold: 0.366, far_dev: 1e-3 },
    Threshold { model: "sface", threshold: 0.363, far_dev: 1e-3 },
    Threshold { model: "w600k_mbf", threshold: 0.231, far_dev: 1e-3 },
    Threshold { model: "edgeface_xs", threshold: 0.363, far_dev: 1e-3 },
];

pub fn threshold_for(model: &str) -> f32 {
    THRESHOLDS.iter().find(|t| t.model == model).map(|t| t.threshold).unwrap_or(0.35)
}

fn js<T: Serialize>(v: &T) -> Result<JsValue, JsError> {
    v.serialize(&serde_wasm_bindgen::Serializer::json_compatible()).map_err(|e| JsError::new(&e.to_string()))
}

fn jserr(e: anyhow::Error) -> JsError {
    JsError::new(&format!("{e:#}"))
}

/// The face scanner for the page: load the models, then feed it frames.
#[wasm_bindgen]
#[derive(Default)]
pub struct FaceScanner {
    engine: FaceEngine,
    session: RefCell<Option<liveness::Session>>,
}

#[wasm_bindgen]
impl FaceScanner {
    #[wasm_bindgen(constructor)]
    pub fn new() -> FaceScanner {
        console_error_panic_hook::set_once();
        FaceScanner::default()
    }

    /// BlazeFace short-range and Face Mesh V2, as ONNX.
    pub fn load_tracker(&mut self, detector: Vec<u8>, mesh: Vec<u8>) -> Result<(), JsError> {
        self.engine.detector = Some(Detector::load(detector).map_err(jserr)?);
        self.engine.mesh = Some(Mesh::load(mesh).map_err(jserr)?);
        Ok(())
    }

    /// The MiniFASNet pair (`face/tools/export_minifasnet.py`).
    pub fn load_antispoof(&mut self, model: Vec<u8>) -> Result<(), JsError> {
        self.engine.antispoof = Some(antispoof::AntiSpoof::load(model).map_err(jserr)?);
        Ok(())
    }

    /// A recognition model: `name` labels its templates (and picks its
    /// threshold), `kind` its input convention (`arcface`, `sface`, `facenet`).
    pub fn load_recogniser(&mut self, model: Vec<u8>, name: &str, kind: &str) -> Result<(), JsError> {
        let kind = InputKind::parse(kind).map_err(jserr)?;
        self.engine.recogniser = Some(Recogniser::load(model, kind).map_err(jserr)?);
        self.engine.recogniser_name = name.to_string();
        Ok(())
    }

    pub fn has_tracker(&self) -> bool {
        self.engine.detector.is_some() && self.engine.mesh.is_some()
    }
    pub fn has_antispoof(&self) -> bool {
        self.engine.antispoof.is_some()
    }
    pub fn has_recogniser(&self) -> bool {
        self.engine.recogniser.is_some()
    }
    pub fn recogniser_name(&self) -> String {
        self.engine.recogniser_name.clone()
    }

    /// One frame's face: found, box, pose, quality, outline (no session).
    pub fn track(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let frame = Frame::new(rgba, width as usize, height as usize).map_err(jserr)?;
        js(&self.engine.observe(&frame).map_err(jserr)?)
    }

    /// Starts an active liveness session. `config` is a JSON object (see
    /// `liveness::Config`; every field optional).
    pub fn liveness_start(&self, config: JsValue) -> Result<(), JsError> {
        let config: liveness::Config = if config.is_undefined() || config.is_null() {
            liveness::Config::default()
        } else {
            serde_wasm_bindgen::from_value(config).map_err(|e| JsError::new(&e.to_string()))?
        };
        self.engine.reset_tracking();
        *self.session.borrow_mut() = Some(liveness::Session::new(config));
        Ok(())
    }

    /// One camera frame of the session (`timestamp_ms`: the frame's capture
    /// time). Returns the progress: phase, hint, ring segments, face.
    pub fn liveness_frame(&self, rgba: &[u8], width: u32, height: u32, timestamp_ms: f64) -> Result<JsValue, JsError> {
        let frame = Frame::new(rgba, width as usize, height as usize).map_err(jserr)?;
        let mut session = self.session.borrow_mut();
        let s = session.as_mut().ok_or_else(|| JsError::new("liveness_start first"))?;
        js(&s.frame(&self.engine, &frame, timestamp_ms).map_err(jserr)?)
    }

    /// The session's outcome (once the progress says `done`, or to give up):
    /// pass or fail with a score per check, the best frame, quality and template.
    pub fn liveness_result(&self) -> Result<JsValue, JsError> {
        let session = self.session.borrow();
        let s = session.as_ref().ok_or_else(|| JsError::new("liveness_start first"))?;
        js(&s.result(&self.engine))
    }

    /// The most prominent face in a still image (a selfie or an identity
    /// document): quality, aligned crop and template.
    pub fn photo(&self, rgba: &[u8], width: u32, height: u32) -> Result<JsValue, JsError> {
        let frame = Frame::new(rgba, width as usize, height as usize).map_err(jserr)?;
        js(&self.engine.photo(&frame).map_err(jserr)?)
    }

    /// Cosine similarity of two templates.
    pub fn compare(&self, a: &[f32], b: &[f32]) -> f32 {
        recognise::similarity(a, b)
    }

    /// The decision threshold for the loaded model (see `THRESHOLDS`).
    pub fn threshold(&self) -> f32 {
        threshold_for(&self.engine.recogniser_name)
    }
}

impl FaceScanner {
    pub fn engine(&self) -> &FaceEngine {
        &self.engine
    }
    pub fn engine_mut(&mut self) -> &mut FaceEngine {
        &mut self.engine
    }
}
