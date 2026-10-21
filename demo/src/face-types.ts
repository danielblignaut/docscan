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
  real: number;
  print: number;
  replay: number;
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

export function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / Math.max(1e-12, Math.sqrt(na * nb));
}
