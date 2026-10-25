// What a finished scan hands to the results screen: the captured data, and
// how it was captured (for the Metadata section).
import type { DocumentEvidence, InputReference } from "./document-review";
import type { TextResult } from "./TextCapture";
import type { AddressCaptured } from "./AddressCapture";
import type { DocumentFace, FaceFlowId, FaceMatch } from "./FaceFlow";
import type { LivenessOutcome } from "./FaceLiveness";
import type { PhotoFace } from "./face-types";
import type { Captured } from "./IdCapture";
import type { ScannerId } from "./scanners";
import type { FinancialCapturedPage } from "./financial-data";
import type { FinancialTablesReport, FinancialTablesOptions } from "./financial-tables";
import type { ItemRegion, Divider } from "./item-grouping";
import type { Gs1Result } from "./gs1";
import type { LabelledField } from "./types";

/** What the worker reported once the wasm and the models had loaded. */
export interface ReadyInfo {
  ocr: boolean;
  tagger: boolean;
  loadMs: number;
  threads: number;
}

export interface CaptureMeta {
  source: "camera" | "photo" | "pdf";
  input?: InputReference;
  /** From the camera opening (or the photo being chosen) to the capture. */
  captureMs: number;
  /** Frames analysed, and how many of them were OCR passes. */
  frames: number;
  ocrFrames?: number;
  /** Median milliseconds per fast pass and per OCR pass. */
  fastMs?: number | null;
  ocrMs?: number | null;
  /** Allocated wasm linear memory after the read (not total browser RAM). */
  memoryBytes?: number;
}

export interface SeenCode {
  symbology_identifier?: string | null;
  points?: [number, number][];
  gs1?: Gs1Result;
  format: string;
  text: string;
  /** Frames the code was read in. */
  count: number;
}

export type Outcome = OutcomeData & { documentEvidence?: DocumentEvidence; operationId?: string };

export type OutcomeData =
  | { kind: "batch"; scanner: ScannerId; pages: Outcome[]; meta: CaptureMeta }
  | { kind: "file_error"; message: string; severity?: "warning" | "error"; meta: CaptureMeta }
  | { kind: "financial"; pages: FinancialCapturedPage[]; report: FinancialTablesReport; options: FinancialTablesOptions; incompleteInputs: number; meta: CaptureMeta }
  | { kind: "text"; result: TextResult; imageUrl: string; meta: CaptureMeta }
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
      imageSize?: [number, number];
      itemMode?: boolean;
      droppedObservations?: SeenCode[];
      itemRegions?: ItemRegion[];
      itemDividers?: Divider[];
      /** Observations from the retained image only, not positions mixed across camera frames. */
      observations?: SeenCode[];
      labelReader?: "detailed" | "fast";
      labelReadError?: string;
      labelReadWarning?: string;
      labelReadMs?: number;
      labelReadStatus?: "pending" | "complete" | "failed" | "cancelled";
      /** Confirmed codes only. */
      barcodes: SeenCode[];
      fields: LabelledField[];
      /** A still of the frame the set was captured from. */
      imageUrl: string | null;
      /** Retained locally for explicit printed-label reading; excluded from JSON reports. */
      blob?: Blob;
      /** Why the scan finished: which rule fired, or the staff member did. */
      finishedBy: string;
      meta: CaptureMeta;
    };

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}
