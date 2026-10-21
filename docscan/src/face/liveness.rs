//! Active liveness: centre the face, then sweep a ring by turning the head
//! all the way round, then look straight again.
//!
//! Phases:
//! 1. **centre**: one face, inside the guide, the right size, facing the
//!    camera, lit, sharp, eyes open, for a few consecutive frames. Those
//!    frames fix the *neutral* pose (a phone's camera sits above the screen,
//!    so "straight" is rarely 0°) and the reference landmarks.
//! 2. **sweep**: the ring of `segments` around the guide. The direction the
//!    face points, relative to neutral and as seen in the mirrored preview,
//!    lights the segment it points at once it is at least `min_angle` off
//!    neutral.
//! 3. **finish**: facing the camera again for a few frames.
//!
//! The checks, scored over the whole session:
//! - **coverage**: the share of segments lit;
//! - **3-D motion** (`planarity`): a flat photo or screen, however it is moved
//!   or tilted, moves its landmarks by one homography between two frames; a
//!   real head turning shows parallax (the nose moves against the cheeks)
//!   that no homography explains. The residual of a homography fitted from
//!   the reference frame's rigid landmarks to each turned frame's, in
//!   canonical-face centimetres, must be large enough at the turned frames;
//! - **anti-spoofing**: the MiniFASNet pair's live probability, averaged over
//!   sampled near-frontal frames;
//! - **continuity**: no gap with the face lost for long, no jump of the face
//!   between consecutive frames that a head cannot make (a spliced or
//!   switched stream), timestamps that increase;
//! - **identity**: the face at the end is the face at the start (templates
//!   from the centre and finish phases agree);
//! - **blink**: counted (eye aspect ratio against the session's own open-eye
//!   baseline); required only when the config asks.

use serde::{Deserialize, Serialize};

use super::FaceEngine;
use super::image::{self, Frame};
use super::linalg::{fit_homography, homography_rms};
use super::mesh;
use super::parallax;
use super::pose::Pose;
use super::quality::FaceQuality;
use super::recognise;

/// Session settings; every field has a default.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Ring segments.
    pub segments: usize,
    /// Share of the segments to light before finishing.
    pub coverage: f32,
    /// Degrees off neutral that light a segment.
    pub min_angle: f32,
    /// The preview is mirrored (a front camera): the ring follows the mirror.
    pub mirrored: bool,
    /// The guide, as fractions of the frame: centre x, centre y, and radius
    /// (of the frame's shorter side).
    pub guide: [f32; 3],
    /// Consecutive good frames to finish centring, and to finish.
    pub centre_frames: usize,
    pub finish_frames: usize,
    /// Give up after this long (ms).
    pub max_ms: f64,
    pub require_blink: bool,
    /// Pass thresholds (see `face/RESULTS.md` for how they were chosen).
    pub min_parallax: f32,
    pub min_antispoof: f32,
    pub min_identity: f32,
    /// Run anti-spoofing at most this often (ms).
    pub antispoof_every_ms: f64,
    /// Measure texture parallax on every this-many-th turned frame.
    pub parallax_every: usize,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            segments: 12,
            coverage: 1.0,
            min_angle: 14.0,
            mirrored: true,
            guide: [0.5, 0.5, 0.25],
            centre_frames: 5,
            finish_frames: 3,
            max_ms: 60_000.0,
            require_blink: false,
            min_parallax: 0.06,
            min_antispoof: 0.5,
            min_identity: 0.5,
            antispoof_every_ms: 250.0,
            parallax_every: 2,
        }
    }
}

/// The points re-found by texture for the parallax measure: the rigid ones,
/// plus textured points inside the face (nostrils, nose sides, cheeks).
pub const PARALLAX_POINTS: [usize; 62] = [
    1, 4, 5, 195, 197, 6, 168, 2, 98, 327, 10, 151, 9, 108, 337, 67, 297, 33, 133, 263, 362, 116, 345, 123, 352, 50, 280, 205, 425, 152, 175, 199, 172,
    397, 136, 365, 58, 288, 127, 356, 162, 389, 21, 251, 93, 323, // RIGID
    48, 278, 115, 344, 131, 360, 64, 294, 36, 266, 47, 277, 142, 371, 187, 411,
];

