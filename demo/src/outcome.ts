// What a finished scan hands to the results screen: the captured data, and
// how it was captured (for the Metadata section).
import type { AddressCaptured } from "./AddressCapture";
import type { DocumentFace, FaceFlowId, FaceMatch } from "./FaceFlow";
import type { LivenessOutcome } from "./FaceLiveness";
import type { PhotoFace } from "./face-types";
import type { Captured } from "./IdCapture";
import type { ScannerId } from "./scanners";
import type { LabelledField } from "./types";

/** What the worker reported once the wasm and the models had loaded. */
export interface ReadyInfo {
  ocr: boolean;
  tagger: boolean;
  loadMs: number;
  threads: number;
}

export interface CaptureMeta {
  source: "camera" | "photo";
  /** From the camera opening (or the photo being chosen) to the capture. */
  captureMs: number;
  /** Frames analysed, and how many of them were OCR passes. */
  frames: number;
  ocrFrames?: number;
  /** Median milliseconds per fast pass and per OCR pass. */
  fastMs?: number | null;
  ocrMs?: number | null;
}

export interface SeenCode {
  format: string;
  text: string;
  /** Frames the code was read in. */
  count: number;
}

export type Outcome =
  | { kind: "id"; scanner: ScannerId; captured: Captured[]; meta: CaptureMeta }
  | {
      kind: "face";
      flow: FaceFlowId;
      /** The live capture; null for "Test with a photo", which cannot show liveness. */
      liveness: LivenessOutcome | null;
      match?: FaceMatch | null;
      document?: DocumentFace;
      /** "Test with a photo": the photos' faces. */
      photos?: { label: string; imageUrl: string; face: PhotoFace }[];
      meta: CaptureMeta;
    }
  | { kind: "address"; captured: AddressCaptured; meta: CaptureMeta }
  | {
      kind: "barcodes";
      labels: boolean;
      /** Confirmed codes only. */
      barcodes: SeenCode[];
      fields: LabelledField[];
      /** A still of the frame the set was captured from. */
      imageUrl: string | null;
      /** Why the scan finished: which rule fired, or the staff member did. */
      finishedBy: string;
      meta: CaptureMeta;
    };

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}
