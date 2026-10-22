// The models the demo can load, with their download size and an estimate of
// the memory they need, and the choice of extractor for this device.
//
// The shape follows RunAnywhere's web model catalogue (an entry per model with
// download and memory sizes, and capability-gated routing; see the README):
// the idea only, none of its code. Every file is served from this origin.

export interface CatalogueEntry {
  id: string;
  /** Files under /models/. */
  files: string[];
  downloadMb: number;
  /**
   * Peak memory while it runs, MB. Measured: the wasm heap after reading a
   * page in headless Chrome (README, Proof of address) for OCR + tagger.
   */
  memoryMb: number;
  required: boolean;
  licence: string;
}

export const CATALOGUE: CatalogueEntry[] = [
  {
    id: "ocrs",
    files: ["text-detection.rten", "text-recognition.rten", "text-detection-page.onnx"],
    downloadMb: 14.7,
    memoryMb: 220,
    required: true,
    licence: "ocrs-models terms (github.com/robertknight/ocrs-models)",
  },
  {
    id: "poa-tagger",
    files: ["poa-tagger.onnx"],
    downloadMb: 6.0,
    memoryMb: 10,
    required: false,
    licence: "MIT OR Apache-2.0, trained here on synthetic data only",
  },
];

export type Extractor = "tagger" | "rules";

/**
 * Which extractor reads the page: the one chosen on the home screen (or by
 * `?method=`) when it is not "auto"; otherwise the tagger when it loaded, and
 * the rules when it did not or when the device reports under 1 GB of memory
 * (`navigator.deviceMemory`, Chromium only; Safari does not report it, and
 * gets the tagger, which adds ~10 MB to OCR's ~220 MB).
 */
export function chooseExtractor(taggerLoaded: boolean, asked: Extractor | "auto" = "auto"): Extractor {
  if (asked === "rules" || (asked === "tagger" && taggerLoaded)) return asked;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (!taggerLoaded || (memory !== undefined && memory < 1)) return "rules";
  return "tagger";
}

export const catalogueEntry = (id: string) => CATALOGUE.find((e) => e.id === id)!;
