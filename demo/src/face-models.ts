// The face models the demo serves (under /models/face/, copied there by
// scripts/fetch-models.sh from models/face/), with their sizes and licences.
// face/MODELS.md has the full table, the training data where known, and the
// models that were benchmarked but are not shipped (research-only weights).

export const FACE_MODELS = {
  detector: "face_detector.onnx",
  mesh: "face_landmarks_detector.onnx",
  antispoof: "minifasnet.onnx",
};

/**
 * The recognition model: OpenCV's SFace (Apache-2.0 weights; the training
 * data is not documented by OpenCV, see face/MODELS.md), its weights stored
 * as int8 here (9.9 MB instead of 38.7 MB; float32 arithmetic).
 */
export const RECOGNISER = { file: "sface_int8.onnx", name: "sface_int8", kind: "sface" } as const;

export const FACE_DOWNLOAD_MB = 0.4 + 4.9 + 3.5 + 9.9;

export const FACE_LICENCES = [
  "BlazeFace short-range and Face Mesh V2: Apache-2.0 (Google MediaPipe)",
  "MiniFASNet V2 + V1SE: Apache-2.0 (Minivision Silent-Face-Anti-Spoofing)",
  "SFace: Apache-2.0 (OpenCV Zoo); training data undocumented",
];

/**
 * The cosine-similarity threshold for a live face against an identity
 * document's photo: lower than the live-to-live one, because a printed,
 * small, often greyscale ID photo scores lower for the same person. Set from
 * the DEV split of the document-to-live eval (face/RESULTS.md).
 */
export const DOC_THRESHOLD = 0.356;