fn upper_median(mut r: Vec<f32>) -> Option<f32> {
    if r.len() < 3 {
        return None;
    }
    r.sort_by(f32::total_cmp);
    let upper = &r[r.len() / 2..];
    Some(upper[upper.len() / 2])
}

/// Mesh points that move rigidly with the skull (nose, forehead, cheekbones,
/// eye corners, chin, jaw, temples), not with expression.
pub const RIGID: [usize; 46] = [
    1, 4, 5, 195, 197, 6, 168, 2, 98, 327, // nose
    10, 151, 9, 108, 337, 67, 297, // forehead
    33, 133, 263, 362, // eye corners
    116, 345, 123, 352, 50, 280, 205, 425, // cheeks
    152, 175, 199, // chin
    172, 397, 136, 365, 58, 288, // jaw
    127, 356, 162, 389, 21, 251, 93, 323, // temples, contour
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Centre,
    Sweep,
    Finish,
    Done,
    /// Timed out.
    Failed,
}

#[derive(Debug, Clone)]
struct Sample {
    rigid: Vec<[f64; 2]>,
    pose: Pose,
    /// Offset from neutral as shown on screen: degrees right and up.
    dir: [f32; 2],
}

#[derive(Debug, Clone)]
struct Kept {
    quality: f32,
    template: Vec<f32>,
    aligned: Vec<u8>,
    portrait: Vec<u8>,
    face_quality: FaceQuality,
}

