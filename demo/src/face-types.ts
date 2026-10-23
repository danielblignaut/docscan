import type { Enrolment } from "./face-store";

// The JSON shapes docscan's FaceScanner returns (docscan/src/face/).

export interface Pose {
  yaw: number;
  pitch: number;
  roll: number;
  forward: [number, number, number];
  scale: number;
}

export interface FaceQuality {
  interocular_px: number;
  brightness: number;
  evenness: number;
  saturated: number;
  sharpness: number;
  eyes_open: number;
  off_frontal: number;
  roll: number;
  score: number;
  problems: string[];
}

export type LivenessPhase = "centre" | "sweep" | "finish" | "done" | "failed";

export interface LivenessProgress {
  phase: LivenessPhase;
  hint: string;
  segments: boolean[];
  coverage: number;
  pointing: number | null;
  direction: [number, number];
  found: boolean;
  faces: number | null;
  bbox: [number, number, number, number];
  outline: [number, number][];
  pose: Pose;
  quality: number;
  elapsed_ms: number;
  ms: number;
}

export interface Check {
  name: string;
  passed: boolean;
  required: boolean;
  score: number;
  threshold: number;
  detail: string;
}

export interface Portrait {
  width: number;
  height: number;
  rgba: Uint8Array;
}

export interface LivenessResult {
  passed: boolean;
  completed: boolean;
  score: number;
  checks: Check[];
  quality: FaceQuality | null;
  best_frame: Portrait | null;
  aligned: Portrait | null;
  template: number[];
  model: string;
  duration_ms: number;
  frames: number;
  frames_with_face: number;
  segments: boolean[];
  reasons: string[];
}

export interface SpoofScore {
  /** Calibrated live probability: 0.5 is the balanced decision. */
  real: number;
  print: number;
  replay: number;
  /** The models' uncalibrated live probability. */
  raw_real: number;
}

export interface PhotoFace {
  found: boolean;
  faces: number;
  detection_score: number;
  presence: number;
  bbox: [number, number, number, number];
  pose: Pose;
  quality: FaceQuality;
  aligned: Uint8Array;
  template: number[];
  model: string;
  antispoof: SpoofScore | null;
  ms: number;
}

/** A Portrait (RGBA bytes) as a PNG data URL for an <img>. */
export function portraitUrl(p: { width: number; height: number; rgba: Uint8Array }): string {
  const c = document.createElement("canvas");
  c.width = p.width;
  c.height = p.height;
  c.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(p.rgba), p.width, p.height), 0, 0);
  return c.toDataURL("image/png");
}

/** Invalid templates produce NaN, which cannot pass a match threshold. */
export function cosine(a: number[], b: number[]): number {
  if (!a.length || a.length !== b.length || !a.every(Number.isFinite) || !b.every(Number.isFinite)) return NaN;
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (!(na > 0 && nb > 0) || !Number.isFinite(na * nb)) return NaN;
  return Math.max(-1, Math.min(1, dot / Math.sqrt(na * nb)));
}

export interface FaceMatch {
  similarity: number;
  threshold: number;
  matched: boolean;
  /** What the live face was compared with. */
  against: string;
  others?: { label: string; similarity: number }[];
}

/** Only templates from the same recognition model share a feature space. */
export function matchEnrolments(template: number[], model: string, enrolments: Enrolment[], threshold: number): FaceMatch | null {
  if (!model || !Number.isFinite(threshold)) return null;
  const scored = enrolments
    .filter((e) => e.model === model)
    .map((e) => ({ label: e.label, similarity: cosine(template, e.template) }))
    .filter((e) => Number.isFinite(e.similarity))
    .sort((a, b) => b.similarity - a.similarity);
  if (!scored.length) return null;
  const best = scored[0];
  return { similarity: best.similarity, threshold, matched: best.similarity >= threshold, against: best.label, others: scored.slice(1) };
}

/** The threshold belongs to the supplied model and document-photo benchmark. */
export function documentMatch(template: number[], model: string, doc: PhotoFace, threshold: number): FaceMatch | null {
  if (!doc.found || !model || doc.model !== model || !Number.isFinite(threshold)) return null;
  const similarity = cosine(template, doc.template);
  if (!Number.isFinite(similarity)) return null;
  return { similarity, threshold, matched: similarity >= threshold, against: "the identity document's photo" };
}

/** A verification result requires both live capture and a positive comparison. */
export function verificationPassed(livenessPassed: boolean, match: FaceMatch | null): boolean {
  return livenessPassed && match?.matched === true;
}