#[derive(Debug, Clone, Serialize)]
pub struct Progress {
    pub phase: Phase,
    pub hint: String,
    /// One per ring segment, clockwise from the top (as shown on screen).
    pub segments: Vec<bool>,
    pub coverage: f32,
    /// The segment the face points at now, if far enough off neutral.
    pub pointing: Option<usize>,
    /// Degrees right and up of neutral, as shown on screen.
    pub direction: [f32; 2],
    pub found: bool,
    pub faces: Option<usize>,
    pub bbox: [f32; 4],
    pub outline: Vec<[f32; 2]>,
    pub pose: Pose,
    pub quality: f32,
    pub elapsed_ms: f64,
    pub ms: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Check {
    pub name: &'static str,
    pub passed: bool,
    /// Whether it counts towards the decision.
    pub required: bool,
    pub score: f32,
    pub threshold: f32,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Portrait {
    pub width: u32,
    pub height: u32,
    #[serde(with = "super::serde_bytes_vec")]
    pub rgba: Vec<u8>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LivenessResult {
    pub passed: bool,
    pub completed: bool,
    /// The weakest required check's score over its threshold, capped at 2.
    pub score: f32,
    pub checks: Vec<Check>,
    pub quality: Option<FaceQuality>,
    /// The best frontal frame: a 240 × 300 portrait crop, and the aligned 112 × 112 face.
    pub best_frame: Option<Portrait>,
    pub aligned: Option<Portrait>,
    pub template: Vec<f32>,
    pub model: String,
    pub duration_ms: f64,
    pub frames: usize,
    pub frames_with_face: usize,
    pub segments: Vec<bool>,
    pub reasons: Vec<String>,
}

pub struct Session {
    config: Config,
    phase: Phase,
    start: Option<f64>,
    last_ts: Option<f64>,
    frames: usize,
    with_face: usize,
    good_run: usize,
    centre_samples: Vec<Sample>,
    reference: Option<Sample>,
    neutral: [f32; 2],
    samples: Vec<Sample>,
    segments: Vec<bool>,
    spoof: Vec<f32>,
    last_spoof_ts: f64,
    start_kept: Vec<Kept>,
    finish_kept: Vec<Kept>,
    ear_open: Vec<f32>,
    blinks: usize,
    blink_closed_at: Option<f64>,
    max_gap_ms: f64,
    lost_since: Option<f64>,
    jumps: usize,
    non_monotonic: usize,
    multi_face: usize,
    prev_centre: Option<([f32; 2], f32, f64)>,
    done_ts: Option<f64>,
    /// The texture reference for the parallax measure, and its landmarks.
    parallax_ref: Option<parallax::Reference>,
    parallax_ref_points: Vec<[f32; 2]>,
    /// Per measured turned frame: texture parallax (share of the interocular
    /// distance) and the angle off neutral.
    parallax: Vec<(f32, f32)>,
    /// The screen direction (degrees right, up of neutral) of each of them.
    parallax_dirs: Vec<[f32; 2]>,
    outliers: Vec<f32>,
    turned: usize,
}

const PORTRAIT_W: usize = 240;
const PORTRAIT_H: usize = 300;

fn hint_for_quality(q: &FaceQuality) -> Option<&'static str> {
    q.problems.first().map(|p| match *p {
        "face too small" => "Move closer",
        "too dark" => "Find better light",
        "too bright" => "Too bright: move out of direct light",
        "uneven light" => "Light your face evenly",
        "blurred" => "Hold still",
        "eyes closed" => "Open your eyes",
        _ => "Look straight at the camera",
    })
}

impl Session {
    pub fn new(config: Config) -> Session {
        let n = config.segments.max(4);
        Session {
            segments: vec![false; n],
            config,
            phase: Phase::Centre,
            start: None,
            last_ts: None,
            frames: 0,
            with_face: 0,
            good_run: 0,
            centre_samples: Vec::new(),
            reference: None,
            neutral: [0.0, 0.0],
            samples: Vec::new(),
            spoof: Vec::new(),
            last_spoof_ts: f64::MIN,
            start_kept: Vec::new(),
            finish_kept: Vec::new(),
            ear_open: Vec::new(),
            blinks: 0,
            blink_closed_at: None,
            max_gap_ms: 0.0,
            lost_since: None,
            jumps: 0,
            non_monotonic: 0,
            multi_face: 0,
            prev_centre: None,
            done_ts: None,
            parallax_ref: None,
            parallax_ref_points: Vec::new(),
            parallax: Vec::new(),
            parallax_dirs: Vec::new(),
            outliers: Vec::new(),
            turned: 0,
        }
    }

    pub fn phase(&self) -> Phase {
        self.phase
    }

    fn coverage(&self) -> f32 {
        self.segments.iter().filter(|s| **s).count() as f32 / self.segments.len() as f32
    }

    /// The screen direction of a pose relative to neutral: degrees right, up.
    fn screen_dir(&self, pose: &Pose) -> [f32; 2] {
        let right = if self.config.mirrored { -pose.yaw } else { pose.yaw };
        [right - self.neutral[0], pose.pitch - self.neutral[1]]
    }

    /// The segment a screen direction points at (0 at the top, clockwise).
    fn segment_of(&self, dir: [f32; 2]) -> usize {
        let n = self.segments.len();
        let theta = dir[0].atan2(dir[1]).to_degrees().rem_euclid(360.0);
        let seg = 360.0 / n as f32;
        (((theta + seg / 2.0) / seg).floor() as usize) % n
    }

    fn keep(&self, engine: &FaceEngine, frame: &Frame, points: &[[f32; 3]], q: &FaceQuality) -> anyhow::Result<Option<Kept>> {
        let Some(rec) = engine.recogniser.as_ref() else {
            return Ok(Some(Kept { quality: q.score, template: Vec::new(), aligned: Vec::new(), portrait: portrait(frame, points), face_quality: q.clone() }));
        };
        let five = recognise::five_points(points);
        let map = recognise::alignment(&five);
        let template = rec.embed(frame, &five, false)?;
        Ok(Some(Kept { quality: q.score, template, aligned: image::warp_rgba(frame, &map, 112, 112), portrait: portrait(frame, points), face_quality: q.clone() }))
    }

    pub fn frame(&mut self, engine: &FaceEngine, frame: &Frame, ts: f64) -> anyhow::Result<Progress> {
        let t0 = crate::now();
        let start = *self.start.get_or_insert(ts);
        if let Some(last) = self.last_ts {
            if ts <= last {
                self.non_monotonic += 1;
            }
        }
        self.frames += 1;
        let obs = engine.observe(frame)?;
        if obs.faces.is_some_and(|n| n > 1) {
            self.multi_face += 1;
        }
        let short = frame.width.min(frame.height) as f32;
        let guide_c = [self.config.guide[0] * frame.width as f32, self.config.guide[1] * frame.height as f32];
        let guide_r = self.config.guide[2] * short;
        let mut hint = String::new();
        let mut pointing = None;
        let mut direction = [0.0, 0.0];

        if self.phase == Phase::Done || self.phase == Phase::Failed {
            return Ok(self.progress(&obs, "".into(), None, direction, ts, t0));
        }
        if ts - start > self.config.max_ms {
            self.phase = Phase::Failed;
            return Ok(self.progress(&obs, "Time is up".into(), None, direction, ts, t0));
        }

        if !obs.found {
            self.lost_since.get_or_insert(ts);
            self.good_run = 0;
            if self.phase == Phase::Centre {
                self.centre_samples.clear();
            }
            self.last_ts = Some(ts);
            let h = if self.phase == Phase::Sweep { "Keep your face in view" } else { "Show your face in the oval" };
            return Ok(self.progress(&obs, h.into(), None, direction, ts, t0));
        }
        if let Some(lost) = self.lost_since.take() {
            if self.phase != Phase::Centre || self.reference.is_some() {
                self.max_gap_ms = self.max_gap_ms.max(ts - lost);
            }
        }
        self.with_face += 1;

        // Continuity: how far the face centre moved since the last frame, in
        // face widths, against the time between them.
        let iod = mesh::interocular(&obs.points).max(1.0);
        let centre = [obs.bbox[0] + obs.bbox[2] / 2.0, obs.bbox[1] + obs.bbox[3] / 2.0];
        if let Some((pc, piod, pts)) = self.prev_centre {
            let d = ((centre[0] - pc[0]).powi(2) + (centre[1] - pc[1]).powi(2)).sqrt() / piod.max(1.0);
            let dt = (ts - pts).max(1.0);
            let scale_jump = (iod / piod).max(piod / iod);
            // A head moves its face at most ~3 interocular distances in 100 ms
            // (a fast turn); a jump of more than that in a short interval, or
            // the face suddenly 1.6 × larger or smaller, is a splice.
            if dt < 400.0 && (d > 3.0 * (dt as f32 / 100.0).max(1.0) || scale_jump > 1.6) {
                self.jumps += 1;
            }
        }
        self.prev_centre = Some((centre, iod, ts));

        let rigid: Vec<[f64; 2]> = RIGID.iter().map(|&i| [obs.points[i][0] as f64, obs.points[i][1] as f64]).collect();
        let dir = self.screen_dir(&obs.pose);
        direction = dir;
        let sample = Sample { rigid, pose: obs.pose, dir };

        // Blink: the eye aspect ratio dropping well under the open-eye
        // baseline and coming back within 600 ms, while near frontal.
        let near_frontal = dir[0].abs() < 12.0 && dir[1].abs() < 12.0;
        if !self.ear_open.is_empty() && near_frontal {
            let mut sorted = self.ear_open.clone();
            sorted.sort_by(f32::total_cmp);
            let base = sorted[sorted.len() / 2];
            if obs.ear < 0.6 * base {
                self.blink_closed_at.get_or_insert(ts);
            } else if obs.ear > 0.8 * base {
                if let Some(closed) = self.blink_closed_at.take() {
                    if ts - closed < 600.0 {
                        self.blinks += 1;
                    }
                }
            }
        }

        // Anti-spoofing on near-frontal frames, at most every `antispoof_every_ms`.
        if let Some(a) = engine.antispoof.as_ref() {
            if near_frontal && ts - self.last_spoof_ts >= self.config.antispoof_every_ms && self.phase != Phase::Centre {
                self.last_spoof_ts = ts;
                self.spoof.push(a.score(frame, obs.bbox)?.real);
            }
        }

        // Texture parallax on turned frames (every `parallax_every`-th, to bound the cost).
        if matches!(self.phase, Phase::Sweep | Phase::Finish) {
            let mag = (dir[0].powi(2) + dir[1].powi(2)).sqrt();
            if mag >= self.config.min_angle * 0.7 {
                self.turned += 1;
                if (self.turned - 1) % self.config.parallax_every.max(1) == 0 {
                    if let Some(r) = &self.parallax_ref {
                        let cur: Vec<[f32; 2]> = PARALLAX_POINTS.iter().map(|&i| [obs.points[i][0], obs.points[i][1]]).collect();
                        if let Some(p) = r.measure(frame, &self.parallax_ref_points, &cur, iod) {
                            self.parallax.push((p.residual, mag));
                            self.parallax_dirs.push(dir);
                            self.outliers.push(p.outliers);
                        }
                    }
                }
            }
        }

        let q = &obs.quality;
        match self.phase {
            Phase::Centre => {
                let dx = (centre[0] - guide_c[0]) / guide_r;
                let dy = (centre[1] - guide_c[1]) / guide_r;
                let size = obs.bbox[2].max(obs.bbox[3] * 0.8) / (2.0 * guide_r);
                let raw_right = if self.config.mirrored { -obs.pose.yaw } else { obs.pose.yaw };
                let h = if obs.faces.is_some_and(|n| n > 1) {
                    Some("Only one face, please")
                } else if dx.abs() > 0.35 || dy.abs() > 0.45 {
                    Some("Centre your face in the oval")
                } else if size < 0.42 {
                    Some("Move closer")
                } else if size > 1.05 {
                    Some("Move back a little")
                } else if raw_right.abs() > 15.0 || obs.pose.pitch.abs() > 20.0 || obs.pose.roll.abs() > 12.0 {
                    Some("Look straight at the camera")
                } else {
                    hint_for_quality(q)
                };
                match h {
                    Some(h) => {
                        self.good_run = 0;
                        self.centre_samples.clear();
                        hint = h.into();
                    }
                    None => {
                        self.good_run += 1;
                        self.ear_open.push(obs.ear);
                        if let Some(k) = self.keep(engine, frame, &obs.points, q)? {
                            self.start_kept.push(k);
                        }
                        self.centre_samples.push(sample.clone());
                        hint = "Hold still".into();
                        if self.good_run >= self.config.centre_frames {
                            let n = self.centre_samples.len() as f32;
                            let ry: f32 = self.centre_samples.iter().map(|s| if self.config.mirrored { -s.pose.yaw } else { s.pose.yaw }).sum::<f32>() / n;
                            let rp: f32 = self.centre_samples.iter().map(|s| s.pose.pitch).sum::<f32>() / n;
                            self.neutral = [ry, rp];
                            let mut r = self.centre_samples.last().cloned().unwrap();
                            r.dir = [0.0, 0.0];
                            self.reference = Some(r);
                            let pts: Vec<[f32; 2]> = PARALLAX_POINTS.iter().map(|&i| [obs.points[i][0], obs.points[i][1]]).collect();
                            self.parallax_ref = Some(parallax::Reference::new(frame, &pts, iod));
                            self.parallax_ref_points = pts;
                            self.phase = Phase::Sweep;
                            self.good_run = 0;
                            hint = "Slowly turn your head to light up the ring".into();
                        }
                    }
                }
            }
            Phase::Sweep => {
                let mag = (dir[0].powi(2) + dir[1].powi(2)).sqrt();
                if mag >= self.config.min_angle {
                    let s = self.segment_of(dir);
                    self.segments[s] = true;
                    pointing = Some(s);
                }
                self.samples.push(sample);
                if self.coverage() >= self.config.coverage - 1e-6 {
                    self.phase = Phase::Finish;
                    self.good_run = 0;
                    hint = "Now look straight at the camera".into();
                } else {
                    // Point the user at the nearest unlit segment.
                    hint = if mag < self.config.min_angle * 0.6 { "Tilt your head further, and keep turning" } else { "Keep turning your head around the circle" }.into();
                }
            }
            Phase::Finish => {
                self.samples.push(sample);
                let frontal = dir[0].abs() < 10.0 && dir[1].abs() < 10.0;
                if frontal && hint_for_quality(q).is_none() {
                    self.good_run += 1;
                    if let Some(k) = self.keep(engine, frame, &obs.points, q)? {
                        self.finish_kept.push(k);
                    }
                    hint = "Hold still".into();
                    if self.good_run >= self.config.finish_frames {
                        self.phase = Phase::Done;
                        self.done_ts = Some(ts);
                        hint = "Done".into();
                    }
                } else {
                    self.good_run = 0;
                    hint = "Now look straight at the camera".into();
                }
            }
            Phase::Done | Phase::Failed => {}
        }
        self.last_ts = Some(ts);
        Ok(self.progress(&obs, hint, pointing, direction, ts, t0))
    }

    fn progress(&self, obs: &super::Observation, hint: String, pointing: Option<usize>, direction: [f32; 2], ts: f64, t0: f64) -> Progress {
        Progress {
            phase: self.phase,
            hint,
            segments: self.segments.clone(),
            coverage: self.coverage(),
            pointing,
            direction,
            found: obs.found,
            faces: obs.faces,
            bbox: obs.bbox,
            outline: obs.outline.clone(),
            pose: obs.pose,
            quality: obs.quality.score,
            elapsed_ms: ts - self.start.unwrap_or(ts),
            ms: crate::now() - t0,
        }
    }

    /// The homography residual of each turned frame against the reference,
    /// in canonical centimetres, with the frame's angle off neutral.
    pub fn planarity_residuals(&self) -> Vec<(f32, f32)> {
        let Some(r) = &self.reference else { return Vec::new() };
        self.samples
            .iter()
            .filter_map(|s| {
                let mag = (s.dir[0].powi(2) + s.dir[1].powi(2)).sqrt();
                if mag < self.config.min_angle * 0.7 {
                    return None;
                }
                let h = fit_homography(&r.rigid, &s.rigid)?;
                let rms = homography_rms(&h, &r.rigid, &s.rigid) as f32;
                Some((rms / s.pose.scale.max(1e-3), mag))
            })
            .collect()
    }

    /// The landmark-only planarity: the median of the upper half of the
    /// landmark homography residuals (canonical cm). A diagnostic: the
    /// landmark model's face prior makes it weak against tilted prints.
    pub fn planarity(&self) -> Option<f32> {
        upper_median(self.planarity_residuals().into_iter().map(|x| x.0).collect())
    }

    /// The texture parallax score: the median of the upper half of the
    /// measured turned frames' parallax (share of the interocular distance).
    pub fn parallax(&self) -> Option<f32> {
        upper_median(self.parallax.iter().map(|x| x.0).collect())
    }

    pub fn parallax_samples(&self) -> &[(f32, f32)] {
        &self.parallax
    }

    /// The screen direction of each parallax sample (degrees right, up).
    pub fn parallax_directions(&self) -> &[[f32; 2]] {
        &self.parallax_dirs
    }

    /// The passive live probability of each sampled frame.
    pub fn antispoof_samples(&self) -> &[f32] {
        &self.spoof
    }

    /// The share of texture matches off the best homography, per measured frame.
    pub fn outlier_samples(&self) -> &[f32] {
        &self.outliers
    }

    fn best(&self) -> Option<&Kept> {
        self.start_kept.iter().chain(self.finish_kept.iter()).max_by(|a, b| a.quality.total_cmp(&b.quality))
    }

    pub fn result(&self, engine: &FaceEngine) -> LivenessResult {
        let c = &self.config;
        let completed = self.phase == Phase::Done;
        let mut checks = Vec::new();
        let coverage = self.coverage();
        checks.push(Check {
            name: "coverage",
            passed: coverage >= c.coverage - 1e-6,
            required: true,
            score: coverage,
            threshold: c.coverage,
            detail: format!("{} of {} segments", self.segments.iter().filter(|s| **s).count(), self.segments.len()),
        });
        let par = self.parallax();
        let planar = self.planarity();
        checks.push(Check {
            name: "3d_motion",
            passed: par.is_some_and(|p| p >= c.min_parallax),
            required: true,
            score: par.unwrap_or(0.0),
            threshold: c.min_parallax,
            detail: match par {
                Some(p) => format!(
                    "the face's texture departs from a plane by {:.1}% of the eye distance over {} turned frames (landmarks alone: {:.2} cm)",
                    p * 100.0,
                    self.parallax.len(),
                    planar.unwrap_or(0.0)
                ),
                None => "not enough turned frames".into(),
            },
        });
        if engine.antispoof.is_some() {
            // Every sampled near-frontal frame must look live: an attack has
            // only to look live on average, so the weakest frame decides.
            let mean = if self.spoof.is_empty() { 0.0 } else { self.spoof.iter().sum::<f32>() / self.spoof.len() as f32 };
            let min = self.spoof.iter().copied().fold(f32::INFINITY, f32::min);
            let min = if self.spoof.is_empty() { 0.0 } else { min };
            checks.push(Check {
                name: "antispoof",
                passed: !self.spoof.is_empty() && min >= c.min_antispoof,
                required: true,
                score: min,
                threshold: c.min_antispoof,
                detail: format!("lowest live probability over {} sampled frames (mean {:.2})", self.spoof.len(), mean),
            });
        }
        let continuity_ok = self.jumps == 0 && self.max_gap_ms <= 1500.0 && self.non_monotonic == 0 && self.multi_face <= 1;
        checks.push(Check {
            name: "continuity",
            passed: continuity_ok,
            required: true,
            score: if continuity_ok { 1.0 } else { 0.0 },
            threshold: 1.0,
            detail: format!(
                "{} jumps, longest gap {:.0} ms, {} out-of-order timestamps, {} frames with several faces",
                self.jumps, self.max_gap_ms, self.non_monotonic, self.multi_face
            ),
        });
        if engine.recogniser.is_some() {
            let start = self.start_kept.iter().max_by(|a, b| a.quality.total_cmp(&b.quality));
            let finish = self.finish_kept.iter().max_by(|a, b| a.quality.total_cmp(&b.quality));
            let sim = match (start, finish) {
                (Some(a), Some(b)) if !a.template.is_empty() => Some(recognise::similarity(&a.template, &b.template)),
                _ => None,
            };
            checks.push(Check {
                name: "identity",
                passed: sim.is_some_and(|s| s >= c.min_identity),
                required: true,
                score: sim.unwrap_or(0.0),
                threshold: c.min_identity,
                detail: "similarity of the face before and after the sweep".into(),
            });
        }
        checks.push(Check {
            name: "blink",
            passed: self.blinks > 0,
            required: c.require_blink,
            score: self.blinks as f32,
            threshold: 1.0,
            detail: format!("{} blinks", self.blinks),
        });
        let duration = match (self.start, self.done_ts.or(self.last_ts)) {
            (Some(a), Some(b)) => b - a,
            _ => 0.0,
        };
        let required: Vec<&Check> = checks.iter().filter(|k| k.required).collect();
        let passed = completed && required.iter().all(|k| k.passed);
        let score = required
            .iter()
            .map(|k| if k.threshold > 0.0 { (k.score / k.threshold).min(2.0) } else { 2.0 })
            .fold(2.0f32, f32::min);
        let mut reasons: Vec<String> = required.iter().filter(|k| !k.passed).map(|k| format!("{} failed: {}", k.name, k.detail)).collect();
        if !completed {
            reasons.insert(0, format!("not completed (phase {:?})", self.phase).to_lowercase());
        }
        let best = self.best();
        // The template: the mean of the best start and finish templates.
        let mut template: Vec<f32> = Vec::new();
        let mut kept: Vec<&Kept> = self.start_kept.iter().chain(self.finish_kept.iter()).filter(|k| !k.template.is_empty()).collect();
        kept.sort_by(|a, b| b.quality.total_cmp(&a.quality));
        for k in kept.iter().take(3) {
            if template.is_empty() {
                template = vec![0.0; k.template.len()];
            }
            for (t, v) in template.iter_mut().zip(&k.template) {
                *t += v;
            }
        }
        let n = template.iter().map(|x| x * x).sum::<f32>().sqrt();
        if n > 0.0 {
            for t in template.iter_mut() {
                *t /= n;
            }
        }
        LivenessResult {
            passed,
            completed,
            score,
            checks,
            quality: best.map(|b| b.face_quality.clone()),
            best_frame: best.map(|b| Portrait { width: PORTRAIT_W as u32, height: PORTRAIT_H as u32, rgba: b.portrait.clone() }),
            aligned: best.filter(|b| !b.aligned.is_empty()).map(|b| Portrait { width: 112, height: 112, rgba: b.aligned.clone() }),
            template,
            model: engine.recogniser_name.clone(),
            duration_ms: duration,
            frames: self.frames,
            frames_with_face: self.with_face,
            segments: self.segments.clone(),
            reasons,
        }
    }
}

/// An upright head-and-shoulders crop around the face, 240 × 300.
fn portrait(frame: &Frame, points: &[[f32; 3]]) -> Vec<u8> {
    let b = mesh::bbox(points);
    let side = b[2].max(b[3]) * 1.6;
    let cx = b[0] + b[2] / 2.0;
    let cy = b[1] + b[3] / 2.0 - b[3] * 0.05;
    let k = side / PORTRAIT_W as f32;
    let h = PORTRAIT_H as f32 * k;
    let map = image::Affine([k, 0.0, cx - side / 2.0, 0.0, k, cy - h / 2.0]);
    image::warp_rgba(frame, &map, PORTRAIT_W, PORTRAIT_H)
}
